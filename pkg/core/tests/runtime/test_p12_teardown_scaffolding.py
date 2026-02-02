"""
P12-CORE-001/002 INV-TEARDOWN-STABLE-STATE-001: Contract tests for deferred teardown scaffolding.

Verifies _STABLE_STATES, _TRANSIENT_STATES, _TEARDOWN_GRACE_TIMEOUT and instance fields
_teardown_pending, _teardown_deadline, _teardown_reason exist and are initialized/cleared correctly.
P12-CORE-002: _request_teardown() stable vs transient, idempotent.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from retrovue.runtime.clock import ControllableMasterClock
from retrovue.runtime.channel_manager import (
    BoundaryState,
    ChannelManager,
    MockAlternatingScheduleService,
    Phase8ProgramDirector,
    _STABLE_STATES,
    _TEARDOWN_GRACE_TIMEOUT,
    _TRANSIENT_STATES,
)


def test_stable_and_transient_states_defined() -> None:
    """P12-CORE-001: _STABLE_STATES and _TRANSIENT_STATES are defined and disjoint."""
    assert _STABLE_STATES == {
        BoundaryState.NONE,
        BoundaryState.LIVE,
        BoundaryState.FAILED_TERMINAL,
    }
    assert _TRANSIENT_STATES == {
        BoundaryState.PLANNED,
        BoundaryState.PRELOAD_ISSUED,
        BoundaryState.SWITCH_SCHEDULED,
        BoundaryState.SWITCH_ISSUED,
    }
    assert _STABLE_STATES.isdisjoint(_TRANSIENT_STATES)


def test_teardown_grace_timeout_defined() -> None:
    """P12-CORE-001: _TEARDOWN_GRACE_TIMEOUT is 10 seconds."""
    assert _TEARDOWN_GRACE_TIMEOUT == timedelta(seconds=10)


def test_teardown_fields_initialized(tmp_path: Path) -> None:
    """P12-CORE-001: _teardown_pending, _teardown_deadline, _teardown_reason are initialized."""
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
    ok, _ = schedule.load_schedule(channel_id)
    assert ok
    manager = ChannelManager(
        channel_id=channel_id,
        clock=clock,
        schedule_service=schedule,
        program_director=Phase8ProgramDirector(),
    )
    assert manager._teardown_pending is False
    assert manager._teardown_deadline is None
    assert manager._teardown_reason is None


def test_stop_channel_clears_teardown_fields(tmp_path: Path) -> None:
    """P12-CORE-001: stop_channel() resets _teardown_pending, _teardown_deadline, _teardown_reason."""
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
    ok, _ = schedule.load_schedule(channel_id)
    assert ok
    manager = ChannelManager(
        channel_id=channel_id,
        clock=clock,
        schedule_service=schedule,
        program_director=Phase8ProgramDirector(),
    )
    manager._teardown_pending = True
    manager._teardown_deadline = datetime.now(timezone.utc)
    manager._teardown_reason = "test_defer"
    manager.stop_channel()
    assert manager._teardown_pending is False
    assert manager._teardown_deadline is None
    assert manager._teardown_reason is None


def _create_manager_in_state(boundary_state: BoundaryState, tmp_path: Path) -> tuple[ChannelManager, ControllableMasterClock]:
    """Create a minimal ChannelManager with _boundary_state set; return (manager, clock)."""
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
    ok, _ = schedule.load_schedule(channel_id)
    assert ok
    manager = ChannelManager(
        channel_id=channel_id,
        clock=clock,
        schedule_service=schedule,
        program_director=Phase8ProgramDirector(),
    )
    manager._boundary_state = boundary_state
    return manager, clock


@pytest.mark.parametrize("stable_state", list(_STABLE_STATES))
def test_request_teardown_stable_returns_true(tmp_path: Path, stable_state: BoundaryState) -> None:
    """P12-CORE-002: _request_teardown() in stable state returns True, caller may proceed."""
    manager, _ = _create_manager_in_state(stable_state, tmp_path)
    result = manager._request_teardown("viewer_inactive")
    assert result is True
    assert manager._teardown_pending is False
    assert manager._teardown_deadline is None


@pytest.mark.parametrize("transient_state", list(_TRANSIENT_STATES))
def test_request_teardown_transient_defers(tmp_path: Path, transient_state: BoundaryState) -> None:
    """P12-CORE-002: _request_teardown() in transient state returns False and sets pending/deadline."""
    manager, clock = _create_manager_in_state(transient_state, tmp_path)
    now_before = clock.now_utc()
    result = manager._request_teardown("viewer_inactive")
    assert result is False
    assert manager._teardown_pending is True
    assert manager._teardown_deadline is not None
    assert manager._teardown_reason == "viewer_inactive"
    # Deadline = now + 10s (testable clock)
    expected_deadline = now_before + _TEARDOWN_GRACE_TIMEOUT
    assert manager._teardown_deadline == expected_deadline


def test_request_teardown_idempotent(tmp_path: Path) -> None:
    """P12-CORE-002: Second _request_teardown() while pending is no-op; deadline not extended."""
    manager, clock = _create_manager_in_state(BoundaryState.PLANNED, tmp_path)
    result1 = manager._request_teardown("reason1")
    assert result1 is False
    deadline_first = manager._teardown_deadline
    assert deadline_first is not None
    clock.advance(2.0)  # 2 seconds later
    result2 = manager._request_teardown("reason2")
    assert result2 is False
    # Deadline unchanged (idempotent; did not extend)
    assert manager._teardown_deadline == deadline_first
    assert manager._teardown_reason == "reason1"  # reason from first call
