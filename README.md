# Liquid-Staking Basis Research

Reproducible research infrastructure for ETH liquid-staking basis and hedged
carry. The current work is a data-feasibility pilot only; it does not calculate
strategy returns or constitute a registered performance experiment.

## Local configuration

Copy `.env.example` to `.env` and insert the private Ethereum RPC endpoint.
The endpoint is read locally and is never written to manifests or command
output.

```bash
cp .env.example .env
```

## Pilot commands

```bash
lsb-data rpc-check
lsb-data estimate --start-block 12000000 --end-block 12010000
lsb-data fetch-logs \
  --dataset-id example_contract_logs \
  --address 0x0000000000000000000000000000000000000000 \
  --start-block 12000000 \
  --end-block 12000009
lsb-data audit --dataset-id example_contract_logs
```

`fetch-logs` defaults to the Free-plan limit of ten blocks per request. Each
response is stored byte-for-byte, named with its SHA-256 prefix, and accompanied
by a secret-free immutable manifest. Existing chunks provide resumability.

