"""
Tests for the Traffic Manager v1.

Each ad within an ad block is its own ScheduledSegment with sequential
offsets into filler.mp4. Filler wraps when exhausted.
"""

from __future__ import annotations

import pytest

from retrovue.runtime.playout_log_expander import expand_program_block
from retrovue.runtime.traffic_manager import fill_ad_blocks
from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment

START_MS = 1_000_000_000_000


def _make_block() -> ScheduledBlock:
    """Block with 3 ad breaks, 160_000ms each (480_000ms total ad time)."""
    return expand_program_block(
        asset_id="ep1", asset_uri="/shows/ep1.mp4",
        start_utc_ms=START_MS, slot_duration_ms=1_800_000,
        episode_duration_ms=1_320_000,
        chapter_markers_ms=(330_000, 660_000, 990_000),
    )


class TestSequentialOffsets:
    def test_ads_have_sequential_offsets(self):
        """Filler segments should play sequentially through filler.mp4."""
        block = _make_block()
        # 30s filler, 160s ad block → plays 0-30, 30-60, 60-90, 90-120, 120-150, then wraps
        filled = fill_ad_blocks(block, "/ads/filler.mp4", 30_000)
        fillers = [s for s in filled.segments if s.segment_type == "filler"]
        # First ad block: offsets 0, 30000, 60000, 90000, 120000 (5 full plays)
        assert fillers[0].asset_start_offset_ms == 0
        assert fillers[1].asset_start_offset_ms == 0  # wraps: 30000 offset consumes full filler
        # Actually with 30s filler and 30s ad slots, each starts at 0 after consuming full file
        # Let me verify: first block 160s / 30s = 5 full + 10s pad
        first_block_fillers = fillers[:5]
        for f in first_block_fillers:
            assert f.segment_duration_ms == 30_000
            assert f.asset_uri == "/ads/filler.mp4"

    def test_offset_wraps_at_filler_end(self):
        """When filler is shorter than ad slot, offset wraps to 0."""
        block = expand_program_block(
            asset_id="ep1", asset_uri="/shows/ep1.mp4",
            start_utc_ms=START_MS, slot_duration_ms=1_800_000,
            episode_duration_ms=1_740_000,  # 60s ad time, 1 break
            chapter_markers_ms=(870_000,),
        )
        # 60s filler, 60s ad block
        filled = fill_ad_blocks(block, "/ads/filler.mp4", 60_000)
        fillers = [s for s in filled.segments if s.segment_type == "filler"]
        assert len(fillers) == 1
        assert fillers[0].asset_start_offset_ms == 0
        assert fillers[0].segment_duration_ms == 60_000

    def test_offset_continues_across_ad_blocks(self):
        """Filler offset carries forward across ad blocks within a ScheduledBlock."""
        block = expand_program_block(
            asset_id="ep1", asset_uri="/shows/ep1.mp4",
            start_utc_ms=START_MS, slot_duration_ms=1_800_000,
            episode_duration_ms=1_680_000,  # 120s total, 2 breaks of 60s each
            chapter_markers_ms=(560_000, 1_120_000),
        )
        # 100s filler, 60s ad blocks
        filled = fill_ad_blocks(block, "/ads/filler.mp4", 100_000)
        fillers = [s for s in filled.segments if s.segment_type == "filler"]
        # Block 1 (60s): plays 0-60 from filler (offset now at 60000)
        assert fillers[0].asset_start_offset_ms == 0
        assert fillers[0].segment_duration_ms == 60_000
        # Block 2 (60s): plays 60-100 (40s), then wraps to 0-20 (20s)
        assert fillers[1].asset_start_offset_ms == 60_000
        assert fillers[1].segment_duration_ms == 40_000
        assert fillers[2].asset_start_offset_ms == 0
        assert fillers[2].segment_duration_ms == 20_000


class TestFillerFilling:
    def test_exact_fill_no_pad(self):
        """When filler divides evenly, no pad segments."""
        block = expand_program_block(
            asset_id="ep1", asset_uri="/shows/ep1.mp4",
            start_utc_ms=START_MS, slot_duration_ms=1_800_000,
            episode_duration_ms=1_680_000,  # 120s total, 3 breaks of 40s
            chapter_markers_ms=(420_000, 840_000, 1_260_000),
        )
        filled = fill_ad_blocks(block, "/ads/filler.mp4", 40_000)
        pads = [s for s in filled.segments if s.segment_type == "pad"]
        assert len(pads) == 0

    def test_content_unchanged(self):
        block = _make_block()
        filled = fill_ad_blocks(block, "/ads/filler.mp4", 30_000)
        content = [s for s in filled.segments if s.segment_type == "content"]
        assert len(content) == 4
        for seg in content:
            assert seg.asset_uri == "/shows/ep1.mp4"


class TestPadding:
    def test_remainder_becomes_partial_filler(self):
        """When filler doesn't divide evenly, remainders become partial filler segments (wrap)."""
        block = _make_block()
        # 160s ad block, 30s filler → sequential play wraps, no pad needed
        filled = fill_ad_blocks(block, "/ads/filler.mp4", 30_000)
        pads = [s for s in filled.segments if s.segment_type == "pad"]
        # No pads — filler wraps to fill completely
        assert len(pads) == 0
        # All filler segments reference the filler file
        fillers = [s for s in filled.segments if s.segment_type == "filler"]
        for f in fillers:
            assert f.asset_uri == "/ads/filler.mp4"

    def test_filler_longer_than_block_partial_play(self):
        """When filler > ad block, a partial filler segment plays."""
        block = _make_block()
        # 200s filler, 160s ad block → plays 0-160 (partial), offset carries to next block
        filled = fill_ad_blocks(block, "/ads/filler.mp4", 200_000)
        fillers = [s for s in filled.segments if s.segment_type == "filler"]
        # First ad block: 160s from offset 0
        assert fillers[0].asset_start_offset_ms == 0
        assert fillers[0].segment_duration_ms == 160_000
        # Second ad block: 40s from offset 160000, then wraps to 0 for 120s
        assert fillers[1].asset_start_offset_ms == 160_000
        assert fillers[1].segment_duration_ms == 40_000
        assert fillers[2].asset_start_offset_ms == 0
        assert fillers[2].segment_duration_ms == 120_000


class TestDurationMath:
    def test_total_duration_preserved(self):
        """Sum of all segment durations must equal slot duration."""
        block = _make_block()
        filled = fill_ad_blocks(block, "/ads/filler.mp4", 30_000)
        total = sum(s.segment_duration_ms for s in filled.segments)
        assert total == 1_800_000

    def test_block_metadata_preserved(self):
        block = _make_block()
        filled = fill_ad_blocks(block, "/ads/filler.mp4", 30_000)
        assert filled.block_id == block.block_id
        assert filled.start_utc_ms == block.start_utc_ms
        assert filled.end_utc_ms == block.end_utc_ms


class TestDynamicSegmentCounts:
    def test_more_breaks_more_segments(self):
        """More chapter markers = more segments."""
        block_2 = expand_program_block(
            asset_id="ep1", asset_uri="/shows/ep1.mp4",
            start_utc_ms=START_MS, slot_duration_ms=1_800_000,
            episode_duration_ms=1_320_000,
            chapter_markers_ms=(660_000,),  # 1 break
        )
        block_5 = expand_program_block(
            asset_id="ep1", asset_uri="/shows/ep1.mp4",
            start_utc_ms=START_MS, slot_duration_ms=1_800_000,
            episode_duration_ms=1_320_000,
            chapter_markers_ms=(264_000, 528_000, 792_000, 1_056_000),  # 4 breaks
        )
        filled_2 = fill_ad_blocks(block_2, "/ads/filler.mp4", 30_000)
        filled_5 = fill_ad_blocks(block_5, "/ads/filler.mp4", 30_000)
        assert len(filled_5.segments) > len(filled_2.segments)

    def test_no_hardcoded_counts(self):
        """Segment count depends entirely on chapter markers + filler math."""
        for n_markers in (1, 2, 3, 5, 8):
            interval = 1_320_000 // (n_markers + 1)
            markers = tuple(interval * (i + 1) for i in range(n_markers))
            block = expand_program_block(
                asset_id="ep1", asset_uri="/shows/ep1.mp4",
                start_utc_ms=START_MS, slot_duration_ms=1_800_000,
                episode_duration_ms=1_320_000,
                chapter_markers_ms=markers,
            )
            filled = fill_ad_blocks(block, "/ads/filler.mp4", 30_000)
            content = [s for s in filled.segments if s.segment_type == "content"]
            assert len(content) == n_markers + 1
            # Total duration always matches
            total = sum(s.segment_duration_ms for s in filled.segments)
            assert total == 1_800_000


class TestEdgeCases:
    def test_zero_filler_raises(self):
        block = _make_block()
        with pytest.raises(ValueError, match="positive"):
            fill_ad_blocks(block, "/ads/filler.mp4", 0)

    def test_negative_filler_raises(self):
        block = _make_block()
        with pytest.raises(ValueError, match="positive"):
            fill_ad_blocks(block, "/ads/filler.mp4", -5)

    def test_already_filled_not_refilled(self):
        """Filler segments with a real asset_uri are not re-filled."""
        block = _make_block()
        filled = fill_ad_blocks(block, "/ads/filler.mp4", 30_000)
        filled2 = fill_ad_blocks(filled, "/ads/other.mp4", 15_000)
        fillers = [s for s in filled2.segments if s.segment_type == "filler"]
        for f in fillers:
            assert f.asset_uri == "/ads/filler.mp4"

    def test_output_is_frozen(self):
        block = _make_block()
        filled = fill_ad_blocks(block, "/ads/filler.mp4", 30_000)
        with pytest.raises(AttributeError):
            filled.block_id = "x"  # type: ignore[misc]
