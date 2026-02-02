"""
P11F-009 INV-SWITCH-ISSUANCE-TERMINAL-001: Contract tests for terminal exception handling.

Verifies exceptions transition to FAILED_TERMINAL, no retry/re-arm after exception,
and tick cannot retry failed boundary.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from retrovue.runtime.clock import ControllableMasterClock
from retrovue.runtime.channel_manager import (
    BoundaryState,
    ChannelManager,
    MockAlternatingScheduleService,
    Phase8ProgramDirector,
    SchedulingError,
    SwitchState,
)
from retrovue.runtime.producer.base import Producer, ProducerMode, ProducerStatus


def _create_manager(tmp_path: Path) -> ChannelManager:
    """Create a minimal ChannelManager with a fake producer for terminal tests."""
    sample = str(tmp_path / "Sample.mp4")
    (tmp_path / "Sample.mp4").write_bytes(b"")
    clock = ControllableMasterClock()
    schedule = MockAlternatingScheduleService(
        clock=clock,
        asset_a_path=sample,
        asset_b_path=sample,
        segment_seconds=10.0,
    )
    channel_id = MockAlternatingScheduleService.MOCK_AB_CHANNEL_ID
    ok, err = schedule.load_schedule(channel_id)
    assert ok, err
    manager = ChannelManager(
        channel_id=channel_id,
        clock=clock,
        schedule_service=schedule,
        program_director=Phase8ProgramDirector(),
    )
    return manager


class FakeProducerWithSwitch(Producer):
    """Producer that can have switch_to_live overridden for tests."""

    def __init__(self, channel_id: str) -> None:
        super().__init__(channel_id, ProducerMode.NORMAL, {})
        self._endpoint = "fake://term"

    def start(
        self,
        playout_plan: list[dict[str, Any]],
        start_at_station_time: datetime,
    ) -> bool:
        self.status = ProducerStatus.RUNNING
        return True

    def stop(self) -> bool:
        self.status = ProducerStatus.STOPPED
        return True

    def switch_to_live(self, target_boundary_time_utc: datetime | None = None) -> bool:
        return True

    def play_content(self, content: Any) -> bool:
        return True

    def on_paced_tick(self, t_now: float, dt: float) -> None:
        pass

    def get_stream_endpoint(self) -> str | None:
        return self._endpoint

    def health(self) -> str:
        return "running"

    def get_producer_id(self) -> str:
        return "fake_term"


def test_rpc_exception_is_terminal(tmp_path: Any) -> None:
    """INV-SWITCH-ISSUANCE-TERMINAL-001: RPC exception forces terminal state."""
    manager = _create_manager(tmp_path)
    channel_id = MockAlternatingScheduleService.MOCK_AB_CHANNEL_ID
    producer = FakeProducerWithSwitch(channel_id)

    def failing_switch(*args: Any, **kwargs: Any) -> bool:
        raise ConnectionError("AIR unavailable")

    producer.switch_to_live = failing_switch  # type: ignore[assignment]
    manager.active_producer = producer
    manager._channel_state = "RUNNING"
    boundary_time = datetime.now(timezone.utc) + timedelta(seconds=10)
    if boundary_time.tzinfo is None:
        boundary_time = boundary_time.replace(tzinfo=timezone.utc)
    manager._segment_end_time_utc = boundary_time
    manager._plan_boundary_ms = int(boundary_time.timestamp() * 1000)
    manager._switch_state = SwitchState.PREVIEW_LOADED
    manager._boundary_state = BoundaryState.SWITCH_SCHEDULED

    manager._on_switch_issue_deadline(boundary_time)

    assert manager._boundary_state == BoundaryState.FAILED_TERMINAL
    assert manager._pending_fatal is not None
    assert "AIR unavailable" in str(manager._pending_fatal)


def test_no_rearm_after_exception(tmp_path: Any) -> None:
    """INV-SWITCH-ISSUANCE-TERMINAL-001: Timer is NOT re-registered on failure."""
    manager = _create_manager(tmp_path)
    channel_id = MockAlternatingScheduleService.MOCK_AB_CHANNEL_ID
    producer = FakeProducerWithSwitch(channel_id)

    def failing_switch(*args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("Timeout")

    producer.switch_to_live = failing_switch  # type: ignore[assignment]
    manager.active_producer = producer
    manager._channel_state = "RUNNING"
    boundary_time = datetime.now(timezone.utc) + timedelta(seconds=10)
    if boundary_time.tzinfo is None:
        boundary_time = boundary_time.replace(tzinfo=timezone.utc)
    manager._segment_end_time_utc = boundary_time
    manager._plan_boundary_ms = int(boundary_time.timestamp() * 1000)
    manager._switch_state = SwitchState.PREVIEW_LOADED
    manager._boundary_state = BoundaryState.SWITCH_SCHEDULED
    manager._switch_handle = None

    manager._on_switch_issue_deadline(boundary_time)

    assert manager._switch_handle is None
    assert manager._boundary_state == BoundaryState.FAILED_TERMINAL


def test_tick_cannot_retry_terminal(tmp_path: Any) -> None:
    """INV-SWITCH-ISSUANCE-TERMINAL-001: tick() cannot retry failed boundary."""
    manager = _create_manager(tmp_path)
    manager._boundary_state = BoundaryState.FAILED_TERMINAL
    manager._pending_fatal = SchedulingError("Previous failure")

    switch_attempted = False
    original = manager._schedule_switch_issuance

    def mock_schedule(boundary_time: datetime) -> None:
        nonlocal switch_attempted
        switch_attempted = True
        original(boundary_time)

    manager._schedule_switch_issuance = mock_schedule  # type: ignore[assignment]

    for _ in range(5):
        try:
            manager.tick()
        except SchedulingError:
            manager._pending_fatal = None

    assert switch_attempted is False
    assert manager._boundary_state == BoundaryState.FAILED_TERMINAL


@pytest.mark.parametrize(
    "exception",
    [
        ConnectionError("Connection refused"),
        TimeoutError("RPC timeout"),
        ValueError("Invalid boundary"),
        RuntimeError("Unknown error"),
    ],
)
def test_all_exceptions_are_terminal(tmp_path: Any, exception: Exception) -> None:
    """INV-SWITCH-ISSUANCE-TERMINAL-001: All exception types are terminal."""
    manager = _create_manager(tmp_path)
    channel_id = MockAlternatingScheduleService.MOCK_AB_CHANNEL_ID
    producer = FakeProducerWithSwitch(channel_id)

    def failing_switch(*args: Any, **kwargs: Any) -> bool:
        raise exception

    producer.switch_to_live = failing_switch  # type: ignore[assignment]
    manager.active_producer = producer
    manager._channel_state = "RUNNING"
    boundary_time = datetime.now(timezone.utc) + timedelta(seconds=10)
    if boundary_time.tzinfo is None:
        boundary_time = boundary_time.replace(tzinfo=timezone.utc)
    manager._segment_end_time_utc = boundary_time
    manager._plan_boundary_ms = int(boundary_time.timestamp() * 1000)
    manager._switch_state = SwitchState.PREVIEW_LOADED
    manager._boundary_state = BoundaryState.SWITCH_SCHEDULED

    manager._on_switch_issue_deadline(boundary_time)

    assert manager._boundary_state == BoundaryState.FAILED_TERMINAL


def test_pending_fatal_has_diagnostics(tmp_path: Any) -> None:
    """INV-SWITCH-ISSUANCE-TERMINAL-001: pending_fatal includes boundary and error."""
    manager = _create_manager(tmp_path)
    channel_id = MockAlternatingScheduleService.MOCK_AB_CHANNEL_ID
    producer = FakeProducerWithSwitch(channel_id)

    def failing_switch(*args: Any, **kwargs: Any) -> bool:
        raise ConnectionError("specific_error_message")

    producer.switch_to_live = failing_switch  # type: ignore[assignment]
    manager.active_producer = producer
    manager._channel_state = "RUNNING"
    boundary_time = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    manager._segment_end_time_utc = boundary_time
    manager._plan_boundary_ms = int(boundary_time.timestamp() * 1000)
    manager._switch_state = SwitchState.PREVIEW_LOADED
    manager._boundary_state = BoundaryState.SWITCH_SCHEDULED

    manager._on_switch_issue_deadline(boundary_time)

    error_str = str(manager._pending_fatal)
    assert "2025-01-15" in error_str or "boundary" in error_str.lower()
    assert "specific_error_message" in error_str


def test_exception_not_swallowed(tmp_path: Any) -> None:
    """INV-SWITCH-ISSUANCE-TERMINAL-001: Exceptions are not silently swallowed."""
    manager = _create_manager(tmp_path)
    channel_id = MockAlternatingScheduleService.MOCK_AB_CHANNEL_ID
    producer = FakeProducerWithSwitch(channel_id)

    def failing_switch(*args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("Must not be swallowed")

    producer.switch_to_live = failing_switch  # type: ignore[assignment]
    manager.active_producer = producer
    manager._channel_state = "RUNNING"
    boundary_time = datetime.now(timezone.utc) + timedelta(seconds=10)
    if boundary_time.tzinfo is None:
        boundary_time = boundary_time.replace(tzinfo=timezone.utc)
    manager._segment_end_time_utc = boundary_time
    manager._plan_boundary_ms = int(boundary_time.timestamp() * 1000)
    manager._switch_state = SwitchState.PREVIEW_LOADED
    manager._boundary_state = BoundaryState.SWITCH_SCHEDULED

    assert manager._pending_fatal is None

    manager._on_switch_issue_deadline(boundary_time)

    assert manager._pending_fatal is not None
    assert manager._boundary_state != BoundaryState.SWITCH_SCHEDULED
    assert manager._boundary_state == BoundaryState.FAILED_TERMINAL
