from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from liquid_staking_basis.visualization import drawdown, effective_buffer, normalized_nav


def test_normalized_nav_and_drawdown() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    frame = pl.DataFrame(
        {
            "timestamp": [start + timedelta(days=index) for index in range(3)],
            "nav": [100.0, 110.0, 99.0],
        }
    )
    assert normalized_nav(frame)["normalized_nav"].to_list() == pytest.approx([100.0, 110.0, 99.0])
    assert drawdown(frame)["drawdown"].to_list() == pytest.approx([0.0, 0.0, -0.1])


def test_effective_buffer_uses_daily_adverse_minimum() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    frame = pl.DataFrame(
        {
            "timestamp": [start + timedelta(hours=index) for index in range(3)],
            "short_quantity_eth": [1.0, 1.0, 1.0],
            "operational_buffer": [0.40, 0.30, 0.35],
            "risk_operational_buffer": [0.38, 0.20, 0.33],
        }
    )
    result = effective_buffer(frame)
    assert result.height == 1
    assert result["buffer"][0] == pytest.approx(0.20)
