import json
from pathlib import Path

import polars as pl

from liquid_staking_basis.execution_state import audit_raw, build_canonical, estimate


def test_estimate_counts_london_day_as_legacy_block(tmp_path: Path) -> None:
    source = tmp_path / "canonical" / "daily.parquet"
    source.parent.mkdir(parents=True)
    pl.DataFrame(
        {
            "observation_date": ["2021-08-05", "2021-08-06"],
            "target_timestamp": [1628121600, 1628208000],
            "block_number": [1, 2],
            "block_timestamp": [1628121599, 1628207999],
            "block_hash": ["0x1", "0x2"],
        }
    ).write_parquet(source)
    result = estimate(
        tmp_path,
        {
            "source_daily_state_path": "canonical/daily.parquet",
            "start_date": "2021-08-05",
            "end_date": "2021-08-06",
        },
    )
    assert result["legacy_full_block_call_count"] == 1
    assert result["block_call_count"] == 3


def test_build_and_audit_execution_state(tmp_path: Path) -> None:
    source = tmp_path / "canonical" / "ethereum" / "daily" / "daily_state.parquet"
    source.parent.mkdir(parents=True)
    pl.DataFrame(
        {
            "observation_date": ["2024-01-01"],
            "target_timestamp": [1704067200],
            "block_number": [100],
            "block_timestamp": [1704067199],
            "block_hash": ["0xabc"],
        }
    ).write_parquet(source)
    config = {
        "dataset_id": "execution",
        "source_daily_state_path": str(source.relative_to(tmp_path)),
        "start_date": "2024-01-01",
        "end_date": "2024-01-01",
        "quote_input_wei": 10 * 10**18,
    }
    chunk_dir = tmp_path / "raw" / "ethereum_rpc" / "execution" / "chunks"
    manifest_dir = chunk_dir.parent / "manifests"
    chunk_dir.mkdir(parents=True)
    manifest_dir.mkdir()
    snapshot = {
        "observation_date": "2024-01-01",
        "target_timestamp": 1704067200,
        "block": {
            "number": 100,
            "timestamp": 1704067199,
            "hash": "0xabc",
            "base_fee_per_gas_wei": 20 * 10**9,
            "gas_price_per_gas_wei": 22 * 10**9,
            "gas_price_source": "base_fee_plus_fixed_priority",
        },
        "curve_legacy": {
            "quote_input_wei": 10 * 10**18,
            "eth_to_steth_output_wei": 10_100_000_000_000_000_000,
            "steth_to_eth_output_wei": 9_900_000_000_000_000_000,
        },
    }
    body = (json.dumps(snapshot) + "\n").encode()
    import hashlib

    digest = hashlib.sha256(body).hexdigest()
    path = chunk_dir / f"2024-01-01_{digest[:12]}.json"
    path.write_bytes(body)
    manifest = {
        "snapshots": [
            {
                "observation_date": "2024-01-01",
                "block_number": 100,
                "path": str(path.relative_to(tmp_path)),
                "sha256": digest,
            }
        ]
    }
    (manifest_dir / "manifest_1.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert audit_raw(tmp_path, config)["passed"] is True
    result = build_canonical(tmp_path, config)
    assert result["row_count"] == 1
    assert result["minimum_base_fee_gwei"] == 20.0
    assert result["minimum_gas_price_gwei"] == 22.0
    assert result["minimum_eth_to_steth_rate"] == 1.01
    assert result["minimum_steth_to_eth_rate"] == 0.99
