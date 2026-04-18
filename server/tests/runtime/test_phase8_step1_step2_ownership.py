"""
Phase 8 Step 1 + Step 2 — channel-lifecycle ownership regression guards.

Invariants proven by this file:

1. Step 1: ChannelManager does NOT read linger_seconds from resolved_config.
   The value is passed in as an explicit constructor argument by ProgramDirector,
   which is the sole owner of that config read.

2. Step 2: viewer state mutation is pure — viewer_join / viewer_leave return
   a (old_count, new_count) transition tuple and do NOT autonomously invoke
   on_first_viewer / on_last_viewer. That dispatch moves to ProgramDirector
   (via its observe_viewer_transition observer).

3. Step 2 behavior preservation: a first viewer arriving via the external
   entry point (ChannelManager.tune_in, which now runs through PD's observer)
   still results in producer startup, and a last viewer leaving still
   results in the linger path firing — end-to-end behavior is unchanged.
"""
from __future__ import annotations

import inspect
from unittest.mock import patch

import pytest

from retrovue.runtime.channel_manager import ChannelManager


# ---------------------------------------------------------------------------
# Source-level guards
# ---------------------------------------------------------------------------

def test_viewer_join_does_not_autonomously_call_on_first_viewer():
    """Step 2: viewer_join must be a pure state update.

    It may still hold the viewer lock and maintain linger / state flags,
    but it must NOT dispatch the lifecycle callback `self.on_first_viewer(`.
    That dispatch is now ProgramDirector's responsibility.
    """
    source = inspect.getsource(ChannelManager.viewer_join)
    assert "self.on_first_viewer(" not in source, (
        "Phase 8 Step 2 regression: ChannelManager.viewer_join must not call "
        "self.on_first_viewer(...). PD observes the returned transition and "
        "dispatches the lifecycle callback."
    )


def test_viewer_leave_does_not_autonomously_call_on_last_viewer():
    """Step 2: same invariant for viewer_leave / on_last_viewer."""
    source = inspect.getsource(ChannelManager.viewer_leave)
    assert "self.on_last_viewer(" not in source, (
        "Phase 8 Step 2 regression: ChannelManager.viewer_leave must not call "
        "self.on_last_viewer(...). PD observes the returned transition and "
        "dispatches the lifecycle callback."
    )


def test_channel_manager_init_does_not_read_linger_seconds_from_config():
    """Step 1: ChannelManager does not read `linger_seconds` from
    resolved_config. That read belongs to ProgramDirector.

    CM may still *hold* a linger_seconds value (passed in by PD), but the
    source of truth is PD's config read. The guard here checks for the
    actual subscript-access patterns that would indicate a violation,
    not bare occurrences of the string (so descriptive comments/docstrings
    don't false-flag the check).
    """
    source = inspect.getsource(ChannelManager.__init__)
    violation_patterns = (
        '_ch["linger_seconds"]',
        '_ch[\'linger_seconds\']',
        'resolved_config["channel"]["linger_seconds"]',
        "resolved_config['channel']['linger_seconds']",
    )
    offenders = [p for p in violation_patterns if p in source]
    assert not offenders, (
        f"Phase 8 Step 1 regression: ChannelManager.__init__ reads "
        f"linger_seconds from resolved_config: {offenders}. PD is the sole "
        "owner of that config read; it passes the value in via an explicit "
        "linger_seconds parameter."
    )


# ---------------------------------------------------------------------------
# Return-value contract
# ---------------------------------------------------------------------------

def _make_cm_with_dispatching_pd():
    """Build a ChannelManager with a PD mock that correctly dispatches
    observe_viewer_transition. Keeps test setup local and explicit so we
    don't rely on the shared MockProgramDirector used by other tests.
    """
    from datetime import datetime, timezone
    from retrovue.config.testing import TEST_RESOLVED_CONFIG

    class _Clock:
        def now_utc(self):
            return datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    class _ExecReader:
        def get_current_execution_block(self, *_a, **_kw):
            class _B:
                start_utc_ms = 0
                duration_ms = 3_600_000
            return _B()
        def get_next_execution_block(self, *_a, **_kw):
            class _B:
                start_utc_ms = 3_600_000
                duration_ms = 3_600_000
            return _B()

    class _PD:
        def __init__(self):
            self._linger_scheduled: list[str] = []
            self._linger_cancelled: list[str] = []

        def get_channel_mode(self, *_a, **_kw):
            return "normal"

        def observe_viewer_transition(self, mgr, session_id, old_count, new_count):
            # Phase 8 Step 4: on 0→1 cancel any pending linger then start.
            # On 1→0 schedule a linger. This mock records scheduling rather
            # than actually wiring call_later — unit tests here do not need
            # timer fidelity.
            if old_count == 0 and new_count == 1:
                self._linger_cancelled.append(mgr.channel_id)
                mgr.start_producer(trigger_session_id=session_id)
            elif old_count == 1 and new_count == 0:
                self._linger_scheduled.append(mgr.channel_id)

        def is_channel_in_linger(self, channel_id):
            return channel_id in self._linger_scheduled and channel_id not in self._linger_cancelled

    cm = ChannelManager(
        channel_id="phase8-test",
        clock=_Clock(),
        execution_reader=_ExecReader(),
        program_director=_PD(),
        resolved_config=TEST_RESOLVED_CONFIG,
    )
    cm.set_blockplan_mode(True)
    return cm


def test_viewer_join_returns_transition_tuple():
    """viewer_join returns (old_count, new_count)."""
    cm = _make_cm_with_dispatching_pd()
    result = cm.viewer_join("s1", {})
    assert result == (0, 1), f"expected (0, 1), got {result!r}"

    result2 = cm.viewer_join("s2", {})
    assert result2 == (1, 2), f"expected (1, 2), got {result2!r}"


def test_viewer_leave_returns_transition_tuple():
    """viewer_leave returns (old_count, new_count)."""
    cm = _make_cm_with_dispatching_pd()
    cm.viewer_join("s1", {})
    cm.viewer_join("s2", {})

    result = cm.viewer_leave("s1")
    assert result == (2, 1), f"expected (2, 1), got {result!r}"

    result2 = cm.viewer_leave("s2")
    assert result2 == (1, 0), f"expected (1, 0), got {result2!r}"


def test_bare_viewer_join_does_not_start_producer():
    """viewer_join alone is a pure state update — no producer starts.

    Producer start is the responsibility of PD's observer (invoked via
    tune_in). This test proves the separation: calling viewer_join by
    itself must not trigger producer startup.
    """
    cm = _make_cm_with_dispatching_pd()
    with patch.object(ChannelManager, "_producer_start", return_value=True) as mock_start:
        cm.viewer_join("s1", {})
    assert mock_start.call_count == 0, (
        "Phase 8 Step 2: viewer_join must not auto-start the producer. "
        "Only PD's observer (via tune_in) may dispatch the start command."
    )


# ---------------------------------------------------------------------------
# End-to-end behavior preservation (via tune_in / tune_out)
# ---------------------------------------------------------------------------

def test_tune_in_first_viewer_still_starts_producer():
    """Behavior preservation: first viewer (0→1) via tune_in still starts
    the producer. The dispatch now flows through
    ProgramDirector.observe_viewer_transition → ChannelManager.start_producer,
    but the end effect is identical to the pre-refactor path.
    """
    cm = _make_cm_with_dispatching_pd()
    with patch.object(ChannelManager, "_producer_start", return_value=True) as mock_start:
        cm.tune_in("s1", {"client": "test"})
    assert mock_start.call_count == 1
    assert cm.runtime_state.viewer_count == 1


def test_tune_out_last_viewer_is_observed_by_pd():
    """Behavior preservation: last viewer (1→0) via tune_out is observed
    by PD's observer. Phase 8 Step 4 made the linger timer PD-owned, so
    we verify that the mock PD saw the 1→0 transition (it would schedule
    the timer in production). Full timer behavior is covered in
    tests/runtime/test_phase8_step4_linger_ownership.py.
    """
    cm = _make_cm_with_dispatching_pd()
    with patch.object(ChannelManager, "_producer_start", return_value=True):
        cm.tune_in("s1", {})
    cm.tune_out("s1")
    assert cm.runtime_state.viewer_count == 0
    assert cm.channel_id in cm.program_director._linger_scheduled
