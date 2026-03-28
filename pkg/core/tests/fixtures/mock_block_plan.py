"""
Fixture: MockBlockPlanProvider

Test-only mock for BlockPlan providers.
Moved from retrovue.runtime.playout_session — production modules contain only production code.
"""
from __future__ import annotations

from typing import Optional

from retrovue.runtime.playout_session import BlockPlan


class MockBlockPlanProvider:
    """
    Mock provider that returns fixture BlockPlans for testing.

    Returns 3 blocks in sequence, each 10 seconds long.
    """

    def __init__(self, channel_id: int = 1):
        self.channel_id = channel_id
        self._block_index = 0
        self._base_time_ms = 0

    def reset(self, base_time_ms: int = 0):
        """Reset provider to start from given time."""
        self._block_index = 0
        self._base_time_ms = base_time_ms

    def get_next_blocks(self, count: int = 2) -> list[BlockPlan]:
        """Get the next N blocks."""
        blocks = []
        for _ in range(count):
            block = self._create_block()
            if block:
                blocks.append(block)
        return blocks

    def get_next_block(self) -> Optional[BlockPlan]:
        """Get the next block, or None if exhausted."""
        return self._create_block()

    def _create_block(self) -> Optional[BlockPlan]:
        """Create the next block in sequence."""
        # We have 3 fixture blocks
        fixtures = [
            ("BLOCK-A", "assets/SampleA.mp4"),
            ("BLOCK-B", "assets/SampleB.mp4"),
            ("BLOCK-C", "assets/SampleC.mp4"),
        ]

        if self._block_index >= len(fixtures):
            return None

        block_id, asset = fixtures[self._block_index]
        duration_ms = 10000  # 10 seconds per block

        start_ms = self._base_time_ms + (self._block_index * duration_ms)
        end_ms = start_ms + duration_ms

        block = BlockPlan(
            block_id=block_id,
            channel_id=self.channel_id,
            start_utc_ms=start_ms,
            end_utc_ms=end_ms,
            segments=[{
                "segment_index": 0,
                "asset_uri": asset,
                "asset_start_offset_ms": 0,
                "segment_duration_ms": duration_ms,
            }]
        )

        self._block_index += 1
        return block

    @property
    def has_more(self) -> bool:
        return self._block_index < 3
