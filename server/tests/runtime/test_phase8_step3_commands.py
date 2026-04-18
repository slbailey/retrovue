"""
Phase 8 Step 3 — ChannelManager command surface.

Invariants proven by this file:

1. ChannelManager exposes `start_producer` and `stop_producer` as the explicit
   lifecycle-command surface. `on_first_viewer` is removed (inlined into
   `start_producer`). `on_last_viewer` is renamed to `begin_linger_teardown`,
   marked transitional; Step 4 moves it to PD as the timer moves.

2. ProgramDirector is the sole production caller of `start_producer` via
   viewer-transition dispatch. No other production module calls it from a
   viewer-transition observer.

3. Old callback names (`on_first_viewer`, `on_last_viewer`) must not appear
   in production code. Tests may still reference them for source-level
   regression scans; production modules must not.

4. Behavior preservation: first viewer (via `tune_in`) still starts the
   producer exactly once; repeated viewers do not double-start.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import patch

import pytest

from retrovue.runtime.channel_manager import BlockPlanProducer, ChannelManager


# ---------------------------------------------------------------------------
# Command-surface presence / absence
# ---------------------------------------------------------------------------

def test_channel_manager_exposes_start_producer_command():
    assert hasattr(ChannelManager, "start_producer"), (
        "Phase 8 Step 3: ChannelManager must expose start_producer() as the "
        "explicit command surface for producer start."
    )
    assert callable(ChannelManager.start_producer)


def test_channel_manager_exposes_stop_producer_command():
    assert hasattr(ChannelManager, "stop_producer"), (
        "Phase 8 Step 3: ChannelManager must expose stop_producer() as the "
        "explicit command surface for producer stop."
    )
    assert callable(ChannelManager.stop_producer)


def test_on_first_viewer_is_removed_from_channel_manager():
    """on_first_viewer is inlined into start_producer and must not exist
    on ChannelManager any longer. Callback naming is gone."""
    assert not hasattr(ChannelManager, "on_first_viewer"), (
        "Phase 8 Step 3: on_first_viewer must be removed; use start_producer."
    )


# ---------------------------------------------------------------------------
# Production modules no longer use the old callback names
# ---------------------------------------------------------------------------

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "retrovue"

_PROD_MODULES_TO_SCAN = [
    _SRC_ROOT / "runtime" / "program_director.py",
    _SRC_ROOT / "runtime" / "channel_manager.py",
    _SRC_ROOT / "runtime" / "consumption_adapters.py",
    _SRC_ROOT / "runtime" / "pd_helpers.py",
    _SRC_ROOT / "usecases" / "channel_manager_launch.py",
]


@pytest.mark.parametrize("path", _PROD_MODULES_TO_SCAN, ids=lambda p: p.name)
def test_production_module_does_not_call_on_first_viewer(path: Path):
    """No production module may call `.on_first_viewer(` or `.on_last_viewer(`.

    Docstrings / comments referring to the historical names are fine; this
    guard targets the call-expression shape to avoid false positives.
    """
    source = path.read_text()
    offenders: list[str] = []
    for pattern in (".on_first_viewer(", ".on_last_viewer("):
        if pattern in source:
            offenders.append(pattern)
    assert not offenders, (
        f"{path.name} contains forbidden callback-style call(s) {offenders}. "
        "Production code must use the start_producer / stop_producer "
        "command surface (Phase 8 Step 3)."
    )


# ---------------------------------------------------------------------------
# Behavior preservation (via tune_in → PD observer → start_producer)
# ---------------------------------------------------------------------------

def _make_cm_with_dispatching_pd():
    """Construct a ChannelManager wired to a PD mock whose observer uses
    the new command surface (start_producer / begin_linger_teardown)."""
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

        def get_channel_mode(self, *_a, **_kw):
            return "normal"

        def observe_viewer_transition(self, mgr, session_id, old_count, new_count):
            if old_count == 0 and new_count == 1:
                mgr.start_producer(trigger_session_id=session_id)
            elif old_count == 1 and new_count == 0:
                # Phase 8 Step 4: linger scheduling is PD-side. This mock
                # just records the 1→0 event; actual timer behavior is
                # exercised in test_phase8_step4_linger_ownership.py.
                self._linger_scheduled.append(mgr.channel_id)

        def is_channel_in_linger(self, channel_id):
            return channel_id in self._linger_scheduled

    cm = ChannelManager(
        channel_id="phase8-step3-test",
        clock=_Clock(),
        execution_reader=_ExecReader(),
        program_director=_PD(),
        resolved_config=TEST_RESOLVED_CONFIG,
    )
    cm.set_blockplan_mode(True)
    return cm


def test_first_viewer_via_tune_in_starts_producer_once():
    cm = _make_cm_with_dispatching_pd()
    with patch.object(BlockPlanProducer, "start", return_value=True) as mock_start:
        cm.tune_in("s1", {})
    assert mock_start.call_count == 1
    assert cm.active_producer is not None
    assert cm.runtime_state.viewer_count == 1


def test_repeated_viewers_do_not_double_start_producer():
    cm = _make_cm_with_dispatching_pd()
    with patch.object(BlockPlanProducer, "start", return_value=True) as mock_start:
        cm.tune_in("s1", {})
        cm.tune_in("s2", {})
        cm.tune_in("s3", {})
    assert mock_start.call_count == 1, (
        "start_producer must be idempotent; repeated viewer joins must not "
        "restart the producer."
    )
    assert cm.runtime_state.viewer_count == 3


def test_start_producer_delegates_to_ensure_producer_running():
    """start_producer's idempotency comes from _ensure_producer_running,
    which returns early when the active producer is healthy in the correct
    mode. We verify the delegation at the source level (stable, not mock-
    dependent) and separately verify no-double-start through the observer
    path (test_repeated_viewers_do_not_double_start_producer)."""
    source = inspect.getsource(ChannelManager.start_producer)
    assert "_ensure_producer_running" in source, (
        "start_producer must delegate to _ensure_producer_running to "
        "preserve the existing idempotency guarantee."
    )


def test_start_producer_noop_when_no_viewers():
    """start_producer returns without side effects when viewer_count == 0
    (race guard: the transition that triggered this call was superseded by
    a concurrent viewer_leave)."""
    cm = _make_cm_with_dispatching_pd()
    # No tune_in; viewer_count is 0.
    with patch.object(BlockPlanProducer, "start", return_value=True) as mock_start:
        cm.start_producer(trigger_session_id="racey")
    assert mock_start.call_count == 0
    assert cm.active_producer is None


# ---------------------------------------------------------------------------
# PD is the sole production caller of start_producer from viewer transitions
# ---------------------------------------------------------------------------

_SRC_MODULES_TO_SCAN_FOR_CALLERS = [
    _SRC_ROOT / "runtime" / "consumption_adapters.py",
    _SRC_ROOT / "runtime" / "pd_helpers.py",
    _SRC_ROOT / "usecases" / "channel_manager_launch.py",
    _SRC_ROOT / "integrations" / "plex" / "service.py",
]


@pytest.mark.parametrize(
    "path", _SRC_MODULES_TO_SCAN_FOR_CALLERS, ids=lambda p: p.name
)
def test_only_pd_calls_start_producer_from_production(path: Path):
    """No production module outside ProgramDirector (or ChannelManager
    itself, which defines the method) may invoke `.start_producer(` or
    `.stop_producer(` on a manager. These are PD's command surface.
    """
    source = path.read_text()
    offenders: list[str] = []
    for pattern in (".start_producer(", ".stop_producer("):
        if pattern in source:
            offenders.append(pattern)
    assert not offenders, (
        f"{path.name} calls {offenders} on a manager. Only ProgramDirector "
        "may invoke the start_producer / stop_producer command surface."
    )
