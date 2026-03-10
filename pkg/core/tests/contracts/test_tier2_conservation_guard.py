"""INV-BLOCK-SEGMENT-CONSERVATION-001: Tier 2 read boundary enforcement.

sum(segment_duration_ms) must equal block_duration_ms (within frame tolerance)
at every stage of the pipeline, including deserialization from the PlaylistEvent
DB cache.

Violation: _deserialize_scheduled_block(), _get_filled_block_by_id(), and
ensure_block_compiled() reconstruct ScheduledBlocks from stored data without
checking the conservation invariant.  A stale PlaylistEvent row (written before
the Tier 1 presentation-budget fix) carries sum_segment_ms > block_duration_ms.
The overstuffed block reaches channel_manager -> AIR, causing content to play at
the wrong speed (1.25x observed on HBO).
"""
import hashlib

import pytest

from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment


# Frame tolerance: 1 frame at 29.97fps rounded up.
FRAME_TOLERANCE_MS = 40


# ---------------------------------------------------------------------------
# Helpers: build blocks that simulate stale DB data
# ---------------------------------------------------------------------------

def _make_overstuffed_block() -> ScheduledBlock:
    """Block with 79,000ms of presentation that was NOT subtracted from filler.

    This simulates a PlaylistEvent row written before the Tier 1 fix:
      block_duration = 7,200,000ms
      presentation = 79,000ms
      content + filler = 7,200,000ms (should be 7,121,000ms)
      total = 7,279,000ms -- overstuffed by 79,000ms
    """
    raw = "movie-uuid-001:1741500000000"
    block_id = f"blk-{hashlib.sha256(raw.encode()).hexdigest()[:12]}"
    start_utc_ms = 1741500000000  # 2025-03-09T06:00:00Z
    end_utc_ms = start_utc_ms + 7_200_000

    pres_intro = ScheduledSegment(
        segment_type="presentation",
        asset_uri="/mnt/data/bumpers/hbo/intro.mp4",
        asset_start_offset_ms=0,
        segment_duration_ms=74_000,
    )
    pres_rating = ScheduledSegment(
        segment_type="presentation",
        asset_uri="/mnt/data/bumpers/hbo/pg13.mp4",
        asset_start_offset_ms=0,
        segment_duration_ms=5_000,
    )
    content = ScheduledSegment(
        segment_type="content",
        asset_uri="/mnt/data/movies/chaos_walking.mkv",
        asset_start_offset_ms=0,
        segment_duration_ms=6_535_000,
    )
    # Filler computed from full slot (7,200,000 - 6,535,000 = 665,000)
    # Should have been (7,200,000 - 79,000 - 6,535,000 = 586,000)
    filler = ScheduledSegment(
        segment_type="filler",
        asset_uri="/mnt/data/filler/static.mp4",
        asset_start_offset_ms=0,
        segment_duration_ms=665_000,
    )

    return ScheduledBlock(
        block_id=block_id,
        start_utc_ms=start_utc_ms,
        end_utc_ms=end_utc_ms,
        segments=(pres_intro, pres_rating, content, filler),
    )


def _make_correct_block() -> ScheduledBlock:
    """Block where presentation was correctly subtracted from filler budget."""
    raw = "movie-uuid-002:1741500000000"
    block_id = f"blk-{hashlib.sha256(raw.encode()).hexdigest()[:12]}"
    start_utc_ms = 1741500000000
    end_utc_ms = start_utc_ms + 7_200_000

    pres_intro = ScheduledSegment(
        segment_type="presentation",
        asset_uri="/mnt/data/bumpers/hbo/intro.mp4",
        asset_start_offset_ms=0,
        segment_duration_ms=74_000,
    )
    pres_rating = ScheduledSegment(
        segment_type="presentation",
        asset_uri="/mnt/data/bumpers/hbo/pg13.mp4",
        asset_start_offset_ms=0,
        segment_duration_ms=5_000,
    )
    content = ScheduledSegment(
        segment_type="content",
        asset_uri="/mnt/data/movies/chaos_walking.mkv",
        asset_start_offset_ms=0,
        segment_duration_ms=6_535_000,
    )
    # Correctly reduced: 7,200,000 - 79,000 - 6,535,000 = 586,000
    filler = ScheduledSegment(
        segment_type="filler",
        asset_uri="/mnt/data/filler/static.mp4",
        asset_start_offset_ms=0,
        segment_duration_ms=586_000,
    )

    return ScheduledBlock(
        block_id=block_id,
        start_utc_ms=start_utc_ms,
        end_utc_ms=end_utc_ms,
        segments=(pres_intro, pres_rating, content, filler),
    )


def _to_dict(block: ScheduledBlock) -> dict:
    """Serialize a ScheduledBlock to the dict format stored in PlaylistEvent."""
    return {
        "block_id": block.block_id,
        "start_utc_ms": block.start_utc_ms,
        "end_utc_ms": block.end_utc_ms,
        "segments": [
            {
                "segment_type": s.segment_type,
                "asset_uri": s.asset_uri,
                "asset_start_offset_ms": s.asset_start_offset_ms,
                "segment_duration_ms": s.segment_duration_ms,
            }
            for s in block.segments
        ],
    }


# ---------------------------------------------------------------------------
# Tests: INV-BLOCK-SEGMENT-CONSERVATION-001 at Tier 2 read boundary
# ---------------------------------------------------------------------------

class TestTier2ConservationGuard:
    """INV-BLOCK-SEGMENT-CONSERVATION-001: The deserialization boundary must
    reject blocks where abs(sum - duration) > FRAME_TOLERANCE_MS or any
    segment has non-positive duration."""

    # Tier: 2 | Scheduling logic invariant
    def test_overstuffed_block_has_79s_delta(self):
        """Prove the test fixture represents the observed HBO violation:
        79,000ms overflow = exactly the presentation total."""
        block = _make_overstuffed_block()
        block_duration_ms = block.end_utc_ms - block.start_utc_ms
        sum_segment_ms = sum(s.segment_duration_ms for s in block.segments)

        assert block_duration_ms == 7_200_000
        assert sum_segment_ms == 7_279_000
        assert sum_segment_ms - block_duration_ms == 79_000

    # Tier: 2 | Scheduling logic invariant
    def test_correct_block_conserves(self):
        """A correctly budgeted block satisfies the conservation invariant."""
        block = _make_correct_block()
        block_duration_ms = block.end_utc_ms - block.start_utc_ms
        sum_segment_ms = sum(s.segment_duration_ms for s in block.segments)
        assert sum_segment_ms == block_duration_ms

    # Tier: 2 | Scheduling logic invariant
    def test_deserialize_rejects_overstuffed_block(self):
        """INV-BLOCK-SEGMENT-CONSERVATION-001: _deserialize_scheduled_block
        must reject an overstuffed block (79,000ms delta >> 40ms tolerance)
        at the deserialization boundary."""
        from retrovue.runtime.dsl_schedule_service import _deserialize_scheduled_block

        d = _to_dict(_make_overstuffed_block())

        with pytest.raises(ValueError, match="INV-BLOCK-SEGMENT-CONSERVATION"):
            _deserialize_scheduled_block(d)

    # Tier: 2 | Scheduling logic invariant
    def test_correct_block_round_trips(self):
        """A correctly budgeted block must survive deserialization."""
        from retrovue.runtime.dsl_schedule_service import _deserialize_scheduled_block

        d = _to_dict(_make_correct_block())
        deserialized = _deserialize_scheduled_block(d)

        block_duration_ms = deserialized.end_utc_ms - deserialized.start_utc_ms
        sum_segment_ms = sum(s.segment_duration_ms for s in deserialized.segments)
        assert sum_segment_ms == block_duration_ms

    # Tier: 2 | Scheduling logic invariant
    def test_within_frame_tolerance_passes(self):
        """A block with 1ms drift (sub-frame rounding) must pass.
        FRAME_TOLERANCE_MS = 40; 1ms is well within tolerance."""
        from retrovue.runtime.dsl_schedule_service import _deserialize_scheduled_block

        block = _make_correct_block()
        d = _to_dict(block)
        # Add 1ms to the last segment (simulates frame rounding drift)
        d["segments"][-1]["segment_duration_ms"] += 1

        deserialized = _deserialize_scheduled_block(d)
        block_duration_ms = deserialized.end_utc_ms - deserialized.start_utc_ms
        sum_segment_ms = sum(s.segment_duration_ms for s in deserialized.segments)
        assert abs(sum_segment_ms - block_duration_ms) <= FRAME_TOLERANCE_MS

    # Tier: 2 | Scheduling logic invariant
    def test_beyond_frame_tolerance_rejected(self):
        """A block with 41ms drift (just beyond 1 frame) must be rejected."""
        from retrovue.runtime.dsl_schedule_service import _deserialize_scheduled_block

        block = _make_correct_block()
        d = _to_dict(block)
        # Add 41ms (> FRAME_TOLERANCE_MS = 40)
        d["segments"][-1]["segment_duration_ms"] += 41

        with pytest.raises(ValueError, match="INV-BLOCK-SEGMENT-CONSERVATION"):
            _deserialize_scheduled_block(d)

    # Tier: 2 | Scheduling logic invariant
    def test_negative_segment_rejected(self):
        """INV-BLOCK-SEGMENT-CONSERVATION-001: A segment with negative duration
        MUST be rejected, even if the total sum equals block duration via
        cancellation."""
        from retrovue.runtime.dsl_schedule_service import _deserialize_scheduled_block

        d = {
            "block_id": "blk-test-negative",
            "start_utc_ms": 1741500000000,
            "end_utc_ms": 1741500000000 + 60_000,
            "segments": [
                {"segment_type": "content", "asset_uri": "/a.mp4",
                 "asset_start_offset_ms": 0, "segment_duration_ms": 90_000},
                {"segment_type": "filler", "asset_uri": "/b.mp4",
                 "asset_start_offset_ms": 0, "segment_duration_ms": -30_000},
            ],
        }
        # Sum = 90,000 + (-30,000) = 60,000 == block_duration, but negative is invalid
        with pytest.raises(ValueError, match="INV-BLOCK-SEGMENT-CONSERVATION"):
            _deserialize_scheduled_block(d)
