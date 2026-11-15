from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from liquid_staking_basis.cli import data_root, rpc_endpoint
from liquid_staking_basis.rpc import (
    ADDRESS_PATTERN,
    DATASET_ID_PATTERN,
    TOPIC_PATTERN,
    EthereumRpcClient,
)

LOG_REQUEST_CU = 60
DEFAULT_USD_PER_MILLION_CU = 0.525


@dataclass(frozen=True)
class BackfillJob:
    dataset_id: str
    addresses: tuple[str, ...]
    topics: tuple[str, ...]
    start_block: int


def load_jobs(path: Path) -> tuple[BackfillJob, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    jobs: list[BackfillJob] = []
    for raw in payload["jobs"]:
        job = BackfillJob(
            dataset_id=str(raw["dataset_id"]),
            addresses=tuple(str(value) for value in raw["addresses"]),
            topics=tuple(str(value) for value in raw["topics"]),
            start_block=int(raw["start_block"]),
        )
        validate_job(job)
        jobs.append(job)
    if not jobs:
        raise ValueError("backfill configuration contains no jobs")
    if len({job.dataset_id for job in jobs}) != len(jobs):
        raise ValueError("backfill dataset IDs must be unique")
    return tuple(jobs)


def validate_job(job: BackfillJob) -> None:
    if DATASET_ID_PATTERN.fullmatch(job.dataset_id) is None:
        raise ValueError(f"invalid dataset ID: {job.dataset_id}")
    if not job.addresses or any(
        ADDRESS_PATTERN.fullmatch(address) is None for address in job.addresses
    ):
        raise ValueError(f"invalid address in job: {job.dataset_id}")
    if not job.topics or any(TOPIC_PATTERN.fullmatch(topic) is None for topic in job.topics):
        raise ValueError(f"invalid topic in job: {job.dataset_id}")
    if job.start_block < 0:
        raise ValueError(f"invalid start block in job: {job.dataset_id}")


def request_count(jobs: tuple[BackfillJob, ...], end_block: int, chunk_size: int) -> int:
    if chunk_size <= 0 or chunk_size > 2_000:
        raise ValueError("production chunk size must be between 1 and 2,000 blocks")
    return sum(
        math.ceil((end_block - job.start_block + 1) / chunk_size)
        for job in jobs
        if job.start_block <= end_block
    )


def estimate_log_cost_usd(requests: int, usd_per_million_cu: float) -> float:
    return requests * LOG_REQUEST_CU / 1_000_000 * usd_per_million_cu


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _fetch_job(
    client: EthereumRpcClient,
    root: Path,
    job: BackfillJob,
    end_block: int,
    chunk_size: int,
    progress_every: int,
) -> dict[str, object]:
    dataset_dir = root / "raw" / "ethereum_rpc" / job.dataset_id
    chunk_dir = dataset_dir / "chunks"
    manifest_dir = dataset_dir / "manifests"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    status_path = dataset_dir / "backfill_status.json"

    total_chunks = math.ceil((end_block - job.start_block + 1) / chunk_size)
    downloaded = 0
    skipped = 0
    total_logs = 0
    records: list[dict[str, object]] = []
    started = time.monotonic()
    cursor = job.start_block
    while cursor <= end_block:
        chunk_end = min(cursor + chunk_size - 1, end_block)
        prefix = f"{cursor:010d}_{chunk_end:010d}_"
        existing = sorted(chunk_dir.glob(f"{prefix}*.json"))
        if existing:
            path = existing[0]
            body = path.read_bytes()
            skipped += 1
        else:
            topic_filter: str | list[str]
            topic_filter = job.topics[0] if len(job.topics) == 1 else list(job.topics)
            address_filter: str | list[str]
            address_filter = job.addresses[0] if len(job.addresses) == 1 else list(job.addresses)
            query: dict[str, object] = {
                "fromBlock": hex(cursor),
                "toBlock": hex(chunk_end),
                "address": address_filter,
                "topics": [topic_filter],
            }
            envelope = client.call("eth_getLogs", [query])
            body = envelope.raw_body
            digest = hashlib.sha256(body).hexdigest()
            path = chunk_dir / f"{prefix}{digest[:12]}.json"
            path.write_bytes(body)
            downloaded += 1

        digest = hashlib.sha256(body).hexdigest()
        decoded = json.loads(body)
        result = decoded.get("result", [])
        log_count = len(result) if isinstance(result, list) else 0
        total_logs += log_count
        records.append(
            {
                "from_block": cursor,
                "to_block": chunk_end,
                "path": str(path.relative_to(root)),
                "sha256": digest,
                "log_count": log_count,
            }
        )
        completed = downloaded + skipped
        if completed == 1 or completed % progress_every == 0 or completed == total_chunks:
            elapsed = time.monotonic() - started
            new_rate = downloaded / elapsed if downloaded else 0.0
            remaining_new = max(total_chunks - skipped - downloaded, 0)
            eta_seconds = remaining_new / new_rate if new_rate else None
            status: dict[str, object] = {
                "dataset_id": job.dataset_id,
                "updated_at": datetime.now(UTC).isoformat(),
                "start_block": job.start_block,
                "end_block": end_block,
                "chunk_size": chunk_size,
                "completed_chunks": completed,
                "total_chunks": total_chunks,
                "downloaded_chunks": downloaded,
                "skipped_chunks": skipped,
                "logs_observed": total_logs,
                "elapsed_seconds": round(elapsed, 3),
                "eta_seconds": round(eta_seconds, 3) if eta_seconds is not None else None,
            }
            _write_json_atomic(status_path, status)
            print(json.dumps(status, sort_keys=True), flush=True)
        cursor = chunk_end + 1

    created_at = datetime.now(UTC)
    manifest = {
        "created_at": created_at.isoformat(),
        "provider_kind": "ethereum_json_rpc",
        "method": "eth_getLogs",
        "dataset_id": job.dataset_id,
        "addresses": list(job.addresses),
        "topic0s": list(job.topics),
        "start_block": job.start_block,
        "end_block": end_block,
        "chunk_size": chunk_size,
        "plan": "payg",
        "downloaded_chunk_count": downloaded,
        "skipped_chunk_count": skipped,
        "chunks": records,
    }
    timestamp = created_at.strftime("%Y%m%dT%H%M%S.%fZ")
    manifest_path = manifest_dir / f"manifest_{timestamp}.json"
    _write_json_atomic(manifest_path, manifest)
    return {
        "dataset_id": job.dataset_id,
        "downloaded_chunk_count": downloaded,
        "skipped_chunk_count": skipped,
        "total_log_count": total_logs,
        "manifest_path": str(manifest_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the fixed liquid-staking event backfill")
    parser.add_argument("--config", type=Path, default=Path("config/production_backfill.json"))
    parser.add_argument("--end-block", type=int)
    parser.add_argument("--chunk-size", type=int, default=2_000)
    parser.add_argument("--max-estimated-usd", type=float, default=1.0)
    parser.add_argument("--usd-per-million-cu", type=float, default=DEFAULT_USD_PER_MILLION_CU)
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--estimate-only", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    jobs = load_jobs(args.config)
    if args.progress_every <= 0:
        raise SystemExit("--progress-every must be positive")

    endpoint = rpc_endpoint()
    with EthereumRpcClient(endpoint) as client:
        observed_head = int(client.call("eth_blockNumber", []).result, 16)
        end_block = observed_head if args.end_block is None else args.end_block
        if end_block > observed_head:
            raise SystemExit("--end-block cannot exceed the observed chain head")
        requests = request_count(jobs, end_block, args.chunk_size)
        estimated_usd = estimate_log_cost_usd(requests, args.usd_per_million_cu)
        estimate: dict[str, Any] = {
            "observed_head": observed_head,
            "frozen_end_block": end_block,
            "chunk_size": args.chunk_size,
            "job_count": len(jobs),
            "log_request_count": requests,
            "estimated_log_request_cu": requests * LOG_REQUEST_CU,
            "estimated_log_request_usd": round(estimated_usd, 6),
            "max_estimated_usd": args.max_estimated_usd,
        }
        print(json.dumps(estimate, indent=2, sort_keys=True), flush=True)
        if estimated_usd > args.max_estimated_usd:
            raise SystemExit("estimated log-request cost exceeds --max-estimated-usd")
        if args.estimate_only:
            return

        results = [
            _fetch_job(
                client,
                data_root(args.data_root),
                job,
                end_block,
                args.chunk_size,
                args.progress_every,
            )
            for job in jobs
            if job.start_block <= end_block
        ]
        print(json.dumps({"estimate": estimate, "results": results}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
