"""
Schedule Manager Implementation

Production ScheduleManager as defined in:
    docs/contracts/runtime/ScheduleManagerPhase3Contract.md
"""

from datetime import datetime, date, time, timedelta, timezone
from fractions import Fraction
import hashlib
import math

from retrovue.runtime.schedule_types import (
    PlayoutSegment,
    ProgramBlock,
    ScheduleError,
    # Phase 3 types
    ProgramRefType,
    ProgramRef,
    ProgramEvent,
    ScheduleSlot,
    Episode,
    Program,
    ResolvedAsset,
    ResolvedSlot,
    SequenceState,
    ResolvedScheduleDay,
    EPGEvent,
    ScheduleManagerConfig,
)


class ScheduleManager:
    """
    Production ScheduleManager implementation.

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

    def __init__(self, config: ScheduleManagerConfig):
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
        grid_seconds = self._config.grid_minutes * 60

        # Normalize times for comparison (strip timezone if needed)
        start_naive = start_time.replace(tzinfo=None) if start_time.tzinfo else start_time
        end_naive = end_time.replace(tzinfo=None) if end_time.tzinfo else end_time
        has_tz = start_time.tzinfo is not None

        # Determine programming days in range
        current = start_time
        while current < end_time:
            day_date = self._get_programming_day_date(current)
            resolved = self._config.resolved_store.get(channel_id, day_date)

            if resolved and resolved.program_events:
                slot_idx = 0
                for pe in resolved.program_events:
                    first_slot = resolved.resolved_slots[slot_idx]
                    event_start = self._slot_to_datetime(day_date, first_slot.slot_time)
                    event_end = event_start + timedelta(
                        seconds=pe.block_span_count * grid_seconds
                    )

                    if event_start < end_naive and event_end > start_naive:
                        if has_tz:
                            event_start = event_start.replace(tzinfo=start_time.tzinfo)
                            event_end = event_end.replace(tzinfo=start_time.tzinfo)

                        resolved_asset = pe.resolved_asset or first_slot.resolved_asset
                        events.append(EPGEvent(
                            channel_id=channel_id,
                            start_time=event_start,
                            end_time=event_end,
                            title=resolved_asset.title,
                            episode_title=resolved_asset.episode_title,
                            episode_id=resolved_asset.episode_id,
                            resolved_asset=resolved_asset,
                            programming_day_date=day_date,
                        ))

                    slot_idx += pe.block_span_count
            elif resolved:
                # Legacy fallback for days without program_events
                for slot in resolved.resolved_slots:
                    slot_start = self._slot_to_datetime(day_date, slot.slot_time)
                    slot_end = slot_start + timedelta(seconds=slot.duration_seconds)

                    if slot_start < end_naive and slot_end > start_naive:
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

        Episode selection and cursor advancement happen once per ProgramEvent,
        not once per grid block. A 90-minute movie spanning 3 blocks selects
        one episode and advances the cursor once.

        INV-P3-008: Resolution Idempotence - if already resolved, return cached.
        INV-P3-002: EPG Identity Immutability - resolved content cannot change.
        """
        # Check if already resolved (idempotence)
        existing = self._config.resolved_store.get(channel_id, programming_day_date)
        if existing is not None:
            return existing

        resolved_slots = []
        program_events = []
        grid_seconds = self._config.grid_minutes * 60

        slot_idx = 0
        while slot_idx < len(slots):
            slot = slots[slot_idx]

            # Resolve content once per ProgramEvent (not per block)
            resolved_asset = self._resolve_program_ref(
                channel_id, slot.program_ref, programming_day_date, slot.slot_time
            )

            # Derive block span from content duration
            content_duration = resolved_asset.content_duration_seconds
            if content_duration > 0:
                block_span = math.ceil(content_duration / grid_seconds)
            else:
                block_span = 1
            grid_occupancy_seconds = block_span * grid_seconds

            # Create ProgramEvent
            slot_start_dt = self._slot_to_datetime(
                programming_day_date, slot.slot_time
            )
            utc_dt = slot_start_dt.replace(tzinfo=timezone.utc)
            start_utc_ms = int(utc_dt.timestamp() * 1000)
            event_id = (
                f"{channel_id}-{programming_day_date.isoformat()}-evt{slot_idx:04d}"
            )
            program_events.append(ProgramEvent(
                id=event_id,
                program_id=slot.program_ref.ref_id,
                episode_id=resolved_asset.episode_id or "",
                start_utc_ms=start_utc_ms,
                duration_ms=int(content_duration * 1000),
                block_span_count=block_span,
                resolved_asset=resolved_asset,
            ))

            # ResolvedSlots carry per-block asset details for Stage 3+.
            consumed = min(block_span, len(slots) - slot_idx)
            for block_offset in range(consumed):
                s = slots[slot_idx + block_offset]
                resolved_slots.append(ResolvedSlot(
                    slot_time=s.slot_time,
                    program_ref=slot.program_ref,
                    resolved_asset=resolved_asset,
                    duration_seconds=grid_occupancy_seconds,
                    label=slot.label,
                ))

            slot_idx += consumed

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
            program_events=program_events,
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
