"""
Schedule Manager Implementations

Implements ScheduleManager protocol as defined in:
    docs/contracts/runtime/ScheduleManagerContract.md (Phase 0)
    docs/contracts/runtime/ScheduleManagerPhase1Contract.md (Phase 1)
    docs/contracts/runtime/ScheduleManagerPhase2Contract.md (Phase 2)
"""

from datetime import datetime, timedelta

from retrovue.runtime.schedule_types import (
    PlayoutSegment,
    ProgramBlock,
    SimpleGridConfig,
    DailyScheduleConfig,
    ScheduledProgram,
    ScheduleError,
    ScheduleEntry,
    ScheduleDay,
    ScheduleDayConfig,
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


class DailyScheduleManager:
    """
    Phase 1 ScheduleManager implementation.

    Generates ProgramBlocks based on a daily schedule with multiple programs.
    Programs may span multiple grid slots. Unscheduled slots are filled with filler.
    """

    def __init__(self, config: DailyScheduleConfig):
        self._config = config

    def get_program_at(self, channel_id: str, at_time: datetime) -> ProgramBlock:
        """
        Get the program block containing the specified time.

        Returns ProgramBlock where: block_start <= at_time < block_end
        """
        block_start = self._floor_to_grid_boundary(at_time)
        block_end = block_start + timedelta(minutes=self._config.grid_minutes)
        segments = self._build_segments(block_start, block_end, at_time)

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
        segments = self._build_segments(block_start, block_end, block_start)

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

    def _find_program_at(
        self, block_start: datetime
    ) -> tuple[ScheduledProgram | None, datetime | None]:
        """
        Find the program (if any) that covers the given grid slot.

        Checks both the current programming day AND the previous programming day,
        since a program from yesterday may still be running (cross-day programs).

        Returns (program, program_start_datetime) or (None, None) if unscheduled.
        """
        current_day_start = self._get_programming_day_start(block_start)
        previous_day_start = current_day_start - timedelta(days=1)

        day_start_hour_seconds = self._config.programming_day_start_hour * 3600

        # Check both current and previous programming days
        for day_start in [current_day_start, previous_day_start]:
            for program in self._config.programs:
                # Convert program slot_time to seconds since midnight
                program_midnight_seconds = (
                    program.slot_time.hour * 3600
                    + program.slot_time.minute * 60
                    + program.slot_time.second
                )

                # Convert to seconds since programming day start
                if program_midnight_seconds >= day_start_hour_seconds:
                    # Same calendar day as programming day start
                    program_seconds = program_midnight_seconds - day_start_hour_seconds
                else:
                    # Next calendar day (before programming day start hour)
                    program_seconds = (
                        (24 * 3600 - day_start_hour_seconds) + program_midnight_seconds
                    )

                # Calculate absolute program start/end times
                program_start = day_start + timedelta(seconds=program_seconds)
                program_end = program_start + timedelta(seconds=program.duration_seconds)

                # Check if block_start falls within program's time window
                if program_start <= block_start < program_end:
                    return (program, program_start)

        return (None, None)

    def _build_segments(
        self, block_start: datetime, block_end: datetime, query_time: datetime
    ) -> list[PlayoutSegment]:
        """Build the segment list for a program block."""
        program, program_start = self._find_program_at(block_start)

        if program is None:
            # Unscheduled slot: filler for entire slot
            return [
                PlayoutSegment(
                    start_utc=block_start,
                    end_utc=block_end,
                    file_path=self._config.filler_path,
                    seek_offset_seconds=0.0,
                )
            ]

        # Calculate where program ends
        program_end = program_start + timedelta(seconds=program.duration_seconds)

        # Program segment: from block_start (or segment start) to min(program_end, block_end)
        segment_end = min(program_end, block_end)

        # Calculate seek offset: how far into the program this block starts
        seek_offset = (block_start - program_start).total_seconds()

        segments = [
            PlayoutSegment(
                start_utc=block_start,
                end_utc=segment_end,
                file_path=program.file_path,
                seek_offset_seconds=seek_offset,
            )
        ]

        # If program ends before block ends, add filler
        if program_end < block_end:
            segments.append(
                PlayoutSegment(
                    start_utc=program_end,
                    end_utc=block_end,
                    file_path=self._config.filler_path,
                    seek_offset_seconds=0.0,
                )
            )

        return segments


class ScheduleDayScheduleManager:
    """
    Phase 2 ScheduleManager implementation.

    Generates ProgramBlocks based on ScheduleDay entities retrieved from
    a ScheduleSource. Supports day-specific schedules while preserving
    all Phase 1 behavior (multi-slot programs, cross-day programs, etc.).
    """

    def __init__(self, config: ScheduleDayConfig):
        self._config = config

    def get_program_at(self, channel_id: str, at_time: datetime) -> ProgramBlock:
        """
        Get the program block containing the specified time.

        Returns ProgramBlock where: block_start <= at_time < block_end
        """
        block_start = self._floor_to_grid_boundary(at_time)
        block_end = block_start + timedelta(minutes=self._config.grid_minutes)
        segments = self._build_segments(channel_id, block_start, block_end)

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
        segments = self._build_segments(channel_id, block_start, block_end)

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

    def _get_programming_day_date(self, t: datetime) -> datetime:
        """Get the calendar date of the programming day containing t."""
        return self._get_programming_day_start(t).date()

    def _find_entry_at(
        self, channel_id: str, block_start: datetime
    ) -> tuple[ScheduleEntry | None, datetime | None]:
        """
        Find the entry (if any) that covers the given grid slot.

        Checks both the current programming day AND the previous programming day,
        since an entry from yesterday may still be running (cross-day programs).

        Returns (entry, entry_start_datetime) or (None, None) if unscheduled.
        """
        current_day_start = self._get_programming_day_start(block_start)
        previous_day_start = current_day_start - timedelta(days=1)

        day_start_hour_seconds = self._config.programming_day_start_hour * 3600

        # Check both current and previous programming days (bounded by INV-P2-004)
        for day_start in [current_day_start, previous_day_start]:
            programming_day_date = day_start.date()
            schedule_day = self._config.schedule_source.get_schedule_day(
                channel_id, programming_day_date
            )

            if schedule_day is None:
                continue

            for entry in schedule_day.entries:
                # Convert entry slot_time to seconds since midnight
                entry_midnight_seconds = (
                    entry.slot_time.hour * 3600
                    + entry.slot_time.minute * 60
                    + entry.slot_time.second
                )

                # Convert to seconds since programming day start
                if entry_midnight_seconds >= day_start_hour_seconds:
                    # Same calendar day as programming day start
                    entry_seconds = entry_midnight_seconds - day_start_hour_seconds
                else:
                    # Next calendar day (before programming day start hour)
                    entry_seconds = (
                        (24 * 3600 - day_start_hour_seconds) + entry_midnight_seconds
                    )

                # Calculate absolute entry start/end times
                entry_start = day_start + timedelta(seconds=entry_seconds)
                entry_end = entry_start + timedelta(seconds=entry.duration_seconds)

                # Check if block_start falls within entry's time window
                if entry_start <= block_start < entry_end:
                    return (entry, entry_start)

        return (None, None)

    def _build_segments(
        self, channel_id: str, block_start: datetime, block_end: datetime
    ) -> list[PlayoutSegment]:
        """Build the segment list for a program block."""
        entry, entry_start = self._find_entry_at(channel_id, block_start)

        if entry is None:
            # Unscheduled slot: filler for entire slot
            return [
                PlayoutSegment(
                    start_utc=block_start,
                    end_utc=block_end,
                    file_path=self._config.filler_path,
                    seek_offset_seconds=0.0,
                )
            ]

        # Calculate where entry ends
        entry_end = entry_start + timedelta(seconds=entry.duration_seconds)

        # Entry segment: from block_start to min(entry_end, block_end)
        segment_end = min(entry_end, block_end)

        # Calculate seek offset: how far into the entry this block starts
        seek_offset = (block_start - entry_start).total_seconds()

        segments = [
            PlayoutSegment(
                start_utc=block_start,
                end_utc=segment_end,
                file_path=entry.file_path,
                seek_offset_seconds=seek_offset,
            )
        ]

        # If entry ends before block ends, add filler
        if entry_end < block_end:
            segments.append(
                PlayoutSegment(
                    start_utc=entry_end,
                    end_utc=block_end,
                    file_path=self._config.filler_path,
                    seek_offset_seconds=0.0,
                )
            )

        return segments
