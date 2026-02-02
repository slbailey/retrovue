"""
P11F-008 INV-SWITCH-ISSUANCE-ONESHOT-001: Contract tests for one-shot issuance guard.

Verifies duplicate into SWITCH_ISSUED/LIVE is suppressed, duplicate into FAILED_TERMINAL
is FATAL, and tick cannot re-trigger issuance.
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
    SwitchState,
)
from retrovue.runtime.producer.base import Producer, ProducerMode, ProducerStatus


def _create_manager(tmp_path: Path) -> ChannelManager:
    """Create a minimal ChannelManager for one-shot tests."""
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
    return ChannelManager(
        channel_id=channel_id,
        clock=clock,
        schedule_service=schedule,
        program_director=Phase8ProgramDirector(),
    )


def test_duplicate_into_switch_issued_suppressed(tmp_path: Any) -> None:
    """INV-SWITCH-ISSUANCE-ONESHOT-001: Duplicate into SWITCH_ISSUED is benign."""
    manager = _create_manager(tmp_path)
    boundary_time = datetime.now(timezone.utc) + timedelta(seconds=10)

    manager._boundary_state = BoundaryState.SWITCH_SCHEDULED
    assert manager._guard_switch_issuance(boundary_time) is True

    manager._boundary_state = BoundaryState.SWITCH_ISSUED
    assert manager._guard_switch_issuance(boundary_time) is False
    assert manager._pending_fatal is None


def test_duplicate_into_live_suppressed(tmp_path: Any) -> None:
    """INV-SWITCH-ISSUANCE-ONESHOT-001: Duplicate into LIVE is benign."""
    manager = _create_manager(tmp_path)
    boundary_time = datetime.now(timezone.utc) + timedelta(seconds=10)

    manager._boundary_state = BoundaryState.LIVE
    assert manager._guard_switch_issuance(boundary_time) is False
    assert manager._pending_fatal is None


def test_duplicate_into_terminal_is_fatal(tmp_path: Any) -> None:
    """INV-SWITCH-ISSUANCE-ONESHOT-001: Duplicate into FAILED_TERMINAL is control-flow bug."""
    manager = _create_manager(tmp_path)
    boundary_time = datetime.now(timezone.utc) + timedelta(seconds=10)

    manager._boundary_state = BoundaryState.FAILED_TERMINAL
    assert manager._guard_switch_issuance(boundary_time) is False
    assert manager._pending_fatal is not None
    assert "FAILED_TERMINAL" in str(manager._pending_fatal) or "failed boundary" in str(
        manager._pending_fatal
    ).lower()


@pytest.mark.parametrize(
    "terminal_state",
    [
        BoundaryState.SWITCH_ISSUED,
        BoundaryState.LIVE,
        BoundaryState.FAILED_TERMINAL,
    ],
)
def test_tick_skips_processed_boundary(tmp_path: Any, terminal_state: BoundaryState) -> None:
    """INV-SWITCH-ISSUANCE-ONESHOT-001: tick() does not re-trigger issuance."""
    manager = _create_manager(tmp_path)
    manager._boundary_state = terminal_state
    manager._channel_state = "RUNNING"
    manager._segment_end_time_utc = datetime.now(timezone.utc) + timedelta(seconds=10)

    issuance_called = False
    original = manager._on_switch_issue_deadline

    def mock_issuance(boundary_time: datetime) -> None:
        nonlocal issuance_called
        issuance_called = True
        original(boundary_time)

    manager._on_switch_issue_deadline = mock_issuance
    manager.tick()
    assert issuance_called is False


def test_callback_invokes_once(tmp_path: Any) -> None:
    """INV-SWITCH-ISSUANCE-ONESHOT-001: Full flow issues exactly once."""
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

    switch_call_count = 0

    class CountingProducer(Producer):
        def __init__(self) -> None:
            super().__init__(channel_id, ProducerMode.NORMAL, {})
            self._endpoint = "fake://count"

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
            nonlocal switch_call_count
            switch_call_count += 1
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
            return "counting"

    manager = ChannelManager(
        channel_id=channel_id,
        clock=clock,
        schedule_service=schedule,
        program_director=Phase8ProgramDirector(),
    )
    manager.active_producer = CountingProducer()
    boundary_time = datetime.now(timezone.utc) + timedelta(seconds=10)
    if boundary_time.tzinfo is None:
        boundary_time = boundary_time.replace(tzinfo=timezone.utc)
    manager._segment_end_time_utc = boundary_time
    manager._plan_boundary_ms = int(boundary_time.timestamp() * 1000)
    manager._switch_state = SwitchState.PREVIEW_LOADED

    manager._boundary_state = BoundaryState.SWITCH_SCHEDULED
    manager._on_switch_issue_deadline(boundary_time)
    assert switch_call_count == 1

    manager._on_switch_issue_deadline(boundary_time)
    assert switch_call_count == 1
