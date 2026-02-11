"""
P12-TEST-009 through P12-TEST-012: Contract tests for Phase 12 Startup Convergence Amendment.

INV-SESSION-CREATION-UNGATED-001: Session creation not gated on boundary feasibility.
INV-STARTUP-CONVERGENCE-001: Infeasible boundaries skipped during convergence; convergence timeout; post-convergence FATAL.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.skip(reason="Phase 12 startup convergence not yet implemented")

from retrovue.runtime.clock import ControllableMasterClock
from retrovue.runtime.channel_manager import (
    BoundaryState,
    ChannelManager,
    MockAlternatingScheduleService,
    Phase8ProgramDirector,
    SwitchState,
    MAX_STARTUP_CONVERGENCE_WINDOW,
)
from retrovue.runtime.producer.base import Producer, ProducerMode, ProducerStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeProducerForStartup(Producer):
    """Fake producer for startup/convergence tests: start/load_preview/switch_to_live succeed."""

    def __init__(self, channel_id: str) -> None:
        super().__init__(channel_id, ProducerMode.NORMAL, {})
        self._endpoint = f"fake://{channel_id}"

    def start(
        self,
        playout_plan: list[dict[str, Any]],
        start_at_station_time: datetime,
    ) -> bool:
        self.status = ProducerStatus.RUNNING
        return True

    def stop(self) -> bool:
        self.status = ProducerStatus.STOPPED
        self._teardown_cleanup()
        return True

    def load_preview(
        self,
        asset_path: str,
        start_frame: int,
        frame_count: int,
        fps_numerator: int,
        fps_denominator: int,
    ) -> bool:
        return True

    def switch_to_live(self, target_boundary_time_utc: datetime | None = None) -> bool:
        return True

    def play_content(self, content: Any) -> bool:
        return True

    def get_stream_endpoint(self) -> str | None:
        return self._endpoint

    def health(self) -> str:
        return "running" if self.status == ProducerStatus.RUNNING else "stopped"

    def get_producer_id(self) -> str:
        return f"fake_startup_{self.channel_id}"

    def on_paced_tick(self, t_now: float, dt: float) -> None:
        self._advance_teardown(dt)


def _create_manager_startup(tmp_path: Path) -> tuple[ChannelManager, ControllableMasterClock]:
    """Create ChannelManager with fake producer for startup tests."""
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

    def build_fake(_mode: str) -> Producer | None:
        return FakeProducerForStartup(channel_id)

    manager._build_producer_for_mode = build_fake
    return manager, clock


# ---------------------------------------------------------------------------
# P12-TEST-009: Session creation ungated (INV-SESSION-CREATION-UNGATED-001)
# ---------------------------------------------------------------------------


def test_p12_session_created_with_fake_producer(tmp_path: Path) -> None:
    """P12-TEST-009: Session created successfully; no exception; convergence state initialized."""
    manager, clock = _create_manager_startup(tmp_path)
    manager.viewer_join("session-1", {"channel_id": manager.channel_id})
    assert manager.active_producer is not None
    assert manager._converged is False
    assert manager._convergence_deadline is not None
    assert manager._boundary_state == BoundaryState.PLANNED


def test_p12_session_creation_logs_ungated(caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    """P12-TEST-009: Session creation logs INV-SESSION-CREATION-UNGATED-001."""
    caplog.set_level(logging.INFO, logger="retrovue.runtime.channel_manager")
    manager, _ = _create_manager_startup(tmp_path)
    manager.viewer_join("session-1", {"channel_id": manager.channel_id})
    assert "INV-SESSION-CREATION-UNGATED-001" in caplog.text
    assert "Session created" in caplog.text


def test_p12_session_created_ample_lead_time(tmp_path: Path) -> None:
    """P12-TEST-009: Session created with ample lead time; boundary committed (PLANNED, segment_end set)."""
    manager, clock = _create_manager_startup(tmp_path)
    manager.viewer_join("session-1", {"channel_id": manager.channel_id})
    assert manager._segment_end_time_utc is not None
    assert manager._boundary_state == BoundaryState.PLANNED
    assert manager._converged is False
    assert manager._convergence_deadline is not None


def test_p12_convergence_deadline_set_at_creation(tmp_path: Path) -> None:
    """P12-TEST-009: _convergence_deadline = now + MAX_STARTUP_CONVERGENCE_WINDOW at session creation."""
    manager, clock = _create_manager_startup(tmp_path)
    now_before = clock.now_utc()
    if now_before.tzinfo is None:
        now_before = now_before.replace(tzinfo=timezone.utc)
    manager.viewer_join("session-1", {"channel_id": manager.channel_id})
    assert manager._convergence_deadline is not None
    delta = (manager._convergence_deadline - now_before) - MAX_STARTUP_CONVERGENCE_WINDOW
    assert abs(delta.total_seconds()) < 2.0  # within 2s of 120s window


# ---------------------------------------------------------------------------
# P12-TEST-010: Boundary skip during convergence (INV-STARTUP-CONVERGENCE-001)
# ---------------------------------------------------------------------------


def test_p12_boundary_skipped_when_infeasible_during_convergence(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    """P12-TEST-010: Infeasible boundary during convergence is skipped; no FAILED_TERMINAL."""
    caplog.set_level(logging.INFO, logger="retrovue.runtime.channel_manager")
    manager, clock = _create_manager_startup(tmp_path)
    manager.viewer_join("session-1", {"channel_id": manager.channel_id})
    manager._channel_state = "RUNNING"
    manager._converged = False
    # Boundary in 3s (< MIN_PREFEED_LEAD_TIME ~5s) -> infeasible
    now = clock.now_utc()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    manager._segment_end_time_utc = now + timedelta(seconds=3)
    manager._plan_boundary_ms = int(manager._segment_end_time_utc.timestamp() * 1000)
    manager._boundary_state = BoundaryState.PLANNED
    manager._switch_state = SwitchState.IDLE

    manager.tick()

    assert manager._boundary_state != BoundaryState.FAILED_TERMINAL
    assert "STARTUP_BOUNDARY_SKIPPED" in caplog.text


def test_p12_startup_boundary_skipped_log_format(caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    """P12-TEST-010: STARTUP_BOUNDARY_SKIPPED log contains boundary and lead_time."""
    caplog.set_level(logging.INFO, logger="retrovue.runtime.channel_manager")
    manager, clock = _create_manager_startup(tmp_path)
    manager.viewer_join("session-1", {"channel_id": manager.channel_id})
    manager._channel_state = "RUNNING"
    manager._converged = False
    now = clock.now_utc()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    manager._segment_end_time_utc = now + timedelta(seconds=2)
    manager._plan_boundary_ms = int(manager._segment_end_time_utc.timestamp() * 1000)
    manager._boundary_state = BoundaryState.PLANNED
    manager._switch_state = SwitchState.IDLE

    manager.tick()

    assert "STARTUP_BOUNDARY_SKIPPED" in caplog.text
    assert "min_required" in caplog.text or "lead_time" in caplog.text


def test_p12_next_boundary_evaluated_after_skip(tmp_path: Path) -> None:
    """P12-TEST-010: After skip, _segment_end_time_utc advances to next boundary from schedule."""
    manager, clock = _create_manager_startup(tmp_path)
    manager.viewer_join("session-1", {"channel_id": manager.channel_id})
    manager._channel_state = "RUNNING"
    manager._converged = False
    now = clock.now_utc()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    infeasible_boundary = now + timedelta(seconds=3)
    manager._segment_end_time_utc = infeasible_boundary
    manager._plan_boundary_ms = int(infeasible_boundary.timestamp() * 1000)
    manager._boundary_state = BoundaryState.PLANNED
    manager._switch_state = SwitchState.IDLE

    manager.tick()

    # MockAlternatingScheduleService at (now+3s) returns segment; next boundary = (now+3s) + 10s = now+13s
    assert manager._segment_end_time_utc is not None
    assert manager._segment_end_time_utc != infeasible_boundary


def test_p12_no_skip_when_converged_infeasible_fatal(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    """P12-TEST-010 / P12-TEST-012: Post-convergence infeasible boundary -> FAILED_TERMINAL."""
    caplog.set_level(logging.ERROR, logger="retrovue.runtime.channel_manager")
    manager, clock = _create_manager_startup(tmp_path)
    manager.viewer_join("session-1", {"channel_id": manager.channel_id})
    manager._channel_state = "RUNNING"
    manager._converged = True  # post-convergence
    now = clock.now_utc()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    manager._segment_end_time_utc = now + timedelta(seconds=3)
    manager._plan_boundary_ms = int(manager._segment_end_time_utc.timestamp() * 1000)
    manager._boundary_state = BoundaryState.PLANNED
    manager._switch_state = SwitchState.IDLE

    manager.tick()

    assert manager._boundary_state == BoundaryState.FAILED_TERMINAL
    assert "INV-STARTUP-BOUNDARY-FEASIBILITY-001 FATAL" in caplog.text


def test_p12_skip_does_not_log_violation(caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    """P12-TEST-010: Skipped boundary logs STARTUP_BOUNDARY_SKIPPED, not VIOLATION."""
    caplog.set_level(logging.INFO, logger="retrovue.runtime.channel_manager")
    manager, clock = _create_manager_startup(tmp_path)
    manager.viewer_join("session-1", {"channel_id": manager.channel_id})
    manager._channel_state = "RUNNING"
    manager._converged = False
    now = clock.now_utc()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    manager._segment_end_time_utc = now + timedelta(seconds=2)
    manager._plan_boundary_ms = int(manager._segment_end_time_utc.timestamp() * 1000)
    manager._boundary_state = BoundaryState.PLANNED
    manager._switch_state = SwitchState.IDLE

    manager.tick()

    assert "STARTUP_BOUNDARY_SKIPPED" in caplog.text


# ---------------------------------------------------------------------------
# P12-TEST-011: Convergence timeout (INV-STARTUP-CONVERGENCE-001)
# ---------------------------------------------------------------------------


def test_p12_convergence_timeout_forces_failed_terminal(tmp_path: Path) -> None:
    """P12-TEST-011: Convergence deadline expired -> FAILED_TERMINAL and _pending_fatal."""
    manager, clock = _create_manager_startup(tmp_path)
    manager.viewer_join("session-1", {"channel_id": manager.channel_id})
    manager._channel_state = "RUNNING"
    manager._converged = False
    now = clock.now_utc()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    manager._convergence_deadline = now - timedelta(seconds=1)
    manager._segment_end_time_utc = now + timedelta(seconds=60)
    manager._plan_boundary_ms = int(manager._segment_end_time_utc.timestamp() * 1000)
    manager._boundary_state = BoundaryState.PLANNED
    manager._switch_state = SwitchState.IDLE

    manager.tick()

    assert manager._boundary_state == BoundaryState.FAILED_TERMINAL
    assert manager._pending_fatal is not None
    assert "convergence" in str(manager._pending_fatal).lower() or "timeout" in str(manager._pending_fatal).lower()


def test_p12_convergence_timeout_logged_fatal(caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    """P12-TEST-011: Convergence timeout logs INV-STARTUP-CONVERGENCE-001 FATAL."""
    caplog.set_level(logging.ERROR, logger="retrovue.runtime.channel_manager")
    manager, clock = _create_manager_startup(tmp_path)
    manager.viewer_join("session-1", {"channel_id": manager.channel_id})
    manager._channel_state = "RUNNING"
    manager._converged = False
    now = clock.now_utc()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    manager._convergence_deadline = now - timedelta(seconds=1)
    manager._segment_end_time_utc = now + timedelta(seconds=60)
    manager._plan_boundary_ms = int(manager._segment_end_time_utc.timestamp() * 1000)
    manager._boundary_state = BoundaryState.PLANNED
    manager._switch_state = SwitchState.IDLE

    manager.tick()

    assert "INV-STARTUP-CONVERGENCE-001 FATAL" in caplog.text
    assert "Convergence timeout expired" in caplog.text or "timeout expired" in caplog.text


def test_p12_no_timeout_after_converged(tmp_path: Path) -> None:
    """P12-TEST-011: When _converged True, no convergence timeout; tick continues."""
    manager, clock = _create_manager_startup(tmp_path)
    manager.viewer_join("session-1", {"channel_id": manager.channel_id})
    manager._channel_state = "RUNNING"
    manager._converged = True
    manager._convergence_deadline = None
    now = clock.now_utc()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    manager._segment_end_time_utc = now + timedelta(seconds=30)
    manager._plan_boundary_ms = int(manager._segment_end_time_utc.timestamp() * 1000)
    manager._boundary_state = BoundaryState.PLANNED
    manager._switch_state = SwitchState.IDLE

    manager.tick()

    assert manager._boundary_state != BoundaryState.FAILED_TERMINAL or manager._pending_fatal is None
    assert manager._converged is True


def test_p12_convergence_before_timeout(tmp_path: Path) -> None:
    """P12-TEST-011: Session converged; no convergence timeout; boundary still in future after advance."""
    manager, clock = _create_manager_startup(tmp_path)
    manager.viewer_join("session-1", {"channel_id": manager.channel_id})
    manager._channel_state = "RUNNING"
    manager._converged = True
    manager._convergence_deadline = None
    now = clock.now_utc()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    # Boundary far enough in future that after advance(130) it remains feasible (no infeasibility FATAL)
    manager._segment_end_time_utc = now + timedelta(seconds=200)
    manager._plan_boundary_ms = int(manager._segment_end_time_utc.timestamp() * 1000)
    manager._boundary_state = BoundaryState.PLANNED
    manager._switch_state = SwitchState.IDLE

    clock.advance(130)
    manager.tick()

    assert manager._boundary_state == BoundaryState.PLANNED
    assert manager._converged is True


# ---------------------------------------------------------------------------
# P12-TEST-012: Post-convergence feasibility (INV-STARTUP-BOUNDARY-FEASIBILITY-001)
# ---------------------------------------------------------------------------


def test_p12_infeasible_boundary_fatal_after_convergence(tmp_path: Path) -> None:
    """P12-TEST-012: Converged session; infeasible boundary -> FAILED_TERMINAL, not skipped."""
    manager, clock = _create_manager_startup(tmp_path)
    manager.viewer_join("session-1", {"channel_id": manager.channel_id})
    manager._channel_state = "RUNNING"
    manager._converged = True
    now = clock.now_utc()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    manager._segment_end_time_utc = now + timedelta(seconds=3)
    manager._plan_boundary_ms = int(manager._segment_end_time_utc.timestamp() * 1000)
    manager._boundary_state = BoundaryState.PLANNED
    manager._switch_state = SwitchState.IDLE

    manager.tick()

    assert manager._boundary_state == BoundaryState.FAILED_TERMINAL
    assert manager._pending_fatal is not None


def test_p12_convergence_transition_sets_converged(tmp_path: Path) -> None:
    """P12-TEST-012: First successful boundary transition (LIVE) sets _converged True, _convergence_deadline None."""
    manager, _ = _create_manager_startup(tmp_path)
    manager._converged = False
    manager._convergence_deadline = datetime.now(timezone.utc) + MAX_STARTUP_CONVERGENCE_WINDOW
    manager._boundary_state = BoundaryState.SWITCH_ISSUED

    manager._transition_boundary_state(BoundaryState.LIVE)

    assert manager._converged is True
    assert manager._convergence_deadline is None


def test_p12_converged_property_after_transition(tmp_path: Path) -> None:
    """P12-TEST-012: converged property True after first LIVE transition; one-way."""
    manager, _ = _create_manager_startup(tmp_path)
    manager._converged = False
    manager._boundary_state = BoundaryState.SWITCH_ISSUED
    assert manager.converged is False

    manager._transition_boundary_state(BoundaryState.LIVE)
    assert manager.converged is True
    assert manager._convergence_deadline is None


def test_p12_convergence_deadline_cleared_after_convergence(tmp_path: Path) -> None:
    """P12-TEST-012: _convergence_deadline = None after first successful boundary (LIVE)."""
    manager, _ = _create_manager_startup(tmp_path)
    manager._converged = False
    manager._convergence_deadline = datetime.now(timezone.utc) + MAX_STARTUP_CONVERGENCE_WINDOW
    manager._boundary_state = BoundaryState.SWITCH_ISSUED

    manager._transition_boundary_state(BoundaryState.LIVE)

    assert manager._converged is True
    assert manager._convergence_deadline is None
