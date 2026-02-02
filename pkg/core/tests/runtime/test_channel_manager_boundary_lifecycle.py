"""
P11F-007 INV-BOUNDARY-LIFECYCLE-001: Contract tests for boundary state transitions.

Verifies all allowed transitions succeed, illegal transitions force FAILED_TERMINAL,
and FAILED_TERMINAL is absorbing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from retrovue.runtime.clock import ControllableMasterClock
from retrovue.runtime.channel_manager import (
    BoundaryState,
    ChannelManager,
    MockAlternatingScheduleService,
    Phase8ProgramDirector,
)
from retrovue.runtime.producer.base import Producer, ProducerMode, ProducerStatus


def _create_manager_in_state(from_state: BoundaryState, tmp_path: Path) -> ChannelManager:
    """Create a minimal ChannelManager with _boundary_state set to from_state."""
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
    manager._boundary_state = from_state
    return manager


@pytest.mark.parametrize(
    "from_state,to_state",
    [
        (BoundaryState.NONE, BoundaryState.PLANNED),
        (BoundaryState.PLANNED, BoundaryState.PRELOAD_ISSUED),
        (BoundaryState.PRELOAD_ISSUED, BoundaryState.SWITCH_SCHEDULED),
        (BoundaryState.SWITCH_SCHEDULED, BoundaryState.SWITCH_ISSUED),
        (BoundaryState.SWITCH_ISSUED, BoundaryState.LIVE),
        (BoundaryState.LIVE, BoundaryState.NONE),
        (BoundaryState.LIVE, BoundaryState.PLANNED),
    ],
)
def test_allowed_transitions_succeed(tmp_path: Any, from_state: BoundaryState, to_state: BoundaryState) -> None:
    """INV-BOUNDARY-LIFECYCLE-001: Allowed transitions complete normally."""
    manager = _create_manager_in_state(from_state, tmp_path)
    manager._transition_boundary_state(to_state)
    assert manager._boundary_state == to_state


@pytest.mark.parametrize(
    "from_state",
    [
        BoundaryState.PLANNED,
        BoundaryState.PRELOAD_ISSUED,
        BoundaryState.SWITCH_SCHEDULED,
        BoundaryState.SWITCH_ISSUED,
    ],
)
def test_failure_transitions_allowed(tmp_path: Any, from_state: BoundaryState) -> None:
    """INV-BOUNDARY-LIFECYCLE-001: Any active state can transition to FAILED_TERMINAL."""
    manager = _create_manager_in_state(from_state, tmp_path)
    manager._transition_boundary_state(BoundaryState.FAILED_TERMINAL)
    assert manager._boundary_state == BoundaryState.FAILED_TERMINAL


@pytest.mark.parametrize(
    "from_state,to_state",
    [
        (BoundaryState.NONE, BoundaryState.SWITCH_ISSUED),
        (BoundaryState.PLANNED, BoundaryState.LIVE),
        (BoundaryState.SWITCH_ISSUED, BoundaryState.PLANNED),
        (BoundaryState.LIVE, BoundaryState.SWITCH_ISSUED),
    ],
)
def test_illegal_transitions_force_terminal(
    tmp_path: Any, from_state: BoundaryState, to_state: BoundaryState
) -> None:
    """INV-BOUNDARY-LIFECYCLE-001: Illegal transitions force FAILED_TERMINAL."""
    manager = _create_manager_in_state(from_state, tmp_path)
    manager._transition_boundary_state(to_state)
    assert manager._boundary_state == BoundaryState.FAILED_TERMINAL
    assert manager._pending_fatal is not None


@pytest.mark.parametrize("to_state", list(BoundaryState))
def test_terminal_is_absorbing(tmp_path: Any, to_state: BoundaryState) -> None:
    """INV-BOUNDARY-LIFECYCLE-001: FAILED_TERMINAL allows no transitions."""
    manager = _create_manager_in_state(BoundaryState.FAILED_TERMINAL, tmp_path)
    manager._transition_boundary_state(to_state)
    assert manager._boundary_state == BoundaryState.FAILED_TERMINAL


def test_live_allows_next_boundary(tmp_path: Any) -> None:
    """INV-BOUNDARY-LIFECYCLE-001: LIVE allows transition to NONE or PLANNED."""
    manager = _create_manager_in_state(BoundaryState.LIVE, tmp_path)

    manager._transition_boundary_state(BoundaryState.NONE)
    assert manager._boundary_state == BoundaryState.NONE

    manager._boundary_state = BoundaryState.LIVE
    manager._transition_boundary_state(BoundaryState.PLANNED)
    assert manager._boundary_state == BoundaryState.PLANNED
