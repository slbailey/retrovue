"""
Schedule Manager Implementations

Implements ScheduleManager protocol as defined in:
    docs/contracts/runtime/ScheduleManagerContract.md (Phase 0)
    docs/contracts/runtime/ScheduleManagerPhase1Contract.md (Phase 1)
    docs/contracts/runtime/ScheduleManagerPhase2Contract.md (Phase 2)
    docs/contracts/runtime/ScheduleManagerPhase3Contract.md (Phase 3)
"""

from datetime import datetime, date, time, timedelta
from fractions import Fraction
import hashlib
import math

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
    # Phase 3 types
    ProgramRefType,
    ProgramRef,
    ScheduleSlot,
    Episode,
    Program,
    ResolvedAsset,
    ResolvedSlot,
    SequenceState,
    ResolvedScheduleDay,
    EPGEvent,
    Phase3Config,
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
        INV-FRAME-002: padding_frames is computed as grid_frames - content_frames.
        """
        block_start = self._floor_to_grid_boundary(at_time)
        block_end = block_start + timedelta(minutes=self._config.grid_minutes)
        segments = self._build_segments(block_start, block_end)
        fps = self._config.fps

        # INV-FRAME-002: Compute padding in frames
        grid_duration = (block_end - block_start).total_seconds()
        grid_frames = int(grid_duration * fps)
        content_frames = sum(s.frame_count for s in segments)
        padding_frames = max(0, grid_frames - content_frames)

        return ProgramBlock(
            block_start=block_start,
            block_end=block_end,
            segments=segments,
            fps=fps,
            padding_frames=padding_frames,
        )

    def get_next_program(self, channel_id: str, after_time: datetime) -> ProgramBlock:
        """
        Get the next program block at or after the specified time.

        Boundary behavior:
        - If after_time is exactly on a grid boundary, returns that boundary's block
        - If after_time is between boundaries, returns the next boundary's block
        INV-FRAME-002: padding_frames is computed as grid_frames - content_frames.
        """
        block_start = self._ceil_to_grid_boundary(after_time)
        block_end = block_start + timedelta(minutes=self._config.grid_minutes)
        segments = self._build_segments(block_start, block_end)
        fps = self._config.fps

        # INV-FRAME-002: Compute padding in frames
        grid_duration = (block_end - block_start).total_seconds()
        grid_frames = int(grid_duration * fps)
        content_frames = sum(s.frame_count for s in segments)
        padding_frames = max(0, grid_frames - content_frames)

        return ProgramBlock(
            block_start=block_start,
            block_end=block_end,
            segments=segments,
            fps=fps,
            padding_frames=padding_frames,
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
        """
        Build the segment list for a program block.

        INV-FRAME-001: Uses PlayoutSegment.from_time_based() to convert
        time boundaries to frame-indexed execution specification.
        Time-to-frame conversion happens HERE (Core), not at execution (Air).
        """
        fps = self._config.fps
        main_show_end = block_start + timedelta(
            seconds=self._config.main_show_duration_seconds
        )

        # INV-FRAME-001: Create frame-indexed segment
        main_segment = PlayoutSegment.from_time_based(
            start_utc=block_start,
            end_utc=main_show_end,
            file_path=self._config.main_show_path,
            fps=fps,
            seek_offset_seconds=0.0,
            segment_type="content",
            allows_padding=False,
        )

        if main_show_end < block_end:
            # INV-FRAME-001: Filler allows padding at block end
            filler_segment = PlayoutSegment.from_time_based(
                start_utc=main_show_end,
                end_utc=block_end,
                file_path=self._config.filler_path,
                fps=fps,
                seek_offset_seconds=0.0,
                segment_type="filler",
                allows_padding=True,  # Padding goes after filler if needed
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
        """
        Build the segment list for a program block.

        INV-FRAME-001: Uses PlayoutSegment.from_time_based() to convert
        time boundaries to frame-indexed execution specification.
        """
        # Default fps for Phase 1 (no fps in config, use 30)
        fps = Fraction(30, 1)
        program, program_start = self._find_program_at(block_start)

        if program is None:
            # Unscheduled slot: filler for entire slot
            return [
                PlayoutSegment.from_time_based(
                    start_utc=block_start,
                    end_utc=block_end,
                    file_path=self._config.filler_path,
                    fps=fps,
                    seek_offset_seconds=0.0,
                    segment_type="filler",
                )
            ]

        # Calculate where program ends
        program_end = program_start + timedelta(seconds=program.duration_seconds)

        # Program segment: from block_start (or segment start) to min(program_end, block_end)
        segment_end = min(program_end, block_end)

        # Calculate seek offset: how far into the program this block starts
        seek_offset = (block_start - program_start).total_seconds()

        segments = [
            PlayoutSegment.from_time_based(
                start_utc=block_start,
                end_utc=segment_end,
                file_path=program.file_path,
                fps=fps,
                seek_offset_seconds=seek_offset,
                segment_type="content",
            )
        ]

        # If program ends before block ends, add filler
        if program_end < block_end:
            segments.append(
                PlayoutSegment.from_time_based(
                    start_utc=program_end,
                    end_utc=block_end,
                    file_path=self._config.filler_path,
                    fps=fps,
                    seek_offset_seconds=0.0,
                    segment_type="filler",
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
        """
        Build the segment list for a program block.

        INV-FRAME-001: Uses PlayoutSegment.from_time_based() to convert
        time boundaries to frame-indexed execution specification.
        """
        # Default fps for Phase 2 (no fps in config, use 30)
        fps = Fraction(30, 1)
        entry, entry_start = self._find_entry_at(channel_id, block_start)

        if entry is None:
            # Unscheduled slot: filler for entire slot
            return [
                PlayoutSegment.from_time_based(
                    start_utc=block_start,
                    end_utc=block_end,
                    file_path=self._config.filler_path,
                    fps=fps,
                    seek_offset_seconds=0.0,
                    segment_type="filler",
                )
            ]

        # Calculate where entry ends
        entry_end = entry_start + timedelta(seconds=entry.duration_seconds)

        # Entry segment: from block_start to min(entry_end, block_end)
        segment_end = min(entry_end, block_end)

        # Calculate seek offset: how far into the entry this block starts
        seek_offset = (block_start - entry_start).total_seconds()

        segments = [
            PlayoutSegment.from_time_based(
                start_utc=block_start,
                end_utc=segment_end,
                file_path=entry.file_path,
                fps=fps,
                seek_offset_seconds=seek_offset,
                segment_type="content",
            )
        ]

        # If entry ends before block ends, add filler
        if entry_end < block_end:
            segments.append(
                PlayoutSegment.from_time_based(
                    start_utc=entry_end,
                    end_utc=block_end,
                    file_path=self._config.filler_path,
                    fps=fps,
                    seek_offset_seconds=0.0,
                    segment_type="filler",
                )
            )

        return segments


class Phase3ScheduleManager:
    """
    Phase 3 ScheduleManager implementation.

    Generates ProgramBlocks based on resolved schedules with dynamic content
    selection. Implements the two-pass architecture:

    1. Editorial Resolution Pass: Resolves Programs to specific episodes,
       producing ResolvedScheduleDay with immutable EPG identities.

    2. Structural Expansion Pass: Generates PlayoutSegments from resolved
       schedules with seek offsets and filler segments.

    Key invariants:
    - INV-P3-001: Episode Selection Determinism
    - INV-P3-002: EPG Identity Immutability
    - INV-P3-004: Sequential State Isolation
    - INV-P3-008: Resolution Idempotence
    - INV-P3-009: Content Duration Supremacy
    - INV-P3-010: Playout Is a Pure Projection
    """

    def __init__(self, config: Phase3Config):
        self._config = config

    # =========================================================================
    # ScheduleManager Protocol (unchanged from Phase 2)
    # =========================================================================

    def get_program_at(self, channel_id: str, at_time: datetime) -> ProgramBlock:
        """
        Get the program block containing the specified time.

        Returns ProgramBlock where: block_start <= at_time < block_end

        This is the Structural Expansion Pass - it uses already-resolved
        EPG data to produce playout instructions.
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

    # =========================================================================
    # EPGProvider Protocol
    # =========================================================================

    def get_epg_events(
        self,
        channel_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> list[EPGEvent]:
        """
        Get EPG events for the specified time range.

        Returns resolved events with episode information.
        Events are immutable once returned.

        INV-P3-003: Resolution Independence - EPG exists even with no viewers.
        """
        events = []

        # Normalize times for comparison (strip timezone if needed)
        start_naive = start_time.replace(tzinfo=None) if start_time.tzinfo else start_time
        end_naive = end_time.replace(tzinfo=None) if end_time.tzinfo else end_time
        has_tz = start_time.tzinfo is not None

        # Determine programming days in range
        current = start_time
        while current < end_time:
            day_date = self._get_programming_day_date(current)
            resolved = self._config.resolved_store.get(channel_id, day_date)

            if resolved:
                for slot in resolved.resolved_slots:
                    slot_start = self._slot_to_datetime(day_date, slot.slot_time)
                    # INV-P4-001: EPG uses grid-aligned duration (minimum blocks)
                    # slot.duration_seconds was computed during resolution as
                    # ceil(content_duration / grid) * grid
                    slot_end = slot_start + timedelta(seconds=slot.duration_seconds)

                    if slot_start < end_naive and slot_end > start_naive:
                        # Add timezone back if original times had one
                        if has_tz:
                            slot_start = slot_start.replace(tzinfo=start_time.tzinfo)
                            slot_end = slot_end.replace(tzinfo=start_time.tzinfo)

                        events.append(EPGEvent(
                            channel_id=channel_id,
                            start_time=slot_start,
                            end_time=slot_end,
                            title=slot.resolved_asset.title,
                            episode_title=slot.resolved_asset.episode_title,
                            episode_id=slot.resolved_asset.episode_id,
                            resolved_asset=slot.resolved_asset,
                            programming_day_date=day_date,
                        ))

            current += timedelta(days=1)

        return events

    # =========================================================================
    # Editorial Resolution Pass
    # =========================================================================

    def resolve_schedule_day(
        self,
        channel_id: str,
        programming_day_date: date,
        slots: list[ScheduleSlot],
        resolution_time: datetime,
    ) -> ResolvedScheduleDay:
        """
        Resolve a schedule day to specific episodes/assets.

        This is the Editorial Resolution Pass. All content decisions
        are made here. Once resolved, the EPG identity is immutable.

        INV-P3-008: Resolution Idempotence - if already resolved, return cached.
        INV-P3-002: EPG Identity Immutability - resolved content cannot change.
        """
        # Check if already resolved (idempotence)
        existing = self._config.resolved_store.get(channel_id, programming_day_date)
        if existing is not None:
            return existing

        # Resolve each slot
        resolved_slots = []
        grid_seconds = self._config.grid_minutes * 60

        for slot in slots:
            resolved_asset = self._resolve_program_ref(
                channel_id, slot.program_ref, programming_day_date, slot.slot_time
            )

            # INV-P4-001: Minimum Grid Occupancy
            # Compute exactly ceil(content_duration / grid) blocks
            content_duration = resolved_asset.content_duration_seconds
            if content_duration > 0:
                blocks_required = math.ceil(content_duration / grid_seconds)
                actual_duration = blocks_required * grid_seconds
            else:
                # Fallback to slot duration if content duration unknown
                actual_duration = slot.duration_seconds

            resolved_slots.append(ResolvedSlot(
                slot_time=slot.slot_time,
                program_ref=slot.program_ref,
                resolved_asset=resolved_asset,
                duration_seconds=actual_duration,
                label=slot.label,
            ))

        # Capture sequence state snapshot
        sequence_state = SequenceState(
            positions=self._capture_sequence_positions(channel_id),
            as_of=resolution_time,
        )

        resolved = ResolvedScheduleDay(
            programming_day_date=programming_day_date,
            resolved_slots=resolved_slots,
            resolution_timestamp=resolution_time,
            sequence_state=sequence_state,
        )

        # Store for idempotence (INV-P3-008)
        self._config.resolved_store.store(channel_id, resolved)

        return resolved

    def _resolve_program_ref(
        self,
        channel_id: str,
        ref: ProgramRef,
        programming_day_date: date,
        slot_time: time,
    ) -> ResolvedAsset:
        """
        Resolve a ProgramRef to a specific asset.

        This is where episode selection happens based on play_mode.
        """
        if ref.ref_type == ProgramRefType.FILE:
            # Phase 2 compatibility: direct file path
            return ResolvedAsset(
                file_path=ref.ref_id,
                title=ref.ref_id,
                content_duration_seconds=0.0,
            )

        if ref.ref_type == ProgramRefType.ASSET:
            # Direct asset reference (manual mode equivalent)
            return ResolvedAsset(
                file_path=f"/media/assets/{ref.ref_id}.mp4",
                asset_id=ref.ref_id,
                title=ref.ref_id,
                content_duration_seconds=0.0,
            )

        if ref.ref_type == ProgramRefType.PROGRAM:
            program = self._config.program_catalog.get_program(ref.ref_id)
            if program is None:
                # Missing program: return filler
                return ResolvedAsset(
                    file_path=self._config.filler_path,
                    title="Unknown Program",
                    content_duration_seconds=0.0,
                )

            episode = self._select_episode(
                channel_id, program, programming_day_date, slot_time
            )

            return ResolvedAsset(
                file_path=episode.file_path,
                asset_id=episode.episode_id,
                title=program.name,
                episode_title=episode.title,
                episode_id=episode.episode_id,
                content_duration_seconds=episode.duration_seconds,
            )

        raise ScheduleError(f"Unknown ProgramRefType: {ref.ref_type}")

    def _select_episode(
        self,
        channel_id: str,
        program: Program,
        programming_day_date: date,
        slot_time: time,
    ) -> Episode:
        """
        Select an episode based on play_mode.

        INV-P3-001: Episode Selection Determinism - same inputs → same result.
        INV-P3-004: State advances only at resolution time.
        """
        if not program.episodes:
            raise ScheduleError(f"Program {program.program_id} has no episodes")

        if program.play_mode == "sequential":
            # Get current position and advance
            current_index = self._config.sequence_store.get_position(
                channel_id, program.program_id
            )
            episode = program.episodes[current_index % len(program.episodes)]

            # Advance for next time (INV-P3-004: only at resolution time)
            next_index = (current_index + 1) % len(program.episodes)
            self._config.sequence_store.set_position(
                channel_id, program.program_id, next_index
            )

            return episode

        if program.play_mode == "random":
            # INV-P3-001: Deterministic random selection
            index = self._deterministic_random_select(
                channel_id,
                program.program_id,
                programming_day_date,
                slot_time,
                len(program.episodes),
            )
            return program.episodes[index]

        if program.play_mode == "manual":
            # Manual mode: first episode (in production, operator selects)
            return program.episodes[0]

        raise ScheduleError(f"Unknown play_mode: {program.play_mode}")

    def _deterministic_random_select(
        self,
        channel_id: str,
        program_id: str,
        programming_day_date: date,
        slot_time: time,
        episode_count: int,
    ) -> int:
        """
        Deterministic episode selection for random mode.

        INV-P3-001: Same inputs always produce same selection.
        """
        seed_string = f"{channel_id}:{program_id}:{programming_day_date}:{slot_time}"
        hash_bytes = hashlib.sha256(seed_string.encode()).digest()
        hash_int = int.from_bytes(hash_bytes[:8], byteorder='big')
        return hash_int % episode_count

    def _capture_sequence_positions(self, channel_id: str) -> dict[str, int]:
        """Capture current sequence positions for all programs."""
        # In production, this would query all sequential programs
        # For now, return empty dict (positions are stored incrementally)
        return {}

    # =========================================================================
    # Structural Expansion Pass (Traffic Logic)
    # =========================================================================

    def _build_segments(
        self, channel_id: str, block_start: datetime, block_end: datetime
    ) -> list[PlayoutSegment]:
        """
        Build the segment list for a program block.

        This is the Structural Expansion Pass - uses already-resolved
        EPG data to produce playout instructions.

        INV-P3-010: Playout Is a Pure Projection - this is derivable from EPG.
        INV-FRAME-001: Uses PlayoutSegment.from_time_based() to convert
        time boundaries to frame-indexed execution specification.
        """
        # Default fps for Phase 3 (no fps in config, use 30)
        fps = Fraction(30, 1)
        slot, slot_start = self._find_resolved_slot_at(channel_id, block_start)

        if slot is None:
            # Unscheduled slot: filler for entire slot
            return [
                PlayoutSegment.from_time_based(
                    start_utc=block_start,
                    end_utc=block_end,
                    file_path=self._config.filler_path,
                    fps=fps,
                    seek_offset_seconds=0.0,
                    segment_type="filler",
                )
            ]

        # INV-P3-009: Content Duration Supremacy
        content_duration = (
            slot.resolved_asset.content_duration_seconds
            or slot.duration_seconds
        )
        slot_end = slot_start + timedelta(seconds=content_duration)

        # Segment: from block_start to min(slot_end, block_end)
        segment_end = min(slot_end, block_end)

        # Calculate seek offset: how far into the content this block starts
        seek_offset = (block_start - slot_start).total_seconds()

        segments = [
            PlayoutSegment.from_time_based(
                start_utc=block_start,
                end_utc=segment_end,
                file_path=slot.resolved_asset.file_path,
                fps=fps,
                seek_offset_seconds=seek_offset,
                segment_type="content",
            )
        ]

        # If content ends before block ends, add filler
        if slot_end < block_end:
            segments.append(
                PlayoutSegment.from_time_based(
                    start_utc=slot_end,
                    end_utc=block_end,
                    file_path=self._config.filler_path,
                    fps=fps,
                    seek_offset_seconds=0.0,
                    segment_type="filler",
                )
            )

        return segments

    def _find_resolved_slot_at(
        self, channel_id: str, block_start: datetime
    ) -> tuple[ResolvedSlot | None, datetime | None]:
        """
        Find the resolved slot (if any) that covers the given grid slot.

        Checks both current and previous programming days for cross-day content.
        """
        current_day_start = self._get_programming_day_start(block_start)
        previous_day_start = current_day_start - timedelta(days=1)

        day_start_hour_seconds = self._config.programming_day_start_hour * 3600

        # Normalize block_start for comparison (strip timezone if needed)
        block_start_naive = block_start.replace(tzinfo=None) if block_start.tzinfo else block_start

        # Check both current and previous programming days
        for day_start in [current_day_start, previous_day_start]:
            programming_day_date = day_start.date()
            resolved_day = self._config.resolved_store.get(
                channel_id, programming_day_date
            )

            if resolved_day is None:
                continue

            for slot in resolved_day.resolved_slots:
                slot_start = self._slot_to_datetime(programming_day_date, slot.slot_time)

                # INV-P4-001: Use grid-aligned duration for slot coverage
                # slot.duration_seconds = ceil(content_duration / grid) * grid
                slot_end = slot_start + timedelta(seconds=slot.duration_seconds)

                # Check if block_start falls within slot's time window
                if slot_start <= block_start_naive < slot_end:
                    # Return slot_start with original timezone if block_start had one
                    if block_start.tzinfo:
                        slot_start = slot_start.replace(tzinfo=block_start.tzinfo)
                    return (slot, slot_start)

        return (None, None)

    # =========================================================================
    # Grid and Time Utilities
    # =========================================================================

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

    def _get_programming_day_date(self, t: datetime) -> date:
        """Get the programming day date for a given time."""
        if t.hour < self._config.programming_day_start_hour:
            return (t - timedelta(days=1)).date()
        return t.date()

    def _slot_to_datetime(self, programming_day_date: date, slot_time: time) -> datetime:
        """Convert a slot time to absolute datetime (naive, for backward compat)."""
        base = datetime.combine(programming_day_date, slot_time)
        if slot_time.hour < self._config.programming_day_start_hour:
            base += timedelta(days=1)
        return base
