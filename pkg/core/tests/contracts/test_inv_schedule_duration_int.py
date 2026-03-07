"""
Contract test for INV-TIME-TYPE-001.

Invariant:
    All durations and timestamps in the playout pipeline MUST be integer
    milliseconds.  This is enforced at construction boundaries:

      - ScheduledSegment.__post_init__: rejects float ms fields
      - ScheduledBlock.__post_init__: rejects float timestamp fields
      - BlockPlan.__post_init__: rejects float timestamp fields
      - expand_program_block(): rejects float ms parameters
      - fill_ad_blocks(): rejects float filler_duration_ms
      - _fill_break_with_interstitials(): rejects float break_duration_ms

    Float contamination from `duration_sec * 1000` arithmetic is caught
    at these boundaries — not deep in range() calls or proto serialization.

    The source fix (dsl_schedule_service.py int() casts) prevents floats
    from ever reaching these boundaries in production.  The boundary checks
    are the safety net that makes the invariant structural, not discipline-based.
"""

import pytest

from retrovue.runtime.playout_log_expander import expand_program_block
from retrovue.runtime.playout_session import BlockPlan
from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment
from retrovue.runtime.traffic_manager import fill_ad_blocks


# ─────────────────────────────────────────────────────────────────────────────
# ScheduledSegment boundary enforcement
# ─────────────────────────────────────────────────────────────────────────────

class TestScheduledSegmentTimeType:
    """INV-TIME-TYPE-001: ScheduledSegment rejects float ms at construction."""

    def test_float_segment_duration_ms_rejected(self):
        with pytest.raises(TypeError, match="INV-TIME-TYPE-001.*segment_duration_ms"):
            ScheduledSegment(
                segment_type="content",
                asset_uri="/media/ep.mkv",
                asset_start_offset_ms=0,
                segment_duration_ms=5000.0,
            )

    def test_float_asset_start_offset_ms_rejected(self):
        with pytest.raises(TypeError, match="INV-TIME-TYPE-001.*asset_start_offset_ms"):
            ScheduledSegment(
                segment_type="content",
                asset_uri="/media/ep.mkv",
                asset_start_offset_ms=1500.0,
                segment_duration_ms=5000,
            )

    def test_float_transition_in_duration_ms_rejected(self):
        with pytest.raises(TypeError, match="INV-TIME-TYPE-001.*transition_in_duration_ms"):
            ScheduledSegment(
                segment_type="content",
                asset_uri="/media/ep.mkv",
                asset_start_offset_ms=0,
                segment_duration_ms=5000,
                transition_in_duration_ms=500.0,
            )

    def test_float_transition_out_duration_ms_rejected(self):
        with pytest.raises(TypeError, match="INV-TIME-TYPE-001.*transition_out_duration_ms"):
            ScheduledSegment(
                segment_type="content",
                asset_uri="/media/ep.mkv",
                asset_start_offset_ms=0,
                segment_duration_ms=5000,
                transition_out_duration_ms=500.0,
            )

    def test_int_values_accepted(self):
        """Regression guard: int values still work."""
        seg = ScheduledSegment(
            segment_type="content",
            asset_uri="/media/ep.mkv",
            asset_start_offset_ms=1500,
            segment_duration_ms=5000,
            transition_in_duration_ms=500,
            transition_out_duration_ms=500,
        )
        assert seg.segment_duration_ms == 5000
        assert seg.asset_start_offset_ms == 1500


# ─────────────────────────────────────────────────────────────────────────────
# ScheduledBlock boundary enforcement
# ─────────────────────────────────────────────────────────────────────────────

class TestScheduledBlockTimeType:
    """INV-TIME-TYPE-001: ScheduledBlock rejects float timestamps at construction."""

    def test_float_start_utc_ms_rejected(self):
        with pytest.raises(TypeError, match="INV-TIME-TYPE-001.*start_utc_ms"):
            ScheduledBlock(
                block_id="blk-test",
                start_utc_ms=1000000.0,
                end_utc_ms=1005000,
                segments=(),
            )

    def test_float_end_utc_ms_rejected(self):
        with pytest.raises(TypeError, match="INV-TIME-TYPE-001.*end_utc_ms"):
            ScheduledBlock(
                block_id="blk-test",
                start_utc_ms=1000000,
                end_utc_ms=1005000.0,
                segments=(),
            )

    def test_int_values_accepted(self):
        block = ScheduledBlock(
            block_id="blk-test",
            start_utc_ms=1000000,
            end_utc_ms=1005000,
            segments=(),
        )
        assert block.duration_ms == 5000


# ─────────────────────────────────────────────────────────────────────────────
# BlockPlan boundary enforcement
# ─────────────────────────────────────────────────────────────────────────────

class TestBlockPlanTimeType:
    """INV-TIME-TYPE-001: BlockPlan rejects float timestamps at construction."""

    def test_float_start_utc_ms_rejected(self):
        with pytest.raises(TypeError, match="INV-TIME-TYPE-001.*start_utc_ms"):
            BlockPlan(
                block_id="blk-test",
                channel_id=1,
                start_utc_ms=1000000.0,
                end_utc_ms=1005000,
            )

    def test_float_end_utc_ms_rejected(self):
        with pytest.raises(TypeError, match="INV-TIME-TYPE-001.*end_utc_ms"):
            BlockPlan(
                block_id="blk-test",
                channel_id=1,
                start_utc_ms=1000000,
                end_utc_ms=1005000.0,
            )

    def test_from_dict_coerces_to_int(self):
        """from_dict is a deserialization boundary — it int()-casts."""
        bp = BlockPlan.from_dict({
            "block_id": "blk-test",
            "channel_id": 1,
            "start_utc_ms": 1000000.0,
            "end_utc_ms": 1005000.0,
        })
        assert isinstance(bp.start_utc_ms, int)
        assert isinstance(bp.end_utc_ms, int)


# ─────────────────────────────────────────────────────────────────────────────
# expand_program_block boundary enforcement
# ─────────────────────────────────────────────────────────────────────────────

class TestExpandProgramBlockTimeType:
    """INV-TIME-TYPE-001: expand_program_block rejects float ms parameters."""

    def test_float_slot_duration_ms_rejected(self):
        with pytest.raises(TypeError, match="INV-TIME-TYPE-001.*slot_duration_ms"):
            expand_program_block(
                asset_id="test",
                asset_uri="/media/ep.mkv",
                start_utc_ms=0,
                slot_duration_ms=1800000.0,
                episode_duration_ms=1320000,
            )

    def test_float_episode_duration_ms_rejected(self):
        with pytest.raises(TypeError, match="INV-TIME-TYPE-001.*episode_duration_ms"):
            expand_program_block(
                asset_id="test",
                asset_uri="/media/ep.mkv",
                start_utc_ms=0,
                slot_duration_ms=1800000,
                episode_duration_ms=1320000.0,
            )

    def test_int_values_produce_int_segments(self):
        """When inputs are int, all output segments have int ms fields."""
        block = expand_program_block(
            asset_id="test",
            asset_uri="/media/ep.mkv",
            start_utc_ms=0,
            slot_duration_ms=1800000,
            episode_duration_ms=1320000,
            num_breaks=3,
        )
        for seg in block.segments:
            assert isinstance(seg.segment_duration_ms, int)
            assert isinstance(seg.asset_start_offset_ms, int)
            assert isinstance(seg.transition_in_duration_ms, int)
            assert isinstance(seg.transition_out_duration_ms, int)


# ─────────────────────────────────────────────────────────────────────────────
# fill_ad_blocks boundary enforcement
# ─────────────────────────────────────────────────────────────────────────────

class TestFillAdBlocksTimeType:
    """INV-TIME-TYPE-001: fill_ad_blocks rejects float filler_duration_ms."""

    def test_float_filler_duration_ms_rejected(self):
        block = ScheduledBlock(
            block_id="blk-test",
            start_utc_ms=0,
            end_utc_ms=1800000,
            segments=(
                ScheduledSegment(
                    segment_type="content",
                    asset_uri="/media/ep.mkv",
                    asset_start_offset_ms=0,
                    segment_duration_ms=1320000,
                ),
                ScheduledSegment(
                    segment_type="filler",
                    asset_uri="",
                    asset_start_offset_ms=0,
                    segment_duration_ms=480000,
                ),
            ),
        )
        with pytest.raises(TypeError, match="INV-TIME-TYPE-001.*filler_duration_ms"):
            fill_ad_blocks(
                block,
                filler_uri="/media/filler.ts",
                filler_duration_ms=30000.0,
            )

    def test_int_fill_produces_correct_total(self):
        """With all-int inputs, filled segments sum to block duration."""
        block = ScheduledBlock(
            block_id="blk-test",
            start_utc_ms=0,
            end_utc_ms=1800000,
            segments=(
                ScheduledSegment(
                    segment_type="content",
                    asset_uri="/media/ep.mkv",
                    asset_start_offset_ms=0,
                    segment_duration_ms=1320000,
                ),
                ScheduledSegment(
                    segment_type="filler",
                    asset_uri="",
                    asset_start_offset_ms=0,
                    segment_duration_ms=480000,
                ),
            ),
        )
        filled = fill_ad_blocks(block, filler_uri="/media/filler.ts", filler_duration_ms=30000)
        total_ms = sum(s.segment_duration_ms for s in filled.segments)
        assert total_ms == 1800000


# ─────────────────────────────────────────────────────────────────────────────
# Callback exception safety
# ─────────────────────────────────────────────────────────────────────────────

class TestCallbackExceptionSafety:
    """INV-CALLBACK-EXCEPTION-SAFETY-001: on_block_started exceptions must
    not crash the playout session event loop."""

    def test_on_block_started_exception_is_caught(self):
        """Verify the try/except pattern exists in playout_session.py."""
        import inspect
        from retrovue.runtime.playout_session import PlayoutSession
        source = inspect.getsource(PlayoutSession._subscribe_to_events)
        assert "on_block_started" in source
        assert "except Exception" in source
