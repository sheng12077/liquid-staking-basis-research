# Historical Contract Semantics Audit

Date: 2026-11-16 (Asia/Taipei)

## Scope

This audit determines whether the Ethereum contracts used by the
liquid-staking data pipeline changed implementation or runtime bytecode during
the historical research period. It does not calculate a basis, signal,
position, or strategy return.

The audit is fixed through Ethereum block `26,421,585`, matching the paid raw
event backfill. Raw upgrade evidence is stored outside Git under the shared
data root. The reproducible interval registry is
`docs/proxy_implementation_intervals.json`.

## Evidence and method

- The Withdrawal Queue is a Lido `OssifiableProxy`. Its complete
  `Upgraded(address)` history was acquired, and every transition was verified
  against the historical ERC-1967 implementation storage slot.
- stETH is an Aragon `AppProxyUpgradeable`, not an ERC-1967 proxy. The complete
  Lido DAO Kernel `SetApp` history was acquired, then restricted to the app
  bases namespace and Lido app ID. Every transition was verified with a
  historical `implementation()` call on the stETH proxy.
- Proxy-shell and implementation runtime bytecode were hashed at the relevant
  historical blocks.
- wstETH and the two Curve pools are direct deployments. Their deployment and
  audit-end runtime bytecode hashes were compared.
- Both raw upgrade-event datasets passed the existing checksum and manifest
  integrity audit with zero errors.

Primary references:

- Lido mainnet registry:
  https://github.com/lidofinance/core/blob/master/deployed-mainnet.json
- Lido deployed-contract documentation:
  https://docs.lido.fi/deployed-contracts/
- Lido OssifiableProxy documentation:
  https://docs.lido.fi/contracts/ossifiable-proxy/
- Aragon AppProxyUpgradeable source:
  https://github.com/aragon/aragonOS/blob/next/contracts/apps/AppProxyUpgradeable.sol
- Lido WithdrawalQueueERC721 source:
  https://github.com/lidofinance/core/blob/master/contracts/0.8.9/WithdrawalQueueERC721.sol
- Lido wstETH source:
  https://github.com/lidofinance/core/blob/master/contracts/0.6.12/WstETH.sol
- Curve legacy stETH pool source:
  https://github.com/curvefi/curve-contract/blob/master/contracts/pools/steth/StableSwapSTETH.vy

## Results

### Withdrawal Queue

The proxy emitted two `Upgraded` events:

| Start block | End block | Implementation | Interpretation |
| ---: | ---: | --- | --- |
| 17,172,547 | 17,266,003 | `0x6f6541c2203196feedd14cd2c09550da1cbeda31` | Initial deployment implementation |
| 17,266,004 | 26,421,585 | `0xe42c659dc09109566720ea8b2de186c2be7d94d9` | WithdrawalQueueERC721 implementation |

The first selected withdrawal event in the complete raw dataset occurs at
block `17,266,004`, exactly when the WithdrawalQueueERC721 implementation was
activated. No selected withdrawal events occurred under the initial
implementation, and no later implementation transition occurred through the
audit end.

Therefore all 275,957 selected `WithdrawalRequested`, `WithdrawalsFinalized`,
and `WithdrawalClaimed` events share one implementation and the registered
event layouts are historically consistent for this dataset.

### stETH

The Aragon Kernel evidence and historical `implementation()` calls establish
six implementation intervals:

| Start block | Start date UTC | End block | Implementation |
| ---: | --- | ---: | --- |
| 11,473,216 | 2020-12-17 | 13,500,146 | `0x20dc62d5904633cc6a5e34bec87a048e80c92e97` |
| 13,500,147 | 2021-10-27 | 14,860,267 | `0xc7b5af82b05eb3b64f12241b04b2cf14469e39f7` |
| 14,860,268 | 2022-05-28 | 17,266,003 | `0x47ebab13b806773ec2a2d16873e2df770d130b50` |
| 17,266,004 | 2023-05-15 | 24,083,112 | `0x17144556fd3424edc8fc8a4c940b2d04936d17eb` |
| 24,083,113 | 2025-12-24 | 25,603,296 | `0x6ca84080381e43938476814be61b779a8bb6a600` |
| 25,603,297 | 2026-07-24 | 26,421,585 | `0x028271e30a695c0527a0c50ca30603fed004cdb0` |

The stETH proxy shell bytecode remained unchanged, but the delegated
implementation did not. Historical wstETH conversion-rate acquisition must
therefore execute `stEthPerToken()` at the contemporaneous block against an
archive node. It must not apply the current stETH implementation or current
state retroactively.

### Direct contracts

The following direct contracts had identical runtime bytecode hashes at their
deployment block and the audit-end block:

- wstETH;
- Curve legacy stETH/ETH pool; and
- Curve concentrated stETH/WETH pool.

Their registered address-level runtime code did not change over the audited
period. The complete Curve swap dataset also used one fixed
`TokenExchange(address,int128,uint256,int128,uint256)` topic.

## Conclusion

The historical event semantics gate passes for the acquired Curve swap and
Lido withdrawal datasets:

- all selected withdrawal events were emitted under one verified
  WithdrawalQueueERC721 implementation;
- both Curve pool contracts retained the same runtime bytecode; and
- the proxy and direct-contract classifications are now explicit and
  reproducible.

The audit also identifies an important point-in-time requirement: stETH had
six implementations. Daily wstETH conversion rates and any stETH-dependent
state must be queried at historical blocks. This is a data-model constraint,
not evidence of strategy performance.

## Remaining data gates

1. Acquire daily point-in-time wstETH conversion rates and executable Curve
   quotes, with explicit UTC observation rules and historical block mapping.
2. Validate state-call behavior immediately before and after all five stETH
   implementation boundaries.
3. Design a bounded-cost canonicalization path that avoids one receipt RPC per
   event where receipt-level gas metadata is not required.
4. Reconcile daily on-chain coverage with CEX mark, perpetual, and funding
   datasets before preregistering a strategy experiment.
