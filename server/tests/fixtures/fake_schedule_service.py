"""FakeScheduleService — deterministic schedule service for tests.

Returns pre-configured ScheduledBlock objects.  Execution tests use this
instead of mocking dicts or patching methods.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment


class FakeScheduleService:
    """Deterministic schedule service for contract tests.

    Constructs grid-aligned ScheduledBlocks from a fixed block_duration_ms
    and a repeating segment pattern.  All timing decisions are made here
    (schedule layer), not in the test or in execution code.
    """

    def __init__(
        self,
        channel_id: str = "test-ch",
        block_duration_ms: int = 30_000,
        asset_uri: str = "test.mp4",
        segment_type: str = "episode",
        grid_origin_utc_ms: int = 0,
    ):
        self.channel_id = channel_id
        self.block_duration_ms = block_duration_ms
        self.asset_uri = asset_uri
        self.segment_type = segment_type
        self.grid_origin_utc_ms = grid_origin_utc_ms
        self._call_log: list[tuple[str, int]] = []

    def get_playout_plan_now(self, channel_id: str, at_station_time: datetime) -> list[dict[str, Any]]:
        """Legacy protocol method — returns [] to signal callers to use get_block_at."""
        return []

    def get_block_at(self, channel_id: str, utc_ms: int) -> ScheduledBlock | None:
        """Return a grid-aligned ScheduledBlock covering utc_ms."""
        self._call_log.append((channel_id, utc_ms))
        origin = self.grid_origin_utc_ms
        dur = self.block_duration_ms
        block_start = origin + ((utc_ms - origin) // dur) * dur
        block_end = block_start + dur
        block_index = (block_start - origin) // dur

        return ScheduledBlock(
            block_id=f"BLOCK-{channel_id}-{block_index}",
            start_utc_ms=block_start,
            end_utc_ms=block_end,
            segments=(
                ScheduledSegment(
                    segment_type=self.segment_type,
                    asset_uri=self.asset_uri,
                    asset_start_offset_ms=0,
                    segment_duration_ms=dur,
                ),
            ),
        )

    def load_schedule(self, channel_id: str) -> tuple[bool, str | None]:
        return (True, None)
