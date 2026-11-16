import hashlib
import json
from pathlib import Path
from typing import Any

from liquid_staking_basis.daily_state import (
    RpcEnvelope,
    _implementation_at,
    audit_raw_snapshots,
    encode_get_dy,
    find_last_block_before,
)


class FakeBlockClient:
    def __init__(self, timestamps: dict[int, int]) -> None:
        self.timestamps = timestamps

    def call(self, method: str, params: list[object]) -> RpcEnvelope:
        assert method == "eth_getBlockByNumber"
        number = int(str(params[0]), 16)
        block: dict[str, Any] = {
            "number": hex(number),
            "timestamp": hex(self.timestamps[number]),
            "hash": "0x" + f"{number:064x}",
        }
        return RpcEnvelope(block, b"")


def test_encode_get_dy_uses_three_abi_words() -> None:
    encoded = encode_get_dy("0x5e0d443f", 0, 1, 10**18)
    assert encoded.startswith("0x5e0d443f")
    assert len(encoded) == 2 + 8 + 64 * 3
    assert int(encoded[-64:], 16) == 10**18


def test_find_last_block_strictly_before_target() -> None:
    timestamps = {number: number * 10 for number in range(100, 10_101)}
    selected, following = find_last_block_before(
        FakeBlockClient(timestamps),
        target_timestamp=1_050,
        known_lower_block=100,
        maximum_block=10_100,
    )
    assert int(selected["number"], 16) == 104
    assert int(selected["timestamp"], 16) == 1_040
    assert int(following["number"], 16) == 105
    assert int(following["timestamp"], 16) == 1_050


def test_implementation_lookup_is_point_in_time() -> None:
    intervals = [
        {"start_block": 100, "end_block": 199, "implementation": "0x1"},
        {"start_block": 200, "end_block": 300, "implementation": "0x2"},
    ]
    assert _implementation_at(intervals, 199) == "0x1"
    assert _implementation_at(intervals, 200) == "0x2"


def test_audit_raw_snapshots_checks_manifest_and_digest(tmp_path: Path) -> None:
    dataset_id = "daily"
    chunk_dir = tmp_path / "raw" / "ethereum_rpc" / dataset_id / "chunks"
    manifest_dir = chunk_dir.parent / "manifests"
    chunk_dir.mkdir(parents=True)
    manifest_dir.mkdir()
    payload = {
        "observation_date": "2024-01-01",
        "block": {"number": 123},
    }
    body = json.dumps(payload).encode()
    digest = hashlib.sha256(body).hexdigest()
    path = chunk_dir / f"2024-01-01_{digest[:12]}.json"
    path.write_bytes(body)
    manifest = {
        "snapshots": [
            {
                "observation_date": "2024-01-01",
                "block_number": 123,
                "path": str(path.relative_to(tmp_path)),
                "sha256": digest,
            }
        ]
    }
    (manifest_dir / "manifest_1.json").write_text(json.dumps(manifest), encoding="utf-8")
    config = {"dataset_id": dataset_id, "start_date": "2024-01-01", "end_date": "2024-01-01"}
    result = audit_raw_snapshots(tmp_path, config)
    assert result["passed"] is True
    assert result["snapshot_count"] == 1
