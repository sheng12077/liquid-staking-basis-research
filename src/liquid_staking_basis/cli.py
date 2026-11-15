from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from liquid_staking_basis.cost import estimate_cost
from liquid_staking_basis.rpc import EthereumRpcClient, audit_dataset, fetch_logs

DEFAULT_DATA_ROOT = Path("/home/sheng77/working_space/quant_research/data")
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def load_local_env(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        if key in {"ETHEREUM_RPC_URL", "QUANT_RESEARCH_DATA_ROOT"}:
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def rpc_endpoint() -> str:
    load_local_env()
    endpoint = os.environ.get("ETHEREUM_RPC_URL")
    if not endpoint or endpoint.endswith("/replace-me"):
        raise SystemExit("Set ETHEREUM_RPC_URL in the local .env file")
    return endpoint


def data_root(argument: Path | None) -> Path:
    load_local_env()
    if argument is not None:
        return argument
    configured = os.environ.get("QUANT_RESEARCH_DATA_ROOT")
    return Path(configured) if configured else DEFAULT_DATA_ROOT


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Liquid-staking basis data pilot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("rpc-check", help="Verify chain and archive-state access")
    check.add_argument("--archive-block", type=int, default=12_000_000)

    estimate = subparsers.add_parser("estimate", help="Estimate RPC calls and compute units")
    estimate.add_argument("--start-block", type=int, required=True)
    estimate.add_argument("--end-block", type=int, required=True)
    estimate.add_argument("--chunk-size", type=int, default=10)
    estimate.add_argument("--log-filters", type=int, default=1)
    estimate.add_argument("--snapshot-calls", type=int, default=0)
    estimate.add_argument("--usd-per-million-cu", type=float, default=0.525)

    fetch = subparsers.add_parser("fetch-logs", help="Fetch resumable raw eth_getLogs chunks")
    fetch.add_argument("--dataset-id", required=True)
    fetch.add_argument("--address", action="append", required=True, dest="addresses")
    fetch.add_argument("--topic")
    fetch.add_argument("--start-block", type=int, required=True)
    fetch.add_argument("--end-block", type=int, required=True)
    fetch.add_argument("--chunk-size", type=int, default=10)
    fetch.add_argument("--plan", choices=("free", "payg"), default="free")
    fetch.add_argument("--request-delay", type=float, default=0.15)
    fetch.add_argument("--data-root", type=Path)

    audit = subparsers.add_parser("audit", help="Verify raw chunks and manifests")
    audit.add_argument("--dataset-id", required=True)
    audit.add_argument("--data-root", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "estimate":
        estimate_result = estimate_cost(
            args.start_block,
            args.end_block,
            args.chunk_size,
            args.log_filters,
            args.snapshot_calls,
            args.usd_per_million_cu,
        )
        print(json.dumps(estimate_result.to_dict(), indent=2, sort_keys=True))
        return

    if args.command == "audit":
        audit_result = audit_dataset(data_root(args.data_root), args.dataset_id)
        print(json.dumps(audit_result, indent=2, sort_keys=True))
        if not audit_result["passed"]:
            raise SystemExit(1)
        return

    endpoint = rpc_endpoint()
    with EthereumRpcClient(endpoint) as client:
        if args.command == "rpc-check":
            chain_id = int(client.call("eth_chainId", []).result, 16)
            latest_block = int(client.call("eth_blockNumber", []).result, 16)
            archive_balance = client.call(
                "eth_getBalance", [ZERO_ADDRESS, hex(args.archive_block)]
            ).result
            print(
                json.dumps(
                    {
                        "archive_balance_query_ok": isinstance(archive_balance, str),
                        "archive_block": args.archive_block,
                        "chain_id": chain_id,
                        "latest_block": latest_block,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return

        fetch_result = fetch_logs(
            client=client,
            data_root=data_root(args.data_root),
            dataset_id=args.dataset_id,
            addresses=tuple(args.addresses),
            topic=args.topic,
            start_block=args.start_block,
            end_block=args.end_block,
            chunk_size=args.chunk_size,
            plan=args.plan,
            request_delay_seconds=args.request_delay,
        )
        print(json.dumps(fetch_result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

