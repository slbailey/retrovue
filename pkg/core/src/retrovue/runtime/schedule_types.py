"""
Schedule Manager Contract Types

Canonical data structures for Schedule Manager as defined in:
    docs/contracts/runtime/ScheduleManagerContract.md

These types are the authoritative definitions. Tests and implementations
MUST import from this module, not redefine locally.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class PlayoutSegment:
    """
    A single file to play with timing information.

    A PlayoutSegment represents a time-bounded playback instruction.
    In later phases, segments may reference partial assets, concatenations,
    or synthesized outputs.
    """
    start_utc: datetime       # When this segment starts (wall clock)
    end_utc: datetime         # When this segment ends (wall clock)
    file_path: str            # Path to the media file
    seek_offset_seconds: float = 0.0  # Where to start in the file

    @property
    def duration_seconds(self) -> float:
        """Duration of this segment in seconds."""
        return (self.end_utc - self.start_utc).total_seconds()


@dataclass
class ProgramBlock:
    """
    A complete program unit bounded by grid boundaries.

    NOTE: ProgramBlock is a Phase 0 abstraction representing one grid slot's
    worth of playout. In later phases, this type may be replaced or wrapped
    by continuous playlog segments that are not grid-bounded. Do not build
    dependencies on grid-bounded semantics beyond Phase 0.
    """
    block_start: datetime     # Grid boundary start (e.g., 9:00:00)
    block_end: datetime       # Grid boundary end (e.g., 9:30:00)
    segments: list[PlayoutSegment]  # Ordered list of segments

    @property
    def duration_seconds(self) -> float:
        """Duration of this block in seconds."""
        return (self.block_end - self.block_start).total_seconds()


@dataclass
class SimpleGridConfig:
    """
    Phase 0 configuration: single main show + filler.

    This is a simplified configuration for proving the core scheduling loop.
    Later phases will use richer configuration from SchedulePlan/ScheduleDay.
    """
    grid_minutes: int              # Grid slot duration (e.g., 30)
    main_show_path: str            # Path to main show file
    main_show_duration_seconds: float  # Duration of main show
    filler_path: str               # Path to filler file
    filler_duration_seconds: float # Duration of filler (must be >= grid - main)
    programming_day_start_hour: int = 6  # Broadcast day start (default 6 AM)


class ScheduleManager(Protocol):
    """
    Protocol for schedule manager implementations.

    ScheduleManager provides playout instructions to ChannelManager.
    It answers: "What should be playing right now, and what comes next?"

    All time parameters MUST come from MasterClock. Implementations
    MUST NOT access system clock directly.
    """

    def get_program_at(self, channel_id: str, at_time: datetime) -> ProgramBlock:
        """
        Get the program block containing the specified time.

        Args:
            channel_id: The channel identifier
            at_time: The MasterClock-provided UTC time to query

        Returns:
            ProgramBlock where: block_start <= at_time < block_end

        Raises:
            ScheduleError: If no schedule is configured for the channel
        """
        ...

    def get_next_program(self, channel_id: str, after_time: datetime) -> ProgramBlock:
        """
        Get the next program block after the specified time.

        Boundary behavior:
            - after_time is treated as EXCLUSIVE
            - If after_time falls exactly on a grid boundary, that boundary's
              block is returned (the boundary belongs to the NEW block)
            - If after_time is mid-block, the next grid boundary's block is returned

        Args:
            channel_id: The channel identifier
            after_time: The MasterClock-provided UTC time

        Returns:
            The next ProgramBlock where: block_start >= after_time
            AND block_start is the nearest grid boundary >= after_time

        Raises:
            ScheduleError: If no schedule is configured for the channel
        """
        ...


class ScheduleError(Exception):
    """Raised when schedule operations fail."""
    pass
