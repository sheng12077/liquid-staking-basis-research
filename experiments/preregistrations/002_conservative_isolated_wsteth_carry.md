# Experiment 002: Conservative Isolated wstETH Carry

## Registration

- Status: preregistered; no Experiment 002 return has been calculated
- Registration date: 2026-11-16
- Strategy identifier: `LSB-P2`
- Initial capital: 10,000 USDT-equivalent
- Primary venue pair: Curve legacy ETH/stETH pool and Binance ETHUSDT USD-M perpetual
- Locked window: the same first executable 2021-02-20 observation through the
  execution following the 2026-10-31 observation used in Experiment 001

This is a post-Experiment-001 redesign. Experiment 001 showed that its 40% wstETH / 60%
isolated-futures allocation was profitable on the primary path but breached margin in
the registered X4 adverse-mark and X5 funding-haircut stresses. Experiment 002 therefore
tests one economically motivated reduction in deployed notional. It is not blind OOS,
does not erase the Experiment 001 rejection, and may not be described as independent
confirmation.

Passing this experiment permits only later forward-validation planning. It does not
authorize paper trading, live trading, exchange orders, wallet actions, or Raspberry Pi
deployment.

## Research question and fixed hypothesis

Can liquid-staking carry survive the previously failed margin stresses when only 25% of
total capital is converted to wstETH and 75% is pre-positioned in the isolated Binance
futures wallet?

The fixed hypothesis is that lowering both the wstETH long and ETH perpetual short from
approximately 40% to approximately 25% of NAV reduces collateral drift enough to avoid
maintenance breach, while staking accrual and funding still produce at least a 3% CAGR.
No allocation near 25/75 may be tested and substituted after results are observed.

## Frozen strategy rules

Except for the capital split and the monitoring ledger below, every data, execution,
accounting, cost, hedge, exit, stress, and missing-data rule is inherited unchanged from
the preregistered Experiment 001 `LSB-P1` specification.

### Capital and exposure

1. Allocate 25% of initial strategy capital to the on-chain long budget.
2. Allocate 75% to the dedicated Binance USD-M isolated futures wallet.
3. Buy ETH, deduct the registered spot costs, 0.005 ETH withdrawal allowance, entry gas,
   and Curve slippage, then hold the resulting fixed wstETH units.
4. Short ETHUSDT perpetual in the conservative liquidatable-ETH quantity, rounded down
   to the registered 0.001 ETH step.
5. Initial long and short notionals are each approximately 0.25 times NAV; initial total
   gross exposure is approximately 0.50 times NAV.
6. No capital outside the registered 10,000 USDT may be counted, and no external cash,
   S4 capital, cross-margin balance, or on-chain asset may rescue the futures wallet.

### Hedge and collateral maintenance

- Retain Experiment 001's first-calendar-day monthly hedge resize.
- Do not restore a 25/75 allocation after entry.
- Do not sell wstETH to replenish the futures wallet.
- Do not transfer collateral after entry.
- Do not automatically reduce the short in response to a warning.

These exclusions isolate whether pre-positioned collateral alone solves the registered
failure. Dynamic deleveraging or scheduled collateral transfer would be a different
future experiment.

### Monitoring ledger

At every hourly risk check, continue to compute:

`operational_buffer = (wallet_equity - maintenance_reserve) / short_notional`

Record two diagnostic states:

- warning: operational buffer is at or below 25% of short notional;
- critical: operational buffer is at or below 10% of short notional.

The 25% warning is an engineering reserve derived from approximately 20% adverse price
movement plus the 3.5% maintenance/liquidation reserve, rounded conservatively. Warnings
do not change positions. Report warning counts, first timestamp, total warning hours,
longest consecutive warning duration, and any warning-to-breach lead time.

## Frozen inputs, costs, and execution

Use the exact Experiment 001 inputs and point-in-time conventions:

- daily wstETH share rate and fixed-block legacy Curve 10-token quotes;
- Binance ETHUSDT spot, USD-M perpetual, mark-price hourly bars, and recorded funding;
- decisions at 00:00 UTC using the registered pre-00:00 on-chain block and prior
  completed CEX information;
- fills no earlier than the close of the 00:00 UTC bar;
- monthly hedge resizing and final exit exactly as in Experiment 001;
- the same registered mark-gap proxy, with no silent forward-fill.

Costs remain:

- spot taker fee 10 bp and adverse spot slippage 5 bp;
- perpetual taker fee 5 bp and adverse perpetual slippage 5 bp;
- additional Curve slippage 10 bp beyond the fixed 10-token quote;
- 0.005 ETH withdrawal allowance;
- 350,000 entry and 350,000 exit gas units;
- the same post-London base-fee-plus-2-gwei and pre-London median-legacy-gas rules;
- zero yield on cash and futures collateral.

## Frozen stress and attribution suite

Run the same paths without alteration:

- `X1`: all slippage rates multiplied by five;
- `X2`: gas price multiplied by five;
- `X3`: X1 and X2 together;
- `X4`: every hourly mark high multiplied by 1.20 for margin testing only;
- `X5`: positive funding receipts multiplied by 0.50, with negative payments unchanged;
- `X6`: additional 5% haircut on every post-entry stETH-to-ETH quote;
- `A1`: funding rates set to zero;
- `A2`: wstETH share rate frozen at entry;
- `A3`: post-cost stETH/ETH basis fixed at par.

Attributions remain diagnostic and cannot replace the primary path.

## Benchmarks and comparisons

- `C0`: 10,000 USDT zero-yield cash.
- `C1-25`: 25% ETH buy-and-hold plus 75% cash with registered spot costs.
- `C2-25`: 25% ETH spot plus equal ETHUSDT short and 75% isolated futures collateral,
  with the registered CEX rules but no Lido or Curve exposure.
- `C3-25`: 25% unhedged wstETH plus 75% cash under registered on-chain costs.
- `P1`: the frozen Experiment 001 40/60 primary result, reported only as a redesign
  comparison and never used as an acceptance substitute.

Recompute the frozen S4 NAV without changing S4 rules, verify its repeat-run checksum,
and align exact common timestamps.

## Temporal evaluation

There is no fitting or parameter selection. Report the full registered window plus:

- pre-Shapella through 2023-04-12;
- post-Shapella from 2023-04-13;
- 2024-2026 pseudo-OOS diagnostic;
- every calendar year or partial year;
- rolling 365-day results.

All segments remain historical and non-blind. No threshold or rule may be revised using
either the earlier or later segment.

## Correctness gates

All Experiment 001 correctness gates remain mandatory, including point-in-time delay,
unique funding booking, 10-token quote sizing, conversion and residual recomputation,
0.01 USDT accounting tolerance, quantity-step integrity, registered missing-data rules,
byte-identical repeat execution, and passing unit, integration, lint, and type checks.

The configuration must additionally verify exactly 25% long budget and 75% initial
futures-wallet allocation, with no post-entry collateral transfer.

## LSB-P2 economic acceptance gates

Every condition must pass:

1. Primary and X1-X6 have no maintenance breach.
2. Primary minimum operational buffer is at least 25% of short notional above the
   registered reserve.
3. Primary net CAGR is at least 3.00%.
4. Primary 4% hurdle Sharpe is non-negative.
5. Primary maximum drawdown is no worse than -10.00%.
6. Primary minimum rolling 365-day return is greater than -10.00%.
7. Both pre-Shapella and post-Shapella total returns are positive.
8. At least four calendar-year or partial-year segments have positive returns.
9. No calendar segment contributes more than 50% of the sum of positive
   calendar-segment returns.
10. Total registered cost is below 40% of gross positive staking accrual plus positive
    funding receipts. The looser ratio than Experiment 001 is fixed before execution
    because gas and withdrawal costs are largely fixed while deployed long capital is
    reduced.
11. Relative to `C2-25`, LSB-P2 improves at least one of:
    - CAGR by at least 0.25 percentage points;
    - 4% hurdle Sharpe by at least 0.10;
    - maximum-drawdown magnitude by at least 20%.
12. The relative gate cannot pass if LSB-P2 simultaneously reduces CAGR by more than
    0.50 percentage points and worsens maximum-drawdown magnitude by more than 20%
    versus C2-25.
13. Every correctness gate passes.

Failure is labelled `economically_rejected`. Passing is labelled
`economically_supported_isolated` regardless of portfolio diversification outcome.

## Separate diversification diagnostic

Test one fixed multi-strategy allocation: 75% initial S4 capital and 25% initial LSB-P2
capital, without subsequent transfers or rebalancing. No other portfolio weight may be
tested.

To earn the additional label `candidate_b_sleeve`, an economically supported LSB-P2
must also satisfy:

1. absolute S4 correlation no greater than 0.50 daily, 0.60 weekly, and 0.60 monthly;
2. the fixed 75/25 portfolio improves at least one versus S4 alone: Sharpe by 0.10,
   4% hurdle Sharpe by 0.10, maximum-drawdown magnitude by 10%, or Calmar by 0.10;
3. portfolio CAGR is not more than 0.50 percentage points below S4;
4. portfolio maximum-drawdown magnitude is not more than 10% worse than S4.

Failure of this diagnostic does not invalidate an independently economically supported
isolated strategy; it only prevents the B-sleeve label.

## Required outputs

- the complete Experiment 001 hourly, daily, fill, funding, cost, attribution, temporal,
  correctness, and checksum outputs adapted only to the 25/75 allocation;
- primary and X1-X6 breach status and minimum operational buffer;
- warning and critical monitoring statistics for every path;
- C0, C1-25, C2-25, C3-25, P1, A1-A3, and temporal summaries;
- frozen-S4 correlations and fixed 75/25 portfolio metrics;
- a conclusion report that preserves the Experiment 001 result and explicitly states
  that Experiment 002 is an in-sample redesign.

## Prohibited analysis

- no search over 20/80, 25/75, 30/70, or any nearby split;
- no change to warning thresholds after viewing alert frequency;
- no dynamic deleveraging, emergency transfer, cross margin, or external rescue;
- no replacement of a failed primary with a stress, attribution, subperiod, or
  alternative portfolio weight;
- no paper trading, live trading, wallet signing, API-key use, or deployment.
