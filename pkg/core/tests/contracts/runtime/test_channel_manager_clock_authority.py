"""Contract: Runway and scheduling decisions follow the injected MasterClock, not wall clock.

Proves that if a non-wall MasterClock is injected (e.g. FakeAdvancingClock),
runway and related decisions diverge from real time — i.e. no time.time() leak.
"""

from datetime import datetime, timezone

import pytest


class FakeAdvancingClock:
    """Deterministic clock for testing; advance() controls time."""

    def __init__(self, start_ms: int) -> None:
        self._ms = start_ms

    def now_utc(self) -> datetime:
        return datetime.fromtimestamp(self._ms / 1000.0, tz=timezone.utc)

    def advance(self, delta_ms: int) -> None:
        self._ms += delta_ms


def test_runway_follows_injected_clock_not_wall_clock():
    """_compute_runway_ms() uses the injected clock; no time.time() leak."""
    from unittest.mock import MagicMock

    from retrovue.runtime.channel_manager import ChannelManager

    # Start at 100s (100_000 ms) so we have room to advance
    start_ms = 100_000
    clock = FakeAdvancingClock(start_ms)

    # ChannelManager needs schedule_service and program_director
    schedule_service = MagicMock()
    program_director = MagicMock()

    cm = ChannelManager(
        channel_id="clock-auth-test",
        clock=clock,
        schedule_service=schedule_service,
        program_director=program_director,
    )
    cm.set_blockplan_mode(True)

    # Build the producer the same way ChannelManager does (with our fake clock)
    producer = cm._build_producer_for_mode("normal")
    assert producer is not None

    # Simulate: delivered content ends 10_000 ms ahead of "current" clock time
    # So runway should be 10_000
    producer._max_delivered_end_utc_ms = start_ms + 10_000
    runway = producer._compute_runway_ms()
    assert runway == 10_000, "runway should be 10_000 when delivered end is 10s ahead of clock"

    # Advance clock by 5_000 ms; runway should drop to 5_000
    clock.advance(5_000)
    runway = producer._compute_runway_ms()
    assert runway == 5_000, "runway should be 5_000 after advancing clock 5s"

    # Advance another 6_000 ms; runway should be 0 (never negative)
    clock.advance(6_000)
    runway = producer._compute_runway_ms()
    assert runway == 0, "runway must be 0 when clock has passed delivered end (no negative)"
