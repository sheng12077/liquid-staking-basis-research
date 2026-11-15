# Canonical Ethereum Event Schema

The canonical datasets are strategy-neutral reconstructions of selected
Ethereum events. Raw JSON-RPC responses remain under `data/raw/ethereum_rpc`;
canonical Parquet files are written under `data/canonical/ethereum`.

## Common provenance fields

Every decoded event includes block number and timestamp, block and transaction
hashes, transaction and log indices, contract address, topic 0, receipt status,
transaction gas used, effective gas price, total transaction fee, and block
base fee.

Transaction gas is the gas used by the entire transaction. It must not be
interpreted as the incremental gas attributable to a single event or strategy
action.

## Curve swaps

`curve_swaps.parquet` decodes `TokenExchange` for the registered ETH/stETH and
WETH/stETH pools. It stores the buyer, pool coin indices, mapped asset names,
and sold/bought quantities. Exact uint256 amounts are retained as decimal
strings in `*_raw`; floating-point token amounts are convenience fields only.

## Lido withdrawals

`withdrawal_events.parquet` decodes `WithdrawalRequested`,
`WithdrawalsFinalized`, and `WithdrawalClaimed`. Exact token, share, and ETH
amounts are retained as decimal strings alongside convenience token-unit
fields.

## Unsupported events

Events outside the registered schemas are not discarded. They are retained in
`unsupported_events.parquet` with their complete topics and data payload so
coverage gaps remain visible and can be decoded later.

The unique event key is `(transaction_hash, log_index)`.

