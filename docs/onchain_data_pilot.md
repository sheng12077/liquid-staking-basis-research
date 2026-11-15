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

## Conclusion

The archive RPC is technically suitable for point-in-time wstETH conversion
rates and resumable contract-log acquisition. The implementation preserves raw
responses, records SHA-256 checksums, produces secret-free manifests, enforces
the Free-plan block-range limit, and estimates compute-unit usage.

This is a narrow positive feasibility result, not approval for a historical
backtest or a full paid backfill.

## Remaining gates

Before purchasing a full backfill, the next data pilot must verify:

1. authoritative contract addresses and deployment blocks across relevant Lido
   versions;
2. Curve pool swap events and historical executable pool state;
3. Lido withdrawal request, finalization, and claim events;
4. block timestamps, base fees, transaction gas, and canonical Parquet output;
5. actual request density and PAYG cost for the proposed historical window.

No strategy experiment should begin until those data semantics are documented
and the experiment is preregistered on `main`.

