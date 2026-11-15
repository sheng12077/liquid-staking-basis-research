from __future__ import annotations

from dataclasses import asdict, dataclass

ETH_GET_LOGS_CU = 60
ETH_CALL_CU = 26


@dataclass(frozen=True)
class CostEstimate:
    block_count: int
    chunk_count: int
    log_request_count: int
    snapshot_call_count: int
    total_compute_units: int
    estimated_usd: float

    def to_dict(self) -> dict[str, int | float]:
        return asdict(self)


def estimate_cost(
    start_block: int,
    end_block: int,
    chunk_size: int,
    log_filters: int = 1,
    snapshot_calls: int = 0,
    usd_per_million_cu: float = 0.525,
) -> CostEstimate:
    if start_block < 0 or end_block < start_block:
        raise ValueError("block range must be non-negative and inclusive")
    if chunk_size <= 0 or log_filters <= 0 or snapshot_calls < 0:
        raise ValueError("chunk_size and log_filters must be positive")
    block_count = end_block - start_block + 1
    chunk_count = (block_count + chunk_size - 1) // chunk_size
    log_request_count = chunk_count * log_filters
    total_cu = log_request_count * ETH_GET_LOGS_CU + snapshot_calls * ETH_CALL_CU
    return CostEstimate(
        block_count=block_count,
        chunk_count=chunk_count,
        log_request_count=log_request_count,
        snapshot_call_count=snapshot_calls,
        total_compute_units=total_cu,
        estimated_usd=round(total_cu / 1_000_000 * usd_per_million_cu, 6),
    )

