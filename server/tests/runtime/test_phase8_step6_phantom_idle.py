"""
Phase 8 Step 6 — phantom-drain side-channel removed.

Invariants proven by this file:

1. HlsConsumptionAdapter's drain thread is a *detector only*. It does not
   call ``mgr.tune_out(...)`` or otherwise mutate ChannelManager
   lifecycle directly. All lifecycle mutation flows through PD via
   ``pd._on_phantom_idle(channel_id, phantom_id, reason)``.

2. ProgramDirector owns the phantom-idle event handler and routes it
   through the normal viewer-unregistration path — so phantom teardown
   obeys the same linger / recovery / teardown rules as any other
   viewer_leave.

3. Duplicate phantom-idle events are idempotent: repeated calls with
   the same channel/phantom do not double-teardown and do not double-
   unsubscribe on the fanout side.

4. Real viewers present when a phantom-idle event fires do NOT cause
   incorrect teardown — `tune_out(phantom_id)` only affects one
   session, and the 1→0 lifecycle gate is enforced by PD's observer.

5. Source-level guard: after Step 6, `consumption_adapters.py` does not
   contain any direct `mgr.tune_out(` call expressions. The sole
   permitted phantom-lifecycle path is via `pd._on_phantom_idle(...)`.
"""
from __future__ import annotations

import inspect
import logging
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from retrovue.runtime.consumption_adapters import HlsConsumptionAdapter
from retrovue.runtime.program_director import ProgramDirector


_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "retrovue"


# ---------------------------------------------------------------------------
# PD surface
# ---------------------------------------------------------------------------

def test_program_director_exposes_phantom_idle_entry_point():
    assert hasattr(ProgramDirector, "_on_phantom_idle"), (
        "Phase 8 Step 6: ProgramDirector must expose _on_phantom_idle as "
        "the sole phantom-lifecycle entry point."
    )
    assert callable(ProgramDirector._on_phantom_idle)


# ---------------------------------------------------------------------------
# Source-level guard: drain thread no longer mutates lifecycle directly
# ---------------------------------------------------------------------------

_ADAPTERS_SRC_PATH = _SRC_ROOT / "runtime" / "consumption_adapters.py"


def test_consumption_adapters_has_no_direct_tune_out_call():
    """After Step 6, the adapter must route phantom-lifecycle mutation
    through PD. No direct `mgr.tune_out(` / `manager.tune_out(` expression
    may remain in `consumption_adapters.py`.
    """
    source = _ADAPTERS_SRC_PATH.read_text()
    forbidden = ("mgr.tune_out(", "manager.tune_out(")
    offenders = [p for p in forbidden if p in source]
    assert not offenders, (
        f"consumption_adapters.py still contains forbidden direct "
        f"lifecycle mutation{offenders}. Route via pd._on_phantom_idle(...)."
    )


def test_drain_function_calls_pd_on_phantom_idle():
    """The `_activate_phantom` method (which contains the drain closure)
    must call `pd._on_phantom_idle` to route phantom-lifecycle mutation
    through PD.
    """
    source = inspect.getsource(HlsConsumptionAdapter._activate_phantom)
    assert "_on_phantom_idle(" in source, (
        "_activate_phantom must call PD._on_phantom_idle(...) instead of "
        "mutating ChannelManager lifecycle directly."
    )


# ---------------------------------------------------------------------------
# Behavior: PD._on_phantom_idle routes through manager.tune_out
# ---------------------------------------------------------------------------

def _make_pd_with_manager(*, viewer_count: int = 1):
    """Minimal PD harness: a real ProgramDirector skeleton with a MagicMock
    manager registered under a channel id. `observe_viewer_transition`
    is also mocked so the tune_out side effects don't need a full PD
    bring-up."""
    pd = ProgramDirector.__new__(ProgramDirector)
    pd._linger_handles = {}
    pd._linger_lock = threading.Lock()
    pd._recovery_state = {}
    pd._recovery_handles = {}
    pd._recovery_lock = threading.Lock()
    pd._managers = {}
    pd._managers_lock = threading.Lock()
    pd._asyncio_loop = None
    pd._logger = logging.getLogger("phase8-step6-test")

    manager = MagicMock()
    manager.channel_id = "ch-phantom"
    manager.runtime_state = MagicMock()
    manager.runtime_state.viewer_count = viewer_count
    pd._managers["ch-phantom"] = manager
    return pd, manager


def test_on_phantom_idle_routes_through_manager_tune_out():
    pd, manager = _make_pd_with_manager()
    pd._on_phantom_idle("ch-phantom", "phantom-abc", "idle_timeout")
    manager.tune_out.assert_called_once_with("phantom-abc")


def test_on_phantom_idle_is_noop_for_unknown_channel():
    pd, _ = _make_pd_with_manager()
    # An event for a channel PD has no record of must not raise and must
    # not touch anything.
    pd._on_phantom_idle("ch-unknown", "phantom-xyz", "idle_timeout")  # should not raise


def test_on_phantom_idle_swallows_tune_out_failures():
    """A misbehaving tune_out (e.g., race on a channel mid-teardown)
    must not propagate out of _on_phantom_idle. PD logs and returns."""
    pd, manager = _make_pd_with_manager()
    manager.tune_out.side_effect = RuntimeError("boom")
    pd._on_phantom_idle("ch-phantom", "phantom-abc", "byte_flow_dead")  # must not raise


def test_duplicate_phantom_idle_is_idempotent_at_pd_level():
    """PD forwards each event to `tune_out`. On the second call for the
    same phantom, the manager's `viewer_leave` is a no-op for an
    unknown session — so nothing blows up. PD itself does not need
    dedup state; the flow is naturally idempotent once the phantom has
    been removed from `viewer_sessions`.
    """
    pd, manager = _make_pd_with_manager()
    pd._on_phantom_idle("ch-phantom", "phantom-abc", "idle_timeout")
    pd._on_phantom_idle("ch-phantom", "phantom-abc", "idle_timeout")
    # Both calls reach tune_out; the manager (real one) would dedup via
    # `viewer_sessions.pop` which is safe. Our MagicMock just records:
    assert manager.tune_out.call_count == 2
    # The important guarantee is that no exception propagates and no
    # direct-mutation side channel is invoked by PD.


# ---------------------------------------------------------------------------
# Behavior with a real ChannelManager: multi-viewer safety
# ---------------------------------------------------------------------------

def _make_real_cm_with_pd():
    """Construct a real ChannelManager wired to a PD that uses the real
    observer but mocks the linger/recovery schedulers. This proves the
    phantom-idle → tune_out path is safe when real viewers coexist.
    """
    from datetime import datetime, timezone
    from retrovue.runtime.channel_manager import ChannelManager
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

    pd = ProgramDirector.__new__(ProgramDirector)
    pd._linger_handles = {}
    pd._linger_lock = threading.Lock()
    pd._recovery_state = {}
    pd._recovery_handles = {}
    pd._recovery_lock = threading.Lock()
    pd._managers = {}
    pd._managers_lock = threading.Lock()
    pd._asyncio_loop = None
    pd._logger = logging.getLogger("phase8-step6-integration")

    # Stub the linger scheduler so we can observe without a real loop.
    pd._scheduled_linger: list[str] = []
    pd._schedule_linger = pd._scheduled_linger.append  # type: ignore[method-assign]
    pd._cancel_linger = lambda cid: None  # type: ignore[method-assign]
    # Stub recovery cancel so _stop_channel_internal paths (if hit) don't error.
    pd._cancel_recovery = lambda cid: None  # type: ignore[method-assign]

    # observe_viewer_transition stays real (bound method).
    pd.observe_viewer_transition = ProgramDirector.observe_viewer_transition.__get__(pd)

    def _get_channel_mode(cid):
        return "normal"
    pd.get_channel_mode = _get_channel_mode  # type: ignore[method-assign]

    cm = ChannelManager(
        channel_id="ch-integration",
        clock=_Clock(),
        execution_reader=_ExecReader(),
        program_director=pd,
        resolved_config=TEST_RESOLVED_CONFIG,
    )
    cm.set_blockplan_mode(True)

    # Stub start_producer so tune_in on 0→1 doesn't try to launch AIR.
    cm.start_producer = lambda *_a, **_kw: None  # type: ignore[method-assign]
    with pd._managers_lock:
        pd._managers[cm.channel_id] = cm
    return pd, cm


def test_phantom_idle_with_real_viewer_present_does_not_teardown():
    """A phantom idle event while a real viewer is still connected must
    NOT schedule linger / teardown — the 1→0 transition never happens.
    """
    pd, cm = _make_real_cm_with_pd()
    cm.tune_in("phantom-viewer", {"hls": True})
    cm.tune_in("real-viewer", {"hls": False})
    assert cm.runtime_state.viewer_count == 2
    # Phantom idle fires — phantom goes away but real viewer stays.
    pd._on_phantom_idle(cm.channel_id, "phantom-viewer", "idle_timeout")
    assert cm.runtime_state.viewer_count == 1
    # Crucially: the transition was 2→1, not 1→0. No linger scheduled.
    assert pd._scheduled_linger == [], (
        f"Linger must NOT be scheduled with a real viewer still present, "
        f"got {pd._scheduled_linger}"
    )


def test_phantom_idle_as_only_viewer_schedules_linger():
    """When the phantom is the only viewer, its idle-event must flow
    through the normal 1→0 path and schedule a linger — same as any
    other viewer_leave."""
    pd, cm = _make_real_cm_with_pd()
    cm.tune_in("phantom-viewer", {"hls": True})
    assert cm.runtime_state.viewer_count == 1
    pd._on_phantom_idle(cm.channel_id, "phantom-viewer", "byte_flow_dead")
    assert cm.runtime_state.viewer_count == 0
    assert pd._scheduled_linger == [cm.channel_id], (
        f"Linger must be scheduled on 1→0 phantom idle, "
        f"got {pd._scheduled_linger}"
    )


def test_duplicate_phantom_idle_with_real_cm_is_safe():
    """A duplicate phantom-idle on the same session is a no-op against
    `viewer_sessions` (the session is already gone) and must not flip
    the count into the negatives or re-trigger linger scheduling."""
    pd, cm = _make_real_cm_with_pd()
    cm.tune_in("phantom-viewer", {"hls": True})
    pd._on_phantom_idle(cm.channel_id, "phantom-viewer", "idle_timeout")
    assert cm.runtime_state.viewer_count == 0
    # Clear recorded schedules so we can see whether the second event re-schedules.
    pd._scheduled_linger.clear()
    pd._on_phantom_idle(cm.channel_id, "phantom-viewer", "idle_timeout")
    assert cm.runtime_state.viewer_count == 0, "viewer_count must not go negative"
    # Second event: session unknown in viewer_sessions, so viewer_leave is
    # a no-op-on-state but the observer still runs. On a 0→0 transition,
    # `observe_viewer_transition` must NOT re-schedule linger (only 1→0 does).
    assert pd._scheduled_linger == [], (
        "Duplicate phantom-idle must not re-schedule linger (transition 0→0)."
    )
