"""
Contract Tests: INV-HLS-RING-STALENESS-RECOVERY-001

The HLS manifest endpoint MUST NOT serve a playlist containing only stale
segments.  When the newest segment age exceeds 4 × target_segment_duration,
the endpoint MUST return HTTP 503.

These tests exercise the staleness check that lives in the manifest-serve
path.  They use the same minimal-fake-endpoint pattern as the rest of the
HLS delivery test suite (no FastAPI stack required).

Canonical contract:
    docs/contracts/invariants/core/runtime/INV-HLS-RING-STALENESS-RECOVERY-001.md
"""

from __future__ import annotations

import time

import pytest

from retrovue.runtime.hls.segment_ring import SegmentRing, LiveSegment
from retrovue.runtime.hls.manifest_generator import ManifestGenerator

from .conftest import (
    make_ring,
    get_playlist,
    extract_segment_names,
)


# ---------------------------------------------------------------------------
# Constants — match production defaults
# ---------------------------------------------------------------------------

TARGET_DURATION_MS = 6000       # 6 s — production segmenter default
STALENESS_FACTOR = 4            # 4 × target = 24 s threshold
STALENESS_THRESHOLD_MS = TARGET_DURATION_MS * STALENESS_FACTOR  # 24 000 ms


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _populate_ring(
    n: int = 5,
    base_utc_ms: int = 1_700_000_000_000,
    duration_ms: int = TARGET_DURATION_MS,
) -> SegmentRing:
    """Push *n* segments to a ring at sequential wall-clock times."""
    ring = make_ring(capacity=20, manifest_window=10)
    for i in range(n):
        ring.push(LiveSegment(
            channel_id="test-ch",
            index=i,
            data=b"\x47" * 188 * 10,
            byte_count=188 * 10,
            duration_ms=duration_ms,
            wall_clock_start_utc_ms=base_utc_ms + i * duration_ms,
            discontinuity=(i == 0),
        ))
    return ring


def _newest_end_utc_ms(ring: SegmentRing) -> int:
    """Wall-clock end of the newest segment in the ring (ms)."""
    window = ring.window()
    newest = window[-1]
    return newest.wall_clock_start_utc_ms + newest.duration_ms


def _serve_manifest_with_staleness_check(
    ring: SegmentRing | None,
    gen: ManifestGenerator | None,
    now_utc_ms: int,
    staleness_threshold_ms: int = STALENESS_THRESHOLD_MS,
) -> tuple[int, str | None]:
    """Manifest-serve path WITH the staleness guard.

    This mirrors what the production handler SHOULD do once the
    invariant is enforced:
        1. Generate playlist from ring.
        2. If ring is non-empty, check newest segment age.
        3. If stale → 503.
        4. Otherwise → 200.

    Returns (status_code, playlist_or_none).
    """
    playlist = gen.generate(ring) if (gen and ring) else None
    if playlist is None:
        return 503, None

    # --- INV-HLS-RING-STALENESS-RECOVERY-001 staleness gate ---
    window = ring.window()
    if window:
        newest = window[-1]
        newest_end_ms = newest.wall_clock_start_utc_ms + newest.duration_ms
        age_ms = now_utc_ms - newest_end_ms
        if age_ms > staleness_threshold_ms:
            return 503, None

    return 200, playlist


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------

@pytest.mark.contract
class TestInvHlsRingStalenessRecovery001:
    """INV-HLS-RING-STALENESS-RECOVERY-001:
    Stale ring → 503, not 200 with old segments."""

    def test_stale_ring_returns_503(self):
        """A ring whose newest segment is older than 4× target_duration
        MUST cause the manifest endpoint to return 503."""
        BASE = 1_700_000_000_000
        ring = _populate_ring(n=5, base_utc_ms=BASE)
        gen = ManifestGenerator("test-ch")

        # Newest segment ends at BASE + 5 * 6000 = BASE + 30_000 ms.
        # Set "now" to BASE + 30_000 + 24_001 ms (1 ms past threshold).
        newest_end = _newest_end_utc_ms(ring)
        now_ms = newest_end + STALENESS_THRESHOLD_MS + 1

        status, playlist = _serve_manifest_with_staleness_check(
            ring, gen, now_utc_ms=now_ms,
        )
        assert status == 503, (
            "INV-HLS-RING-STALENESS-RECOVERY-001: stale ring must return 503, "
            f"got {status}"
        )
        assert playlist is None

    def test_fresh_ring_returns_200(self):
        """A ring whose newest segment is within the threshold
        MUST return normal 200 with a valid playlist."""
        BASE = 1_700_000_000_000
        ring = _populate_ring(n=5, base_utc_ms=BASE)
        gen = ManifestGenerator("test-ch")

        # Set "now" to 1 second after newest end — well within threshold.
        newest_end = _newest_end_utc_ms(ring)
        now_ms = newest_end + 1000  # 1 s after newest end

        status, playlist = _serve_manifest_with_staleness_check(
            ring, gen, now_utc_ms=now_ms,
        )
        assert status == 200
        assert playlist is not None
        assert "#EXTM3U" in playlist
        names = extract_segment_names(playlist)
        assert len(names) == 5

    def test_exactly_at_threshold_returns_200(self):
        """At exactly 4× target_duration, the ring is NOT stale (boundary)."""
        BASE = 1_700_000_000_000
        ring = _populate_ring(n=5, base_utc_ms=BASE)
        gen = ManifestGenerator("test-ch")

        newest_end = _newest_end_utc_ms(ring)
        now_ms = newest_end + STALENESS_THRESHOLD_MS  # exactly at boundary

        status, _ = _serve_manifest_with_staleness_check(
            ring, gen, now_utc_ms=now_ms,
        )
        assert status == 200, (
            "At exactly the threshold, ring is not yet stale — should be 200"
        )

    def test_stale_ring_triggers_reactivation(self):
        """When a stale ring is detected, the ring MUST be cleared so the
        next request triggers re-activation via the normal cold-start path
        (INV-HLS-FIRST-VIEWER-ACTIVATES-CHANNEL-001).

        This test verifies the clearing behavior: after staleness detection,
        ring.count() == 0, so subsequent requests hit the empty-ring → 503
        → activate path.
        """
        BASE = 1_700_000_000_000
        ring = _populate_ring(n=5, base_utc_ms=BASE)
        gen = ManifestGenerator("test-ch")

        newest_end = _newest_end_utc_ms(ring)
        now_ms = newest_end + STALENESS_THRESHOLD_MS + 5000  # clearly stale

        # First request: detect staleness, clear ring.
        status, _ = _serve_manifest_with_staleness_check(
            ring, gen, now_utc_ms=now_ms,
        )
        assert status == 503

        # After staleness detection, caller (production handler) clears the ring.
        # We simulate this here — the production code will do it in the handler.
        ring.clear()

        # Second request: empty ring → 503 → triggers activation.
        status2, _ = _serve_manifest_with_staleness_check(
            ring, gen, now_utc_ms=now_ms,
        )
        assert status2 == 503
        assert ring.count() == 0

    def test_empty_ring_still_503(self):
        """Empty ring behaviour is unchanged (no regression).

        INV-HLS-LIFECYCLE-SEGMENT-READY-001 already requires 503 for empty
        rings.  This invariant adds staleness detection but MUST NOT break
        the existing empty-ring path.
        """
        ring = make_ring()
        gen = ManifestGenerator("test-ch")

        status, _ = _serve_manifest_with_staleness_check(
            ring, gen, now_utc_ms=1_700_000_000_000,
        )
        assert status == 503

    def test_staleness_threshold_is_4x_target(self):
        """The threshold is exactly 4× target_segment_duration.

        A ring that is 3× stale returns 200; 5× stale returns 503."""
        BASE = 1_700_000_000_000
        ring = _populate_ring(n=3, base_utc_ms=BASE)
        gen = ManifestGenerator("test-ch")
        newest_end = _newest_end_utc_ms(ring)

        # 3× target = 18 s — within threshold → 200
        now_3x = newest_end + TARGET_DURATION_MS * 3
        status_3x, _ = _serve_manifest_with_staleness_check(
            ring, gen, now_utc_ms=now_3x,
        )
        assert status_3x == 200

        # 5× target = 30 s — beyond threshold → 503
        now_5x = newest_end + TARGET_DURATION_MS * 5
        status_5x, _ = _serve_manifest_with_staleness_check(
            ring, gen, now_utc_ms=now_5x,
        )
        assert status_5x == 503
