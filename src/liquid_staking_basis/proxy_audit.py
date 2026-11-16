from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from liquid_staking_basis.cli import data_root, rpc_endpoint
from liquid_staking_basis.rpc import EthereumRpcClient


def _load_logs(root: Path, dataset_id: str) -> list[dict[str, Any]]:
    chunk_dir = root / "raw" / "ethereum_rpc" / dataset_id / "chunks"
    logs: list[dict[str, Any]] = []
    for path in sorted(chunk_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        result = payload.get("result", [])
        if not isinstance(result, list):
            raise ValueError(f"non-list RPC result in {path}")
        logs.extend(result)
    return sorted(logs, key=lambda item: (int(item["blockNumber"], 16), int(item["logIndex"], 16)))


def _word_address(value: str) -> str:
    payload = value.removeprefix("0x")
    if len(payload) < 40:
        raise ValueError("address word is too short")
    return "0x" + payload[-40:].lower()


def extract_transitions(
    logs: list[dict[str, Any]], proxy: dict[str, Any]
) -> list[dict[str, object]]:
    expected_topic = str(proxy["event_topic0"]).lower()
    transitions: list[dict[str, object]] = []
    for log in logs:
        topics = [str(value).lower() for value in log["topics"]]
        if not topics or topics[0] != expected_topic:
            continue
        if proxy["resolver"] == "aragon_implementation_call":
            if len(topics) != 3:
                raise ValueError("unexpected Aragon SetApp topic layout")
            if topics[1] != str(proxy["namespace"]).lower():
                continue
            if topics[2] != str(proxy["app_id"]).lower():
                continue
            implementation = _word_address(str(log["data"]))
        else:
            if len(topics) != 2:
                raise ValueError("unexpected EIP-1967 Upgraded topic layout")
            implementation = _word_address(topics[1])
        transitions.append(
            {
                "block_number": int(log["blockNumber"], 16),
                "implementation": implementation,
                "transaction_hash": str(log["transactionHash"]),
                "log_index": int(log["logIndex"], 16),
                "evidence": "event",
            }
        )
    return transitions


def build_intervals(
    start_block: int,
    end_block: int,
    initial_implementation: str,
    transitions: list[dict[str, object]],
) -> list[dict[str, object]]:
    states: list[dict[str, object]] = [
        {
            "block_number": start_block,
            "implementation": initial_implementation.lower(),
            "transaction_hash": None,
            "log_index": None,
            "evidence": "historical_state",
        }
    ]
    for transition in transitions:
        block_number = int(str(transition["block_number"]))
        if block_number < start_block or block_number > end_block:
            continue
        implementation = str(transition["implementation"]).lower()
        if block_number == int(str(states[-1]["block_number"])):
            states[-1] = {**transition, "implementation": implementation}
        elif implementation != states[-1]["implementation"]:
            states.append({**transition, "implementation": implementation})

    intervals: list[dict[str, object]] = []
    for index, state in enumerate(states):
        next_start = (
            int(str(states[index + 1]["block_number"]))
            if index + 1 < len(states)
            else None
        )
        intervals.append(
            {
                **state,
                "start_block": int(str(state["block_number"])),
                "end_block": next_start - 1 if next_start is not None else end_block,
            }
        )
        intervals[-1].pop("block_number")
    return intervals


def _resolve_implementation(
    client: EthereumRpcClient, proxy: dict[str, Any], block_number: int
) -> str:
    address = str(proxy["address"])
    if proxy["resolver"] == "aragon_implementation_call":
        result = client.call(
            "eth_call",
            [{"to": address, "data": str(proxy["selector"])}, hex(block_number)],
        ).result
    elif proxy["resolver"] == "eip1967_storage":
        result = client.call(
            "eth_getStorageAt", [address, str(proxy["slot"]), hex(block_number)]
        ).result
    else:
        raise ValueError(f"unsupported resolver: {proxy['resolver']}")
    return _word_address(str(result))


def _code_sha256(client: EthereumRpcClient, address: str, block_number: int) -> str:
    code = str(client.call("eth_getCode", [address, hex(block_number)]).result)
    if code == "0x":
        raise ValueError(f"no bytecode for {address} at block {block_number}")
    return hashlib.sha256(bytes.fromhex(code.removeprefix("0x"))).hexdigest()


def _block_time(client: EthereumRpcClient, block_number: int) -> str:
    block = client.call("eth_getBlockByNumber", [hex(block_number), False]).result
    timestamp = int(block["timestamp"], 16)
    return datetime.fromtimestamp(timestamp, UTC).isoformat()


def audit_proxy(
    client: EthereumRpcClient,
    root: Path,
    proxy: dict[str, Any],
    end_block: int,
) -> dict[str, object]:
    start_block = int(proxy["deployment_block"])
    raw_transitions = extract_transitions(_load_logs(root, str(proxy["dataset_id"])), proxy)
    initial = _resolve_implementation(client, proxy, start_block)
    intervals = build_intervals(start_block, end_block, initial, raw_transitions)
    errors: list[str] = []

    for interval in intervals:
        interval_start = int(str(interval["start_block"]))
        expected = str(interval["implementation"])
        observed = _resolve_implementation(client, proxy, interval_start)
        if observed != expected:
            errors.append(
                f"implementation mismatch at {interval_start}: expected {expected}, got {observed}"
            )
        interval["start_time_utc"] = _block_time(client, interval_start)
        interval["implementation_code_sha256"] = _code_sha256(
            client, expected, interval_start
        )

    current = _resolve_implementation(client, proxy, end_block)
    if current != str(intervals[-1]["implementation"]):
        errors.append(f"end-block implementation mismatch: {current}")
    proxy_code_start = _code_sha256(client, str(proxy["address"]), start_block)
    proxy_code_end = _code_sha256(client, str(proxy["address"]), end_block)
    if proxy_code_start != proxy_code_end:
        errors.append("proxy shell bytecode changed between deployment and audit end")
    return {
        "id": proxy["id"],
        "address": str(proxy["address"]).lower(),
        "architecture": str(proxy["resolver"]),
        "source": proxy["source"],
        "deployment_block": start_block,
        "audit_end_block": end_block,
        "raw_upgrade_event_count": len(raw_transitions),
        "implementation_interval_count": len(intervals),
        "intervals": intervals,
        "proxy_code_sha256": proxy_code_start,
        "current_implementation": current,
        "errors": errors,
        "passed": not errors,
    }


def audit_direct_contract(
    client: EthereumRpcClient, contract: dict[str, Any], end_block: int
) -> dict[str, object]:
    start_block = int(contract["deployment_block"])
    start_hash = _code_sha256(client, str(contract["address"]), start_block)
    end_hash = _code_sha256(client, str(contract["address"]), end_block)
    errors = [] if start_hash == end_hash else ["runtime bytecode hash changed"]
    return {
        "id": contract["id"],
        "address": str(contract["address"]).lower(),
        "architecture": "direct_deployment",
        "source": contract["source"],
        "deployment_block": start_block,
        "audit_end_block": end_block,
        "deployment_code_sha256": start_hash,
        "end_code_sha256": end_hash,
        "errors": errors,
        "passed": not errors,
    }


def run_audit(
    client: EthereumRpcClient, root: Path, config_path: Path
) -> dict[str, object]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    end_block = int(config["audit_end_block"])
    proxies = [audit_proxy(client, root, proxy, end_block) for proxy in config["proxies"]]
    direct = [
        audit_direct_contract(client, contract, end_block)
        for contract in config["direct_contracts"]
    ]
    passed = all(bool(item["passed"]) for item in [*proxies, *direct])
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "audit_end_block": end_block,
        "proxies": proxies,
        "direct_contracts": direct,
        "passed": passed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit historical implementation intervals")
    parser.add_argument("--config", type=Path, default=Path("config/proxy_audit.json"))
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with EthereumRpcClient(rpc_endpoint()) as client:
        result = run_audit(client, data_root(args.data_root), args.config)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
