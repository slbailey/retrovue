"""
Simple Grid Schedule Manager - Phase 0 Implementation

Implements ScheduleManager protocol as defined in:
    docs/contracts/runtime/ScheduleManagerContract.md

This is the Phase 0 implementation: deterministic grid-based scheduling
with a single main show and filler content.
"""

from datetime import datetime, timedelta

from retrovue.runtime.schedule_types import (
    PlayoutSegment,
    ProgramBlock,
    SimpleGridConfig,
    ScheduleError,
)


class SimpleGridScheduleManager:
    """
    Phase 0 ScheduleManager implementation.

    Generates ProgramBlocks based on fixed grid slots with:
    - Main show starting at each grid boundary
    - Filler content filling the gap until next boundary
    """

    def __init__(self, config: SimpleGridConfig):
        self._config = config

    def get_program_at(self, channel_id: str, at_time: datetime) -> ProgramBlock:
        """
        Get the program block containing the specified time.

        Returns ProgramBlock where: block_start <= at_time < block_end
        """
        block_start = self._floor_to_grid_boundary(at_time)
        block_end = block_start + timedelta(minutes=self._config.grid_minutes)
        segments = self._build_segments(block_start, block_end)

        return ProgramBlock(
            block_start=block_start,
            block_end=block_end,
            segments=segments,
        )

    def get_next_program(self, channel_id: str, after_time: datetime) -> ProgramBlock:
        """
        Get the next program block at or after the specified time.

        Boundary behavior:
        - If after_time is exactly on a grid boundary, returns that boundary's block
        - If after_time is between boundaries, returns the next boundary's block
        """
        block_start = self._ceil_to_grid_boundary(after_time)
        block_end = block_start + timedelta(minutes=self._config.grid_minutes)
        segments = self._build_segments(block_start, block_end)

        return ProgramBlock(
            block_start=block_start,
            block_end=block_end,
            segments=segments,
        )

    def _floor_to_grid_boundary(self, t: datetime) -> datetime:
        """Floor time to the nearest grid boundary at or before t."""
        day_start = self._get_programming_day_start(t)
        seconds_since_day_start = (t - day_start).total_seconds()
        grid_seconds = self._config.grid_minutes * 60
        floored_seconds = (seconds_since_day_start // grid_seconds) * grid_seconds
        return day_start + timedelta(seconds=floored_seconds)

    def _ceil_to_grid_boundary(self, t: datetime) -> datetime:
        """Ceil time to the nearest grid boundary at or after t."""
        floored = self._floor_to_grid_boundary(t)
        if floored == t:
            return t
        return floored + timedelta(minutes=self._config.grid_minutes)

    def _get_programming_day_start(self, t: datetime) -> datetime:
        """Get the programming day start for the given time."""
        day_start = t.replace(
            hour=self._config.programming_day_start_hour,
            minute=0,
            second=0,
            microsecond=0,
        )
        if t < day_start:
            day_start -= timedelta(days=1)
        return day_start

    def _build_segments(
        self, block_start: datetime, block_end: datetime
    ) -> list[PlayoutSegment]:
        """Build the segment list for a program block."""
        main_show_end = block_start + timedelta(
            seconds=self._config.main_show_duration_seconds
        )

        main_segment = PlayoutSegment(
            start_utc=block_start,
            end_utc=main_show_end,
            file_path=self._config.main_show_path,
            seek_offset_seconds=0.0,
        )

        if main_show_end < block_end:
            filler_segment = PlayoutSegment(
                start_utc=main_show_end,
                end_utc=block_end,
                file_path=self._config.filler_path,
                seek_offset_seconds=0.0,
            )
            return [main_segment, filler_segment]

        return [main_segment]
