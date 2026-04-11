"""Contract tests: INV-HLS-RESTART-DISCONTINUITY-001

When a producer restarts (failure recovery or viewer departure + return),
the first segment produced after restart MUST carry discontinuity=True.
The segmenter's PTS tracker MUST reset. Segment indices MUST continue
from the channel's counter (not reset to zero).
"""

from __future__ import annotations

import pytest

try:
    from retrovue.runtime.hls.segmenter import HlsSegmenter
    from retrovue.runtime.hls.segment_ring import SegmentRing, LiveSegment
except ImportError:
    pytest.skip(
        "retrovue.runtime.hls not available",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_segmenter(
    channel_id: str = "test-channel",
    capacity: int = 10,
    manifest_window: int = 3,
    starting_index: int = 0,
) -> tuple[HlsSegmenter, SegmentRing]:
    """Create a segmenter + ring pair for testing."""
    ring = SegmentRing(capacity=capacity, manifest_window=manifest_window)
    segmenter = HlsSegmenter(
        channel_id=channel_id,
        segment_ring=ring,
        target_duration_ms=6000,
        starting_index=starting_index,
    )
    return segmenter, ring


# ===========================================================================
# INV-HLS-RESTART-DISCONTINUITY-001 — Discontinuity on restart
# ===========================================================================


class TestHlsRestartDiscontinuity:
    """INV-HLS-RESTART-DISCONTINUITY-001: After a producer restart,
    the first segment MUST carry discontinuity=True.
    """

    def test_initial_construction_forces_discontinuity(self):
        """A newly constructed segmenter must force discontinuity on its
        first segment (no prior PTS context exists).
        """
        segmenter, _ = _make_segmenter()
        # _force_next_discontinuity is set True at construction
        assert segmenter._force_next_discontinuity is True, (
            "INV-HLS-RESTART-DISCONTINUITY-001: new segmenter must "
            "force discontinuity on first segment"
        )

    def test_reset_for_restart_forces_discontinuity(self):
        """After reset_for_restart(), the next segment must carry
        discontinuity=True.
        """
        segmenter, _ = _make_segmenter(starting_index=0)

        # Simulate: clear the initial flag as if segments were produced
        segmenter._force_next_discontinuity = False

        # Now restart
        segmenter.reset_for_restart(next_index=5)

        assert segmenter._force_next_discontinuity is True, (
            "INV-HLS-RESTART-DISCONTINUITY-001: reset_for_restart must "
            "force discontinuity on next segment"
        )

    def test_reset_for_restart_resets_pts_tracking(self):
        """After reset_for_restart(), PTS continuity tracking must be cleared
        so the segmenter treats the next input as a fresh stream.
        """
        segmenter, _ = _make_segmenter()

        # Simulate some PTS state from prior session
        segmenter._last_pcr = 12345678
        segmenter._seg_start_pcr = 12000000
        segmenter._prev_segment_end_pcr = 12345678

        segmenter.reset_for_restart(next_index=10)

        assert segmenter._last_pcr is None, (
            "INV-HLS-RESTART-DISCONTINUITY-001: _last_pcr must be None after restart"
        )
        assert segmenter._seg_start_pcr is None, (
            "INV-HLS-RESTART-DISCONTINUITY-001: _seg_start_pcr must be None after restart"
        )
        assert segmenter._prev_segment_end_pcr is None, (
            "INV-HLS-RESTART-DISCONTINUITY-001: _prev_segment_end_pcr must be None after restart"
        )

    def test_reset_for_restart_continues_index(self):
        """After reset_for_restart(next_index=N), the next segment index
        must be N — not 0 or 1.
        """
        segmenter, _ = _make_segmenter(starting_index=0)

        segmenter.reset_for_restart(next_index=42)

        assert segmenter._next_index == 42, (
            "INV-HLS-RESTART-DISCONTINUITY-001: index must continue from "
            f"next_index=42, got {segmenter._next_index}"
        )

    def test_reset_clears_accumulation_buffer(self):
        """After reset, the internal byte buffer must be cleared so stale
        data from the prior session does not bleed into new segments.
        """
        segmenter, _ = _make_segmenter()

        # Simulate accumulated bytes from prior session
        segmenter._seg_buffer = bytearray(b"\x47" * 188 * 10)
        segmenter._seg_pkt_count = 10
        segmenter._leftover = bytearray(b"\x47" * 100)

        segmenter.reset_for_restart(next_index=5)

        assert len(segmenter._seg_buffer) == 0, (
            "INV-HLS-RESTART-DISCONTINUITY-001: seg_buffer must be cleared after restart"
        )
        assert segmenter._seg_pkt_count == 0, (
            "INV-HLS-RESTART-DISCONTINUITY-001: packet count must be 0 after restart"
        )
        assert len(segmenter._leftover) == 0, (
            "INV-HLS-RESTART-DISCONTINUITY-001: leftover must be cleared after restart"
        )

    def test_reset_reopens_closed_segmenter(self):
        """A closed segmenter must be reopened by reset_for_restart so it
        can accept new feed() calls after restart.
        """
        segmenter, _ = _make_segmenter()
        segmenter.close()
        assert segmenter._closed is True

        segmenter.reset_for_restart(next_index=1)
        assert segmenter._closed is False, (
            "INV-HLS-RESTART-DISCONTINUITY-001: segmenter must be reopened after restart"
        )


# ===========================================================================
# INV-HLS-DISCONTINUITY-MARKER-001 — Manifest propagation
# ===========================================================================


class TestHlsDiscontinuityMarker:
    """INV-HLS-DISCONTINUITY-MARKER-001: LiveSegment.discontinuity=True
    must produce #EXT-X-DISCONTINUITY in the manifest.
    """

    def test_live_segment_discontinuity_field_exists(self):
        """LiveSegment must have a 'discontinuity' field defaulting to False."""
        seg = LiveSegment(
            channel_id="test",
            index=0,
            wall_clock_start_utc_ms=1000,
            duration_ms=6000,
            byte_count=188,
            data=b"\x47" * 188,
        )
        assert seg.discontinuity is False

    def test_live_segment_discontinuity_can_be_true(self):
        """LiveSegment must accept discontinuity=True."""
        seg = LiveSegment(
            channel_id="test",
            index=0,
            wall_clock_start_utc_ms=1000,
            duration_ms=6000,
            byte_count=188,
            data=b"\x47" * 188,
            discontinuity=True,
        )
        assert seg.discontinuity is True

    def test_manifest_generator_emits_discontinuity_tag(self):
        """The manifest generator must emit #EXT-X-DISCONTINUITY before
        segments with discontinuity=True.
        """
        try:
            from retrovue.runtime.hls.manifest_generator import generate_manifest
        except ImportError:
            pytest.skip("manifest_generator not available")

        ring = SegmentRing(capacity=10, manifest_window=3, min_ready_segments=1)

        # Push 2 segments: first normal, second with discontinuity
        ring.push(LiveSegment(
            channel_id="test", index=0,
            wall_clock_start_utc_ms=1000, duration_ms=6000,
            byte_count=188, data=b"\x47" * 188,
            discontinuity=False,
        ))
        ring.push(LiveSegment(
            channel_id="test", index=1,
            wall_clock_start_utc_ms=7000, duration_ms=6000,
            byte_count=188, data=b"\x47" * 188,
            discontinuity=True,
        ))

        manifest = generate_manifest(ring, "test")
        assert "#EXT-X-DISCONTINUITY" in manifest, (
            "INV-HLS-DISCONTINUITY-MARKER-001: manifest must contain "
            "#EXT-X-DISCONTINUITY tag for discontinuous segments"
        )
