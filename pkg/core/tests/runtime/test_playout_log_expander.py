"""
Tests for the Playout Log Expander.

Covers: chapter marker splitting, approximation, act/ad_block structure,
ad block duration math, edge cases. All output uses ScheduledBlock/ScheduledSegment.
"""

from __future__ import annotations

import pytest

from retrovue.runtime.playout_log_expander import expand_program_block
from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment


START_MS = 1_000_000_000_000  # arbitrary UTC ms


class TestChapterMarkers:
    def test_chapter_markers_create_acts(self):
        block = expand_program_block(
            asset_id="ep1", asset_uri="/shows/ep1.mp4",
            start_utc_ms=START_MS, slot_duration_ms=1_800_000,
            episode_duration_ms=1_320_000,
            chapter_markers_ms=(330_000, 660_000, 990_000),
        )
        assert isinstance(block, ScheduledBlock)
        acts = [s for s in block.segments if s.segment_type == "content"]
        fillers = [s for s in block.segments if s.segment_type == "filler"]
        assert len(acts) == 4
        assert len(fillers) == 3

    def test_chapter_marker_act_durations(self):
        block = expand_program_block(
            asset_id="ep1", asset_uri="/shows/ep1.mp4",
            start_utc_ms=START_MS, slot_duration_ms=1_800_000,
            episode_duration_ms=1_320_000,
            chapter_markers_ms=(330_000, 660_000, 990_000),
        )
        acts = [s for s in block.segments if s.segment_type == "content"]
        for act in acts:
            assert act.segment_duration_ms == 330_000

    def test_chapter_marker_seek_offsets(self):
        block = expand_program_block(
            asset_id="ep1", asset_uri="/shows/ep1.mp4",
            start_utc_ms=START_MS, slot_duration_ms=1_800_000,
            episode_duration_ms=1_320_000,
            chapter_markers_ms=(330_000, 660_000, 990_000),
        )
        acts = [s for s in block.segments if s.segment_type == "content"]
        assert acts[0].asset_start_offset_ms == 0
        assert acts[1].asset_start_offset_ms == 330_000
        assert acts[2].asset_start_offset_ms == 660_000
        assert acts[3].asset_start_offset_ms == 990_000

    def test_content_segments_reference_asset(self):
        block = expand_program_block(
            asset_id="ep1", asset_uri="/shows/ep1.mp4",
            start_utc_ms=START_MS, slot_duration_ms=1_800_000,
            episode_duration_ms=1_320_000,
            chapter_markers_ms=(660_000,),
        )
        acts = [s for s in block.segments if s.segment_type == "content"]
        for act in acts:
            assert act.asset_uri == "/shows/ep1.mp4"


class TestAlgorithmicBreaks:
    def test_no_markers_produces_algorithmic_breaks(self):
        """detect_breaks produces 2 algorithmic breaks for 22min in 30min slot."""
        block = expand_program_block(
            asset_id="ep1", asset_uri="/shows/ep1.mp4",
            start_utc_ms=START_MS, slot_duration_ms=1_800_000,
            episode_duration_ms=1_320_000,
        )
        acts = [s for s in block.segments if s.segment_type == "content"]
        fillers = [s for s in block.segments if s.segment_type == "filler"]
        # detect_breaks: max(2, 1_320_000 // 480_000) = 2 breaks
        assert len(acts) == 3
        assert len(fillers) == 2

    def test_algorithmic_acts_non_uniform(self):
        """Algorithmic breaks use non-uniform spacing (first act longest)."""
        block = expand_program_block(
            asset_id="ep1", asset_uri="/shows/ep1.mp4",
            start_utc_ms=START_MS, slot_duration_ms=1_800_000,
            episode_duration_ms=1_320_000,
        )
        acts = [s for s in block.segments if s.segment_type == "content"]
        durations = [a.segment_duration_ms for a in acts]
        # Non-uniform: first act > last act (harmonic-decreasing intervals)
        assert durations[0] > durations[-1]


class TestAdBlockDurations:
    def test_weighted_ad_block_split(self):
        """INV-BREAK-WEIGHT-001: filler durations proportional to weights."""
        block = expand_program_block(
            asset_id="ep1", asset_uri="/shows/ep1.mp4",
            start_utc_ms=START_MS, slot_duration_ms=1_800_000,
            episode_duration_ms=1_320_000,
            chapter_markers_ms=(330_000, 660_000, 990_000),
        )
        fillers = [s for s in block.segments if s.segment_type == "filler"]
        # 480_000ms budget, weights [1,2,3] → [80_000, 160_000, 240_000]
        assert [f.segment_duration_ms for f in fillers] == [80_000, 160_000, 240_000]

    def test_no_ad_time_when_episode_fills_slot(self):
        block = expand_program_block(
            asset_id="ep1", asset_uri="/shows/ep1.mp4",
            start_utc_ms=START_MS, slot_duration_ms=1_320_000,
            episode_duration_ms=1_320_000,
            chapter_markers_ms=(330_000, 660_000, 990_000),
        )
        fillers = [s for s in block.segments if s.segment_type == "filler"]
        assert len(fillers) == 0


class TestBlockMetadata:
    def test_block_times(self):
        block = expand_program_block(
            asset_id="ep1", asset_uri="/shows/ep1.mp4",
            start_utc_ms=START_MS, slot_duration_ms=1_800_000,
            episode_duration_ms=1_320_000,
        )
        assert block.start_utc_ms == START_MS
        assert block.end_utc_ms == START_MS + 1_800_000
        assert block.duration_ms == 1_800_000

    def test_block_id_deterministic(self):
        b1 = expand_program_block(
            asset_id="ep1", asset_uri="/shows/ep1.mp4",
            start_utc_ms=START_MS, slot_duration_ms=1_800_000,
            episode_duration_ms=1_320_000,
        )
        b2 = expand_program_block(
            asset_id="ep1", asset_uri="/shows/ep1.mp4",
            start_utc_ms=START_MS, slot_duration_ms=1_800_000,
            episode_duration_ms=1_320_000,
        )
        assert b1.block_id == b2.block_id
        assert b1.block_id.startswith("blk-")

    def test_filler_placeholders_have_empty_uri(self):
        """Unfilled filler segments have empty asset_uri."""
        block = expand_program_block(
            asset_id="ep1", asset_uri="/shows/ep1.mp4",
            start_utc_ms=START_MS, slot_duration_ms=1_800_000,
            episode_duration_ms=1_320_000,
            chapter_markers_ms=(660_000,),
        )
        fillers = [s for s in block.segments if s.segment_type == "filler"]
        for f in fillers:
            assert f.asset_uri == ""


class TestEdgeCases:
    def test_no_breaks_when_episode_fills_slot(self):
        """INV-BREAK-011: zero budget → empty break plan → no filler."""
        block = expand_program_block(
            asset_id="ep1", asset_uri="/shows/ep1.mp4",
            start_utc_ms=START_MS, slot_duration_ms=1_320_000,
            episode_duration_ms=1_320_000,
        )
        acts = [s for s in block.segments if s.segment_type == "content"]
        fillers = [s for s in block.segments if s.segment_type == "filler"]
        assert len(acts) == 1
        assert len(fillers) == 0
        assert acts[0].segment_duration_ms == 1_320_000

    def test_empty_chapter_markers_falls_back_to_algorithmic(self):
        """Empty chapter markers tuple → algorithmic break detection."""
        block = expand_program_block(
            asset_id="ep1", asset_uri="/shows/ep1.mp4",
            start_utc_ms=START_MS, slot_duration_ms=1_800_000,
            episode_duration_ms=1_320_000,
            chapter_markers_ms=(),
        )
        acts = [s for s in block.segments if s.segment_type == "content"]
        # detect_breaks: 2 algorithmic breaks → 3 content segments
        assert len(acts) == 3

    def test_segment_order(self):
        block = expand_program_block(
            asset_id="ep1", asset_uri="/shows/ep1.mp4",
            start_utc_ms=START_MS, slot_duration_ms=1_800_000,
            episode_duration_ms=1_320_000,
            chapter_markers_ms=(440_000, 880_000),
        )
        types = [s.segment_type for s in block.segments]
        assert types == ["content", "filler", "content", "filler", "content"]

    def test_segments_are_frozen(self):
        block = expand_program_block(
            asset_id="ep1", asset_uri="/shows/ep1.mp4",
            start_utc_ms=START_MS, slot_duration_ms=1_800_000,
            episode_duration_ms=1_320_000,
        )
        with pytest.raises(AttributeError):
            block.block_id = "changed"  # type: ignore[misc]
        with pytest.raises(AttributeError):
            block.segments[0].segment_type = "x"  # type: ignore[misc]

    def test_total_segment_duration_equals_slot(self):
        """Sum of all segment durations must equal slot duration."""
        block = expand_program_block(
            asset_id="ep1", asset_uri="/shows/ep1.mp4",
            start_utc_ms=START_MS, slot_duration_ms=1_800_000,
            episode_duration_ms=1_320_000,
            chapter_markers_ms=(330_000, 660_000, 990_000),
        )
        total = sum(s.segment_duration_ms for s in block.segments)
        assert total == 1_800_000
