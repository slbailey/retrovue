"""
Contract Tests: HLS First-Viewer Channel Activation

Canonical contract:
    docs/contracts/delivery_hls.md — §4, §5

Invariant:
    INV-HLS-FIRST-VIEWER-ACTIVATES-CHANNEL-001

These tests verify that an HLS manifest request activates an inactive
channel through the standard ChannelManager lifecycle, and that
activation is idempotent (no duplicate producers from concurrent
requests).

The tests use a minimal fake runtime to validate the behavioral contract
independently of the full FastAPI stack.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Minimal fake runtime for activation contract testing
# ---------------------------------------------------------------------------


@dataclass
class FakeProducer:
    started: bool = False
    start_count: int = 0

    def start(self) -> None:
        self.start_count += 1
        self.started = True


@dataclass
class FakeChannelManager:
    """Minimal ChannelManager implementing the viewer lifecycle contract."""

    channel_id: str
    _viewer_lock: threading.Lock = field(default_factory=threading.Lock)
    _viewer_count: int = 0
    _tune_in_count: int = 0
    _producer: FakeProducer = field(default_factory=FakeProducer)
    _sessions: set[str] = field(default_factory=set)

    @property
    def viewer_count(self) -> int:
        return self._viewer_count

    @property
    def producer(self) -> FakeProducer:
        return self._producer

    def tune_in(self, session_id: str, metadata: dict[str, Any] | None = None) -> None:
        with self._viewer_lock:
            self._tune_in_count += 1
            if session_id in self._sessions:
                return  # already tuned in
            self._sessions.add(session_id)
            self._viewer_count += 1
            if self._viewer_count == 1:
                self._producer.start()

    def tune_out(self, session_id: str) -> None:
        with self._viewer_lock:
            if session_id not in self._sessions:
                return
            self._sessions.discard(session_id)
            self._viewer_count -= 1


@dataclass
class FakeChannelRegistry:
    """Simulates ProgramDirector's channel manager resolution."""

    _managers: dict[str, FakeChannelManager] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def get_or_create(self, channel_id: str) -> FakeChannelManager:
        with self._lock:
            if channel_id not in self._managers:
                self._managers[channel_id] = FakeChannelManager(channel_id=channel_id)
            return self._managers[channel_id]

    def get(self, channel_id: str) -> FakeChannelManager | None:
        with self._lock:
            return self._managers.get(channel_id)


def _simulate_hls_activation(
    registry: FakeChannelRegistry,
    channel_id: str,
    session_id: str,
) -> FakeChannelManager:
    """Simulate the HLS manifest activation path.

    This mirrors the contract behavior expected from ProgramDirector:
    1. Resolve or create the ChannelManager
    2. Tune in through the standard lifecycle
    """
    mgr = registry.get_or_create(channel_id)
    mgr.tune_in(session_id, {"channel_id": channel_id, "hls": True})
    return mgr


# ---------------------------------------------------------------------------
# INV-HLS-FIRST-VIEWER-ACTIVATES-CHANNEL-001
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsFirstViewerActivatesChannel001:
    """INV-HLS-FIRST-VIEWER-ACTIVATES-CHANNEL-001"""

    def test_hls_request_activates_inactive_channel(self):
        """First HLS manifest request for an inactive channel starts the producer."""
        registry = FakeChannelRegistry()

        mgr = _simulate_hls_activation(registry, "hbo", "session-1")

        # INV-HLS-FIRST-VIEWER-ACTIVATES-CHANNEL-001 — channel activated
        assert mgr.viewer_count == 1
        assert mgr.producer.started is True
        assert mgr.producer.start_count == 1

    def test_multiple_requests_do_not_create_multiple_producers(self):
        """Concurrent manifest requests start the producer exactly once."""
        registry = FakeChannelRegistry()

        # Three sequential requests from different sessions
        _simulate_hls_activation(registry, "hbo", "session-1")
        _simulate_hls_activation(registry, "hbo", "session-2")
        _simulate_hls_activation(registry, "hbo", "session-3")

        mgr = registry.get("hbo")
        assert mgr is not None

        # INV-HLS-FIRST-VIEWER-ACTIVATES-CHANNEL-001 — single producer
        assert mgr.producer.start_count == 1
        assert mgr.viewer_count == 3

    def test_concurrent_requests_start_producer_once(self):
        """Concurrent HLS requests activate the channel exactly once."""
        registry = FakeChannelRegistry()
        errors: list[str] = []
        barrier = threading.Barrier(4)

        def _activate(session_id: str):
            try:
                barrier.wait(timeout=5)
                _simulate_hls_activation(registry, "hbo", session_id)
            except Exception as e:
                errors.append(str(e))

        threads = [
            threading.Thread(target=_activate, args=(f"session-{i}",))
            for i in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == []

        mgr = registry.get("hbo")
        assert mgr is not None

        # INV-HLS-FIRST-VIEWER-ACTIVATES-CHANNEL-001 — exactly one start
        assert mgr.producer.start_count == 1
        assert mgr.viewer_count == 4

    def test_request_while_active_does_not_restart(self):
        """Manifest request while channel is already active does not restart the producer."""
        registry = FakeChannelRegistry()

        _simulate_hls_activation(registry, "hbo", "session-1")
        mgr = registry.get("hbo")
        assert mgr is not None
        assert mgr.producer.start_count == 1

        # Second request with same session — tune_in is idempotent
        _simulate_hls_activation(registry, "hbo", "session-1")

        # INV-HLS-FIRST-VIEWER-ACTIVATES-CHANNEL-001 — no restart
        assert mgr.producer.start_count == 1
        assert mgr.viewer_count == 1

    def test_activation_uses_tune_in_not_parallel_path(self):
        """Activation goes through tune_in, not a parallel producer start."""
        registry = FakeChannelRegistry()

        mgr = _simulate_hls_activation(registry, "hbo", "session-1")

        # INV-HLS-FIRST-VIEWER-ACTIVATES-CHANNEL-001 — uses tune_in
        assert mgr._tune_in_count >= 1

    def test_activation_creates_manager_for_unknown_channel(self):
        """HLS request for an uncached channel creates the ChannelManager."""
        registry = FakeChannelRegistry()

        assert registry.get("new-channel") is None

        mgr = _simulate_hls_activation(registry, "new-channel", "session-1")

        # INV-HLS-FIRST-VIEWER-ACTIVATES-CHANNEL-001 — manager created
        assert mgr is not None
        assert mgr.channel_id == "new-channel"
        assert mgr.viewer_count == 1

    def test_two_channels_activate_independently(self):
        """Activating one channel does not affect another."""
        registry = FakeChannelRegistry()

        mgr_a = _simulate_hls_activation(registry, "hbo", "s1")
        mgr_b = _simulate_hls_activation(registry, "cnn", "s2")

        # INV-HLS-FIRST-VIEWER-ACTIVATES-CHANNEL-001 — independent
        assert mgr_a.channel_id == "hbo"
        assert mgr_b.channel_id == "cnn"
        assert mgr_a.producer.start_count == 1
        assert mgr_b.producer.start_count == 1
        assert mgr_a.viewer_count == 1
        assert mgr_b.viewer_count == 1
