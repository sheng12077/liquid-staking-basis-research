from datetime import UTC, datetime, timedelta

from liquid_staking_basis.cex_audit import _missing_ranges


def test_missing_ranges_groups_consecutive_hours() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    missing = [start, start + timedelta(hours=1), start + timedelta(hours=4)]
    assert _missing_ranges(missing, timedelta(hours=1)) == [
        {"start": "2024-01-01T00:00:00Z", "end": "2024-01-01T01:00:00Z", "count": 2},
        {"start": "2024-01-01T04:00:00Z", "end": "2024-01-01T04:00:00Z", "count": 1},
    ]
