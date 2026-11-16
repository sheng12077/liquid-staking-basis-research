# Daily Point-in-Time Lido and Curve State

Date: 2026-11-16 (Asia/Taipei)

## Scope

This infrastructure segment builds a daily point-in-time dataset for future
liquid-staking basis research. It does not calculate a basis signal, position,
strategy return, or acceptance metric.

The dataset is fixed through Ethereum block `26,421,585`, matching the event
backfill and contract-semantics audit.

## Point-in-time rule

For each UTC date from 2021-01-06 through 2026-11-15:

1. Set the observation time to `00:00:00 UTC`.
2. Select the last Ethereum block whose timestamp is strictly less than the
   observation time.
3. Verify that the immediately following block timestamp is greater than or
   equal to the observation time.
4. Execute every state call against the selected historical block.

This rule prevents a daily observation from using state first known after the
UTC boundary. Block selection uses timestamp interpolation followed by an
exact adjacent-block bracket check.

## State calls

Each available daily snapshot includes:

- wstETH `stEthPerToken()`;
- Curve legacy ETH to stETH `get_dy` for an input of 1 ETH;
- Curve legacy stETH to ETH `get_dy` for an input of 1 stETH;
- Curve concentrated WETH to stETH `get_dy` for an input of 1 WETH; and
- Curve concentrated stETH to WETH `get_dy` for an input of 1 stETH.

Exact uint256 results are retained as decimal strings. Floating-point token
amounts are convenience fields only. Every row also records selected and
following block metadata plus the point-in-time stETH implementation.

The raw dataset is `lido_curve_daily_state_v1` under the shared data root. The
canonical output is:

`data/canonical/ethereum/lido_curve_daily_state_v1/daily_state.parquet`

## ABI correction during acquisition

The first run stopped before writing 2022-05-13 because the concentrated pool
was initially configured with the newer
`get_dy(uint256,uint256,uint256)` selector. Historical probing confirmed that
this pool uses Curve's Vyper `get_dy(int128,int128,uint256)` selector
`0x5e0d443f`, matching the previously validated quote at block 20,000,000.

The configuration was corrected before any concentrated-pool row was written.
The resumable runner reused the first 492 valid daily snapshots and continued
without redownloading them. No failed or guessed quote was retained.

## Validation results

- Canonical rows: 2,140
- Columns: 18
- Missing observation dates: 0
- Extra observation dates: 0
- Duplicate or non-increasing daily blocks: 0
- Timestamp bracket failures: 0
- Raw checksum or manifest errors: 0
- Endpoint disclosures: 0
- Canonical Parquet size: 270,679 bytes

Expected availability nulls:

| Field group | Null rows | Reason |
| --- | ---: | --- |
| wstETH conversion | 45 | wstETH was not yet deployed |
| Curve legacy quotes | 0 | available for the full fixed period |
| Curve concentrated quotes | 492 | pool was not yet deployed |

Observed convenience-value ranges:

| Field | Minimum | Maximum |
| --- | ---: | ---: |
| wstETH stETH per token | 1.003748 | 1.249225 |
| Legacy ETH to stETH | 0.997015 | 1.067958 |
| Legacy stETH to ETH | 0.935616 | 1.002167 |
| Concentrated WETH to stETH | 0.999281 | 1.068890 |
| Concentrated stETH to WETH | 0.934682 | 0.999831 |

All available quotes passed the fixed broad data-quality range of 0.5 to 2.0.
These ranges are data observations, not trading-performance results.

## stETH implementation boundaries

`stEthPerToken()` was queried immediately before and at all five historical
stETH implementation transitions. All ten calls succeeded. The exact raw rate
was unchanged across every boundary, so each observed relative jump was zero.
All boundaries passed the fixed maximum absolute relative-jump threshold of
5%.

## Cost

The conservative pre-run model was 786,706 CU, approximately US$0.413021 at
US$0.525 per million CU, below the US$1 guard. Timestamp interpolation reduced
the observed block-header request count substantially below the conservative
25-calls-per-day assumption. The exact billed amount must be read from the
Alchemy dashboard.

## Interpretation limits

- Curve `get_dy` represents a contract quote for the fixed 1-token input at
  the selected block. It does not include gas, transaction latency, MEV,
  failed execution, routing, WETH wrapping, or CEX hedge costs.
- A 00:00 UTC state is not automatically executable at the same timestamp in
  a backtest. Any future signal must trade at a later admissible CEX/on-chain
  time.
- The dataset does not reconstruct intraday basis paths or order-book depth.
- Availability nulls must remain null; they must not be backfilled from later
  contract state.

## Conclusion

The daily point-in-time state gate passes. Historical block mapping, wstETH
conversion rates, Curve executable quotes, deployment-aware availability, and
stETH implementation boundaries are now represented without look-ahead.

The dataset is suitable for the next data-integration stage, but this is not
approval to calculate or tune strategy performance.

## Remaining gates before strategy preregistration

1. Build a bounded-cost canonical event path that omits per-transaction receipt
   calls when gas attribution is not required.
2. Reconcile date and timestamp coverage with CEX ETH spot, perpetual mark,
   funding, and tradable price data.
3. Define the exact economic trade, execution delay, fees, gas, slippage,
   funding, inventory, withdrawal latency, and liquidation assumptions.
4. Preregister the fixed Experiment 001 rules and acceptance thresholds on
   `main` before calculating returns.
