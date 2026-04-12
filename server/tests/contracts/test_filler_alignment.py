"""
Contract tests for filler alignment (docs/contracts/filler_alignment.md).

Test matrix IDs: FILLER-ALIGN-001 through FILLER-ALIGN-013.
"""

import pytest

from retrovue.runtime.traffic_manager import _build_filler_segments, fill_ad_blocks
from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment


FILLER_URI = "/opt/retrovue/assets/filler.mp4"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_block_with_gap(gap_ms: int) -> ScheduledBlock:
    """Create a ScheduledBlock with a single empty filler placeholder."""
    return ScheduledBlock(
        block_id="test-block",
        start_utc_ms=0,
        end_utc_ms=gap_ms,
        segments=(
            ScheduledSegment(
                segment_type="filler",
                asset_uri="",
                asset_start_offset_ms=0,
                segment_duration_ms=gap_ms,
            ),
        ),
    )


def _filler_segments(segs):
    """Filter to filler segments only."""
    return [s for s in segs if s.segment_type == "filler"]


# ---------------------------------------------------------------------------
# INV-FILLER-ALIGNMENT-001 — Start mode
# ---------------------------------------------------------------------------


class TestStartAlignment:
    """FILLER-ALIGN-001/002/003: Start-aligned filler."""

    def test_gap_smaller_than_filler(self):
        """FILLER-ALIGN-001: gap < filler, offset starts at 0."""
        segs, offset = _build_filler_segments(
            gap_ms=60_000,
            filler_uri=FILLER_URI,
            filler_duration_ms=3_650_000,
            alignment="start",
            wrapping_offset_ms=0,
        )
        assert len(segs) == 1
        assert segs[0].asset_start_offset_ms == 0
        assert segs[0].segment_duration_ms == 60_000
        assert segs[0].asset_uri == FILLER_URI
        assert segs[0].segment_type == "filler"
        assert offset == 60_000

    def test_gap_larger_than_filler_wraps(self):
        """FILLER-ALIGN-002: gap > filler, wraps and fills exactly."""
        filler_dur = 100_000
        gap = 250_000
        segs, offset = _build_filler_segments(
            gap_ms=gap,
            filler_uri=FILLER_URI,
            filler_duration_ms=filler_dur,
            alignment="start",
        )
        total = sum(s.segment_duration_ms for s in segs)
        assert total == gap
        # Should produce 3 segments: 100k, 100k, 50k
        assert len(segs) == 3
        assert segs[0].asset_start_offset_ms == 0
        assert segs[0].segment_duration_ms == 100_000
        assert segs[1].asset_start_offset_ms == 0
        assert segs[1].segment_duration_ms == 100_000
        assert segs[2].asset_start_offset_ms == 0
        assert segs[2].segment_duration_ms == 50_000
        assert offset == 50_000

    def test_wrapping_offset_carries_across_gaps(self):
        """FILLER-ALIGN-003: wrapping offset carries across consecutive gaps."""
        filler_dur = 100_000

        # First gap
        segs1, offset1 = _build_filler_segments(
            gap_ms=60_000,
            filler_uri=FILLER_URI,
            filler_duration_ms=filler_dur,
            alignment="start",
            wrapping_offset_ms=0,
        )
        assert offset1 == 60_000
        assert segs1[0].asset_start_offset_ms == 0

        # Second gap: should start at offset 60_000
        segs2, offset2 = _build_filler_segments(
            gap_ms=60_000,
            filler_uri=FILLER_URI,
            filler_duration_ms=filler_dur,
            alignment="start",
            wrapping_offset_ms=offset1,
        )
        # First segment: 60_000 → end of filler (40_000)
        assert segs2[0].asset_start_offset_ms == 60_000
        assert segs2[0].segment_duration_ms == 40_000
        # Second segment: wrap to 0, play remaining 20_000
        assert segs2[1].asset_start_offset_ms == 0
        assert segs2[1].segment_duration_ms == 20_000
        assert offset2 == 20_000


# ---------------------------------------------------------------------------
# INV-FILLER-ALIGNMENT-001 — End mode
# ---------------------------------------------------------------------------


class TestEndAlignment:
    """FILLER-ALIGN-004/005/006/007: End-aligned filler."""

    def test_gap_smaller_than_filler(self):
        """FILLER-ALIGN-004: gap < filler, offset = filler_duration - gap."""
        filler_dur = 3_650_000
        gap = 60_000
        segs, offset = _build_filler_segments(
            gap_ms=gap,
            filler_uri=FILLER_URI,
            filler_duration_ms=filler_dur,
            alignment="end",
        )
        assert len(segs) == 1
        assert segs[0].asset_start_offset_ms == filler_dur - gap  # 3_590_000
        assert segs[0].segment_duration_ms == gap
        assert segs[0].asset_uri == FILLER_URI
        assert segs[0].segment_type == "filler"
        assert offset == 0  # end mode is stateless

    def test_gap_equals_filler(self):
        """FILLER-ALIGN-005: gap == filler, offset = 0, single segment."""
        filler_dur = 100_000
        segs, _ = _build_filler_segments(
            gap_ms=filler_dur,
            filler_uri=FILLER_URI,
            filler_duration_ms=filler_dur,
            alignment="end",
        )
        assert len(segs) == 1
        assert segs[0].asset_start_offset_ms == 0
        assert segs[0].segment_duration_ms == filler_dur

    def test_gap_larger_than_filler_with_remainder(self):
        """FILLER-ALIGN-006: gap > filler, partial + full loops, seam-aligned."""
        filler_dur = 100_000
        gap = 250_000  # 2 full loops + 50_000 remaining
        segs, _ = _build_filler_segments(
            gap_ms=gap,
            filler_uri=FILLER_URI,
            filler_duration_ms=filler_dur,
            alignment="end",
        )
        # Contract §2: partial first, then full loops
        assert len(segs) == 3
        # Partial segment: starts at filler_dur - remaining = 50_000
        assert segs[0].asset_start_offset_ms == 50_000
        assert segs[0].segment_duration_ms == 50_000
        # Full loops
        assert segs[1].asset_start_offset_ms == 0
        assert segs[1].segment_duration_ms == 100_000
        assert segs[2].asset_start_offset_ms == 0
        assert segs[2].segment_duration_ms == 100_000
        # Duration conservation
        total = sum(s.segment_duration_ms for s in segs)
        assert total == gap

    def test_gap_exact_multiple_of_filler(self):
        """FILLER-ALIGN-007: gap = 2x filler, two full loops, no partial."""
        filler_dur = 100_000
        gap = 200_000
        segs, _ = _build_filler_segments(
            gap_ms=gap,
            filler_uri=FILLER_URI,
            filler_duration_ms=filler_dur,
            alignment="end",
        )
        # No remainder → no partial segment, just full loops
        assert len(segs) == 2
        assert segs[0].asset_start_offset_ms == 0
        assert segs[0].segment_duration_ms == 100_000
        assert segs[1].asset_start_offset_ms == 0
        assert segs[1].segment_duration_ms == 100_000


# ---------------------------------------------------------------------------
# INV-FILLER-ALIGNMENT-DETERMINISTIC-001
# ---------------------------------------------------------------------------


class TestDeterminism:
    """FILLER-ALIGN-008/009: Identical inputs produce identical output."""

    def test_start_deterministic(self):
        """FILLER-ALIGN-008: start-aligned determinism."""
        args = dict(
            gap_ms=150_000,
            filler_uri=FILLER_URI,
            filler_duration_ms=100_000,
            alignment="start",
            wrapping_offset_ms=30_000,
        )
        segs1, off1 = _build_filler_segments(**args)
        segs2, off2 = _build_filler_segments(**args)
        assert off1 == off2
        assert len(segs1) == len(segs2)
        for s1, s2 in zip(segs1, segs2):
            assert s1.asset_start_offset_ms == s2.asset_start_offset_ms
            assert s1.segment_duration_ms == s2.segment_duration_ms

    def test_end_deterministic(self):
        """FILLER-ALIGN-009: end-aligned determinism."""
        args = dict(
            gap_ms=150_000,
            filler_uri=FILLER_URI,
            filler_duration_ms=100_000,
            alignment="end",
        )
        segs1, _ = _build_filler_segments(**args)
        segs2, _ = _build_filler_segments(**args)
        assert len(segs1) == len(segs2)
        for s1, s2 in zip(segs1, segs2):
            assert s1.asset_start_offset_ms == s2.asset_start_offset_ms
            assert s1.segment_duration_ms == s2.segment_duration_ms


# ---------------------------------------------------------------------------
# INV-FILLER-ALIGNMENT-END-STATELESS-001
# ---------------------------------------------------------------------------


class TestEndStateless:
    """FILLER-ALIGN-010: End-aligned second gap unaffected by first gap size."""

    def test_second_gap_independent_of_first(self):
        filler_dur = 100_000
        second_gap = 30_000

        # Scenario A: first gap is 60_000
        _, _ = _build_filler_segments(
            gap_ms=60_000, filler_uri=FILLER_URI,
            filler_duration_ms=filler_dur, alignment="end",
        )
        segs_a, _ = _build_filler_segments(
            gap_ms=second_gap, filler_uri=FILLER_URI,
            filler_duration_ms=filler_dur, alignment="end",
        )

        # Scenario B: first gap is 90_000
        _, _ = _build_filler_segments(
            gap_ms=90_000, filler_uri=FILLER_URI,
            filler_duration_ms=filler_dur, alignment="end",
        )
        segs_b, _ = _build_filler_segments(
            gap_ms=second_gap, filler_uri=FILLER_URI,
            filler_duration_ms=filler_dur, alignment="end",
        )

        assert len(segs_a) == len(segs_b)
        for sa, sb in zip(segs_a, segs_b):
            assert sa.asset_start_offset_ms == sb.asset_start_offset_ms
            assert sa.segment_duration_ms == sb.segment_duration_ms


# ---------------------------------------------------------------------------
# INV-FILLER-ALIGNMENT-001 — Duration conservation (both modes)
# ---------------------------------------------------------------------------


class TestDurationConservation:
    """FILLER-ALIGN-011: sum(segment_duration_ms) == gap_ms."""

    @pytest.mark.parametrize("alignment", ["start", "end"])
    @pytest.mark.parametrize("gap_ms,filler_dur", [
        (30_000, 100_000),      # gap < filler
        (100_000, 100_000),     # gap == filler
        (250_000, 100_000),     # gap > filler, remainder
        (200_000, 100_000),     # gap = 2x filler, exact
        (1, 100_000),           # 1ms gap
        (350_000, 100_000),     # gap > 3x filler
    ])
    def test_total_equals_gap(self, alignment, gap_ms, filler_dur):
        segs, _ = _build_filler_segments(
            gap_ms=gap_ms,
            filler_uri=FILLER_URI,
            filler_duration_ms=filler_dur,
            alignment=alignment,
        )
        total = sum(s.segment_duration_ms for s in segs)
        assert total == gap_ms


# ---------------------------------------------------------------------------
# INV-FILLER-ALIGNMENT-001 — Offset bounds (both modes)
# ---------------------------------------------------------------------------


class TestOffsetBounds:
    """FILLER-ALIGN-012: all offsets within [0, filler_duration_ms)."""

    @pytest.mark.parametrize("alignment", ["start", "end"])
    @pytest.mark.parametrize("gap_ms,filler_dur", [
        (30_000, 100_000),
        (100_000, 100_000),
        (250_000, 100_000),
        (200_000, 100_000),
    ])
    def test_offsets_in_bounds(self, alignment, gap_ms, filler_dur):
        segs, _ = _build_filler_segments(
            gap_ms=gap_ms,
            filler_uri=FILLER_URI,
            filler_duration_ms=filler_dur,
            alignment=alignment,
        )
        for s in segs:
            assert 0 <= s.asset_start_offset_ms < filler_dur, (
                f"offset {s.asset_start_offset_ms} out of bounds "
                f"[0, {filler_dur})"
            )
            assert s.asset_start_offset_ms + s.segment_duration_ms <= filler_dur, (
                f"offset {s.asset_start_offset_ms} + duration "
                f"{s.segment_duration_ms} exceeds filler_duration {filler_dur}"
            )


# ---------------------------------------------------------------------------
# FILLER-ALIGN-013: Default alignment is "start"
# ---------------------------------------------------------------------------


class TestDefaultAlignment:
    """FILLER-ALIGN-013: Default alignment is 'start' when config omits field."""

    def test_fill_ad_blocks_defaults_to_start(self):
        """fill_ad_blocks without filler_alignment behaves like start."""
        block = _make_block_with_gap(60_000)
        filler_dur = 100_000

        result_default = fill_ad_blocks(
            block, filler_uri=FILLER_URI, filler_duration_ms=filler_dur,
        )
        result_start = fill_ad_blocks(
            block, filler_uri=FILLER_URI, filler_duration_ms=filler_dur,
            filler_alignment="start",
        )

        assert len(result_default.segments) == len(result_start.segments)
        for sd, ss in zip(result_default.segments, result_start.segments):
            assert sd.asset_start_offset_ms == ss.asset_start_offset_ms
            assert sd.segment_duration_ms == ss.segment_duration_ms


# ---------------------------------------------------------------------------
# Integration: fill_ad_blocks with alignment parameter
# ---------------------------------------------------------------------------


class TestFillAdBlocksIntegration:
    """End-to-end: fill_ad_blocks respects filler_alignment."""

    def test_end_alignment_via_fill_ad_blocks(self):
        """End-aligned filler through the full fill_ad_blocks path."""
        gap = 60_000
        filler_dur = 3_650_000
        block = _make_block_with_gap(gap)

        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=filler_dur,
            filler_alignment="end",
        )

        fillers = _filler_segments(result.segments)
        assert len(fillers) == 1
        assert fillers[0].asset_start_offset_ms == filler_dur - gap
        assert fillers[0].segment_duration_ms == gap

    def test_start_alignment_via_fill_ad_blocks(self):
        """Start-aligned filler through the full fill_ad_blocks path."""
        gap = 60_000
        filler_dur = 3_650_000
        block = _make_block_with_gap(gap)

        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=filler_dur,
            filler_alignment="start",
        )

        fillers = _filler_segments(result.segments)
        assert len(fillers) == 1
        assert fillers[0].asset_start_offset_ms == 0
        assert fillers[0].segment_duration_ms == gap

    def test_end_alignment_multiple_gaps_stateless(self):
        """End-aligned: multiple filler placeholders processed independently."""
        filler_dur = 100_000
        gap1, gap2 = 30_000, 50_000
        block = ScheduledBlock(
            block_id="test-multi",
            start_utc_ms=0,
            end_utc_ms=gap1 + gap2 + 100_000,
            segments=(
                ScheduledSegment(
                    segment_type="filler", asset_uri="",
                    asset_start_offset_ms=0, segment_duration_ms=gap1,
                ),
                ScheduledSegment(
                    segment_type="content", asset_uri="/content.mp4",
                    asset_start_offset_ms=0, segment_duration_ms=100_000,
                ),
                ScheduledSegment(
                    segment_type="filler", asset_uri="",
                    asset_start_offset_ms=0, segment_duration_ms=gap2,
                ),
            ),
        )

        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=filler_dur,
            filler_alignment="end",
        )

        fillers = _filler_segments(result.segments)
        assert len(fillers) == 2
        # Each gap computed independently
        assert fillers[0].asset_start_offset_ms == filler_dur - gap1  # 70_000
        assert fillers[0].segment_duration_ms == gap1
        assert fillers[1].asset_start_offset_ms == filler_dur - gap2  # 50_000
        assert fillers[1].segment_duration_ms == gap2

    def test_block_duration_conservation(self):
        """INV-BLOCK-SEGMENT-CONSERVATION-001: total segments == block duration."""
        gap = 250_000
        filler_dur = 100_000
        block = _make_block_with_gap(gap)

        for alignment in ("start", "end"):
            result = fill_ad_blocks(
                block,
                filler_uri=FILLER_URI,
                filler_duration_ms=filler_dur,
                filler_alignment=alignment,
            )
            total = sum(s.segment_duration_ms for s in result.segments)
            block_dur = result.end_utc_ms - result.start_utc_ms
            assert total == block_dur, (
                f"alignment={alignment}: {total} != {block_dur}"
            )
