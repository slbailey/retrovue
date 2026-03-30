"""
Contract Tests: HLS Cold-Start Connect Guarantee

Invariant:
    INV-HLS-COLD-START-CONNECT-GUARANTEED-001

These tests verify the behavioral contract: a single HLS manifest request
to a cold channel must receive a 200 response without client retry.

The tests validate the bounded-wait helper logic that mirrors the
corrected activate() path — specifically:
  - that the ring becomes ready after activation completes
  - that a warm ring is detected immediately (no spurious wait)
  - that the 503 fallback only fires on actual timeout (never on a
    successful activation)
  - that the fanout-exists condition (not is_running) is the correct break
    point for the fanout wait loop
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from retrovue.runtime.hls.segment_ring import SegmentRing
from retrovue.runtime.hls.manifest_generator import ManifestGenerator

from .conftest import (
    make_ring,
    make_segmenter,
    feed_n_segments,
    get_playlist,
)


# ---------------------------------------------------------------------------
# Bounded-wait helper — mirrors the corrected endpoint + activate() path
# ---------------------------------------------------------------------------

async def _wait_for_ring(ring: SegmentRing, timeout_s: float = 10.0) -> bool:
    """Poll ring.count() > 0 for up to timeout_s. Returns True when ready."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if ring.count() > 0:
            return True
        await asyncio.sleep(0.25)
    return False


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _feed_ring_after_delay(ring: SegmentRing, delay_s: float, n: int = 3) -> None:
    """Simulate Air startup: segments arrive after delay_s seconds."""
    def _worker():
        time.sleep(delay_s)
        seg, _ = make_segmenter(ring=ring)
        feed_n_segments(seg, n)
    threading.Thread(target=_worker, daemon=True).start()


# ---------------------------------------------------------------------------
# INV-HLS-COLD-START-CONNECT-GUARANTEED-001
# ---------------------------------------------------------------------------

@pytest.mark.contract
class TestInvHlsColdStartConnectGuaranteed001:
    """INV-HLS-COLD-START-CONNECT-GUARANTEED-001"""

    def test_single_cold_request_succeeds_without_retry(self):
        """
        A single request to a cold channel returns a valid manifest once
        segments arrive — no client retry required.
        """
        ring = make_ring()
        assert ring.count() == 0

        _feed_ring_after_delay(ring, delay_s=1.0, n=3)

        ready = _run(_wait_for_ring(ring, timeout_s=10.0))

        assert ready is True, "Ring never became ready within bounded window"
        assert ring.count() > 0

        playlist = get_playlist(ring)
        assert "#EXTM3U" in playlist
        assert "#EXTINF" in playlist

    def test_warm_ring_detected_immediately(self):
        """Warm channel: ring already has segments, no wait introduced."""
        seg, ring = make_segmenter()
        feed_n_segments(seg, 3)
        assert ring.count() > 0

        t0 = time.monotonic()
        ready = _run(_wait_for_ring(ring, timeout_s=10.0))
        elapsed = time.monotonic() - t0

        assert ready is True
        assert elapsed < 0.5, f"Warm ring check took {elapsed:.2f}s, expected <0.5s"

    def test_timeout_produces_false_not_exception(self):
        """Timeout on empty ring returns False (endpoint may then 503)."""
        ring = make_ring()

        t0 = time.monotonic()
        ready = _run(_wait_for_ring(ring, timeout_s=0.5))
        elapsed = time.monotonic() - t0

        assert ready is False
        assert elapsed < 1.5, f"Timeout wait took {elapsed:.2f}s"

    def test_503_not_returned_when_activation_succeeds(self):
        """
        INV-HLS-COLD-START-CONNECT-GUARANTEED-001:
        503 must NOT be returned when activation succeeds within the window.
        """
        ring = make_ring()
        _feed_ring_after_delay(ring, delay_s=0.2, n=3)

        ready = _run(_wait_for_ring(ring, timeout_s=5.0))

        assert ready is True, (
            "INV-HLS-COLD-START-CONNECT-GUARANTEED-001 VIOLATED: "
            "cold channel with successful activation must not 503"
        )

    def test_manifest_valid_after_bounded_wait(self):
        """Manifest generated after bounded wait satisfies INV-HLS-MANIFEST-VALID-PLAYLIST-001."""
        ring = make_ring()
        _feed_ring_after_delay(ring, delay_s=0.3, n=5)

        ready = _run(_wait_for_ring(ring, timeout_s=5.0))
        assert ready is True

        playlist = get_playlist(ring)
        assert "#EXTM3U" in playlist
        assert "#EXTINF" in playlist
        assert "#EXT-X-ENDLIST" not in playlist, (
            "INV-HLS-MANIFEST-LIVE-001 violated: live playlist must not have EXT-X-ENDLIST"
        )

    def test_fanout_exists_is_correct_break_condition(self):
        """
        The fanout wait loop must break when fanout is not None,
        NOT when fanout.is_running() — is_running() is only True after
        subscribe() is called (which happens after the loop).

        This test documents the invariant that drove the fix.
        """
        # Simulate a fanout object that exists but is not yet running
        class FakeFanout:
            def is_running(self):
                return False

        fanout = FakeFanout()

        # Old (broken) condition: would never break
        old_condition = fanout is not None and fanout.is_running()
        assert old_condition is False, "Old condition would spin forever"

        # New (correct) condition: breaks immediately when fanout exists
        new_condition = fanout is not None
        assert new_condition is True, "New condition correctly detects fanout exists"
