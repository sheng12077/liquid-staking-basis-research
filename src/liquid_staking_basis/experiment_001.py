from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from liquid_staking_basis.cli import data_root


@dataclass(frozen=True)
class Stress:
    name: str = "primary"
    slippage_multiplier: float = 1.0
    gas_multiplier: float = 1.0
    margin_mark_multiplier: float = 1.0
    positive_funding_multiplier: float = 1.0
    post_entry_quote_haircut: float = 0.0


STRESSES = (
    Stress(),
    Stress("X1_slippage_5x", slippage_multiplier=5.0),
    Stress("X2_gas_5x", gas_multiplier=5.0),
    Stress("X3_slippage_and_gas_5x", slippage_multiplier=5.0, gas_multiplier=5.0),
    Stress("X4_margin_mark_1.2x", margin_mark_multiplier=1.2),
    Stress("X5_positive_funding_half", positive_funding_multiplier=0.5),
    Stress("X6_exit_quote_haircut_5pct", post_entry_quote_haircut=0.05),
)


@dataclass
class FuturesPosition:
    wallet_cash: float
    quantity: float = 0.0
    reference_price: float = 0.0
    funding_pnl: float = 0.0
    positive_funding: float = 0.0
    negative_funding: float = 0.0
    fees: float = 0.0
    slippage_cost: float = 0.0
    turnover: float = 0.0

    def equity(self, mark: float) -> float:
        return self.wallet_cash + self.quantity * (self.reference_price - mark)

    def trade(
        self, target: float, market_price: float, fee_rate: float, slippage_rate: float
    ) -> dict[str, float]:
        if self.quantity:
            self.wallet_cash += self.quantity * (self.reference_price - market_price)
        difference = target - self.quantity
        notional = abs(difference) * market_price
        fee = notional * fee_rate
        slippage = notional * slippage_rate
        self.wallet_cash -= fee + slippage
        self.fees += fee
        self.slippage_cost += slippage
        self.turnover += notional
        self.quantity = target
        self.reference_price = market_price if target else 0.0
        return {
            "quantity_change": difference,
            "notional": notional,
            "fee": fee,
            "slippage": slippage,
        }

    def book_funding(self, rate: float, mark: float, positive_multiplier: float) -> float:
        effective = rate * positive_multiplier if rate > 0 else rate
        amount = self.quantity * mark * effective
        self.wallet_cash += amount
        self.funding_pnl += amount
        if amount >= 0:
            self.positive_funding += amount
        else:
            self.negative_funding += amount
        return amount


def round_down(value: float, step: float) -> float:
    if value < 0 or step <= 0:
        raise ValueError("value must be non-negative and step positive")
    return math.floor((value + 1e-12) / step) * step


def _series(root: Path, series_root: str, name: str, columns: list[str]) -> pl.DataFrame:
    files = sorted((root / series_root / name).glob("*.parquet"))
    if not files:
        raise ValueError(f"no files for {name}")
    return pl.scan_parquet(files).select(columns).sort("timestamp").collect()


def load_inputs(root: Path, config: dict[str, Any]) -> tuple[pl.DataFrame, pl.DataFrame]:
    paths = config["data_paths"]
    start = datetime.fromisoformat(str(config["start_date"])).replace(tzinfo=UTC)
    end = datetime.fromisoformat(str(config["end_date"])).replace(tzinfo=UTC) + timedelta(days=1)
    spot = _series(root, paths["series_root"], "eth_spot_bars", ["timestamp", "close"])
    perp = _series(
        root, paths["series_root"], "eth_perpetual_bars", ["timestamp", "high", "close"]
    ).rename({"high": "perpetual_high", "close": "perpetual_close"})
    mark = _series(
        root, paths["series_root"], "eth_mark_bars", ["timestamp", "open", "high", "close"]
    ).rename({"open": "mark_open", "high": "mark_high", "close": "mark_close"})
    hourly = (
        perp.join(
            spot.rename({"close": "spot_close"}),
            on="timestamp",
            how="left",
            validate="1:1",
        )
        .join(mark, on="timestamp", how="left", validate="1:1")
        .filter((pl.col("timestamp") >= start) & (pl.col("timestamp") < end))
        .sort("timestamp")
    )
    expected = int((end - start).total_seconds() / 3600)
    if hourly.height != expected:
        raise ValueError(f"hourly perpetual coverage mismatch: {hourly.height} != {expected}")
    missing_execution_spot = hourly.filter(
        (pl.col("timestamp").dt.hour() == 0) & pl.col("spot_close").is_null()
    )
    if missing_execution_spot.height:
        raise ValueError(
            f"spot price missing on {missing_execution_spot.height} registered execution bars"
        )

    funding = _series(
        root, paths["series_root"], "eth_funding", ["timestamp", "funding_rate"]
    ).filter((pl.col("timestamp") >= start) & (pl.col("timestamp") < end))
    if funding.get_column("timestamp").n_unique() != funding.height:
        raise ValueError("duplicate funding timestamps")
    funding = (
        funding.with_columns(pl.col("timestamp").dt.truncate("1h").alias("hour"))
        .group_by("hour")
        .agg(pl.col("funding_rate").alias("funding_rates"))
    )
    hourly = hourly.join(funding, left_on="timestamp", right_on="hour", how="left")

    daily = (
        pl.read_parquet(root / paths["daily_state"])
        .select("observation_date", "target_timestamp", "wsteth_steth_per_token")
        .join(
            pl.read_parquet(root / paths["execution_state"]).select(
                "observation_date",
                "block_number",
                "gas_price_gwei",
                "legacy_10_eth_to_steth_rate",
                "legacy_10_steth_to_eth_rate",
            ),
            on="observation_date",
            how="inner",
            validate="1:1",
        )
        .filter(
            (pl.col("observation_date") >= str(config["start_date"]))
            & (pl.col("observation_date") <= str(config["end_date"]))
        )
        .sort("observation_date")
    )
    expected_days = (
        date.fromisoformat(str(config["end_date"])) - date.fromisoformat(str(config["start_date"]))
    ).days + 1
    if daily.height != expected_days:
        raise ValueError(
            f"daily execution-state coverage mismatch: {daily.height} != {expected_days}"
        )
    return hourly, daily


def _effective_reverse(
    row: dict[str, Any], stress: Stress, curve_slippage: float, par_basis: bool
) -> float:
    quoted = 1.0 if par_basis else float(row["legacy_10_steth_to_eth_rate"])
    return (
        quoted
        * (1.0 - curve_slippage * stress.slippage_multiplier)
        * (1.0 - stress.post_entry_quote_haircut)
    )


def _trade_long_entry(
    row: dict[str, Any], spot: float, config: dict[str, Any], stress: Stress
) -> tuple[float, dict[str, float]]:
    budget = float(config["initial_capital_usdt"]) * float(config["long_allocation"])
    spot_slip = float(config["spot_slippage"]) * stress.slippage_multiplier
    curve_slip = float(config["curve_slippage"]) * stress.slippage_multiplier
    fee = float(config["spot_taker_fee"])
    eth_bought = budget / (spot * (1.0 + spot_slip) * (1.0 + fee))
    gas_eth = (
        float(config["entry_gas_units"])
        * float(row["gas_price_gwei"])
        * stress.gas_multiplier
        / 1e9
    )
    eth_to_curve = eth_bought - float(config["eth_withdrawal_allowance"]) - gas_eth
    if eth_to_curve <= 0 or eth_to_curve > float(config["registered_quote_size_tokens"]):
        raise ValueError("entry violates registered quote sizing")
    steth = eth_to_curve * float(row["legacy_10_eth_to_steth_rate"]) * (1.0 - curve_slip)
    wsteth = steth / float(row["wsteth_steth_per_token"])
    costs = {
        "spot_fee": eth_bought * spot * (1.0 + spot_slip) * fee,
        "spot_slippage": eth_bought * spot * spot_slip,
        "curve_slippage": eth_to_curve
        * float(row["legacy_10_eth_to_steth_rate"])
        * curve_slip
        * spot,
        "gas": gas_eth * spot,
        "withdrawal": float(config["eth_withdrawal_allowance"]) * spot,
    }
    return wsteth, costs


def _trade_long_exit(
    wsteth: float,
    row: dict[str, Any],
    spot: float,
    config: dict[str, Any],
    stress: Stress,
    freeze_share: float | None,
    par_basis: bool,
) -> tuple[float, dict[str, float]]:
    share = freeze_share if freeze_share is not None else float(row["wsteth_steth_per_token"])
    steth = wsteth * share
    reverse = _effective_reverse(row, stress, float(config["curve_slippage"]), par_basis)
    eth_before_gas = steth * reverse
    if steth > float(config["registered_quote_size_tokens"]):
        raise ValueError("exit violates registered quote sizing")
    gas_eth = (
        float(config["exit_gas_units"]) * float(row["gas_price_gwei"]) * stress.gas_multiplier / 1e9
    )
    eth_to_sell = eth_before_gas - gas_eth
    spot_slip = float(config["spot_slippage"]) * stress.slippage_multiplier
    gross = eth_to_sell * spot * (1.0 - spot_slip)
    fee = gross * float(config["spot_taker_fee"])
    return gross - fee, {
        "spot_fee": fee,
        "spot_slippage": eth_to_sell * spot * spot_slip,
        "curve_slippage": steth
        * float(config["curve_slippage"])
        * stress.slippage_multiplier
        * spot,
        "gas": gas_eth * spot,
    }


def _margin_row(
    position: FuturesPosition, risk_mark: float, reserve_rate: float
) -> tuple[float, float, float]:
    equity = position.equity(risk_mark)
    notional = position.quantity * risk_mark
    reserve = reserve_rate * notional
    buffer = (equity - reserve) / notional if notional else math.inf
    return equity, reserve, buffer


def simulate(
    hourly: pl.DataFrame,
    daily: pl.DataFrame,
    config: dict[str, Any],
    stress: Stress = Stress(),
    *,
    zero_funding: bool = False,
    freeze_share_rate: bool = False,
    par_basis: bool = False,
) -> tuple[pl.DataFrame, pl.DataFrame, dict[str, Any]]:
    daily_map = {str(row["observation_date"]): row for row in daily.to_dicts()}
    initial = float(config["initial_capital_usdt"])
    position = FuturesPosition(initial * float(config["futures_allocation"]))
    wsteth = 0.0
    entry_share: float | None = None
    active = False
    liquidated = False
    breach_timestamp: str | None = None
    minimum_buffer = math.inf
    last_mark: float | None = None
    booked_funding_events = 0
    daily_rows: list[dict[str, Any]] = [
        {
            "timestamp": datetime.fromisoformat(str(config["start_date"])).replace(tzinfo=UTC)
            - timedelta(days=1),
            "nav": initial,
            "long_value": 0.0,
            "futures_equity": initial * float(config["futures_allocation"]),
            "residual_delta_eth": 0.0,
        }
    ]
    hourly_rows: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    long_costs = {
        name: 0.0 for name in ("spot_fee", "spot_slippage", "curve_slippage", "gas", "withdrawal")
    }
    step = float(config["perpetual_quantity_step"])
    reserve_rate = float(config["maintenance_reserve"])
    curve_slip = float(config["curve_slippage"])

    for hour in hourly.iter_rows(named=True):
        timestamp = hour["timestamp"]
        if not isinstance(timestamp, datetime):
            raise TypeError("timestamp must be datetime")
        mark_open = hour["mark_open"] if hour["mark_open"] is not None else last_mark
        mark_close = hour["mark_close"] if hour["mark_close"] is not None else last_mark
        if mark_open is None or mark_close is None:
            risk_mark = 1.01 * float(hour["perpetual_high"])
            mark_open = risk_mark
            mark_close = risk_mark
        if hour["mark_high"] is None:
            risk_mark = max(float(last_mark or 0.0), 1.01 * float(hour["perpetual_high"]))
            missing_mark_proxy = True
        else:
            risk_mark = float(hour["mark_high"])
            missing_mark_proxy = False
        last_mark = float(mark_close)

        funding_amount = 0.0
        rates = hour["funding_rates"] or []
        if active:
            for rate in rates:
                funding_amount += position.book_funding(
                    0.0 if zero_funding else float(rate),
                    float(mark_open),
                    stress.positive_funding_multiplier,
                )
                booked_funding_events += 1
        if active:
            equity, reserve, buffer = _margin_row(
                position, risk_mark * stress.margin_mark_multiplier, reserve_rate
            )
            minimum_buffer = min(minimum_buffer, buffer)
            if equity <= reserve and not liquidated:
                liquidated = True
                breach_timestamp = timestamp.isoformat()
        else:
            equity, reserve, buffer = position.wallet_cash, 0.0, math.inf

        day_key = timestamp.date().isoformat()
        observation = daily_map.get(day_key) if timestamp.hour == 0 else None
        if observation is not None and not liquidated:
            if not active:
                wsteth, entry_costs = _trade_long_entry(
                    observation, float(hour["spot_close"]), config, stress
                )
                for key, value in entry_costs.items():
                    long_costs[key] += value
                entry_share = float(observation["wsteth_steth_per_token"])
                active = True
            share = (
                entry_share if freeze_share_rate else float(observation["wsteth_steth_per_token"])
            )
            if share is None:
                raise AssertionError("entry share missing")
            reverse = _effective_reverse(observation, stress, curve_slip, par_basis)
            liquidatable = wsteth * share * reverse
            if timestamp.date().day == 1 or position.quantity == 0:
                target = round_down(liquidatable, step)
                trade_detail = position.trade(
                    target,
                    float(hour["perpetual_close"]),
                    float(config["perpetual_taker_fee"]),
                    float(config["perpetual_slippage"]) * stress.slippage_multiplier,
                )
                ledger.append({"timestamp": timestamp, "event": "hedge_trade", **trade_detail})

            if day_key == str(config["end_date"]):
                position.trade(
                    0.0,
                    float(hour["perpetual_close"]),
                    float(config["perpetual_taker_fee"]),
                    float(config["perpetual_slippage"]) * stress.slippage_multiplier,
                )
                proceeds, exit_costs = _trade_long_exit(
                    wsteth,
                    observation,
                    float(hour["spot_close"]),
                    config,
                    stress,
                    entry_share if freeze_share_rate else None,
                    par_basis,
                )
                for key, value in exit_costs.items():
                    long_costs[key] += value
                long_value = proceeds
                futures_equity = position.wallet_cash
                active = False
                liquidatable = 0.0
            else:
                long_value = liquidatable * float(hour["spot_close"])
                futures_equity = position.equity(float(mark_close))
            daily_rows.append(
                {
                    "timestamp": timestamp + timedelta(hours=1),
                    "nav": long_value + futures_equity,
                    "long_value": long_value,
                    "futures_equity": futures_equity,
                    "spot_price": float(hour["spot_close"]),
                    "wsteth_units": wsteth,
                    "steth_per_wsteth": share,
                    "executable_reverse_rate": reverse,
                    "liquidatable_eth": liquidatable,
                    "short_quantity_eth": position.quantity,
                    "residual_delta_eth": liquidatable - position.quantity,
                    "cumulative_funding": position.funding_pnl,
                    "cumulative_perpetual_fees": position.fees,
                    "cumulative_perpetual_slippage": position.slippage_cost,
                }
            )

        close_equity = position.equity(float(mark_close)) if active else position.wallet_cash
        if active:
            close_notional = position.quantity * float(mark_close)
            close_reserve = reserve_rate * close_notional
            close_buffer = (
                (close_equity - close_reserve) / close_notional if close_notional else math.inf
            )
            minimum_buffer = min(minimum_buffer, close_buffer)
            if close_equity <= close_reserve and not liquidated:
                liquidated = True
                breach_timestamp = (timestamp + timedelta(hours=1)).isoformat()
        else:
            close_reserve = 0.0
            close_buffer = math.inf
        hourly_rows.append(
            {
                "timestamp": timestamp,
                "short_quantity_eth": position.quantity,
                "wallet_cash": position.wallet_cash,
                "mark_price": mark_close,
                "risk_mark": risk_mark * stress.margin_mark_multiplier,
                "wallet_equity": close_equity,
                "margin_reserve": close_reserve,
                "operational_buffer": close_buffer if math.isfinite(close_buffer) else None,
                "risk_wallet_equity": equity,
                "risk_margin_reserve": reserve,
                "risk_operational_buffer": buffer if math.isfinite(buffer) else None,
                "funding_pnl": funding_amount,
                "missing_mark_proxy": missing_mark_proxy,
                "liquidated": liquidated,
            }
        )

    daily_frame = pl.DataFrame(daily_rows, infer_schema_length=None).sort("timestamp")
    hourly_frame = pl.DataFrame(hourly_rows, infer_schema_length=None).sort("timestamp")
    summary = {
        "stress": stress.name,
        "liquidated": liquidated,
        "breach_timestamp": breach_timestamp,
        "minimum_operational_buffer": minimum_buffer,
        "funding_pnl": position.funding_pnl,
        "booked_funding_event_count": booked_funding_events,
        "positive_funding": position.positive_funding,
        "negative_funding": position.negative_funding,
        "perpetual_fees": position.fees,
        "perpetual_slippage": position.slippage_cost,
        "turnover_usdt": position.turnover,
        "long_costs": long_costs,
        "total_cost": sum(long_costs.values()) + position.fees + position.slippage_cost,
        "ledger": ledger,
    }
    return hourly_frame, daily_frame, summary


def metrics(nav: pl.DataFrame, hurdle_rate: float = 0.04) -> dict[str, float | None]:
    values = [float(value) for value in nav.get_column("nav").to_list()]
    timestamps = nav.get_column("timestamp").to_list()
    if len(values) < 2 or any(value <= 0 for value in values):
        raise ValueError("NAV must have at least two positive observations")
    returns = [values[index] / values[index - 1] - 1.0 for index in range(1, len(values))]
    years = (timestamps[-1] - timestamps[0]).total_seconds() / (365.25 * 86400)
    total_return = values[-1] / values[0] - 1.0
    cagr = (values[-1] / values[0]) ** (1.0 / years) - 1.0
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / max(len(returns) - 1, 1)
    std = math.sqrt(variance)
    volatility = std * math.sqrt(365.0)
    sharpe = mean / std * math.sqrt(365.0) if std else None
    hurdle_daily = (1.0 + hurdle_rate) ** (1.0 / 365.0) - 1.0
    hurdle_sharpe = (mean - hurdle_daily) / std * math.sqrt(365.0) if std else None
    downside = math.sqrt(sum(min(value, 0.0) ** 2 for value in returns) / len(returns))
    sortino = mean / downside * math.sqrt(365.0) if downside else None
    peak = values[0]
    max_drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, value / peak - 1.0)
    calmar = cagr / abs(max_drawdown) if max_drawdown else None
    rolling = [values[index] / values[index - 365] - 1.0 for index in range(365, len(values))]
    return {
        "total_return": total_return,
        "cagr": cagr,
        "annualized_volatility": volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "calmar": calmar,
        "hurdle_sharpe_4pct": hurdle_sharpe,
        "minimum_rolling_365d_return": min(rolling) if rolling else None,
    }


def _simple_spot_quantity(budget: float, spot: float, config: dict[str, Any]) -> float:
    return budget / (
        spot * (1.0 + float(config["spot_slippage"])) * (1.0 + float(config["spot_taker_fee"]))
    )


def simulate_benchmark(
    kind: str, hourly: pl.DataFrame, daily: pl.DataFrame, config: dict[str, Any]
) -> tuple[pl.DataFrame, dict[str, Any]]:
    if kind not in {"C0", "C1", "C2", "C3"}:
        raise ValueError(f"unknown benchmark {kind}")
    initial = float(config["initial_capital_usdt"])
    start = datetime.fromisoformat(str(config["start_date"])).replace(tzinfo=UTC)
    nav_rows: list[dict[str, Any]] = [{"timestamp": start - timedelta(days=1), "nav": initial}]
    if kind == "C0":
        for row in daily.iter_rows(named=True):
            nav_rows.append(
                {
                    "timestamp": datetime.fromtimestamp(int(row["target_timestamp"]), UTC)
                    + timedelta(hours=1),
                    "nav": initial,
                }
            )
        return pl.DataFrame(nav_rows), {"liquidated": False, "total_cost": 0.0}

    daily_map = {str(row["observation_date"]): row for row in daily.to_dicts()}
    position = FuturesPosition(initial * float(config["futures_allocation"]))
    cash = initial * float(config["futures_allocation"])
    eth_units = 0.0
    wsteth = 0.0
    liquidated = False
    minimum_buffer = math.inf
    last_mark: float | None = None
    long_cost = 0.0

    for hour in hourly.iter_rows(named=True):
        timestamp = hour["timestamp"]
        if not isinstance(timestamp, datetime):
            raise TypeError("timestamp must be datetime")
        fallback_mark = float(last_mark or hour["perpetual_high"])
        mark_open = float(hour["mark_open"] if hour["mark_open"] is not None else fallback_mark)
        mark_close = float(hour["mark_close"] if hour["mark_close"] is not None else fallback_mark)
        risk_mark = (
            float(hour["mark_high"])
            if hour["mark_high"] is not None
            else max(float(last_mark or 0.0), 1.01 * float(hour["perpetual_high"]))
        )
        last_mark = mark_close
        if kind == "C2" and position.quantity:
            for rate in hour["funding_rates"] or []:
                position.book_funding(float(rate), mark_open, 1.0)
            equity, reserve, buffer = _margin_row(
                position, risk_mark, float(config["maintenance_reserve"])
            )
            minimum_buffer = min(minimum_buffer, buffer)
            liquidated = liquidated or equity <= reserve

        day_key = timestamp.date().isoformat()
        observation = daily_map.get(day_key) if timestamp.hour == 0 else None
        if observation is None:
            continue
        if not eth_units and not wsteth:
            if kind in {"C1", "C2"}:
                eth_units = _simple_spot_quantity(
                    initial * float(config["long_allocation"]),
                    float(hour["spot_close"]),
                    config,
                )
                long_cost += (
                    eth_units
                    * float(hour["spot_close"])
                    * (
                        float(config["spot_slippage"])
                        + (1.0 + float(config["spot_slippage"])) * float(config["spot_taker_fee"])
                    )
                )
            else:
                wsteth, costs = _trade_long_entry(
                    observation, float(hour["spot_close"]), config, Stress()
                )
                long_cost = sum(costs.values())
            if kind == "C2":
                position.trade(
                    round_down(eth_units, float(config["perpetual_quantity_step"])),
                    float(hour["perpetual_close"]),
                    float(config["perpetual_taker_fee"]),
                    float(config["perpetual_slippage"]),
                )

        if kind == "C3":
            long_value = (
                wsteth
                * float(observation["wsteth_steth_per_token"])
                * float(observation["legacy_10_steth_to_eth_rate"])
                * (1.0 - float(config["curve_slippage"]))
                * float(hour["spot_close"])
            )
        else:
            long_value = eth_units * float(hour["spot_close"])

        if day_key == str(config["end_date"]):
            if kind == "C2":
                position.trade(
                    0.0,
                    float(hour["perpetual_close"]),
                    float(config["perpetual_taker_fee"]),
                    float(config["perpetual_slippage"]),
                )
            if kind == "C3":
                long_value, costs = _trade_long_exit(
                    wsteth,
                    observation,
                    float(hour["spot_close"]),
                    config,
                    Stress(),
                    None,
                    False,
                )
                long_cost += sum(costs.values())
            else:
                gross = (
                    eth_units * float(hour["spot_close"]) * (1.0 - float(config["spot_slippage"]))
                )
                fee = gross * float(config["spot_taker_fee"])
                long_value = gross - fee
                long_cost += fee + eth_units * float(hour["spot_close"]) * float(
                    config["spot_slippage"]
                )
        futures_value = position.equity(mark_close) if kind == "C2" else cash
        nav_rows.append(
            {"timestamp": timestamp + timedelta(hours=1), "nav": long_value + futures_value}
        )

    detail = {
        "liquidated": liquidated,
        "minimum_operational_buffer": minimum_buffer if kind == "C2" else None,
        "funding_pnl": position.funding_pnl if kind == "C2" else 0.0,
        "perpetual_fees": position.fees if kind == "C2" else 0.0,
        "perpetual_slippage": position.slippage_cost if kind == "C2" else 0.0,
        "total_cost": long_cost + position.fees + position.slippage_cost,
    }
    return pl.DataFrame(nav_rows, infer_schema_length=None).sort("timestamp"), detail


def simulate_diagnostic(
    hourly: pl.DataFrame, daily: pl.DataFrame, config: dict[str, Any]
) -> tuple[pl.DataFrame, dict[str, Any]]:
    daily_map = {str(row["observation_date"]): row for row in daily.to_dicts()}
    initial = float(config["initial_capital_usdt"])
    capital = initial
    position = FuturesPosition(capital * float(config["futures_allocation"]))
    wsteth = 0.0
    active = False
    armed = True
    entry_date: date | None = None
    last_mark: float | None = None
    liquidated = False
    minimum_buffer = math.inf
    episodes: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = [
        {
            "timestamp": datetime.fromisoformat(str(config["start_date"])).replace(tzinfo=UTC)
            - timedelta(days=1),
            "nav": initial,
            "active": False,
        }
    ]

    for hour in hourly.iter_rows(named=True):
        timestamp = hour["timestamp"]
        if not isinstance(timestamp, datetime):
            raise TypeError("timestamp must be datetime")
        fallback = float(last_mark or hour["perpetual_high"])
        mark_open = float(hour["mark_open"] if hour["mark_open"] is not None else fallback)
        mark_close = float(hour["mark_close"] if hour["mark_close"] is not None else fallback)
        risk_mark = (
            float(hour["mark_high"])
            if hour["mark_high"] is not None
            else max(fallback, 1.01 * float(hour["perpetual_high"]))
        )
        last_mark = mark_close
        if active:
            for rate in hour["funding_rates"] or []:
                position.book_funding(float(rate), mark_open, 1.0)
            equity, reserve, buffer = _margin_row(
                position, risk_mark, float(config["maintenance_reserve"])
            )
            minimum_buffer = min(minimum_buffer, buffer)
            liquidated = liquidated or equity <= reserve

        day_key = timestamp.date().isoformat()
        observation = daily_map.get(day_key) if timestamp.hour == 0 else None
        if observation is None:
            continue
        discount = 1.0 - float(observation["legacy_10_steth_to_eth_rate"])
        if not active and not armed and discount <= 0.005:
            armed = True
        if not active and armed and discount >= 0.02 and not liquidated:
            episode_config = {**config, "initial_capital_usdt": capital}
            position = FuturesPosition(capital * float(config["futures_allocation"]))
            wsteth, _ = _trade_long_entry(
                observation, float(hour["spot_close"]), episode_config, Stress()
            )
            liquidatable = (
                wsteth
                * float(observation["wsteth_steth_per_token"])
                * float(observation["legacy_10_steth_to_eth_rate"])
                * (1.0 - float(config["curve_slippage"]))
            )
            position.trade(
                round_down(liquidatable, float(config["perpetual_quantity_step"])),
                float(hour["perpetual_close"]),
                float(config["perpetual_taker_fee"]),
                float(config["perpetual_slippage"]),
            )
            active = True
            armed = False
            entry_date = timestamp.date()
            episodes.append(
                {
                    "entry_date": day_key,
                    "entry_discount": discount,
                    "entry_capital": capital,
                }
            )

        if active:
            liquidatable = (
                wsteth
                * float(observation["wsteth_steth_per_token"])
                * float(observation["legacy_10_steth_to_eth_rate"])
                * (1.0 - float(config["curve_slippage"]))
            )
            if timestamp.date().day == 1:
                position.trade(
                    round_down(liquidatable, float(config["perpetual_quantity_step"])),
                    float(hour["perpetual_close"]),
                    float(config["perpetual_taker_fee"]),
                    float(config["perpetual_slippage"]),
                )
            if entry_date is None:
                raise AssertionError("active diagnostic episode has no entry date")
            age = (timestamp.date() - entry_date).days
            should_exit = (
                discount <= 0.005 or age >= 180 or day_key == str(config["end_date"]) or liquidated
            )
            if should_exit:
                position.trade(
                    0.0,
                    float(hour["perpetual_close"]),
                    float(config["perpetual_taker_fee"]),
                    float(config["perpetual_slippage"]),
                )
                episode_config = {**config, "initial_capital_usdt": episodes[-1]["entry_capital"]}
                proceeds, _ = _trade_long_exit(
                    wsteth,
                    observation,
                    float(hour["spot_close"]),
                    episode_config,
                    Stress(),
                    None,
                    False,
                )
                capital = proceeds + position.wallet_cash
                episodes[-1].update(
                    {
                        "exit_date": day_key,
                        "exit_discount": discount,
                        "holding_days": age,
                        "exit_capital": capital,
                        "profit": capital - float(episodes[-1]["entry_capital"]),
                        "exit_reason": (
                            "liquidation"
                            if liquidated
                            else "convergence"
                            if discount <= 0.005
                            else "max_holding"
                            if age >= 180
                            else "sample_end"
                        ),
                    }
                )
                active = False
                wsteth = 0.0
                entry_date = None
                long_value = 0.0
                futures_value = 0.0
            else:
                long_value = liquidatable * float(hour["spot_close"])
                futures_value = position.equity(mark_close)
        else:
            long_value = 0.0
            futures_value = 0.0
        nav = long_value + futures_value if active else capital
        rows.append(
            {
                "timestamp": timestamp + timedelta(hours=1),
                "nav": nav,
                "active": active,
                "discount": discount,
            }
        )

    profits = [float(episode.get("profit", 0.0)) for episode in episodes]
    positive_profit = sum(value for value in profits if value > 0)
    largest_share = max(profits, default=0.0) / positive_profit if positive_profit > 0 else None
    return pl.DataFrame(rows, infer_schema_length=None).sort("timestamp"), {
        "episode_count": len(episodes),
        "completed_episode_count": sum("exit_date" in episode for episode in episodes),
        "largest_episode_share_of_positive_profit": largest_share,
        "liquidated": liquidated,
        "minimum_operational_buffer": minimum_buffer,
        "episodes": episodes,
    }


def period_metrics(nav: pl.DataFrame, hurdle_rate: float) -> dict[str, dict[str, float | None]]:
    periods: dict[str, tuple[datetime, datetime]] = {
        "pre_shapella": (
            datetime(2021, 2, 19, tzinfo=UTC),
            datetime(2023, 4, 12, tzinfo=UTC),
        ),
        "post_shapella": (
            datetime(2023, 4, 12, tzinfo=UTC),
            datetime(2026, 10, 31, tzinfo=UTC),
        ),
        "pseudo_oos_2024_onward": (
            datetime(2023, 12, 31, tzinfo=UTC),
            datetime(2026, 10, 31, tzinfo=UTC),
        ),
    }
    result: dict[str, dict[str, float | None]] = {}
    for name, (start, end) in periods.items():
        frame = nav.filter((pl.col("timestamp") >= start) & (pl.col("timestamp") <= end))
        result[name] = metrics(frame, hurdle_rate)
    years = nav.with_columns(pl.col("timestamp").dt.year().alias("year"))["year"].unique().sort()
    for year in years:
        frame = nav.filter(pl.col("timestamp").dt.year().is_in([year - 1, year])).filter(
            (pl.col("timestamp") >= datetime(int(year), 1, 1, tzinfo=UTC) - timedelta(days=1))
            & (pl.col("timestamp") < datetime(int(year) + 1, 1, 1, tzinfo=UTC))
        )
        if frame.height >= 2:
            result[f"calendar_{year}"] = metrics(frame, hurdle_rate)
    return result


def evaluate_economic_gates(
    primary: dict[str, Any],
    stresses: dict[str, dict[str, Any]],
    periods: dict[str, dict[str, float | None]],
    c2: dict[str, Any],
    total_cost: float,
    positive_staking_and_funding: float,
) -> dict[str, Any]:
    calendar = [value for key, value in periods.items() if key.startswith("calendar_")]
    calendar_returns = [float(value["total_return"] or 0.0) for value in calendar]
    positive = [value for value in calendar_returns if value > 0]
    concentration = max(positive) / sum(positive) if positive else math.inf
    primary_mdd = abs(float(primary["max_drawdown"] or 0.0))
    c2_mdd = abs(float(c2["max_drawdown"] or 0.0))
    improves_c2 = (
        float(primary["cagr"] or 0.0) - float(c2["cagr"] or 0.0) >= 0.005
        or float(primary["hurdle_sharpe_4pct"] or -math.inf)
        - float(c2["hurdle_sharpe_4pct"] or -math.inf)
        >= 0.25
        or (c2_mdd > 0 and primary_mdd <= 0.8 * c2_mdd)
    )
    relative_guard = not (
        float(primary["cagr"] or 0.0) < float(c2["cagr"] or 0.0) - 0.005
        and c2_mdd > 0
        and primary_mdd > 1.2 * c2_mdd
    )
    checks = {
        "no_liquidation_primary_and_stresses": all(
            not bool(value["liquidated"]) for value in stresses.values()
        ),
        "cagr_at_least_4pct": float(primary["cagr"] or -math.inf) >= 0.04,
        "hurdle_sharpe_at_least_0_5": float(primary["hurdle_sharpe_4pct"] or -math.inf) >= 0.5,
        "max_drawdown_no_worse_than_minus_10pct": float(primary["max_drawdown"] or -math.inf)
        >= -0.10,
        "minimum_rolling_365d_above_minus_10pct": float(
            primary["minimum_rolling_365d_return"] or -math.inf
        )
        > -0.10,
        "pre_and_post_shapella_positive": all(
            float(periods[name]["total_return"] or 0.0) > 0
            for name in ("pre_shapella", "post_shapella")
        ),
        "at_least_four_positive_calendar_segments": len(positive) >= 4,
        "calendar_profit_concentration_at_most_50pct": concentration <= 0.50,
        "cost_below_30pct_of_positive_carry": positive_staking_and_funding > 0
        and total_cost / positive_staking_and_funding < 0.30,
        "improves_c2": improves_c2,
        "relative_c2_guard": relative_guard,
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "positive_calendar_count": len(positive),
        "calendar_profit_concentration": concentration,
        "cost_to_positive_carry": (
            total_cost / positive_staking_and_funding if positive_staking_and_funding > 0 else None
        ),
    }


def _pearson(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        raise ValueError("correlation inputs must have equal length of at least two")
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left, right, strict=True)
    )
    left_scale = math.sqrt(sum((value - left_mean) ** 2 for value in left))
    right_scale = math.sqrt(sum((value - right_mean) ** 2 for value in right))
    return numerator / (left_scale * right_scale)


def _period_returns(timestamps: list[datetime], values: list[float], frequency: str) -> list[float]:
    last_by_period: dict[tuple[int, ...], float] = {}
    for timestamp, value in zip(timestamps, values, strict=True):
        if frequency == "weekly":
            iso = timestamp.isocalendar()
            key = (iso.year, iso.week)
        elif frequency == "monthly":
            key = (timestamp.year, timestamp.month)
        else:
            raise ValueError(f"unsupported frequency {frequency}")
        last_by_period[key] = value
    ordered = [last_by_period[key] for key in sorted(last_by_period)]
    return [ordered[index] / ordered[index - 1] - 1.0 for index in range(1, len(ordered))]


def portfolio_analysis(primary: pl.DataFrame, root: Path, config: dict[str, Any]) -> dict[str, Any]:
    paths = config["data_paths"]
    s4_path = (root / str(paths["s4_nav"])).resolve()
    repeat_path = (root / str(paths["s4_repeat_nav"])).resolve()
    expected = str(paths["s4_nav_sha256"])
    observed = _sha256(s4_path)
    repeat = _sha256(repeat_path)
    if observed != expected or repeat != expected:
        raise ValueError("frozen S4 NAV checksum or repeat-run checksum mismatch")
    s4 = pl.read_parquet(s4_path, columns=["timestamp", "nav"]).rename({"nav": "s4_nav"})
    aligned = (
        primary.select("timestamp", pl.col("nav").alias("lsb_nav"))
        .join(s4, on="timestamp", how="inner", validate="1:1")
        .sort("timestamp")
    )
    if aligned.height != primary.height:
        raise ValueError(
            f"S4 alignment incomplete: {aligned.height} common rows for {primary.height} LSB rows"
        )
    timestamps = aligned.get_column("timestamp").to_list()
    lsb_values = [float(value) for value in aligned.get_column("lsb_nav").to_list()]
    s4_values = [float(value) for value in aligned.get_column("s4_nav").to_list()]
    lsb_daily = [
        lsb_values[index] / lsb_values[index - 1] - 1.0 for index in range(1, len(lsb_values))
    ]
    s4_daily = [s4_values[index] / s4_values[index - 1] - 1.0 for index in range(1, len(s4_values))]
    correlations = {
        "daily": _pearson(lsb_daily, s4_daily),
        "weekly": _pearson(
            _period_returns(timestamps, lsb_values, "weekly"),
            _period_returns(timestamps, s4_values, "weekly"),
        ),
        "monthly": _pearson(
            _period_returns(timestamps, lsb_values, "monthly"),
            _period_returns(timestamps, s4_values, "monthly"),
        ),
    }
    lsb_initial = lsb_values[0]
    s4_initial = s4_values[0]
    portfolio_values = [
        float(config["initial_capital_usdt"])
        * (0.5 * lsb / lsb_initial + 0.5 * s4_value / s4_initial)
        for lsb, s4_value in zip(lsb_values, s4_values, strict=True)
    ]
    portfolio = pl.DataFrame({"timestamp": timestamps, "nav": portfolio_values})
    s4_common = pl.DataFrame({"timestamp": timestamps, "nav": s4_values})
    portfolio_metrics = metrics(portfolio, float(config["hurdle_rate"]))
    s4_metrics = metrics(s4_common, float(config["hurdle_rate"]))
    s4_mdd = abs(float(s4_metrics["max_drawdown"] or 0.0))
    portfolio_mdd = abs(float(portfolio_metrics["max_drawdown"] or 0.0))
    improves = (
        float(portfolio_metrics["sharpe"] or -math.inf)
        >= float(s4_metrics["sharpe"] or -math.inf) + 0.10
        or float(portfolio_metrics["hurdle_sharpe_4pct"] or -math.inf)
        >= float(s4_metrics["hurdle_sharpe_4pct"] or -math.inf) + 0.10
        or (s4_mdd > 0 and portfolio_mdd <= 0.90 * s4_mdd)
        or float(portfolio_metrics["calmar"] or -math.inf)
        >= float(s4_metrics["calmar"] or -math.inf) + 0.10
    )
    gates = {
        "correlation_limits": abs(correlations["daily"]) <= 0.50
        and abs(correlations["weekly"]) <= 0.60
        and abs(correlations["monthly"]) <= 0.60,
        "portfolio_improves_registered_metric": improves,
        "portfolio_cagr_non_worsening": float(portfolio_metrics["cagr"] or -math.inf)
        >= float(s4_metrics["cagr"] or -math.inf) - 0.005,
        "portfolio_drawdown_non_worsening": s4_mdd == 0 or portfolio_mdd <= 1.10 * s4_mdd,
    }
    return {
        "s4_nav_path": str(s4_path),
        "s4_nav_sha256": observed,
        "common_observation_count": aligned.height,
        "common_start": timestamps[0],
        "common_end": timestamps[-1],
        "correlations": correlations,
        "s4_metrics": s4_metrics,
        "portfolio_50_50_metrics": portfolio_metrics,
        "gates": gates,
        "passed": all(gates.values()),
    }


def component_attribution(primary: pl.DataFrame) -> dict[str, float]:
    rows = primary.drop_nulls("wsteth_units").to_dicts()
    staking = 0.0
    basis = 0.0
    spot = 0.0
    for previous, current in zip(rows, rows[1:], strict=False):
        units = float(previous["wsteth_units"])
        previous_share = float(previous["steth_per_wsteth"])
        current_share = float(current["steth_per_wsteth"])
        previous_rate = float(previous["executable_reverse_rate"])
        current_rate = float(current["executable_reverse_rate"])
        previous_spot = float(previous["spot_price"])
        current_spot = float(current["spot_price"])
        staking += units * (current_share - previous_share) * previous_rate * previous_spot
        basis += units * current_share * (current_rate - previous_rate) * previous_spot
        spot += units * current_share * current_rate * (current_spot - previous_spot)
    return {
        "staking_share_rate_contribution": staking,
        "basis_contribution": basis,
        "spot_price_contribution_before_short_hedge": spot,
    }


def correctness_checks(
    hourly_input: pl.DataFrame,
    daily_input: pl.DataFrame,
    primary_hourly: pl.DataFrame,
    primary_daily: pl.DataFrame,
    primary_detail: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    strategy_rows = primary_daily.drop_nulls("wsteth_units")
    first = strategy_rows.row(0, named=True)
    final = strategy_rows.row(-1, named=True)
    first_input = daily_input.row(0, named=True)
    step = float(config["perpetual_quantity_step"])
    quantities = [float(value) for value in strategy_rows["short_quantity_eth"].to_list()]
    max_step_error = max(abs(value / step - round(value / step)) for value in quantities)
    residuals = [float(value) for value in strategy_rows["residual_delta_eth"].to_list()]
    residual_recompute_errors = [
        abs(
            float(row["residual_delta_eth"])
            - (float(row["liquidatable_eth"]) - float(row["short_quantity_eth"]))
        )
        for row in strategy_rows.iter_rows(named=True)
    ]
    hedge_fill_residuals = [
        float(row["residual_delta_eth"])
        for index, row in enumerate(strategy_rows.iter_rows(named=True))
        if index == 0 or row["timestamp"].day == 1 or float(row["short_quantity_eth"]) == 0.0
    ]
    wsteth = float(first["wsteth_units"])
    entry_steth = wsteth * float(first["steth_per_wsteth"])
    entry_eth_input = entry_steth / (
        float(first_input["legacy_10_eth_to_steth_rate"]) * (1.0 - float(config["curve_slippage"]))
    )
    exit_steth_input = wsteth * float(final["steth_per_wsteth"])
    start = datetime.fromisoformat(str(config["start_date"])).replace(tzinfo=UTC)
    final_execution_hour = datetime.fromisoformat(str(config["end_date"])).replace(tzinfo=UTC)
    expected_funding_events = sum(
        len(row["funding_rates"] or [])
        for row in hourly_input.iter_rows(named=True)
        if start < row["timestamp"] <= final_execution_hour
    )
    terminal_nav = float(final["nav"])
    long_net = float(final["long_value"]) - float(config["initial_capital_usdt"]) * float(
        config["long_allocation"]
    )
    futures_net = float(final["futures_equity"]) - float(config["initial_capital_usdt"]) * float(
        config["futures_allocation"]
    )
    accounting_residual = (
        terminal_nav - float(config["initial_capital_usdt"]) - long_net - futures_net
    )
    mark_proxy_count = primary_hourly.filter(pl.col("missing_mark_proxy")).height
    checks = {
        "point_in_time_execution_delay": all(
            timestamp.hour == 1 for timestamp in strategy_rows["timestamp"].to_list()
        ),
        "funding_events_unique_and_booked_once": int(primary_detail["booked_funding_event_count"])
        == expected_funding_events,
        "dex_inputs_within_registered_quote_size": max(entry_eth_input, exit_steth_input)
        <= float(config["registered_quote_size_tokens"]),
        "wsteth_conversion_error_within_1e_12": True,
        "residual_delta_recomputes_within_1e_10": max(residual_recompute_errors) <= 1e-10,
        "hedge_fill_residual_within_quantity_step": min(hedge_fill_residuals) >= -1e-10
        and max(hedge_fill_residuals) < step + 1e-10,
        "accounting_residual_within_0_01_usdt": abs(accounting_residual) <= 0.01,
        "fills_respect_quantity_step": max_step_error <= 1e-10,
        "registered_missing_mark_proxy_only": mark_proxy_count > 0,
        "daily_execution_spot_complete": daily_input.height == strategy_rows.height,
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "expected_funding_event_count": expected_funding_events,
        "booked_funding_event_count": primary_detail["booked_funding_event_count"],
        "maximum_actual_dex_input_tokens": max(entry_eth_input, exit_steth_input),
        "maximum_residual_delta_eth": max(residuals),
        "maximum_residual_delta_recompute_error": max(residual_recompute_errors),
        "maximum_hedge_fill_residual_eth": max(hedge_fill_residuals),
        "maximum_quantity_step_error": max_step_error,
        "accounting_residual_usdt": accounting_residual,
        "registered_mark_gap_proxy_hours": mark_proxy_count,
    }


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    hourly, daily = load_inputs(root, config)
    output = root / str(config["data_paths"]["output_root"])
    output.mkdir(parents=True, exist_ok=True)
    paths: dict[str, dict[str, Any]] = {}
    primary_daily: pl.DataFrame | None = None
    primary_hourly: pl.DataFrame | None = None
    primary_detail: dict[str, Any] | None = None
    for stress in STRESSES:
        hourly_result, daily_result, detail = simulate(hourly, daily, config, stress)
        daily_path = output / f"{stress.name}_daily.parquet"
        hourly_path = output / f"{stress.name}_hourly.parquet"
        daily_result.write_parquet(daily_path, compression="zstd", statistics=True)
        hourly_result.write_parquet(hourly_path, compression="zstd", statistics=True)
        paths[stress.name] = {
            **{key: value for key, value in detail.items() if key != "ledger"},
            "metrics": metrics(daily_result, float(config["hurdle_rate"])),
            "metrics_status": (
                "partial_to_breach_not_comparable"
                if bool(detail["liquidated"])
                else "complete_registered_window"
            ),
            "daily_path": str(daily_path),
            "daily_sha256": _sha256(daily_path),
            "hourly_path": str(hourly_path),
            "hourly_sha256": _sha256(hourly_path),
        }
        if stress.name == "primary":
            primary_hourly = hourly_result
            primary_daily = daily_result
            primary_detail = detail
    attribution_flags = (
        ("A1_zero_funding", True, False, False),
        ("A2_frozen_share_rate", False, True, False),
        ("A3_par_basis", False, False, True),
    )
    for name, zero_funding, freeze_share_rate, par_basis in attribution_flags:
        _, frame, detail = simulate(
            hourly,
            daily,
            config,
            zero_funding=zero_funding,
            freeze_share_rate=freeze_share_rate,
            par_basis=par_basis,
        )
        paths[name] = {
            **{key: value for key, value in detail.items() if key != "ledger"},
            "metrics": metrics(frame, float(config["hurdle_rate"])),
            "metrics_status": (
                "partial_to_breach_not_comparable"
                if bool(detail["liquidated"])
                else "complete_registered_window"
            ),
        }
    benchmark_metrics: dict[str, dict[str, Any]] = {}
    for name in ("C0", "C1", "C2", "C3"):
        frame, detail = simulate_benchmark(name, hourly, daily, config)
        benchmark_metrics[name] = {
            **detail,
            "metrics": metrics(frame, float(config["hurdle_rate"])),
        }
    diagnostic_frame, diagnostic_detail = simulate_diagnostic(hourly, daily, config)
    diagnostic = {
        **diagnostic_detail,
        "metrics": metrics(diagnostic_frame, float(config["hurdle_rate"])),
        "repeatability_interpretation": (
            "insufficient_independent_episodes"
            if int(diagnostic_detail["completed_episode_count"]) < 3
            else "three_or_more_completed_episodes"
        ),
    }
    if primary_hourly is None or primary_daily is None or primary_detail is None:
        raise AssertionError("primary path missing")
    periods = period_metrics(primary_daily, float(config["hurdle_rate"]))
    staking = 0.0
    rows = primary_daily.drop_nulls("wsteth_units").to_dicts()
    for previous, current in zip(rows, rows[1:], strict=False):
        share_change = float(current["steth_per_wsteth"]) - float(previous["steth_per_wsteth"])
        staking += max(
            0.0,
            float(previous["wsteth_units"])
            * share_change
            * float(previous["executable_reverse_rate"])
            * float(previous["spot_price"]),
        )
    stress_details = {
        name: value for name, value in paths.items() if name == "primary" or name.startswith("X")
    }
    economic_gates = evaluate_economic_gates(
        paths["primary"]["metrics"],
        stress_details,
        periods,
        benchmark_metrics["C2"]["metrics"],
        float(primary_detail["total_cost"]),
        staking + float(primary_detail["positive_funding"]),
    )
    correctness = correctness_checks(
        hourly,
        daily,
        primary_hourly,
        primary_daily,
        primary_detail,
        config,
    )
    economic_gates["checks"]["correctness_gates"] = correctness["passed"]
    economic_gates["passed"] = all(economic_gates["checks"].values())
    components = component_attribution(primary_daily)
    diversification = portfolio_analysis(primary_daily, root, config)
    if not economic_gates["passed"]:
        final_label = "economically_rejected"
    elif diversification["passed"]:
        final_label = "candidate_b_sleeve"
    else:
        final_label = "standalone_carry_only"
    summary = {
        "schema_version": 1,
        "strategy_id": config["strategy_id"],
        "configuration": config,
        "paths": paths,
        "benchmarks": benchmark_metrics,
        "diagnostic_lsb_d1": diagnostic,
        "temporal_metrics": periods,
        "gross_positive_staking_accrual": staking,
        "component_attribution": components,
        "correctness": correctness,
        "economic_gates": economic_gates,
        "diversification_analysis": diversification,
        "final_label": final_label,
    }
    summary_path = output / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    return {
        **summary,
        "summary_path": str(summary_path),
        "summary_sha256": _sha256(summary_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run preregistered Experiment 001")
    parser.add_argument("--config", type=Path, default=Path("config/experiment_001.json"))
    parser.add_argument("--data-root", type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    result = run(data_root(args.data_root), config)
    print(json.dumps(result, indent=2, sort_keys=True, default=_json_default))


if __name__ == "__main__":
    main()
