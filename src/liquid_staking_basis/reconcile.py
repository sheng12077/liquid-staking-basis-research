from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from liquid_staking_basis.cli import data_root
from liquid_staking_basis.rpc import DATASET_ID_PATTERN


def reconcile_dataset(root: Path, dataset_id: str) -> dict[str, object]:
    if DATASET_ID_PATTERN.fullmatch(dataset_id) is None:
        raise ValueError("invalid dataset_id")
    dataset_dir = root / "raw" / "ethereum_rpc" / dataset_id
    manifests = sorted((dataset_dir / "manifests").glob("manifest_*.json"))
    if not manifests:
        raise ValueError("dataset has no immutable manifest")
    manifest_path = manifests[-1]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = sorted(manifest["chunks"], key=lambda item: int(item["from_block"]))
    expected_addresses = {str(value).lower() for value in manifest["addresses"]}
    configured_topics = manifest.get("topic0s")
    if configured_topics is None:
        single_topic = manifest.get("topic0")
        configured_topics = [] if single_topic is None else [single_topic]
    expected_topics = {str(value).lower() for value in configured_topics}

    errors: list[str] = []
    address_counts: Counter[str] = Counter()
    topic_counts: Counter[str] = Counter()
    event_keys: set[tuple[str, str]] = set()
    duplicate_event_count = 0
    total_logs = 0
    minimum_event_block: int | None = None
    maximum_event_block: int | None = None
    previous_end: int | None = None

    for index, record in enumerate(records):
        chunk_start = int(record["from_block"])
        chunk_end = int(record["to_block"])
        if index == 0 and chunk_start != int(manifest["start_block"]):
            errors.append("first chunk does not begin at manifest start_block")
        if previous_end is not None and chunk_start != previous_end + 1:
            errors.append(f"chunk boundary gap or overlap before block {chunk_start}")
        previous_end = chunk_end

        path = root / str(record["path"])
        payload = json.loads(path.read_text(encoding="utf-8"))
        logs = payload.get("result", [])
        if not isinstance(logs, list):
            errors.append(f"non-list result in {record['path']}")
            continue
        if len(logs) != int(record["log_count"]):
            errors.append(f"log count changed in {record['path']}")
        total_logs += len(logs)
        for log in logs:
            item: dict[str, Any] = log
            block_number = int(str(item["blockNumber"]), 16)
            if block_number < chunk_start or block_number > chunk_end:
                errors.append(f"event outside chunk range in {record['path']}")
            address = str(item["address"]).lower()
            topics = item.get("topics", [])
            topic0 = str(topics[0]).lower() if topics else ""
            if address not in expected_addresses:
                errors.append(f"unexpected address {address}")
            if expected_topics and topic0 not in expected_topics:
                errors.append(f"unexpected topic0 {topic0}")
            address_counts[address] += 1
            topic_counts[topic0] += 1
            event_key = (str(item["transactionHash"]), str(item["logIndex"]))
            if event_key in event_keys:
                duplicate_event_count += 1
            else:
                event_keys.add(event_key)
            minimum_event_block = (
                block_number
                if minimum_event_block is None
                else min(minimum_event_block, block_number)
            )
            maximum_event_block = (
                block_number
                if maximum_event_block is None
                else max(maximum_event_block, block_number)
            )

    if not records:
        errors.append("manifest contains no chunks")
    elif previous_end != int(manifest["end_block"]):
        errors.append("last chunk does not end at manifest end_block")
    if duplicate_event_count:
        errors.append(f"found {duplicate_event_count} duplicate event keys")

    return {
        "dataset_id": dataset_id,
        "manifest_path": str(manifest_path),
        "passed": not errors,
        "errors": errors,
        "configured_start_block": int(manifest["start_block"]),
        "configured_end_block": int(manifest["end_block"]),
        "chunk_count": len(records),
        "total_log_count": total_logs,
        "unique_event_count": len(event_keys),
        "duplicate_event_count": duplicate_event_count,
        "minimum_event_block": minimum_event_block,
        "maximum_event_block": maximum_event_block,
        "address_counts": dict(sorted(address_counts.items())),
        "topic0_counts": dict(sorted(topic_counts.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile a complete raw event backfill")
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = reconcile_dataset(data_root(args.data_root), args.dataset_id)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
