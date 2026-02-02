"""
P12-TEST-001 through P12-TEST-005: Contract tests for Phase 12 teardown semantics.

INV-TEARDOWN-STABLE-STATE-001: Teardown deferred until boundary state stable.
INV-TEARDOWN-GRACE-TIMEOUT-001: Grace timeout forces FAILED_TERMINAL when elapsed.
INV-TEARDOWN-NO-NEW-WORK-001: No new boundary work when teardown pending.
INV-VIEWER-COUNT-ADVISORY-001: Viewer count advisory; disconnect triggers request, not force.
"""

from __future__ import annotations

from datetime import timedelta, timezone
from pathlib import Path

import pytest

from retrovue.runtime.clock import ControllableMasterClock
from retrovue.runtime.channel_manager import (
    BoundaryState,
    ChannelManager,
    MockAlternatingScheduleService,
    Phase8ProgramDirector,
    _TEARDOWN_GRACE_TIMEOUT,
)


def _create_manager_in_state(
    boundary_state: BoundaryState,
    tmp_path: Path,
    *,
    teardown_pending: bool = False,
    deadline_in_past: bool = False,
) -> tuple[ChannelManager, ControllableMasterClock]:
    """Create a minimal ChannelManager with _boundary_state set; optional teardown state."""
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
    if teardown_pending:
        manager._teardown_pending = True
        if deadline_in_past:
            now = clock.now_utc()
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            manager._teardown_deadline = now - timedelta(seconds=1)
        else:
            manager._request_teardown("viewer_inactive")  # sets deadline = now + 10s
        manager._teardown_reason = "viewer_inactive"
    return manager, clock


# ---------------------------------------------------------------------------
# P12-TEST-001: Teardown blocked in transient states, allowed in stable states
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "transient_state",
    [
        BoundaryState.SWITCH_ISSUED,
        BoundaryState.SWITCH_SCHEDULED,
        BoundaryState.PRELOAD_ISSUED,
        BoundaryState.PLANNED,
    ],
)
def test_p12_teardown_blocked_in_transient_state(
    tmp_path: Path, transient_state: BoundaryState
) -> None:
    """P12-TEST-001: _request_teardown() in transient state returns False, sets pending and deadline."""
    manager, clock = _create_manager_in_state(transient_state, tmp_path)
    now_before = clock.now_utc()
    result = manager._request_teardown("viewer_inactive")
    assert result is False
    assert manager._teardown_pending is True
    assert manager._teardown_deadline is not None
    assert manager._teardown_deadline == now_before + _TEARDOWN_GRACE_TIMEOUT


def test_p12_teardown_allowed_in_live(tmp_path: Path) -> None:
    """P12-TEST-001: _request_teardown() in LIVE returns True, pending unchanged."""
    manager, _ = _create_manager_in_state(BoundaryState.LIVE, tmp_path)
    result = manager._request_teardown("viewer_inactive")
    assert result is True
    assert manager._teardown_pending is False
    assert manager._teardown_deadline is None


def test_p12_teardown_allowed_in_none(tmp_path: Path) -> None:
    """P12-TEST-001: _request_teardown() in NONE returns True."""
    manager, _ = _create_manager_in_state(BoundaryState.NONE, tmp_path)
    result = manager._request_teardown("viewer_inactive")
    assert result is True


def test_p12_teardown_allowed_in_failed_terminal(tmp_path: Path) -> None:
    """P12-TEST-001: _request_teardown() in FAILED_TERMINAL returns True."""
    manager, _ = _create_manager_in_state(BoundaryState.FAILED_TERMINAL, tmp_path)
    result = manager._request_teardown("viewer_inactive")
    assert result is True


# ---------------------------------------------------------------------------
# P12-TEST-002: Deferred teardown executes on stable state entry
# ---------------------------------------------------------------------------


def test_p12_deferred_teardown_executes_on_live_entry(tmp_path: Path) -> None:
    """P12-TEST-002: Transition to LIVE with teardown pending fires signal and clears pending."""
    manager, _ = _create_manager_in_state(BoundaryState.SWITCH_ISSUED, tmp_path)
    manager._teardown_pending = True
    manager._teardown_deadline = manager.clock.now_utc() + _TEARDOWN_GRACE_TIMEOUT
    manager._teardown_reason = "viewer_inactive"
    manager._transition_boundary_state(BoundaryState.LIVE)
    assert manager._boundary_state == BoundaryState.LIVE
    assert manager._teardown_pending is False
    assert manager._teardown_deadline is None
    assert manager._teardown_reason is None
    assert manager.deferred_teardown_triggered() is True


def test_p12_deferred_teardown_executes_on_failed_terminal_entry(tmp_path: Path) -> None:
    """P12-TEST-002: Transition to FAILED_TERMINAL with teardown pending fires signal."""
    manager, _ = _create_manager_in_state(BoundaryState.SWITCH_ISSUED, tmp_path)
    manager._teardown_pending = True
    manager._teardown_deadline = manager.clock.now_utc() + _TEARDOWN_GRACE_TIMEOUT
    manager._teardown_reason = "viewer_inactive"
    manager._transition_boundary_state(BoundaryState.FAILED_TERMINAL)
    assert manager._boundary_state == BoundaryState.FAILED_TERMINAL
    assert manager._teardown_pending is False
    assert manager.deferred_teardown_triggered() is True


def test_p12_deferred_teardown_executes_on_none_entry(tmp_path: Path) -> None:
    """P12-TEST-002: Transition LIVE -> NONE with teardown pending fires signal."""
    manager, _ = _create_manager_in_state(BoundaryState.LIVE, tmp_path)
    manager._teardown_pending = True
    manager._teardown_deadline = manager.clock.now_utc() + _TEARDOWN_GRACE_TIMEOUT
    manager._teardown_reason = "viewer_inactive"
    manager._transition_boundary_state(BoundaryState.NONE)
    assert manager._boundary_state == BoundaryState.NONE
    assert manager._teardown_pending is False
    assert manager.deferred_teardown_triggered() is True


def test_p12_no_spurious_teardown_when_not_pending(tmp_path: Path) -> None:
    """P12-TEST-002: Transition to LIVE without teardown pending does not fire signal."""
    manager, _ = _create_manager_in_state(BoundaryState.SWITCH_ISSUED, tmp_path)
    manager._teardown_pending = False
    manager._transition_boundary_state(BoundaryState.LIVE)
    assert manager._boundary_state == BoundaryState.LIVE
    assert manager.deferred_teardown_triggered() is False


def test_p12_teardown_pending_cleared_after_execution(tmp_path: Path) -> None:
    """P12-TEST-002: After _execute_deferred_teardown, pending and deadline cleared."""
    manager, _ = _create_manager_in_state(BoundaryState.SWITCH_ISSUED, tmp_path)
    manager._teardown_pending = True
    manager._teardown_deadline = manager.clock.now_utc() + _TEARDOWN_GRACE_TIMEOUT
    manager._teardown_reason = "viewer_inactive"
    manager._transition_boundary_state(BoundaryState.LIVE)
    assert manager._teardown_pending is False
    assert manager._teardown_deadline is None


# ---------------------------------------------------------------------------
# P12-TEST-003: Grace timeout enforcement
# ---------------------------------------------------------------------------


def test_p12_grace_timeout_forces_failed_terminal(tmp_path: Path) -> None:
    """P12-TEST-003: tick() with deadline in past forces FAILED_TERMINAL and sets _pending_fatal."""
    manager, clock = _create_manager_in_state(
        BoundaryState.SWITCH_ISSUED, tmp_path, teardown_pending=True, deadline_in_past=True
    )
    manager.tick()
    assert manager._boundary_state == BoundaryState.FAILED_TERMINAL
    assert manager._pending_fatal is not None
    assert "grace timeout" in str(manager._pending_fatal).lower() or "Teardown" in str(manager._pending_fatal)


def test_p12_grace_timeout_triggers_deferred_teardown(tmp_path: Path) -> None:
    """P12-TEST-003: Grace timeout transition to FAILED_TERMINAL triggers deferred teardown signal."""
    manager, clock = _create_manager_in_state(
        BoundaryState.SWITCH_ISSUED, tmp_path, teardown_pending=True, deadline_in_past=True
    )
    manager.tick()
    assert manager._boundary_state == BoundaryState.FAILED_TERMINAL
    assert manager.deferred_teardown_triggered() is True


def test_p12_no_timeout_when_deadline_not_reached(tmp_path: Path) -> None:
    """P12-TEST-003: tick() with deadline in future does not force FAILED_TERMINAL; returns early (no work)."""
    manager, clock = _create_manager_in_state(
        BoundaryState.SWITCH_ISSUED, tmp_path, teardown_pending=True, deadline_in_past=False
    )
    initial_state = manager._boundary_state
    manager.tick()
    assert manager._boundary_state == initial_state
    assert manager._boundary_state == BoundaryState.SWITCH_ISSUED
    assert manager._pending_fatal is None


def test_p12_no_timeout_when_not_pending(tmp_path: Path) -> None:
    """P12-TEST-003: tick() with _teardown_pending False does not run timeout check."""
    manager, clock = _create_manager_in_state(BoundaryState.SWITCH_ISSUED, tmp_path)
    manager._teardown_pending = False
    clock.advance(15)  # past any hypothetical deadline
    manager.tick()
    assert manager._boundary_state == BoundaryState.SWITCH_ISSUED


def test_p12_timeout_with_controllable_clock(tmp_path: Path) -> None:
    """P12-TEST-003: Set deadline = now+10s, advance clock 11s, tick() -> FAILED_TERMINAL."""
    manager, clock = _create_manager_in_state(BoundaryState.SWITCH_ISSUED, tmp_path)
    manager._request_teardown("viewer_inactive")
    assert manager._teardown_pending is True
    clock.advance(11)
    manager.tick()
    assert manager._boundary_state == BoundaryState.FAILED_TERMINAL


# ---------------------------------------------------------------------------
# P12-TEST-004: No new work when teardown pending
# ---------------------------------------------------------------------------


def test_p12_tick_skips_boundary_work_when_pending(tmp_path: Path) -> None:
    """P12-TEST-004: tick() with teardown pending (deadline not reached) returns early; no state changes."""
    manager, clock = _create_manager_in_state(
        BoundaryState.SWITCH_ISSUED, tmp_path, teardown_pending=True, deadline_in_past=False
    )
    state_before = manager._boundary_state
    manager.tick()
    assert manager._boundary_state == state_before
    assert manager._teardown_pending is True


def test_p12_no_new_load_preview_when_pending(tmp_path: Path) -> None:
    """P12-TEST-004: With _teardown_pending True, tick() returns before LoadPreview path (early return)."""
    manager, clock = _create_manager_in_state(BoundaryState.PLANNED, tmp_path)
    manager._teardown_pending = True
    manager._teardown_deadline = clock.now_utc() + _TEARDOWN_GRACE_TIMEOUT
    manager._segment_end_time_utc = clock.now_utc() + timedelta(seconds=60)
    manager._channel_state = "RUNNING"
    manager.tick()
    assert manager._boundary_state == BoundaryState.PLANNED
    assert manager._teardown_pending is True


def test_p12_no_new_switch_to_live_when_pending(tmp_path: Path) -> None:
    """P12-TEST-004: With _teardown_pending True, tick() returns before SwitchToLive scheduling."""
    manager, clock = _create_manager_in_state(BoundaryState.PRELOAD_ISSUED, tmp_path)
    manager._teardown_pending = True
    manager._teardown_deadline = clock.now_utc() + _TEARDOWN_GRACE_TIMEOUT
    manager.tick()
    assert manager._boundary_state == BoundaryState.PRELOAD_ISSUED


def test_p12_ensure_producer_running_blocked_when_pending(tmp_path: Path) -> None:
    """P12-TEST-004: _ensure_producer_running() returns early when _teardown_pending."""
    manager, _ = _create_manager_in_state(BoundaryState.LIVE, tmp_path)
    manager._teardown_pending = True
    manager._ensure_producer_running()
    assert manager.active_producer is None


def test_p12_multiple_ticks_while_pending(tmp_path: Path) -> None:
    """P12-TEST-004: Multiple tick() calls while pending all return early; state unchanged."""
    manager, clock = _create_manager_in_state(
        BoundaryState.SWITCH_ISSUED, tmp_path, teardown_pending=True, deadline_in_past=False
    )
    for _ in range(10):
        manager.tick()
    assert manager._boundary_state == BoundaryState.SWITCH_ISSUED
    assert manager._teardown_pending is True


# ---------------------------------------------------------------------------
# P12-TEST-005: Viewer disconnect handling (INV-VIEWER-COUNT-ADVISORY-001)
# ---------------------------------------------------------------------------


def test_p12_viewer_disconnect_defers_during_switch_issued(tmp_path: Path) -> None:
    """P12-TEST-005: Simulated disconnect (request_teardown) during SWITCH_ISSUED defers; channel not destroyed."""
    manager, _ = _create_manager_in_state(BoundaryState.SWITCH_ISSUED, tmp_path)
    result = manager._request_teardown("viewer_inactive")
    assert result is False
    assert manager._teardown_pending is True


def test_p12_viewer_disconnect_proceeds_during_live(tmp_path: Path) -> None:
    """P12-TEST-005: Simulated disconnect (request_teardown) during LIVE returns True; caller may destroy."""
    manager, _ = _create_manager_in_state(BoundaryState.LIVE, tmp_path)
    result = manager._request_teardown("viewer_inactive")
    assert result is True


def test_p12_viewer_disconnect_defers_during_switch_scheduled(tmp_path: Path) -> None:
    """P12-TEST-005: Request teardown during SWITCH_SCHEDULED defers; channel remains (pending set)."""
    manager, _ = _create_manager_in_state(BoundaryState.SWITCH_SCHEDULED, tmp_path)
    result = manager._request_teardown("viewer_inactive")
    assert result is False
    assert manager._teardown_pending is True


def test_p12_deferred_teardown_completes_after_live(tmp_path: Path) -> None:
    """P12-TEST-005: Teardown pending during SWITCH_ISSUED; transition to LIVE -> deferred signal fired."""
    manager, _ = _create_manager_in_state(BoundaryState.SWITCH_ISSUED, tmp_path)
    manager._request_teardown("viewer_inactive")
    assert manager._teardown_pending is True
    manager._transition_boundary_state(BoundaryState.LIVE)
    assert manager.deferred_teardown_triggered() is True
    assert manager._teardown_pending is False


def test_p12_rapid_disconnect_reconnect_idempotent(tmp_path: Path) -> None:
    """P12-TEST-005: Multiple _request_teardown() while pending: only one pending; deadline not reset."""
    manager, clock = _create_manager_in_state(BoundaryState.SWITCH_ISSUED, tmp_path)
    manager._request_teardown("viewer_inactive")
    deadline_first = manager._teardown_deadline
    assert deadline_first is not None
    manager._request_teardown("viewer_inactive")
    assert manager._teardown_deadline == deadline_first
    manager._request_teardown("viewer_inactive")
    assert manager._teardown_deadline == deadline_first
    assert manager._teardown_pending is True


# ---------------------------------------------------------------------------
# P12-TEST-006: Liveness only reported in LIVE state (INV-LIVE-SESSION-AUTHORITY-001)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("boundary_state", list(BoundaryState))
def test_p12_is_live_only_true_in_live_state(
    tmp_path: Path, boundary_state: BoundaryState
) -> None:
    """P12-TEST-006: is_live is True only when _boundary_state == LIVE; False for all other states."""
    manager, _ = _create_manager_in_state(boundary_state, tmp_path)
    if boundary_state == BoundaryState.LIVE:
        assert manager.is_live is True
    else:
        assert manager.is_live is False


def test_p12_is_live_true_in_live(tmp_path: Path) -> None:
    """P12-TEST-006: is_live == True when _boundary_state = LIVE."""
    manager, _ = _create_manager_in_state(BoundaryState.LIVE, tmp_path)
    assert manager.is_live is True


def test_p12_is_live_false_in_failed_terminal(tmp_path: Path) -> None:
    """P12-TEST-006: is_live == False when _boundary_state = FAILED_TERMINAL (session dead)."""
    manager, _ = _create_manager_in_state(BoundaryState.FAILED_TERMINAL, tmp_path)
    assert manager.is_live is False


def test_p12_is_live_false_in_switch_issued(tmp_path: Path) -> None:
    """P12-TEST-006: is_live == False when _boundary_state = SWITCH_ISSUED (session provisional)."""
    manager, _ = _create_manager_in_state(BoundaryState.SWITCH_ISSUED, tmp_path)
    assert manager.is_live is False
