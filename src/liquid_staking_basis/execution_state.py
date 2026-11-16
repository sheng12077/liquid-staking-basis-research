from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from liquid_staking_basis.cli import data_root, rpc_endpoint
from liquid_staking_basis.daily_state import (
    BLOCK_CALL_CU,
    STATE_CALL_CU,
    USD_PER_MILLION_CU,
    WEI,
    CountingRpcClient,
    _eth_call,
    _write_atomic,
    encode_get_dy,
)
from liquid_staking_basis.rpc import EthereumRpcClient


def _source_rows(root: Path, config: dict[str, Any]) -> list[dict[str, object]]:
    source = root / str(config["source_daily_state_path"])
    return (
        pl.read_parquet(
            source,
            columns=[
                "observation_date",
                "target_timestamp",
                "block_number",
                "block_timestamp",
                "block_hash",
            ],
        )
        .filter(
            (pl.col("observation_date") >= str(config["start_date"]))
            & (pl.col("observation_date") <= str(config["end_date"]))
        )
        .sort("observation_date")
        .to_dicts()
    )


def estimate(root: Path, config: dict[str, Any]) -> dict[str, object]:
    rows = _source_rows(root, config)
    # The observation immediately before 00:00 UTC on London fork day predates
    # activation later on 2021-08-05 and therefore still needs a full block.
    legacy_block_calls = sum(str(row["observation_date"]) <= "2021-08-05" for row in rows)
    block_calls = len(rows) + legacy_block_calls
    state_calls = len(rows) * 2
    compute_units = block_calls * BLOCK_CALL_CU + state_calls * STATE_CALL_CU
    return {
        "day_count": len(rows),
        "block_call_count": block_calls,
        "legacy_full_block_call_count": legacy_block_calls,
        "state_call_count": state_calls,
        "estimated_compute_units": compute_units,
        "estimated_usd": round(compute_units / 1_000_000 * USD_PER_MILLION_CU, 6),
    }


def _existing(chunk_dir: Path, observation_date: str) -> Path | None:
    matches = sorted(chunk_dir.glob(f"{observation_date}_*.json"))
    if len(matches) > 1:
        raise ValueError(f"multiple execution-state chunks for {observation_date}")
    return matches[0] if matches else None


def acquire(
    client: CountingRpcClient,
    root: Path,
    config: dict[str, Any],
    progress_every: int,
) -> dict[str, object]:
    dataset_id = str(config["dataset_id"])
    dataset_dir = root / "raw" / "ethereum_rpc" / dataset_id
    chunk_dir = dataset_dir / "chunks"
    manifest_dir = dataset_dir / "manifests"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    rows = _source_rows(root, config)
    pool = config["curve_legacy"]
    amount = int(config["quote_input_wei"])
    downloaded = 0
    skipped = 0
    records: list[dict[str, object]] = []
    started = time.monotonic()

    for index, source in enumerate(rows, start=1):
        observation_date = str(source["observation_date"])
        existing = _existing(chunk_dir, observation_date)
        if existing is not None:
            path = existing
            body = path.read_bytes()
            snapshot = json.loads(body)
            skipped += 1
        else:
            block_number = int(str(source["block_number"]))
            block = client.call("eth_getBlockByNumber", [hex(block_number), False]).result
            if not isinstance(block, dict):
                raise ValueError(f"missing block {block_number}")
            if block["hash"] != source["block_hash"]:
                raise ValueError(f"source block hash mismatch on {observation_date}")
            if int(block["timestamp"], 16) != int(str(source["block_timestamp"])):
                raise ValueError(f"source block timestamp mismatch on {observation_date}")
            base_fee = block.get("baseFeePerGas")
            if isinstance(base_fee, str):
                parsed_base_fee = int(base_fee, 16)
                base_fee_wei: int | None = parsed_base_fee
                gas_price_wei = parsed_base_fee + int(config["priority_fee_wei"])
                gas_price_source = "base_fee_plus_fixed_priority"
            else:
                full_block = client.call("eth_getBlockByNumber", [hex(block_number), True]).result
                if not isinstance(full_block, dict) or full_block.get("hash") != block["hash"]:
                    raise ValueError(f"legacy full-block mismatch on {observation_date}")
                transactions = full_block.get("transactions")
                if not isinstance(transactions, list):
                    raise ValueError(f"legacy block has no transactions on {observation_date}")
                legacy_prices = [
                    int(transaction["gasPrice"], 16)
                    for transaction in transactions
                    if isinstance(transaction, dict)
                    and isinstance(transaction.get("gasPrice"), str)
                ]
                if not legacy_prices:
                    raise ValueError(f"legacy block has no gas prices on {observation_date}")
                base_fee_wei = None
                gas_price_wei = int(statistics.median(legacy_prices))
                gas_price_source = "median_legacy_transaction_gas_price"
            forward_calldata = encode_get_dy(str(pool["get_dy_selector"]), 0, 1, amount)
            reverse_calldata = encode_get_dy(str(pool["get_dy_selector"]), 1, 0, amount)
            forward = _eth_call(client, str(pool["address"]), forward_calldata, block_number)
            reverse = _eth_call(client, str(pool["address"]), reverse_calldata, block_number)
            snapshot = {
                "schema_version": 1,
                "dataset_id": dataset_id,
                "observation_date": observation_date,
                "target_timestamp": int(str(source["target_timestamp"])),
                "source_daily_state_path": config["source_daily_state_path"],
                "block": {
                    "number": block_number,
                    "hash": block["hash"],
                    "timestamp": int(block["timestamp"], 16),
                    "base_fee_per_gas_wei": base_fee_wei,
                    "gas_price_per_gas_wei": gas_price_wei,
                    "gas_price_source": gas_price_source,
                },
                "curve_legacy": {
                    "address": pool["address"],
                    "quote_input_wei": amount,
                    "eth_to_steth_calldata": forward_calldata,
                    "eth_to_steth_output_wei": int(forward, 16),
                    "steth_to_eth_calldata": reverse_calldata,
                    "steth_to_eth_output_wei": int(reverse, 16),
                },
            }
            body = json.dumps(snapshot, indent=2, sort_keys=True).encode() + b"\n"
            digest = hashlib.sha256(body).hexdigest()
            path = chunk_dir / f"{observation_date}_{digest[:12]}.json"
            _write_atomic(path, body)
            downloaded += 1

        digest = hashlib.sha256(body).hexdigest()
        records.append(
            {
                "observation_date": observation_date,
                "block_number": int(snapshot["block"]["number"]),
                "path": str(path.relative_to(root)),
                "sha256": digest,
            }
        )
        if index == 1 or index % progress_every == 0 or index == len(rows):
            elapsed = time.monotonic() - started
            rate = downloaded / elapsed if downloaded else 0.0
            print(
                json.dumps(
                    {
                        "completed_days": index,
                        "total_days": len(rows),
                        "downloaded_days": downloaded,
                        "skipped_days": skipped,
                        "last_observation_date": observation_date,
                        "rpc_counts": dict(client.counts),
                        "eta_seconds": round((len(rows) - index) / rate, 1) if rate else None,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

    created_at = datetime.now(UTC)
    manifest = {
        "schema_version": 1,
        "dataset_id": dataset_id,
        "created_at": created_at.isoformat(),
        "start_date": config["start_date"],
        "end_date": config["end_date"],
        "source_daily_state_path": config["source_daily_state_path"],
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


def audit_raw(root: Path, config: dict[str, Any]) -> dict[str, object]:
    dataset_id = str(config["dataset_id"])
    dataset_dir = root / "raw" / "ethereum_rpc" / dataset_id
    manifests = sorted((dataset_dir / "manifests").glob("manifest_*.json"))
    errors: list[str] = []
    if not manifests:
        return {"dataset_id": dataset_id, "passed": False, "errors": ["no manifest"]}
    manifest = json.loads(manifests[-1].read_text(encoding="utf-8"))
    expected = {str(row["observation_date"]) for row in _source_rows(root, config)}
    observed: set[str] = set()
    for record in manifest["snapshots"]:
        day = str(record["observation_date"])
        if day in observed:
            errors.append(f"duplicate date {day}")
        observed.add(day)
        path = root / str(record["path"])
        if not path.exists():
            errors.append(f"missing file {record['path']}")
            continue
        body = path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if digest != record["sha256"] or not path.stem.endswith(digest[:12]):
            errors.append(f"checksum mismatch {record['path']}")
        if b"alchemy.com" in body or b"ETHEREUM_RPC_URL" in body:
            errors.append(f"endpoint disclosure {record['path']}")
    if expected - observed:
        errors.append(f"missing {len(expected - observed)} dates")
    if observed - expected:
        errors.append(f"extra {len(observed - expected)} dates")
    return {
        "dataset_id": dataset_id,
        "manifest_path": str(manifests[-1]),
        "snapshot_count": len(observed),
        "expected_snapshot_count": len(expected),
        "errors": errors,
        "passed": not errors,
    }


def build_canonical(root: Path, config: dict[str, Any]) -> dict[str, object]:
    dataset_id = str(config["dataset_id"])
    chunk_dir = root / "raw" / "ethereum_rpc" / dataset_id / "chunks"
    input_wei = int(config["quote_input_wei"])
    rows: list[dict[str, object]] = []
    errors: list[str] = []
    for path in sorted(chunk_dir.glob("*.json")):
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        curve = snapshot["curve_legacy"]
        if int(curve["quote_input_wei"]) != input_wei:
            errors.append(f"input mismatch {path.name}")
        forward = int(curve["eth_to_steth_output_wei"])
        reverse = int(curve["steth_to_eth_output_wei"])
        forward_rate = forward / input_wei
        reverse_rate = reverse / input_wei
        if not 0.5 <= forward_rate <= 2.0 or not 0.5 <= reverse_rate <= 2.0:
            errors.append(f"implausible quote {path.name}")
        block = snapshot["block"]
        rows.append(
            {
                "observation_date": snapshot["observation_date"],
                "target_timestamp": int(snapshot["target_timestamp"]),
                "block_number": int(block["number"]),
                "block_timestamp": int(block["timestamp"]),
                "block_hash": block["hash"],
                "base_fee_per_gas_wei": block["base_fee_per_gas_wei"],
                "base_fee_gwei": (
                    int(block["base_fee_per_gas_wei"]) / 10**9
                    if block["base_fee_per_gas_wei"] is not None
                    else None
                ),
                "gas_price_per_gas_wei": int(block["gas_price_per_gas_wei"]),
                "gas_price_gwei": int(block["gas_price_per_gas_wei"]) / 10**9,
                "gas_price_source": block["gas_price_source"],
                "quote_input_wei": input_wei,
                "quote_input_tokens": input_wei / WEI,
                "legacy_10_eth_to_steth_output_raw": str(forward),
                "legacy_10_eth_to_steth_rate": forward_rate,
                "legacy_10_steth_to_eth_output_raw": str(reverse),
                "legacy_10_steth_to_eth_rate": reverse_rate,
            }
        )
    expected = _source_rows(root, config)
    if len(rows) != len(expected):
        errors.append(f"expected {len(expected)} rows, found {len(rows)}")
    if errors:
        raise ValueError("; ".join(errors[:20]))
    output_dir = root / "canonical" / "ethereum" / dataset_id
    output_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = output_dir / "execution_state.parquet"
    frame = pl.DataFrame(rows, infer_schema_length=None).sort("observation_date")
    frame.write_parquet(parquet_path, compression="zstd", statistics=True)
    manifest = {
        "schema_version": 1,
        "dataset_id": dataset_id,
        "row_count": frame.height,
        "start_date": frame["observation_date"].min(),
        "end_date": frame["observation_date"].max(),
        "quote_input_tokens": input_wei / WEI,
        "minimum_base_fee_gwei": frame["base_fee_gwei"].min(),
        "maximum_base_fee_gwei": frame["base_fee_gwei"].max(),
        "minimum_gas_price_gwei": frame["gas_price_gwei"].min(),
        "maximum_gas_price_gwei": frame["gas_price_gwei"].max(),
        "gas_price_source_counts": frame.group_by("gas_price_source")
        .len()
        .sort("gas_price_source")
        .to_dicts(),
        "minimum_eth_to_steth_rate": frame["legacy_10_eth_to_steth_rate"].min(),
        "maximum_eth_to_steth_rate": frame["legacy_10_eth_to_steth_rate"].max(),
        "minimum_steth_to_eth_rate": frame["legacy_10_steth_to_eth_rate"].min(),
        "maximum_steth_to_eth_rate": frame["legacy_10_steth_to_eth_rate"].max(),
        "parquet_path": str(parquet_path),
        "validation_errors": [],
    }
    manifest_path = output_dir / "canonical_manifest.json"
    _write_atomic(manifest_path, json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n")
    return {**manifest, "manifest_path": str(manifest_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Acquire Experiment 001 execution state")
    parser.add_argument(
        "--config", type=Path, default=Path("config/experiment_001_execution_state.json")
    )
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--max-estimated-usd", type=float, default=0.25)
    parser.add_argument("--progress-every", type=int, default=50)
    parser.add_argument("--estimate-only", action="store_true")
    args = parser.parse_args()
    root = data_root(args.data_root)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    projected = estimate(root, config)
    print(json.dumps(projected, indent=2, sort_keys=True), flush=True)
    if float(str(projected["estimated_usd"])) > args.max_estimated_usd:
        raise SystemExit("estimated cost exceeds --max-estimated-usd")
    if args.estimate_only:
        return
    with EthereumRpcClient(rpc_endpoint()) as raw_client:
        acquisition = acquire(CountingRpcClient(raw_client), root, config, args.progress_every)
    raw_audit = audit_raw(root, config)
    if not raw_audit["passed"]:
        raise SystemExit("raw execution-state audit failed")
    canonical = build_canonical(root, config)
    print(
        json.dumps(
            {
                "estimate": projected,
                "acquisition": acquisition,
                "raw_audit": raw_audit,
                "canonical": canonical,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
