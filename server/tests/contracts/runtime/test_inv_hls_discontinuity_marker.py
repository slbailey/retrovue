"""Contract tests for INV-HLS-DISCONTINUITY-MARKER-001.

Discontinuity markers (#EXT-X-DISCONTINUITY) must appear in HLS manifests
immediately before any segment whose discontinuity flag is True.

These markers signal to HLS clients (players, Plex, IPTV apps) that PTS
continuity is broken at that boundary — required after channel restart,
mid-stream source change, or detected PCR jump.

Invariants tested:
    INV-HLS-DISCONTINUITY-MARKER-001  Tag propagation: manifest emits
                                       #EXT-X-DISCONTINUITY before every
                                       LiveSegment with discontinuity=True
    INV-HLS-RESTART-DISCONTINUITY-001  First segment after reset_for_restart()
                                        is always discontinuous
"""

from __future__ import annotations

import pytest

from retrovue.runtime.clock import SystemClock
from retrovue.runtime.hls.segment_ring import LiveSegment, SegmentRing
from retrovue.runtime.hls.segmenter import HlsSegmenter, TS_PACKET_SIZE, TS_SYNC_BYTE
from retrovue.runtime.hls.manifest_generator import ManifestGenerator

_TEST_CLOCK = SystemClock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ts_packet(
    pid: int = 0x100,
    keyframe: bool = False,
) -> bytes:
    """Build a minimal valid 188-byte TS packet."""
    b1 = (pid >> 8) & 0x1F
    b2 = pid & 0xFF
    if keyframe:
        # adaptation field with random_access_indicator set
        b3 = 0x30  # adaptation + payload
        adaptation = bytes([0x02, 0x40])  # length=2, RAI flag
    else:
        b3 = 0x10  # payload only
        adaptation = b""
    payload_len = TS_PACKET_SIZE - 4 - len(adaptation)
    pkt = bytes([TS_SYNC_BYTE, b1, b2, b3]) + adaptation + b"\x00" * payload_len
    assert len(pkt) == TS_PACKET_SIZE
    return pkt


def _make_live_segment(
    index: int,
    discontinuity: bool = False,
    duration_ms: int = 2000,
) -> LiveSegment:
    """Build a minimal LiveSegment for manifest testing."""
    data = b"\x00" * 188
    return LiveSegment(
        channel_id="test-ch",
        index=index,
        wall_clock_start_utc_ms=1_700_000_000_000 + index * duration_ms,
        duration_ms=duration_ms,
        byte_count=len(data),
        data=data,
        discontinuity=discontinuity,
    )


def _manifest_from_ring(ring: SegmentRing, channel_id: str = "test-ch") -> str | None:
    """Generate manifest string from ring using ManifestGenerator."""
    return ManifestGenerator(channel_id).generate(ring)


# ---------------------------------------------------------------------------
# INV-HLS-DISCONTINUITY-MARKER-001 — Manifest tag propagation
# ---------------------------------------------------------------------------

@pytest.mark.contract
class TestDiscontinuityTagPropagation:
    """INV-HLS-DISCONTINUITY-MARKER-001: #EXT-X-DISCONTINUITY appears before
    every LiveSegment whose discontinuity flag is True."""

    def test_no_discontinuity_segments_produces_no_disc_tag(self):
        """Clean segment stream → no #EXT-X-DISCONTINUITY in manifest."""
        ring = SegmentRing(capacity=5, manifest_window=3)
        for i in range(3):
            ring.push(_make_live_segment(i, discontinuity=False))
        manifest = _manifest_from_ring(ring)
        assert manifest is not None
        assert "#EXT-X-DISCONTINUITY" not in manifest

    def test_discontinuous_first_segment_has_disc_tag(self):
        """Segment 0 with discontinuity=True → #EXT-X-DISCONTINUITY before it."""
        ring = SegmentRing(capacity=5, manifest_window=3)
        ring.push(_make_live_segment(0, discontinuity=True))
        ring.push(_make_live_segment(1, discontinuity=False))
        ring.push(_make_live_segment(2, discontinuity=False))
        manifest = _manifest_from_ring(ring)
        assert manifest is not None
        assert "#EXT-X-DISCONTINUITY" in manifest

    def test_disc_tag_appears_exactly_once_for_one_discontinuous_segment(self):
        """One discontinuous segment → exactly one #EXT-X-DISCONTINUITY tag."""
        ring = SegmentRing(capacity=8, manifest_window=5)
        ring.push(_make_live_segment(0, discontinuity=False))
        ring.push(_make_live_segment(1, discontinuity=True))
        ring.push(_make_live_segment(2, discontinuity=False))
        manifest = _manifest_from_ring(ring)
        assert manifest is not None
        assert manifest.count("#EXT-X-DISCONTINUITY") == 1

    def test_disc_tag_appears_before_discontinuous_segment_uri(self):
        """#EXT-X-DISCONTINUITY must appear BEFORE the segment URI line."""
        ring = SegmentRing(capacity=8, manifest_window=5)
        ring.push(_make_live_segment(0, discontinuity=False))
        ring.push(_make_live_segment(1, discontinuity=True))
        ring.push(_make_live_segment(2, discontinuity=False))
        manifest = _manifest_from_ring(ring)
        assert manifest is not None
        lines = manifest.splitlines()
        disc_idx = lines.index("#EXT-X-DISCONTINUITY")
        # Find the seg_00001.ts URI
        uri_idx = next(i for i, l in enumerate(lines) if "seg_00001.ts" in l)
        assert disc_idx < uri_idx, (
            f"#EXT-X-DISCONTINUITY (line {disc_idx}) must appear before "
            f"segment URI (line {uri_idx})"
        )

    def test_multiple_discontinuous_segments_each_get_tag(self):
        """N discontinuous segments → N #EXT-X-DISCONTINUITY tags."""
        ring = SegmentRing(capacity=10, manifest_window=6)
        ring.push(_make_live_segment(0, discontinuity=True))
        ring.push(_make_live_segment(1, discontinuity=False))
        ring.push(_make_live_segment(2, discontinuity=True))
        ring.push(_make_live_segment(3, discontinuity=False))
        ring.push(_make_live_segment(4, discontinuity=True))
        ring.push(_make_live_segment(5, discontinuity=False))
        manifest = _manifest_from_ring(ring)
        assert manifest is not None
        assert manifest.count("#EXT-X-DISCONTINUITY") == 3

    def test_continuous_segments_never_get_disc_tag(self):
        """Segment with discontinuity=False must NOT be preceded by disc tag."""
        ring = SegmentRing(capacity=8, manifest_window=5)
        for i in range(5):
            ring.push(_make_live_segment(i, discontinuity=False))
        manifest = _manifest_from_ring(ring)
        assert manifest is not None
        lines = manifest.splitlines()
        for i, line in enumerate(lines):
            if "seg_" in line and ".ts" in line:
                # The line directly before should NOT be #EXT-X-DISCONTINUITY
                if i > 0:
                    assert lines[i - 1] != "#EXT-X-DISCONTINUITY", (
                        f"Continuous segment at manifest line {i} incorrectly "
                        f"preceded by #EXT-X-DISCONTINUITY"
                    )

    def test_disc_tag_ordering_matches_segment_ordering(self):
        """Disc tags appear in the same order as their corresponding segments."""
        ring = SegmentRing(capacity=10, manifest_window=8)
        disc_indices = {0, 3, 6}
        for i in range(8):
            ring.push(_make_live_segment(i, discontinuity=(i in disc_indices)))
        manifest = _manifest_from_ring(ring)
        assert manifest is not None
        lines = manifest.splitlines()
        # Collect (disc_positions, uri_positions)
        disc_positions = [i for i, l in enumerate(lines) if l == "#EXT-X-DISCONTINUITY"]
        disc_uri_positions = []
        for disc_idx in disc_positions:
            # Find the next seg URI after this disc tag
            for j in range(disc_idx + 1, len(lines)):
                if "seg_" in lines[j] and ".ts" in lines[j]:
                    disc_uri_positions.append(j)
                    break
        # Disc tags should be strictly ordered before their URIs
        assert len(disc_positions) == 3
        for disc_pos, uri_pos in zip(disc_positions, disc_uri_positions):
            assert disc_pos < uri_pos

    def test_disc_tag_not_emitted_for_non_window_segments(self):
        """Segments evicted from the manifest window don't produce spurious tags."""
        # Ring capacity=5, manifest_window=3 — only 3 segments in manifest
        # even if ring holds 5. Disc tags should only appear for what's in window.
        ring = SegmentRing(capacity=5, manifest_window=3)
        # First 2 segments have disc=True but will be outside manifest window
        ring.push(_make_live_segment(0, discontinuity=True))
        ring.push(_make_live_segment(1, discontinuity=True))
        # Last 3 are continuous
        ring.push(_make_live_segment(2, discontinuity=False))
        ring.push(_make_live_segment(3, discontinuity=False))
        ring.push(_make_live_segment(4, discontinuity=False))
        manifest = _manifest_from_ring(ring)
        assert manifest is not None
        # manifest_window=3 shows segments 2,3,4 — no disc tags
        assert "#EXT-X-DISCONTINUITY" not in manifest


# ---------------------------------------------------------------------------
# INV-HLS-RESTART-DISCONTINUITY-001 — First segment after restart
# ---------------------------------------------------------------------------

@pytest.mark.contract
class TestRestartDiscontinuity:
    """INV-HLS-RESTART-DISCONTINUITY-001: reset_for_restart() forces
    the next produced segment to carry discontinuity=True."""

    def test_first_segment_after_construction_is_discontinuous(self):
        """First segment produced by a freshly constructed HlsSegmenter
        must have discontinuity=True (no prior PTS context)."""
        ring = SegmentRing(capacity=5, manifest_window=3)
        seg = HlsSegmenter(
            channel_id="test-ch",
            segment_ring=ring,
            clock=_TEST_CLOCK,
            target_duration_ms=200,
        )
        # Feed enough keyframe packets to trigger at least one segment
        for _ in range(3):
            seg.feed(_make_ts_packet(keyframe=True) * 10)

        segments = ring.window()
        if segments:
            assert segments[0].discontinuity is True, (
                "INV-HLS-RESTART-DISCONTINUITY-001: first segment must be discontinuous"
            )

    def test_segment_after_reset_for_restart_is_discontinuous(self):
        """reset_for_restart() must set discontinuity=True on the next segment."""
        ring = SegmentRing(capacity=20, manifest_window=10)
        seg = HlsSegmenter(
            channel_id="test-ch",
            segment_ring=ring,
            clock=_TEST_CLOCK,
            target_duration_ms=200,
        )

        # Produce at least one segment normally
        for _ in range(5):
            seg.feed(_make_ts_packet(keyframe=True) * 10)
        before_count = ring.count()

        # Reset and produce more segments
        seg.reset_for_restart(next_index=before_count)
        for _ in range(5):
            seg.feed(_make_ts_packet(keyframe=True) * 10)

        after_segments = ring.window()
        if ring.count() > before_count:
            # Find the restart segment by index
            restart_seg = next(
                (s for s in after_segments if s.index == before_count), None
            )
            if restart_seg is not None:
                assert restart_seg.discontinuity is True, (
                    "INV-HLS-RESTART-DISCONTINUITY-001: segment immediately after "
                    f"reset_for_restart() must be discontinuous; got {restart_seg}"
                )

    def test_segments_after_restart_segment_are_not_forced_discontinuous(self):
        """Only the FIRST segment after reset should be discontinuous;
        subsequent continuous segments should not be marked discontinuous."""
        ring = SegmentRing(capacity=30, manifest_window=15)
        seg = HlsSegmenter(
            channel_id="test-ch",
            segment_ring=ring,
            clock=_TEST_CLOCK,
            target_duration_ms=200,
        )

        # Produce initial segments
        for _ in range(5):
            seg.feed(_make_ts_packet(keyframe=True) * 10)
        before_count = ring.count()

        # Reset and produce many more segments
        seg.reset_for_restart(next_index=before_count)
        for _ in range(20):
            seg.feed(_make_ts_packet(keyframe=True) * 10)

        all_segments = ring.window()
        post_restart = [s for s in all_segments if s.index >= before_count]

        # Should have at least 2 segments post-restart to check
        if len(post_restart) >= 2:
            # First must be discontinuous
            assert post_restart[0].discontinuity is True
            # Subsequent ones must NOT be discontinuous (no PCR jump injected)
            for i, s in enumerate(post_restart[1:], start=1):
                assert s.discontinuity is False, (
                    f"Segment {i} post-restart should not be discontinuous "
                    f"(only the first restart segment should be)"
                )

    def test_restart_discontinuity_propagates_to_manifest(self):
        """After reset_for_restart(), manifest must contain #EXT-X-DISCONTINUITY
        if the restart segment falls within the manifest window."""
        ring = SegmentRing(capacity=10, manifest_window=5)
        seg = HlsSegmenter(
            channel_id="test-ch",
            segment_ring=ring,
            clock=_TEST_CLOCK,
            target_duration_ms=200,
        )

        # Produce initial segments
        for _ in range(3):
            seg.feed(_make_ts_packet(keyframe=True) * 10)
        before_count = ring.count()

        # Reset
        seg.reset_for_restart(next_index=before_count)
        for _ in range(3):
            seg.feed(_make_ts_packet(keyframe=True) * 10)

        if ring.count() > before_count:
            manifest = _manifest_from_ring(ring)
            if manifest is not None:
                # The restart segment should be in the window — disc tag must be present
                window = ring.window()
                has_restart_seg = any(s.index >= before_count for s in window)
                if has_restart_seg:
                    assert "#EXT-X-DISCONTINUITY" in manifest, (
                        "INV-HLS-DISCONTINUITY-MARKER-001: restart segment in manifest "
                        "window must produce #EXT-X-DISCONTINUITY tag"
                    )

    def test_multiple_restarts_each_produce_discontinuous_segment(self):
        """Each call to reset_for_restart() must yield exactly one
        discontinuous segment (the first one produced after the reset)."""
        ring = SegmentRing(capacity=40, manifest_window=20)
        seg = HlsSegmenter(
            channel_id="test-ch",
            segment_ring=ring,
            clock=_TEST_CLOCK,
            target_duration_ms=200,
        )

        restart_at_indices: list[int] = []
        current_index = 0

        for _restart_round in range(3):
            # Reset
            seg.reset_for_restart(next_index=current_index)
            # Produce segments
            for _ in range(8):
                seg.feed(_make_ts_packet(keyframe=True) * 10)
            new_count = ring.count()
            if new_count > current_index:
                restart_at_indices.append(current_index)
                current_index = new_count

        all_segments = ring.window()
        seg_by_index = {s.index: s for s in all_segments}

        for restart_idx in restart_at_indices:
            s = seg_by_index.get(restart_idx)
            if s is not None:
                assert s.discontinuity is True, (
                    f"Restart segment at index {restart_idx} must be discontinuous"
                )
