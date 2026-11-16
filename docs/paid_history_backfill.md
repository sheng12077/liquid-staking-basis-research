# Paid Ethereum Event Backfill

Date: 2026-11-16 (Asia/Taipei)

## Scope

This infrastructure segment acquired and reconciled the complete raw event
history needed for the event-driven portion of liquid-staking basis research.
It did not calculate a basis, signal, position, or strategy return.

The acquisition range was frozen before the run at Ethereum block
`26,421,585`. Production requests used 2,000-block chunks, immutable raw JSON
responses, SHA-256 filenames, resumable writes, and address plus topic filters.

## Fixed datasets

### Curve stETH swaps

- Dataset ID: `curve_steth_swaps_full_history`
- Configured blocks: 11,592,551 through 26,421,585 inclusive
- Contracts: legacy stETH/ETH and concentrated stETH/WETH pools
- Event: `TokenExchange(address,int128,uint256,int128,uint256)`
- Chunks: 7,415
- Unique events: 323,055
- Legacy pool events: 306,300
- Concentrated pool events: 16,755
- First observed event block: 11,594,401
- Last observed event block: 26,421,274
- Raw size: approximately 251 MB

### Lido withdrawals

- Dataset ID: `lido_withdrawals_full_history`
- Configured blocks: 17,172,547 through 26,421,585 inclusive
- Contract: WithdrawalQueueERC721
- Events: `WithdrawalRequested`, `WithdrawalsFinalized`, and
  `WithdrawalClaimed`
- Chunks: 4,625
- Unique events: 275,957
- Requested events: 141,864
- Finalized events: 1,280
- Claimed events: 132,813
- First observed event block: 17,266,004
- Last observed event block: 26,421,554
- Raw size: approximately 205 MB

## Cost and runtime

The fixed production plan issued 12,040 `eth_getLogs` requests. At 60 CU per
request and US$0.525 per million CU, the modeled log-request usage was 722,400
CU, or US$0.379260. This is an estimate, not an Alchemy invoice measurement.

The Curve acquisition took approximately 21.6 minutes and the withdrawal
acquisition approximately 13.3 minutes. The combined production download took
approximately 35 minutes, excluding validation and local reconciliation.

## Validation

Both standard integrity audits passed with zero errors. They verified all
12,040 raw files, SHA-256 filename prefixes, manifest references, JSON-RPC
result types, log counts, and absence of endpoint disclosure.

The complete-history reconciliation also passed both datasets with zero
errors. It verified:

- contiguous configured block coverage with no gaps or overlaps;
- every event fell within its chunk's block range;
- every event matched the configured contract address and topic filter;
- manifest log counts matched the raw responses; and
- all 599,012 `(transaction_hash, log_index)` keys were unique.

## Conclusion

The targeted raw event backfill is complete and internally consistent through
block 26,421,585. PAYG removed the Free-tier block-range bottleneck, and the
topic-filtered production design avoided irrelevant ERC-20 and ERC-721
Transfer/Approval logs.

This conclusion applies only to raw Curve swap and Lido withdrawal events. It
does not establish backtest readiness or strategy profitability.

## Remaining gates before Experiment 001

1. Document proxy implementation intervals and confirm event semantics across
   upgrades.
2. Acquire point-in-time daily state snapshots for wstETH conversion rates and
   executable Curve quotes.
3. Design a scalable canonicalization path. The pilot implementation performs
   per-transaction receipt enrichment and should not be run over 599,012 events
   before its RPC cost is separately estimated and bounded.
4. Reconcile the on-chain datasets with CEX mark price, perpetual, and funding
   coverage.
5. Preregister the strategy hypothesis, fixed rules, costs, risk model, and
   acceptance thresholds on `main` before calculating performance.
