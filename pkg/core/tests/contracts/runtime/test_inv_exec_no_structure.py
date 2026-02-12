"""INV-EXEC-NO-STRUCTURE-001: Execution SHALL NOT define block duration.

Tests:
- BlockPlanProducer has no DEFAULT_BLOCK_DURATION_MS attribute
- BlockPlanProducer has no _block_duration_ms field
- _generate_next_block requires ScheduledBlock (typed, not dict)
- Block timing comes from FakeScheduleService via typed objects
- ScheduledBlock is frozen/immutable
- INV-EXEC-OFFSET-001: JIP offset computed within block
- INV-EXEC-NO-BOUNDARY-001: No grid alignment math in execution
- End-to-end regression: 30-minute blocks with JIP at 10 minutes
- INV-BLOCKPLAN-HORIZON-MISS: Missing schedule data policy

Copyright (c) 2025 RetroVue
"""
from __future__ import annotations

import pytest

from retrovue.runtime.channel_manager import BlockPlanProducer
from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "fixtures"))
from fake_schedule_service import FakeScheduleService


# =============================================================================
# Test Infrastructure
# =============================================================================


def _make_producer(
    schedule_service: FakeScheduleService | None = None,
    channel_id: str = "inv-test",
) -> BlockPlanProducer:
    """Create a BlockPlanProducer with FakeScheduleService."""
    svc = schedule_service or FakeScheduleService(
        channel_id=channel_id,
        block_duration_ms=10_000,
    )
    return BlockPlanProducer(
        channel_id=channel_id,
        schedule_service=svc,
        clock=None,
    )


def _make_scheduled_block(
    block_id: str = "BLOCK-test-0",
    start_utc_ms: int = 0,
    end_utc_ms: int = 10_000,
    asset_uri: str = "test.mp4",
) -> ScheduledBlock:
    return ScheduledBlock(
        block_id=block_id,
        start_utc_ms=start_utc_ms,
        end_utc_ms=end_utc_ms,
        segments=(
            ScheduledSegment(
                segment_type="episode",
                asset_uri=asset_uri,
                asset_start_offset_ms=0,
                segment_duration_ms=end_utc_ms - start_utc_ms,
            ),
        ),
    )


# =============================================================================
# 1. No duration constants in execution layer
# =============================================================================


class TestNoDurationConstantsInExecution:
    """INV-EXEC-NO-STRUCTURE-001: BlockPlanProducer must not define block duration."""

    def test_no_default_block_duration_ms_class_attr(self):
        """BlockPlanProducer has no DEFAULT_BLOCK_DURATION_MS class attribute."""
        assert not hasattr(BlockPlanProducer, "DEFAULT_BLOCK_DURATION_MS"), (
            "INV-EXEC-NO-STRUCTURE-001 VIOLATION: "
            "BlockPlanProducer still has DEFAULT_BLOCK_DURATION_MS"
        )

    def test_no_block_duration_ms_instance_attr(self):
        """BlockPlanProducer instances have no _block_duration_ms field."""
        producer = _make_producer()
        assert not hasattr(producer, "_block_duration_ms"), (
            "INV-EXEC-NO-STRUCTURE-001 VIOLATION: "
            "BlockPlanProducer instance still has _block_duration_ms"
        )

    def test_no_execution_store_attr(self):
        """BlockPlanProducer instances have no _execution_store field."""
        producer = _make_producer()
        assert not hasattr(producer, "_execution_store"), (
            "INV-EXEC-NO-STRUCTURE-001: "
            "BlockPlanProducer instance still has _execution_store"
        )

    def test_no_playout_plan_attr(self):
        """BlockPlanProducer instances have no _playout_plan field."""
        producer = _make_producer()
        assert not hasattr(producer, "_playout_plan"), (
            "INV-EXEC-NO-STRUCTURE-001: "
            "BlockPlanProducer instance still has _playout_plan"
        )


# =============================================================================
# 2. ScheduledBlock is frozen and typed
# =============================================================================


class TestScheduledBlockImmutability:
    """ScheduledBlock must be frozen (immutable)."""

    def test_frozen_start(self):
        b = _make_scheduled_block()
        with pytest.raises(AttributeError):
            b.start_utc_ms = 999  # type: ignore[misc]

    def test_frozen_end(self):
        b = _make_scheduled_block()
        with pytest.raises(AttributeError):
            b.end_utc_ms = 999  # type: ignore[misc]

    def test_frozen_block_id(self):
        b = _make_scheduled_block()
        with pytest.raises(AttributeError):
            b.block_id = "modified"  # type: ignore[misc]

    def test_duration_property(self):
        b = _make_scheduled_block(start_utc_ms=1000, end_utc_ms=31_000)
        assert b.duration_ms == 30_000

    def test_segments_is_tuple(self):
        b = _make_scheduled_block()
        assert isinstance(b.segments, tuple), (
            "segments must be a tuple for true immutability"
        )


# =============================================================================
# 3. _generate_next_block requires ScheduledBlock
# =============================================================================


class TestGenerateNextBlockTyped:
    """_generate_next_block takes ScheduledBlock, not dict."""

    def test_generate_from_scheduled_block(self):
        producer = _make_producer()
        sb = _make_scheduled_block(
            block_id="BLOCK-typed-0",
            start_utc_ms=0,
            end_utc_ms=10_000,
            asset_uri="assets/A.mp4",
        )
        block = producer._generate_next_block(sb)
        assert block.block_id == "BLOCK-typed-0"
        assert block.start_utc_ms == 0
        assert block.end_utc_ms == 10_000
        assert block.segments[0]["asset_uri"] == "assets/A.mp4"
        assert block.segments[0]["segment_duration_ms"] == 10_000

    def test_generate_preserves_timing(self):
        """Block timing must come from ScheduledBlock, not computed."""
        producer = _make_producer()
        sb = _make_scheduled_block(
            start_utc_ms=100_000,
            end_utc_ms=1_900_000,
        )
        block = producer._generate_next_block(sb)
        assert block.start_utc_ms == 100_000
        assert block.end_utc_ms == 1_900_000
        assert block.end_utc_ms - block.start_utc_ms == 1_800_000


# =============================================================================
# 4. Block timing from FakeScheduleService
# =============================================================================


class TestBlockTimingFromScheduleService:
    """Block duration is defined by schedule service, not execution."""

    def test_resolve_returns_scheduled_block(self):
        svc = FakeScheduleService(
            channel_id="svc-test",
            block_duration_ms=1_800_000,
        )
        producer = _make_producer(schedule_service=svc, channel_id="svc-test")
        producer._next_block_start_ms = 0
        sb = producer._resolve_plan_for_block()
        assert sb is not None
        assert isinstance(sb, ScheduledBlock)
        assert sb.duration_ms == 1_800_000

    def test_resolve_at_returns_scheduled_block(self):
        svc = FakeScheduleService(
            channel_id="svc-test",
            block_duration_ms=30_000,
        )
        producer = _make_producer(schedule_service=svc, channel_id="svc-test")
        sb = producer._resolve_plan_for_block_at(15_000)
        assert sb is not None
        assert sb.start_utc_ms == 0
        assert sb.end_utc_ms == 30_000

    def test_no_schedule_service_returns_none(self):
        producer = BlockPlanProducer(
            channel_id="no-svc",
            schedule_service=None,
            clock=None,
        )
        producer._next_block_start_ms = 0
        assert producer._resolve_plan_for_block() is None


# =============================================================================
# 5. INV-EXEC-OFFSET-001: JIP offset within block
# =============================================================================


class TestJipOffsetWithinBlock:
    """INV-EXEC-OFFSET-001: Execution MAY compute offsets within a block."""

    def test_jip_offset_shortens_first_block(self):
        producer = _make_producer()
        sb = _make_scheduled_block(start_utc_ms=0, end_utc_ms=10_000)
        block = producer._generate_next_block(sb, jip_offset_ms=3_000, now_utc_ms=3_000)
        # Block starts at now (3000), ends at fence (10000)
        assert block.start_utc_ms == 3_000
        assert block.end_utc_ms == 10_000
        assert block.end_utc_ms - block.start_utc_ms == 7_000

    def test_jip_zero_produces_full_block(self):
        producer = _make_producer()
        sb = _make_scheduled_block(start_utc_ms=0, end_utc_ms=10_000)
        block = producer._generate_next_block(sb, jip_offset_ms=0, now_utc_ms=0)
        assert block.start_utc_ms == 0
        assert block.end_utc_ms == 10_000


# =============================================================================
# 6. INV-EXEC-NO-BOUNDARY-001: No grid alignment in execution
# =============================================================================


class TestNoGridAlignmentInExecution:
    """INV-EXEC-NO-BOUNDARY-001: Execution MAY NOT compute block boundaries."""

    def test_contiguous_blocks_from_service(self):
        """Blocks generated from schedule service are contiguous."""
        svc = FakeScheduleService(
            channel_id="contiguous-test",
            block_duration_ms=10_000,
        )
        producer = _make_producer(schedule_service=svc, channel_id="contiguous-test")
        producer._next_block_start_ms = 0

        blocks = []
        for _ in range(5):
            sb = producer._resolve_plan_for_block()
            assert sb is not None
            block = producer._generate_next_block(sb)
            blocks.append(block)
            producer._advance_cursor(block)

        for i in range(1, len(blocks)):
            assert blocks[i].start_utc_ms == blocks[i - 1].end_utc_ms, (
                f"Gap between block {i-1} and {i}: "
                f"end={blocks[i-1].end_utc_ms}, start={blocks[i].start_utc_ms}"
            )


# =============================================================================
# 7. End-to-end regression: 30-minute blocks (the original failure mode)
# =============================================================================


class TestEndToEndThirtyMinuteBlockRegression:
    """Regression test: the exact failure mode that triggered INV-EXEC-NO-STRUCTURE-001.

    Before this invariant, BlockPlanProducer hardcoded block_duration_ms=30_000 (30s),
    causing 30-second blocks instead of 30-minute blocks. This test uses the real
    FakeScheduleService returning 30-minute ScheduledBlocks and verifies:
    - JIP at 10 minutes into a 30-minute block produces a partial first block
    - Next block is full 30 minutes
    - Segment durations sum to block durations for both blocks
    """

    def test_thirty_minute_blocks_with_jip_at_ten_minutes(self):
        svc = FakeScheduleService(
            channel_id="regression-30m",
            block_duration_ms=1_800_000,  # 30 minutes
        )
        producer = BlockPlanProducer(
            channel_id="regression-30m",
            schedule_service=svc,
            clock=None,
        )

        # Join 10 minutes into the first 30-minute block
        join_utc_ms = 600_000  # 10 minutes (in the first 30-min block starting at 0)
        producer._next_block_start_ms = 0

        # Resolve block A (the block covering join time)
        block_a_scheduled = producer._resolve_plan_for_block_at(join_utc_ms)
        assert block_a_scheduled is not None
        assert block_a_scheduled.duration_ms == 1_800_000  # 30 minutes from schedule

        # Generate block A with JIP
        jip_offset_ms = join_utc_ms - block_a_scheduled.start_utc_ms  # = 600_000
        block_a = producer._generate_next_block(
            block_a_scheduled, jip_offset_ms=jip_offset_ms, now_utc_ms=join_utc_ms,
        )
        producer._advance_cursor(block_a)

        # Block A: partial — [10min, 30min) = 20 minutes
        assert block_a.start_utc_ms == 600_000
        assert block_a.end_utc_ms == 1_800_000
        assert block_a.duration_ms == 1_200_000  # 20 minutes

        # Segment sum equals block duration
        seg_sum_a = sum(s["segment_duration_ms"] for s in block_a.segments)
        assert seg_sum_a == block_a.duration_ms

        # Resolve and generate block B (next full block)
        block_b_scheduled = producer._resolve_plan_for_block()
        assert block_b_scheduled is not None
        block_b = producer._generate_next_block(block_b_scheduled)

        # Block B: full 30 minutes
        assert block_b.start_utc_ms == 1_800_000
        assert block_b.end_utc_ms == 3_600_000
        assert block_b.duration_ms == 1_800_000  # Full 30 minutes

        # Segment sum equals block duration
        seg_sum_b = sum(s["segment_duration_ms"] for s in block_b.segments)
        assert seg_sum_b == block_b.duration_ms

        # Contiguous
        assert block_b.start_utc_ms == block_a.end_utc_ms


# =============================================================================
# 8. INV-BLOCKPLAN-HORIZON-MISS: Missing schedule data policy
# =============================================================================


class TestMissingScheduleDataPolicy:
    """INV-BLOCKPLAN-HORIZON-MISS: Missing schedule data is a horizon failure, not execution panic."""

    def test_resolve_returns_none_when_no_service(self):
        producer = BlockPlanProducer(channel_id="no-svc", schedule_service=None, clock=None)
        producer._next_block_start_ms = 0
        assert producer._resolve_plan_for_block() is None

    def test_resolve_at_returns_none_when_no_service(self):
        producer = BlockPlanProducer(channel_id="no-svc", schedule_service=None, clock=None)
        assert producer._resolve_plan_for_block_at(12345) is None

    def test_feed_ahead_skips_on_none_no_crash(self):
        """When schedule data is missing, _feed_ahead skips without crashing."""
        from retrovue.runtime.channel_manager import _FeedState

        producer = BlockPlanProducer(channel_id="gap-test", schedule_service=None, clock=None)
        producer._started = True
        producer._session_ended = False
        producer._feed_credits = 2
        producer._feed_state = _FeedState.RUNNING

        # Create a minimal mock session
        class StubSession:
            on_block_complete = None
            on_session_end = None
            is_running = True

        producer._session = StubSession()
        # Should not raise — just returns silently
        producer._feed_ahead()
        # No block was generated (pending_block is still None)
        assert producer._pending_block is None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
