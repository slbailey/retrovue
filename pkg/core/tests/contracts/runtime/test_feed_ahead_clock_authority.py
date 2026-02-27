"""Contract: Feed-ahead due/miss decisions are driven only by the injected clock.

Proves that deadline_due, is_miss, and is_late_decision follow the injected
MasterClock (e.g. FakeAdvancingClock), not wall clock. No sleep() used.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest


class FakeAdvancingClock:
    """Deterministic clock for testing; advance() controls time (reused from runway test)."""

    def __init__(self, start_ms: int) -> None:
        self._ms = start_ms

    def now_utc(self) -> datetime:
        return datetime.fromtimestamp(self._ms / 1000.0, tz=timezone.utc)

    def advance(self, delta_ms: int) -> None:
        self._ms += delta_ms


def test_feed_ahead_due_and_miss_follow_injected_clock():
    """Feed-ahead 'due' and 'miss' / 'late_decision' use injected clock only."""
    from retrovue.runtime.channel_manager import (
        BlockPlanProducer,
        ChannelManager,
        _FeedState,
    )
    from retrovue.runtime.playout_session import BlockPlan, FeedResult

    # Time base: 100s
    start_ms = 100_000
    clock = FakeAdvancingClock(start_ms)

    schedule_service = MagicMock()
    program_director = MagicMock()

    cm = ChannelManager(
        channel_id="feed-clock-test",
        clock=clock,
        schedule_service=schedule_service,
        program_director=program_director,
    )
    cm.set_blockplan_mode(True)
    producer = cm._build_producer_for_mode("normal")
    assert producer is not None

    # ready_by_utc_ms = start_ms + 5_000, block start (deadline) = start_ms + 8_000
    # => preload_budget_ms = 3_000
    producer._preload_budget_ms = 3_000
    producer._feed_ahead_horizon_ms = 20_000
    producer._max_delivered_end_utc_ms = start_ms + 20_000  # runway 20s so not runway_low at start_ms
    producer._feed_state = _FeedState.RUNNING
    producer._started = True
    producer._session_ended = False
    producer._session = MagicMock()
    producer._session.feed = MagicMock(return_value=FeedResult.QUEUE_FULL)

    pending_block = BlockPlan(
        block_id="test-block",
        channel_id=1,
        start_utc_ms=start_ms + 8_000,
        end_utc_ms=start_ms + 8_000 + 30_000,
        segments=[],
    )
    producer._pending_block = pending_block
    producer._next_block_first_due_utc_ms = 0
    producer._feed_credits = 0  # So at start_ms we hit credit gate and never mark block

    with producer._lock:
        producer._feed_ahead()

    # At start_ms: now < ready_by (100_000 < 105_000), so block is NOT due; we never mark missed/late
    assert producer._ready_by_miss_count == 0
    assert producer._late_decision_count == 0

    # Advance 6_000 ms; now = 106_000 >= ready_by (105_000) => deadline-due, but now < start (108_000) => not missed
    clock.advance(6_000)
    producer._feed_credits = 1
    with producer._lock:
        producer._feed_ahead()

    assert producer._ready_by_miss_count == 0, "Block should be deadline-due but NOT missed (first noticed before start)"
    # May be 0 if feed returned QUEUE_FULL before we incremented late_decision (we're past start? no: 106_000 < 108_000)
    # So we're in [ready_by, start) window, not past start. So no late_decision yet. Good.

    # Advance another 3_000 ms; now = 109_000 > start (108_000). first_due was set to 106_000 => late_decision
    clock.advance(3_000)
    producer._feed_credits = 1
    with producer._lock:
        producer._feed_ahead()

    # Either miss or late_decision: we're past block start; first_due was 106_000 so late_decision
    assert (producer._ready_by_miss_count >= 1 or producer._late_decision_count >= 1), (
        "Block should be marked missed or late_decision after clock passed start_utc_ms"
    )
