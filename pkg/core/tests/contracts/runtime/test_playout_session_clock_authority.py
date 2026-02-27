"""Contract: BlockCompleted delta_ms in PlayoutSession is driven only by the injected clock.

Proves that the delta (actual_wall_ms - scheduled_end_ms) uses the injected
MasterClock, not wall clock. No real time, no sleep().
"""

import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest


class FakeAdvancingClock:
    """Deterministic clock for testing; advance() controls time."""

    def __init__(self, start_ms: int) -> None:
        self._ms = start_ms

    def now_utc(self) -> datetime:
        return datetime.fromtimestamp(self._ms / 1000.0, tz=timezone.utc)

    def advance(self, delta_ms: int) -> None:
        self._ms += delta_ms


def _make_block_completed_event(playout_pb2, block_end_utc_ms: int):
    """Build a BlockEvent with block_completed for testing."""
    event = playout_pb2.BlockEvent()
    event.block_completed.block_id = "test-block"
    event.block_completed.block_start_utc_ms = block_end_utc_ms - 30_000
    event.block_completed.block_end_utc_ms = block_end_utc_ms
    event.block_completed.final_ct_ms = block_end_utc_ms
    event.block_completed.blocks_executed_total = 1
    return event


def _run_event_loop_and_capture_delta(
    session,
    playout_pb2,
    block_end_utc_ms: int,
) -> int:
    """Inject one BlockCompleted event, run event loop, return captured delta_ms."""
    event = _make_block_completed_event(playout_pb2, block_end_utc_ms)
    captured = {"delta_ms": None}

    def capture_delta(record: logging.LogRecord) -> None:
        msg = record.getMessage()
        m = re.search(r"delta_ms=(-?\d+)", msg)
        if m:
            captured["delta_ms"] = int(m.group(1))

    session._stub = MagicMock()
    session._stub.SubscribeBlockEvents = MagicMock(
        return_value=iter([event])
    )
    logger = logging.getLogger("retrovue.runtime.playout_session")
    handler = logging.Handler()
    handler.emit = capture_delta
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        session._subscribe_to_events()
        if session._event_thread:
            session._event_thread.join(timeout=2.0)
    finally:
        logger.removeHandler(handler)
    assert captured["delta_ms"] is not None, "Expected one BlockCompleted log with delta_ms"
    return captured["delta_ms"]


def test_block_completed_delta_follows_injected_clock():
    """BlockCompleted delta_ms uses session clock only; no wall-clock leak."""
    from retrovue.runtime.playout_session import PlayoutSession, playout_pb2

    start_ms = 200_000
    clock = FakeAdvancingClock(start_ms)
    block_end_utc_ms = 205_000

    session = PlayoutSession(
        channel_id="delta-clock-test",
        channel_id_int=1,
        ts_socket_path=Path("/tmp/notused"),
        program_format={"width": 1920, "height": 1080, "frame_rate": "30/1"},
        clock=clock,
    )
    # Ensure event loop can run (no real gRPC)
    session._stub = None
    session._event_stop = threading.Event()

    # At fake time 200_000: delta = 200_000 - 205_000 = -5_000
    delta1 = _run_event_loop_and_capture_delta(
        session, playout_pb2, block_end_utc_ms
    )
    assert delta1 == -5_000, f"At clock 200_000, delta should be -5_000, got {delta1}"

    # Advance fake clock to 206_000
    clock.advance(6_000)
    delta2 = _run_event_loop_and_capture_delta(
        session, playout_pb2, block_end_utc_ms
    )
    assert delta2 == 1_000, f"At clock 206_000, delta should be +1_000, got {delta2}"
