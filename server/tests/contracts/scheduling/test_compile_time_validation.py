"""
Contract tests for compile-time validators on the production schedule path.

INV-COMPILED-BLOCK-CONTIGUITY-001: No temporal gaps between adjacent
    compiled blocks within a broadcast day.
INV-COMPILED-GRID-ALIGNMENT-001: Block boundaries align to grid after
    expansion.

Tier: 2 | Scheduling logic invariant
"""

from __future__ import annotations

import pytest

from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_segment(duration_ms: int = 1_800_000) -> ScheduledSegment:
    """Build a minimal content segment."""
    return ScheduledSegment(
        segment_type="content",
        asset_uri="/media/test.ts",
        asset_start_offset_ms=0,
        segment_duration_ms=duration_ms,
    )


def _make_block(
    block_id: str,
    start_ms: int,
    end_ms: int,
) -> ScheduledBlock:
    """Build a minimal ScheduledBlock."""
    return ScheduledBlock(
        block_id=block_id,
        start_utc_ms=start_ms,
        end_utc_ms=end_ms,
        segments=(_make_segment(end_ms - start_ms),),
    )


def _make_contiguous_blocks(
    start_ms: int = 0,
    count: int = 3,
    block_ms: int = 1_800_000,
) -> list[ScheduledBlock]:
    """Build N contiguous 30-minute blocks."""
    blocks = []
    for i in range(count):
        s = start_ms + i * block_ms
        blocks.append(_make_block(f"block-{i}", s, s + block_ms))
    return blocks


# ---------------------------------------------------------------------------
# INV-COMPILED-BLOCK-CONTIGUITY-001
# ---------------------------------------------------------------------------

class TestCompiledBlockContiguity:
    """Contract tests for INV-COMPILED-BLOCK-CONTIGUITY-001."""

    def test_contiguous_blocks_pass(self):
        """Contiguous blocks produce no error."""
        from retrovue.scheduling.compile_time_validation import (
            validate_compiled_block_contiguity,
        )

        blocks = _make_contiguous_blocks()
        validate_compiled_block_contiguity(blocks)  # must not raise

    def test_gap_between_blocks_raises(self):
        """A 1-second gap between blocks must be detected."""
        from retrovue.scheduling.compile_time_validation import (
            validate_compiled_block_contiguity,
        )

        blocks = _make_contiguous_blocks(count=2)
        # Introduce a 1-second gap
        blocks[1] = _make_block(
            "block-1",
            blocks[0].end_utc_ms + 1000,
            blocks[0].end_utc_ms + 1000 + 1_800_000,
        )

        with pytest.raises(ValueError, match="INV-COMPILED-BLOCK-CONTIGUITY-001-VIOLATED"):
            validate_compiled_block_contiguity(blocks)

    def test_empty_blocks_pass(self):
        """Empty block list is valid (compile may produce no blocks)."""
        from retrovue.scheduling.compile_time_validation import (
            validate_compiled_block_contiguity,
        )

        validate_compiled_block_contiguity([])  # must not raise

    def test_single_block_passes(self):
        """A single block has no adjacency to check."""
        from retrovue.scheduling.compile_time_validation import (
            validate_compiled_block_contiguity,
        )

        blocks = [_make_block("block-0", 0, 1_800_000)]
        validate_compiled_block_contiguity(blocks)  # must not raise

    def test_unsorted_blocks_are_sorted_before_check(self):
        """Blocks provided out of order are sorted before gap check."""
        from retrovue.scheduling.compile_time_validation import (
            validate_compiled_block_contiguity,
        )

        blocks = _make_contiguous_blocks(count=3)
        # Reverse order — should still pass because validator sorts
        blocks.reverse()
        validate_compiled_block_contiguity(blocks)  # must not raise

    def test_overlap_is_detected_as_negative_gap(self):
        """Overlapping blocks produce a negative gap (still a violation)."""
        from retrovue.scheduling.compile_time_validation import (
            validate_compiled_block_contiguity,
        )

        blocks = [
            _make_block("block-0", 0, 1_800_000),
            _make_block("block-1", 1_700_000, 3_500_000),  # overlaps by 100s
        ]

        with pytest.raises(ValueError, match="INV-COMPILED-BLOCK-CONTIGUITY-001-VIOLATED"):
            validate_compiled_block_contiguity(blocks)


# ---------------------------------------------------------------------------
# INV-COMPILED-GRID-ALIGNMENT-001
# ---------------------------------------------------------------------------

class TestCompiledGridAlignment:
    """Contract tests for INV-COMPILED-GRID-ALIGNMENT-001."""

    def test_aligned_blocks_pass(self):
        """Blocks on 30-minute grid pass validation."""
        from retrovue.scheduling.compile_time_validation import (
            validate_compiled_grid_alignment,
        )

        grid_ms = 30 * 60 * 1000  # 30 minutes
        blocks = _make_contiguous_blocks(block_ms=grid_ms)
        validate_compiled_grid_alignment(blocks, grid_ms)  # must not raise

    def test_misaligned_block_raises(self):
        """A block offset by 1ms from grid raises violation."""
        from retrovue.scheduling.compile_time_validation import (
            validate_compiled_grid_alignment,
        )

        grid_ms = 30 * 60 * 1000
        blocks = [
            _make_block("block-0", 0, grid_ms),
            _make_block("block-1", grid_ms + 1, 2 * grid_ms + 1),  # off by 1ms
        ]

        with pytest.raises(ValueError, match="INV-COMPILED-GRID-ALIGNMENT-001-VIOLATED"):
            validate_compiled_grid_alignment(blocks, grid_ms)

    def test_empty_blocks_pass(self):
        """Empty block list is valid."""
        from retrovue.scheduling.compile_time_validation import (
            validate_compiled_grid_alignment,
        )

        validate_compiled_grid_alignment([], 1_800_000)  # must not raise
