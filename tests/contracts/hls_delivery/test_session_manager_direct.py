"""
Contract Tests: HlsSessionManager (Direct)

Canonical contract:
    docs/contracts/delivery_hls.md — §5 Viewer Presence Contract

These tests exercise the production HlsSessionManager directly,
validating the same invariants as test_viewer_presence.py
(which tests the behavioral contract via an inline fake).

INV-HLS-VIEWER-PRESENCE-001
INV-HLS-VIEWER-COUNT-ACCURATE-001
INV-HLS-SESSION-REAP-BOUNDED-001
INV-HLS-SESSION-FIRST-VIEWER-ONCE-001
INV-HLS-PHANTOM-CLEANUP-001
"""

from __future__ import annotations

import threading

import pytest

from retrovue.runtime.hls.session_manager import HlsSessionManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mgr(
    timeout_ms: int = 10_000,
    reap_interval_ms: int = 5_000,
) -> HlsSessionManager:
    return HlsSessionManager(
        channel_id="test-ch",
        session_timeout_ms=timeout_ms,
        reap_interval_ms=reap_interval_ms,
    )


# ---------------------------------------------------------------------------
# INV-HLS-VIEWER-PRESENCE-001 — Request-based detection
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestHlsSessionManagerPresence:
    """INV-HLS-VIEWER-PRESENCE-001"""

    def test_first_touch_creates_session(self):
        mgr = _make_mgr()
        assert mgr.count() == 0
        mgr.touch("a")
        assert mgr.count() == 1

    def test_repeated_touch_does_not_duplicate(self):
        mgr = _make_mgr()
        mgr.touch("a")
        mgr.touch("a")
        mgr.touch("a")
        assert mgr.count() == 1

    def test_multiple_sessions_independent(self):
        mgr = _make_mgr()
        mgr.touch("a")
        mgr.touch("b")
        mgr.touch("c")
        assert mgr.count() == 3

    def test_expired_session_reaped(self):
        mgr = _make_mgr()
        mgr.touch("a")
        mgr.set_clock(15_000)
        mgr.reap()
        assert mgr.count() == 0

    def test_refreshed_session_survives(self):
        mgr = _make_mgr()
        mgr.touch("a")
        mgr.set_clock(5_000)
        mgr.touch("a")
        mgr.set_clock(12_000)
        mgr.reap()
        assert mgr.count() == 1

    def test_remove_session(self):
        mgr = _make_mgr()
        mgr.touch("a")
        mgr.touch("b")
        mgr.remove("a")
        assert mgr.count() == 1

    def test_remove_nonexistent_is_noop(self):
        mgr = _make_mgr()
        mgr.remove("nonexistent")  # should not raise
        assert mgr.count() == 0


# ---------------------------------------------------------------------------
# INV-HLS-VIEWER-COUNT-ACCURATE-001 — Count matches state
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestHlsSessionManagerCount:
    """INV-HLS-VIEWER-COUNT-ACCURATE-001"""

    def test_count_after_partial_expiry(self):
        mgr = _make_mgr()
        mgr.touch("a")
        mgr.touch("b")
        mgr.touch("c")
        mgr.set_clock(5_000)
        mgr.touch("b")
        mgr.touch("c")
        mgr.set_clock(15_000)
        mgr.reap()
        assert mgr.count() == 2

    def test_count_zero_after_all_expire(self):
        mgr = _make_mgr()
        mgr.touch("a")
        mgr.touch("b")
        mgr.set_clock(20_000)
        mgr.reap()
        assert mgr.count() == 0

    def test_count_after_remove(self):
        mgr = _make_mgr()
        mgr.touch("a")
        mgr.touch("b")
        mgr.touch("c")
        mgr.remove("b")
        assert mgr.count() == 2


# ---------------------------------------------------------------------------
# INV-HLS-SESSION-REAP-BOUNDED-001 — Bounded reap timing
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestHlsSessionManagerReapBounded:
    """INV-HLS-SESSION-REAP-BOUNDED-001"""

    def test_reap_interval_clamped_to_half_timeout(self):
        mgr = HlsSessionManager(
            channel_id="test",
            session_timeout_ms=10_000,
            reap_interval_ms=8_000,  # exceeds timeout/2
        )
        assert mgr.reap_interval_ms <= 10_000 // 2

    def test_valid_reap_interval_accepted(self):
        mgr = HlsSessionManager(
            channel_id="test",
            session_timeout_ms=10_000,
            reap_interval_ms=4_000,
        )
        assert mgr.reap_interval_ms == 4_000

    def test_reap_examines_all_sessions(self):
        mgr = _make_mgr()
        mgr.touch("old")
        mgr.set_clock(5_000)
        mgr.touch("new")
        mgr.set_clock(11_000)
        mgr.reap()
        assert mgr.count() == 1

    def test_reap_expired_with_explicit_now(self):
        mgr = _make_mgr()
        mgr.touch("a")
        mgr.reap_expired(now_ms=15_000)
        assert mgr.count() == 0


# ---------------------------------------------------------------------------
# INV-HLS-SESSION-FIRST-VIEWER-ONCE-001 — First/last viewer atomicity
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestHlsSessionManagerFirstViewer:
    """INV-HLS-SESSION-FIRST-VIEWER-ONCE-001"""

    def test_first_viewer_fires_once(self):
        mgr = _make_mgr()
        mgr.touch("a")
        mgr.touch("b")
        mgr.touch("c")
        assert mgr._first_viewer_count == 1

    def test_last_viewer_on_full_expiry(self):
        mgr = _make_mgr()
        mgr.touch("a")
        mgr.touch("b")
        mgr.set_clock(15_000)
        mgr.reap()
        assert mgr._last_viewer_count == 1
        assert mgr.count() == 0

    def test_last_viewer_on_remove(self):
        mgr = _make_mgr()
        mgr.touch("a")
        mgr.remove("a")
        assert mgr._last_viewer_count == 1

    def test_reactivation_fires_first_viewer_again(self):
        mgr = _make_mgr()
        mgr.touch("a")
        assert mgr._first_viewer_count == 1

        mgr.set_clock(15_000)
        mgr.reap()
        assert mgr._last_viewer_count == 1

        mgr.touch("b")
        assert mgr._first_viewer_count == 2
        assert mgr.count() == 1

    def test_concurrent_first_touch(self):
        mgr = _make_mgr()
        errors: list[str] = []
        barrier = threading.Barrier(4)

        def _touch(sid: str):
            try:
                barrier.wait(timeout=5)
                mgr.touch(sid)
            except Exception as e:
                errors.append(str(e))

        threads = [
            threading.Thread(target=_touch, args=(f"s-{i}",))
            for i in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == []
        assert mgr.count() == 4
        assert mgr._first_viewer_count == 1

    def test_callback_invoked_on_first_viewer(self):
        calls: list[str] = []
        mgr = HlsSessionManager(
            channel_id="test",
            session_timeout_ms=10_000,
            reap_interval_ms=5_000,
            viewer_join_callback=lambda: calls.append("join"),
            viewer_leave_callback=lambda: calls.append("leave"),
        )
        mgr.touch("a")
        assert calls == ["join"]

        mgr.touch("b")
        assert calls == ["join"]  # not fired again

    def test_callback_invoked_on_last_viewer(self):
        calls: list[str] = []
        mgr = HlsSessionManager(
            channel_id="test",
            session_timeout_ms=10_000,
            reap_interval_ms=5_000,
            viewer_join_callback=lambda: calls.append("join"),
            viewer_leave_callback=lambda: calls.append("leave"),
        )
        mgr.touch("a")
        mgr.set_clock(15_000)
        mgr.reap()
        assert calls == ["join", "leave"]


# ---------------------------------------------------------------------------
# INV-HLS-PHANTOM-CLEANUP-001 — Failed startup cleanup
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestHlsSessionManagerPhantom:
    """INV-HLS-PHANTOM-CLEANUP-001"""

    def test_untouched_session_expires(self):
        mgr = _make_mgr()
        mgr.touch("phantom")
        mgr.set_clock(15_000)
        mgr.reap()
        assert mgr.count() == 0

    def test_session_not_refreshed_by_failed_responses(self):
        mgr = _make_mgr()
        mgr.touch("a")
        # Simulate: no further touch calls (all responses are 503)
        mgr.set_clock(5_000)
        mgr.set_clock(11_000)
        mgr.reap()
        assert mgr.count() == 0
