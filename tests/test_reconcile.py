import hashlib
import json
from pathlib import Path

from liquid_staking_basis.reconcile import reconcile_dataset


def test_reconcile_complete_filtered_dataset(tmp_path: Path) -> None:
    dataset_id = "events"
    dataset_dir = tmp_path / "raw" / "ethereum_rpc" / dataset_id
    chunk_dir = dataset_dir / "chunks"
    manifest_dir = dataset_dir / "manifests"
    chunk_dir.mkdir(parents=True)
    manifest_dir.mkdir()
    address = "0x" + "1" * 40
    topic = "0x" + "a" * 64
    event = {
        "address": address,
        "blockNumber": "0x64",
        "transactionHash": "0x" + "b" * 64,
        "logIndex": "0x0",
        "topics": [topic],
    }
    body = json.dumps({"result": [event]}).encode()
    digest = hashlib.sha256(body).hexdigest()
    chunk_path = chunk_dir / f"0000000100_0000000109_{digest[:12]}.json"
    chunk_path.write_bytes(body)
    manifest = {
        "dataset_id": dataset_id,
        "addresses": [address],
        "topic0s": [topic],
        "start_block": 100,
        "end_block": 109,
        "chunks": [
            {
                "from_block": 100,
                "to_block": 109,
                "path": str(chunk_path.relative_to(tmp_path)),
                "sha256": digest,
                "log_count": 1,
            }
        ],
    }
    (manifest_dir / "manifest_1.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = reconcile_dataset(tmp_path, dataset_id)

    assert result["passed"] is True
    assert result["unique_event_count"] == 1
    assert result["duplicate_event_count"] == 0
