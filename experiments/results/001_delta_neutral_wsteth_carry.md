# Experiment 001 Result: Delta-Neutral wstETH Carry and Stress-Event Basis

## Decision

**LSB-P1 is labelled `economically_rejected`.** The primary path is profitable and
passes every standalone return, drawdown, temporal, cost, relative-value, and
correctness threshold. It nevertheless fails the locked all-stress margin gate:

- `X4` (hourly mark high multiplied by 1.20 for margin testing) breaches isolated
  margin on 2021-05-10 09:00 UTC;
- `X5` (positive funding receipts multiplied by 0.50) breaches isolated margin on
  2025-08-24 17:00 UTC.

The result therefore cannot be promoted to paper or live trading. The historical
primary path must not be presented alone as an investable strategy.

## Registered primary result

Window: first 2021-02-20 executable observation through the execution following the
2026-10-31 observation. Initial capital is 10,000 USDT-equivalent.

| Metric | LSB-P1 |
|---|---:|
| Terminal NAV | 14,245.57 |
| Net return | 42.46% |
| CAGR | 6.41% |
| Annualized volatility | 1.33% |
| Sharpe | 4.68 |
| Sortino | 6.48 |
| Maximum drawdown | -1.97% |
| Calmar | 3.25 |
| 4% hurdle Sharpe | 1.73 |
| Minimum rolling 365-day return | 1.81% |
| Minimum operational buffer | 7.69% of short notional above reserve |
| Maintenance breach | No |

The attractive primary metrics do not override the registered stress failure.

## Stress suite

| Path | Net return | CAGR | 4% hurdle Sharpe | MDD | Margin result |
|---|---:|---:|---:|---:|---|
| Primary | 42.46% | 6.41% | 1.73 | -1.97% | Pass |
| X1 slippage 5x | 41.32% | 6.26% | 1.51 | -2.43% | Pass |
| X2 gas 5x | 31.47% | 4.92% | 0.31 | -7.01% | Pass |
| X3 slippage and gas 5x | 30.45% | 4.78% | 0.25 | -7.42% | Pass |
| X4 margin mark high 1.2x | n/a | n/a | n/a | n/a | **Breach 2021-05-10** |
| X5 positive funding half | n/a | n/a | n/a | n/a | **Breach 2025-08-24** |
| X6 post-entry quote haircut 5% | 38.34% | 5.86% | 0.97 | -3.87% | Pass |

X4 and X5 returns after breach are not continued and their partial-path performance
statistics are explicitly marked `partial_to_breach_not_comparable` in the machine
output. They are omitted from this comparison table.

## Temporal evidence

| Segment | Total return |
|---|---:|
| Pre-Shapella | 18.41% |
| Post-Shapella | 20.38% |
| 2024-2026 pseudo-OOS diagnostic | 16.44% |
| 2021 partial year | 14.34% |
| 2022 | 2.12% |
| 2023 | 4.85% |
| 2024 | 9.91% |
| 2025 | 4.38% |
| 2026 partial year | 1.42% |

All six calendar segments are positive. The largest segment contributes 38.72% of
the sum of positive calendar-segment returns, below the locked 50% limit. The
2024-2026 segment is only pseudo-OOS; it was historically available when the design
was written and is not blind OOS.

## Benchmarks and mechanism

| Path | Net return | CAGR | Sharpe | 4% hurdle Sharpe | MDD |
|---|---:|---:|---:|---:|---:|
| C0 cash | 0.00% | 0.00% | n/a | n/a | 0.00% |
| C1 40% ETH + 60% cash | 6.41% | 1.10% | 0.20 | 0.09 | -49.36% |
| C2 ETH spot + USD-M short | 29.53% | 4.65% | 8.00 | 1.09 | -0.53% |
| C3 unhedged wstETH + cash | 15.83% | 2.61% | 0.25 | 0.14 | -49.81% |

LSB-P1 improves CAGR over C2 by 1.76 percentage points and therefore passes the
registered incremental-value comparison. C2 has materially lower volatility and a
higher Sharpe, so the improvement is return-driven rather than uniformly superior.

Sequential long-leg attribution reports approximately:

- +1,190.75 USDT from the wstETH share-rate change;
- -9.15 USDT from executable stETH/ETH basis changes;
- +565.49 USDT gross spot-price contribution before the short hedge.

These sequential components are path-dependent and are not claimed as an additive
causal decomposition of total strategy PnL. A1 with funding set to zero breaches on
2021-11-08 and is a partial diagnostic, which reinforces that funding receipts also
provide material margin support. A2 with the share rate frozen returns 27.52%; A3
with post-cost basis fixed at par returns 42.26%.

## Costs and funding

Primary registered cost is 174.03 USDT:

| Cost | USDT |
|---|---:|
| Gas | 129.51 |
| Curve adverse slippage | 9.47 |
| Spot fees | 9.58 |
| Spot slippage | 4.79 |
| ETH withdrawal allowance | 9.67 |
| Perpetual fees | 5.50 |
| Perpetual slippage | 5.50 |

Positive funding receipts are 3,448.34 USDT and negative funding payments are
-302.13 USDT. Total cost is 3.75% of gross positive staking accrual plus positive
funding, comfortably below the registered 30% gate. Perpetual turnover is 11,002.86
USDT.

## S4 diversification test

The frozen and independently repeated S4 NAV files have identical SHA-256
`1758308740a9b87b499b4d22bf34d5604eb9c831e08f53c58f6018cce08c0777`.

| Diagnostic | Result | Gate |
|---|---:|---:|
| Daily correlation | 0.094 | absolute <= 0.50 |
| Weekly correlation | 0.527 | absolute <= 0.60 |
| Monthly correlation | 0.636 | absolute <= 0.60 |
| S4 common-period CAGR | 8.18% | reference |
| Fixed 50/50 CAGR | 7.31% | no more than 0.50 pp lower |
| S4 common-period Sharpe | 4.51 | reference |
| Fixed 50/50 Sharpe | 6.14 | improve by at least 0.10 |
| S4 common-period MDD | -3.39% | reference |
| Fixed 50/50 MDD | -1.26% | improve magnitude by at least 10% |

The portfolio improves Sharpe, hurdle Sharpe, Calmar, and drawdown. It nevertheless
fails two locked diversification gates: monthly correlation is 0.636 and portfolio
CAGR is 0.87 percentage points below S4, worse than the allowed 0.50 percentage-point
reduction. This is secondary because the economic stress gate already rejects LSB-P1.

## LSB-D1 diagnostic

The discount-triggered diagnostic completes four episodes, returns 1.89% in total,
and has a 0.33% CAGR. Two episodes profit and two lose. The largest episode supplies
64.14% of total positive episode profit. Although the count exceeds the registered
minimum of three completed episodes, the result is economically weak and
event-concentrated. D1 has no promotion authority and cannot replace LSB-P1.

## Integrity and reproducibility

All registered implementation checks pass:

- 6,237 eligible funding events are booked exactly once;
- maximum actual Curve input is 2.489 tokens, below the 10-token quote size;
- maximum hedge-fill residual is 0.000955 ETH, below the 0.001 ETH step;
- residual-delta recomputation error is 0;
- maximum quantity-step error is approximately 2.27e-13;
- terminal accounting residual is 0.00 USDT;
- the 63 hours on the three registered mark-gap dates use the adverse proxy;
- every daily execution spot price exists and no spot price is forward-filled;
- Ruff, mypy, and all 28 tests pass;
- a complete second run produces byte-identical SHA-256 hashes for every derived
  output file.

The first performance attempt stopped before simulation because an input loader
incorrectly required spot prices during 13 non-execution hours. The correction uses
the complete perpetual timeline, requires spot only at registered daily execution
bars, and does not forward-fill. No performance was available before that correction.

## Interpretation

The historical mechanism is real enough to merit retaining as a documented research
result: staking accrual and funding together produce a smooth primary path, while
executable basis contributes little over the full sample. The failure mode is also
substantive. Keeping 60% in the isolated futures wallet is insufficient under the
locked adverse mark or lower-positive-funding paths, and the preregistration forbids
hypothetical collateral rescue.

No capital split, leverage, reserve, or funding rule may now be retuned on this same
sample and reported as confirmatory Experiment 001. A future redesign would require a
new economic hypothesis, new preregistration, and genuinely new validation evidence.
This experiment authorizes no paper trading, live trading, wallet action, or
Raspberry Pi deployment.
