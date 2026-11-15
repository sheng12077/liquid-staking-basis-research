import json
from pathlib import Path

from liquid_staking_basis.registry import (
    discover_deployments,
    estimate_full_backfill,
    find_deployment_block,
)
from liquid_staking_basis.rpc import RpcEnvelope


class FakeRegistryClient:
    def __init__(self, deployment_block: int = 37, latest_block: int = 100) -> None:
        self.deployment_block = deployment_block
        self.latest_block = latest_block

    def call(self, method: str, params: list[object]) -> RpcEnvelope:
        if method == "eth_chainId":
            result: object = "0x1"
        elif method == "eth_blockNumber":
            result = hex(self.latest_block)
        elif method == "eth_getCode":
            block = int(str(params[1]), 16)
            result = "0x6000" if block >= self.deployment_block else "0x"
        elif method == "eth_getBlockByNumber":
            block = int(str(params[0]), 16)
            result = {"timestamp": hex(1_600_000_000 + block * 12)}
        else:
            raise AssertionError(method)
        return RpcEnvelope(result, b"{}")


def test_find_deployment_block_returns_first_block_with_code() -> None:
    block, probes = find_deployment_block(FakeRegistryClient(), "0x" + "1" * 40, 100)

    assert block == 37
    assert probes <= 9


def test_discover_deployments_and_estimate_backfill(tmp_path: Path) -> None:
    registry = tmp_path / "contracts.json"
    registry.write_text(
        json.dumps(
            {
                "chain_id": 1,
                "contracts": [
                    {
                        "id": "sample",
                        "address": "0x" + "1" * 40,
                        "kind": "test",
                        "official_source": "https://example.com",
                    }
                ],
            }
        )
    )

    report = discover_deployments(FakeRegistryClient(), registry)
    estimate = estimate_full_backfill(report, snapshot_calls_per_day=2)

    assert report["chain_id"] == 1
    assert report["deployments"][0]["deployment_block"] == 37
    assert estimate["start_block"] == 37
    assert estimate["free"]["total_compute_units"] > estimate["payg"]["total_compute_units"]

