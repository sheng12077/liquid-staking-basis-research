from liquid_staking_basis.cost import estimate_cost


def test_estimate_cost_uses_inclusive_block_range() -> None:
    result = estimate_cost(100, 119, chunk_size=10, snapshot_calls=2)

    assert result.block_count == 20
    assert result.chunk_count == 2
    assert result.log_request_count == 2
    assert result.total_compute_units == 172


def test_estimate_cost_multiplies_independent_filters() -> None:
    result = estimate_cost(100, 109, chunk_size=10, log_filters=3)

    assert result.log_request_count == 3
    assert result.total_compute_units == 180

