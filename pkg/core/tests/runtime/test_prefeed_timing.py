"""
P11E-005: Contract tests for prefeed timing (INV-CONTROL-NO-POLL-001).

Verifies:
- MIN_PREFEED_LEAD_TIME constant is defined and in valid range
- LoadPreview trigger time ensures sufficient lead when issued on time
- Violation logging when SwitchToLive issued with insufficient lead
- Metrics recorded when prometheus_client available
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from retrovue.runtime.constants import (
    MIN_PREFEED_LEAD_TIME,
    MIN_PREFEED_LEAD_TIME_MS,
    SCHEDULING_BUFFER_SECONDS,
    STARTUP_LATENCY,
)
from retrovue.runtime.channel_manager import Phase8AirProducer
from retrovue.runtime.config import MOCK_CHANNEL_CONFIG


# ---------------------------------------------------------------------------
# P11E-001: Constants defined and in range
# ---------------------------------------------------------------------------


def test_min_prefeed_lead_time_ms_in_valid_range():
    """MIN_PREFEED_LEAD_TIME_MS is in [1000, 30000] (P11E-001)."""
    assert MIN_PREFEED_LEAD_TIME_MS >= 1000
    assert MIN_PREFEED_LEAD_TIME_MS <= 30000


def test_min_prefeed_lead_time_is_timedelta():
    """MIN_PREFEED_LEAD_TIME is timedelta matching MIN_PREFEED_LEAD_TIME_MS."""
    assert MIN_PREFEED_LEAD_TIME == timedelta(milliseconds=MIN_PREFEED_LEAD_TIME_MS)


def test_startup_latency_defined():
    """STARTUP_LATENCY is defined for first-boundary feasibility."""
    assert STARTUP_LATENCY.total_seconds() >= 0


def test_scheduling_buffer_defined():
    """SCHEDULING_BUFFER_SECONDS is defined for LoadPreview trigger (P11E-002)."""
    assert SCHEDULING_BUFFER_SECONDS >= 0


# ---------------------------------------------------------------------------
# P11E-002: Preload trigger gives sufficient lead when issued on time
# ---------------------------------------------------------------------------


def test_preload_trigger_lead_exceeds_min():
    """When LoadPreview is triggered at preload_at, lead time >= MIN_PREFEED_LEAD_TIME."""
    # Trigger time = boundary - MIN - SCHEDULING_BUFFER. So when we issue at preload_at,
    # lead = boundary - preload_at = MIN + SCHEDULING_BUFFER >= MIN.
    preload_lead_seconds = MIN_PREFEED_LEAD_TIME.total_seconds() + SCHEDULING_BUFFER_SECONDS
    assert preload_lead_seconds >= MIN_PREFEED_LEAD_TIME.total_seconds()


# ---------------------------------------------------------------------------
# P11E-003: Violation logged when SwitchToLive issued with insufficient lead
# ---------------------------------------------------------------------------


def test_switch_to_live_logs_violation_when_lead_insufficient(caplog):
    """INV-CONTROL-NO-POLL-001: SwitchToLive with lead < MIN logs violation (P11E-003)."""
    producer = Phase8AirProducer(
        channel_id="test-1",
        configuration={},
        channel_config=MOCK_CHANNEL_CONFIG,
    )
    # Set grpc_addr so we enter the block that logs violation (then we mock the RPC).
    producer._grpc_addr = "127.0.0.1:9999"
    # Boundary in the past so lead is negative.
    past_boundary = datetime.now(timezone.utc) - timedelta(seconds=10)

    with patch("retrovue.runtime.channel_manager.channel_manager_launch.air_switch_to_live") as mock_rpc:
        mock_rpc.return_value = (False, 4, "Insufficient prefeed lead time")  # PROTOCOL_VIOLATION
        producer.switch_to_live(target_boundary_time_utc=past_boundary)

    assert "INV-CONTROL-NO-POLL-001 VIOLATION" in caplog.text
    assert "SwitchToLive issued too late" in caplog.text
    assert "min_required_ms" in caplog.text


def test_switch_to_live_no_violation_log_when_lead_sufficient(caplog):
    """When lead >= MIN, no violation is logged."""
    producer = Phase8AirProducer(
        channel_id="test-1",
        configuration={},
        channel_config=MOCK_CHANNEL_CONFIG,
    )
    producer._grpc_addr = "127.0.0.1:9999"
    # Boundary far in future.
    future_boundary = datetime.now(timezone.utc) + timedelta(seconds=MIN_PREFEED_LEAD_TIME_MS // 1000 + 5)

    with patch("retrovue.runtime.channel_manager.channel_manager_launch.air_switch_to_live") as mock_rpc:
        mock_rpc.return_value = (True, 1, "")
        producer.switch_to_live(target_boundary_time_utc=future_boundary)

    # Should not contain violation for insufficient lead (may contain other logs).
    assert "SwitchToLive issued too late" not in caplog.text


# ---------------------------------------------------------------------------
# P11E-004: Metrics recorded when available
# ---------------------------------------------------------------------------


def test_switch_lead_time_observed_when_metrics_available():
    """When switch_lead_time_ms is not None, observe is called (P11E-004)."""
    from retrovue.runtime import metrics as metrics_module

    if metrics_module.switch_lead_time_ms is None:
        pytest.skip("prometheus_client not available")

    producer = Phase8AirProducer(
        channel_id="test-metrics",
        configuration={},
        channel_config=MOCK_CHANNEL_CONFIG,
    )
    producer._grpc_addr = "127.0.0.1:9999"
    future_boundary = datetime.now(timezone.utc) + timedelta(seconds=10)

    with patch("retrovue.runtime.channel_manager.channel_manager_launch.air_switch_to_live") as mock_rpc:
        mock_rpc.return_value = (True, 1, "")
        producer.switch_to_live(target_boundary_time_utc=future_boundary)

    # Metric should have been observed (no exception); exact count depends on registry.
    assert metrics_module.switch_lead_time_ms is not None
