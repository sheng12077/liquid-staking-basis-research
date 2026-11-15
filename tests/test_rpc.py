import json
from pathlib import Path
from typing import Any

import pytest

from liquid_staking_basis.rpc import (
    RpcEnvelope,
    audit_dataset,
    fetch_logs,
    validate_fetch_inputs,
)


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[object]]] = []

    def call(self, method: str, params: list[object]) -> RpcEnvelope:
        self.calls.append((method, params))
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": []}).encode()
        return RpcEnvelope([], body)


def test_free_plan_rejects_wide_chunks() -> None:
    with pytest.raises(ValueError, match="cannot exceed 10"):
        validate_fetch_inputs(
            "pilot",
            ("0x0000000000000000000000000000000000000000",),
            None,
            1,
            20,
            11,
            "free",
        )


def test_fetch_logs_is_resumable_and_manifest_has_no_endpoint(tmp_path: Path) -> None:
    client = FakeClient()
    kwargs: dict[str, Any] = {
        "client": client,
        "data_root": tmp_path,
        "dataset_id": "pilot",
        "addresses": ("0x0000000000000000000000000000000000000000",),
        "start_block": 100,
        "end_block": 119,
        "chunk_size": 10,
        "request_delay_seconds": 0,
    }

    first = fetch_logs(**kwargs)
    second = fetch_logs(**kwargs)

    assert first["downloaded_chunk_count"] == 2
    assert second["downloaded_chunk_count"] == 0
    assert second["skipped_chunk_count"] == 2
    assert len(client.calls) == 2
    manifests = sorted((tmp_path / "raw/ethereum_rpc/pilot/manifests").glob("*.json"))
    assert len(manifests) == 2
    assert "RPC_URL" not in manifests[-1].read_text()
    audit = audit_dataset(tmp_path, "pilot")
    assert audit["passed"] is True
    assert audit["chunk_count"] == 2
    assert audit["manifest_reference_count"] == 4


def test_audit_detects_corrupted_chunk(tmp_path: Path) -> None:
    client = FakeClient()
    fetch_logs(
        client=client,
        data_root=tmp_path,
        dataset_id="pilot",
        addresses=("0x0000000000000000000000000000000000000000",),
        start_block=100,
        end_block=109,
        request_delay_seconds=0,
    )
    chunk = next((tmp_path / "raw/ethereum_rpc/pilot/chunks").glob("*.json"))
    chunk.write_text("{}")

    audit = audit_dataset(tmp_path, "pilot")

    assert audit["passed"] is False
    assert audit["errors"]

