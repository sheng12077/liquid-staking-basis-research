from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import polars as pl


@dataclass(frozen=True)
class SeriesSpec:
    series_id: str
    kind: str
    required: bool


SERIES = (
    SeriesSpec("eth_spot_bars", "bars", True),
    SeriesSpec("eth_perpetual_bars", "bars", True),
    SeriesSpec("eth_mark_bars", "bars", True),
    SeriesSpec("eth_index_bars", "bars", False),
    SeriesSpec("eth_premium_bars", "bars", False),
    SeriesSpec("eth_funding", "funding", True),
)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _missing_ranges(missing: list[datetime], step: timedelta) -> list[dict[str, object]]:
    if not missing:
        return []
    ranges: list[dict[str, object]] = []
    start = previous = missing[0]
    for value in missing[1:]:
        if value - previous != step:
            ranges.append(
                {
                    "start": _iso(start),
                    "end": _iso(previous),
                    "count": int((previous - start) / step) + 1,
                }
            )
            start = value
        previous = value
    ranges.append(
        {
            "start": _iso(start),
            "end": _iso(previous),
            "count": int((previous - start) / step) + 1,
        }
    )
    return ranges


def _load_series(path: Path, columns: list[str]) -> pl.DataFrame:
    files = sorted(path.glob("*.parquet"))
    if not files:
        raise ValueError(f"no Parquet files found in {path}")
    return pl.scan_parquet(files).select(columns).sort("timestamp").collect()


def audit_hourly_bars(
    path: Path, start: datetime, end_exclusive: datetime
) -> dict[str, object]:
    frame = _load_series(path, ["timestamp", "open", "high", "low", "close"])
    timestamps = frame.get_column("timestamp").to_list()
    observed = set(timestamps)
    expected: list[datetime] = []
    cursor = start
    while cursor < end_exclusive:
        expected.append(cursor)
        cursor += timedelta(hours=1)
    missing = [timestamp for timestamp in expected if timestamp not in observed]
    in_scope = frame.filter(
        (pl.col("timestamp") >= start) & (pl.col("timestamp") < end_exclusive)
    )
    invalid_ohlc = in_scope.filter(
        (pl.col("high") < pl.max_horizontal("open", "close", "low"))
        | (pl.col("low") > pl.min_horizontal("open", "close", "high"))
    ).height
    nonpositive = in_scope.filter(
        pl.any_horizontal(
            pl.col("open") <= 0,
            pl.col("high") <= 0,
            pl.col("low") <= 0,
            pl.col("close") <= 0,
        )
    ).height
    return {
        "file_count": len(list(path.glob("*.parquet"))),
        "row_count": frame.height,
        "in_scope_rows": in_scope.height,
        "first_timestamp": _iso(timestamps[0]),
        "last_timestamp": _iso(timestamps[-1]),
        "duplicate_timestamps": frame.height - frame.get_column("timestamp").n_unique(),
        "expected_hours": len(expected),
        "missing_hours": len(missing),
        "coverage": (len(expected) - len(missing)) / len(expected),
        "missing_ranges": _missing_ranges(missing, timedelta(hours=1)),
        "invalid_ohlc_rows": invalid_ohlc,
        "nonpositive_price_rows": nonpositive,
    }


def audit_funding(path: Path, start: datetime, end_exclusive: datetime) -> dict[str, object]:
    frame = _load_series(path, ["timestamp", "funding_interval_hours", "funding_rate"])
    in_scope = frame.filter(
        (pl.col("timestamp") >= start) & (pl.col("timestamp") < end_exclusive)
    )
    timestamps = in_scope.get_column("timestamp").to_list()
    intervals = in_scope.get_column("funding_interval_hours").to_list()
    interval_counts = (
        in_scope.group_by("funding_interval_hours")
        .len()
        .sort("funding_interval_hours")
        .to_dicts()
    )
    mismatches = 0
    maximum_gap_hours = 0.0
    for index in range(1, len(timestamps)):
        gap_hours = (timestamps[index] - timestamps[index - 1]).total_seconds() / 3600
        maximum_gap_hours = max(maximum_gap_hours, gap_hours)
        if abs(gap_hours - intervals[index]) > 1 / 3600:
            mismatches += 1
    return {
        "file_count": len(list(path.glob("*.parquet"))),
        "row_count": frame.height,
        "in_scope_rows": in_scope.height,
        "first_timestamp": _iso(timestamps[0]),
        "last_timestamp": _iso(timestamps[-1]),
        "duplicate_timestamps": in_scope.height
        - in_scope.get_column("timestamp").n_unique(),
        "interval_counts": interval_counts,
        "interval_mismatches": mismatches,
        "maximum_gap_hours": maximum_gap_hours,
        "null_or_nonfinite_rates": in_scope.filter(
            pl.col("funding_rate").is_null() | ~pl.col("funding_rate").is_finite()
        ).height,
    }


def audit_onchain_alignment(
    daily_state_path: Path, start: datetime, end_exclusive: datetime
) -> dict[str, object]:
    frame = pl.read_parquet(daily_state_path).filter(
        (pl.col("target_timestamp") >= int(start.timestamp()))
        & (pl.col("target_timestamp") < int(end_exclusive.timestamp()))
    )
    target = frame.get_column("target_timestamp")
    block = frame.get_column("block_timestamp")
    following = frame.get_column("following_block_timestamp")
    lags = target - block
    maximum_lag = lags.max()
    if not isinstance(maximum_lag, int):
        raise ValueError("daily state contains no integer block lag")
    return {
        "aligned_daily_rows": frame.height,
        "first_observation_date": frame.get_column("observation_date").min(),
        "last_observation_date": frame.get_column("observation_date").max(),
        "selected_block_strictly_before_target": bool((block < target).all()),
        "following_block_at_or_after_target": bool((following >= target).all()),
        "maximum_selected_block_lag_seconds": maximum_lag,
        "known_cex_bar_rule": "use the prior completed hourly bar (23:00 UTC bar)",
        "earliest_conservative_execution_rule": (
            "execute no earlier than the close of the 00:00 UTC bar, after the on-chain "
            "snapshot is observable"
        ),
    }


def audit_daily_bar_alignment(
    bar_path: Path,
    daily_state_path: Path,
    start: datetime,
    end_exclusive: datetime,
) -> dict[str, object]:
    observed = set(_load_series(bar_path, ["timestamp"]).get_column("timestamp").to_list())
    daily = pl.read_parquet(
        daily_state_path, columns=["observation_date", "target_timestamp"]
    ).filter(
        (pl.col("target_timestamp") >= int(start.timestamp()))
        & (pl.col("target_timestamp") < int(end_exclusive.timestamp()))
    )
    targets = [datetime.fromtimestamp(value, UTC) for value in daily["target_timestamp"]]
    prior_missing = [target for target in targets if target - timedelta(hours=1) not in observed]
    execution_missing = [target for target in targets if target not in observed]
    return {
        "prior_completed_bar_missing_count": len(prior_missing),
        "prior_completed_bar_missing_observations": [_iso(value) for value in prior_missing],
        "conservative_execution_bar_missing_count": len(execution_missing),
        "conservative_execution_bar_missing_observations": [
            _iso(value) for value in execution_missing
        ],
    }


def audit_cex_coverage(
    data_root: Path,
    start: datetime,
    end_exclusive: datetime,
) -> dict[str, object]:
    series_root = data_root / "canonical" / "binance_core_audit" / "series"
    daily_state_path = (
        data_root
        / "canonical"
        / "ethereum"
        / "lido_curve_daily_state_v1"
        / "daily_state.parquet"
    )
    results: dict[str, dict[str, object]] = {}
    for spec in SERIES:
        path = series_root / spec.series_id
        detail = (
            audit_hourly_bars(path, start, end_exclusive)
            if spec.kind == "bars"
            else audit_funding(path, start, end_exclusive)
        )
        detail["spec"] = asdict(spec)
        if spec.kind == "bars":
            detail["daily_alignment"] = audit_daily_bar_alignment(
                path, daily_state_path, start, end_exclusive
            )
        results[spec.series_id] = detail

    alignment = audit_onchain_alignment(
        daily_state_path,
        start,
        end_exclusive,
    )
    required_series = {spec.series_id for spec in SERIES if spec.required}
    required_passed = all(
        result["duplicate_timestamps"] == 0
        and result.get("invalid_ohlc_rows", 0) == 0
        and result.get("nonpositive_price_rows", 0) == 0
        and result.get("interval_mismatches", 0) == 0
        for series_id, result in results.items()
        if series_id in required_series
    )
    spot_coverage = cast(float, results["eth_spot_bars"]["coverage"])
    perpetual_coverage = cast(float, results["eth_perpetual_bars"]["coverage"])
    mark_coverage = cast(float, results["eth_mark_bars"]["coverage"])
    return {
        "scope": {
            "start": _iso(start),
            "end_exclusive": _iso(end_exclusive),
            "performance_metrics_computed": False,
        },
        "series": results,
        "onchain_alignment": alignment,
        "required_integrity_checks_passed": required_passed,
        "research_ready": required_passed
        and spot_coverage >= 0.999
        and perpetual_coverage == 1.0
        and mark_coverage >= 0.995,
    }
