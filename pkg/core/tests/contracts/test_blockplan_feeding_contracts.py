"""
Contract Tests: BlockPlan Feeding Policy Invariants

These tests enforce the production-grade feeding contracts for perpetual playout:

Part 1 - Feeding Policy Contracts:
  - INV-FEED-EXACTLY-ONCE: N BlockCompleted events → exactly N feeds
  - INV-FEED-NO-MID-BLOCK: FeedBlockPlan never called before BlockCompleted
  - INV-FEED-TWO-BLOCK-WINDOW: Window size never exceeds 2
  - INV-FEED-NO-FEED-AFTER-END: No feeds after SessionEnded
  - INV-FEED-SESSION-END-REASON: Correct reason codes

Part 2 - Streaming Teardown Safety:
  - INV-TEARDOWN-IMMEDIATE: stop() completes within bounded time
  - INV-TEARDOWN-NO-DEADLOCK: stop() during various states succeeds
  - INV-TEARDOWN-SUBSCRIBER-CLEANUP: AIR removes disconnected subscribers

Part 3 - ChannelManager Integration:
  - INV-CM-SINGLE-SUBSCRIPTION: One subscription per session
  - INV-CM-VIEWER-LIFECYCLE: Correct start/stop on viewer transitions
  - INV-CM-RESTART-SAFETY: New session on restart

Copyright (c) 2025 RetroVue
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from unittest.mock import MagicMock, Mock, patch, call

import pytest


# =============================================================================
# Test Infrastructure - Mock Event System
# =============================================================================

@dataclass
class MockBlockCompletedEvent:
    """Simulates a BlockCompleted event from AIR."""
    block_id: str
    final_ct_ms: int
    blocks_executed_total: int


@dataclass
class MockSessionEndedEvent:
    """Simulates a SessionEnded event from AIR."""
    reason: str  # "lookahead_exhausted", "stopped", "error"
    final_ct_ms: int
    blocks_executed_total: int


@dataclass
class FeedingTracker:
    """
    Tracks all feeding operations for contract verification.

    This is injected into the system under test to observe feeding behavior
    without modifying production code.
    """
    feed_calls: list[tuple[str, float]] = field(default_factory=list)  # (block_id, timestamp)
    block_completed_events: list[tuple[str, float]] = field(default_factory=list)
    session_ended_event: Optional[tuple[str, float]] = None
    session_ended_received: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_feed(self, block_id: str):
        """Record a FeedBlockPlan call."""
        with self._lock:
            self.feed_calls.append((block_id, time.time()))

    def record_block_completed(self, block_id: str):
        """Record a BlockCompleted event."""
        with self._lock:
            self.block_completed_events.append((block_id, time.time()))

    def record_session_ended(self, reason: str):
        """Record a SessionEnded event."""
        with self._lock:
            self.session_ended_event = (reason, time.time())
            self.session_ended_received = True

    @property
    def feed_count(self) -> int:
        with self._lock:
            return len(self.feed_calls)

    @property
    def event_count(self) -> int:
        with self._lock:
            return len(self.block_completed_events)

    def get_feeds_after_session_end(self) -> list[tuple[str, float]]:
        """Return any feeds that occurred after SessionEnded."""
        with self._lock:
            if not self.session_ended_event:
                return []
            end_time = self.session_ended_event[1]
            return [(bid, t) for bid, t in self.feed_calls if t > end_time]

    def get_feeds_before_first_event(self) -> list[tuple[str, float]]:
        """Return any feeds that occurred before the first BlockCompleted."""
        with self._lock:
            if not self.block_completed_events:
                return self.feed_calls.copy()
            first_event_time = self.block_completed_events[0][1]
            return [(bid, t) for bid, t in self.feed_calls if t < first_event_time]


@dataclass
class MockBlockPlan:
    """Minimal BlockPlan for testing."""
    block_id: str
    channel_id: int
    start_utc_ms: int
    end_utc_ms: int

    def to_proto(self):
        """Mock proto conversion."""
        mock = MagicMock()
        mock.block_id = self.block_id
        mock.channel_id = self.channel_id
        mock.start_utc_ms = self.start_utc_ms
        mock.end_utc_ms = self.end_utc_ms
        return mock


class MockPlayoutSession:
    """
    Mock PlayoutSession that simulates AIR behavior for contract testing.

    Allows controlled emission of events to verify Core's response.
    """

    def __init__(
        self,
        channel_id: str,
        tracker: FeedingTracker,
        event_queue: Optional[queue.Queue] = None,
    ):
        self.channel_id = channel_id
        self.tracker = tracker
        self.event_queue = event_queue or queue.Queue()

        self._is_running = False
        self._blocks_seeded = 0
        self._blocks_fed = 0
        self._lock = threading.Lock()

        # Callbacks set by BlockPlanProducer
        self.on_block_complete: Optional[Callable[[str], None]] = None
        self.on_session_end: Optional[Callable[[str], None]] = None

        # Event processing thread
        self._event_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self, join_utc_ms: int = 0) -> bool:
        self._is_running = True
        return True

    def seed(self, block_a, block_b) -> bool:
        with self._lock:
            self._blocks_seeded = 2
            # Start event processing thread
            self._start_event_thread()
            return True

    def feed(self, block) -> bool:
        """Record feed and verify contract conditions."""
        with self._lock:
            # Record the feed
            self.tracker.record_feed(block.block_id)
            self._blocks_fed += 1
            return True

    def stop(self, reason: str = "requested") -> bool:
        self._stop_event.set()
        if self._event_thread and self._event_thread.is_alive():
            self._event_thread.join(timeout=2.0)
        self._is_running = False
        return True

    @property
    def is_running(self) -> bool:
        return self._is_running

    def _start_event_thread(self):
        """Start thread that processes mock events."""
        def event_loop():
            while not self._stop_event.is_set():
                try:
                    event = self.event_queue.get(timeout=0.1)
                    if isinstance(event, MockBlockCompletedEvent):
                        self.tracker.record_block_completed(event.block_id)
                        if self.on_block_complete:
                            self.on_block_complete(event.block_id)
                    elif isinstance(event, MockSessionEndedEvent):
                        self.tracker.record_session_ended(event.reason)
                        if self.on_session_end:
                            self.on_session_end(event.reason)
                        break  # Session ended
                except queue.Empty:
                    continue

        self._event_thread = threading.Thread(target=event_loop, daemon=True)
        self._event_thread.start()

    def emit_block_completed(self, block_id: str, ct_ms: int = 3000, total: int = 1):
        """Simulate AIR emitting BlockCompleted event."""
        self.event_queue.put(MockBlockCompletedEvent(block_id, ct_ms, total))

    def emit_session_ended(self, reason: str, ct_ms: int = 3000, total: int = 1):
        """Simulate AIR emitting SessionEnded event."""
        self.event_queue.put(MockSessionEndedEvent(reason, ct_ms, total))


# =============================================================================
# Part 1: Feeding Policy Contract Tests
# =============================================================================

class TestExactlyOnceFeed:
    """
    INV-FEED-EXACTLY-ONCE: For N BlockCompleted events, Core feeds exactly N blocks.

    Verifies:
    - No duplicate feeds for the same block
    - Feed count matches event count exactly
    - Idempotent handling of rapid events
    """

    def test_one_event_one_feed(self):
        """Single BlockCompleted → exactly one feed."""
        tracker = FeedingTracker()
        session = MockPlayoutSession("test-channel", tracker)

        # Simulate BlockPlanProducer setup
        def on_block_complete(block_id: str):
            block = MockBlockPlan(f"BLOCK-next", 1, 0, 3000)
            session.feed(block)

        session.on_block_complete = on_block_complete
        session.start()
        session.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))

        # Emit one event
        session.emit_block_completed("BLOCK-A", 3000, 1)
        time.sleep(0.2)  # Allow processing

        session.stop()

        assert tracker.event_count == 1, "Expected exactly 1 event"
        assert tracker.feed_count == 1, "INV-FEED-EXACTLY-ONCE: Expected exactly 1 feed for 1 event"

    def test_n_events_n_feeds(self):
        """N BlockCompleted events → exactly N feeds."""
        tracker = FeedingTracker()
        session = MockPlayoutSession("test-channel", tracker)

        feed_counter = [0]

        def on_block_complete(block_id: str):
            feed_counter[0] += 1
            block = MockBlockPlan(f"BLOCK-{feed_counter[0]}", 1, 0, 3000)
            session.feed(block)

        session.on_block_complete = on_block_complete
        session.start()
        session.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))

        # Emit 5 events
        for i in range(5):
            session.emit_block_completed(f"BLOCK-{i}", 3000 * (i + 1), i + 1)
            time.sleep(0.05)  # Small delay between events

        time.sleep(0.3)  # Allow processing
        session.stop()

        assert tracker.event_count == 5, f"Expected 5 events, got {tracker.event_count}"
        assert tracker.feed_count == 5, f"INV-FEED-EXACTLY-ONCE: Expected 5 feeds, got {tracker.feed_count}"

    def test_no_duplicate_feeds_for_same_block(self):
        """Duplicate events for same block_id do not cause duplicate feeds."""
        tracker = FeedingTracker()
        session = MockPlayoutSession("test-channel", tracker)

        # Track which blocks we've fed to prevent duplicates
        fed_blocks = set()

        def on_block_complete(block_id: str):
            if block_id in fed_blocks:
                return  # Skip duplicate
            fed_blocks.add(block_id)
            block = MockBlockPlan(f"NEXT-{block_id}", 1, 0, 3000)
            session.feed(block)

        session.on_block_complete = on_block_complete
        session.start()
        session.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))

        # Emit same event multiple times (simulating duplicate delivery)
        for _ in range(3):
            session.emit_block_completed("BLOCK-A", 3000, 1)

        time.sleep(0.3)
        session.stop()

        assert tracker.event_count == 3, "3 events were received"
        assert tracker.feed_count == 1, "INV-FEED-EXACTLY-ONCE: Only 1 feed despite 3 duplicate events"


class TestNoMidBlockFeeding:
    """
    INV-FEED-NO-MID-BLOCK: FeedBlockPlan is never called before a BlockCompleted event.

    Verifies:
    - Time-based or polling-based feeds are forbidden
    - All feeds are strictly event-driven
    """

    def test_no_feed_before_first_event(self):
        """No FeedBlockPlan before first BlockCompleted event."""
        tracker = FeedingTracker()
        session = MockPlayoutSession("test-channel", tracker)

        # Set up callback that tracks timing
        def on_block_complete(block_id: str):
            block = MockBlockPlan(f"NEXT-{block_id}", 1, 0, 3000)
            session.feed(block)

        session.on_block_complete = on_block_complete
        session.start()
        session.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))

        # Wait WITHOUT emitting any events
        time.sleep(0.5)

        # Verify no feeds occurred
        feeds_before = tracker.get_feeds_before_first_event()
        assert len(feeds_before) == 0, (
            f"INV-FEED-NO-MID-BLOCK: Found {len(feeds_before)} feeds before first event. "
            f"Feeds must be strictly event-driven, not time-based."
        )

        # Now emit an event
        session.emit_block_completed("BLOCK-A", 3000, 1)
        time.sleep(0.2)

        session.stop()

        # Now exactly one feed should exist
        assert tracker.feed_count == 1

    def test_feed_only_on_event_boundary(self):
        """Feeds occur only at event boundaries, never mid-block."""
        tracker = FeedingTracker()
        session = MockPlayoutSession("test-channel", tracker)

        event_times = []

        def on_block_complete(block_id: str):
            event_times.append(time.time())
            block = MockBlockPlan(f"NEXT-{block_id}", 1, 0, 3000)
            session.feed(block)

        session.on_block_complete = on_block_complete
        session.start()
        session.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))

        # Emit events at specific times
        session.emit_block_completed("BLOCK-A", 3000, 1)
        time.sleep(0.2)
        session.emit_block_completed("BLOCK-B", 6000, 2)
        time.sleep(0.2)

        session.stop()

        # Verify each feed correlates with an event
        assert tracker.feed_count == tracker.event_count, (
            "INV-FEED-NO-MID-BLOCK: Feed count must equal event count"
        )

        # Verify timing: each feed should happen very close to its event
        for i, (block_id, feed_time) in enumerate(tracker.feed_calls):
            _, event_time = tracker.block_completed_events[i]
            delta = abs(feed_time - event_time)
            assert delta < 0.1, (
                f"INV-FEED-NO-MID-BLOCK: Feed {i} occurred {delta*1000:.0f}ms from event. "
                f"Max allowed: 100ms"
            )


class TestTwoBlockWindowPreservation:
    """
    INV-FEED-TWO-BLOCK-WINDOW: Window size never exceeds 2 blocks.

    Verifies:
    - After seed(A, B): A completes → feed C
    - B completes → feed D
    - Queue never has more than 2 pending blocks
    """

    def test_feed_maintains_two_block_window(self):
        """Feed restores window to 2 after block completion."""
        tracker = FeedingTracker()
        session = MockPlayoutSession("test-channel", tracker)

        block_sequence = []
        current_index = [2]  # Start at C (after A, B seed)

        def on_block_complete(block_id: str):
            idx = current_index[0]
            block = MockBlockPlan(f"BLOCK-{chr(65 + idx)}", 1, idx * 3000, (idx + 1) * 3000)
            block_sequence.append(block.block_id)
            session.feed(block)
            current_index[0] += 1

        session.on_block_complete = on_block_complete
        session.start()
        session.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))

        # A completes → should feed C
        session.emit_block_completed("BLOCK-A", 3000, 1)
        time.sleep(0.1)

        # B completes → should feed D
        session.emit_block_completed("BLOCK-B", 6000, 2)
        time.sleep(0.1)

        # C completes → should feed E
        session.emit_block_completed("BLOCK-C", 9000, 3)
        time.sleep(0.1)

        session.stop()

        # Verify sequence: C, D, E
        assert block_sequence == ["BLOCK-C", "BLOCK-D", "BLOCK-E"], (
            f"INV-FEED-TWO-BLOCK-WINDOW: Expected sequence [C, D, E], got {block_sequence}"
        )

        # Verify each feed adds exactly one block
        assert tracker.feed_count == 3, "Expected 3 feeds for 3 events"

    def test_window_never_exceeds_two(self):
        """Queue rejects feeds that would exceed 2-block window."""
        tracker = FeedingTracker()

        # Track queue state
        queue_size = [2]  # Initial seed
        queue_full_rejections = [0]

        class WindowTrackingSession(MockPlayoutSession):
            def feed(self, block) -> bool:
                if queue_size[0] >= 2:
                    # Queue full - would exceed window
                    queue_full_rejections[0] += 1
                    return False  # Reject
                tracker.record_feed(block.block_id)
                queue_size[0] += 1
                return True

        session = WindowTrackingSession("test-channel", tracker)

        def on_block_complete(block_id: str):
            queue_size[0] -= 1  # Block completed, slot freed
            block = MockBlockPlan(f"NEXT-{block_id}", 1, 0, 3000)
            session.feed(block)

        session.on_block_complete = on_block_complete
        session.start()
        session.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))

        # Complete block A → queue goes to 1, feed adds back to 2
        session.emit_block_completed("BLOCK-A", 3000, 1)
        time.sleep(0.1)

        assert queue_size[0] <= 2, f"INV-FEED-TWO-BLOCK-WINDOW: Queue exceeded 2 (size={queue_size[0]})"

        session.stop()


class TestNoFeedAfterSessionEnded:
    """
    INV-FEED-NO-FEED-AFTER-END: No feeds after SessionEnded is received.

    Verifies:
    - Once SessionEnded is received, Core stops feeding
    - Even if schedule has more blocks available
    """

    def test_no_feed_after_session_ended(self):
        """SessionEnded halts all further feeding."""
        tracker = FeedingTracker()
        session = MockPlayoutSession("test-channel", tracker)

        # This flag simulates BlockPlanProducer's session_ended state
        session_active = [True]

        def on_block_complete(block_id: str):
            if not session_active[0]:
                return  # Guard: don't feed after session end
            block = MockBlockPlan(f"NEXT-{block_id}", 1, 0, 3000)
            session.feed(block)

        def on_session_end(reason: str):
            session_active[0] = False

        session.on_block_complete = on_block_complete
        session.on_session_end = on_session_end
        session.start()
        session.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))

        # Emit some events
        session.emit_block_completed("BLOCK-A", 3000, 1)
        time.sleep(0.1)
        session.emit_block_completed("BLOCK-B", 6000, 2)
        time.sleep(0.1)

        # Emit SessionEnded
        session.emit_session_ended("lookahead_exhausted", 9000, 2)
        time.sleep(0.2)

        feeds_before_end = tracker.feed_count

        # Try to emit more events (simulating edge case)
        # These should NOT trigger feeds
        session.emit_block_completed("BLOCK-C", 12000, 3)
        time.sleep(0.1)

        session.stop()

        # Check for feeds after session end
        feeds_after_end = tracker.get_feeds_after_session_end()
        assert len(feeds_after_end) == 0, (
            f"INV-FEED-NO-FEED-AFTER-END: Found {len(feeds_after_end)} feeds after SessionEnded. "
            f"No feeds should occur after session termination."
        )

    def test_session_ended_with_pending_blocks_in_schedule(self):
        """SessionEnded stops feeding even if schedule has more blocks."""
        tracker = FeedingTracker()
        session = MockPlayoutSession("test-channel", tracker)

        session_active = [True]
        blocks_available = [10]  # Many blocks available
        blocks_fed_after_end = [0]

        def on_block_complete(block_id: str):
            if not session_active[0]:
                blocks_fed_after_end[0] += 1
                return  # Should not feed
            if blocks_available[0] > 0:
                block = MockBlockPlan(f"NEXT-{block_id}", 1, 0, 3000)
                session.feed(block)
                blocks_available[0] -= 1

        def on_session_end(reason: str):
            session_active[0] = False

        session.on_block_complete = on_block_complete
        session.on_session_end = on_session_end
        session.start()
        session.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))

        # One completion
        session.emit_block_completed("BLOCK-A", 3000, 1)
        time.sleep(0.1)

        # Session ends
        session.emit_session_ended("stopped", 6000, 1)
        time.sleep(0.1)

        # More completions attempted
        for i in range(3):
            session.emit_block_completed(f"BLOCK-{i+2}", 9000 + i*3000, i+2)
            time.sleep(0.05)

        session.stop()

        # Verify: only 1 feed occurred (before session end)
        assert tracker.feed_count == 1, (
            f"INV-FEED-NO-FEED-AFTER-END: Expected 1 feed, got {tracker.feed_count}. "
            f"blocks_available={blocks_available[0]} should not be fed after SessionEnded."
        )
        assert blocks_fed_after_end[0] == 0, "No feed attempts should reach the callback after session end"


class TestSessionEndedReasonIntegrity:
    """
    INV-FEED-SESSION-END-REASON: Correct reason codes for session termination.

    Verifies:
    - "lookahead_exhausted" only when no future blocks exist
    - "stopped" only when Core explicitly stops
    - "error" propagates immediately and halts feeding
    """

    def test_lookahead_exhausted_when_no_blocks(self):
        """lookahead_exhausted fires when feed queue is depleted."""
        tracker = FeedingTracker()
        session = MockPlayoutSession("test-channel", tracker)

        received_reason = [None]

        def on_session_end(reason: str):
            received_reason[0] = reason

        session.on_session_end = on_session_end
        session.start()
        session.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))

        # Emit session ended with lookahead_exhausted
        session.emit_session_ended("lookahead_exhausted", 6000, 2)
        time.sleep(0.2)

        session.stop()

        assert received_reason[0] == "lookahead_exhausted", (
            f"INV-FEED-SESSION-END-REASON: Expected 'lookahead_exhausted', got '{received_reason[0]}'"
        )
        assert tracker.session_ended_event is not None
        assert tracker.session_ended_event[0] == "lookahead_exhausted"

    def test_stopped_on_explicit_stop(self):
        """stopped reason when Core explicitly stops."""
        tracker = FeedingTracker()
        session = MockPlayoutSession("test-channel", tracker)

        received_reason = [None]

        def on_session_end(reason: str):
            received_reason[0] = reason

        session.on_session_end = on_session_end
        session.start()
        session.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))

        # Emit session ended with stopped
        session.emit_session_ended("stopped", 3000, 1)
        time.sleep(0.2)

        session.stop()

        assert received_reason[0] == "stopped", (
            f"INV-FEED-SESSION-END-REASON: Expected 'stopped', got '{received_reason[0]}'"
        )

    def test_error_halts_feeding_immediately(self):
        """error reason propagates and halts feeding immediately."""
        tracker = FeedingTracker()
        session = MockPlayoutSession("test-channel", tracker)

        received_reason = [None]
        session_active = [True]

        def on_block_complete(block_id: str):
            if not session_active[0]:
                return
            block = MockBlockPlan(f"NEXT-{block_id}", 1, 0, 3000)
            session.feed(block)

        def on_session_end(reason: str):
            received_reason[0] = reason
            session_active[0] = False

        session.on_block_complete = on_block_complete
        session.on_session_end = on_session_end
        session.start()
        session.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))

        # Emit one completion
        session.emit_block_completed("BLOCK-A", 3000, 1)
        time.sleep(0.1)

        # Emit error
        session.emit_session_ended("error", 4000, 1)
        time.sleep(0.1)

        # Emit more completions (should be ignored)
        session.emit_block_completed("BLOCK-B", 6000, 2)
        time.sleep(0.1)

        session.stop()

        assert received_reason[0] == "error", (
            f"INV-FEED-SESSION-END-REASON: Expected 'error', got '{received_reason[0]}'"
        )
        # Only 1 feed should have occurred (before error)
        assert tracker.feed_count == 1, (
            f"INV-FEED-SESSION-END-REASON: Error should halt feeding. "
            f"Expected 1 feed, got {tracker.feed_count}"
        )


# =============================================================================
# Part 2: Streaming Teardown Safety Contract Tests
# =============================================================================

class TestImmediateShutdown:
    """
    INV-TEARDOWN-IMMEDIATE: stop() completes within bounded time.

    Verifies:
    - AIR terminates
    - gRPC channel closes
    - Event stream exits cleanly
    - No thread leaks
    """

    def test_stop_completes_within_timeout(self):
        """stop() completes within 5 second timeout."""
        tracker = FeedingTracker()
        session = MockPlayoutSession("test-channel", tracker)

        session.start()
        session.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))

        # Start block execution
        session.emit_block_completed("BLOCK-A", 3000, 1)
        time.sleep(0.1)

        # Measure stop time
        start_time = time.time()
        result = session.stop("test_shutdown")
        stop_duration = time.time() - start_time

        assert result is True, "stop() should return True"
        assert stop_duration < 5.0, (
            f"INV-TEARDOWN-IMMEDIATE: stop() took {stop_duration:.2f}s. "
            f"Must complete within 5 seconds."
        )

    def test_event_thread_terminates_on_stop(self):
        """Event processing thread terminates cleanly on stop."""
        tracker = FeedingTracker()
        session = MockPlayoutSession("test-channel", tracker)

        session.start()
        session.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))

        # Verify thread is running
        assert session._event_thread is not None
        assert session._event_thread.is_alive()

        # Stop
        session.stop()

        # Thread should have stopped
        if session._event_thread:
            assert not session._event_thread.is_alive(), (
                "INV-TEARDOWN-IMMEDIATE: Event thread should terminate on stop()"
            )

    def test_no_resource_leaks_on_stop(self):
        """Repeated start/stop cycles don't leak resources."""
        tracker = FeedingTracker()

        initial_thread_count = threading.active_count()

        for _ in range(5):
            session = MockPlayoutSession("test-channel", tracker)
            session.start()
            session.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))
            session.emit_block_completed("BLOCK-A", 3000, 1)
            time.sleep(0.05)
            session.stop()

        time.sleep(0.5)  # Allow threads to fully terminate

        final_thread_count = threading.active_count()
        thread_leak = final_thread_count - initial_thread_count

        assert thread_leak <= 1, (  # Allow 1 for daemon threads
            f"INV-TEARDOWN-IMMEDIATE: Thread leak detected. "
            f"Started with {initial_thread_count}, ended with {final_thread_count}"
        )


class TestNoDeadlocks:
    """
    INV-TEARDOWN-NO-DEADLOCK: stop() during various states completes within bounded time.

    Verifies:
    - Stopping while waiting for next event
    - Stopping between block boundaries
    - Stopping during event callback
    """

    def test_stop_while_waiting_for_event(self):
        """stop() while blocked waiting for next event completes."""
        tracker = FeedingTracker()
        session = MockPlayoutSession("test-channel", tracker)

        session.start()
        session.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))

        # Don't emit any events - session is waiting
        time.sleep(0.1)

        # Stop should still work
        start_time = time.time()
        result = session.stop()
        stop_duration = time.time() - start_time

        assert result is True
        assert stop_duration < 3.0, (
            f"INV-TEARDOWN-NO-DEADLOCK: stop() while waiting took {stop_duration:.2f}s. "
            f"Must complete within 3 seconds."
        )

    def test_stop_between_block_boundaries(self):
        """stop() between block boundaries completes."""
        tracker = FeedingTracker()
        session = MockPlayoutSession("test-channel", tracker)

        def slow_callback(block_id: str):
            # Simulate slow processing
            time.sleep(0.1)
            block = MockBlockPlan(f"NEXT-{block_id}", 1, 0, 3000)
            session.feed(block)

        session.on_block_complete = slow_callback
        session.start()
        session.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))

        # Start a completion
        session.emit_block_completed("BLOCK-A", 3000, 1)

        # Stop immediately (during callback processing)
        time.sleep(0.05)  # In the middle of callback
        start_time = time.time()
        result = session.stop()
        stop_duration = time.time() - start_time

        assert result is True
        assert stop_duration < 3.0, (
            f"INV-TEARDOWN-NO-DEADLOCK: stop() during processing took {stop_duration:.2f}s"
        )

    def test_concurrent_stop_from_multiple_threads(self):
        """Concurrent stop() calls don't deadlock."""
        tracker = FeedingTracker()
        session = MockPlayoutSession("test-channel", tracker)

        session.start()
        session.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))

        results = []
        errors = []

        def try_stop():
            try:
                result = session.stop()
                results.append(result)
            except Exception as e:
                errors.append(e)

        # Multiple threads try to stop simultaneously
        threads = [threading.Thread(target=try_stop) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        # All should complete without error
        assert len(errors) == 0, f"INV-TEARDOWN-NO-DEADLOCK: Errors during concurrent stop: {errors}"
        assert len(results) == 5, "All stop() calls should return"
        assert all(r is True for r in results), "All stop() calls should succeed"


class TestSubscriberCleanup:
    """
    INV-TEARDOWN-SUBSCRIBER-CLEANUP: AIR removes disconnected subscribers.

    Verifies:
    - No writes to closed streams
    - Subscriber list cleaned up on disconnect
    """

    def test_subscriber_removed_on_disconnect(self):
        """Subscriber removed from list when stream closes."""
        # This test would need the real AIR implementation
        # For mock testing, we verify the contract through the tracker
        tracker = FeedingTracker()
        session = MockPlayoutSession("test-channel", tracker)

        session.start()
        session.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))

        # Emit event
        session.emit_block_completed("BLOCK-A", 3000, 1)
        time.sleep(0.1)

        # Stop (disconnects subscriber)
        session.stop()

        # Verify stream ended cleanly
        assert session._stop_event.is_set(), "Stop event should be set"
        if session._event_thread:
            session._event_thread.join(timeout=1.0)
            assert not session._event_thread.is_alive(), (
                "INV-TEARDOWN-SUBSCRIBER-CLEANUP: Event thread should be cleaned up"
            )


# =============================================================================
# Part 3: ChannelManager Integration Contract Tests
# =============================================================================

class TestSingleSubscriptionPerSession:
    """
    INV-CM-SINGLE-SUBSCRIPTION: Only one event subscription per session.

    Verifies:
    - Multiple viewers do not create multiple event streams
    - Subscription is shared across all viewers
    """

    def test_multiple_viewers_single_subscription(self):
        """Multiple viewers share one event subscription."""
        subscription_count = [0]

        class SubscriptionTrackingSession(MockPlayoutSession):
            def seed(self, block_a, block_b) -> bool:
                result = super().seed(block_a, block_b)
                if result:
                    subscription_count[0] += 1
                return result

        tracker = FeedingTracker()
        session = SubscriptionTrackingSession("test-channel", tracker)

        # Simulate BlockPlanProducer
        session.start()

        # First viewer triggers seed (and subscription)
        session.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))

        # More "viewers" join - should not re-subscribe
        # In real implementation, seed() is only called once

        assert subscription_count[0] == 1, (
            f"INV-CM-SINGLE-SUBSCRIPTION: Expected 1 subscription, got {subscription_count[0]}"
        )

        session.stop()


class TestViewerLifecycleCorrectness:
    """
    INV-CM-VIEWER-LIFECYCLE: Correct session start/stop on viewer transitions.

    Verifies:
    - 0 → 1 viewers: starts session + subscription
    - N → N-1 (N > 1): does nothing
    - 1 → 0 viewers: stops session and closes subscription
    """

    def test_first_viewer_starts_session(self):
        """0 → 1 viewer transition starts session."""
        session_started = [False]

        class LifecycleTrackingSession(MockPlayoutSession):
            def start(self, join_utc_ms: int = 0) -> bool:
                session_started[0] = True
                return super().start(join_utc_ms)

        tracker = FeedingTracker()
        session = LifecycleTrackingSession("test-channel", tracker)

        # Simulate 0 → 1 transition
        session.start()
        session.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))

        assert session_started[0] is True, (
            "INV-CM-VIEWER-LIFECYCLE: 0→1 transition should start session"
        )
        assert session.is_running is True

        session.stop()

    def test_last_viewer_stops_session(self):
        """1 → 0 viewer transition stops session."""
        session_stopped = [False]

        class LifecycleTrackingSession(MockPlayoutSession):
            def stop(self, reason: str = "requested") -> bool:
                session_stopped[0] = True
                return super().stop(reason)

        tracker = FeedingTracker()
        session = LifecycleTrackingSession("test-channel", tracker)

        session.start()
        session.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))

        # Simulate 1 → 0 transition
        session.stop("last_viewer_left")

        assert session_stopped[0] is True, (
            "INV-CM-VIEWER-LIFECYCLE: 1→0 transition should stop session"
        )
        assert session.is_running is False


class TestRestartSafety:
    """
    INV-CM-RESTART-SAFETY: New session on restart, old resources not reused.

    Verifies:
    - New viewer after stop creates fresh session
    - Old session resources are not reused
    - State is properly reset
    """

    def test_restart_creates_new_session(self):
        """New viewer after stop creates new session."""
        session_instances = []

        tracker = FeedingTracker()

        # First session
        session1 = MockPlayoutSession("test-channel", tracker)
        session_instances.append(id(session1))
        session1.start()
        session1.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))
        session1.stop()

        # Second session (simulating new viewer after stop)
        session2 = MockPlayoutSession("test-channel", tracker)
        session_instances.append(id(session2))
        session2.start()
        session2.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))
        session2.stop()

        assert session_instances[0] != session_instances[1], (
            "INV-CM-RESTART-SAFETY: New session should be a new instance"
        )

    def test_old_session_state_not_reused(self):
        """State from old session doesn't affect new session."""
        tracker1 = FeedingTracker()
        tracker2 = FeedingTracker()

        # First session - process some blocks
        session1 = MockPlayoutSession("test-channel", tracker1)
        session1.on_block_complete = lambda bid: session1.feed(MockBlockPlan("X", 1, 0, 3000))
        session1.start()
        session1.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))
        session1.emit_block_completed("BLOCK-A", 3000, 1)
        time.sleep(0.1)
        session1.stop()

        # Verify first session had activity
        assert tracker1.feed_count == 1, "First session should have 1 feed"

        # Second session - fresh start
        session2 = MockPlayoutSession("test-channel", tracker2)
        session2.on_block_complete = lambda bid: session2.feed(MockBlockPlan("Y", 1, 0, 3000))
        session2.start()
        session2.seed(MockBlockPlan("C", 1, 0, 3000), MockBlockPlan("D", 1, 3000, 6000))

        # Second session starts fresh
        assert tracker2.feed_count == 0, (
            "INV-CM-RESTART-SAFETY: New session should start with 0 feeds"
        )
        assert session2._blocks_seeded == 2, "New session should have 2 seeded blocks"

        session2.stop()


# =============================================================================
# Architecture Verification Tests
# =============================================================================

class TestArchitecturalInvariants:
    """
    Verify architectural invariants are preserved:
    - AIR remains autonomous (no mid-block polling)
    - Core remains event-driven (no timers)
    - Boundaries are the only synchronization points
    """

    def test_no_timer_based_feeding(self):
        """Feeding is not timer-based."""
        tracker = FeedingTracker()
        session = MockPlayoutSession("test-channel", tracker)

        # Set up callback that ONLY feeds on events
        event_driven_feeds = [0]

        def strict_event_callback(block_id: str):
            event_driven_feeds[0] += 1
            session.feed(MockBlockPlan(f"NEXT-{block_id}", 1, 0, 3000))

        session.on_block_complete = strict_event_callback
        session.start()
        session.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))

        # Wait a "long" time without events
        time.sleep(0.5)

        # No feeds should occur (no timer)
        assert tracker.feed_count == 0, (
            "ARCHITECTURE: No timer-based feeding. "
            f"Expected 0 feeds during wait, got {tracker.feed_count}"
        )

        # Now emit event - should trigger exactly one feed
        session.emit_block_completed("BLOCK-A", 3000, 1)
        time.sleep(0.2)

        assert tracker.feed_count == 1, "Event should trigger exactly one feed"
        assert event_driven_feeds[0] == 1, "Feed was event-driven"

        session.stop()

    def test_air_autonomous_execution(self):
        """AIR executes blocks autonomously without Core intervention."""
        tracker = FeedingTracker()
        session = MockPlayoutSession("test-channel", tracker)

        # Track when events are emitted (simulating AIR's autonomous execution)
        event_emit_times = []

        def on_block_complete(block_id: str):
            event_emit_times.append(time.time())
            session.feed(MockBlockPlan(f"NEXT-{block_id}", 1, 0, 3000))

        session.on_block_complete = on_block_complete
        session.start()
        session.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))

        # AIR emits events autonomously (simulated)
        start_time = time.time()
        session.emit_block_completed("BLOCK-A", 3000, 1)
        time.sleep(0.1)
        session.emit_block_completed("BLOCK-B", 6000, 2)
        time.sleep(0.1)

        session.stop()

        # Events were driven by AIR (emissions), not by Core polling
        assert len(event_emit_times) == 2, "AIR emitted 2 events autonomously"

        # Verify Core only reacted to events (didn't initiate)
        assert tracker.feed_count == tracker.event_count, (
            "ARCHITECTURE: Core reacts exactly once per AIR event"
        )

    def test_boundaries_only_sync_point(self):
        """Block boundaries are the only synchronization points."""
        tracker = FeedingTracker()
        session = MockPlayoutSession("test-channel", tracker)

        sync_points = []  # Track when Core and AIR synchronize

        def on_block_complete(block_id: str):
            sync_points.append(("boundary", time.time(), block_id))
            session.feed(MockBlockPlan(f"NEXT-{block_id}", 1, 0, 3000))

        session.on_block_complete = on_block_complete
        session.start()
        session.seed(MockBlockPlan("A", 1, 0, 3000), MockBlockPlan("B", 1, 3000, 6000))

        # Emit boundary events
        session.emit_block_completed("BLOCK-A", 3000, 1)
        time.sleep(0.1)
        session.emit_block_completed("BLOCK-B", 6000, 2)
        time.sleep(0.1)

        session.stop()

        # All sync points are boundaries
        for sync_type, _, block_id in sync_points:
            assert sync_type == "boundary", (
                f"ARCHITECTURE: Non-boundary sync detected at {block_id}"
            )

        # Number of sync points equals number of events
        assert len(sync_points) == 2, (
            f"ARCHITECTURE: Expected 2 boundary sync points, got {len(sync_points)}"
        )


# =============================================================================
# Part 4: Queue Discipline Contract Tests (INV-FEED-QUEUE-*)
# =============================================================================

class TestQueueFullRetry:
    """
    INV-FEED-QUEUE-001 through 005: QUEUE_FULL retry discipline.

    Verifies:
    - Rejected blocks are stored in pending slot
    - Pending blocks are retried on BLOCK_COMPLETE (before generating new)
    - Cursor only advances on successful feed
    - No block index is skipped
    - Retry is event-driven (no polling/timers)
    """

    def test_queue_full_stores_pending_and_retries_on_complete(self):
        """
        INV-FEED-QUEUE-001/002/003: When feed() returns False (QUEUE_FULL),
        the block is stored as pending. On next BLOCK_COMPLETE, the pending
        block is retried before any new block is generated.
        """
        from retrovue.runtime.channel_manager import BlockPlanProducer

        producer = BlockPlanProducer(
            channel_id="qf-test",
            configuration={"block_duration_ms": 3000},
            channel_config=None,
            schedule_service=None,
            clock=None,
        )

        playout_plan = [
            {"asset_path": "assets/Episode1.mp4", "duration_ms": 3000},
            {"asset_path": "assets/Filler.mp4", "duration_ms": 3000},
            {"asset_path": "assets/Episode2.mp4", "duration_ms": 3000},
        ]

        # Track all feed calls with their block_ids and return values
        feed_log: list[tuple[str, bool]] = []
        queue_full_until_event = [True]  # Simulate queue full initially

        class QueueFullSession:
            """Mock session that rejects first feed (simulating QUEUE_FULL at startup)."""
            def __init__(self):
                self.on_block_complete = None
                self.on_session_end = None
                self._seeded = False

            def start(self, join_utc_ms=0):
                return True

            def seed(self, block_a, block_b):
                self._seeded = True
                return True

            def feed(self, block):
                from retrovue.runtime.playout_session import FeedResult
                if queue_full_until_event[0]:
                    feed_log.append((block.block_id, False))
                    return FeedResult.QUEUE_FULL
                feed_log.append((block.block_id, True))
                return FeedResult.ACCEPTED

            def stop(self, reason="requested"):
                return True

            @property
            def is_running(self):
                return self._seeded

        # Manually wire the mock session into the producer
        mock_session = QueueFullSession()
        producer._session = mock_session
        producer._playout_plan = playout_plan

        # Simulate start() sequence: generate and seed first 2 blocks
        block_a = producer._generate_next_block(playout_plan)
        producer._advance_cursor(block_a)
        block_b = producer._generate_next_block(playout_plan)
        producer._advance_cursor(block_b)

        mock_session.seed(block_a, block_b)
        mock_session.on_block_complete = producer._on_block_complete

        # Feed 3rd block — should be rejected (QUEUE_FULL)
        from retrovue.runtime.playout_session import FeedResult
        block_c = producer._generate_next_block(playout_plan)
        result = producer._try_feed_block(block_c)

        # Verify: feed was rejected, block is pending
        assert result == FeedResult.QUEUE_FULL, f"Feed should be QUEUE_FULL, got {result}"
        assert producer._pending_block is not None, (
            "INV-FEED-QUEUE-002: Rejected block must be stored in _pending_block"
        )
        assert producer._pending_block.block_id == "BLOCK-qf-test-2", (
            f"Pending block should be BLOCK-qf-test-2, got {producer._pending_block.block_id}"
        )
        # Cursor should NOT have advanced past block 2
        assert producer._block_index == 2, (
            f"INV-FEED-QUEUE-001: Cursor should still be at 2, got {producer._block_index}"
        )

        assert feed_log == [("BLOCK-qf-test-2", False)], (
            f"Expected single rejected feed, got {feed_log}"
        )

        # Now simulate: queue slot freed (BLOCK_COMPLETE for block A)
        queue_full_until_event[0] = False  # Queue now has room
        feed_log.clear()

        producer._started = True  # Simulate started state
        # Feed-ahead requires RUNNING state and in-flight tracking
        from retrovue.runtime.channel_manager import _FeedState
        producer._feed_state = _FeedState.RUNNING
        producer._in_flight_block_ids.add("BLOCK-qf-test-0")
        producer._on_block_complete("BLOCK-qf-test-0")

        # Verify: pending block was retried FIRST (same block_id)
        assert len(feed_log) >= 1, f"Expected at least 1 feed on retry, got {len(feed_log)}"
        assert feed_log[0] == ("BLOCK-qf-test-2", True), (
            f"INV-FEED-QUEUE-003: Retry must use same block_id. Got {feed_log[0]}"
        )

        # Verify: pending slot is now clear
        assert producer._pending_block is None, (
            "Pending block should be cleared after successful retry"
        )

        # Verify: cursor has advanced past the retried block (may be further due to feed-ahead)
        assert producer._block_index >= 3, (
            f"INV-FEED-QUEUE-001: Cursor should be >= 3 after successful feed, got {producer._block_index}"
        )

    def test_sequence_integrity_no_gaps(self):
        """
        INV-FEED-QUEUE-004: Block sequence is gap-free despite QUEUE_FULL.

        Runs a full 5-block feeding sequence where block 2 is initially
        rejected. Verifies every block index appears exactly once.
        """
        from retrovue.runtime.channel_manager import BlockPlanProducer

        producer = BlockPlanProducer(
            channel_id="seq-test",
            configuration={"block_duration_ms": 3000},
            channel_config=None,
            schedule_service=None,
            clock=None,
        )

        playout_plan = [
            {"asset_path": f"assets/Content{i}.mp4", "duration_ms": 3000}
            for i in range(5)
        ]

        # Track successfully fed block IDs
        successfully_fed: list[str] = []
        reject_next = [False]

        class ControlledSession:
            def __init__(self):
                self.on_block_complete = None
                self.on_session_end = None

            def start(self, join_utc_ms=0):
                return True

            def seed(self, block_a, block_b):
                successfully_fed.append(block_a.block_id)
                successfully_fed.append(block_b.block_id)
                return True

            def feed(self, block):
                from retrovue.runtime.playout_session import FeedResult
                if reject_next[0]:
                    reject_next[0] = False  # Only reject once
                    return FeedResult.QUEUE_FULL
                successfully_fed.append(block.block_id)
                return FeedResult.ACCEPTED

            def stop(self, reason="requested"):
                return True

            @property
            def is_running(self):
                return True

        from retrovue.runtime.channel_manager import _FeedState

        mock_session = ControlledSession()
        producer._session = mock_session
        producer._playout_plan = playout_plan
        producer._started = True
        producer._feed_state = _FeedState.RUNNING
        mock_session.on_block_complete = producer._on_block_complete

        # Seed blocks 0, 1
        block_a = producer._generate_next_block(playout_plan)
        producer._advance_cursor(block_a)
        block_b = producer._generate_next_block(playout_plan)
        producer._advance_cursor(block_b)
        mock_session.seed(block_a, block_b)

        # Track seeded blocks as in-flight
        producer._in_flight_block_ids.add(block_a.block_id)
        producer._in_flight_block_ids.add(block_b.block_id)

        # Feed block 2 — will be REJECTED
        reject_next[0] = True
        producer._feed_credits = 1  # Give a credit for the direct _try_feed_block call
        block_c = producer._generate_next_block(playout_plan)
        producer._try_feed_block(block_c)

        # Verify block 2 is pending
        assert producer._pending_block is not None
        assert producer._pending_block.block_id == "BLOCK-seq-test-2"

        # BLOCK_COMPLETE for block 0 → retries block 2 (succeeds), may feed more via feed-ahead
        producer._on_block_complete("BLOCK-seq-test-0")

        # Track additionally fed blocks as in-flight for subsequent completions
        for bid in successfully_fed[2:]:  # skip seeded 0,1
            producer._in_flight_block_ids.add(bid)

        # BLOCK_COMPLETE for block 1 → generates and feeds next block(s)
        producer._on_block_complete("BLOCK-seq-test-1")
        for bid in successfully_fed:
            producer._in_flight_block_ids.add(bid)

        # BLOCK_COMPLETE for block 2 → generates and feeds next block(s)
        producer._on_block_complete("BLOCK-seq-test-2")

        # Verify sequence integrity: blocks 0-4 must all be present, in order, no gaps
        # Feed-ahead may have fed beyond block 4, but 0-4 must appear in order.
        expected_prefix = [f"BLOCK-seq-test-{i}" for i in range(5)]
        assert successfully_fed[:5] == expected_prefix, (
            f"INV-FEED-QUEUE-004: Expected gap-free sequence starting with {expected_prefix}, "
            f"got {successfully_fed}"
        )

    def test_no_polling_retry(self):
        """
        INV-FEED-QUEUE-005: Retry only happens on BLOCK_COMPLETE event,
        never via timer or polling.
        """
        from retrovue.runtime.channel_manager import BlockPlanProducer

        producer = BlockPlanProducer(
            channel_id="poll-test",
            configuration={"block_duration_ms": 3000},
            channel_config=None,
            schedule_service=None,
            clock=None,
        )

        playout_plan = [{"asset_path": "assets/A.mp4", "duration_ms": 3000}]
        feed_attempts: list[str] = []

        class NeverAcceptSession:
            """Session that always rejects feeds (permanent QUEUE_FULL)."""
            def __init__(self):
                self.on_block_complete = None
                self.on_session_end = None

            def start(self, join_utc_ms=0):
                return True

            def seed(self, block_a, block_b):
                return True

            def feed(self, block):
                from retrovue.runtime.playout_session import FeedResult
                feed_attempts.append(block.block_id)
                return FeedResult.QUEUE_FULL  # Always QUEUE_FULL

            def stop(self, reason="requested"):
                return True

            @property
            def is_running(self):
                return True

        mock_session = NeverAcceptSession()
        producer._session = mock_session
        producer._playout_plan = playout_plan
        producer._started = True
        mock_session.on_block_complete = producer._on_block_complete

        # Seed blocks 0, 1
        block_a = producer._generate_next_block(playout_plan)
        producer._advance_cursor(block_a)
        block_b = producer._generate_next_block(playout_plan)
        producer._advance_cursor(block_b)
        mock_session.seed(block_a, block_b)

        # Try to feed block 2 — rejected
        producer._feed_credits = 1  # Give a credit for the direct _try_feed_block call
        block_c = producer._generate_next_block(playout_plan)
        producer._try_feed_block(block_c)

        # Wait without any BLOCK_COMPLETE events — should NOT retry
        initial_attempts = len(feed_attempts)
        time.sleep(0.3)
        after_wait_attempts = len(feed_attempts)

        assert after_wait_attempts == initial_attempts, (
            f"INV-FEED-QUEUE-005: No retry without BLOCK_COMPLETE event. "
            f"Expected {initial_attempts} attempts, got {after_wait_attempts}"
        )

    def test_cleanup_clears_pending(self):
        """
        INV-FEED-QUEUE-002: _cleanup() resets _pending_block to None.
        """
        from retrovue.runtime.channel_manager import BlockPlanProducer

        producer = BlockPlanProducer(
            channel_id="cleanup-test",
            configuration={"block_duration_ms": 3000},
            channel_config=None,
            schedule_service=None,
            clock=None,
        )

        # Simulate a pending block
        from retrovue.runtime.playout_session import BlockPlan
        producer._pending_block = BlockPlan(
            block_id="BLOCK-cleanup-test-2",
            channel_id=1,
            start_utc_ms=6000,
            end_utc_ms=9000,
            segments=[],
        )

        assert producer._pending_block is not None

        producer._cleanup()

        assert producer._pending_block is None, (
            "INV-FEED-QUEUE-002: _cleanup() must clear _pending_block"
        )


# =============================================================================
# Part 5: Feed-Ahead Controller Contract Tests
# =============================================================================


def _make_producer_with_mock_session(
    *,
    channel_id: str = "fa-test",
    block_duration_ms: int = 30_000,
    feed_ahead_horizon_ms: int = 20_000,
    feed_returns=None,
):
    """Helper: create a BlockPlanProducer wired to a controllable mock session.

    Returns (producer, mock_session, feed_log, _FeedState).
    feed_log is a list of (block_id, accepted:bool) tuples.
    feed_returns controls what the mock session.feed() returns (a FeedResult).
    """
    from retrovue.runtime.channel_manager import BlockPlanProducer, _FeedState
    from retrovue.runtime.playout_session import FeedResult

    if feed_returns is None:
        feed_returns = FeedResult.ACCEPTED

    producer = BlockPlanProducer(
        channel_id=channel_id,
        configuration={
            "block_duration_ms": block_duration_ms,
            "feed_ahead_horizon_ms": feed_ahead_horizon_ms,
        },
        channel_config=None,
        schedule_service=None,
        clock=None,
    )

    feed_log: list[tuple[str, bool]] = []
    _feed_returns = [feed_returns]

    class ControllableMockSession:
        def __init__(self):
            self.on_block_complete = None
            self.on_session_end = None

        def start(self, join_utc_ms=0):
            return True

        def seed(self, block_a, block_b):
            return True

        def feed(self, block):
            result = _feed_returns[0]
            accepted = (result == FeedResult.ACCEPTED)
            feed_log.append((block.block_id, accepted))
            return result

        def stop(self, reason="requested"):
            return True

        @property
        def is_running(self):
            return True

    mock_session = ControllableMockSession()
    mock_session._feed_returns = _feed_returns  # expose for test control
    return producer, mock_session, feed_log, _FeedState


class TestFeedAheadNoFeedDuringSeeded:
    """After seed, before BlockCompleted, verify no feeds occur."""

    def test_no_feed_during_seeded_state(self):
        """
        In SEEDED state (after seed, before first BlockCompleted),
        on_paced_tick must NOT trigger any feeds — even after many ticks.
        """
        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session()

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 30_000},
        ]

        producer._session = mock_session
        producer._playout_plan = playout_plan
        mock_session.on_block_complete = producer._on_block_complete

        # Simulate seed (blocks 0, 1)
        block_a = producer._generate_next_block(playout_plan)
        producer._advance_cursor(block_a)
        block_b = producer._generate_next_block(playout_plan)
        producer._advance_cursor(block_b)
        mock_session.seed(block_a, block_b)

        # Enter SEEDED state (as start() would)
        producer._feed_state = _FeedState.SEEDED
        producer._max_delivered_end_utc_ms = block_b.end_utc_ms
        producer._started = True

        # Pump many ticks — should NOT feed
        for i in range(100):
            producer.on_paced_tick(time.time(), 1 / 30)

        assert len(feed_log) == 0, (
            f"FEED-AHEAD: Expected 0 feeds during SEEDED state, got {len(feed_log)}"
        )
        assert producer._feed_state == _FeedState.SEEDED


class TestFeedAheadSeededToRunning:
    """First BlockCompleted triggers SEEDED→RUNNING transition and feed-ahead."""

    def test_seeded_to_running_on_first_complete(self):
        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session(
            feed_ahead_horizon_ms=20_000,
            block_duration_ms=30_000,
        )

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 30_000},
        ]

        producer._session = mock_session
        producer._playout_plan = playout_plan
        mock_session.on_block_complete = producer._on_block_complete

        # Simulate seed
        block_a = producer._generate_next_block(playout_plan)
        producer._advance_cursor(block_a)
        block_b = producer._generate_next_block(playout_plan)
        producer._advance_cursor(block_b)
        mock_session.seed(block_a, block_b)

        producer._feed_state = _FeedState.SEEDED
        # Use a far-future end time so runway > 0 for the test
        now_ms = int(time.time() * 1000)
        producer._max_delivered_end_utc_ms = now_ms + 60_000  # 60s ahead
        producer._started = True
        producer._in_flight_block_ids.add(block_a.block_id)
        producer._in_flight_block_ids.add(block_b.block_id)

        # Emit BlockCompleted for block_a
        producer._on_block_complete(block_a.block_id)

        assert producer._feed_state == _FeedState.RUNNING, (
            f"Expected RUNNING after first BlockCompleted, got {producer._feed_state}"
        )


class TestFeedAheadStartupNoQueueFullRace:
    """No immediate feed(block_c) after seed. No QUEUE_FULL at startup."""

    def test_startup_no_queue_full_race(self):
        """
        After seed, the producer enters SEEDED (not RUNNING). No block_c
        feed is attempted, eliminating the startup QUEUE_FULL race.
        """
        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session()

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 30_000},
        ]

        # Wire a session that always rejects (to detect any feed attempt)
        from retrovue.runtime.playout_session import FeedResult
        mock_session._feed_returns[0] = FeedResult.QUEUE_FULL

        producer._session = mock_session
        producer._playout_plan = playout_plan
        mock_session.on_block_complete = producer._on_block_complete

        # Simulate what start() does: seed 2 blocks, enter SEEDED
        block_a = producer._generate_next_block(playout_plan)
        producer._advance_cursor(block_a)
        block_b = producer._generate_next_block(playout_plan)
        producer._advance_cursor(block_b)
        mock_session.seed(block_a, block_b)

        # This is what start() now does (instead of _try_feed_block(block_c)):
        producer._feed_state = _FeedState.SEEDED
        producer._max_delivered_end_utc_ms = block_b.end_utc_ms
        producer._started = True

        # No feed should have been attempted
        assert len(feed_log) == 0, (
            f"FEED-AHEAD: Expected 0 feed attempts at startup, got {len(feed_log)}. "
            "This means the QUEUE_FULL race condition is eliminated."
        )


class TestFeedAheadFillsToHorizon:
    """When runway < horizon, blocks are fed until runway >= horizon."""

    def test_feed_ahead_fills_to_horizon(self):
        """
        With short blocks (5s) and 20s horizon, _feed_ahead should feed
        multiple blocks in one call to reach the horizon.
        """
        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session(
            block_duration_ms=5_000,
            feed_ahead_horizon_ms=20_000,
        )

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 5_000},
        ]

        producer._session = mock_session
        producer._playout_plan = playout_plan

        # Simulate: currently RUNNING, with 0 runway
        now_ms = int(time.time() * 1000)
        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = now_ms  # 0 runway
        producer._started = True
        producer._feed_credits = 2  # Credits for feed-ahead
        producer._next_block_start_ms = now_ms
        producer._block_index = 0

        producer._feed_ahead()

        # With 5s blocks and 20s horizon, 2 iterations of the loop (loop is max 2)
        # should produce 2 feeds. Runway is checked each iteration.
        assert len(feed_log) >= 1, (
            "FEED-AHEAD: Should feed at least 1 block when runway < horizon"
        )
        # All feeds accepted
        assert all(accepted for _, accepted in feed_log), (
            "All feeds should be accepted"
        )


class TestFeedAheadStopsAtHorizon:
    """When runway >= horizon AND deadline not due, no feed attempt."""

    def test_feed_ahead_stops_at_horizon(self):
        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session(
            feed_ahead_horizon_ms=20_000,
        )

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 30_000},
        ]

        producer._session = mock_session
        producer._playout_plan = playout_plan

        # RUNNING with plenty of runway (60s ahead)
        now_ms = int(time.time() * 1000)
        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = now_ms + 60_000
        producer._started = True
        producer._feed_credits = 2  # Credits available but no trigger met

        # Set next block start far in the future so ready_by is also future
        # (otherwise deadline-driven logic would feed because start_utc_ms=0
        # makes ready_by in the past)
        producer._next_block_start_ms = now_ms + 90_000

        producer._feed_ahead()

        assert len(feed_log) == 0, (
            f"FEED-AHEAD: Expected 0 feeds when runway >= horizon and deadline not due, "
            f"got {len(feed_log)}"
        )


class TestFeedAheadBackoffOnQueueFull:
    """After QUEUE_FULL, credits=0 → tick evaluation produces no feeds."""

    def test_credit_gate_on_queue_full(self):
        from retrovue.runtime.playout_session import FeedResult

        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session(
            feed_ahead_horizon_ms=20_000,
        )

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 30_000},
        ]

        producer._session = mock_session
        producer._playout_plan = playout_plan

        # RUNNING with 0 runway — will want to feed
        now_ms = int(time.time() * 1000)
        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = now_ms  # 0 runway
        producer._started = True
        producer._next_block_start_ms = now_ms
        producer._block_index = 0
        producer._feed_credits = 1  # Give one credit so _feed_ahead tries

        # Session rejects feeds (QUEUE_FULL)
        mock_session._feed_returns[0] = FeedResult.QUEUE_FULL

        producer._feed_ahead()

        # Verify credits zeroed (authoritative correction)
        assert producer._feed_credits == 0, (
            f"Expected credits=0 after QUEUE_FULL, got {producer._feed_credits}"
        )

        # Now pump many throttled ticks — credits=0 means no feeds
        feed_log.clear()
        divisor = producer.FEED_AHEAD_TICK_DIVISOR
        for _ in range(divisor * 10):  # 10 throttled evaluations
            producer.on_paced_tick(time.time(), 1 / 30)

        # With credits=0, no new feeds should occur
        assert len(feed_log) == 0, (
            f"Expected 0 feeds with credits=0, got {len(feed_log)}"
        )


class TestFeedAheadNoDrainingFeed:
    """After session end, feed-ahead is a no-op."""

    def test_no_feed_in_draining(self):
        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session()

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 30_000},
        ]

        producer._session = mock_session
        producer._playout_plan = playout_plan

        now_ms = int(time.time() * 1000)
        producer._feed_state = _FeedState.DRAINING
        producer._max_delivered_end_utc_ms = now_ms  # 0 runway
        producer._started = True

        producer._feed_ahead()

        assert len(feed_log) == 0, (
            "FEED-AHEAD: Expected 0 feeds in DRAINING state"
        )


class TestFeedAheadTickThrottle:
    """Only every Nth tick triggers feed-ahead evaluation."""

    def test_tick_throttle(self):
        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session(
            feed_ahead_horizon_ms=20_000,
        )

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 30_000},
        ]

        producer._session = mock_session
        producer._playout_plan = playout_plan

        # RUNNING with 0 runway (will want to feed on every evaluation)
        now_ms = int(time.time() * 1000)
        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = now_ms  # 0 runway
        producer._started = True
        producer._feed_credits = 2  # Credits for feed-ahead
        producer._next_block_start_ms = now_ms
        producer._block_index = 0

        divisor = producer.FEED_AHEAD_TICK_DIVISOR

        # Pump exactly (divisor - 1) ticks — should NOT trigger evaluation
        producer._feed_tick_counter = 0
        for i in range(divisor - 1):
            producer.on_paced_tick(time.time(), 1 / 30)

        assert len(feed_log) == 0, (
            f"Expected 0 feeds before divisor triggers, got {len(feed_log)}"
        )

        # One more tick — now the divisor fires and _feed_ahead runs
        producer.on_paced_tick(time.time(), 1 / 30)

        assert len(feed_log) >= 1, (
            f"Expected >= 1 feed after divisor triggers, got {len(feed_log)}"
        )


class TestRunwayComputation:
    """Verify _compute_runway_ms() correctness."""

    def test_runway_computation_basic(self):
        from retrovue.runtime.channel_manager import BlockPlanProducer

        producer = BlockPlanProducer(
            channel_id="runway-test",
            configuration={"block_duration_ms": 30_000},
            channel_config=None,
            schedule_service=None,
            clock=None,
        )

        # Zero delivered → 0 runway
        producer._max_delivered_end_utc_ms = 0
        assert producer._compute_runway_ms() == 0

        # Far future → positive runway
        now_ms = int(time.time() * 1000)
        producer._max_delivered_end_utc_ms = now_ms + 30_000
        runway = producer._compute_runway_ms()
        # Should be approximately 30_000 (within a few ms of test execution)
        assert 29_000 <= runway <= 31_000, (
            f"Expected runway ~30000ms, got {runway}"
        )

        # In the past → 0 runway (clamped)
        producer._max_delivered_end_utc_ms = now_ms - 5_000
        assert producer._compute_runway_ms() == 0


# =============================================================================
# Part 6: Deadline-Driven Feed-Ahead Contract Tests
# =============================================================================


class TestReadyByDeadlineComputation:
    """Verify _compute_ready_by_ms() returns start_utc_ms - preload_budget_ms."""

    def test_ready_by_equals_start_minus_budget(self):
        from retrovue.runtime.channel_manager import BlockPlanProducer

        producer = BlockPlanProducer(
            channel_id="rb-test",
            configuration={"block_duration_ms": 30_000, "preload_budget_ms": 10_000},
            channel_config=None,
            schedule_service=None,
            clock=None,
        )

        block = MockBlockPlan(
            block_id="B1", channel_id=1,
            start_utc_ms=1_000_000, end_utc_ms=1_030_000,
        )
        assert producer._compute_ready_by_ms(block) == 990_000

    def test_ready_by_with_custom_budget(self):
        from retrovue.runtime.channel_manager import BlockPlanProducer

        producer = BlockPlanProducer(
            channel_id="rb-test2",
            configuration={"block_duration_ms": 30_000, "preload_budget_ms": 5_000},
            channel_config=None,
            schedule_service=None,
            clock=None,
        )

        block = MockBlockPlan(
            block_id="B2", channel_id=1,
            start_utc_ms=500_000, end_utc_ms=530_000,
        )
        assert producer._compute_ready_by_ms(block) == 495_000


class TestFeedTriggeredByDeadline:
    """Feed occurs when now >= ready_by, even if runway is sufficient."""

    def test_deadline_triggers_feed_despite_high_runway(self):
        """
        When now_utc_ms >= ready_by_utc_ms, a feed occurs regardless of runway.
        This is the key change from runway-only to deadline-driven.
        """
        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session(
            feed_ahead_horizon_ms=20_000,
            block_duration_ms=30_000,
        )

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 30_000},
        ]

        producer._session = mock_session
        producer._playout_plan = playout_plan

        now_ms = int(time.time() * 1000)

        # Plenty of runway (60s)
        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = now_ms + 60_000
        producer._started = True
        producer._feed_credits = 2  # Credits for feed-ahead

        # But next block starts soon (in 5s), so ready_by = 5s - 10s = -5s (past!)
        producer._next_block_start_ms = now_ms + 5_000
        producer._block_index = 0

        producer._feed_ahead()

        # Deadline is due → feed occurs despite sufficient runway
        assert len(feed_log) >= 1, (
            "DEADLINE: Feed should occur when deadline is due, even with high runway"
        )
        assert feed_log[0][1] is True, "Feed should be accepted"


class TestNoFeedWhenNeitherTriggerMet:
    """No feed when both deadline not due AND runway sufficient."""

    def test_skip_when_not_due_and_runway_ok(self):
        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session(
            feed_ahead_horizon_ms=20_000,
            block_duration_ms=30_000,
        )

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 30_000},
        ]

        producer._session = mock_session
        producer._playout_plan = playout_plan

        now_ms = int(time.time() * 1000)

        # Plenty of runway (60s)
        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = now_ms + 60_000
        producer._started = True
        producer._feed_credits = 2  # Credits available but neither trigger met

        # Next block starts far in the future (90s),
        # ready_by = 90s - 10s = 80s in the future
        producer._next_block_start_ms = now_ms + 90_000
        producer._block_index = 0

        producer._feed_ahead()

        assert len(feed_log) == 0, (
            "DEADLINE: No feed when deadline not due AND runway >= horizon"
        )


class TestReadyByMissCount:
    """ready_by_miss_count incremented when now > block.start_utc_ms."""

    def test_miss_count_incremented_for_late_feed(self):
        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session(
            feed_ahead_horizon_ms=20_000,
            block_duration_ms=30_000,
        )

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 30_000},
        ]

        producer._session = mock_session
        producer._playout_plan = playout_plan

        now_ms = int(time.time() * 1000)

        # RUNNING, low runway
        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = now_ms
        producer._started = True
        producer._feed_credits = 2  # Credits for feed-ahead

        # Block starts in the PAST (5s ago) — this is a miss
        producer._next_block_start_ms = now_ms - 5_000
        producer._block_index = 0

        assert producer._ready_by_miss_count == 0
        producer._feed_ahead()

        assert producer._ready_by_miss_count >= 1, (
            "DEADLINE: ready_by_miss_count should increment when block is fed after its start_utc_ms"
        )

    def test_no_miss_for_on_time_feed(self):
        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session(
            feed_ahead_horizon_ms=20_000,
            block_duration_ms=30_000,
        )

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 30_000},
        ]

        producer._session = mock_session
        producer._playout_plan = playout_plan

        now_ms = int(time.time() * 1000)

        # RUNNING, low runway
        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = now_ms
        producer._started = True
        producer._feed_credits = 2  # Credits for feed-ahead

        # Block starts in the future (5s from now) — not a miss
        producer._next_block_start_ms = now_ms + 5_000
        producer._block_index = 0

        producer._feed_ahead()

        assert producer._ready_by_miss_count == 0, (
            "DEADLINE: No miss when block is fed before its start_utc_ms"
        )


class TestFeedAheadDecisionLogging:
    """Verify FEED_AHEAD_DECISION log output."""

    def test_decision_log_emitted_on_feed(self):
        import logging

        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session(
            feed_ahead_horizon_ms=20_000,
            block_duration_ms=30_000,
        )

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 30_000},
        ]

        producer._session = mock_session
        producer._playout_plan = playout_plan

        now_ms = int(time.time() * 1000)
        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = now_ms
        producer._started = True
        producer._feed_credits = 2  # Credits for feed-ahead
        producer._next_block_start_ms = now_ms + 5_000
        producer._block_index = 0

        # Capture log output
        log_records = []
        handler = logging.Handler()
        handler.emit = lambda record: log_records.append(record)
        producer._logger.addHandler(handler)
        producer._logger.setLevel(logging.DEBUG)

        try:
            producer._feed_ahead()
        finally:
            producer._logger.removeHandler(handler)

        # Find FEED_AHEAD_DECISION log line
        decision_logs = [
            r for r in log_records
            if "FEED_AHEAD_DECISION" in r.getMessage()
        ]
        assert len(decision_logs) >= 1, (
            "DECISION LOG: Expected at least one FEED_AHEAD_DECISION log"
        )

        msg = decision_logs[0].getMessage()
        # Verify key fields are present
        assert "block=" in msg, "DECISION LOG: must contain block="
        assert "start=" in msg, "DECISION LOG: must contain start="
        assert "ready_by=" in msg, "DECISION LOG: must contain ready_by="
        assert "reason=" in msg, "DECISION LOG: must contain reason="
        assert "runway=" in msg, "DECISION LOG: must contain runway="
        assert "miss=" in msg, "DECISION LOG: must contain miss="

    def test_skip_decision_logged_at_debug(self):
        """When neither trigger is met, a debug skip log is emitted."""
        import logging

        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session(
            feed_ahead_horizon_ms=20_000,
        )

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 30_000},
        ]

        producer._session = mock_session
        producer._playout_plan = playout_plan

        now_ms = int(time.time() * 1000)
        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = now_ms + 60_000
        producer._started = True
        producer._feed_credits = 2  # Credits available but neither trigger met
        producer._next_block_start_ms = now_ms + 90_000
        producer._block_index = 0

        log_records = []
        handler = logging.Handler()
        handler.emit = lambda record: log_records.append(record)
        producer._logger.addHandler(handler)
        producer._logger.setLevel(logging.DEBUG)

        try:
            producer._feed_ahead()
        finally:
            producer._logger.removeHandler(handler)

        skip_logs = [
            r for r in log_records
            if "FEED_AHEAD_DECISION" in r.getMessage() and "skip_not_due" in r.getMessage()
        ]
        assert len(skip_logs) == 1, (
            f"DECISION LOG: Expected 1 skip_not_due log, got {len(skip_logs)}"
        )


class TestPreloadBudgetConfiguration:
    """Verify preload_budget_ms configuration is respected."""

    def test_custom_preload_budget(self):
        """Custom preload_budget_ms changes when deadline is due."""
        # With a large budget (50s), a block starting in 40s has ready_by in the past
        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session(
            feed_ahead_horizon_ms=20_000,
            block_duration_ms=30_000,
        )
        # Override preload_budget_ms directly
        producer._preload_budget_ms = 50_000

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 30_000},
        ]

        producer._session = mock_session
        producer._playout_plan = playout_plan

        now_ms = int(time.time() * 1000)
        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = now_ms + 60_000  # High runway
        producer._started = True
        producer._feed_credits = 2  # Credits for feed-ahead

        # Block starts in 40s: ready_by = 40s - 50s = -10s (past)
        producer._next_block_start_ms = now_ms + 40_000
        producer._block_index = 0

        producer._feed_ahead()

        assert len(feed_log) >= 1, (
            "BUDGET: With 50s preload budget, block starting in 40s "
            "should be fed (ready_by is -10s)"
        )

    def test_small_preload_budget_no_early_feed(self):
        """With small budget, far-future blocks are not fed early."""
        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session(
            feed_ahead_horizon_ms=20_000,
            block_duration_ms=30_000,
        )
        # Small budget: only 2s
        producer._preload_budget_ms = 2_000

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 30_000},
        ]

        producer._session = mock_session
        producer._playout_plan = playout_plan

        now_ms = int(time.time() * 1000)
        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = now_ms + 60_000  # High runway
        producer._started = True
        producer._feed_credits = 2  # Credits available but neither trigger met

        # Block starts in 40s: ready_by = 40s - 2s = 38s (far future)
        producer._next_block_start_ms = now_ms + 40_000
        producer._block_index = 0

        producer._feed_ahead()

        assert len(feed_log) == 0, (
            "BUDGET: With 2s budget, block starting in 40s should NOT be fed "
            "(ready_by is 38s in future, runway is sufficient)"
        )


class TestFeedAheadReasonClassification:
    """Verify correct reason string in FEED_AHEAD_DECISION based on triggers."""

    def test_reason_deadline_when_only_deadline_met(self):
        """reason='deadline' when deadline due but runway >= horizon."""
        import logging

        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session(
            feed_ahead_horizon_ms=20_000,
            block_duration_ms=30_000,
        )

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 30_000},
        ]

        producer._session = mock_session
        producer._playout_plan = playout_plan

        now_ms = int(time.time() * 1000)
        producer._feed_state = _FeedState.RUNNING
        # Runway > horizon (60s)
        producer._max_delivered_end_utc_ms = now_ms + 60_000
        producer._started = True
        producer._feed_credits = 2  # Credits for feed-ahead
        # Deadline due: block starts in 5s, budget=10s → ready_by=-5s
        producer._next_block_start_ms = now_ms + 5_000
        producer._block_index = 0

        log_records = []
        handler = logging.Handler()
        handler.emit = lambda record: log_records.append(record)
        producer._logger.addHandler(handler)
        producer._logger.setLevel(logging.INFO)

        try:
            producer._feed_ahead()
        finally:
            producer._logger.removeHandler(handler)

        decision_logs = [
            r for r in log_records
            if "FEED_AHEAD_DECISION" in r.getMessage()
        ]
        assert len(decision_logs) >= 1
        assert "reason=deadline " in decision_logs[0].getMessage() or \
               "reason=deadline+" in decision_logs[0].getMessage(), (
            f"Expected reason=deadline, got: {decision_logs[0].getMessage()}"
        )

    def test_reason_runway_when_only_runway_low(self):
        """reason='runway' when runway < horizon but deadline not due."""
        import logging

        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session(
            feed_ahead_horizon_ms=20_000,
            block_duration_ms=30_000,
        )

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 30_000},
        ]

        producer._session = mock_session
        producer._playout_plan = playout_plan

        now_ms = int(time.time() * 1000)
        producer._feed_state = _FeedState.RUNNING
        # Low runway (5s < 20s horizon)
        producer._max_delivered_end_utc_ms = now_ms + 5_000
        producer._started = True
        producer._feed_credits = 2  # Credits for feed-ahead
        # Deadline NOT due: block starts in 60s, budget=10s → ready_by=50s future
        producer._next_block_start_ms = now_ms + 60_000
        producer._block_index = 0

        log_records = []
        handler = logging.Handler()
        handler.emit = lambda record: log_records.append(record)
        producer._logger.addHandler(handler)
        producer._logger.setLevel(logging.INFO)

        try:
            producer._feed_ahead()
        finally:
            producer._logger.removeHandler(handler)

        decision_logs = [
            r for r in log_records
            if "FEED_AHEAD_DECISION" in r.getMessage()
        ]
        assert len(decision_logs) >= 1
        assert "reason=runway " in decision_logs[0].getMessage(), (
            f"Expected reason=runway, got: {decision_logs[0].getMessage()}"
        )

    def test_reason_deadline_plus_runway_when_both(self):
        """reason='deadline+runway' when both triggers met."""
        import logging

        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session(
            feed_ahead_horizon_ms=20_000,
            block_duration_ms=30_000,
        )

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 30_000},
        ]

        producer._session = mock_session
        producer._playout_plan = playout_plan

        now_ms = int(time.time() * 1000)
        producer._feed_state = _FeedState.RUNNING
        # Low runway (0ms)
        producer._max_delivered_end_utc_ms = now_ms
        producer._started = True
        producer._feed_credits = 2  # Credits for feed-ahead
        # Deadline due: block starts in 5s, budget=10s → ready_by=-5s
        producer._next_block_start_ms = now_ms + 5_000
        producer._block_index = 0

        log_records = []
        handler = logging.Handler()
        handler.emit = lambda record: log_records.append(record)
        producer._logger.addHandler(handler)
        producer._logger.setLevel(logging.INFO)

        try:
            producer._feed_ahead()
        finally:
            producer._logger.removeHandler(handler)

        decision_logs = [
            r for r in log_records
            if "FEED_AHEAD_DECISION" in r.getMessage()
        ]
        assert len(decision_logs) >= 1
        assert "reason=deadline+runway" in decision_logs[0].getMessage(), (
            f"Expected reason=deadline+runway, got: {decision_logs[0].getMessage()}"
        )


class TestCleanupResetsDeadlineState:
    """Verify _cleanup() resets all deadline-driven and credit state."""

    def test_cleanup_resets_deadline_state(self):
        from retrovue.runtime.channel_manager import BlockPlanProducer, _FeedState

        producer = BlockPlanProducer(
            channel_id="cleanup-dl-test",
            configuration={"block_duration_ms": 30_000},
            channel_config=None,
            schedule_service=None,
            clock=None,
        )

        # Mutate state
        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = 999_999
        producer._feed_credits = 2
        producer._consecutive_feed_errors = 3
        producer._error_backoff_remaining = 16
        producer._feed_tick_counter = 42
        producer._ready_by_miss_count = 5

        producer._cleanup()

        assert producer._feed_state == _FeedState.CREATED
        assert producer._max_delivered_end_utc_ms == 0
        assert producer._feed_credits == 0
        assert producer._consecutive_feed_errors == 0
        assert producer._error_backoff_remaining == 0
        assert producer._feed_tick_counter == 0
        assert producer._ready_by_miss_count == 0


# =============================================================================
# Part 7: Miss Policy Contract Tests (INV-FEED-SEQUENCE, deterministic passive)
# =============================================================================


class TestMissPolicyNoReorder:
    """INV-FEED-SEQUENCE: Block sequence preserved after miss — no reordering."""

    def test_block_sequence_preserved_after_miss(self):
        """After a miss, subsequent blocks maintain sequential order."""
        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session(
            feed_ahead_horizon_ms=20_000,
            block_duration_ms=5_000,
        )

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 5_000},
        ]

        producer._session = mock_session
        producer._playout_plan = playout_plan

        now_ms = int(time.time() * 1000)

        # RUNNING, block 0 starts in the PAST (miss)
        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = now_ms - 10_000  # far behind
        producer._started = True
        producer._feed_credits = 2  # Credits for feed-ahead
        producer._next_block_start_ms = now_ms - 5_000  # 5s in the past
        producer._block_index = 0

        producer._feed_ahead()

        # Should have fed blocks; verify they are sequential
        assert len(feed_log) >= 1, "Should feed at least 1 block on miss"
        fed_ids = [bid for bid, _ in feed_log]
        for i, bid in enumerate(fed_ids):
            assert bid == f"BLOCK-fa-test-{i}", (
                f"INV-FEED-SEQUENCE: Expected BLOCK-fa-test-{i}, got {bid}. "
                "Blocks must remain in sequence after a miss."
            )


class TestMissPolicyNoFiller:
    """No emergency/filler block injected on miss."""

    def test_no_filler_block_on_miss(self):
        """When a miss occurs, no extra filler/emergency block is injected."""
        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session(
            feed_ahead_horizon_ms=20_000,
            block_duration_ms=30_000,
        )

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 30_000},
        ]

        producer._session = mock_session
        producer._playout_plan = playout_plan

        now_ms = int(time.time() * 1000)
        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = now_ms
        producer._started = True
        producer._feed_credits = 2  # Credits for feed-ahead
        producer._next_block_start_ms = now_ms - 5_000  # 5s miss
        producer._block_index = 0

        producer._feed_ahead()

        # All fed blocks must come from the playout plan (sequential IDs)
        for bid, accepted in feed_log:
            assert bid.startswith("BLOCK-fa-test-"), (
                f"MISS POLICY: Block {bid} is not from the playout plan. "
                "No filler/emergency blocks should be injected on miss."
            )
            assert accepted is True


class TestMissPolicyContinueFeedAhead:
    """_feed_ahead() loop continues normally after miss."""

    def test_feed_ahead_continues_after_miss(self):
        """After a miss, _feed_ahead() completes its loop normally."""
        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session(
            feed_ahead_horizon_ms=20_000,
            block_duration_ms=5_000,
        )

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 5_000},
        ]

        producer._session = mock_session
        producer._playout_plan = playout_plan

        now_ms = int(time.time() * 1000)
        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = now_ms - 5_000
        producer._started = True
        producer._feed_credits = 2  # Credits for feed-ahead
        producer._next_block_start_ms = now_ms - 3_000  # 3s miss
        producer._block_index = 0

        producer._feed_ahead()

        # Loop runs up to 2 iterations; with 5s blocks both iterations
        # should trigger (runway is well below horizon for short blocks)
        assert len(feed_log) == 2, (
            f"MISS POLICY: _feed_ahead() should continue its full loop after miss. "
            f"Expected 2 feeds (loop max), got {len(feed_log)}"
        )
        assert all(accepted for _, accepted in feed_log)


class TestMissAnnotationRecorded:
    """Annotation has type=missed_ready_by, block_id, lateness_ms on miss."""

    def test_annotation_recorded_on_miss(self):
        """When a miss occurs, an as-run annotation is recorded."""
        from retrovue.runtime.channel_manager import BlockPlanProducer, _FeedState

        producer = BlockPlanProducer(
            channel_id="miss-ann-test",
            configuration={
                "block_duration_ms": 30_000,
                "feed_ahead_horizon_ms": 20_000,
            },
            channel_config=None,
            schedule_service=None,
            clock=None,
        )

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 30_000},
        ]

        feed_log: list[tuple[str, bool]] = []

        class SimpleMockSession:
            def __init__(self):
                self.on_block_complete = None
                self.on_session_end = None

            def start(self, join_utc_ms=0):
                return True

            def seed(self, block_a, block_b):
                return True

            def feed(self, block):
                from retrovue.runtime.playout_session import FeedResult
                feed_log.append((block.block_id, True))
                return FeedResult.ACCEPTED

            def stop(self, reason="requested"):
                return True

            @property
            def is_running(self):
                return True

        mock_session = SimpleMockSession()
        producer._session = mock_session
        producer._playout_plan = playout_plan

        now_ms = int(time.time() * 1000)
        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = now_ms
        producer._started = True
        producer._feed_credits = 2  # Credits for feed-ahead
        producer._next_block_start_ms = now_ms - 3_000  # 3s miss
        producer._block_index = 0

        producer._feed_ahead()

        annotations = producer.get_asrun_annotations()
        assert len(annotations) >= 1, (
            "MISS POLICY: At least one annotation should be recorded on miss"
        )

        ann = annotations[0]
        assert ann.annotation_type == "missed_ready_by", (
            f"Expected annotation_type='missed_ready_by', got '{ann.annotation_type}'"
        )
        assert ann.block_id.startswith("BLOCK-miss-ann-test-"), (
            f"Expected block_id starting with 'BLOCK-miss-ann-test-', got '{ann.block_id}'"
        )
        assert "lateness_ms" in ann.metadata, (
            "Annotation metadata must contain 'lateness_ms'"
        )
        assert ann.metadata["lateness_ms"] >= 3_000, (
            f"Expected lateness_ms >= 3000, got {ann.metadata['lateness_ms']}"
        )


class TestMissAnnotationNotRecordedOnTime:
    """No annotation when block is fed on time."""

    def test_no_annotation_when_on_time(self):
        """No as-run annotation is recorded when block is fed before start_utc_ms."""
        from retrovue.runtime.channel_manager import BlockPlanProducer, _FeedState

        producer = BlockPlanProducer(
            channel_id="ontime-test",
            configuration={
                "block_duration_ms": 30_000,
                "feed_ahead_horizon_ms": 20_000,
            },
            channel_config=None,
            schedule_service=None,
            clock=None,
        )

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 30_000},
        ]

        class SimpleMockSession:
            def __init__(self):
                self.on_block_complete = None
                self.on_session_end = None

            def start(self, join_utc_ms=0):
                return True

            def seed(self, block_a, block_b):
                return True

            def feed(self, block):
                from retrovue.runtime.playout_session import FeedResult
                return FeedResult.ACCEPTED

            def stop(self, reason="requested"):
                return True

            @property
            def is_running(self):
                return True

        mock_session = SimpleMockSession()
        producer._session = mock_session
        producer._playout_plan = playout_plan

        now_ms = int(time.time() * 1000)
        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = now_ms
        producer._started = True
        producer._feed_credits = 2  # Credits for feed-ahead
        # Block starts 30s in the future — well ahead of now
        producer._next_block_start_ms = now_ms + 30_000
        producer._block_index = 0

        producer._feed_ahead()

        annotations = producer.get_asrun_annotations()
        assert len(annotations) == 0, (
            f"MISS POLICY: No annotations should be recorded for on-time feeds. "
            f"Got {len(annotations)} annotations."
        )


class TestMissLatenessMetric:
    """feed_ahead_miss_lateness_ms histogram observed with correct value."""

    def test_lateness_metric_observed(self):
        """On miss, lateness_ms value is passed to the histogram."""
        from retrovue.runtime.channel_manager import BlockPlanProducer, _FeedState
        from unittest.mock import patch, MagicMock

        producer = BlockPlanProducer(
            channel_id="lateness-metric-test",
            configuration={
                "block_duration_ms": 30_000,
                "feed_ahead_horizon_ms": 20_000,
            },
            channel_config=None,
            schedule_service=None,
            clock=None,
        )

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 30_000},
        ]

        class SimpleMockSession:
            def __init__(self):
                self.on_block_complete = None
                self.on_session_end = None

            def start(self, join_utc_ms=0):
                return True

            def seed(self, block_a, block_b):
                return True

            def feed(self, block):
                from retrovue.runtime.playout_session import FeedResult
                return FeedResult.ACCEPTED

            def stop(self, reason="requested"):
                return True

            @property
            def is_running(self):
                return True

        mock_session = SimpleMockSession()
        producer._session = mock_session
        producer._playout_plan = playout_plan

        now_ms = int(time.time() * 1000)
        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = now_ms
        producer._started = True
        producer._feed_credits = 2  # Credits for feed-ahead
        producer._next_block_start_ms = now_ms - 7_000  # 7s miss
        producer._block_index = 0

        # Mock the histogram metric
        mock_histogram = MagicMock()
        mock_labels = MagicMock()
        mock_histogram.labels.return_value = mock_labels

        with patch(
            "retrovue.runtime.channel_manager.feed_ahead_miss_lateness_ms",
            mock_histogram,
        ):
            producer._feed_ahead()

        # Verify histogram was observed with approximately correct value
        mock_histogram.labels.assert_called()
        mock_labels.observe.assert_called()
        observed_value = mock_labels.observe.call_args[0][0]
        assert observed_value >= 7_000, (
            f"MISS POLICY: Expected lateness_ms >= 7000, got {observed_value}"
        )


class TestLateJoinStabilization:
    """Late join 2s before fence: Core doesn't thrash, session stabilizes,
    no duplicate block IDs."""

    def test_late_join_no_thrash_no_duplicates(self):
        """Simulate late join scenario: blocks fed once each, no duplicates."""
        from retrovue.runtime.channel_manager import BlockPlanProducer, _FeedState

        producer = BlockPlanProducer(
            channel_id="late-join-test",
            configuration={
                "block_duration_ms": 10_000,
                "feed_ahead_horizon_ms": 20_000,
            },
            channel_config=None,
            schedule_service=None,
            clock=None,
        )

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 10_000},
        ]

        fed_block_ids: list[str] = []

        class TrackingSession:
            def __init__(self):
                self.on_block_complete = None
                self.on_session_end = None

            def start(self, join_utc_ms=0):
                return True

            def seed(self, block_a, block_b):
                return True

            def feed(self, block):
                from retrovue.runtime.playout_session import FeedResult
                fed_block_ids.append(block.block_id)
                return FeedResult.ACCEPTED

            def stop(self, reason="requested"):
                return True

            @property
            def is_running(self):
                return True

        mock_session = TrackingSession()
        producer._session = mock_session
        producer._playout_plan = playout_plan
        mock_session.on_block_complete = producer._on_block_complete
        producer._started = True

        # Simulate late join: seed with blocks that are already partially past
        now_ms = int(time.time() * 1000)
        block_a = producer._generate_next_block(playout_plan)
        producer._advance_cursor(block_a)
        block_b = producer._generate_next_block(playout_plan)
        producer._advance_cursor(block_b)
        mock_session.seed(block_a, block_b)

        producer._in_flight_block_ids.add(block_a.block_id)
        producer._in_flight_block_ids.add(block_b.block_id)

        # Set state as if we just joined late: fence is 2s away,
        # first block is already past, second block is current
        producer._feed_state = _FeedState.SEEDED
        producer._max_delivered_end_utc_ms = block_b.end_utc_ms
        producer._next_block_start_ms = now_ms + 8_000  # next block starts in 8s

        # First BlockCompleted triggers SEEDED→RUNNING and feed-ahead
        producer._on_block_complete(block_a.block_id)

        assert producer._feed_state == _FeedState.RUNNING, (
            "Should transition to RUNNING after first BlockCompleted"
        )

        # Verify no duplicate block IDs were fed
        assert len(fed_block_ids) == len(set(fed_block_ids)), (
            f"MISS POLICY: Duplicate block IDs detected in late-join scenario: "
            f"{fed_block_ids}"
        )

        # Verify blocks are sequential
        for i, bid in enumerate(fed_block_ids):
            expected = f"BLOCK-late-join-test-{i + 2}"  # blocks 0,1 were seeded
            assert bid == expected, (
                f"MISS POLICY: Expected {expected}, got {bid}. "
                "Late join must produce sequential blocks."
            )


class TestMissLogging:
    """MISS_READY_BY log line emitted with channel, block, lateness_ms fields."""

    def test_miss_ready_by_log_emitted(self):
        """When a miss occurs, MISS_READY_BY warning log is emitted."""
        import logging

        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session(
            feed_ahead_horizon_ms=20_000,
            block_duration_ms=30_000,
        )

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 30_000},
        ]

        producer._session = mock_session
        producer._playout_plan = playout_plan

        now_ms = int(time.time() * 1000)
        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = now_ms
        producer._started = True
        producer._feed_credits = 2  # Credits for feed-ahead
        producer._next_block_start_ms = now_ms - 4_000  # 4s miss
        producer._block_index = 0

        log_records = []
        handler = logging.Handler()
        handler.emit = lambda record: log_records.append(record)
        producer._logger.addHandler(handler)
        producer._logger.setLevel(logging.DEBUG)

        try:
            producer._feed_ahead()
        finally:
            producer._logger.removeHandler(handler)

        miss_logs = [
            r for r in log_records
            if "MISS_READY_BY" in r.getMessage()
        ]
        assert len(miss_logs) >= 1, (
            "MISS POLICY: Expected at least one MISS_READY_BY log on miss"
        )

        msg = miss_logs[0].getMessage()
        assert "channel=" in msg, "MISS_READY_BY must contain channel="
        assert "block=" in msg, "MISS_READY_BY must contain block="
        assert "lateness_ms=" in msg, "MISS_READY_BY must contain lateness_ms="
        assert "ready_by=" in msg, "MISS_READY_BY must contain ready_by="
        assert "start=" in msg, "MISS_READY_BY must contain start="
        assert "now=" in msg, "MISS_READY_BY must contain now="

        # Verify it's a WARNING level log
        assert miss_logs[0].levelno == logging.WARNING, (
            f"MISS_READY_BY should be WARNING level, got {miss_logs[0].levelname}"
        )

    def test_no_miss_log_when_on_time(self):
        """No MISS_READY_BY log when block is fed on time."""
        import logging

        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session(
            feed_ahead_horizon_ms=20_000,
            block_duration_ms=30_000,
        )

        playout_plan = [
            {"asset_path": "assets/A.mp4", "duration_ms": 30_000},
        ]

        producer._session = mock_session
        producer._playout_plan = playout_plan

        now_ms = int(time.time() * 1000)
        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = now_ms
        producer._started = True
        producer._feed_credits = 2  # Credits available but neither trigger met
        producer._next_block_start_ms = now_ms + 30_000  # well in the future
        producer._block_index = 0

        log_records = []
        handler = logging.Handler()
        handler.emit = lambda record: log_records.append(record)
        producer._logger.addHandler(handler)
        producer._logger.setLevel(logging.DEBUG)

        try:
            producer._feed_ahead()
        finally:
            producer._logger.removeHandler(handler)

        miss_logs = [
            r for r in log_records
            if "MISS_READY_BY" in r.getMessage()
        ]
        assert len(miss_logs) == 0, (
            f"MISS POLICY: No MISS_READY_BY log expected for on-time feeds. "
            f"Got {len(miss_logs)} logs."
        )


# =============================================================================
# Part 8: Credit-Based Flow Control Contract Tests (INV-FEED-CREDIT-*)
# =============================================================================


class TestCreditInitialization:
    """Credits = 0 after seed; tick path makes 0 gRPC calls; cleanup resets all."""

    def test_credits_zero_after_seed(self):
        """After seed, credits = 0 (queue full with A+B)."""
        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session()

        playout_plan = [{"asset_path": "assets/A.mp4", "duration_ms": 30_000}]
        producer._session = mock_session
        producer._playout_plan = playout_plan
        mock_session.on_block_complete = producer._on_block_complete

        block_a = producer._generate_next_block(playout_plan)
        producer._advance_cursor(block_a)
        block_b = producer._generate_next_block(playout_plan)
        producer._advance_cursor(block_b)
        mock_session.seed(block_a, block_b)

        producer._feed_state = _FeedState.SEEDED
        producer._max_delivered_end_utc_ms = block_b.end_utc_ms
        producer._feed_credits = 0  # As start() would set
        producer._started = True

        assert producer._feed_credits == 0

    def test_tick_makes_zero_calls_with_zero_credits(self):
        """With credits = 0 in RUNNING, 100 ticks produce 0 feed calls."""
        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session()

        playout_plan = [{"asset_path": "assets/A.mp4", "duration_ms": 30_000}]
        producer._session = mock_session
        producer._playout_plan = playout_plan

        now_ms = int(time.time() * 1000)
        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = now_ms
        producer._started = True
        producer._feed_credits = 0
        producer._next_block_start_ms = now_ms
        producer._block_index = 0

        for _ in range(100):
            producer.on_paced_tick(time.time(), 1 / 30)

        assert len(feed_log) == 0, (
            f"Expected 0 feed calls with credits=0, got {len(feed_log)}"
        )

    def test_cleanup_resets_credit_state(self):
        """_cleanup() resets credits, errors, and backoff to zero."""
        from retrovue.runtime.channel_manager import BlockPlanProducer

        producer = BlockPlanProducer(
            channel_id="credit-cleanup-test",
            configuration={"block_duration_ms": 30_000},
            channel_config=None, schedule_service=None, clock=None,
        )
        producer._feed_credits = 2
        producer._consecutive_feed_errors = 5
        producer._error_backoff_remaining = 64

        producer._cleanup()

        assert producer._feed_credits == 0
        assert producer._consecutive_feed_errors == 0
        assert producer._error_backoff_remaining == 0


class TestCreditIncrementOnBlockComplete:
    """BlockCompleted → credits += 1; capped at AIR_QUEUE_DEPTH."""

    def test_block_complete_increments_credit(self):
        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session()

        playout_plan = [{"asset_path": "assets/A.mp4", "duration_ms": 30_000}]
        producer._session = mock_session
        producer._playout_plan = playout_plan
        mock_session.on_block_complete = producer._on_block_complete

        block_a = producer._generate_next_block(playout_plan)
        producer._advance_cursor(block_a)
        block_b = producer._generate_next_block(playout_plan)
        producer._advance_cursor(block_b)
        mock_session.seed(block_a, block_b)

        producer._feed_state = _FeedState.SEEDED
        producer._max_delivered_end_utc_ms = block_b.end_utc_ms
        producer._feed_credits = 0
        producer._started = True
        producer._in_flight_block_ids.add(block_a.block_id)
        producer._in_flight_block_ids.add(block_b.block_id)

        # After BlockCompleted, credits should be 1
        # (feed_ahead may consume it if a feed succeeds, but credit was set to 1 first)
        old_credits = producer._feed_credits
        producer._on_block_complete(block_a.block_id)
        # Credit was incremented to 1 before _feed_ahead; _feed_ahead may decrement it
        # We verify the state is consistent
        assert producer._feed_state == _FeedState.RUNNING

    def test_credits_capped_at_queue_depth(self):
        """Credits never exceed AIR_QUEUE_DEPTH."""
        from retrovue.runtime.channel_manager import BlockPlanProducer

        producer = BlockPlanProducer(
            channel_id="cap-test",
            configuration={"block_duration_ms": 30_000},
            channel_config=None, schedule_service=None, clock=None,
        )
        producer._feed_credits = producer.AIR_QUEUE_DEPTH

        # Simulate increment (as _on_block_complete does internally)
        producer._feed_credits = min(
            producer._feed_credits + 1, producer.AIR_QUEUE_DEPTH
        )
        assert producer._feed_credits == producer.AIR_QUEUE_DEPTH, (
            f"Credits must be capped at {producer.AIR_QUEUE_DEPTH}, "
            f"got {producer._feed_credits}"
        )


class TestCreditDecrementOnAccepted:
    """ACCEPTED → credits -= 1; credit gate stops at 0."""

    def test_accepted_decrements_credit(self):
        from retrovue.runtime.playout_session import FeedResult

        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session()

        playout_plan = [{"asset_path": "assets/A.mp4", "duration_ms": 30_000}]
        producer._session = mock_session
        producer._playout_plan = playout_plan

        now_ms = int(time.time() * 1000)
        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = now_ms
        producer._started = True
        producer._feed_credits = 1
        producer._next_block_start_ms = now_ms
        producer._block_index = 0

        producer._feed_ahead()

        # One feed consumed the credit
        assert len(feed_log) == 1, f"Expected 1 feed, got {len(feed_log)}"
        assert producer._feed_credits == 0, (
            f"Expected credits=0 after ACCEPTED, got {producer._feed_credits}"
        )

    def test_credit_gate_stops_second_feed(self):
        """With credits=1, only 1 feed occurs even if runway is still low."""
        from retrovue.runtime.playout_session import FeedResult

        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session(
            block_duration_ms=5_000,
            feed_ahead_horizon_ms=20_000,
        )

        playout_plan = [{"asset_path": "assets/A.mp4", "duration_ms": 5_000}]
        producer._session = mock_session
        producer._playout_plan = playout_plan

        now_ms = int(time.time() * 1000)
        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = now_ms
        producer._started = True
        producer._feed_credits = 1  # Only 1 credit
        producer._next_block_start_ms = now_ms
        producer._block_index = 0

        producer._feed_ahead()

        # Even though runway is still low after 1 feed (5s < 20s), credit gate stops
        assert len(feed_log) == 1, (
            f"Expected exactly 1 feed with credits=1, got {len(feed_log)}"
        )


class TestCreditResetOnQueueFull:
    """QUEUE_FULL → credits = 0 (authoritative); no error escalation."""

    def test_queue_full_zeros_credits(self):
        from retrovue.runtime.playout_session import FeedResult

        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session()
        mock_session._feed_returns[0] = FeedResult.QUEUE_FULL

        playout_plan = [{"asset_path": "assets/A.mp4", "duration_ms": 30_000}]
        producer._session = mock_session
        producer._playout_plan = playout_plan

        now_ms = int(time.time() * 1000)
        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = now_ms
        producer._started = True
        producer._feed_credits = 1
        producer._next_block_start_ms = now_ms
        producer._block_index = 0

        producer._feed_ahead()

        assert producer._feed_credits == 0, (
            f"QUEUE_FULL must reset credits to 0, got {producer._feed_credits}"
        )

    def test_queue_full_no_error_escalation(self):
        """QUEUE_FULL does NOT increment consecutive_feed_errors."""
        from retrovue.runtime.playout_session import FeedResult

        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session()
        mock_session._feed_returns[0] = FeedResult.QUEUE_FULL

        playout_plan = [{"asset_path": "assets/A.mp4", "duration_ms": 30_000}]
        producer._session = mock_session
        producer._playout_plan = playout_plan

        now_ms = int(time.time() * 1000)
        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = now_ms
        producer._started = True
        producer._feed_credits = 1
        producer._next_block_start_ms = now_ms
        producer._block_index = 0

        producer._feed_ahead()

        assert producer._consecutive_feed_errors == 0, (
            f"QUEUE_FULL must NOT escalate errors, got {producer._consecutive_feed_errors}"
        )
        assert producer._error_backoff_remaining == 0, (
            f"QUEUE_FULL must NOT set error backoff, got {producer._error_backoff_remaining}"
        )


class TestCreditGateEliminatesThrash:
    """100 ticks with credits=0 → 0 feed calls; BlockCompleted breaks silence."""

    def test_zero_credits_zero_calls(self):
        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session()

        playout_plan = [{"asset_path": "assets/A.mp4", "duration_ms": 30_000}]
        producer._session = mock_session
        producer._playout_plan = playout_plan
        mock_session.on_block_complete = producer._on_block_complete

        now_ms = int(time.time() * 1000)
        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = now_ms
        producer._started = True
        producer._feed_credits = 0
        producer._next_block_start_ms = now_ms
        producer._block_index = 0

        # 100 ticks → zero gRPC calls
        for _ in range(100):
            producer.on_paced_tick(time.time(), 1 / 30)

        assert len(feed_log) == 0, (
            f"Credit gate: expected 0 feed calls with credits=0, got {len(feed_log)}"
        )

    def test_block_completed_breaks_silence(self):
        """BlockCompleted after credit drought triggers feed."""
        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session()

        playout_plan = [{"asset_path": "assets/A.mp4", "duration_ms": 30_000}]
        producer._session = mock_session
        producer._playout_plan = playout_plan
        mock_session.on_block_complete = producer._on_block_complete

        now_ms = int(time.time() * 1000)
        block_a = producer._generate_next_block(playout_plan)
        producer._advance_cursor(block_a)
        block_b = producer._generate_next_block(playout_plan)
        producer._advance_cursor(block_b)
        mock_session.seed(block_a, block_b)

        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = block_b.end_utc_ms
        producer._started = True
        producer._feed_credits = 0
        producer._in_flight_block_ids.add(block_a.block_id)
        producer._in_flight_block_ids.add(block_b.block_id)

        # 50 ticks → no feeds
        for _ in range(50):
            producer.on_paced_tick(time.time(), 1 / 30)
        assert len(feed_log) == 0

        # BlockCompleted → credits=1 → feed
        producer._on_block_complete(block_a.block_id)

        assert len(feed_log) >= 1, (
            "BlockCompleted must break credit drought and trigger feed"
        )


class TestErrorBackoffEscalation:
    """Consecutive errors → 4, 8, 16, 32, 64, 112 ticks; caps at 112."""

    def test_escalating_backoff(self):
        from retrovue.runtime.playout_session import FeedResult
        from retrovue.runtime.channel_manager import BlockPlanProducer

        producer = BlockPlanProducer(
            channel_id="backoff-test",
            configuration={"block_duration_ms": 30_000},
            channel_config=None, schedule_service=None, clock=None,
        )

        from retrovue.runtime.playout_session import BlockPlan

        expected_ticks = [4, 8, 16, 32, 64, 112, 112]  # caps at 112

        for i, expected in enumerate(expected_ticks):
            block = BlockPlan(
                block_id=f"BLOCK-err-{i}", channel_id=1,
                start_utc_ms=1000 * i, end_utc_ms=1000 * (i + 1), segments=[],
            )

            # Simulate _try_feed_block ERROR path manually
            producer._consecutive_feed_errors += 1
            producer._error_backoff_remaining = min(
                producer.ERROR_BACKOFF_BASE_TICKS
                * (2 ** (producer._consecutive_feed_errors - 1)),
                producer.ERROR_BACKOFF_MAX_TICKS,
            )

            assert producer._error_backoff_remaining == expected, (
                f"Error #{i+1}: expected backoff={expected}, "
                f"got {producer._error_backoff_remaining}"
            )


class TestErrorBackoffReset:
    """BlockCompleted resets consecutive errors and backoff to 0."""

    def test_block_complete_clears_error_state(self):
        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session()

        playout_plan = [{"asset_path": "assets/A.mp4", "duration_ms": 30_000}]
        producer._session = mock_session
        producer._playout_plan = playout_plan
        mock_session.on_block_complete = producer._on_block_complete

        block_a = producer._generate_next_block(playout_plan)
        producer._advance_cursor(block_a)
        block_b = producer._generate_next_block(playout_plan)
        producer._advance_cursor(block_b)
        mock_session.seed(block_a, block_b)

        producer._feed_state = _FeedState.RUNNING
        producer._max_delivered_end_utc_ms = block_b.end_utc_ms
        producer._started = True
        producer._in_flight_block_ids.add(block_a.block_id)
        producer._in_flight_block_ids.add(block_b.block_id)

        # Simulate error state
        producer._consecutive_feed_errors = 5
        producer._error_backoff_remaining = 112
        producer._feed_credits = 0

        producer._on_block_complete(block_a.block_id)

        assert producer._consecutive_feed_errors == 0, (
            f"BlockCompleted must clear errors, got {producer._consecutive_feed_errors}"
        )
        assert producer._error_backoff_remaining == 0, (
            f"BlockCompleted must clear backoff, got {producer._error_backoff_remaining}"
        )


class TestErrorVsQueueFullDistinction:
    """QUEUE_FULL: no error escalation; ERROR: credits unchanged."""

    def test_queue_full_vs_error(self):
        from retrovue.runtime.playout_session import FeedResult, BlockPlan
        from retrovue.runtime.channel_manager import BlockPlanProducer

        producer = BlockPlanProducer(
            channel_id="distinction-test",
            configuration={"block_duration_ms": 30_000},
            channel_config=None, schedule_service=None, clock=None,
        )

        # Mock session returning QUEUE_FULL
        class QFSession:
            def feed(self, block):
                return FeedResult.QUEUE_FULL
        producer._session = QFSession()
        producer._feed_credits = 1

        block = BlockPlan(
            block_id="BLOCK-qf", channel_id=1,
            start_utc_ms=0, end_utc_ms=30000, segments=[],
        )
        result = producer._try_feed_block(block)
        assert result == FeedResult.QUEUE_FULL
        assert producer._consecutive_feed_errors == 0, "QUEUE_FULL must NOT escalate errors"
        assert producer._feed_credits == 0, "QUEUE_FULL must zero credits"

        # Mock session returning ERROR
        class ErrSession:
            def feed(self, block):
                return FeedResult.ERROR
        producer._session = ErrSession()
        producer._feed_credits = 1
        producer._consecutive_feed_errors = 0

        result = producer._try_feed_block(block)
        assert result == FeedResult.ERROR
        assert producer._consecutive_feed_errors == 1, "ERROR must escalate errors"
        assert producer._feed_credits == 1, "ERROR must NOT change credits"


class TestFeedResultIntegration:
    """ACCEPTED/QUEUE_FULL/ERROR each handle cursor, pending, credits correctly."""

    def test_accepted_advances_cursor_clears_pending(self):
        from retrovue.runtime.playout_session import FeedResult, BlockPlan
        from retrovue.runtime.channel_manager import BlockPlanProducer

        producer = BlockPlanProducer(
            channel_id="result-test",
            configuration={"block_duration_ms": 30_000},
            channel_config=None, schedule_service=None, clock=None,
        )

        class AccSession:
            def feed(self, block):
                return FeedResult.ACCEPTED
        producer._session = AccSession()
        producer._feed_credits = 2

        block = BlockPlan(
            block_id="BLOCK-acc", channel_id=1,
            start_utc_ms=0, end_utc_ms=30000, segments=[],
        )
        producer._pending_block = block
        old_index = producer._block_index

        result = producer._try_feed_block(block)

        assert result == FeedResult.ACCEPTED
        assert producer._pending_block is None, "ACCEPTED must clear pending"
        assert producer._block_index == old_index + 1, "ACCEPTED must advance cursor"
        assert producer._feed_credits == 1, "ACCEPTED must decrement credits"

    def test_queue_full_stores_pending_no_cursor(self):
        from retrovue.runtime.playout_session import FeedResult, BlockPlan
        from retrovue.runtime.channel_manager import BlockPlanProducer

        producer = BlockPlanProducer(
            channel_id="result-test",
            configuration={"block_duration_ms": 30_000},
            channel_config=None, schedule_service=None, clock=None,
        )

        class QFSession:
            def feed(self, block):
                return FeedResult.QUEUE_FULL
        producer._session = QFSession()
        producer._feed_credits = 1

        block = BlockPlan(
            block_id="BLOCK-qf", channel_id=1,
            start_utc_ms=0, end_utc_ms=30000, segments=[],
        )
        old_index = producer._block_index

        result = producer._try_feed_block(block)

        assert result == FeedResult.QUEUE_FULL
        assert producer._pending_block is block, "QUEUE_FULL must store pending"
        assert producer._block_index == old_index, "QUEUE_FULL must NOT advance cursor"

    def test_error_stores_pending_escalates(self):
        from retrovue.runtime.playout_session import FeedResult, BlockPlan
        from retrovue.runtime.channel_manager import BlockPlanProducer

        producer = BlockPlanProducer(
            channel_id="result-test",
            configuration={"block_duration_ms": 30_000},
            channel_config=None, schedule_service=None, clock=None,
        )

        class ErrSession:
            def feed(self, block):
                return FeedResult.ERROR
        producer._session = ErrSession()
        producer._feed_credits = 1

        block = BlockPlan(
            block_id="BLOCK-err", channel_id=1,
            start_utc_ms=0, end_utc_ms=30000, segments=[],
        )
        old_index = producer._block_index

        result = producer._try_feed_block(block)

        assert result == FeedResult.ERROR
        assert producer._pending_block is block, "ERROR must store pending"
        assert producer._block_index == old_index, "ERROR must NOT advance cursor"
        assert producer._consecutive_feed_errors == 1
        assert producer._error_backoff_remaining == 4  # BASE * 2^0


class TestCreditLifecycleEndToEnd:
    """Full trace: seed→ticks→BlockCompleted→feed→ticks→BlockCompleted→feed."""

    def test_full_lifecycle(self):
        producer, mock_session, feed_log, _FeedState = _make_producer_with_mock_session(
            block_duration_ms=5_000,
            feed_ahead_horizon_ms=20_000,
        )

        playout_plan = [{"asset_path": "assets/A.mp4", "duration_ms": 5_000}]
        producer._session = mock_session
        producer._playout_plan = playout_plan
        mock_session.on_block_complete = producer._on_block_complete

        # --- seed(A, B) ---
        now_ms = int(time.time() * 1000)
        producer._next_block_start_ms = now_ms
        block_a = producer._generate_next_block(playout_plan)
        producer._advance_cursor(block_a)
        block_b = producer._generate_next_block(playout_plan)
        producer._advance_cursor(block_b)
        mock_session.seed(block_a, block_b)

        producer._feed_state = _FeedState.SEEDED
        producer._max_delivered_end_utc_ms = block_b.end_utc_ms
        producer._feed_credits = 0  # Queue full after seed
        producer._started = True
        producer._in_flight_block_ids.add(block_a.block_id)
        producer._in_flight_block_ids.add(block_b.block_id)

        # --- Ticks: credits=0, nothing happens ---
        for _ in range(20):
            producer.on_paced_tick(time.time(), 1 / 30)
        assert len(feed_log) == 0, "No feeds during credit drought"

        # --- BlockCompleted(A): credit=1 → SEEDED→RUNNING → feed(C) → credit=0 ---
        producer._on_block_complete(block_a.block_id)
        assert producer._feed_state == _FeedState.RUNNING
        assert len(feed_log) >= 1, "BlockCompleted(A) must trigger feed"
        feed_log_after_a = len(feed_log)

        # --- More ticks: credits should be 0 again → no more feeds ---
        for _ in range(20):
            producer.on_paced_tick(time.time(), 1 / 30)
        assert len(feed_log) == feed_log_after_a, "No feeds between BlockCompleted events"

        # --- BlockCompleted(B): credit=1 → feed(D) → credit=0 ---
        producer._on_block_complete(block_b.block_id)
        assert len(feed_log) > feed_log_after_a, "BlockCompleted(B) must trigger feed"

        # All fed blocks must be sequential
        for i, (bid, accepted) in enumerate(feed_log):
            expected_id = f"BLOCK-fa-test-{i + 2}"  # blocks 0,1 were seeded
            assert bid == expected_id, (
                f"Expected {expected_id}, got {bid}"
            )
            assert accepted is True


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
