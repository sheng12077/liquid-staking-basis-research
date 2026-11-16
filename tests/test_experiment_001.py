from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from liquid_staking_basis.experiment_001 import FuturesPosition, Stress, metrics, round_down


def test_round_down_respects_contract_step() -> None:
    assert round_down(1.2349, 0.001) == 1.234
    assert round_down(1.234, 0.001) == 1.234


def test_linear_short_accounting_and_costs() -> None:
    position = FuturesPosition(wallet_cash=6000.0)
    opened = position.trade(2.0, 2000.0, 0.0005, 0.0005)
    assert opened["notional"] == 4000.0
    assert position.wallet_cash == 5996.0
    assert position.equity(1900.0) == 6196.0
    funding = position.book_funding(0.0001, 1900.0, 1.0)
    assert funding == 0.38
    closed = position.trade(0.0, 1900.0, 0.0005, 0.0005)
    assert closed["notional"] == 3800.0
    assert abs(position.wallet_cash - 6192.58) < 1e-10


def test_positive_funding_stress_does_not_reduce_negative_payment() -> None:
    position = FuturesPosition(wallet_cash=100.0, quantity=1.0, reference_price=1000.0)
    assert position.book_funding(0.001, 1000.0, 0.5) == 0.5
    assert position.book_funding(-0.001, 1000.0, 0.5) == -1.0


def test_metrics_include_initial_cost_and_drawdown() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    frame = pl.DataFrame(
        {
            "timestamp": [start + timedelta(days=index) for index in range(367)],
            "nav": [100.0] + [99.0] * 365 + [110.0],
        }
    )
    result = metrics(frame)
    assert result["total_return"] == pytest.approx(0.10)
    assert result["max_drawdown"] == pytest.approx(-0.01)
    assert result["minimum_rolling_365d_return"] == pytest.approx(-0.01)


def test_registered_stress_names_are_stable() -> None:
    assert Stress().name == "primary"
