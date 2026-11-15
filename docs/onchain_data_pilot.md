# On-Chain Data Pilot

Date: 2026-11-15

## Scope

This pilot evaluates whether an Ethereum archive RPC can support reproducible,
point-in-time liquid-staking research. It does not calculate a basis, trading
signal, position, or strategy return and is not a performance experiment.

The shared strategy-neutral data root is:

`/home/sheng77/working_space/quant_research/data`

## Observations

- Ethereum chain ID was `1`.
- The latest observed block during the pilot was `26,421,036`.
- An archive-state query succeeded at block `12,000,000`.
- The official Ethereum Mainnet wstETH contract
  `0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0` was used.
- Blocks `26,420,937` through `26,421,036` were fetched with the Free-plan
  limit of ten blocks per `eth_getLogs` request.
- The first run downloaded ten raw chunks; an identical second run downloaded
  zero and skipped all ten existing chunks.
- The integrity audit found ten valid chunks, two manifests, twenty manifest
  references, 72 unique logs, and no checksum, log-count, JSON, missing-file,
  or endpoint-disclosure errors.
- The `stEthPerToken()` selector was derived as `0x035faf82`. A historical
  `eth_call` returned approximately `1.0073058721` stETH per wstETH at block
  `12,000,000`; a latest-state call returned approximately `1.2493061337`.
- The local `.env` was ignored by Git and restricted to owner read/write.
- A second 100-block acquisition combined the official Curve concentrated
  stETH/wETH pool `0x828b154032950C8ff7CF8085D841723Db2696056`
  and Lido WithdrawalQueueERC721
  `0x889edC2eDab5f40e902b864aD4d7AdE8E412F9B1` in one address filter. Its audit
  passed with ten chunks and 19 unique logs: 11 from Curve and eight from the
  withdrawal queue.
- The Curve pool identified coin 0 as WETH and coin 1 as stETH. A historical
  `get_dy(0, 1, 1e18)` call at block `20,000,000` returned
  `999946582276815102`; the latest-state call returned
  `1000020445526442411`. This confirms that point-in-time executable quotes can
  be obtained from archived pool state.

## Conclusion

The archive RPC is technically suitable for point-in-time wstETH conversion
rates, historical Curve executable quotes, withdrawal-queue events, and
resumable contract-log acquisition. The implementation preserves raw responses,
records SHA-256 checksums, produces secret-free manifests, enforces the
Free-plan block-range limit, and estimates compute-unit usage.

This is a narrow positive feasibility result, not approval for a historical
backtest or a full paid backfill.

## Deployment registry and backfill estimate

An archive `eth_getCode` binary search recorded the first bytecode block for
each registered contract:

| Contract | Deployment block | UTC date |
| --- | ---: | --- |
| Lido stETH | 11,473,216 | 2020-12-17 |
| Curve stETH/ETH legacy | 11,592,551 | 2021-01-05 |
| Lido wstETH | 11,888,477 | 2021-02-19 |
| Curve stETH/wETH concentrated | 14,759,666 | 2022-05-12 |
| Lido withdrawal queue | 17,172,547 | 2023-05-02 |

At observed head block `26,421,239`, the complete combined range contained
14,948,024 blocks and 2,159 calendar days. Assuming one combined address
filter, 2,000-block PAYG chunks, three daily historical state calls, and
US$0.525 per million CU:

- Free: 1,494,803 log requests and 89,856,582 CU; this exceeds one monthly
  Free allowance and would take multiple quota cycles.
- PAYG: 7,475 log requests and 616,902 CU, estimated at US$0.323874.

The PAYG estimate excludes retries, provider-side range splitting, receipts,
and future canonicalization queries. A US$5 usage cap provides more than ten
times the modeled allowance, but payment should wait until event schemas and
the production acquisition plan are fixed.

## Canonicalization pilot

Official Curve and Lido source declarations were used to register four event
signatures: Curve `TokenExchange`, Lido `WithdrawalRequested`,
`WithdrawalsFinalized`, and `WithdrawalClaimed`.

The real-data canonicalization pilot produced:

- four decoded withdrawal events: two requests and two claims;
- one decoded Curve swap, with the observed direction stETH to WETH;
- 15 unsupported Transfer/Approval events preserved with their raw topics and
  data instead of being silently discarded;
- reconciled unique `(transaction_hash, log_index)` keys;
- successful receipt statuses and positive block timestamps for every decoded
  row;
- block base fee, full-transaction gas used, effective gas price, and total
  transaction fee metadata.

The pilot did not observe a real finalization event in its narrow sample, so
the `WithdrawalsFinalized` layout is covered by a unit test based on the
official Solidity declaration. It must also be observed in the production
backfill audit.

## Remaining gates

Before purchasing a full backfill, the next data pilot must verify:

1. proxy implementation version intervals where event semantics changed;
2. a real observed `WithdrawalsFinalized` event and proxy-version boundary
   audit;
3. a production acquisition dry run using wider PAYG-compatible chunks.

No strategy experiment should begin until those data semantics are documented
and the experiment is preregistered on `main`.

