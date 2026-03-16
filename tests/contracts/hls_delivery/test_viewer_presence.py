"""
Contract Tests: HLS Viewer Presence

Canonical contract:
    docs/contracts/delivery_hls.md — §5 Viewer Presence Contract

Test matrix:
    docs/contracts/TEST-MATRIX-HLS-DELIVERY.md — Viewer Presence

These tests enforce the viewer presence invariants
(INV-HLS-VIEWER-PRESENCE-001 through INV-HLS-PHANTOM-CLEANUP-001)
using an in-memory session manager test double.

Every test references the specific invariant(s) it validates.

Note: These tests validate behavioral contracts through a minimal
protocol-level session manager, not through the full HTTP stack.
The session manager interface is: touch(session_id), reap(), count(),
and integration with viewer_join/viewer_leave callbacks.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable

import pytest


# ---------------------------------------------------------------------------
# Minimal session manager protocol for contract testing
# ---------------------------------------------------------------------------


@dataclass
class FakeSessionManager:
    """In-memory session manager implementing the viewer presence contract.

    This is NOT an implementation detail test — it validates the behavioral
    contract that any conforming session manager must satisfy.
    """

    timeout_ms: int = 10_000
    _sessions: dict[str, int] = field(default_factory=dict)  # session_id → last_activity_ms
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _clock_ms: int = 0
    on_first_viewer: Callable[[], None] | None = None
    on_last_viewer: Callable[[], None] | None = None
    _first_viewer_count: int = 0
    _last_viewer_count: int = 0

    def set_clock(self, ms: int) -> None:
        self._clock_ms = ms

    def touch(self, session_id: str) -> None:
        with self._lock:
            is_new = session_id not in self._sessions
            self._sessions[session_id] = self._clock_ms
            if is_new and len(self._sessions) == 1:
                self._first_viewer_count += 1
                if self.on_first_viewer:
                    self.on_first_viewer()

    def reap(self) -> None:
        with self._lock:
            expired = [
                sid for sid, ts in self._sessions.items()
                if self._clock_ms - ts > self.timeout_ms
            ]
            for sid in expired:
                del self._sessions[sid]
            if expired and len(self._sessions) == 0:
                self._last_viewer_count += 1
                if self.on_last_viewer:
                    self.on_last_viewer()

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)


@pytest.fixture
def session_mgr():
    """Provide a fresh session manager with 10-second timeout."""
    return FakeSessionManager(timeout_ms=10_000)


# ---------------------------------------------------------------------------
# INV-HLS-VIEWER-PRESENCE-001 — Request-based detection
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsViewerPresence001:
    """INV-HLS-VIEWER-PRESENCE-001"""

    # Tier: 2 | Lifecycle invariant
    def test_first_touch_creates_session(self, session_mgr):
        """First touch from an unknown session creates a new viewer."""
        assert session_mgr.count() == 0

        # INV-HLS-VIEWER-PRESENCE-001 — first request creates session
        session_mgr.touch("session-a")
        assert session_mgr.count() == 1

    # Tier: 2 | Lifecycle invariant
    def test_subsequent_touch_refreshes_not_duplicates(self, session_mgr):
        """Repeated touch from the same session does not increment count."""
        session_mgr.touch("session-a")
        session_mgr.touch("session-a")
        session_mgr.touch("session-a")

        # INV-HLS-VIEWER-PRESENCE-001 — refresh, not duplicate
        assert session_mgr.count() == 1

    # Tier: 2 | Lifecycle invariant
    def test_multiple_sessions_counted_independently(self, session_mgr):
        """Different session IDs create independent sessions."""
        session_mgr.touch("session-a")
        session_mgr.touch("session-b")
        session_mgr.touch("session-c")

        # INV-HLS-VIEWER-PRESENCE-001 — each session counted
        assert session_mgr.count() == 3

    # Tier: 2 | Lifecycle invariant
    def test_expired_session_reaped(self, session_mgr):
        """Session older than timeout is removed by reap."""
        session_mgr.touch("session-a")
        assert session_mgr.count() == 1

        # Advance past timeout
        session_mgr.set_clock(15_000)
        session_mgr.reap()

        # INV-HLS-VIEWER-PRESENCE-001 — expired = reaped
        assert session_mgr.count() == 0

    # Tier: 2 | Lifecycle invariant
    def test_refreshed_session_survives_reap(self, session_mgr):
        """Session refreshed within timeout survives reaping."""
        session_mgr.touch("session-a")

        session_mgr.set_clock(5_000)
        session_mgr.touch("session-a")  # refresh at 5s

        session_mgr.set_clock(12_000)  # 7s since refresh, within timeout
        session_mgr.reap()

        # INV-HLS-VIEWER-PRESENCE-001 — refreshed = alive
        assert session_mgr.count() == 1


# ---------------------------------------------------------------------------
# INV-HLS-VIEWER-COUNT-ACCURATE-001 — Count matches state
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsViewerCountAccurate001:
    """INV-HLS-VIEWER-COUNT-ACCURATE-001"""

    # Tier: 1 | Structural invariant
    def test_count_equals_active_sessions(self, session_mgr):
        """Viewer count equals number of non-expired sessions at all times."""
        session_mgr.touch("a")
        session_mgr.touch("b")
        session_mgr.touch("c")
        assert session_mgr.count() == 3

        # Expire one
        session_mgr.set_clock(5_000)
        session_mgr.touch("b")  # refresh b
        session_mgr.touch("c")  # refresh c

        session_mgr.set_clock(15_000)
        session_mgr.reap()

        # INV-HLS-VIEWER-COUNT-ACCURATE-001 — count matches
        # "a" expired (last touch at 0, now 15s), b and c refreshed at 5s
        assert session_mgr.count() == 2

    # Tier: 1 | Structural invariant
    def test_count_zero_after_all_expire(self, session_mgr):
        """Count reaches zero after all sessions expire."""
        session_mgr.touch("a")
        session_mgr.touch("b")

        session_mgr.set_clock(20_000)
        session_mgr.reap()

        # INV-HLS-VIEWER-COUNT-ACCURATE-001 — zero when all expired
        assert session_mgr.count() == 0


# ---------------------------------------------------------------------------
# INV-HLS-SESSION-REAP-BOUNDED-001 — Bounded reap timing
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsSessionReapBounded001:
    """INV-HLS-SESSION-REAP-BOUNDED-001"""

    # Tier: 2 | Lifecycle invariant
    def test_expired_session_removed_by_reap(self):
        """Session is removed within one reap cycle after timeout."""
        mgr = FakeSessionManager(timeout_ms=10_000)
        mgr.touch("session-a")

        mgr.set_clock(11_000)  # past timeout
        mgr.reap()

        # INV-HLS-SESSION-REAP-BOUNDED-001 — removed by first reap after expiry
        assert mgr.count() == 0

    # Tier: 2 | Lifecycle invariant
    def test_reap_examines_all_sessions(self):
        """Reap sweep checks all sessions, not just recently active."""
        mgr = FakeSessionManager(timeout_ms=10_000)
        mgr.touch("old")

        mgr.set_clock(5_000)
        mgr.touch("new")

        mgr.set_clock(11_000)
        mgr.reap()

        # INV-HLS-SESSION-REAP-BOUNDED-001 — "old" expired, "new" alive
        assert mgr.count() == 1


# ---------------------------------------------------------------------------
# INV-HLS-SESSION-FIRST-VIEWER-ONCE-001 — First/last viewer atomicity
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsSessionFirstViewerOnce001:
    """INV-HLS-SESSION-FIRST-VIEWER-ONCE-001"""

    # Tier: 3 | Runtime behavior invariant
    def test_first_viewer_fires_once(self):
        """First-viewer transition fires exactly once even with multiple sessions."""
        mgr = FakeSessionManager(timeout_ms=10_000)

        mgr.touch("a")
        mgr.touch("b")
        mgr.touch("c")

        # INV-HLS-SESSION-FIRST-VIEWER-ONCE-001 — exactly once
        assert mgr._first_viewer_count == 1, (
            f"First-viewer fired {mgr._first_viewer_count} times, expected 1"
        )

    # Tier: 3 | Runtime behavior invariant
    def test_last_viewer_fires_on_zero(self):
        """Last-viewer transition fires when count reaches zero."""
        mgr = FakeSessionManager(timeout_ms=10_000)
        mgr.touch("a")
        mgr.touch("b")

        mgr.set_clock(15_000)
        mgr.reap()

        # INV-HLS-SESSION-FIRST-VIEWER-ONCE-001 — last viewer on zero
        assert mgr._last_viewer_count == 1
        assert mgr.count() == 0

    # Tier: 3 | Runtime behavior invariant
    def test_concurrent_first_touch_fires_once(self):
        """Concurrent session creation triggers first-viewer exactly once."""
        mgr = FakeSessionManager(timeout_ms=10_000)
        errors: list[str] = []
        barrier = threading.Barrier(4)

        def _touch(session_id: str):
            try:
                barrier.wait(timeout=5)
                mgr.touch(session_id)
            except Exception as e:
                errors.append(str(e))

        threads = [
            threading.Thread(target=_touch, args=(f"session-{i}",))
            for i in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == []
        assert mgr.count() == 4

        # INV-HLS-SESSION-FIRST-VIEWER-ONCE-001 — exactly once under concurrency
        assert mgr._first_viewer_count == 1, (
            f"First-viewer fired {mgr._first_viewer_count} times under concurrency"
        )

    # Tier: 3 | Runtime behavior invariant
    def test_reactivation_after_full_expiry(self):
        """After all sessions expire and reap fires last-viewer, a new touch fires first-viewer again."""
        mgr = FakeSessionManager(timeout_ms=10_000)

        mgr.touch("a")
        assert mgr._first_viewer_count == 1

        mgr.set_clock(15_000)
        mgr.reap()
        assert mgr._last_viewer_count == 1

        # New viewer after full teardown
        mgr.touch("b")

        # INV-HLS-SESSION-FIRST-VIEWER-ONCE-001 — fires again on reactivation
        assert mgr._first_viewer_count == 2
        assert mgr.count() == 1


# ---------------------------------------------------------------------------
# INV-HLS-PHANTOM-CLEANUP-001 — Failed startup cleanup
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsPhantomCleanup001:
    """INV-HLS-PHANTOM-CLEANUP-001"""

    # Tier: 2 | Lifecycle invariant
    def test_no_touch_on_failed_response(self):
        """Failed responses (simulated by not calling touch) do not refresh sessions."""
        mgr = FakeSessionManager(timeout_ms=10_000)
        mgr.touch("session-a")  # initial creation

        # Simulate: subsequent requests fail (503) — no touch called
        mgr.set_clock(15_000)
        mgr.reap()

        # INV-HLS-PHANTOM-CLEANUP-001 — session expired, no phantom persistence
        assert mgr.count() == 0

    # Tier: 2 | Lifecycle invariant
    def test_session_does_not_persist_through_errors(self):
        """A session created at startup that never receives a successful response
        is eventually reaped."""
        mgr = FakeSessionManager(timeout_ms=10_000)
        mgr.touch("phantom")  # Created on first request

        # No further touches (all responses are 503)
        mgr.set_clock(5_000)
        # Would normally touch here on 200, but 503 → no touch
        mgr.set_clock(11_000)
        mgr.reap()

        # INV-HLS-PHANTOM-CLEANUP-001 — phantom cleaned up
        assert mgr.count() == 0
