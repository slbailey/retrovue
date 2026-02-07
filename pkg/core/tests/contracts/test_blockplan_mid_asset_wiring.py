"""
Contract Tests: BlockPlan Mid-Asset Seek Wiring

These tests verify that BlockPlanProducer._generate_next_block() correctly
wires asset_uri and asset_start_offset_ms into generated blocks when the
playout plan contains entries with non-zero offsets.

This is a plan-wiring test, NOT a decoder test. It verifies the data flow
from playout_plan → FedBlock/BlockPlan segment fields.

Contract Reference: PlayoutAuthorityContract.md "Mid-Asset Seek Strategy"
Copyright (c) 2025 RetroVue
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from retrovue.runtime.channel_manager import BlockPlanProducer


# =============================================================================
# Test Infrastructure
# =============================================================================

SAMPLE_A = "/opt/retrovue/assets/SampleA.mp4"
SAMPLE_B = "/opt/retrovue/assets/SampleB.mp4"

TWO_ASSET_PLAN = [
    {
        "asset_path": SAMPLE_A,
        "asset_start_offset_ms": 0,
        "segment_type": "content",
    },
    {
        "asset_path": SAMPLE_B,
        "asset_start_offset_ms": 12000,
        "segment_type": "content",
    },
]


def make_producer(block_duration_ms: int = 5000) -> BlockPlanProducer:
    """Create a BlockPlanProducer with mock dependencies for plan generation tests."""
    return BlockPlanProducer(
        channel_id="mock",
        configuration={"block_duration_ms": block_duration_ms},
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
        block = producer._generate_next_block(TWO_ASSET_PLAN)

        assert block.block_id == "BLOCK-mock-0"
        assert len(block.segments) == 1
        seg = block.segments[0]
        assert seg["asset_uri"] == SAMPLE_A
        assert seg["asset_start_offset_ms"] == 0

    def test_block_1_uses_sample_b_mid_offset(self):
        """BLOCK-mock-1 must use SampleB with offset=12000."""
        producer = make_producer()
        # Generate block 0 first, advance cursor
        b0 = producer._generate_next_block(TWO_ASSET_PLAN)
        producer._advance_cursor(b0)
        # Now generate block 1
        block = producer._generate_next_block(TWO_ASSET_PLAN)

        assert block.block_id == "BLOCK-mock-1"
        assert len(block.segments) == 1
        seg = block.segments[0]
        assert seg["asset_uri"] == SAMPLE_B
        assert seg["asset_start_offset_ms"] == 12000

    def test_round_robin_cycles_back(self):
        """Block 2 should cycle back to SampleA (index 2 % 2 == 0)."""
        producer = make_producer()
        b = producer._generate_next_block(TWO_ASSET_PLAN)  # block 0
        producer._advance_cursor(b)
        b = producer._generate_next_block(TWO_ASSET_PLAN)  # block 1
        producer._advance_cursor(b)
        block = producer._generate_next_block(TWO_ASSET_PLAN)  # block 2

        assert block.block_id == "BLOCK-mock-2"
        seg = block.segments[0]
        assert seg["asset_uri"] == SAMPLE_A
        assert seg["asset_start_offset_ms"] == 0

    def test_block_timing_contiguous(self):
        """Blocks must form a contiguous timeline (no gaps)."""
        producer = make_producer(block_duration_ms=5000)
        blocks = []
        for _ in range(4):
            b = producer._generate_next_block(TWO_ASSET_PLAN)
            blocks.append(b)
            producer._advance_cursor(b)

        for i in range(1, len(blocks)):
            assert blocks[i].start_utc_ms == blocks[i - 1].end_utc_ms, (
                f"Block {i} start_utc_ms={blocks[i].start_utc_ms} "
                f"!= Block {i-1} end_utc_ms={blocks[i-1].end_utc_ms}"
            )

    def test_block_duration_matches_config(self):
        """Every block must have the configured duration."""
        producer = make_producer(block_duration_ms=5000)
        blocks = []
        for _ in range(4):
            b = producer._generate_next_block(TWO_ASSET_PLAN)
            blocks.append(b)
            producer._advance_cursor(b)

        for b in blocks:
            assert b.duration_ms == 5000

    def test_segment_duration_matches_block(self):
        """Each segment's duration must equal block duration."""
        producer = make_producer(block_duration_ms=5000)
        blocks = []
        for _ in range(4):
            b = producer._generate_next_block(TWO_ASSET_PLAN)
            blocks.append(b)
            producer._advance_cursor(b)

        for b in blocks:
            assert b.segments[0]["segment_duration_ms"] == 5000

    def test_empty_plan_defaults_to_sample_a(self):
        """An empty playout_plan falls back to SampleA with offset=0."""
        producer = make_producer()
        block = producer._generate_next_block([])

        seg = block.segments[0]
        assert seg["asset_uri"] == "assets/SampleA.mp4"
        assert seg["asset_start_offset_ms"] == 0

    def test_single_entry_plan_no_offset(self):
        """A single-entry plan without offset field defaults to 0."""
        plan = [{"asset_path": SAMPLE_A}]
        producer = make_producer()
        block = producer._generate_next_block(plan)

        seg = block.segments[0]
        assert seg["asset_uri"] == SAMPLE_A
        assert seg["asset_start_offset_ms"] == 0

    def test_retained_plan_used_after_start(self):
        """_playout_plan stored at start() is available for feeding."""
        producer = make_producer()
        # Simulate what start() does: store the plan
        producer._playout_plan = TWO_ASSET_PLAN

        # Simulate what _on_block_complete does: use retained plan
        block = producer._generate_next_block(producer._playout_plan)
        assert block.segments[0]["asset_uri"] == SAMPLE_A
        producer._advance_cursor(block)

        block = producer._generate_next_block(producer._playout_plan)
        assert block.segments[0]["asset_uri"] == SAMPLE_B
        assert block.segments[0]["asset_start_offset_ms"] == 12000
