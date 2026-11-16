# Experiment 002 Result: Conservative Isolated wstETH Carry

## Decision

**LSB-P2 is labelled `economically_supported_isolated`.** The fixed 25% wstETH / 75%
isolated-futures allocation passes every preregistered standalone economic,
liquidation, temporal, cost, relative-value, and correctness gate.

It does not earn the additional `candidate_b_sleeve` label. Monthly correlation with
S4 exceeds the locked threshold and the fixed 75% S4 / 25% P2 portfolio reduces CAGR
by more than the allowed 0.50 percentage points.

This is a post-Experiment-001 in-sample redesign, not blind OOS confirmation. The
result supports treating P2 as an independent second-strategy candidate for later
forward validation; it does not authorize paper or live trading.

## Registered primary result

Window: first 2021-02-20 executable observation through the execution following the
2026-10-31 observation. Initial capital is 10,000 USDT-equivalent. Initial deployment
is 25% wstETH long and approximately 25% ETHUSDT short, with 75% of capital
pre-positioned in the isolated futures wallet.

| Metric | LSB-P2 |
|---|---:|
| Terminal NAV | 12,541.08 |
| Net return | 25.41% |
| CAGR | 4.06% |
| Annualized volatility | 0.99% |
| Sharpe | 4.11 |
| Sortino | 5.17 |
| Maximum drawdown | -1.74% |
| Calmar | 2.33 |
| 4% hurdle Sharpe | 0.06 |
| Minimum rolling 365-day return | 1.18% |
| Minimum operational buffer | 64.80% of short notional above reserve |
| Warning / critical hours | 0 / 0 |
| Maintenance breach | No |

P2 clears the locked 3% CAGR and non-negative 4% hurdle-Sharpe thresholds. The hurdle
result is only slightly positive, so the strategy has little excess return above a 4%
cash hurdle even though its raw Sharpe is high.

## Stress suite

| Path | Net return | CAGR | 4% hurdle Sharpe | MDD | Minimum buffer | Breach |
|---|---:|---:|---:|---:|---:|---|
| Primary | 25.41% | 4.06% | 0.06 | -1.74% | 64.80% | No |
| X1 slippage 5x | 24.71% | 3.95% | -0.04 | -2.02% | 65.77% | No |
| X2 gas 5x | 14.42% | 2.39% | -0.54 | -6.79% | 93.26% | No |
| X3 slippage and gas 5x | 13.83% | 2.30% | -0.55 | -7.02% | 94.65% | No |
| X4 margin mark high 1.2x | 25.41% | 4.06% | 0.06 | -1.74% | 36.75% | No |
| X5 positive funding half | 14.87% | 2.46% | -1.56 | -1.94% | 51.66% | No |
| X6 post-entry quote haircut 5% | 22.94% | 3.69% | -0.22 | -2.90% | 70.29% | No |

No registered path reaches the 25% warning threshold or the 10% critical threshold.
The monitoring ledger never changes a position, so the result is produced entirely by
pre-positioned collateral rather than an assumed rescue or dynamic deleveraging.

Experiment 001's 40/60 P1 earned a higher 6.41% CAGR but breached X4 and X5. P2 gives
up 2.35 percentage points of CAGR in exchange for removing both registered margin
failures with a substantial buffer.

## Temporal evidence

| Segment | Total return |
|---|---:|
| Pre-Shapella | 10.73% |
| Post-Shapella | 13.32% |
| 2024-2026 pseudo-OOS diagnostic | 10.86% |
| 2021 partial year | 8.24% |
| 2022 | 1.36% |
| 2023 | 3.16% |
| 2024 | 6.56% |
| 2025 | 2.98% |
| 2026 partial year | 0.98% |

All six calendar segments are positive. The largest contributes 35.41% of the sum of
positive calendar returns, below the locked 50% concentration limit. These are
historical diagnostics; the 2024-2026 segment is not blind OOS.

## Benchmarks and incremental value

| Path | Net return | CAGR | Sharpe | 4% hurdle Sharpe | MDD |
|---|---:|---:|---:|---:|---:|
| C0 cash | 0.00% | 0.00% | n/a | n/a | 0.00% |
| C1-25 ETH + cash | 4.01% | 0.69% | 0.14 | -0.03 | -35.83% |
| C2-25 ETH spot + short | 18.46% | 3.02% | 8.11 | -2.59 | -0.35% |
| C3-25 unhedged wstETH + cash | 9.14% | 1.55% | 0.18 | 0.01 | -35.75% |

P2 improves CAGR over C2-25 by 1.04 percentage points and improves its 4% hurdle
Sharpe materially, passing the locked relative-value gate. C2-25 still has lower
drawdown and higher raw Sharpe, so P2 is not uniformly superior.

The sequential long-leg attribution reports approximately:

- +728.29 USDT from the wstETH share-rate change;
- -5.59 USDT from executable stETH/ETH basis changes;
- +345.87 USDT gross spot-price contribution before the short hedge.

These components are path-dependent and are not an additive causal decomposition of
total strategy PnL. With funding removed, A1 remains margin-feasible but CAGR falls to
1.06%. Freezing the share rate in A2 produces 2.69% CAGR. A3 with post-cost basis fixed
at par produces 4.04% CAGR. Both staking and funding therefore remain economically
material, while the full-window basis contribution is small.

## Costs and funding

Primary registered cost is 160.57 USDT:

| Cost | USDT |
|---|---:|
| Gas | 129.51 |
| Curve adverse slippage | 5.79 |
| Spot fees | 5.91 |
| Spot slippage | 2.96 |
| ETH withdrawal allowance | 9.67 |
| Perpetual fees | 3.36 |
| Perpetual slippage | 3.36 |

Positive funding receipts are 2,108.86 USDT and negative funding payments are
-184.76 USDT. Total cost is 5.66% of gross positive staking accrual plus positive
funding, below the registered 40% threshold. Perpetual turnover is 6,727.15 USDT.

Fixed gas and withdrawal cost make the smaller strategy less capital-efficient than
P1, but not enough to invalidate the 10,000 USDT registered capital level.

## S4 diversification diagnostic

The frozen and repeat S4 NAV files retain the identical SHA-256
`1758308740a9b87b499b4d22bf34d5604eb9c831e08f53c58f6018cce08c0777`.

| Diagnostic | Result | Gate |
|---|---:|---:|
| Daily correlation | 0.048 | absolute <= 0.50 |
| Weekly correlation | 0.529 | absolute <= 0.60 |
| Monthly correlation | 0.644 | absolute <= 0.60 |
| S4 common-period CAGR | 8.18% | reference |
| Fixed 75/25 portfolio CAGR | 7.22% | no more than 0.50 pp lower |
| S4 common-period Sharpe | 4.51 | reference |
| Fixed 75/25 portfolio Sharpe | 5.12 | improve by at least 0.10 |
| S4 common-period MDD | -3.39% | reference |
| Fixed 75/25 portfolio MDD | -2.28% | improve magnitude by at least 10% |

The fixed portfolio improves raw Sharpe, Calmar, and drawdown, but monthly correlation
is 0.644 and portfolio CAGR is 0.96 percentage points below S4. Both exceed their
locked limits. P2 is therefore supported as an isolated strategy candidate, not as a
formally accepted S4 diversifier under Experiment 002.

## Integrity and reproducibility

All registered checks pass:

- the configuration is exactly 25% long and 75% initial futures wallet;
- no post-entry collateral transfer or external rescue occurs;
- primary and X1-X6 have no maintenance breach;
- 6,237 eligible funding events are booked exactly once;
- maximum actual Curve input is 1.522 tokens, below the 10-token quote size;
- maximum hedge-fill residual is 0.000974 ETH, below the 0.001 ETH step;
- residual-delta recomputation error is 0;
- quantity-step error is 0;
- terminal accounting residual is approximately 4.55e-13 USDT;
- all 63 registered mark-gap hours use the adverse proxy;
- every daily execution spot price exists and no spot price is forward-filled;
- Ruff, mypy, and all 30 tests pass;
- a complete second run produces byte-identical SHA-256 hashes for every derived
  output file.

## Interpretation and next boundary

Experiment 002 supports the narrow claim that a substantially overcollateralized,
fully isolated liquid-staking carry sleeve can survive the registered historical and
counterfactual margin paths. It does not establish live execution reliability,
exchange solvency, bridge availability, future Curve liquidity, smart-contract safety,
or blind out-of-sample profitability.

No nearby capital split, warning threshold, or portfolio weight may now be searched on
this sample and presented as confirmatory evidence. The next legitimate step, if the
project continues, is forward paper validation of the frozen 25/75 rules and monitoring
ledger. This report itself does not authorize that step or any deployment.
