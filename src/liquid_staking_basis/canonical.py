from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import polars as pl

from liquid_staking_basis.rpc import RpcEnvelope

CURVE_TOKEN_EXCHANGE = "0x8b3e96f2b889fa771c53c981b40daf005f63f637f1869f707052d15a3dd97140"
WITHDRAWAL_REQUESTED = "0xf0cb471f23fb74ea44b8252eb1881a2dca546288d9f6e90d1a0e82fe0ed342ab"
WITHDRAWALS_FINALIZED = "0x197874c72af6a06fb0aa4fab45fd39c7cb61ac0992159872dc3295207da7e9eb"
WITHDRAWAL_CLAIMED = "0x6ad26c5e238e7d002799f9a5db07e81ef14e37386ae03496d7a7ef04713e145b"

CURVE_POOLS = {
    "0x828b154032950c8ff7cf8085d841723db2696056": ("WETH", "stETH"),
    "0xdc24316b9ae028f1497c275eb9192a3ea0f67022": ("ETH", "stETH"),
}
WITHDRAWAL_QUEUE = "0x889edc2edab5f40e902b864ad4d7ade8e412f9b1"


class RpcCaller(Protocol):
    def call(self, method: str, params: list[object]) -> RpcEnvelope: ...


def _words(data: str) -> list[int]:
    payload = data.removeprefix("0x")
    if len(payload) % 64 != 0:
        raise ValueError("ABI data length is not a multiple of 32 bytes")
    return [int(payload[index : index + 64], 16) for index in range(0, len(payload), 64)]


def _topic_uint(topic: str) -> int:
    return int(topic, 16)


def _topic_address(topic: str) -> str:
    return "0x" + topic[-40:].lower()


def decode_log(log: dict[str, Any]) -> tuple[str, dict[str, object]]:
    address = str(log["address"]).lower()
    topics = [str(item).lower() for item in log["topics"]]
    if not topics:
        return "unsupported", {}
    topic0 = topics[0]
    values = _words(str(log["data"]))

    if address in CURVE_POOLS and topic0 == CURVE_TOKEN_EXCHANGE:
        if len(topics) != 2 or len(values) != 4:
            raise ValueError("unexpected Curve TokenExchange layout")
        sold_id, tokens_sold, bought_id, tokens_bought = values
        coins = CURVE_POOLS[address]
        if sold_id >= len(coins) or bought_id >= len(coins):
            raise ValueError("Curve coin index is outside registered pool schema")
        return "curve_swap", {
            "event_type": "TokenExchange",
            "buyer": _topic_address(topics[1]),
            "sold_id": sold_id,
            "sold_asset": coins[sold_id],
            "tokens_sold_raw": str(tokens_sold),
            "tokens_sold": tokens_sold / 10**18,
            "bought_id": bought_id,
            "bought_asset": coins[bought_id],
            "tokens_bought_raw": str(tokens_bought),
            "tokens_bought": tokens_bought / 10**18,
        }

    if address == WITHDRAWAL_QUEUE and topic0 == WITHDRAWAL_REQUESTED:
        if len(topics) != 4 or len(values) != 2:
            raise ValueError("unexpected WithdrawalRequested layout")
        return "withdrawal", {
            "event_type": "WithdrawalRequested",
            "request_id": _topic_uint(topics[1]),
            "requestor": _topic_address(topics[2]),
            "owner": _topic_address(topics[3]),
            "amount_steth_raw": str(values[0]),
            "amount_steth": values[0] / 10**18,
            "amount_shares_raw": str(values[1]),
            "amount_shares": values[1] / 10**18,
        }

    if address == WITHDRAWAL_QUEUE and topic0 == WITHDRAWALS_FINALIZED:
        if len(topics) != 3 or len(values) != 3:
            raise ValueError("unexpected WithdrawalsFinalized layout")
        return "withdrawal", {
            "event_type": "WithdrawalsFinalized",
            "from_request_id": _topic_uint(topics[1]),
            "to_request_id": _topic_uint(topics[2]),
            "amount_eth_locked_raw": str(values[0]),
            "amount_eth_locked": values[0] / 10**18,
            "shares_to_burn_raw": str(values[1]),
            "shares_to_burn": values[1] / 10**18,
            "finalization_timestamp": values[2],
        }

    if address == WITHDRAWAL_QUEUE and topic0 == WITHDRAWAL_CLAIMED:
        if len(topics) != 4 or len(values) != 1:
            raise ValueError("unexpected WithdrawalClaimed layout")
        return "withdrawal", {
            "event_type": "WithdrawalClaimed",
            "request_id": _topic_uint(topics[1]),
            "owner": _topic_address(topics[2]),
            "receiver": _topic_address(topics[3]),
            "amount_eth_raw": str(values[0]),
            "amount_eth": values[0] / 10**18,
        }
    return "unsupported", {}


def _load_raw_logs(data_root: Path, dataset_id: str) -> list[dict[str, Any]]:
    chunk_dir = data_root / "raw" / "ethereum_rpc" / dataset_id / "chunks"
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted(chunk_dir.glob("*.json")):
        payload = json.loads(path.read_bytes())
        for log in payload.get("result", []):
            key = (str(log["transactionHash"]), str(log["logIndex"]))
            unique[key] = log
    return sorted(
        unique.values(),
        key=lambda item: (int(item["blockNumber"], 16), int(item["logIndex"], 16)),
    )


def _common_metadata(
    log: dict[str, Any], block: dict[str, Any], receipt: dict[str, Any]
) -> dict[str, object]:
    timestamp = int(block["timestamp"], 16)
    gas_used = int(receipt["gasUsed"], 16)
    gas_price = int(receipt.get("effectiveGasPrice", "0x0"), 16)
    return {
        "block_number": int(log["blockNumber"], 16),
        "block_timestamp": timestamp,
        "block_time_utc": datetime.fromtimestamp(timestamp, UTC).isoformat(),
        "block_hash": str(log["blockHash"]),
        "transaction_hash": str(log["transactionHash"]),
        "transaction_index": int(log["transactionIndex"], 16),
        "log_index": int(log["logIndex"], 16),
        "contract_address": str(log["address"]).lower(),
        "topic0": str(log["topics"][0]).lower(),
        "transaction_status": int(receipt["status"], 16),
        "transaction_gas_used": gas_used,
        "transaction_effective_gas_price_wei": gas_price,
        "transaction_fee_wei": str(gas_used * gas_price),
        "block_base_fee_per_gas_wei": int(block.get("baseFeePerGas", "0x0"), 16),
    }


def build_canonical_dataset(
    client: RpcCaller, data_root: Path, dataset_id: str
) -> dict[str, object]:
    logs = _load_raw_logs(data_root, dataset_id)
    if not logs:
        raise ValueError("raw dataset contains no logs")
    block_cache: dict[str, dict[str, Any]] = {}
    receipt_cache: dict[str, dict[str, Any]] = {}
    swaps: list[dict[str, object]] = []
    withdrawals: list[dict[str, object]] = []
    unsupported: list[dict[str, object]] = []

    for log in logs:
        block_number = str(log["blockNumber"])
        tx_hash = str(log["transactionHash"])
        if block_number not in block_cache:
            block_cache[block_number] = client.call(
                "eth_getBlockByNumber", [block_number, False]
            ).result
        if tx_hash not in receipt_cache:
            receipt_cache[tx_hash] = client.call(
                "eth_getTransactionReceipt", [tx_hash]
            ).result
        common = _common_metadata(log, block_cache[block_number], receipt_cache[tx_hash])
        category, decoded = decode_log(log)
        row = {**common, **decoded}
        if category == "curve_swap":
            swaps.append(row)
        elif category == "withdrawal":
            withdrawals.append(row)
        else:
            unsupported.append(
                {
                    **common,
                    "topics_json": json.dumps(log["topics"]),
                    "data": str(log["data"]),
                }
            )

    output_dir = data_root / "canonical" / "ethereum" / dataset_id
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str | None] = {}
    for name, rows in (
        ("curve_swaps", swaps),
        ("withdrawal_events", withdrawals),
        ("unsupported_events", unsupported),
    ):
        if rows:
            path = output_dir / f"{name}.parquet"
            pl.DataFrame(rows, infer_schema_length=None).write_parquet(
                path, compression="zstd", statistics=True
            )
            paths[name] = str(path)
        else:
            paths[name] = None
    summary = {
        "dataset_id": dataset_id,
        "raw_log_count": len(logs),
        "curve_swap_count": len(swaps),
        "withdrawal_event_count": len(withdrawals),
        "unsupported_event_count": len(unsupported),
        "unique_block_count": len(block_cache),
        "unique_transaction_count": len(receipt_cache),
        "paths": paths,
    }
    (output_dir / "canonical_manifest.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary

