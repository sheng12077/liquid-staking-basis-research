# Experiment 001: Delta-Neutral wstETH Carry and Stress-Event Basis

## Material Passport

- Origin skill: academic-research-suite / experiment-agent
- Origin mode: plan
- Origin date: 2026-11-16
- Verification status: UNVERIFIED
- Version label: code_plan_v1

## Registration

- Status: preregistered; no Experiment 001 performance has been calculated
- Strategy repository: `liquid_staking_basis`
- Strategy identifiers: `LSB-P1` (primary) and `LSB-D1` (diagnostic)
- Primary venue pair: Curve legacy ETH/stETH pool and Binance ETHUSDT USD-M perpetual
- Initial capital: 10,000 USDT-equivalent
- Locked primary window: first executable observation on or after 2021-02-20 through
  the execution following the 2026-10-31 observation
- Registration date: 2026-11-16

This repository uses strategy-local experiment numbering. Experiment 001 is the
first performance experiment for the liquid-staking-basis strategy; experiment numbers
from the separate `funding_carry` repository are not inherited here. Earlier planning
documents are normalized to this repository-local identifier in the registration
history.

Passing this historical experiment permits only later portfolio research. It does not
authorize paper trading, live trading, capital deployment, or Raspberry Pi work.

## Research question and hypotheses

### Primary question

Does a conservatively collateralized long-wstETH/short-ETH-perpetual position produce
positive net carry after staking accrual, liquid-staking basis changes, perpetual
funding, CEX costs, Curve execution, Ethereum gas, and liquidation constraints?

### Primary directional hypothesis

`LSB-P1` should earn two structurally distinct cash-flow components: Lido staking
accrual embedded in the stETH-per-wstETH share rate and funding received by a short
ETH perpetual when funding is positive. These may be offset by negative funding,
stETH/ETH discount widening, execution cost, gas, protocol loss, and isolated CEX
margin risk. The registered expectation is that the combined net CAGR clears 4% and
that adding wstETH improves on an otherwise identical ETH-spot/short-perpetual carry
benchmark.

### Diversification hypothesis

Because `LSB-P1` still contains perpetual funding carry, low correlation with the
frozen BTC COIN-M S4 strategy is uncertain rather than assumed. It qualifies as a
multi-strategy B sleeve only if it passes the separately registered correlation and
50/50 portfolio-improvement gates. Otherwise a profitable result is labelled
`standalone_carry_only`, not a diversifier.

### Diagnostic hypothesis

`LSB-D1` tests whether rare, executable stETH discounts of at least 2% support a
delta-hedged convergence trade. It is diagnostic because the number of independent
episodes may be too small for promotion. Its outcome cannot replace `LSB-P1` and no
threshold may be altered after results are viewed.

## Economic rationale and evidence base

- Lido documents stETH as a rebasing claim on pooled ETH whose balance normally
  changes with daily oracle reports; wstETH is the non-rebasing wrapper whose
  stETH-per-token share rate embeds the accrual.
- Secondary-market stETH may trade away from one ETH. Protocol withdrawals provide a
  redemption path after Shapella but remain subject to queues, limits, timing,
  protocol operation, and upstream Ethereum withdrawal mechanics.
- Published liquid-staking research documents time-varying and clustered stETH basis
  risk, including the 2022 discount, and relates wider basis to liquidity,
  concentration, and risk conditions.
- Perpetual funding helps anchor perpetual and spot prices, but crypto carry is
  volatile and limited by margin, liquidity, venue, and arbitrage-capital frictions.
- Leveraged liquid-staking positions can amplify forced selling and liquidation.
  Experiment 001 therefore uses less than one times total gross exposure, isolates
  CEX collateral from the on-chain asset, and fails rather than rescues a breached
  margin path with a hypothetical instant collateral transfer.

These sources motivate the mechanism and risks; they do not determine a historically
optimal parameter.

## Frozen data inputs

### On-chain state

The existing `lido_curve_daily_state_v1` observation for calendar day `t` is the last
Ethereum block strictly before 00:00 UTC on `t`. It supplies:

- `stEthPerToken()` for wstETH accounting;
- Curve legacy ETH-to-stETH and stETH-to-ETH quotes;
- block number and timestamp.

Before any return is calculated, the implementation branch must augment the same
fixed observation blocks with:

- legacy-pool `get_dy` quotes for exactly 10 ETH to stETH and 10 stETH to ETH;
- block `baseFeePerGas`.

This is a registered deterministic data addition, not a parameter search. The
10-token effective rate is used for any smaller strategy trade as a conservative
impact proxy. If any actual primary trade exceeds 10 input tokens, the experiment
fails its sizing-integrity check and may not silently extrapolate.

### CEX state

- Binance ETHUSDT spot hourly OHLC;
- Binance ETHUSDT USD-M perpetual hourly OHLC;
- Binance ETHUSDT mark-price hourly OHLC;
- recorded ETHUSDT funding events and funding rates.

The primary window ends with October 2026 because the complete Binance monthly
archive ends there. Later on-chain observations are excluded rather than
forward-filled.

### Withdrawal and swap events

Canonical Curve swaps and Lido withdrawal requests, finalizations, and claims may be
used only for point-in-time liquidity and queue diagnostics. They are not entry
signals in `LSB-P1`, may not define a tuned threshold, and may not replace missing
prices.

### Frozen S4 comparison

The portfolio analysis uses the already-frozen S4-CM1 BTC strategy from funding-carry
Experiment 012, recomputed without changing its rules. Daily returns are aligned over
the exact common period. No S4 parameter or Experiment 001 weight is optimized.

## Point-in-time and execution convention

1. The decision timestamp is 00:00 UTC.
2. The on-chain state is the registered last block strictly before 00:00.
3. CEX information known at decision time ends with the completed 23:00 UTC bar from
   the prior day. Funding is known only at its recorded event timestamp.
4. CEX fills occur no earlier than the close of the 00:00 UTC bar, approximately
   01:00 UTC. The fill cannot use that bar to form the preceding decision.
5. A Curve quote observed at the decision block is adjusted by the registered adverse
   DEX slippage. The one-hour observation-to-execution uncertainty is a limitation and
   is stressed at five times slippage.
6. No future price, quote, funding rate, queue state, or implementation state enters a
   decision.

## Primary strategy: LSB-P1

### Initial capital and entry

At the first day on or after 2021-02-20 for which all required inputs and the 10-token
quotes pass audit:

1. Allocate 40% of initial USDT capital to the on-chain long budget and 60% to a
   dedicated Binance USD-M futures wallet.
2. Buy ETH for the 40% long budget at the registered CEX fill, deducting spot fee and
   spot slippage.
3. Deduct the fixed Binance ETH withdrawal allowance, entry gas, and Curve adverse
   slippage.
4. Exchange the remaining ETH to stETH through the Curve legacy pool using the
   10-ETH effective quote, then wrap all resulting stETH to wstETH.
5. Short ETHUSDT perpetual in ETH quantity equal to the wstETH position's conservative
   liquidatable ETH amount after entry.

No notional is borrowed for the on-chain long. Initial total gross exposure is
approximately 0.80 times NAV: 0.40 long and 0.40 short. Initial futures notional is
approximately 0.67 times the isolated 60% futures wallet.

### Long position accounting

The wstETH token quantity remains fixed until exit. On observation day `t`:

`steth_units_t = wsteth_units * steth_per_wsteth_t`

`liquidatable_eth_t = steth_units_t * legacy_10_steth_to_eth_rate_t`

The on-chain long is valued in USDT using `liquidatable_eth_t` and the latest
completed non-future ETHUSDT spot close. This recognizes both staking accrual and
executable stETH/ETH basis. It does not value stETH at an assumed one-to-one peg.

### Perpetual PnL and funding

For a linear USD-M short of `q` ETH, price PnL over a valuation interval is:

`short_pnl_usdt = q * (previous_mark - current_mark)`

At each recorded funding event, a positive Binance funding rate is a receipt to the
short and a negative rate is a payment:

`funding_pnl_usdt = q_event * mark_event * funding_rate`

Each event is booked once using the latest non-future mark. Funding does not accrue
between recorded events.

### Hedge maintenance

- At entry, short quantity equals conservative liquidatable ETH.
- Thereafter, hedge resizing occurs only on the first calendar day of each month.
- The 00:00 observation determines target quantity; the resize fills at the close of
  the 00:00 CEX bar.
- Target short quantity equals that day's conservative liquidatable ETH amount.
- Only the quantity difference trades. No wstETH is sold to rebalance the 40/60
  allocation and no on-chain/CEX collateral transfer is assumed.
- Quantity rounds down to the Binance ETHUSDT quantity step recorded in the instrument
  registry. Residual delta is retained and reported.

This calendar rule replaces a fitted no-trade threshold. There is no daily funding,
basis, volatility, or momentum filter.

### Exit

At the execution following the 2026-10-31 observation:

1. close the complete ETHUSDT short;
2. unwrap wstETH to stETH;
3. exchange stETH to ETH using the legacy-pool 10-stETH effective rate and adverse
   DEX slippage;
4. deduct exit gas;
5. sell the resulting ETH to USDT with registered CEX costs;
6. combine on-chain proceeds with the futures wallet to obtain terminal NAV.

Protocol withdrawal is not substituted after seeing whether Curve or withdrawal is
historically better.

## Diagnostic strategy: LSB-D1

`LSB-D1` uses the same 40/60 capital, hedge, costs, margin model, and execution lag,
but is flat unless a stress discount occurs.

- Executable discount is `1 - legacy_10_steth_to_eth_rate`.
- Enter when the 00:00 observed executable discount is at least 2.00%.
- Exit when the observed discount is at most 0.50% or after 180 calendar days,
  whichever occurs first.
- After an exit, re-entry requires the discount first to reset to at most 0.50% and
  later cross back to at least 2.00%.
- No overlapping positions and no pyramiding.
- Flat capital earns zero.

The 2.00%, 0.50%, and 180-day rules are locked economic stress definitions, not
optimized values. `LSB-D1` must report the number of independent episodes and the
share of profit from its largest episode. It has no promotion authority and cannot
replace a failed `LSB-P1`.

## Costs

### Primary costs

- Binance spot taker fee: 10 basis points per fill.
- Binance USD-M perpetual taker fee: 5 basis points per fill.
- Adverse CEX spot slippage: 5 basis points per fill.
- Adverse perpetual slippage: 5 basis points per fill.
- Additional adverse Curve slippage beyond the 10-token `get_dy` quote: 10 basis
  points per swap.
- Binance ETH withdrawal allowance: 0.005 ETH at entry.
- Entry gas: 350,000 gas units.
- Exit gas: 350,000 gas units.
- Gas price after EIP-1559 activation: observation-block base fee plus a fixed 2 gwei
  priority fee. Before `baseFeePerGas` exists, use the median legacy `gasPrice` of all
  transactions in the observation block; do not add a second priority-fee allowance.
- Cash and futures collateral yield: zero.

The gas budgets include Curve exchange, approvals, wrap/unwrap, and the final ETH
transfer as conservative aggregate allowances. No maker, VIP, BNB, referral, rebate,
MEV rebate, lending yield, or promotional discount is permitted.

### Pre-performance gas-semantic clarification

On 2026-11-16, the first execution-state acquisition stopped on 2021-02-20 before
writing a snapshot because the selected pre-London block correctly had no
`baseFeePerGas`. No strategy return, NAV, or acceptance metric had been calculated or
viewed. The legacy-block median rule above was therefore registered before resuming
data acquisition. It resolves a protocol-era data absence only; it does not change
gas units, costs after EIP-1559, strategy rules, stress multipliers, or acceptance
thresholds.

### Cost stresses

- `X1`: multiply every registered slippage rate by five.
- `X2`: multiply gas price by five, leaving gas units unchanged.
- `X3`: apply both `X1` and `X2`.

## Margin, liquidation, and operational risk

- The Binance futures wallet is isolated from the on-chain wstETH asset.
- No instant collateral injection, portfolio margin, cross-exchange netting, or
  hypothetical rescue is permitted.
- Margin is checked at every hourly mark-price high because a price rise is adverse
  to the short.
- Maintenance plus liquidation reserve is fixed at 3.5% of current short notional.
- A breach occurs when futures-wallet equity, including unrealized PnL and all booked
  funding/fees, is less than or equal to that reserve. The path is immediately marked
  operationally infeasible and cannot resume.
- Operational buffer is `(wallet_equity - reserve) / short_notional`.
- During the three registered mark-data gap dates, use the greater of the last known
  mark and `1.01 * perpetual_high` for short-side margin testing. This is a
  conservative proxy, not silent interpolation.
- `X4`: multiply every hourly mark high by 1.20 for margin testing only.
- `X5`: multiply positive funding receipts by 0.50 while leaving negative funding
  payments unchanged.
- `X6`: impose an additional 5% haircut on every post-entry stETH-to-ETH liquidation
  quote while leaving the entry price unchanged.

Primary and all X1-X6 paths must report any maintenance breach, minimum operational
buffer, and time to breach. Historical Binance maintenance tiers are unavailable;
the fixed reserve is a conservative registered proxy, not exact liquidation
reconstruction.

## Frozen benchmarks and counterfactuals

- `C0`: zero-yield 10,000 USDT cash.
- `C1`: 40% ETH buy-and-hold plus 60% zero-yield USDT, with the same spot entry and
  exit costs.
- `C2`: 40% ETH spot plus an equal ETHUSDT perpetual short and 60% futures margin,
  using the same hedge schedule and CEX costs but no Lido or Curve exposure. This is
  the primary incremental-value comparator.
- `C3`: 40% unhedged wstETH plus 60% zero-yield USDT under the same on-chain costs.
- `A1`: primary with all funding rates set to zero.
- `A2`: primary with `steth_per_wsteth` frozen at entry, preserving basis and funding
  but removing subsequent staking accrual.
- `A3`: primary with the stETH-to-ETH basis fixed at par after costs, preserving
  staking accrual and funding.

Attribution paths are diagnostics, not alternative strategies. Their differences are
path-dependent and must not be presented as additive causal decomposition.

## Temporal evaluation and pseudo-OOS disclosure

There is no training or parameter fitting. The complete rule is fixed in this commit.
The full registered window is the primary evaluation, with mandatory reporting for:

- pre-Shapella: entry through 2023-04-12;
- post-Shapella: 2023-04-13 through exit;
- pseudo-OOS diagnostic: 2024-01-01 through exit;
- every calendar year or partial calendar year;
- rolling 365-day outcomes.

The 2024-2026 segment is called pseudo-OOS only to enforce chronological reporting.
It is not blind OOS: the historical period and data were available when this design
was written. No choice may be revised using either the earlier or later segment.

## Required outputs

- Hourly CEX wallet, mark PnL, funding, fees, notional, margin reserve, and operational
  buffer.
- Daily wstETH units, stETH share rate, executable basis, liquidatable ETH, residual
  delta, component PnL, and total NAV.
- Every decision, trigger, fill, quote timestamp, funding event, and cost ledger entry.
- Net return, CAGR, annualized volatility, Sharpe, Sortino, maximum drawdown, Calmar,
  4% hurdle Sharpe, minimum rolling 365-day return, turnover, and time in market.
- Gross staking accrual, positive and negative funding, basis contribution, DEX/CEX
  fees, gas, withdrawal allowance, and total cost.
- Full-window, regime, calendar, pseudo-OOS, C0-C3, A1-A3, X1-X6, and LSB-D1 summaries.
- Daily, weekly, and monthly correlations with frozen S4.
- Fixed 50/50 initial S4/LSB-P1 portfolio metrics over the exact common period. The
  two normalized sleeve NAVs are added without later transfers or rebalancing. No
  other portfolio weight is tested.
- Deterministic configuration, input manifest, output checksums, and repeat-run check.

## Correctness gates

All must pass:

- no future observation enters a decision or fill;
- every funding event is unique, uses a non-future mark, and is booked at most once;
- all actual DEX inputs are no greater than the registered 10-token quote size;
- wstETH-to-stETH conversion independently recomputes within `1e-12` token;
- linear-perpetual PnL and residual delta independently recompute within `1e-10` ETH;
- maximum absolute accounting residual is no greater than 0.01 USDT;
- all fills respect instrument step size and the registered execution delay;
- missing data follow only the registered rules and are never silently forward-filled;
- identical inputs and configuration reproduce byte-identical summary JSON and
  checksums;
- all unit, integration, lint, and static-type checks pass.

## LSB-P1 economic promotion gates

`LSB-P1` is economically supported only if every condition below passes:

1. Primary and X1-X6 have no maintenance breach.
2. Primary net CAGR is at least 4.00%.
3. Primary 4% hurdle Sharpe is at least 0.50.
4. Primary maximum drawdown is no worse than -10.00%.
5. Primary minimum rolling 365-day return is greater than -10.00%.
6. Both pre-Shapella and post-Shapella subperiod total returns are positive.
7. At least four calendar-year or partial-year segments have positive return.
8. No single calendar segment contributes more than 50% of the sum of positive
   calendar-segment PnL.
9. Total trading, gas, withdrawal, and slippage cost is below 30% of gross positive
   staking accrual plus positive funding receipts.
10. Relative to `C2`, `LSB-P1` improves at least one of:
    - CAGR by at least 0.50 percentage points;
    - 4% hurdle Sharpe by at least 0.25;
    - maximum-drawdown magnitude by at least 20%.
11. The relative gate cannot pass if `LSB-P1` simultaneously reduces CAGR by more than
    0.50 percentage points and worsens maximum-drawdown magnitude by more than 20%
    versus `C2`.
12. Every correctness gate passes.

Failure is reported as `economically_rejected`. Thresholds may not be softened after
observing results.

## B-sleeve diversification gates

An economically supported `LSB-P1` is promoted from standalone carry to a candidate B
sleeve only if all conditions below also pass over the common S4 period:

1. Absolute return correlation with S4 is no greater than 0.50 daily, 0.60 weekly,
   and 0.60 monthly.
2. The fixed 50/50 initial S4/LSB-P1 portfolio improves at least one of the following
   relative to S4 alone:
   - Sharpe by at least 0.10;
   - 4% hurdle Sharpe by at least 0.10;
   - maximum-drawdown magnitude by at least 10%;
   - Calmar by at least 0.10.
3. The 50/50 portfolio does not reduce CAGR by more than 0.50 percentage points and
   does not worsen maximum-drawdown magnitude by more than 10%.

If the economic gates pass but any diversification gate fails, the locked label is
`standalone_carry_only`. No correlation threshold, portfolio weight, or return
frequency may be changed on this dataset.

## LSB-D1 interpretation rule

Report `LSB-D1` without a promotion decision. Fewer than three independent completed
episodes is explicitly insufficient evidence of repeatability, regardless of return
or Sharpe. A large return from one episode must be described as event concentration,
not robust alpha.

## Implementation order after registration

1. Commit this preregistration on `main` before calculating any Experiment 001 return.
2. Create `exp/liquid-staking-basis-001`.
3. Add and audit the registered 10-token quotes and block base fees without producing
   strategy returns.
4. Implement deterministic accounting, fixtures, and tests.
5. Run the complete registered suite once; do not inspect an incomplete primary and
   then alter rules.
6. Produce the result report, integrity checks, and repeat-run checks.
7. Merge only a supported conclusion with `--no-ff`, then delete the topic branch.

## Exclusions

- no threshold, lookback, venue, pool, hedge frequency, capital split, leverage,
  portfolio weight, or sample-window search;
- no use of the newer concentrated Curve pool to select a historically better route;
- no maker-fill assumption, order-book reconstruction, or hidden liquidity rebate;
- no lending, recursive staking, LP provision, restaking, options, dated futures, or
  cross-margin portfolio netting;
- no paper trading, live trading, exchange order placement, wallet signing, API-key
  use, or Raspberry Pi deployment;
- no replacement of a failed primary by LSB-D1, a stress path, a subperiod, OKX, or a
  better-looking attribution path.

## References

1. Scharnowski, S., and Jahanshahloo, H. “The Economics of Liquid Staking
   Derivatives: Basis Determinants and Price Discovery.” *Journal of Futures Markets*.
   <https://doi.org/10.1002/fut.22556>
2. He, S., Manela, A., Ross, O., and von Wachter, V. “Fundamentals of Perpetual
   Futures.” <https://arxiv.org/abs/2212.06888>
3. Schmeling, M., Schrimpf, A., and Todorov, K. “Crypto Carry.” BIS Working Paper
   1087. <https://www.bis.org/publ/work1087.htm>
4. Huth, M., et al. “Leverage Staking with Liquid Staking Derivatives: Opportunities
   and Risks.” <https://arxiv.org/abs/2401.08610>
5. Lido, “Lido Contract,” “wstETH,” “Tokens Integration Guide,” “Withdrawal Queue,”
   and “Public Risk Disclosure.” <https://docs.lido.fi/contracts/lido/>
6. Curve Finance, legacy StableSwap pool and `get_dy` documentation.
   <https://docs.curve.finance/developer/amm/legacy/stableswap/pools/plain-pools/>
7. Binance, USD-M Futures developer documentation.
   <https://developers.binance.com/docs/derivatives/usds-margined-futures/>
