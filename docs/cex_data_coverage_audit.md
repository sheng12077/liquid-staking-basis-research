# ETH CEX Data Coverage and Point-in-Time Alignment Audit

## Scope

This is a data-feasibility audit, not a performance experiment. It does not compute
strategy returns, tune parameters, or inspect an entry/exit rule. The audited primary
window is 2021-01-01 00:00 UTC through 2026-11-01 00:00 UTC (exclusive), matching the
complete monthly Binance archive currently available in the shared data lake.

Primary data are the canonical Binance ETHUSDT spot and USD-M perpetual series. The
daily Lido/Curve state dataset is used only to verify point-in-time alignment. Existing
OKX ETH-USDT spot, swap, and funding audit results are reviewed as a shorter secondary
cross-venue source.

## Conclusion

**Pass for research use, with explicit missing-mark handling.** The data support a
pre-registered liquid-staking basis experiment over the common daily window from
2021-01-06 through 2026-10-31. Binance spot, perpetual execution bars, and funding are
sufficiently complete. Mark price is sufficiently complete for risk and liquidation
checks, but three daily observations require a pre-registered missing-data rule.

This conclusion does not establish that the strategy is profitable or executable.

## Binance coverage

| Series | Rows/events | Coverage | Duplicates | Main finding |
| --- | ---: | ---: | ---: | --- |
| ETHUSDT spot hourly | 51,106 | 99.9726% | 0 | 14 missing hours; none affects the daily prior or execution bar |
| ETHUSDT USD-M perpetual hourly | 51,120 | 100.0000% | 0 | Complete primary execution series |
| ETHUSDT mark hourly | 51,057 | 99.8768% | 0 | 63 missing hours; conservative execution bar always present |
| ETHUSDT index hourly | 51,024 | 99.8122% | 0 | Optional; four missing whole days |
| ETHUSDT premium hourly | 50,928 | 99.6244% | 0 | Optional; eight affected daily observations |
| ETHUSDT funding | 6,390 | event series | 0 | All events use 8-hour intervals; no interval violation with 1-second tolerance |

All price series have zero OHLC violations. Spot, perpetual, mark, and index prices are
strictly positive. Premium index values may be negative by definition and are therefore
not subject to a positive-price check. Funding rates contain no null or non-finite values.

The funding timestamps contain harmless sub-second publication jitter. For example, the
first event is timestamped 2021-01-01 00:00:00.002 UTC. Requiring exact integer-hour
differences would falsely classify 4,041 observations as violations; a one-second
tolerance produces zero interval violations and agrees with the prior archive audit.

## Material missing ranges

Spot has seven short gaps totaling 14 hours. None occurs at a 23:00 UTC prior-completed
bar or a 00:00 UTC conservative execution bar used by the daily design.

Mark data are missing 63 hours on three dates:

- 2022-10-02: hours 01-07, 09-15, and 17-23 UTC;
- 2023-02-24: the same pattern;
- 2026-06-29: the same pattern.

Consequently, the prior 23:00 UTC mark is missing for observations on 2022-10-03,
2023-02-25, and 2026-06-30. The 00:00 UTC mark bar on each observation date exists.
Experiment 001 must pre-register its treatment before performance is viewed. It uses
the greater of the last known mark and `1.01 * perpetual_high` for short-side margin
testing during missing hours. None of the three affected observations is a scheduled
monthly hedge decision, so the proxy cannot create a fill signal.

Index and premium series are auxiliary, not execution sources. They must not be silently
imputed. If used in a later signal or risk rule, their missing observations require a
separate pre-registered treatment.

## Point-in-time alignment

There are 2,125 daily on-chain observations in the common window, from 2021-01-06
through 2026-10-31. Every selected Ethereum block is strictly before its 00:00 UTC
target, and every following block is at or after the target. The maximum selected-block
lag is 107 seconds.

The no-look-ahead convention for a future experiment should be:

1. At the 00:00 UTC observation boundary, on-chain state comes from the last Ethereum
   block strictly before 00:00.
2. Any CEX input considered known at that boundary comes from the completed 23:00 UTC
   hourly bar from the prior day.
3. A trade is priced no earlier than the close of the 00:00 UTC bar (approximately
   01:00 UTC), after the on-chain observation is available. This is intentionally more
   conservative than assuming an instantaneous 00:00 open fill.
4. Funding is booked only at recorded event timestamps while the simulated position is
   open; it must not be inferred from future premium-index data.

This convention avoids using the 00:00-00:59 CEX close to form a 00:00 decision and
prevents an Ethereum block selected near midnight from being treated as known before it
was observed.

## Secondary OKX data

The latest existing OKX archive audit (`20261113T155145Z`) passes its 99.5% threshold
for the shorter 2023-07 through 2026-09 window:

- ETH spot: 28,512 complete hourly bars, zero missing hours and zero post-dedup duplicates;
- ETH swap: 28,512 complete hourly bars, zero missing hours and zero post-dedup duplicates;
- ETH funding: 3,564 events, all 39 months passed and zero duplicate events.

OKX is suitable for a secondary robustness check, but not as a replacement for the
longer Binance primary history. Cross-venue validation must be declared before viewing
strategy performance and should not be used to choose whichever venue backtests better.

## Remaining limits before Experiment 001

- Hourly OHLC does not reveal intrabar liquidation paths. Liquidation safety must use
  mark-price high/low stress, conservative maintenance-margin assumptions, and low gross
  exposure; a bar-level backtest cannot prove absence of intrabar liquidation.
- Historical order-book depth and realized slippage are not present. Costs must therefore
  use pre-registered taker fees plus conservative slippage scenarios rather than fitted
  fills.
- The on-chain state is a one-token quote, not a size-dependent execution curve. Larger
  notional requires either contract quote calls at fixed sizes or an explicit impact
  model before claiming capacity.
- The Binance monthly archive ends at 2026-10 while on-chain state continues to
  2026-11-15. The final 15 on-chain observations are excluded from the common window,
  not forward-filled.
- The existing history is not blind out-of-sample. Walk-forward or pseudo-OOS reporting
  is still required even if the eventual rule has few or no fitted parameters.

## Reproduction

Run the repository command and compare the generated JSON with
`docs/cex_data_coverage_audit.json`:

```bash
lsb-data audit-cex-coverage
```

The detailed machine-readable output includes every missing range and the daily
point-in-time alignment counts.
