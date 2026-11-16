from datetime import UTC, datetime, timedelta

import polars as pl

from liquid_staking_basis.experiment_002 import monitoring_stats


def test_monitoring_records_warnings_without_actions() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    frame = pl.DataFrame(
        {
            "timestamp": [start + timedelta(hours=index) for index in range(5)],
            "short_quantity_eth": [1.0] * 5,
            "operational_buffer": [0.40, 0.24, 0.20, 0.30, 0.09],
            "risk_operational_buffer": [0.39, 0.23, 0.19, 0.29, 0.08],
        }
    )
    result = monitoring_stats(frame, None, 0.25, 0.10)
    assert result["warning_hour_count"] == 3
    assert result["critical_hour_count"] == 1
    assert result["longest_consecutive_warning_hours"] == 2
    assert result["monitoring_action"] == "observe_only_no_position_change"


def test_monitoring_stops_at_breach_and_reports_lead_time() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    frame = pl.DataFrame(
        {
            "timestamp": [start + timedelta(hours=index) for index in range(4)],
            "short_quantity_eth": [1.0] * 4,
            "operational_buffer": [0.24, 0.20, -0.01, -0.10],
            "risk_operational_buffer": [0.24, 0.20, -0.01, -0.10],
        }
    )
    result = monitoring_stats(frame, (start + timedelta(hours=2)).isoformat(), 0.25, 0.10)
    assert result["warning_hour_count"] == 3
    assert result["warning_to_breach_lead_hours"] == 2.0
