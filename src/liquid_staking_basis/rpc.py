from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

DATASET_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
ADDRESS_PATTERN = re.compile(r"0x[0-9a-fA-F]{40}")
TOPIC_PATTERN = re.compile(r"0x[0-9a-fA-F]{64}")


@dataclass(frozen=True)
class RpcEnvelope:
    result: Any
    raw_body: bytes


class EthereumRpcClient:
    def __init__(
        self,
        endpoint: str,
        timeout_seconds: float = 60.0,
        max_attempts: int = 5,
    ) -> None:
        if not endpoint.startswith("https://"):
            raise ValueError("ETHEREUM_RPC_URL must use HTTPS")
        self._endpoint = endpoint
        self._max_attempts = max_attempts
        self._client = httpx.Client(timeout=timeout_seconds)
        self._request_id = 0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> EthereumRpcClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def call(self, method: str, params: list[object]) -> RpcEnvelope:
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        for attempt in range(self._max_attempts):
            try:
                response = self._client.post(self._endpoint, json=payload)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt + 1 < self._max_attempts:
                        time.sleep(min(2**attempt, 8))
                        continue
                response.raise_for_status()
                body = response.content
                decoded = response.json()
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                if attempt + 1 < self._max_attempts:
                    time.sleep(min(2**attempt, 8))
                    continue
                raise RuntimeError("Ethereum RPC request failed after retries") from exc
            if "error" in decoded:
                error = decoded["error"]
                code = error.get("code") if isinstance(error, dict) else None
                raise RuntimeError(f"Ethereum RPC returned error code {code}")
            if "result" not in decoded:
                raise RuntimeError("Ethereum RPC response omitted result")
            return RpcEnvelope(decoded["result"], body)
        raise RuntimeError("Ethereum RPC request failed")


def validate_fetch_inputs(
    dataset_id: str,
    addresses: tuple[str, ...],
    topic: str | None,
    start_block: int,
    end_block: int,
    chunk_size: int,
    plan: str,
) -> None:
    if DATASET_ID_PATTERN.fullmatch(dataset_id) is None:
        raise ValueError("dataset_id must contain lowercase letters, numbers, underscores or dashes")
    if not addresses or any(ADDRESS_PATTERN.fullmatch(item) is None for item in addresses):
        raise ValueError("at least one valid Ethereum address is required")
    if topic is not None and TOPIC_PATTERN.fullmatch(topic) is None:
        raise ValueError("topic must be a 32-byte hex value")
    if start_block < 0 or end_block < start_block:
        raise ValueError("invalid inclusive block range")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if plan == "free" and chunk_size > 10:
        raise ValueError("Free-plan eth_getLogs chunks cannot exceed 10 blocks")
    if plan == "payg" and chunk_size > 10_000:
        raise ValueError("pilot limits PAYG chunks to 10,000 blocks")


def fetch_logs(
    client: EthereumRpcClient,
    data_root: Path,
    dataset_id: str,
    addresses: tuple[str, ...],
    start_block: int,
    end_block: int,
    topic: str | None = None,
    chunk_size: int = 10,
    plan: str = "free",
    request_delay_seconds: float = 0.15,
) -> dict[str, object]:
    validate_fetch_inputs(
        dataset_id, addresses, topic, start_block, end_block, chunk_size, plan
    )
    dataset_dir = data_root / "raw" / "ethereum_rpc" / dataset_id
    chunk_dir = dataset_dir / "chunks"
    manifest_dir = dataset_dir / "manifests"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    address_filter: str | list[str]
    address_filter = addresses[0] if len(addresses) == 1 else list(addresses)
    records: list[dict[str, object]] = []
    downloaded = 0
    skipped = 0
    cursor = start_block
    while cursor <= end_block:
        chunk_end = min(cursor + chunk_size - 1, end_block)
        prefix = f"{cursor:010d}_{chunk_end:010d}_"
        existing = sorted(chunk_dir.glob(f"{prefix}*.json"))
        if existing:
            path = existing[0]
            body = path.read_bytes()
            skipped += 1
        else:
            query: dict[str, object] = {
                "fromBlock": hex(cursor),
                "toBlock": hex(chunk_end),
                "address": address_filter,
            }
            if topic is not None:
                query["topics"] = [topic]
            envelope = client.call("eth_getLogs", [query])
            body = envelope.raw_body
            digest = hashlib.sha256(body).hexdigest()
            path = chunk_dir / f"{prefix}{digest[:12]}.json"
            path.write_bytes(body)
            downloaded += 1
            if request_delay_seconds > 0:
                time.sleep(request_delay_seconds)
        digest = hashlib.sha256(body).hexdigest()
        decoded = json.loads(body)
        result = decoded.get("result", [])
        records.append(
            {
                "from_block": cursor,
                "to_block": chunk_end,
                "path": str(path.relative_to(data_root)),
                "sha256": digest,
                "log_count": len(result) if isinstance(result, list) else None,
            }
        )
        cursor = chunk_end + 1

    created_at = datetime.now(UTC)
    manifest = {
        "created_at": created_at.isoformat(),
        "provider_kind": "ethereum_json_rpc",
        "method": "eth_getLogs",
        "dataset_id": dataset_id,
        "addresses": list(addresses),
        "topic0": topic,
        "start_block": start_block,
        "end_block": end_block,
        "chunk_size": chunk_size,
        "plan": plan,
        "downloaded_chunk_count": downloaded,
        "skipped_chunk_count": skipped,
        "chunks": records,
    }
    timestamp = created_at.strftime("%Y%m%dT%H%M%S.%fZ")
    manifest_path = manifest_dir / f"manifest_{timestamp}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return {
        "dataset_id": dataset_id,
        "downloaded_chunk_count": downloaded,
        "skipped_chunk_count": skipped,
        "manifest_path": str(manifest_path),
    }

