"""
Phase 8 Step 5 — producer-recovery policy moves to ProgramDirector.

Invariants proven by this file:

1. ChannelManager no longer owns any recovery-policy state or methods:
   no `_attempt_recovery`, `_on_producer_session_end`, `_recovery_attempts`,
   `_recovery_timer`, `_RECOVERY_BASE_DELAY_S`, or `_RECOVERY_MAX_ATTEMPTS`.
   The CM source contains no references to these identifiers.

2. ProgramDirector owns the recovery driver: `_recovery_state`,
   `_recovery_handles`, `_resolve_recovery_config`, `on_producer_failure`,
   `_schedule_recovery`, `_attempt_recovery`, `_cancel_recovery`.

3. Policy semantics — enforcement of INV-CHANNEL-LIVENESS-RECOVERY-001,
   now against PD:
    - reason ∈ {"stopped", "error"} with viewer_count > 0 → retry scheduled
    - reason == "last_viewer_left" → no retry
    - reason == "lookahead_exhausted" → no retry
    - viewer_count == 0 → no retry
    - backoff is non-decreasing across consecutive attempts
    - max attempts is bounded (PD gives up)
    - successful start resets the counter
    - admin/teardown stop cancels any pending recovery

4. PD issues commands through the existing command surface:
   `manager.start_producer()` is the retry mechanism; PD never reaches
   into CM-private restart paths.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from retrovue.runtime.channel_manager import ChannelManager
from retrovue.runtime.program_director import ProgramDirector


_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "retrovue"


# ---------------------------------------------------------------------------
# CM no longer owns recovery
# ---------------------------------------------------------------------------

_CM_FORBIDDEN_RECOVERY_ATTRS = (
    "_attempt_recovery",
    "_on_producer_session_end",
    "_recovery_attempts",
    "_recovery_timer",
    "_RECOVERY_BASE_DELAY_S",
    "_RECOVERY_MAX_ATTEMPTS",
)


@pytest.mark.parametrize("attr", _CM_FORBIDDEN_RECOVERY_ATTRS)
def test_channel_manager_has_no_recovery_attribute(attr: str):
    """Phase 8 Step 5: recovery-policy symbols are gone from ChannelManager."""
    assert not hasattr(ChannelManager, attr), (
        f"ChannelManager must not own `{attr}`. Recovery policy is in "
        "ProgramDirector now."
    )


def test_channel_manager_source_contains_no_recovery_identifiers():
    """File-level guard: `channel_manager.py` contains none of the forbidden
    recovery identifiers in any form (definitions, references, or comments).
    """
    source = (_SRC_ROOT / "runtime" / "channel_manager.py").read_text()
    offenders = [ident for ident in _CM_FORBIDDEN_RECOVERY_ATTRS if ident in source]
    assert not offenders, (
        f"channel_manager.py still references recovery-policy identifiers "
        f"{offenders}. Phase 8 Step 5 moved these to ProgramDirector."
    )


# ---------------------------------------------------------------------------
# PD owns the recovery driver
# ---------------------------------------------------------------------------

def test_program_director_exposes_recovery_driver_api():
    """PD must expose the recovery surface."""
    for attr in (
        "on_producer_failure",
        "_schedule_recovery",
        "_cancel_recovery",
        "_attempt_recovery",
        "_resolve_recovery_config",
    ):
        assert hasattr(ProgramDirector, attr), (
            f"ProgramDirector must expose `{attr}` (Phase 8 Step 5)."
        )


# ---------------------------------------------------------------------------
# PD behavior — parametrized retry / no-retry matrix
# ---------------------------------------------------------------------------

def _make_bare_pd(
    *,
    loop: asyncio.AbstractEventLoop,
    base_delay: float = 1.0,
    max_attempts: int = 3,
) -> ProgramDirector:
    """Minimal PD-like object for unit-level recovery tests."""
    pd = ProgramDirector.__new__(ProgramDirector)
    pd._asyncio_loop = loop
    pd._linger_handles = {}
    pd._linger_lock = threading.Lock()
    pd._recovery_state: dict[str, dict] = {}
    pd._recovery_handles: dict[str, asyncio.TimerHandle] = {}
    pd._recovery_lock = threading.Lock()
    pd._managers = {}
    pd._managers_lock = threading.Lock()
    pd._logger = logging.getLogger("phase8-step5-test")
    pd._resolve_recovery_config = lambda cid: (float(base_delay), int(max_attempts))
    return pd


def _make_pd_with_manager(
    *,
    loop: asyncio.AbstractEventLoop,
    viewer_count: int,
    base_delay: float = 1.0,
    max_attempts: int = 3,
    channel_state: str = "RUNNING",
):
    pd = _make_bare_pd(loop=loop, base_delay=base_delay, max_attempts=max_attempts)
    manager = MagicMock()
    manager.channel_id = "ch-rec"
    manager.runtime_state = MagicMock()
    manager.runtime_state.viewer_count = viewer_count
    manager._channel_state = channel_state
    with pd._managers_lock:
        pd._managers["ch-rec"] = manager
    return pd, manager


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.mark.parametrize(
    ("reason", "viewer_count", "should_schedule"),
    [
        ("stopped", 1, True),
        ("error", 1, True),
        ("stopped", 0, False),
        ("error", 0, False),
        ("last_viewer_left", 1, False),
        ("last_viewer_left", 0, False),
        ("lookahead_exhausted", 1, False),
        ("lookahead_exhausted", 0, False),
    ],
)
def test_on_producer_failure_retry_matrix(reason, viewer_count, should_schedule):
    """INV-CHANNEL-LIVENESS-RECOVERY-001 matrix: only transient failures
    with active viewers schedule a retry."""
    async def _body():
        loop = asyncio.get_running_loop()
        pd, manager = _make_pd_with_manager(
            loop=loop, viewer_count=viewer_count, base_delay=5.0
        )
        pd.on_producer_failure(manager.channel_id, reason)
        if should_schedule:
            assert manager.channel_id in pd._recovery_handles, (
                f"expected PD to schedule retry for reason={reason!r}, "
                f"viewer_count={viewer_count}"
            )
            # clean up so the event loop can close.
            pd._cancel_recovery(manager.channel_id)
        else:
            assert manager.channel_id not in pd._recovery_handles, (
                f"expected no retry for reason={reason!r}, "
                f"viewer_count={viewer_count}"
            )
    _run(_body())


def test_retry_calls_start_producer_on_expiry():
    """PD's retry timer fires `manager.start_producer()` — the Step 3
    command surface — not any CM-private restart path."""
    async def _body():
        loop = asyncio.get_running_loop()
        pd, manager = _make_pd_with_manager(
            loop=loop, viewer_count=1, base_delay=0.05, max_attempts=3
        )
        pd.on_producer_failure(manager.channel_id, "stopped")
        await asyncio.sleep(0.15)
        assert manager.start_producer.call_count == 1, (
            "PD retry must issue `manager.start_producer()` exactly once per attempt."
        )
    _run(_body())


def test_backoff_is_non_decreasing_across_attempts():
    """Successive failures without recovery produce non-decreasing delays.

    PD's backoff is exponential: base * 2**(attempts-1), capped at 30s.
    """
    async def _body():
        loop = asyncio.get_running_loop()
        pd, manager = _make_pd_with_manager(
            loop=loop, viewer_count=1, base_delay=1.0, max_attempts=10
        )
        delays: list[float] = []
        for _ in range(4):
            pd.on_producer_failure(manager.channel_id, "stopped")
            handle = pd._recovery_handles.get(manager.channel_id)
            if handle is None:
                break
            # Compute the scheduled delay from the TimerHandle's `when()` minus now.
            delays.append(handle.when() - loop.time())
            handle.cancel()
            with pd._recovery_lock:
                pd._recovery_handles.pop(manager.channel_id, None)
        assert len(delays) >= 2, delays
        for i in range(1, len(delays)):
            assert delays[i] >= delays[i - 1] - 0.05, (
                f"PD backoff must be non-decreasing, got {delays}"
            )
    _run(_body())


def test_max_attempts_gives_up():
    """After `max_attempts` consecutive failures, PD stops scheduling retries."""
    async def _body():
        loop = asyncio.get_running_loop()
        pd, manager = _make_pd_with_manager(
            loop=loop, viewer_count=1, base_delay=10.0, max_attempts=3
        )
        scheduled = 0
        for _ in range(6):
            pd.on_producer_failure(manager.channel_id, "stopped")
            if manager.channel_id in pd._recovery_handles:
                scheduled += 1
                pd._cancel_recovery(manager.channel_id)
                # Put the attempts counter back so the next call increments
                # toward the limit naturally.
                with pd._recovery_lock:
                    state = pd._recovery_state.setdefault(manager.channel_id, {"attempts": 0})
                    # _cancel_recovery clears state; restore so counter tracks.
                    state["attempts"] = scheduled
        assert scheduled == 3, (
            f"PD must give up after max_attempts={3}, got {scheduled} schedules."
        )
    _run(_body())


def test_successful_start_resets_recovery_counter():
    """When a retry attempt completes and the producer is healthy on the
    next failure's evaluation, the attempts counter resets so backoff
    starts from base again."""
    async def _body():
        loop = asyncio.get_running_loop()
        pd, manager = _make_pd_with_manager(
            loop=loop, viewer_count=1, base_delay=0.02, max_attempts=5
        )
        # Fail twice, letting each retry run.
        pd.on_producer_failure(manager.channel_id, "stopped")
        await asyncio.sleep(0.06)  # first retry fires → start_producer called
        pd.on_producer_failure(manager.channel_id, "stopped")
        await asyncio.sleep(0.06)  # second retry fires
        # The counter should reset after each successful _attempt_recovery
        # (start_producer didn't raise in the mock).
        with pd._recovery_lock:
            state = pd._recovery_state.get(manager.channel_id, {"attempts": 0})
        assert state["attempts"] == 0, (
            f"attempts must reset after successful start, got {state['attempts']}"
        )
    _run(_body())


def test_cancel_recovery_clears_handle_and_state():
    """`_cancel_recovery` removes any pending handle and clears the attempts
    counter (used on rejoin or admin/teardown stop)."""
    async def _body():
        loop = asyncio.get_running_loop()
        pd, manager = _make_pd_with_manager(loop=loop, viewer_count=1)
        pd.on_producer_failure(manager.channel_id, "stopped")
        assert manager.channel_id in pd._recovery_handles
        pd._cancel_recovery(manager.channel_id)
        assert manager.channel_id not in pd._recovery_handles
        with pd._recovery_lock:
            assert manager.channel_id not in pd._recovery_state
    _run(_body())


def test_stopped_channel_state_suppresses_retry():
    """A channel in STOPPED state (teardown in progress or complete) must
    not trigger retry, even if viewer_count > 0 in a late race."""
    async def _body():
        loop = asyncio.get_running_loop()
        pd, manager = _make_pd_with_manager(
            loop=loop, viewer_count=1, channel_state="STOPPED"
        )
        pd.on_producer_failure(manager.channel_id, "stopped")
        assert manager.channel_id not in pd._recovery_handles
    _run(_body())
