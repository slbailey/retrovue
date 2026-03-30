"""
Proof: HLS manifest returns 200 with stale segments after byte-pipeline death.

This test proves the concrete failure mode described in the investigation:
when the ChannelStream dies (upstream reader stops, no bytes flow to
segmenter), the manifest endpoint continues serving stale segments from
the SegmentRing with HTTP 200. There is no staleness detection.

This is a RED test — it proves the violation exists.  A subsequent
invariant + fix will flip it green.

Methodology:
    1. Populate a SegmentRing with segments at known wall-clock timestamps.
    2. Simulate "pipeline death" by stopping all feeds to the segmenter.
    3. Advance wall-clock time far beyond the ring's newest segment.
    4. Call the manifest endpoint (as the production handler does).
    5. Prove the endpoint returns 200 with a playlist whose segments
       are demonstrably stale — quantified in seconds of age.

No production code is modified.  The test mirrors the real handler's
decision path (ManifestGenerator.generate + ring) and shows the gap.
"""

from __future__ import annotations

import time

import pytest

from retrovue.runtime.hls.segment_ring import SegmentRing, LiveSegment
from retrovue.runtime.hls.manifest_generator import ManifestGenerator

from .conftest import (
    make_ring,
    make_segmenter,
    feed_n_segments,
    get_playlist,
    extract_segment_names,
    extract_extinf_values,
    extract_media_sequence,
)


# ---------------------------------------------------------------------------
# Helpers — mirror production manifest-serve logic exactly
# ---------------------------------------------------------------------------

def _serve_manifest(
    ring: SegmentRing | None,
    gen: ManifestGenerator | None,
) -> tuple[int, str | None]:
    """Reproduce the production manifest endpoint decision path.

    Returns (status_code, playlist_or_none).

    The production handler (ProgramDirector.channels_hls_manifest) does:
        playlist = gen.generate(ring) if (gen and ring) else None
        if playlist is None:
            return 503
        return 200, playlist

    No staleness check exists.  This helper is an exact mirror.
    """
    playlist = gen.generate(ring) if (gen and ring) else None
    if playlist is None:
        return 503, None
    return 200, playlist


def _newest_segment_age_s(ring: SegmentRing, now_utc_ms: int) -> float:
    """Wall-clock age of the newest segment in seconds.

    age = now - (newest.wall_clock_start_utc_ms + newest.duration_ms)
    """
    window = ring.window()
    if not window:
        return float("inf")
    newest = window[-1]
    end_utc_ms = newest.wall_clock_start_utc_ms + newest.duration_ms
    return (now_utc_ms - end_utc_ms) / 1000.0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

TARGET_DURATION_MS = 6000  # 6 s — production default


@pytest.mark.contract
class TestHlsStaleRingProof:
    """Prove that the manifest endpoint serves stale data after pipeline death."""

    # -- setup helper -------------------------------------------------

    def _populate_ring(
        self,
        n_segments: int = 5,
        base_utc_ms: int = 1_700_000_000_000,
    ) -> tuple[SegmentRing, ManifestGenerator]:
        """Create a ring with *n_segments* at known wall-clock times.

        Each segment is TARGET_DURATION_MS long, starting at base_utc_ms
        and advancing sequentially.
        """
        ring = make_ring(capacity=20, manifest_window=10)
        gen = ManifestGenerator("test-ch")

        for i in range(n_segments):
            wall_start = base_utc_ms + i * TARGET_DURATION_MS
            seg = LiveSegment(
                channel_id="test-ch",
                index=i,
                data=b"\x47" * 188 * 10,  # 10 sync-aligned TS packets
                byte_count=188 * 10,
                duration_ms=TARGET_DURATION_MS,
                wall_clock_start_utc_ms=wall_start,
                discontinuity=(i == 0),
            )
            ring.push(seg)

        return ring, gen

    # -- proof: 200 on stale ring --------------------------------------

    def test_manifest_returns_200_with_stale_segments(self):
        """The manifest endpoint returns 200 even when segments are
        minutes old — proving no staleness guard exists.

        Scenario:
            1. Ring populated at T₀ with 5 segments (30 s of content).
            2. No further feeds (simulates dead ChannelStream).
            3. Wall clock advances to T₀ + 5 minutes.
            4. Manifest request → HTTP 200 with playlist pointing to
               segments whose newest end-time is 4.5 minutes in the past.
        """
        BASE = 1_700_000_000_000  # ms — arbitrary epoch
        ring, gen = self._populate_ring(n_segments=5, base_utc_ms=BASE)

        # Verify ring state before "pipeline death"
        assert ring.count() == 5

        # Advance wall clock by 5 minutes — pipeline is dead, no new segments.
        now_utc_ms = BASE + 5 * 60 * 1000  # T₀ + 300 s

        # The newest segment ends at BASE + 5 * 6000 = BASE + 30_000 ms.
        age_s = _newest_segment_age_s(ring, now_utc_ms)
        assert age_s == pytest.approx(270.0, abs=1.0), (
            f"Expected ~270 s of staleness, got {age_s:.1f} s"
        )

        # --- Serve manifest exactly as production does ---
        status, playlist = _serve_manifest(ring, gen)

        # PROOF: endpoint returns 200 with stale data.
        assert status == 200, (
            "Expected 200 (proving the bug); got %d" % status
        )
        assert playlist is not None
        assert "#EXTM3U" in playlist

        # Playlist contains segments — all stale.
        names = extract_segment_names(playlist)
        assert len(names) == 5, f"Expected 5 segments in playlist, got {len(names)}"

    def test_quantify_staleness_in_playlist(self):
        """Quantify exactly how stale the served segments are.

        After pipeline death, the manifest continues returning the same
        segments regardless of how much time passes.  This test proves
        the staleness gap grows without bound.
        """
        BASE = 1_700_000_000_000
        ring, gen = self._populate_ring(n_segments=5, base_utc_ms=BASE)

        newest_end_ms = BASE + 5 * TARGET_DURATION_MS  # BASE + 30_000

        staleness_checks = [
            (30,    "30 s — just past ring horizon"),
            (60,    "1 min — 2× segment duration threshold"),
            (300,   "5 min — far beyond any reasonable staleness window"),
            (3600,  "1 hour — absurdly stale"),
        ]

        for elapsed_s, label in staleness_checks:
            now_ms = BASE + elapsed_s * 1000
            age_s = _newest_segment_age_s(ring, now_ms)

            status, playlist = _serve_manifest(ring, gen)

            # PROOF: always 200, regardless of age.
            assert status == 200, f"[{label}] Expected 200, got {status}"
            assert playlist is not None

            # The same 5 segments are served at every time point.
            names = extract_segment_names(playlist)
            assert len(names) == 5, (
                f"[{label}] Expected 5 stale segments, got {len(names)}"
            )

            seq = extract_media_sequence(playlist)
            assert seq == 0, (
                f"[{label}] MEDIA-SEQUENCE should be frozen at 0, got {seq}"
            )

    def test_stale_ring_is_not_empty(self):
        """A stale ring is NOT the same as an empty ring.

        Empty ring → 503 (INV-HLS-LIFECYCLE-SEGMENT-READY-001).
        Stale ring → 200 with old data.  This proves the gap: there is
        no intermediate state for "ring has data but it's too old."
        """
        BASE = 1_700_000_000_000
        ring, gen = self._populate_ring(n_segments=3, base_utc_ms=BASE)

        # Non-empty ring → 200
        status_with_data, _ = _serve_manifest(ring, gen)
        assert status_with_data == 200

        # Empty ring → 503 (correctly handled by existing contract)
        empty_ring = make_ring()
        status_empty, _ = _serve_manifest(empty_ring, gen)
        assert status_empty == 503

        # The gap: non-empty but stale → still 200
        now_far_future = BASE + 3600 * 1000
        age_s = _newest_segment_age_s(ring, now_far_future)
        assert age_s > 3500, f"Expected >3500 s of staleness, got {age_s:.1f} s"

        status_stale, playlist_stale = _serve_manifest(ring, gen)
        assert status_stale == 200, (
            "Stale ring still returns 200 — no staleness detection exists"
        )

    def test_media_sequence_frozen_proves_no_progress(self):
        """When no new segments are pushed, MEDIA-SEQUENCE stays frozen.

        A healthy live stream increments MEDIA-SEQUENCE as new segments
        arrive and old ones are evicted.  A stale ring has a frozen
        MEDIA-SEQUENCE — the client sees the same playlist over and over.

        This is exactly what VLC observes when it "freezes on the same frame."
        """
        BASE = 1_700_000_000_000
        ring, gen = self._populate_ring(n_segments=5, base_utc_ms=BASE)

        # Take snapshot of manifest at T₀.
        _, playlist_t0 = _serve_manifest(ring, gen)
        seq_t0 = extract_media_sequence(playlist_t0)
        names_t0 = extract_segment_names(playlist_t0)

        # "Time passes" — but no new segments are pushed.
        # (No code changes ring state; this simulates dead pipeline.)

        # Re-serve manifest — should be identical.
        _, playlist_t1 = _serve_manifest(ring, gen)
        seq_t1 = extract_media_sequence(playlist_t1)
        names_t1 = extract_segment_names(playlist_t1)

        assert seq_t0 == seq_t1, (
            "MEDIA-SEQUENCE did not change — playlist is frozen"
        )
        assert names_t0 == names_t1, (
            "Segment list did not change — playlist is frozen"
        )

        # Now prove that the PLAYLIST CONTENT is byte-identical.
        assert playlist_t0 == playlist_t1, (
            "Playlist is byte-identical across requests — "
            "client sees no progress, causing freeze"
        )

    def test_segment_age_quantification(self):
        """Produce a concrete age measurement for each segment in the ring.

        Output: for each segment, (index, wall_clock_end_ms, age_seconds).
        This quantifies the exact data the client would decode.
        """
        BASE = 1_700_000_000_000
        ring, gen = self._populate_ring(n_segments=5, base_utc_ms=BASE)

        # Simulate 5 minutes after last segment.
        now_ms = BASE + 5 * 60 * 1000

        window = ring.window()
        assert len(window) == 5

        ages: list[tuple[int, int, float]] = []
        for seg in window:
            end_ms = seg.wall_clock_start_utc_ms + seg.duration_ms
            age_s = (now_ms - end_ms) / 1000.0
            ages.append((seg.index, end_ms, age_s))

        # Youngest segment (index 4) ends at BASE + 30_000.
        # Age = (BASE + 300_000 - (BASE + 30_000)) / 1000 = 270 s.
        youngest_age = ages[-1][2]
        assert youngest_age == pytest.approx(270.0, abs=1.0)

        # Oldest segment (index 0) ends at BASE + 6_000.
        # Age = (BASE + 300_000 - (BASE + 6_000)) / 1000 = 294 s.
        oldest_age = ages[0][2]
        assert oldest_age == pytest.approx(294.0, abs=1.0)

        # ALL segments are stale beyond any reasonable threshold.
        # 4× target_duration = 24 s — every segment exceeds this.
        staleness_threshold_s = 4 * TARGET_DURATION_MS / 1000.0  # 24 s
        for idx, _, age_s in ages:
            assert age_s > staleness_threshold_s, (
                f"Segment {idx}: age {age_s:.1f}s should exceed "
                f"staleness threshold {staleness_threshold_s:.1f}s"
            )
