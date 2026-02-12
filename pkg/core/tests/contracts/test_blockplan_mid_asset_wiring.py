"""
Contract Tests: BlockPlan Mid-Asset Seek Wiring

These tests verify that BlockPlanProducer._generate_next_block() correctly
wires asset_uri and asset_start_offset_ms into generated blocks when the
ScheduledBlock contains segments with non-zero offsets.

This is a plan-wiring test, NOT a decoder test. It verifies the data flow
from ScheduledBlock → BlockPlan segment fields.

Contract Reference: PlayoutAuthorityContract.md "Mid-Asset Seek Strategy"
Copyright (c) 2025 RetroVue
"""

from __future__ import annotations

import pytest

from retrovue.runtime.channel_manager import BlockPlanProducer
from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "fixtures"))
from fake_schedule_service import FakeScheduleService


# =============================================================================
# Test Infrastructure
# =============================================================================

SAMPLE_A = "/opt/retrovue/assets/SampleA.mp4"
SAMPLE_B = "/opt/retrovue/assets/SampleB.mp4"

# Two-asset round-robin pattern (replaces the old TWO_ASSET_PLAN list[dict])
_ASSET_PATTERN = [
    (SAMPLE_A, 0, "content"),
    (SAMPLE_B, 12000, "content"),
]


def _sb(
    block_index: int,
    start_ms: int,
    dur_ms: int = 5000,
    channel_id: str = "mock",
) -> ScheduledBlock:
    """Create a ScheduledBlock from the two-asset pattern at round-robin index."""
    uri, offset, stype = _ASSET_PATTERN[block_index % len(_ASSET_PATTERN)]
    return ScheduledBlock(
        block_id=f"BLOCK-{channel_id}-{block_index}",
        start_utc_ms=start_ms,
        end_utc_ms=start_ms + dur_ms,
        segments=(
            ScheduledSegment(
                segment_type=stype,
                asset_uri=uri,
                asset_start_offset_ms=offset,
                segment_duration_ms=dur_ms,
            ),
        ),
    )


def make_producer() -> BlockPlanProducer:
    """Create a BlockPlanProducer with mock dependencies for plan generation tests."""
    return BlockPlanProducer(
        channel_id="mock",
        channel_config=None,  # Uses MOCK_CHANNEL_CONFIG default
        schedule_service=None,
        clock=None,
    )


# =============================================================================
# Contract Tests
# =============================================================================


class TestMidAssetBlockPlanWiring:
    """Verify _generate_next_block produces correct segment fields."""

    def test_block_0_uses_sample_a_offset_zero(self):
        """BLOCK-mock-0 must use SampleA with offset=0."""
        producer = make_producer()
        block = producer._generate_next_block(_sb(0, 0))

        assert block.block_id == "BLOCK-mock-0"
        assert len(block.segments) == 1
        seg = block.segments[0]
        assert seg["asset_uri"] == SAMPLE_A
        assert seg["asset_start_offset_ms"] == 0

    def test_block_1_uses_sample_b_mid_offset(self):
        """BLOCK-mock-1 must use SampleB with offset=12000."""
        producer = make_producer()
        # Generate block 0 first, advance cursor
        b0 = producer._generate_next_block(_sb(0, 0))
        producer._advance_cursor(b0)
        # Now generate block 1
        block = producer._generate_next_block(_sb(1, 5000))

        assert block.block_id == "BLOCK-mock-1"
        assert len(block.segments) == 1
        seg = block.segments[0]
        assert seg["asset_uri"] == SAMPLE_B
        assert seg["asset_start_offset_ms"] == 12000

    def test_round_robin_cycles_back(self):
        """Block 2 should cycle back to SampleA (index 2 % 2 == 0)."""
        producer = make_producer()
        b = producer._generate_next_block(_sb(0, 0))  # block 0
        producer._advance_cursor(b)
        b = producer._generate_next_block(_sb(1, 5000))  # block 1
        producer._advance_cursor(b)
        block = producer._generate_next_block(_sb(2, 10000))  # block 2

        assert block.block_id == "BLOCK-mock-2"
        seg = block.segments[0]
        assert seg["asset_uri"] == SAMPLE_A
        assert seg["asset_start_offset_ms"] == 0

    def test_block_timing_contiguous(self):
        """Blocks must form a contiguous timeline (no gaps)."""
        producer = make_producer()
        blocks = []
        start = 0
        for i in range(4):
            b = producer._generate_next_block(_sb(i, start))
            blocks.append(b)
            producer._advance_cursor(b)
            start += 5000

        for i in range(1, len(blocks)):
            assert blocks[i].start_utc_ms == blocks[i - 1].end_utc_ms, (
                f"Block {i} start_utc_ms={blocks[i].start_utc_ms} "
                f"!= Block {i-1} end_utc_ms={blocks[i-1].end_utc_ms}"
            )

    def test_block_duration_matches_scheduled(self):
        """Every block must have the scheduled duration."""
        producer = make_producer()
        blocks = []
        start = 0
        for i in range(4):
            b = producer._generate_next_block(_sb(i, start))
            blocks.append(b)
            producer._advance_cursor(b)
            start += 5000

        for b in blocks:
            assert b.duration_ms == 5000

    def test_segment_duration_matches_block(self):
        """Each segment's duration must equal block duration."""
        producer = make_producer()
        blocks = []
        start = 0
        for i in range(4):
            b = producer._generate_next_block(_sb(i, start))
            blocks.append(b)
            producer._advance_cursor(b)
            start += 5000

        for b in blocks:
            assert b.segments[0]["segment_duration_ms"] == 5000

    def test_default_scheduled_block(self):
        """A ScheduledBlock with default SampleA produces correct wiring."""
        producer = make_producer()
        sb = ScheduledBlock(
            block_id="BLOCK-mock-0",
            start_utc_ms=0,
            end_utc_ms=5000,
            segments=(
                ScheduledSegment(
                    segment_type="episode",
                    asset_uri="assets/SampleA.mp4",
                    asset_start_offset_ms=0,
                    segment_duration_ms=5000,
                ),
            ),
        )
        block = producer._generate_next_block(sb)

        seg = block.segments[0]
        assert seg["asset_uri"] == "assets/SampleA.mp4"
        assert seg["asset_start_offset_ms"] == 0

    def test_single_segment_no_offset(self):
        """A single-segment ScheduledBlock with offset=0 wires correctly."""
        producer = make_producer()
        sb = ScheduledBlock(
            block_id="BLOCK-mock-0",
            start_utc_ms=0,
            end_utc_ms=5000,
            segments=(
                ScheduledSegment(
                    segment_type="episode",
                    asset_uri=SAMPLE_A,
                    asset_start_offset_ms=0,
                    segment_duration_ms=5000,
                ),
            ),
        )
        block = producer._generate_next_block(sb)

        seg = block.segments[0]
        assert seg["asset_uri"] == SAMPLE_A
        assert seg["asset_start_offset_ms"] == 0

    def test_schedule_service_blocks_used_for_feeding(self):
        """Schedule service provides ScheduledBlocks for feeding."""
        svc = FakeScheduleService(
            channel_id="mock",
            block_duration_ms=5000,
            asset_uri=SAMPLE_A,
        )
        producer = BlockPlanProducer(
            channel_id="mock",
            channel_config=None,
            schedule_service=svc,
            clock=None,
        )
        producer._next_block_start_ms = 0

        sb = producer._resolve_plan_for_block()
        assert sb is not None
        block = producer._generate_next_block(sb)
        assert block.segments[0]["asset_uri"] == SAMPLE_A
        producer._advance_cursor(block)

        sb2 = producer._resolve_plan_for_block()
        assert sb2 is not None
        block2 = producer._generate_next_block(sb2)
        assert block2.segments[0]["asset_uri"] == SAMPLE_A
