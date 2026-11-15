from pathlib import Path

import pytest

from liquid_staking_basis.backfill import (
    BackfillJob,
    estimate_log_cost_usd,
    load_jobs,
    request_count,
)


def test_load_jobs_and_combined_topic_filters(tmp_path: Path) -> None:
    config = tmp_path / "jobs.json"
    config.write_text(
        """{
          "jobs": [{
            "dataset_id": "events",
            "addresses": ["0x1111111111111111111111111111111111111111"],
            "topics": [
              "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
              "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            ],
            "start_block": 100
          }]
        }""",
        encoding="utf-8",
    )
    jobs = load_jobs(config)
    assert len(jobs) == 1
    assert len(jobs[0].topics) == 2
    assert request_count(jobs, end_block=4_099, chunk_size=2_000) == 2


def test_request_count_combines_jobs() -> None:
    jobs = (
        BackfillJob("a", ("0x" + "1" * 40,), ("0x" + "a" * 64,), 1),
        BackfillJob("b", ("0x" + "2" * 40,), ("0x" + "b" * 64,), 2_001),
    )
    assert request_count(jobs, end_block=4_000, chunk_size=2_000) == 3
    assert estimate_log_cost_usd(3, 0.525) == pytest.approx(0.0000945)


def test_production_chunk_size_is_bounded() -> None:
    job = BackfillJob("a", ("0x" + "1" * 40,), ("0x" + "a" * 64,), 1)
    with pytest.raises(ValueError, match="2,000"):
        request_count((job,), end_block=4_000, chunk_size=2_001)
