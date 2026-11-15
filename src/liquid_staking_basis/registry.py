from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from liquid_staking_basis.cost import estimate_cost
from liquid_staking_basis.rpc import ADDRESS_PATTERN, RpcEnvelope


class RpcCaller(Protocol):
    def call(self, method: str, params: list[object]) -> RpcEnvelope: ...


@dataclass(frozen=True)
class ContractSpec:
    id: str
    address: str
    kind: str
    official_source: str


def load_registry(path: Path) -> tuple[int, tuple[ContractSpec, ...]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    chain_id = payload.get("chain_id")
    if not isinstance(chain_id, int) or chain_id <= 0:
        raise ValueError("registry chain_id must be a positive integer")
    contracts = tuple(ContractSpec(**item) for item in payload.get("contracts", []))
    if not contracts:
        raise ValueError("registry must contain at least one contract")
    ids = [item.id for item in contracts]
    addresses = [item.address.lower() for item in contracts]
    if len(ids) != len(set(ids)) or len(addresses) != len(set(addresses)):
        raise ValueError("registry ids and addresses must be unique")
    if any(ADDRESS_PATTERN.fullmatch(item.address) is None for item in contracts):
        raise ValueError("registry contains an invalid Ethereum address")
    return chain_id, contracts


def find_deployment_block(
    client: RpcCaller, address: str, latest_block: int
) -> tuple[int, int]:
    probe_count = 0

    def has_code(block_number: int) -> bool:
        nonlocal probe_count
        probe_count += 1
        result = client.call("eth_getCode", [address, hex(block_number)]).result
        return isinstance(result, str) and result not in {"0x", "0x0"}

    if not has_code(latest_block):
        raise ValueError(f"contract has no bytecode at latest block: {address}")
    low = 0
    high = latest_block
    while low < high:
        midpoint = (low + high) // 2
        if has_code(midpoint):
            high = midpoint
        else:
            low = midpoint + 1
    return low, probe_count


def discover_deployments(client: RpcCaller, registry_path: Path) -> dict[str, object]:
    expected_chain_id, contracts = load_registry(registry_path)
    observed_chain_id = int(client.call("eth_chainId", []).result, 16)
    if observed_chain_id != expected_chain_id:
        raise ValueError(
            f"registry chain {expected_chain_id} does not match RPC chain {observed_chain_id}"
        )
    latest_block = int(client.call("eth_blockNumber", []).result, 16)
    latest_header = client.call("eth_getBlockByNumber", [hex(latest_block), False]).result
    deployments: list[dict[str, object]] = []
    total_probes = 0
    for contract in contracts:
        deployment_block, probes = find_deployment_block(client, contract.address, latest_block)
        total_probes += probes
        header = client.call("eth_getBlockByNumber", [hex(deployment_block), False]).result
        code = client.call("eth_getCode", [contract.address, hex(deployment_block)]).result
        code_bytes = bytes.fromhex(code.removeprefix("0x"))
        deployment_timestamp = int(header["timestamp"], 16)
        deployments.append(
            {
                **asdict(contract),
                "deployment_block": deployment_block,
                "deployment_timestamp": deployment_timestamp,
                "deployment_time_utc": datetime.fromtimestamp(
                    deployment_timestamp, UTC
                ).isoformat(),
                "deployment_code_sha256": hashlib.sha256(code_bytes).hexdigest(),
                "binary_search_probe_count": probes,
            }
        )
    return {
        "schema_version": 1,
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "chain_id": observed_chain_id,
        "latest_block": latest_block,
        "latest_block_timestamp": int(latest_header["timestamp"], 16),
        "total_binary_search_probe_count": total_probes,
        "deployments": deployments,
    }


def estimate_full_backfill(
    deployment_report: dict[str, object],
    snapshot_calls_per_day: int = 3,
    payg_chunk_size: int = 2_000,
    usd_per_million_cu: float = 0.525,
) -> dict[str, object]:
    raw_deployments = deployment_report["deployments"]
    if not isinstance(raw_deployments, list) or not raw_deployments:
        raise ValueError("deployment report has no deployments")
    deployments = cast(list[dict[str, Any]], raw_deployments)
    start_block = min(int(item["deployment_block"]) for item in deployments)
    start_timestamp = min(int(item["deployment_timestamp"]) for item in deployments)
    end_block = int(str(deployment_report["latest_block"]))
    end_timestamp = int(str(deployment_report["latest_block_timestamp"]))
    day_count = max(1, (end_timestamp - start_timestamp) // 86_400 + 1)
    snapshot_calls = day_count * snapshot_calls_per_day
    free = estimate_cost(
        start_block,
        end_block,
        chunk_size=10,
        snapshot_calls=snapshot_calls,
        usd_per_million_cu=usd_per_million_cu,
    )
    payg = estimate_cost(
        start_block,
        end_block,
        chunk_size=payg_chunk_size,
        snapshot_calls=snapshot_calls,
        usd_per_million_cu=usd_per_million_cu,
    )
    return {
        "start_block": start_block,
        "end_block": end_block,
        "calendar_day_count": day_count,
        "snapshot_calls_per_day": snapshot_calls_per_day,
        "snapshot_call_count": snapshot_calls,
        "free": free.to_dict(),
        "payg": payg.to_dict(),
    }

