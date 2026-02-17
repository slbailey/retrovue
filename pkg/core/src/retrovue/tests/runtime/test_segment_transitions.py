"""
Tests for segment transition tagging in playout_log_expander.

Verifies INV-TRANSITION-001..005 (SegmentTransitionContract.md):
- First-class breakpoints (chapter markers) → TRANSITION_NONE
- Second-class breakpoints (computed) → TRANSITION_FADE
- fade_duration_ms parameter is respected
- Content segments after filler at computed breakpoints → TRANSITION_FADE in
"""

import pytest

from retrovue.runtime.playout_log_expander import expand_program_block
from retrovue.runtime.schedule_types import ScheduledSegment


# =============================================================================
# Helpers
# =============================================================================

def content_segments(block):
    """Return only content segments from a ScheduledBlock."""
    return [s for s in block.segments if s.segment_type == "content"]


def filler_segments(block):
    """Return only filler segments from a ScheduledBlock."""
    return [s for s in block.segments if s.segment_type == "filler"]


# =============================================================================
# INV-TRANSITION-001: First-class breakpoints → TRANSITION_NONE
# =============================================================================

class TestFirstClassBreakpoints:
    """Chapter marker breakpoints must be clean cuts (TRANSITION_NONE)."""

    def test_chapter_markers_produce_no_transition_out(self):
        """Content segment before chapter-marker filler has TRANSITION_NONE out."""
        block = expand_program_block(
            asset_id="ep01",
            asset_uri="/media/ep01.mkv",
            start_utc_ms=0,
            slot_duration_ms=2_000_000,
            episode_duration_ms=1_800_000,
            chapter_markers_ms=(600_000, 1_200_000),
        )
        contents = content_segments(block)
        # First content segment ends at chapter marker 600_000
        assert contents[0].transition_out == "TRANSITION_NONE"
        assert contents[0].transition_out_duration_ms == 0

    def test_chapter_markers_produce_no_transition_in(self):
        """Content segment after chapter-marker filler has TRANSITION_NONE in."""
        block = expand_program_block(
            asset_id="ep01",
            asset_uri="/media/ep01.mkv",
            start_utc_ms=0,
            slot_duration_ms=2_000_000,
            episode_duration_ms=1_800_000,
            chapter_markers_ms=(600_000, 1_200_000),
        )
        contents = content_segments(block)
        # Middle content segment (after first chapter filler) has no fade-in
        assert contents[1].transition_in == "TRANSITION_NONE"
        assert contents[1].transition_in_duration_ms == 0

    def test_all_chapter_segments_have_no_transitions(self):
        """All segments with chapter markers have TRANSITION_NONE on both ends."""
        block = expand_program_block(
            asset_id="ep01",
            asset_uri="/media/ep01.mkv",
            start_utc_ms=0,
            slot_duration_ms=3_600_000,
            episode_duration_ms=3_000_000,
            chapter_markers_ms=(500_000, 1_000_000, 1_500_000, 2_000_000),
        )
        for seg in content_segments(block):
            assert seg.transition_in == "TRANSITION_NONE", (
                f"Segment at offset {seg.asset_start_offset_ms} should have no transition_in"
            )
            assert seg.transition_out == "TRANSITION_NONE", (
                f"Segment at offset {seg.asset_start_offset_ms} should have no transition_out"
            )
            assert seg.transition_in_duration_ms == 0
            assert seg.transition_out_duration_ms == 0


# =============================================================================
# INV-TRANSITION-001: Second-class breakpoints → TRANSITION_FADE
# =============================================================================

class TestSecondClassBreakpoints:
    """Computed breakpoints must receive TRANSITION_FADE."""

    def test_computed_breakpoints_produce_fade_out(self):
        """Content segment before computed filler has TRANSITION_FADE out."""
        block = expand_program_block(
            asset_id="ep02",
            asset_uri="/media/ep02.mkv",
            start_utc_ms=0,
            slot_duration_ms=2_000_000,
            episode_duration_ms=1_800_000,
            chapter_markers_ms=None,
            num_breaks=2,
        )
        contents = content_segments(block)
        # First two content segments end at computed breakpoints
        assert contents[0].transition_out == "TRANSITION_FADE"
        assert contents[1].transition_out == "TRANSITION_FADE"

    def test_computed_breakpoints_produce_fade_in(self):
        """Content segment after computed filler has TRANSITION_FADE in."""
        block = expand_program_block(
            asset_id="ep02",
            asset_uri="/media/ep02.mkv",
            start_utc_ms=0,
            slot_duration_ms=2_000_000,
            episode_duration_ms=1_800_000,
            chapter_markers_ms=None,
            num_breaks=2,
        )
        contents = content_segments(block)
        # Middle and final content segments follow computed fillers
        assert contents[1].transition_in == "TRANSITION_FADE"
        assert contents[2].transition_in == "TRANSITION_FADE"

    def test_first_content_segment_has_no_transition_in(self):
        """First content segment never has transition_in (no preceding filler)."""
        block = expand_program_block(
            asset_id="ep02",
            asset_uri="/media/ep02.mkv",
            start_utc_ms=0,
            slot_duration_ms=2_000_000,
            episode_duration_ms=1_800_000,
            chapter_markers_ms=None,
            num_breaks=2,
        )
        contents = content_segments(block)
        assert contents[0].transition_in == "TRANSITION_NONE"
        assert contents[0].transition_in_duration_ms == 0

    def test_final_content_segment_has_no_transition_out(self):
        """Final content segment never has transition_out (no following filler)."""
        block = expand_program_block(
            asset_id="ep02",
            asset_uri="/media/ep02.mkv",
            start_utc_ms=0,
            slot_duration_ms=2_000_000,
            episode_duration_ms=1_800_000,
            chapter_markers_ms=None,
            num_breaks=2,
        )
        contents = content_segments(block)
        assert contents[-1].transition_out == "TRANSITION_NONE"
        assert contents[-1].transition_out_duration_ms == 0

    def test_single_computed_break(self):
        """Single computed breakpoint gets fade on both sides."""
        block = expand_program_block(
            asset_id="ep03",
            asset_uri="/media/ep03.mkv",
            start_utc_ms=0,
            slot_duration_ms=1_800_000,
            episode_duration_ms=1_500_000,
            chapter_markers_ms=None,
            num_breaks=1,
        )
        contents = content_segments(block)
        assert len(contents) == 2
        assert contents[0].transition_out == "TRANSITION_FADE"
        assert contents[1].transition_in == "TRANSITION_FADE"

    def test_no_breaks_produces_no_transitions(self):
        """Episode with num_breaks=0 has no filler and no transitions."""
        block = expand_program_block(
            asset_id="ep04",
            asset_uri="/media/ep04.mkv",
            start_utc_ms=0,
            slot_duration_ms=1_800_000,
            episode_duration_ms=1_500_000,
            chapter_markers_ms=None,
            num_breaks=0,
        )
        contents = content_segments(block)
        assert len(contents) == 1
        assert contents[0].transition_in == "TRANSITION_NONE"
        assert contents[0].transition_out == "TRANSITION_NONE"


# =============================================================================
# fade_duration_ms parameter is respected
# =============================================================================

class TestFadeDurationMs:
    """fade_duration_ms parameter controls transition duration."""

    def test_default_duration_is_500ms(self):
        """Default fade duration is 500ms."""
        block = expand_program_block(
            asset_id="ep05",
            asset_uri="/media/ep05.mkv",
            start_utc_ms=0,
            slot_duration_ms=1_800_000,
            episode_duration_ms=1_500_000,
            num_breaks=1,
        )
        contents = content_segments(block)
        assert contents[0].transition_out_duration_ms == 500

    def test_custom_duration_is_applied(self):
        """Custom fade_duration_ms is stored on each second-class transition."""
        block = expand_program_block(
            asset_id="ep05",
            asset_uri="/media/ep05.mkv",
            start_utc_ms=0,
            slot_duration_ms=1_800_000,
            episode_duration_ms=1_500_000,
            num_breaks=2,
            fade_duration_ms=750,
        )
        contents = content_segments(block)
        # First content: fade_out = 750ms
        assert contents[0].transition_out_duration_ms == 750
        # Second content: fade_in = 750ms
        assert contents[1].transition_in_duration_ms == 750
        # Second content: fade_out = 750ms
        assert contents[1].transition_out_duration_ms == 750
        # Third (final) content: fade_in = 750ms
        assert contents[2].transition_in_duration_ms == 750

    def test_zero_duration_not_applied_to_first_class(self):
        """First-class breakpoints have duration_ms=0 regardless of fade_duration_ms."""
        block = expand_program_block(
            asset_id="ep06",
            asset_uri="/media/ep06.mkv",
            start_utc_ms=0,
            slot_duration_ms=2_000_000,
            episode_duration_ms=1_800_000,
            chapter_markers_ms=(900_000,),
            fade_duration_ms=1000,  # Should NOT be used for first-class breaks
        )
        contents = content_segments(block)
        for seg in contents:
            assert seg.transition_in_duration_ms == 0
            assert seg.transition_out_duration_ms == 0


# =============================================================================
# INV-TRANSITION-002: Symmetry — fade_in on content after second-class filler
# =============================================================================

class TestTransitionSymmetry:
    """INV-TRANSITION-002: fade_out on content implies fade_in on following content."""

    def test_symmetry_with_three_breaks(self):
        """All three computed breaks have symmetric fade-out/in pairs."""
        block = expand_program_block(
            asset_id="ep07",
            asset_uri="/media/ep07.mkv",
            start_utc_ms=0,
            slot_duration_ms=3_600_000,
            episode_duration_ms=2_700_000,
            num_breaks=3,
            fade_duration_ms=500,
        )
        contents = content_segments(block)
        # contents[0]: no fade-in (first), fade-out (second-class)
        # contents[1]: fade-in (after second-class filler), fade-out (second-class)
        # contents[2]: fade-in (after second-class filler), fade-out (second-class)
        # contents[3]: fade-in (after second-class filler), no fade-out (final)
        assert len(contents) == 4

        assert contents[0].transition_in == "TRANSITION_NONE"
        assert contents[0].transition_out == "TRANSITION_FADE"

        assert contents[1].transition_in == "TRANSITION_FADE"
        assert contents[1].transition_out == "TRANSITION_FADE"

        assert contents[2].transition_in == "TRANSITION_FADE"
        assert contents[2].transition_out == "TRANSITION_FADE"

        assert contents[3].transition_in == "TRANSITION_FADE"
        assert contents[3].transition_out == "TRANSITION_NONE"

    def test_duration_symmetry(self):
        """fade_in and fade_out durations match at each second-class breakpoint."""
        block = expand_program_block(
            asset_id="ep08",
            asset_uri="/media/ep08.mkv",
            start_utc_ms=0,
            slot_duration_ms=1_800_000,
            episode_duration_ms=1_500_000,
            num_breaks=1,
            fade_duration_ms=333,
        )
        contents = content_segments(block)
        assert contents[0].transition_out_duration_ms == 333
        assert contents[1].transition_in_duration_ms == 333


# =============================================================================
# ScheduledSegment defaults (backward compatibility)
# =============================================================================

class TestScheduledSegmentDefaults:
    """ScheduledSegment transition fields have safe defaults."""

    def test_scheduled_segment_default_no_transition(self):
        """ScheduledSegment created without transition args defaults to NONE."""
        seg = ScheduledSegment(
            segment_type="content",
            asset_uri="/media/ep.mkv",
            asset_start_offset_ms=0,
            segment_duration_ms=1000,
        )
        assert seg.transition_in == "TRANSITION_NONE"
        assert seg.transition_out == "TRANSITION_NONE"
        assert seg.transition_in_duration_ms == 0
        assert seg.transition_out_duration_ms == 0
