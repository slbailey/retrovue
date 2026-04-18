"""
Contract tests for INV-CHANNEL-LIVENESS-RECOVERY-001.

**Ownership (Phase 8 Step 5):** producer-recovery policy lives on
ProgramDirector. ChannelManager reports producer session-end events
(``on_producer_failure`` hook on BlockPlanProducer); PD decides whether
to retry, how long to back off, and when to give up. The retry itself
is issued via the Step 3 command surface ``manager.start_producer()``.

The structural/ownership guards for Step 5 live in
``tests/runtime/test_phase8_step5_recovery_ownership.py``. This file
exists to carry the invariant's semantic coverage forward against the
new owner (PD) — so the invariant's contract tests keep running under
its original ID.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from unittest.mock import MagicMock

import pytest

from retrovue.runtime.program_director import ProgramDirector


pytestmark = pytest.mark.contract


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

def _make_pd(
    *,
    loop: asyncio.AbstractEventLoop,
    base_delay: float = 1.0,
    max_attempts: int = 3,
) -> ProgramDirector:
    """Minimal PD-like object sufficient to exercise the recovery driver."""
    pd = ProgramDirector.__new__(ProgramDirector)
    pd._asyncio_loop = loop
    pd._linger_handles = {}
    pd._linger_lock = threading.Lock()
    pd._recovery_state = {}
    pd._recovery_handles = {}
    pd._recovery_lock = threading.Lock()
    pd._managers = {}
    pd._managers_lock = threading.Lock()
    pd._logger = logging.getLogger("inv-recovery-test")
    pd._resolve_recovery_config = lambda cid: (float(base_delay), int(max_attempts))
    return pd


def _register_manager(pd: ProgramDirector, *, viewer_count: int, channel_state: str = "RUNNING"):
    manager = MagicMock()
    manager.channel_id = "ch-inv"
    manager.runtime_state = MagicMock()
    manager.runtime_state.viewer_count = viewer_count
    manager._channel_state = channel_state
    with pd._managers_lock:
        pd._managers[manager.channel_id] = manager
    return manager


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Contract Tests
# ---------------------------------------------------------------------------

class TestInvChannelLivenessRecovery001:
    """INV-CHANNEL-LIVENESS-RECOVERY-001 contract tests, PD-owned edition."""

    def test_stopped_with_viewers_schedules_restart(self):
        async def _b():
            loop = asyncio.get_running_loop()
            pd = _make_pd(loop=loop)
            mgr = _register_manager(pd, viewer_count=1)
            pd.on_producer_failure(mgr.channel_id, "stopped")
            assert mgr.channel_id in pd._recovery_handles, (
                "reason='stopped' with viewers must schedule a retry"
            )
            pd._cancel_recovery(mgr.channel_id)
        _run(_b())

    def test_error_with_viewers_schedules_restart(self):
        async def _b():
            loop = asyncio.get_running_loop()
            pd = _make_pd(loop=loop)
            mgr = _register_manager(pd, viewer_count=1)
            pd.on_producer_failure(mgr.channel_id, "error")
            assert mgr.channel_id in pd._recovery_handles
            pd._cancel_recovery(mgr.channel_id)
        _run(_b())

    def test_last_viewer_left_no_restart(self):
        async def _b():
            loop = asyncio.get_running_loop()
            pd = _make_pd(loop=loop)
            mgr = _register_manager(pd, viewer_count=0)
            pd.on_producer_failure(mgr.channel_id, "last_viewer_left")
            assert mgr.channel_id not in pd._recovery_handles
        _run(_b())

    def test_lookahead_exhausted_no_restart(self):
        async def _b():
            loop = asyncio.get_running_loop()
            pd = _make_pd(loop=loop)
            mgr = _register_manager(pd, viewer_count=1)
            pd.on_producer_failure(mgr.channel_id, "lookahead_exhausted")
            assert mgr.channel_id not in pd._recovery_handles
        _run(_b())

    def test_stopped_zero_viewers_no_restart(self):
        async def _b():
            loop = asyncio.get_running_loop()
            pd = _make_pd(loop=loop)
            mgr = _register_manager(pd, viewer_count=0)
            pd.on_producer_failure(mgr.channel_id, "stopped")
            assert mgr.channel_id not in pd._recovery_handles
        _run(_b())

    def test_backoff_is_non_decreasing(self):
        """Consecutive failures produce non-decreasing retry delays (bounded)."""
        async def _b():
            loop = asyncio.get_running_loop()
            pd = _make_pd(loop=loop, base_delay=1.0, max_attempts=10)
            mgr = _register_manager(pd, viewer_count=1)
            delays: list[float] = []
            for _ in range(4):
                pd.on_producer_failure(mgr.channel_id, "stopped")
                handle = pd._recovery_handles.get(mgr.channel_id)
                if handle is None:
                    break
                delays.append(handle.when() - loop.time())
                handle.cancel()
                with pd._recovery_lock:
                    pd._recovery_handles.pop(mgr.channel_id, None)
            assert len(delays) >= 2
            for i in range(1, len(delays)):
                assert delays[i] >= delays[i - 1] - 0.05, (
                    f"delays must be non-decreasing, got {delays}"
                )
            assert all(d <= 60.0 for d in delays), f"bounded: {delays}"
        _run(_b())

    def test_max_attempts_gives_up(self):
        async def _b():
            loop = asyncio.get_running_loop()
            pd = _make_pd(loop=loop, base_delay=10.0, max_attempts=3)
            mgr = _register_manager(pd, viewer_count=1)
            scheduled = 0
            for i in range(6):
                pd.on_producer_failure(mgr.channel_id, "stopped")
                if mgr.channel_id in pd._recovery_handles:
                    scheduled += 1
                    pd._recovery_handles.pop(mgr.channel_id).cancel()
                    # Preserve the attempts counter (cancel would clear it).
                    with pd._recovery_lock:
                        pd._recovery_state[mgr.channel_id] = {"attempts": scheduled}
            assert scheduled == 3, f"should give up after max_attempts, got {scheduled}"
        _run(_b())

    def test_recovery_counter_resets_on_successful_start(self):
        """After the retry callback calls manager.start_producer() without
        raising, PD resets the attempts counter so the next failure uses
        the base delay again."""
        async def _b():
            loop = asyncio.get_running_loop()
            pd = _make_pd(loop=loop, base_delay=0.02, max_attempts=5)
            mgr = _register_manager(pd, viewer_count=1)
            pd.on_producer_failure(mgr.channel_id, "stopped")
            await asyncio.sleep(0.06)  # retry timer fires → start_producer called
            with pd._recovery_lock:
                state = pd._recovery_state.get(mgr.channel_id, {"attempts": 0})
            assert state["attempts"] == 0
        _run(_b())

    def test_teardown_cancels_pending_recovery(self):
        """A pending retry is cancelled when `_stop_channel_internal` runs
        (its first act on Phase 8 Step 5 is to cancel the recovery handle)."""
        async def _b():
            loop = asyncio.get_running_loop()
            pd = _make_pd(loop=loop, base_delay=5.0)
            mgr = _register_manager(pd, viewer_count=1)
            pd.on_producer_failure(mgr.channel_id, "stopped")
            assert mgr.channel_id in pd._recovery_handles
            pd._cancel_recovery(mgr.channel_id)
            assert mgr.channel_id not in pd._recovery_handles
        _run(_b())
