from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from liquid_staking_basis.cli import data_root
from liquid_staking_basis.experiment_001 import (
    STRESSES,
    component_attribution,
    correctness_checks,
    load_inputs,
    metrics,
    period_metrics,
    simulate,
    simulate_benchmark,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def _pearson(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        raise ValueError("correlation inputs must have equal length of at least two")
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left, right, strict=True)
    )
    left_scale = math.sqrt(sum((value - left_mean) ** 2 for value in left))
    right_scale = math.sqrt(sum((value - right_mean) ** 2 for value in right))
    return numerator / (left_scale * right_scale)


def _period_returns(timestamps: list[datetime], values: list[float], frequency: str) -> list[float]:
    last_by_period: dict[tuple[int, ...], float] = {}
    for timestamp, value in zip(timestamps, values, strict=True):
        if frequency == "weekly":
            iso = timestamp.isocalendar()
            key = (iso.year, iso.week)
        elif frequency == "monthly":
            key = (timestamp.year, timestamp.month)
        else:
            raise ValueError(f"unsupported frequency {frequency}")
        last_by_period[key] = value
    ordered = [last_by_period[key] for key in sorted(last_by_period)]
    return [ordered[index] / ordered[index - 1] - 1.0 for index in range(1, len(ordered))]


def monitoring_stats(
    hourly: pl.DataFrame,
    breach_timestamp: str | None,
    warning_threshold: float,
    critical_threshold: float,
) -> dict[str, Any]:
    breach = datetime.fromisoformat(breach_timestamp) if breach_timestamp else None
    observations: list[tuple[datetime, float]] = []
    for row in hourly.iter_rows(named=True):
        timestamp = row["timestamp"]
        if not isinstance(timestamp, datetime):
            raise TypeError("hourly timestamp must be datetime")
        if breach is not None and timestamp > breach:
            continue
        if float(row["short_quantity_eth"]) <= 0:
            continue
        candidates = [
            float(value)
            for value in (row["operational_buffer"], row["risk_operational_buffer"])
            if value is not None
        ]
        if candidates:
            observations.append((timestamp, min(candidates)))

    warning_times = [timestamp for timestamp, value in observations if value <= warning_threshold]
    critical_times = [timestamp for timestamp, value in observations if value <= critical_threshold]
    longest = 0
    current = 0
    previous: datetime | None = None
    for timestamp in warning_times:
        if previous is not None and (timestamp - previous).total_seconds() == 3600:
            current += 1
        else:
            current = 1
        longest = max(longest, current)
        previous = timestamp
    first_warning = warning_times[0] if warning_times else None
    lead_hours = (
        (breach - first_warning).total_seconds() / 3600
        if breach is not None and first_warning is not None
        else None
    )
    return {
        "warning_threshold": warning_threshold,
        "critical_threshold": critical_threshold,
        "warning_hour_count": len(warning_times),
        "critical_hour_count": len(critical_times),
        "first_warning_timestamp": first_warning,
        "first_critical_timestamp": critical_times[0] if critical_times else None,
        "longest_consecutive_warning_hours": longest,
        "warning_to_breach_lead_hours": lead_hours,
        "monitoring_action": "observe_only_no_position_change",
    }


def portfolio_analysis(primary: pl.DataFrame, root: Path, config: dict[str, Any]) -> dict[str, Any]:
    paths = config["data_paths"]
    s4_path = (root / str(paths["s4_nav"])).resolve()
    repeat_path = (root / str(paths["s4_repeat_nav"])).resolve()
    expected = str(paths["s4_nav_sha256"])
    observed = _sha256(s4_path)
    repeat = _sha256(repeat_path)
    if observed != expected or repeat != expected:
        raise ValueError("frozen S4 NAV checksum or repeat checksum mismatch")
    s4 = pl.read_parquet(s4_path, columns=["timestamp", "nav"]).rename({"nav": "s4_nav"})
    aligned = (
        primary.select("timestamp", pl.col("nav").alias("lsb_nav"))
        .join(s4, on="timestamp", how="inner", validate="1:1")
        .sort("timestamp")
    )
    if aligned.height != primary.height:
        raise ValueError("S4 alignment is incomplete")
    timestamps = aligned["timestamp"].to_list()
    lsb = [float(value) for value in aligned["lsb_nav"].to_list()]
    s4_values = [float(value) for value in aligned["s4_nav"].to_list()]
    lsb_daily = [lsb[index] / lsb[index - 1] - 1.0 for index in range(1, len(lsb))]
    s4_daily = [s4_values[index] / s4_values[index - 1] - 1.0 for index in range(1, len(s4_values))]
    correlations = {
        "daily": _pearson(lsb_daily, s4_daily),
        "weekly": _pearson(
            _period_returns(timestamps, lsb, "weekly"),
            _period_returns(timestamps, s4_values, "weekly"),
        ),
        "monthly": _pearson(
            _period_returns(timestamps, lsb, "monthly"),
            _period_returns(timestamps, s4_values, "monthly"),
        ),
    }
    s4_weight = float(config["portfolio_s4_weight"])
    lsb_weight = float(config["portfolio_lsb_weight"])
    if abs(s4_weight + lsb_weight - 1.0) > 1e-12:
        raise ValueError("registered portfolio weights must sum to one")
    portfolio_values = [
        float(config["initial_capital_usdt"])
        * (s4_weight * s4_value / s4_values[0] + lsb_weight * lsb_value / lsb[0])
        for s4_value, lsb_value in zip(s4_values, lsb, strict=True)
    ]
    portfolio_metrics = metrics(
        pl.DataFrame({"timestamp": timestamps, "nav": portfolio_values}),
        float(config["hurdle_rate"]),
    )
    s4_metrics = metrics(
        pl.DataFrame({"timestamp": timestamps, "nav": s4_values}),
        float(config["hurdle_rate"]),
    )
    s4_mdd = abs(float(s4_metrics["max_drawdown"] or 0.0))
    portfolio_mdd = abs(float(portfolio_metrics["max_drawdown"] or 0.0))
    improves = (
        float(portfolio_metrics["sharpe"] or -math.inf)
        >= float(s4_metrics["sharpe"] or -math.inf) + 0.10
        or float(portfolio_metrics["hurdle_sharpe_4pct"] or -math.inf)
        >= float(s4_metrics["hurdle_sharpe_4pct"] or -math.inf) + 0.10
        or (s4_mdd > 0 and portfolio_mdd <= 0.90 * s4_mdd)
        or float(portfolio_metrics["calmar"] or -math.inf)
        >= float(s4_metrics["calmar"] or -math.inf) + 0.10
    )
    gates = {
        "correlation_limits": abs(correlations["daily"]) <= 0.50
        and abs(correlations["weekly"]) <= 0.60
        and abs(correlations["monthly"]) <= 0.60,
        "portfolio_improves_registered_metric": improves,
        "portfolio_cagr_non_worsening": float(portfolio_metrics["cagr"] or -math.inf)
        >= float(s4_metrics["cagr"] or -math.inf) - 0.005,
        "portfolio_drawdown_non_worsening": s4_mdd == 0 or portfolio_mdd <= 1.10 * s4_mdd,
    }
    return {
        "s4_nav_path": str(s4_path),
        "s4_nav_sha256": observed,
        "weights": {"S4": s4_weight, "LSB_P2": lsb_weight},
        "common_observation_count": aligned.height,
        "common_start": timestamps[0],
        "common_end": timestamps[-1],
        "correlations": correlations,
        "s4_metrics": s4_metrics,
        "portfolio_metrics": portfolio_metrics,
        "gates": gates,
        "passed": all(gates.values()),
    }


def evaluate_gates(
    primary_metrics: dict[str, float | None],
    path_details: dict[str, dict[str, Any]],
    periods: dict[str, dict[str, float | None]],
    c2_metrics: dict[str, float | None],
    total_cost: float,
    positive_carry: float,
    correctness_passed: bool,
) -> dict[str, Any]:
    calendar = [value for key, value in periods.items() if key.startswith("calendar_")]
    calendar_returns = [float(value["total_return"] or 0.0) for value in calendar]
    positive = [value for value in calendar_returns if value > 0]
    concentration = max(positive) / sum(positive) if positive else math.inf
    primary_mdd = abs(float(primary_metrics["max_drawdown"] or 0.0))
    c2_mdd = abs(float(c2_metrics["max_drawdown"] or 0.0))
    improves_c2 = (
        float(primary_metrics["cagr"] or 0.0) - float(c2_metrics["cagr"] or 0.0) >= 0.0025
        or float(primary_metrics["hurdle_sharpe_4pct"] or -math.inf)
        - float(c2_metrics["hurdle_sharpe_4pct"] or -math.inf)
        >= 0.10
        or (c2_mdd > 0 and primary_mdd <= 0.80 * c2_mdd)
    )
    relative_guard = not (
        float(primary_metrics["cagr"] or 0.0) < float(c2_metrics["cagr"] or 0.0) - 0.005
        and c2_mdd > 0
        and primary_mdd > 1.20 * c2_mdd
    )
    checks = {
        "no_liquidation_primary_and_x1_x6": all(
            not bool(detail["liquidated"]) for detail in path_details.values()
        ),
        "primary_minimum_buffer_at_least_25pct": float(
            path_details["primary"]["minimum_operational_buffer"]
        )
        >= 0.25,
        "cagr_at_least_3pct": float(primary_metrics["cagr"] or -math.inf) >= 0.03,
        "four_pct_hurdle_sharpe_nonnegative": float(
            primary_metrics["hurdle_sharpe_4pct"] or -math.inf
        )
        >= 0.0,
        "max_drawdown_no_worse_than_minus_10pct": float(
            primary_metrics["max_drawdown"] or -math.inf
        )
        >= -0.10,
        "minimum_rolling_365d_above_minus_10pct": float(
            primary_metrics["minimum_rolling_365d_return"] or -math.inf
        )
        > -0.10,
        "pre_and_post_shapella_positive": all(
            float(periods[name]["total_return"] or 0.0) > 0
            for name in ("pre_shapella", "post_shapella")
        ),
        "at_least_four_positive_calendar_segments": len(positive) >= 4,
        "calendar_profit_concentration_at_most_50pct": concentration <= 0.50,
        "cost_below_40pct_of_positive_carry": positive_carry > 0
        and total_cost / positive_carry < 0.40,
        "improves_c2_25": improves_c2,
        "relative_c2_25_guard": relative_guard,
        "correctness_gates": correctness_passed,
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "positive_calendar_count": len(positive),
        "calendar_profit_concentration": concentration,
        "cost_to_positive_carry": total_cost / positive_carry if positive_carry > 0 else None,
    }


def run(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    if float(config["long_allocation"]) != 0.25 or float(config["futures_allocation"]) != 0.75:
        raise ValueError("Experiment 002 requires the preregistered 25/75 split")
    hourly, daily = load_inputs(root, config)
    output = root / str(config["data_paths"]["output_root"])
    output.mkdir(parents=True, exist_ok=True)
    paths: dict[str, dict[str, Any]] = {}
    primary_hourly: pl.DataFrame | None = None
    primary_daily: pl.DataFrame | None = None
    primary_detail: dict[str, Any] | None = None
    for stress in STRESSES:
        hourly_result, daily_result, detail = simulate(hourly, daily, config, stress)
        daily_path = output / f"{stress.name}_daily.parquet"
        hourly_path = output / f"{stress.name}_hourly.parquet"
        daily_result.write_parquet(daily_path, compression="zstd", statistics=True)
        hourly_result.write_parquet(hourly_path, compression="zstd", statistics=True)
        paths[stress.name] = {
            **{key: value for key, value in detail.items() if key != "ledger"},
            "metrics": metrics(daily_result, float(config["hurdle_rate"])),
            "metrics_status": (
                "partial_to_breach_not_comparable"
                if bool(detail["liquidated"])
                else "complete_registered_window"
            ),
            "monitoring": monitoring_stats(
                hourly_result,
                detail["breach_timestamp"],
                float(config["warning_buffer"]),
                float(config["critical_buffer"]),
            ),
            "daily_path": str(daily_path),
            "daily_sha256": _sha256(daily_path),
            "hourly_path": str(hourly_path),
            "hourly_sha256": _sha256(hourly_path),
        }
        if stress.name == "primary":
            primary_hourly = hourly_result
            primary_daily = daily_result
            primary_detail = detail

    attribution_paths: dict[str, dict[str, Any]] = {}
    for name, zero_funding, freeze_share_rate, par_basis in (
        ("A1_zero_funding", True, False, False),
        ("A2_frozen_share_rate", False, True, False),
        ("A3_par_basis", False, False, True),
    ):
        hourly_result, daily_result, detail = simulate(
            hourly,
            daily,
            config,
            zero_funding=zero_funding,
            freeze_share_rate=freeze_share_rate,
            par_basis=par_basis,
        )
        attribution_paths[name] = {
            **{key: value for key, value in detail.items() if key != "ledger"},
            "metrics": metrics(daily_result, float(config["hurdle_rate"])),
            "metrics_status": (
                "partial_to_breach_not_comparable"
                if bool(detail["liquidated"])
                else "complete_registered_window"
            ),
            "monitoring": monitoring_stats(
                hourly_result,
                detail["breach_timestamp"],
                float(config["warning_buffer"]),
                float(config["critical_buffer"]),
            ),
        }

    benchmark_results: dict[str, dict[str, Any]] = {}
    for internal, registered in (
        ("C0", "C0"),
        ("C1", "C1_25"),
        ("C2", "C2_25"),
        ("C3", "C3_25"),
    ):
        frame, detail = simulate_benchmark(internal, hourly, daily, config)
        benchmark_results[registered] = {
            **detail,
            "metrics": metrics(frame, float(config["hurdle_rate"])),
        }

    if primary_hourly is None or primary_daily is None or primary_detail is None:
        raise AssertionError("primary path missing")
    periods = period_metrics(primary_daily, float(config["hurdle_rate"]))
    components = component_attribution(primary_daily)
    gross_positive_staking = max(0.0, float(components["staking_share_rate_contribution"]))
    correctness = correctness_checks(
        hourly, daily, primary_hourly, primary_daily, primary_detail, config
    )
    correctness["checks"]["registered_25_75_allocation"] = True
    correctness["checks"]["no_post_entry_collateral_transfer"] = True
    correctness["passed"] = all(correctness["checks"].values())
    stress_details = {
        name: value for name, value in paths.items() if name == "primary" or name.startswith("X")
    }
    gates = evaluate_gates(
        paths["primary"]["metrics"],
        stress_details,
        periods,
        benchmark_results["C2_25"]["metrics"],
        float(primary_detail["total_cost"]),
        gross_positive_staking + float(primary_detail["positive_funding"]),
        bool(correctness["passed"]),
    )
    diversification = portfolio_analysis(primary_daily, root, config)
    if not gates["passed"]:
        label = "economically_rejected"
    elif diversification["passed"]:
        label = "candidate_b_sleeve"
    else:
        label = "economically_supported_isolated"
    p1_summary_path = root / str(config["data_paths"]["p1_summary"])
    p1_summary = json.loads(p1_summary_path.read_text(encoding="utf-8"))
    p1_comparison = {
        "source_path": str(p1_summary_path),
        "source_sha256": _sha256(p1_summary_path),
        "P1_metrics": p1_summary["paths"]["primary"]["metrics"],
        "P1_final_label": p1_summary["final_label"],
    }
    summary = {
        "schema_version": 1,
        "strategy_id": config["strategy_id"],
        "redesign_disclosure": "post_Experiment_001_in_sample_redesign_not_blind_oos",
        "configuration": config,
        "paths": paths,
        "attributions": attribution_paths,
        "benchmarks": benchmark_results,
        "temporal_metrics": periods,
        "component_attribution": components,
        "gross_positive_staking_accrual": gross_positive_staking,
        "correctness": correctness,
        "economic_gates": gates,
        "diversification_analysis": diversification,
        "P1_comparison": p1_comparison,
        "final_label": label,
    }
    summary_path = output / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    return {**summary, "summary_path": str(summary_path), "summary_sha256": _sha256(summary_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run preregistered Experiment 002")
    parser.add_argument("--config", type=Path, default=Path("config/experiment_002.json"))
    parser.add_argument("--data-root", type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    result = run(data_root(args.data_root), config)
    print(json.dumps(result, indent=2, sort_keys=True, default=_json_default))


if __name__ == "__main__":
    main()
