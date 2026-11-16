from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from datetime import time as datetime_time
from pathlib import Path
from typing import Any, Protocol

import polars as pl

from liquid_staking_basis.cli import data_root, rpc_endpoint
from liquid_staking_basis.rpc import EthereumRpcClient, RpcEnvelope

BLOCK_CALL_CU = 10
STATE_CALL_CU = 26
USD_PER_MILLION_CU = 0.525
WEI = 10**18


class RpcCaller(Protocol):
    def call(self, method: str, params: list[object]) -> RpcEnvelope: ...


class CountingRpcClient:
    def __init__(self, client: RpcCaller) -> None:
        self._client = client
        self.counts: Counter[str] = Counter()

    def call(self, method: str, params: list[object]) -> RpcEnvelope:
        self.counts[method] += 1
        return self._client.call(method, params)


def _dates(start: date, end: date) -> list[date]:
    if end < start:
        raise ValueError("end date precedes start date")
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _timestamp(day: date) -> int:
    return int(datetime.combine(day, datetime_time.min, UTC).timestamp())


def _block(client: RpcCaller, block_number: int) -> dict[str, Any]:
    result = client.call("eth_getBlockByNumber", [hex(block_number), False]).result
    if not isinstance(result, dict):
        raise ValueError(f"missing block {block_number}")
    return result


def find_last_block_before(
    client: RpcCaller,
    target_timestamp: int,
    known_lower_block: int,
    maximum_block: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    lower = known_lower_block
    lower_header = _block(client, lower)
    if int(lower_header["timestamp"], 16) >= target_timestamp:
        raise ValueError("known lower block is not strictly before target timestamp")

    upper = min(lower + 10_000, maximum_block)
    upper_header = _block(client, upper)
    while int(upper_header["timestamp"], 16) < target_timestamp:
        if upper == maximum_block:
            raise ValueError("audit end block is earlier than target timestamp")
        lower = upper
        lower_header = upper_header
        upper = min(upper + 10_000, maximum_block)
        upper_header = _block(client, upper)

    while upper - lower > 1:
        lower_timestamp = int(lower_header["timestamp"], 16)
        upper_timestamp = int(upper_header["timestamp"], 16)
        timestamp_span = upper_timestamp - lower_timestamp
        if timestamp_span > 0:
            interpolated = lower + int(
                (target_timestamp - lower_timestamp)
                * (upper - lower)
                / timestamp_span
            )
            middle = min(max(interpolated, lower + 1), upper - 1)
        else:
            middle = (lower + upper) // 2
        middle_header = _block(client, middle)
        if int(middle_header["timestamp"], 16) < target_timestamp:
            lower = middle
            lower_header = middle_header
        else:
            upper = middle
            upper_header = middle_header
    return lower_header, upper_header


def encode_get_dy(selector: str, sold_id: int, bought_id: int, amount: int) -> str:
    if not selector.startswith("0x") or len(selector) != 10:
        raise ValueError("selector must contain four bytes")
    if sold_id < 0 or bought_id < 0 or amount <= 0:
        raise ValueError("invalid get_dy arguments")
    words = (sold_id, bought_id, amount)
    return selector + "".join(f"{value:064x}" for value in words)


def _eth_call(client: RpcCaller, address: str, calldata: str, block_number: int) -> str:
    result = client.call(
        "eth_call", [{"to": address, "data": calldata}, hex(block_number)]
    ).result
    if not isinstance(result, str) or not result.startswith("0x"):
        raise ValueError("eth_call returned a non-hex result")
    if int(result, 16) <= 0:
        raise ValueError("eth_call returned a non-positive value")
    return result


def _implementation_at(intervals: list[dict[str, Any]], block_number: int) -> str:
    for interval in intervals:
        if int(interval["start_block"]) <= block_number <= int(interval["end_block"]):
            return str(interval["implementation"])
    raise ValueError(f"no stETH implementation interval for block {block_number}")


def _load_steth_intervals(path: Path) -> list[dict[str, Any]]:
    report = json.loads(path.read_text(encoding="utf-8"))
    for proxy in report["proxies"]:
        if proxy["id"] == "lido_steth":
            return list(proxy["intervals"])
    raise ValueError("stETH intervals are missing")


def _write_atomic(path: Path, body: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(body)
    temporary.replace(path)


def _existing_snapshot(chunk_dir: Path, day: date) -> Path | None:
    matches = sorted(chunk_dir.glob(f"{day.isoformat()}_*.json"))
    if len(matches) > 1:
        raise ValueError(f"multiple snapshot chunks for {day.isoformat()}")
    return matches[0] if matches else None


def _snapshot_calls(
    client: RpcCaller,
    config: dict[str, Any],
    block_number: int,
) -> dict[str, dict[str, object] | None]:
    contracts = config["contracts"]
    calls: dict[str, dict[str, object] | None] = {}

    wsteth = contracts["wsteth"]
    if block_number >= int(wsteth["deployment_block"]):
        result = _eth_call(
            client,
            str(wsteth["address"]),
            str(wsteth["steth_per_token_selector"]),
            block_number,
        )
        calls["wsteth_steth_per_token"] = {
            "to": wsteth["address"],
            "calldata": wsteth["steth_per_token_selector"],
            "result": result,
        }
    else:
        calls["wsteth_steth_per_token"] = None

    for pool_key in ("curve_legacy", "curve_concentrated"):
        pool = contracts[pool_key]
        for sold_id, bought_id, suffix in ((0, 1, "0_to_1"), (1, 0, "1_to_0")):
            name = f"{pool_key}_{suffix}"
            if block_number < int(pool["deployment_block"]):
                calls[name] = None
                continue
            calldata = encode_get_dy(
                str(pool["get_dy_selector"]),
                sold_id,
                bought_id,
                int(config["input_amount_wei"]),
            )
            result = _eth_call(client, str(pool["address"]), calldata, block_number)
            calls[name] = {
                "to": pool["address"],
                "calldata": calldata,
                "result": result,
            }
    return calls


def acquire_snapshots(
    client: CountingRpcClient,
    root: Path,
    config: dict[str, Any],
    intervals: list[dict[str, Any]],
    progress_every: int,
) -> dict[str, object]:
    dataset_id = str(config["dataset_id"])
    dataset_dir = root / "raw" / "ethereum_rpc" / dataset_id
    chunk_dir = dataset_dir / "chunks"
    manifest_dir = dataset_dir / "manifests"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    days = _dates(date.fromisoformat(config["start_date"]), date.fromisoformat(config["end_date"]))

    downloaded = 0
    skipped = 0
    records: list[dict[str, object]] = []
    lower_block = int(config["contracts"]["curve_legacy"]["deployment_block"])
    started = time.monotonic()
    for index, day in enumerate(days, start=1):
        existing = _existing_snapshot(chunk_dir, day)
        if existing is not None:
            body = existing.read_bytes()
            snapshot = json.loads(body)
            if snapshot["observation_date"] != day.isoformat():
                raise ValueError(f"snapshot date mismatch in {existing}")
            selected_block = int(snapshot["block"]["number"])
            path = existing
            skipped += 1
        else:
            target_timestamp = _timestamp(day)
            selected, following = find_last_block_before(
                client,
                target_timestamp,
                lower_block,
                int(config["audit_end_block"]),
            )
            selected_block = int(selected["number"], 16)
            snapshot = {
                "schema_version": 1,
                "dataset_id": dataset_id,
                "observation_date": day.isoformat(),
                "target_timestamp": target_timestamp,
                "observation_rule": config["observation_rule"],
                "block": {
                    "number": selected_block,
                    "hash": selected["hash"],
                    "timestamp": int(selected["timestamp"], 16),
                },
                "following_block": {
                    "number": int(following["number"], 16),
                    "hash": following["hash"],
                    "timestamp": int(following["timestamp"], 16),
                },
                "steth_implementation": _implementation_at(intervals, selected_block),
                "calls": _snapshot_calls(client, config, selected_block),
            }
            body = json.dumps(snapshot, indent=2, sort_keys=True).encode() + b"\n"
            digest = hashlib.sha256(body).hexdigest()
            path = chunk_dir / f"{day.isoformat()}_{digest[:12]}.json"
            _write_atomic(path, body)
            downloaded += 1
        lower_block = selected_block
        digest = hashlib.sha256(body).hexdigest()
        records.append(
            {
                "observation_date": day.isoformat(),
                "block_number": selected_block,
                "path": str(path.relative_to(root)),
                "sha256": digest,
            }
        )
        if index == 1 or index % progress_every == 0 or index == len(days):
            elapsed = time.monotonic() - started
            rate = downloaded / elapsed if downloaded else 0.0
            remaining = len(days) - index
            status = {
                "completed_days": index,
                "total_days": len(days),
                "downloaded_days": downloaded,
                "skipped_days": skipped,
                "last_observation_date": day.isoformat(),
                "last_block_number": selected_block,
                "rpc_counts": dict(client.counts),
                "eta_seconds": round(remaining / rate, 3) if rate else None,
            }
            print(json.dumps(status, sort_keys=True), flush=True)

    created_at = datetime.now(UTC)
    manifest = {
        "schema_version": 1,
        "created_at": created_at.isoformat(),
        "dataset_id": dataset_id,
        "observation_rule": config["observation_rule"],
        "start_date": config["start_date"],
        "end_date": config["end_date"],
        "audit_end_block": config["audit_end_block"],
        "downloaded_day_count": downloaded,
        "skipped_day_count": skipped,
        "rpc_counts": dict(client.counts),
        "snapshots": records,
    }
    manifest_path = manifest_dir / created_at.strftime("manifest_%Y%m%dT%H%M%S.%fZ.json")
    _write_atomic(manifest_path, json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n")
    return {
        "dataset_id": dataset_id,
        "downloaded_day_count": downloaded,
        "skipped_day_count": skipped,
        "manifest_path": str(manifest_path),
        "rpc_counts": dict(client.counts),
    }


def _raw_value(call: dict[str, object] | None) -> tuple[str | None, float | None]:
    if call is None:
        return None, None
    integer = int(str(call["result"]), 16)
    return str(integer), integer / WEI


def build_canonical(root: Path, config: dict[str, Any]) -> dict[str, object]:
    dataset_id = str(config["dataset_id"])
    chunk_dir = root / "raw" / "ethereum_rpc" / dataset_id / "chunks"
    rows: list[dict[str, object]] = []
    errors: list[str] = []
    previous_block = -1
    for path in sorted(chunk_dir.glob("*.json")):
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        target = int(snapshot["target_timestamp"])
        block = snapshot["block"]
        following = snapshot["following_block"]
        block_number = int(block["number"])
        block_timestamp = int(block["timestamp"])
        following_timestamp = int(following["timestamp"])
        if not block_timestamp < target <= following_timestamp:
            errors.append(f"timestamp bracket failed for {snapshot['observation_date']}")
        if block_number <= previous_block:
            errors.append(f"block number is not increasing at {snapshot['observation_date']}")
        previous_block = block_number
        calls = snapshot["calls"]
        wsteth_raw, wsteth = _raw_value(calls["wsteth_steth_per_token"])
        legacy_forward_raw, legacy_forward = _raw_value(calls["curve_legacy_0_to_1"])
        legacy_reverse_raw, legacy_reverse = _raw_value(calls["curve_legacy_1_to_0"])
        concentrated_forward_raw, concentrated_forward = _raw_value(
            calls["curve_concentrated_0_to_1"]
        )
        concentrated_reverse_raw, concentrated_reverse = _raw_value(
            calls["curve_concentrated_1_to_0"]
        )
        for name, value in (
            ("legacy_forward", legacy_forward),
            ("legacy_reverse", legacy_reverse),
            ("concentrated_forward", concentrated_forward),
            ("concentrated_reverse", concentrated_reverse),
        ):
            if value is not None and not 0.5 <= value <= 2.0:
                errors.append(f"implausible {name} quote at {snapshot['observation_date']}: {value}")
        rows.append(
            {
                "observation_date": snapshot["observation_date"],
                "target_timestamp": target,
                "block_number": block_number,
                "block_timestamp": block_timestamp,
                "block_hash": block["hash"],
                "following_block_number": int(following["number"]),
                "following_block_timestamp": following_timestamp,
                "steth_implementation": snapshot["steth_implementation"],
                "wsteth_steth_per_token_raw": wsteth_raw,
                "wsteth_steth_per_token": wsteth,
                "legacy_eth_to_steth_raw": legacy_forward_raw,
                "legacy_eth_to_steth": legacy_forward,
                "legacy_steth_to_eth_raw": legacy_reverse_raw,
                "legacy_steth_to_eth": legacy_reverse,
                "concentrated_weth_to_steth_raw": concentrated_forward_raw,
                "concentrated_weth_to_steth": concentrated_forward,
                "concentrated_steth_to_weth_raw": concentrated_reverse_raw,
                "concentrated_steth_to_weth": concentrated_reverse,
            }
        )
    expected_days = len(
        _dates(date.fromisoformat(config["start_date"]), date.fromisoformat(config["end_date"]))
    )
    if len(rows) != expected_days:
        errors.append(f"expected {expected_days} daily rows, found {len(rows)}")
    if errors:
        raise ValueError("; ".join(errors[:20]))
    output_dir = root / "canonical" / "ethereum" / dataset_id
    output_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = output_dir / "daily_state.parquet"
    pl.DataFrame(rows, infer_schema_length=None).write_parquet(
        parquet_path, compression="zstd", statistics=True
    )
    manifest = {
        "schema_version": 1,
        "dataset_id": dataset_id,
        "row_count": len(rows),
        "start_date": rows[0]["observation_date"],
        "end_date": rows[-1]["observation_date"],
        "minimum_block_number": rows[0]["block_number"],
        "maximum_block_number": rows[-1]["block_number"],
        "parquet_path": str(parquet_path),
        "validation_errors": [],
    }
    manifest_path = output_dir / "canonical_manifest.json"
    _write_atomic(manifest_path, json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n")
    return manifest


def audit_raw_snapshots(root: Path, config: dict[str, Any]) -> dict[str, object]:
    dataset_id = str(config["dataset_id"])
    dataset_dir = root / "raw" / "ethereum_rpc" / dataset_id
    manifests = sorted((dataset_dir / "manifests").glob("manifest_*.json"))
    if not manifests:
        return {"dataset_id": dataset_id, "passed": False, "errors": ["no manifest"]}
    manifest_path = manifests[-1]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    expected_dates = {
        day.isoformat()
        for day in _dates(
            date.fromisoformat(config["start_date"]), date.fromisoformat(config["end_date"])
        )
    }
    observed_dates: set[str] = set()
    forbidden_markers = (b"ETHEREUM_RPC_URL", b"alchemy.com/v2/")
    for record in manifest.get("snapshots", []):
        observation_date = str(record["observation_date"])
        if observation_date in observed_dates:
            errors.append(f"duplicate manifest date: {observation_date}")
        observed_dates.add(observation_date)
        path = root / str(record["path"])
        if not path.exists():
            errors.append(f"missing snapshot: {record['path']}")
            continue
        body = path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if record.get("sha256") != digest:
            errors.append(f"manifest checksum mismatch: {record['path']}")
        if not path.stem.endswith(digest[:12]):
            errors.append(f"filename checksum mismatch: {record['path']}")
        if any(marker in body for marker in forbidden_markers):
            errors.append(f"possible endpoint disclosure: {record['path']}")
        snapshot = json.loads(body)
        if snapshot.get("observation_date") != observation_date:
            errors.append(f"payload date mismatch: {record['path']}")
        if int(snapshot["block"]["number"]) != int(record["block_number"]):
            errors.append(f"manifest block mismatch: {record['path']}")
    missing_dates = expected_dates - observed_dates
    extra_dates = observed_dates - expected_dates
    if missing_dates:
        errors.append(f"missing {len(missing_dates)} observation dates")
    if extra_dates:
        errors.append(f"found {len(extra_dates)} unexpected observation dates")
    return {
        "dataset_id": dataset_id,
        "manifest_path": str(manifest_path),
        "snapshot_count": len(observed_dates),
        "expected_snapshot_count": len(expected_dates),
        "missing_date_count": len(missing_dates),
        "extra_date_count": len(extra_dates),
        "errors": errors,
        "passed": not errors,
    }


def validate_boundaries(
    client: CountingRpcClient,
    root: Path,
    config: dict[str, Any],
    intervals: list[dict[str, Any]],
) -> dict[str, object]:
    selector = str(config["contracts"]["wsteth"]["steth_per_token_selector"])
    address = str(config["contracts"]["wsteth"]["address"])
    maximum_jump = float(config["boundary_max_relative_jump"])
    observations: list[dict[str, object]] = []
    errors: list[str] = []
    for interval in intervals[1:]:
        boundary = int(interval["start_block"])
        before_raw = _eth_call(client, address, selector, boundary - 1)
        after_raw = _eth_call(client, address, selector, boundary)
        before = int(before_raw, 16) / WEI
        after = int(after_raw, 16) / WEI
        jump = after / before - 1
        if abs(jump) > maximum_jump:
            errors.append(f"wstETH rate jump {jump} exceeds threshold at block {boundary}")
        observations.append(
            {
                "boundary_block": boundary,
                "before_implementation": _implementation_at(intervals, boundary - 1),
                "after_implementation": _implementation_at(intervals, boundary),
                "before_rate_raw": str(int(before_raw, 16)),
                "after_rate_raw": str(int(after_raw, 16)),
                "relative_jump": jump,
                "passed": abs(jump) <= maximum_jump,
            }
        )
    report = {
        "schema_version": 1,
        "dataset_id": config["dataset_id"],
        "maximum_absolute_relative_jump": maximum_jump,
        "boundary_count": len(observations),
        "observations": observations,
        "errors": errors,
        "passed": not errors,
    }
    output_dir = root / "canonical" / "ethereum" / str(config["dataset_id"])
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "steth_boundary_validation.json"
    _write_atomic(path, json.dumps(report, indent=2, sort_keys=True).encode() + b"\n")
    return {**report, "path": str(path)}


def estimate(config: dict[str, Any], maximum_block_calls_per_day: int = 25) -> dict[str, object]:
    days = _dates(date.fromisoformat(config["start_date"]), date.fromisoformat(config["end_date"]))
    state_calls = 0
    for day in days:
        target = _timestamp(day)
        # Deployment timestamps are conservatively represented by their first full UTC day.
        state_calls += 2
        if target >= _timestamp(date(2021, 2, 20)):
            state_calls += 1
        if target >= _timestamp(date(2022, 5, 13)):
            state_calls += 2
    state_calls += 10
    block_calls = len(days) * maximum_block_calls_per_day
    total_cu = block_calls * BLOCK_CALL_CU + state_calls * STATE_CALL_CU
    return {
        "day_count": len(days),
        "maximum_block_call_count": block_calls,
        "estimated_state_call_count": state_calls,
        "estimated_compute_units": total_cu,
        "estimated_usd": round(total_cu / 1_000_000 * USD_PER_MILLION_CU, 6),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Acquire daily point-in-time Lido/Curve state")
    parser.add_argument("--config", type=Path, default=Path("config/daily_state_snapshots.json"))
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--max-estimated-usd", type=float, default=1.0)
    parser.add_argument("--progress-every", type=int, default=50)
    parser.add_argument("--estimate-only", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    projected = estimate(config)
    print(json.dumps(projected, indent=2, sort_keys=True), flush=True)
    if float(str(projected["estimated_usd"])) > args.max_estimated_usd:
        raise SystemExit("estimated cost exceeds --max-estimated-usd")
    if args.estimate_only:
        return
    if args.progress_every <= 0:
        raise SystemExit("--progress-every must be positive")
    intervals = _load_steth_intervals(Path(config["steth_intervals"]))
    with EthereumRpcClient(rpc_endpoint()) as raw_client:
        client = CountingRpcClient(raw_client)
        head = int(client.call("eth_blockNumber", []).result, 16)
        if head < int(config["audit_end_block"]):
            raise SystemExit("chain head is earlier than fixed audit end block")
        acquisition = acquire_snapshots(
            client,
            data_root(args.data_root),
            config,
            intervals,
            args.progress_every,
        )
        raw_audit = audit_raw_snapshots(data_root(args.data_root), config)
        if not raw_audit["passed"]:
            raise SystemExit("raw snapshot audit failed")
        boundary = validate_boundaries(
            client, data_root(args.data_root), config, intervals
        )
    canonical = build_canonical(data_root(args.data_root), config)
    result = {
        "estimate": projected,
        "acquisition": acquisition,
        "raw_audit": raw_audit,
        "boundary_validation": boundary,
        "canonical": canonical,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if not boundary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
