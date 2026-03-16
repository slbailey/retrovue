"""
Contract Tests: HLS Phantom Drain Liveness Bridge

Canonical contract:
    docs/contracts/delivery_hls.md — §4, §5

Invariants:
    INV-HLS-PHANTOM-DRAIN-KEEPS-CHANNEL-ALIVE-001
    INV-HLS-FIRST-VIEWER-ACTIVATES-CHANNEL-001

These tests verify that the canonical HLS path keeps channels alive
via a phantom drain subscriber, that exactly one phantom exists per
channel, and that the phantom disconnects on inactivity.

Tests use minimal fakes to validate the behavioral contract independently
of the full runtime.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Minimal fakes for phantom drain contract testing
# ---------------------------------------------------------------------------


@dataclass
class FakeQueue:
    """Simulates a BytesBoundedQueue for phantom drain testing."""
    _data: list[bytes] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _event: threading.Event = field(default_factory=threading.Event)

    def put(self, chunk: bytes) -> None:
        with self._lock:
            self._data.append(chunk)
            self._event.set()

    def get(self, timeout: float = 1.0) -> bytes | None:
        if self._event.wait(timeout=timeout):
            with self._lock:
                if self._data:
                    self._event.clear()
                    return self._data.pop(0)
        return None


@dataclass
class FakeFanout:
    """Simulates ChannelStream subscribe/unsubscribe."""
    _subscribers: dict[str, FakeQueue] = field(default_factory=dict)
    _running: bool = True

    def subscribe(self, session_id: str) -> FakeQueue:
        q = FakeQueue()
        self._subscribers[session_id] = q
        return q

    def unsubscribe(self, session_id: str) -> None:
        self._subscribers.pop(session_id, None)

    def is_running(self) -> bool:
        return self._running

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


@dataclass
class FakeManager:
    """Simulates ChannelManager for phantom testing."""
    channel_id: str
    LINGER_SECONDS: int = 5
    _viewers: set[str] = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _tune_in_count: int = 0
    _tune_out_count: int = 0

    def tune_in(self, session_id: str, metadata: dict | None = None) -> None:
        with self._lock:
            self._tune_in_count += 1
            self._viewers.add(session_id)

    def tune_out(self, session_id: str) -> None:
        with self._lock:
            self._tune_out_count += 1
            self._viewers.discard(session_id)

    @property
    def viewer_count(self) -> int:
        with self._lock:
            return len(self._viewers)


@dataclass
class PhantomTracker:
    """Tracks phantom lifecycle for testing.

    Simulates the phantom drain pattern from ProgramDirector.
    """
    _phantoms: dict[str, str] = field(default_factory=dict)  # channel_id → phantom_id
    _activity: dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _drain_threads: dict[str, threading.Thread] = field(default_factory=dict)

    def has_phantom(self, channel_id: str) -> bool:
        with self._lock:
            return channel_id in self._phantoms

    def start_phantom(
        self,
        channel_id: str,
        manager: FakeManager,
        fanout: FakeFanout,
        idle_timeout: float = 5.0,
    ) -> bool:
        """Start a phantom drain for a channel. Returns False if one already exists."""
        with self._lock:
            if channel_id in self._phantoms:
                self._activity[channel_id] = time.monotonic()
                return False
            phantom_id = f"phantom-{channel_id}"
            self._phantoms[channel_id] = phantom_id
            self._activity[channel_id] = time.monotonic()

        manager.tune_in(phantom_id, {"hls": True})
        queue = fanout.subscribe(phantom_id)

        def _drain():
            while True:
                queue.get(timeout=1.0)
                with self._lock:
                    last = self._activity.get(channel_id, 0)
                if time.monotonic() - last > idle_timeout:
                    break

            manager.tune_out(phantom_id)
            fanout.unsubscribe(phantom_id)
            with self._lock:
                self._phantoms.pop(channel_id, None)
                self._activity.pop(channel_id, None)
                self._drain_threads.pop(channel_id, None)

        t = threading.Thread(target=_drain, daemon=True)
        self._drain_threads[channel_id] = t
        t.start()
        return True

    def refresh_activity(self, channel_id: str) -> None:
        with self._lock:
            if channel_id in self._activity:
                self._activity[channel_id] = time.monotonic()


# ---------------------------------------------------------------------------
# INV-HLS-PHANTOM-DRAIN-KEEPS-CHANNEL-ALIVE-001
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsPhantomDrainKeepsChannelAlive001:
    """INV-HLS-PHANTOM-DRAIN-KEEPS-CHANNEL-ALIVE-001"""

    def test_phantom_starts_on_activation(self):
        """HLS activation creates a phantom drain."""
        tracker = PhantomTracker()
        mgr = FakeManager(channel_id="hbo")
        fanout = FakeFanout()

        result = tracker.start_phantom("hbo", mgr, fanout)

        assert result is True
        assert tracker.has_phantom("hbo")
        assert mgr.viewer_count == 1
        assert fanout.subscriber_count == 1

    def test_duplicate_phantom_prevented(self):
        """Second start_phantom for same channel returns False."""
        tracker = PhantomTracker()
        mgr = FakeManager(channel_id="hbo")
        fanout = FakeFanout()

        first = tracker.start_phantom("hbo", mgr, fanout)
        second = tracker.start_phantom("hbo", mgr, fanout)

        assert first is True
        assert second is False
        # Only one tune_in
        assert mgr._tune_in_count == 1
        assert fanout.subscriber_count == 1

    def test_concurrent_activation_starts_one_phantom(self):
        """Concurrent activation attempts start exactly one phantom."""
        tracker = PhantomTracker()
        mgr = FakeManager(channel_id="hbo")
        fanout = FakeFanout()
        results: list[bool] = []
        barrier = threading.Barrier(4)

        def _try_start():
            barrier.wait(timeout=5)
            r = tracker.start_phantom("hbo", mgr, fanout)
            results.append(r)

        threads = [threading.Thread(target=_try_start) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert results.count(True) == 1
        assert results.count(False) == 3
        assert mgr._tune_in_count == 1

    def test_phantom_keeps_fanout_subscribed(self):
        """While phantom is active, fanout has a subscriber."""
        tracker = PhantomTracker()
        mgr = FakeManager(channel_id="hbo")
        fanout = FakeFanout()

        tracker.start_phantom("hbo", mgr, fanout, idle_timeout=10.0)

        # Phantom is running, subscriber exists
        assert fanout.subscriber_count == 1
        assert tracker.has_phantom("hbo")

    def test_phantom_stops_on_inactivity(self):
        """Phantom disconnects when no HLS activity within timeout."""
        tracker = PhantomTracker()
        mgr = FakeManager(channel_id="hbo")
        fanout = FakeFanout()

        tracker.start_phantom("hbo", mgr, fanout, idle_timeout=1.0)

        # Wait for drain to detect inactivity (slightly over idle_timeout + check interval)
        time.sleep(3.0)

        assert not tracker.has_phantom("hbo")
        assert mgr._tune_out_count == 1
        assert fanout.subscriber_count == 0

    def test_activity_refresh_keeps_phantom_alive(self):
        """Refreshing activity prevents phantom timeout."""
        tracker = PhantomTracker()
        mgr = FakeManager(channel_id="hbo")
        fanout = FakeFanout()

        tracker.start_phantom("hbo", mgr, fanout, idle_timeout=2.0)

        # Keep refreshing for 3 seconds (beyond idle_timeout)
        for _ in range(6):
            time.sleep(0.5)
            tracker.refresh_activity("hbo")

        # Should still be alive
        assert tracker.has_phantom("hbo")
        assert mgr._tune_out_count == 0

    def test_phantom_tunes_out_on_stop(self):
        """Phantom calls tune_out on cleanup."""
        tracker = PhantomTracker()
        mgr = FakeManager(channel_id="hbo")
        fanout = FakeFanout()

        tracker.start_phantom("hbo", mgr, fanout, idle_timeout=0.5)
        time.sleep(2.0)

        assert mgr._tune_out_count == 1

    def test_two_channels_independent_phantoms(self):
        """Each channel gets its own independent phantom."""
        tracker = PhantomTracker()
        mgr_a = FakeManager(channel_id="hbo")
        mgr_b = FakeManager(channel_id="cnn")
        fanout_a = FakeFanout()
        fanout_b = FakeFanout()

        tracker.start_phantom("hbo", mgr_a, fanout_a)
        tracker.start_phantom("cnn", mgr_b, fanout_b)

        assert tracker.has_phantom("hbo")
        assert tracker.has_phantom("cnn")
        assert mgr_a._tune_in_count == 1
        assert mgr_b._tune_in_count == 1

    def test_phantom_does_not_affect_existing_subscribers(self):
        """Phantom does not interfere with other fanout subscribers."""
        tracker = PhantomTracker()
        mgr = FakeManager(channel_id="hbo")
        fanout = FakeFanout()

        # Existing subscriber (simulating a raw TS viewer)
        fanout.subscribe("ts-viewer-1")
        assert fanout.subscriber_count == 1

        tracker.start_phantom("hbo", mgr, fanout)
        assert fanout.subscriber_count == 2  # ts-viewer + phantom

        # TS viewer unsubscribes — phantom still there
        fanout.unsubscribe("ts-viewer-1")
        assert fanout.subscriber_count == 1
        assert tracker.has_phantom("hbo")
