"""
Phase 8 Step 4 — linger-timer ownership moves to ProgramDirector.

Invariants proven by this file:

1. ChannelManager no longer owns linger state or the callback-inversion path:
   no `LINGER_SECONDS`, `_linger_handle`, `_linger_deadline`, `_start_linger`,
   `_linger_expire`, `_cancel_linger`, `on_linger_expired`, or
   `begin_linger_teardown`. CM does not accept a `linger_seconds=` or
   `on_linger_expired=` constructor argument.

2. ProgramDirector owns the linger-timer registry: `_linger_handles`
   (channel_id → asyncio.TimerHandle) plus `_schedule_linger` /
   `_cancel_linger` / `_on_linger_expired` methods. PD is the only place
   that reads `linger_seconds` and the only place that holds timer handles.

3. Transition semantics (behavior preservation via PD's observer):
    - 1→0 schedules a PD-owned linger timer for the channel.
    - 0→1 cancels any pending PD-owned linger timer before starting producer.
    - `_on_linger_expired` calls `manager.stop_producer(reason="last_viewer_left")`.
    - A rejoin during the linger window prevents the stop (timer was cancelled).
"""
from __future__ import annotations

import asyncio
import inspect
import re
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from retrovue.runtime.channel_manager import BlockPlanProducer, ChannelManager
from retrovue.runtime.program_director import ProgramDirector


_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "retrovue"


# ---------------------------------------------------------------------------
# CM no longer owns linger
# ---------------------------------------------------------------------------

_CM_FORBIDDEN_ATTRS = (
    "LINGER_SECONDS",
    "_linger_handle",
    "_linger_deadline",
    "_start_linger",
    "_linger_expire",
    "_cancel_linger",
    "on_linger_expired",
    "begin_linger_teardown",
)


@pytest.mark.parametrize("attr", _CM_FORBIDDEN_ATTRS)
def test_channel_manager_has_no_linger_attribute(attr: str):
    """Phase 8 Step 4: every linger-ownership symbol is off ChannelManager."""
    assert not hasattr(ChannelManager, attr), (
        f"Phase 8 Step 4 regression: ChannelManager must not own `{attr}`. "
        "Linger ownership is in ProgramDirector now."
    )


def test_channel_manager_source_contains_no_linger_references():
    """Step 4: no `_linger_*` and no `on_linger_expired` identifiers appear
    anywhere in `channel_manager.py`. (Comments or docstrings that mention
    the word ``linger`` in prose are fine — this guard targets the specific
    identifier shapes that would indicate state or call-expression leftovers.)
    """
    source = (_SRC_ROOT / "runtime" / "channel_manager.py").read_text()
    bad_identifiers = (
        "_linger_handle",
        "_linger_deadline",
        "_start_linger",
        "_linger_expire",
        "_cancel_linger",
        "on_linger_expired",
        "begin_linger_teardown",
        "LINGER_SECONDS",
    )
    offenders = [ident for ident in bad_identifiers if ident in source]
    assert not offenders, (
        f"channel_manager.py still references linger-ownership identifiers "
        f"{offenders}. Phase 8 Step 4 moved these to ProgramDirector."
    )


def test_channel_manager_init_does_not_accept_on_linger_expired():
    """Step 4: the `on_linger_expired=` kwarg is removed from the
    ChannelManager constructor. The callback-inversion path is gone.
    """
    sig = inspect.signature(ChannelManager.__init__)
    assert "on_linger_expired" not in sig.parameters, (
        "Phase 8 Step 4: ChannelManager.__init__ must not accept "
        "on_linger_expired; PD fires its own timer callback directly."
    )


def test_channel_manager_init_does_not_accept_linger_seconds():
    """Step 4: CM no longer takes `linger_seconds`. PD owns that value."""
    sig = inspect.signature(ChannelManager.__init__)
    assert "linger_seconds" not in sig.parameters, (
        "Phase 8 Step 4: ChannelManager.__init__ must not accept "
        "linger_seconds; PD resolves and owns that config value."
    )


# ---------------------------------------------------------------------------
# PD owns the linger state
# ---------------------------------------------------------------------------

def test_program_director_exposes_linger_registry_and_api():
    """PD must expose: `_linger_handles`, `_schedule_linger`,
    `_cancel_linger`, `_on_linger_expired`.
    """
    for attr in ("_schedule_linger", "_cancel_linger", "_on_linger_expired"):
        assert hasattr(ProgramDirector, attr), (
            f"Phase 8 Step 4: ProgramDirector must expose {attr}."
        )


# ---------------------------------------------------------------------------
# Observer dispatch updated
# ---------------------------------------------------------------------------

def test_observe_viewer_transition_schedules_and_cancels_via_pd_helpers():
    """Source-level: the observer uses PD's linger helpers on the
    transitions, not the old `begin_linger_teardown` call.
    """
    source = inspect.getsource(ProgramDirector.observe_viewer_transition)
    assert "_schedule_linger(" in source, (
        "observe_viewer_transition must call self._schedule_linger on 1→0."
    )
    assert "_cancel_linger(" in source, (
        "observe_viewer_transition must call self._cancel_linger on 0→1."
    )
    assert "begin_linger_teardown" not in source, (
        "observe_viewer_transition must not call begin_linger_teardown "
        "(the method is deleted from ChannelManager in Step 4)."
    )


# ---------------------------------------------------------------------------
# Behavior: schedule / cancel / expire
# ---------------------------------------------------------------------------

def _run_with_loop(coro):
    """Run an async coroutine on a fresh event loop and return its result."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_schedule_linger_records_a_timer_handle():
    """_schedule_linger inserts a TimerHandle into _linger_handles."""
    async def _run():
        pd = _make_bare_pd(loop=asyncio.get_running_loop(), linger_seconds=5)
        pd._schedule_linger("ch-1")
        assert "ch-1" in pd._linger_handles
        handle = pd._linger_handles["ch-1"]
        assert isinstance(handle, asyncio.TimerHandle)
        handle.cancel()
    _run_with_loop(_run())


def test_cancel_linger_removes_the_handle():
    """_cancel_linger cancels the timer and clears the registry entry."""
    async def _run():
        pd = _make_bare_pd(loop=asyncio.get_running_loop(), linger_seconds=5)
        pd._schedule_linger("ch-1")
        assert "ch-1" in pd._linger_handles
        pd._cancel_linger("ch-1")
        assert "ch-1" not in pd._linger_handles
    _run_with_loop(_run())


def test_linger_timer_expiry_calls_stop_producer_once():
    """When the PD-owned timer fires, `_on_linger_expired` invokes
    `manager.stop_producer(reason="last_viewer_left")` exactly once.
    """
    async def _run():
        loop = asyncio.get_running_loop()
        pd, manager = _make_pd_with_manager(loop=loop, linger_seconds=0.05)
        manager.runtime_state.viewer_count = 0  # eligible for teardown
        pd._schedule_linger(manager.channel_id)
        await asyncio.sleep(0.15)  # let the timer fire
        assert manager.stop_producer.call_count == 1
        assert manager.stop_producer.call_args.kwargs.get("reason") == "last_viewer_left"
        assert manager.channel_id not in pd._linger_handles
    _run_with_loop(_run())


def test_linger_timer_is_cancelled_on_rejoin_before_expiry():
    """A 0→1 transition before the timer fires cancels it; no stop_producer call."""
    async def _run():
        loop = asyncio.get_running_loop()
        pd, manager = _make_pd_with_manager(loop=loop, linger_seconds=0.2)
        manager.runtime_state.viewer_count = 0
        pd._schedule_linger(manager.channel_id)
        # Simulate a rejoin mid-linger.
        manager.runtime_state.viewer_count = 1
        pd._cancel_linger(manager.channel_id)
        await asyncio.sleep(0.3)  # wait past the original deadline
        assert manager.stop_producer.call_count == 0
        assert manager.channel_id not in pd._linger_handles
    _run_with_loop(_run())


def test_on_linger_expired_skips_stop_if_viewers_returned():
    """Race guard: if viewer_count > 0 at expiry (rare scheduling race),
    `_on_linger_expired` must not call stop_producer.
    """
    async def _run():
        loop = asyncio.get_running_loop()
        pd, manager = _make_pd_with_manager(loop=loop, linger_seconds=5)
        pd._linger_handles[manager.channel_id] = MagicMock()  # simulate a pending handle
        manager.runtime_state.viewer_count = 1  # viewer came back
        pd._on_linger_expired(manager.channel_id)
        assert manager.stop_producer.call_count == 0
    _run_with_loop(_run())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bare_pd(*, loop: asyncio.AbstractEventLoop, linger_seconds: float):
    """Construct a minimal PD-like object by bypassing the real __init__.

    We only need the three Phase 8 Step 4 surfaces (`_linger_handles`,
    `_schedule_linger`, `_cancel_linger`, `_on_linger_expired`,
    `_resolve_linger_seconds`, `_asyncio_loop`, `_managers`,
    `_managers_lock`, `_logger`) plus enough to drive the timer. Building a
    full ProgramDirector here would require DB, startup gating, and config;
    this harness stays local to the unit contract.
    """
    import logging
    pd = ProgramDirector.__new__(ProgramDirector)
    pd._asyncio_loop = loop
    pd._linger_handles = {}
    pd._linger_lock = threading.Lock()
    pd._managers = {}
    pd._managers_lock = threading.Lock()
    pd._logger = logging.getLogger("phase8-step4-test")

    # Override _resolve_linger_seconds to return the test value without
    # touching real resolved_config.
    pd._resolve_linger_seconds = lambda cid: float(linger_seconds)
    return pd


def _make_pd_with_manager(*, loop: asyncio.AbstractEventLoop, linger_seconds: float):
    """PD + a MagicMock manager pre-registered for a channel.

    `_stop_channel_internal` is replaced with a minimal stand-in that just
    forwards to `manager.stop_producer(reason=...)`. The full method
    exercises many PD attributes (fanout registry, pre-warmed timer
    registry, etc.) that this unit harness intentionally does not
    initialise. The stand-in preserves the Step 4 contract:
    linger-expired → stop_producer called once with the right reason.
    """
    pd = _make_bare_pd(loop=loop, linger_seconds=linger_seconds)
    manager = MagicMock()
    manager.channel_id = "ch-unit"
    manager.runtime_state = MagicMock()
    manager.runtime_state.viewer_count = 0
    with pd._managers_lock:
        pd._managers["ch-unit"] = manager

    def _fake_stop_channel_internal(channel_id, reason=None):
        mgr = pd._managers.get(channel_id)
        if mgr is not None:
            mgr.stop_producer(reason=reason or "channel_stop")
    pd._stop_channel_internal = _fake_stop_channel_internal  # type: ignore[method-assign]

    return pd, manager
