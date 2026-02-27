"""
Schedule Manager Service

Adapter that bridges ScheduleManager to the runtime ScheduleService protocol.
Enables production runtime to use dynamic content selection.

Implements:
- INV-P5-001: Config-Driven Activation - schedule_source: "phase3" enables this service
- INV-P5-003: Playout Plan Transformation - ProgramBlock → list[dict] correctly
- INV-P5-004: EPG Endpoint Independence - EPG works without active viewers
- INV-P5-005: Horizon Authority Guard - auto-resolve is prohibited; missing data
  is a planning failure logged as POLICY_VIOLATION.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from retrovue.runtime.clock import MasterClock
from retrovue.runtime.execution_window_store import ExecutionWindowStore
from retrovue.runtime.horizon_config import HorizonNoScheduleDataError
from retrovue.runtime.schedule_manager import ScheduleManager
from retrovue.runtime.schedule_types import (
    Episode,
    ScheduleManagerConfig,
    Program,
    ProgramCatalog,
    ProgramRef,
    ProgramRefType,
    ResolvedScheduleDay,
    ResolvedScheduleStore,
    ScheduledBlock,
    ScheduledSegment,
    ScheduleSlot,
    SequenceStateStore,
)


# ----------------------------------------------------------------------
# In-Memory Store Implementations
# ----------------------------------------------------------------------


class InMemorySequenceStore(SequenceStateStore):
    """
    In-memory implementation of SequenceStateStore.

    Stores sequential program positions. Positions are reset on process restart.
    For production, use a persistent store (e.g., Redis or Postgres).
    """

    def __init__(self) -> None:
        self._positions: dict[str, dict[str, int]] = {}  # channel_id -> {program_id -> index}
        self._lock = threading.Lock()

    def get_position(self, channel_id: str, program_id: str) -> int:
        """Get current episode index for a sequential program."""
        with self._lock:
            channel_positions = self._positions.get(channel_id, {})
            return channel_positions.get(program_id, 0)

    def set_position(self, channel_id: str, program_id: str, index: int) -> None:
        """Set episode index for a sequential program."""
        with self._lock:
            if channel_id not in self._positions:
                self._positions[channel_id] = {}
            self._positions[channel_id][program_id] = index


def validate_scheduleday_contiguity(
    resolved: ResolvedScheduleDay,
    programming_day_start_hour: int,
    effective_start: datetime | None = None,
) -> None:
    """Validate that resolved slots tile the full broadcast day with no gaps or overlaps.

    INV-SCHEDULEDAY-NO-GAPS-001: A materialized ScheduleDay must provide
    continuous, gap-free coverage from programming_day_start to
    programming_day_start + 24h.

    Args:
        resolved: The ResolvedScheduleDay to validate.
        programming_day_start_hour: Broadcast day start hour.
        effective_start: If set, overrides broadcast_start for first-slot
            validation. Used when a preceding day's carry-in pushes the
            effective start of coverage past the nominal boundary.

    Raises:
        ValueError: If any gap or overlap is detected, with
            INV-SCHEDULEDAY-NO-GAPS-001-VIOLATED tag.
    """
    day = resolved.programming_day_date
    pds_time = time(programming_day_start_hour, 0)
    broadcast_start = datetime.combine(day, pds_time, tzinfo=timezone.utc)
    broadcast_end = broadcast_start + timedelta(hours=24)
    actual_start = effective_start if effective_start is not None else broadcast_start

    if not resolved.resolved_slots:
        raise ValueError(
            "INV-SCHEDULEDAY-NO-GAPS-001-VIOLATED: "
            f"ResolvedScheduleDay for {day!r} has no slots. "
            f"Broadcast day [{broadcast_start}→{broadcast_end}] is entirely uncovered."
        )

    # Compute absolute (start, end) for each slot.
    def _slot_start(slot):
        base = datetime.combine(day, slot.slot_time, tzinfo=timezone.utc)
        if slot.slot_time.hour < programming_day_start_hour:
            base += timedelta(days=1)
        return base

    intervals = []
    for slot in resolved.resolved_slots:
        start = _slot_start(slot)
        end = start + timedelta(seconds=slot.duration_seconds)
        intervals.append((start, end, slot))

    # Sort by start time.
    intervals.sort(key=lambda x: x[0])

    # Check first slot starts at expected start (broadcast_start or carry-in end).
    first_start = intervals[0][0]
    if first_start != actual_start:
        raise ValueError(
            "INV-SCHEDULEDAY-NO-GAPS-001-VIOLATED: "
            f"First slot starts at {first_start}, but broadcast day "
            f"starts at {actual_start}. "
            f"Gap: [{actual_start}→{first_start}]."
        )

    # Check contiguity: each slot's end must equal next slot's start.
    for i in range(len(intervals) - 1):
        current_end = intervals[i][1]
        next_start = intervals[i + 1][0]
        if current_end < next_start:
            raise ValueError(
                "INV-SCHEDULEDAY-NO-GAPS-001-VIOLATED: "
                f"Gap between slot '{intervals[i][2].label}' ending at "
                f"{current_end} and slot '{intervals[i + 1][2].label}' "
                f"starting at {next_start}. "
                f"Gap: [{current_end}→{next_start}]."
            )
        if current_end > next_start:
            raise ValueError(
                "INV-SCHEDULEDAY-NO-GAPS-001-VIOLATED: "
                f"Overlap between slot '{intervals[i][2].label}' ending at "
                f"{current_end} and slot '{intervals[i + 1][2].label}' "
                f"starting at {next_start}. "
                f"Overlap: [{next_start}→{current_end}]."
            )

    # Check last slot covers the broadcast day end.
    # last_end >= broadcast_end is valid (carry-in past boundary is allowed).
    # last_end < broadcast_end is a gap at the end of the broadcast day.
    last_end = intervals[-1][1]
    if last_end < broadcast_end:
        raise ValueError(
            "INV-SCHEDULEDAY-NO-GAPS-001-VIOLATED: "
            f"Last slot ends at {last_end}, but broadcast day "
            f"ends at {broadcast_end}. "
            f"Gap: [{last_end}→{broadcast_end}]."
        )


def check_scheduleday_lead_time(
    resolved_store: ResolvedScheduleStore,
    channel_id: str,
    target_date: date,
    now_utc: datetime,
    min_lead_days: int,
    programming_day_start_hour: int = 6,
) -> None:
    """Check that a ScheduleDay exists with sufficient lead time.

    INV-SCHEDULEDAY-LEAD-TIME-001: A ScheduleDay for broadcast date D must
    be materialized no later than D - min_lead_days calendar days.

    Args:
        resolved_store: The store to check for materialized ScheduleDays.
        channel_id: The channel to check.
        target_date: The broadcast date D to verify.
        now_utc: Current UTC time (from clock).
        min_lead_days: Minimum lead time in calendar days (injected, not hardcoded).
        programming_day_start_hour: Broadcast day start hour.

    Raises:
        ValueError: If the deadline has passed and no ScheduleDay exists,
            with INV-SCHEDULEDAY-LEAD-TIME-001-VIOLATED tag.
    """
    deadline = datetime.combine(
        target_date - timedelta(days=min_lead_days),
        time(programming_day_start_hour, 0),
        tzinfo=timezone.utc,
    )

    if now_utc <= deadline:
        # Deadline has not passed yet; no violation.
        return

    if resolved_store.exists(channel_id, target_date):
        # ScheduleDay exists; lead time satisfied.
        return

    raise ValueError(
        "INV-SCHEDULEDAY-LEAD-TIME-001-VIOLATED: "
        f"No ScheduleDay exists for channel_id={channel_id!r}, "
        f"target_date={target_date!r}. "
        f"Deadline was {deadline.isoformat()} "
        f"(min_schedule_day_lead_days={min_lead_days}). "
        f"Current time is {now_utc.isoformat()}, which is past the deadline."
    )


def _enforce_derivation_traceability(resolved: ResolvedScheduleDay) -> None:
    """Enforce INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001.

    A ResolvedScheduleDay must satisfy one of:
    1. plan_id is set (generated from a SchedulePlan), or
    2. is_manual_override is True (operator override).

    Raises:
        ValueError: If neither condition is met.
    """
    if not resolved.is_manual_override and resolved.plan_id is None:
        raise ValueError(
            "INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001-VIOLATED: "
            f"ResolvedScheduleDay for "
            f"programming_day_date={resolved.programming_day_date!r} "
            "has plan_id=None and is_manual_override=False. "
            "Every ScheduleDay must trace to a generating SchedulePlan "
            "or be an explicit operator override."
        )


def validate_scheduleday_seam(
    new_day: ResolvedScheduleDay,
    preceding_day: ResolvedScheduleDay | None,
    programming_day_start_hour: int,
) -> None:
    """Validate that the seam between consecutive ScheduleDays has no overlap.

    INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001: If the preceding day's last slot
    extends past the broadcast-day boundary, the new day's first slot MUST
    NOT start before that carry-in slot's end.

    Args:
        new_day: The ResolvedScheduleDay being stored.
        preceding_day: The preceding day's ResolvedScheduleDay, or None.
        programming_day_start_hour: Broadcast day start hour (e.g. 6).

    Raises:
        ValueError: If carry-in overlap is detected.
    """
    if preceding_day is None:
        return
    if not preceding_day.resolved_slots:
        return
    if not new_day.resolved_slots:
        return

    pds_time = time(programming_day_start_hour, 0)
    boundary = datetime.combine(
        new_day.programming_day_date, pds_time, tzinfo=timezone.utc
    )

    # Compute absolute end of preceding day's last slot.
    prev_slots = sorted(
        preceding_day.resolved_slots,
        key=lambda s: (s.slot_time.hour, s.slot_time.minute),
    )

    def _slot_abs_end(slot, day_date):
        base = datetime.combine(day_date, slot.slot_time, tzinfo=timezone.utc)
        if slot.slot_time < pds_time:
            base += timedelta(days=1)
        return base + timedelta(seconds=slot.duration_seconds)

    last_slot = prev_slots[-1]
    carry_in_end = _slot_abs_end(last_slot, preceding_day.programming_day_date)

    # If the preceding day ends at or before the boundary, no carry-in.
    if carry_in_end <= boundary:
        return

    # Carry-in exists. Check new day's first slot.
    new_slots = sorted(
        new_day.resolved_slots,
        key=lambda s: (s.slot_time.hour, s.slot_time.minute),
    )
    first_slot = new_slots[0]
    first_slot_start = datetime.combine(
        new_day.programming_day_date, first_slot.slot_time, tzinfo=timezone.utc
    )
    if first_slot.slot_time < pds_time:
        first_slot_start += timedelta(days=1)

    if first_slot_start < carry_in_end:
        raise ValueError(
            "INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001-VIOLATED: "
            f"Preceding day ({preceding_day.programming_day_date}) last slot "
            f"carries in until {carry_in_end.isoformat()}, but new day "
            f"({new_day.programming_day_date}) first slot starts at "
            f"{first_slot_start.isoformat()}. "
            f"Overlap: [{first_slot_start.isoformat()}→{carry_in_end.isoformat()}]."
        )


def _compute_effective_start(
    preceding_day: ResolvedScheduleDay | None,
    new_day_date: date,
    programming_day_start_hour: int,
) -> datetime | None:
    """Compute the effective start time for a new day considering carry-in.

    If the preceding day's last slot carries past the broadcast-day boundary,
    the effective start is the carry-in end. Otherwise returns None (use
    default broadcast_start).
    """
    if preceding_day is None or not preceding_day.resolved_slots:
        return None

    pds_time = time(programming_day_start_hour, 0)
    boundary = datetime.combine(new_day_date, pds_time, tzinfo=timezone.utc)

    prev_slots = sorted(
        preceding_day.resolved_slots,
        key=lambda s: (s.slot_time.hour, s.slot_time.minute),
    )
    last_slot = prev_slots[-1]
    base = datetime.combine(
        preceding_day.programming_day_date, last_slot.slot_time,
        tzinfo=timezone.utc,
    )
    if last_slot.slot_time < pds_time:
        base += timedelta(days=1)
    carry_in_end = base + timedelta(seconds=last_slot.duration_seconds)

    if carry_in_end > boundary:
        return carry_in_end
    return None


class InMemoryResolvedStore(ResolvedScheduleStore):
    """
    In-memory implementation of ResolvedScheduleStore.

    Stores resolved schedule days. Lost on process restart.
    For production, use a persistent store.

    When constructed with an ``execution_store``, delete() enforces
    INV-DERIVATION-ANCHOR-PROTECTED-001: a ScheduleDay that has
    downstream ExecutionEntries may not be removed.
    """

    def __init__(
        self,
        execution_store: ExecutionWindowStore | None = None,
        programming_day_start_hour: int | None = None,
        enforce_derivation_traceability: bool = False,
    ) -> None:
        self._resolved: dict[str, dict[date, ResolvedScheduleDay]] = {}
        self._execution_store = execution_store
        self._programming_day_start_hour = programming_day_start_hour
        self._enforce_derivation_traceability = enforce_derivation_traceability
        self._lock = threading.Lock()

    def get(self, channel_id: str, programming_day_date: date) -> ResolvedScheduleDay | None:
        """Get a resolved schedule day, or None if not yet resolved."""
        with self._lock:
            channel_days = self._resolved.get(channel_id, {})
            return channel_days.get(programming_day_date)

    def store(self, channel_id: str, resolved: ResolvedScheduleDay) -> None:
        """Store a resolved schedule day.

        INV-SCHEDULEDAY-ONE-PER-DATE-001: If a record already exists for
        (channel_id, programming_day_date), the insert is rejected.
        Use force_replace() for atomic regeneration.

        Raises:
            ValueError: If a ScheduleDay already exists for this (channel, date),
                or if slot contiguity validation fails.
        """
        if self._enforce_derivation_traceability:
            _enforce_derivation_traceability(resolved)
        with self._lock:
            if channel_id not in self._resolved:
                self._resolved[channel_id] = {}
            if resolved.programming_day_date in self._resolved[channel_id]:
                raise ValueError(
                    "INV-SCHEDULEDAY-ONE-PER-DATE-001-VIOLATED: "
                    f"ResolvedScheduleDay already exists for "
                    f"channel_id={channel_id!r}, "
                    f"programming_day_date={resolved.programming_day_date!r}. "
                    "Duplicate insertion is forbidden. "
                    "Use force_replace() for atomic regeneration."
                )
            if self._programming_day_start_hour is not None:
                prev_date = resolved.programming_day_date - timedelta(days=1)
                preceding = self._resolved.get(channel_id, {}).get(prev_date)
                validate_scheduleday_seam(
                    resolved, preceding, self._programming_day_start_hour
                )
                effective_start = _compute_effective_start(
                    preceding, resolved.programming_day_date,
                    self._programming_day_start_hour,
                )
                validate_scheduleday_contiguity(
                    resolved, self._programming_day_start_hour,
                    effective_start=effective_start,
                )
            self._resolved[channel_id][resolved.programming_day_date] = resolved

    def force_replace(self, channel_id: str, resolved: ResolvedScheduleDay) -> None:
        """Atomically replace an existing ResolvedScheduleDay.

        INV-SCHEDULEDAY-ONE-PER-DATE-001: Replacement is atomic — the old
        record is removed and the new record is installed in a single
        critical section. At no point are zero records visible.

        Raises:
            ValueError: If no existing record to replace, or if slot
                contiguity validation fails.
        """
        if self._enforce_derivation_traceability:
            _enforce_derivation_traceability(resolved)
        with self._lock:
            channel_days = self._resolved.get(channel_id, {})
            if resolved.programming_day_date not in channel_days:
                raise ValueError(
                    f"force_replace(): No existing ResolvedScheduleDay for "
                    f"channel_id={channel_id!r}, "
                    f"programming_day_date={resolved.programming_day_date!r}. "
                    "Nothing to replace."
                )
            if self._programming_day_start_hour is not None:
                prev_date = resolved.programming_day_date - timedelta(days=1)
                preceding = channel_days.get(prev_date)
                validate_scheduleday_seam(
                    resolved, preceding, self._programming_day_start_hour
                )
                effective_start = _compute_effective_start(
                    preceding, resolved.programming_day_date,
                    self._programming_day_start_hour,
                )
                validate_scheduleday_contiguity(
                    resolved, self._programming_day_start_hour,
                    effective_start=effective_start,
                )
            channel_days[resolved.programming_day_date] = resolved

    def exists(self, channel_id: str, programming_day_date: date) -> bool:
        """Check if a day has already been resolved."""
        with self._lock:
            channel_days = self._resolved.get(channel_id, {})
            return programming_day_date in channel_days

    def delete(self, channel_id: str, programming_day_date: date) -> None:
        """Remove a resolved schedule day.

        INV-DERIVATION-ANCHOR-PROTECTED-001: If an ExecutionWindowStore
        is configured and contains entries derived from this
        (channel_id, programming_day_date), deletion is refused.
        Removing a schedule anchor while execution artifacts still
        reference it severs the constitutional derivation chain.

        Raises:
            ValueError: If downstream execution artifacts exist.
        """
        if self._execution_store is not None:
            if self._execution_store.has_entries_for(channel_id, programming_day_date):
                raise ValueError(
                    "INV-DERIVATION-ANCHOR-PROTECTED-001-VIOLATED: "
                    f"Cannot delete ResolvedScheduleDay for "
                    f"channel_id={channel_id!r}, "
                    f"programming_day_date={programming_day_date!r}. "
                    "Downstream ExecutionEntries still reference this "
                    "schedule anchor. Removing it would sever the "
                    "constitutional derivation chain."
                )
        with self._lock:
            channel_days = self._resolved.get(channel_id, {})
            channel_days.pop(programming_day_date, None)

    def update(
        self, channel_id: str, programming_day_date: date, fields: dict
    ) -> None:
        """INV-SCHEDULEDAY-IMMUTABLE-001: In-place mutation is unconditionally
        prohibited. This method always raises.

        Use force_replace() for atomic regeneration or operator_override()
        for operator-initiated changes.

        Raises:
            ValueError: Always — in-place mutation is forbidden.
        """
        raise ValueError(
            "INV-SCHEDULEDAY-IMMUTABLE-001-VIOLATED: "
            f"In-place update of ResolvedScheduleDay for "
            f"channel_id={channel_id!r}, "
            f"programming_day_date={programming_day_date!r} "
            f"is unconditionally prohibited. "
            f"Attempted to modify fields: {sorted(fields.keys())}. "
            "Use force_replace() for atomic regeneration or "
            "operator_override() for operator-initiated changes."
        )

    def operator_override(
        self, channel_id: str, resolved: ResolvedScheduleDay
    ) -> ResolvedScheduleDay:
        """Create an operator override for an existing ResolvedScheduleDay.

        INV-SCHEDULEDAY-IMMUTABLE-001: The original record is never mutated.
        A new record is created with is_manual_override=True and
        supersedes_id pointing to the original. The new record atomically
        replaces the original as the authoritative record.

        Raises:
            ValueError: If no existing record to override.

        Returns:
            The new override ResolvedScheduleDay.
        """
        with self._lock:
            channel_days = self._resolved.get(channel_id, {})
            original = channel_days.get(resolved.programming_day_date)
            if original is None:
                raise ValueError(
                    f"operator_override(): No existing ResolvedScheduleDay for "
                    f"channel_id={channel_id!r}, "
                    f"programming_day_date={resolved.programming_day_date!r}. "
                    "Nothing to override."
                )

            # Create override record with metadata linking to superseded.
            override = ResolvedScheduleDay(
                programming_day_date=resolved.programming_day_date,
                resolved_slots=resolved.resolved_slots,
                resolution_timestamp=resolved.resolution_timestamp,
                sequence_state=resolved.sequence_state,
                program_events=resolved.program_events,
                is_manual_override=True,
                supersedes_id=id(original),
            )

            # Atomic swap: original is replaced, not mutated.
            channel_days[resolved.programming_day_date] = override
            return override


# ----------------------------------------------------------------------
# JSON File Program Catalog
# ----------------------------------------------------------------------


class JsonFileProgramCatalog(ProgramCatalog):
    """
    ProgramCatalog implementation that loads programs from JSON files.

    Programs are loaded from a directory containing {program_id}.json files.
    Each file contains program metadata and episode list with durations.
    """

    def __init__(self, programs_dir: Path) -> None:
        self._programs_dir = programs_dir
        self._programs: dict[str, Program] = {}
        self._lock = threading.Lock()
        self._logger = logging.getLogger(__name__)

    def get_program(self, program_id: str) -> Program | None:
        """Get a Program by ID, loading from file if not cached."""
        with self._lock:
            if program_id in self._programs:
                return self._programs[program_id]

        # Try to load from file
        program = self._load_program(program_id)
        if program:
            with self._lock:
                self._programs[program_id] = program
        return program

    def _load_program(self, program_id: str) -> Program | None:
        """Load program from JSON file."""
        program_file = self._programs_dir / f"{program_id}.json"
        if not program_file.exists():
            self._logger.warning("Program file not found: %s", program_file)
            return None

        try:
            with open(program_file, "r") as f:
                data = json.load(f)

            episodes = [
                Episode(
                    episode_id=ep["episode_id"],
                    title=ep["title"],
                    file_path=ep["file_path"],
                    duration_seconds=ep["duration_seconds"],
                )
                for ep in data.get("episodes", [])
            ]

            return Program(
                program_id=data["program_id"],
                name=data["name"],
                play_mode=data.get("play_mode", "sequential"),
                episodes=episodes,
            )
        except (json.JSONDecodeError, KeyError) as e:
            self._logger.error("Failed to load program %s: %s", program_id, e)
            return None

    def load_all(self) -> None:
        """Pre-load all programs from the directory."""
        if not self._programs_dir.exists():
            return

        for program_file in self._programs_dir.glob("*.json"):
            program_id = program_file.stem
            self.get_program(program_id)


# ----------------------------------------------------------------------
# Schedule Manager Service
# ----------------------------------------------------------------------


@dataclass
class ScheduleSlotDefaults:
    """Configuration for ScheduleManagerBackedScheduleService."""

    grid_minutes: int = 30
    programming_day_start_hour: int = 6
    filler_path: str = ""
    filler_duration_seconds: float = 0.0


class ScheduleManagerBackedScheduleService:
    """
    Adapts ScheduleManager to the ScheduleService protocol.

    This service:
    1. Loads schedule slots from JSON files
    2. Loads programs from a catalog directory
    3. Delegates to ScheduleManager for resolution and playout
    4. Provides EPG events independently of viewers

    Implements INV-P5-001 through INV-P5-004.
    """

    def __init__(
        self,
        clock: MasterClock,
        programs_dir: Path,
        schedules_dir: Path,
        filler_path: str,
        filler_duration_seconds: float = 0.0,
        grid_minutes: int = 30,
        programming_day_start_hour: int = 6,
    ) -> None:
        self._clock = clock
        self._programs_dir = programs_dir
        self._schedules_dir = schedules_dir
        self._filler_path = filler_path
        self._filler_duration_seconds = filler_duration_seconds
        self._grid_minutes = grid_minutes
        self._programming_day_start_hour = programming_day_start_hour

        # Create stores
        self._sequence_store = InMemorySequenceStore()
        self._resolved_store = InMemoryResolvedStore()

        # Create program catalog
        self._program_catalog = JsonFileProgramCatalog(programs_dir)

        # Create ScheduleManager
        config = ScheduleManagerConfig(
            grid_minutes=grid_minutes,
            program_catalog=self._program_catalog,
            sequence_store=self._sequence_store,
            resolved_store=self._resolved_store,
            filler_path=filler_path,
            filler_duration_seconds=filler_duration_seconds,
            programming_day_start_hour=programming_day_start_hour,
        )
        self._manager = ScheduleManager(config)

        # Loaded channel schedules: channel_id -> list[ScheduleSlot]
        self._schedules: dict[str, list[ScheduleSlot]] = {}
        self._lock = threading.Lock()
        self._logger = logging.getLogger(__name__)

    def load_schedule(self, channel_id: str) -> tuple[bool, str | None]:
        """
        Load schedule slots from JSON file.

        Returns:
            (success, error_message) tuple
        """
        schedule_file = self._schedules_dir / f"{channel_id}.json"
        if not schedule_file.exists():
            return (False, f"Schedule file not found: {schedule_file}")

        try:
            with open(schedule_file, "r") as f:
                data = json.load(f)

            slots = []
            for slot_data in data.get("slots", []):
                slot_time_str = slot_data["slot_time"]
                # Parse HH:MM format
                parts = slot_time_str.split(":")
                hour = int(parts[0])
                minute = int(parts[1]) if len(parts) > 1 else 0

                # Parse program_ref
                ref_data = slot_data.get("program_ref", {})
                ref_type_str = ref_data.get("type", "file")
                if ref_type_str == "program":
                    ref_type = ProgramRefType.PROGRAM
                elif ref_type_str == "asset":
                    ref_type = ProgramRefType.ASSET
                else:
                    ref_type = ProgramRefType.FILE

                ref_id = ref_data.get("id", "")

                slots.append(
                    ScheduleSlot(
                        slot_time=time(hour=hour, minute=minute),
                        program_ref=ProgramRef(ref_type=ref_type, ref_id=ref_id),
                        duration_seconds=slot_data.get("duration_seconds", 1800),
                        label=slot_data.get("label", ""),
                    )
                )

            with self._lock:
                self._schedules[channel_id] = slots

            self._logger.info(
                "Loaded %d schedule slots for channel %s", len(slots), channel_id
            )
            return (True, None)

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            error_msg = f"Failed to load schedule for {channel_id}: {e}"
            self._logger.error(error_msg)
            return (False, error_msg)

    def get_schedule_slots(self, channel_id: str) -> list[ScheduleSlot]:
        """Return loaded schedule slots for the channel (chronological by slot_time).

        Returns empty list if schedule not loaded or channel unknown.
        Used by plan-day CLI to build PlanningDirective from same data as HorizonManager.
        """
        with self._lock:
            slots = self._schedules.get(channel_id, [])
        if not slots:
            return []
        return sorted(slots, key=lambda s: (s.slot_time.hour, s.slot_time.minute))

    def prime_schedule_day(
        self,
        channel_id: str,
        programming_day_date: date,
        resolution_time: datetime | None = None,
    ) -> None:
        """Prime the resolved store for a given day. Used by HorizonManager adapters
        and tests. Not part of the consumer API."""
        with self._lock:
            slots = self._schedules.get(channel_id, [])
        if not slots:
            return
        now = resolution_time or self._clock.now_utc()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        self._manager.resolve_schedule_day(
            channel_id=channel_id,
            programming_day_date=programming_day_date,
            slots=slots,
            resolution_time=now,
        )

    def get_playout_plan_now(
        self,
        channel_id: str,
        at_station_time: datetime,
    ) -> list[dict[str, Any]]:
        """
        Return the resolved segment sequence that should be airing 'right now'.

        INV-P5-003: Playout Plan Transformation - ProgramBlock → list[dict].
        """
        with self._lock:
            slots = self._schedules.get(channel_id, [])

        if not slots:
            return []

        # Ensure timezone awareness
        now = at_station_time
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # INV-P5-005: Missing data is a planning failure. No consumer-triggered resolution.
        programming_day_date = self._get_programming_day_date(now)
        if not self._resolved_store.exists(channel_id, programming_day_date):
            msg = (
                f"POLICY_VIOLATION: Programming day {programming_day_date} "
                f"not resolved for channel {channel_id}. "
                f"HorizonManager planning failure."
            )
            self._logger.error(msg)
            raise HorizonNoScheduleDataError(msg)

        # Day-prime: HorizonManager is responsible for extending horizon.
        next_day_date = programming_day_date + timedelta(days=1)
        if not self._resolved_store.exists(channel_id, next_day_date):
            self._logger.info(
                "Skipping day-prime for %s (HorizonManager responsible)",
                next_day_date,
            )

        # Get program block from manager
        block = self._manager.get_program_at(channel_id, now)
        if not block or not block.segments:
            self._logger.warning(
                "[%s] get_playout_plan_now: no block or segments at %s",
                channel_id, now
            )
            return []

        # Debug: log what we got from the manager
        self._logger.info(
            "[%s] get_playout_plan_now: now=%s, block_start=%s, block_end=%s, segments=%d",
            channel_id, now, block.block_start, block.block_end, len(block.segments)
        )
        for i, seg in enumerate(block.segments):
            self._logger.info(
                "[%s]   segment[%d]: file=%s, start=%s, end=%s, seek=%.1f",
                channel_id, i, seg.file_path.split('/')[-1] if seg.file_path else 'None',
                seg.start_utc, seg.end_utc, seg.seek_offset_seconds
            )

        # INV-P5-003: Transform ProgramBlock segments to ChannelManager format
        # Find the segment that is currently active and calculate proper seek offset
        playout_segments = []
        for segment in block.segments:
            # Check if this segment is currently active or in the future
            if now < segment.end_utc:
                # Calculate how far into the segment we are (mid-join offset)
                if now > segment.start_utc:
                    # Mid-segment join: add elapsed time to base seek offset
                    elapsed = (now - segment.start_utc).total_seconds()
                    total_seek = segment.seek_offset_seconds + elapsed
                else:
                    # At or before segment start
                    total_seek = segment.seek_offset_seconds

                start_pts_ms = int(total_seek * 1000)

                playout_segments.append({
                    "asset_path": segment.file_path,
                    "start_pts": start_pts_ms,
                    "duration_seconds": segment.duration_seconds,
                    "start_time_utc": segment.start_utc.isoformat(),
                    "end_time_utc": segment.end_utc.isoformat(),
                    "metadata": {
                        "phase": "phase3",
                        "grid_minutes": self._grid_minutes,
                    },
                })
                break  # Only return the currently active segment

        return playout_segments

    def _ensure_day_resolved(self, channel_id: str, at_dt: datetime) -> None:
        """Ensure the programming day containing at_dt is resolved.

        INV-P5-005: Missing data is a planning failure. No consumer-triggered resolution.
        """
        with self._lock:
            slots = self._schedules.get(channel_id, [])
        if not slots:
            return

        now = at_dt
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        programming_day_date = self._get_programming_day_date(now)
        if not self._resolved_store.exists(channel_id, programming_day_date):
            msg = (
                f"POLICY_VIOLATION: Programming day {programming_day_date} "
                f"not resolved for channel {channel_id}. "
                f"HorizonManager planning failure."
            )
            self._logger.error(msg)
            raise HorizonNoScheduleDataError(msg)

    def get_block_at(self, channel_id: str, utc_ms: int) -> ScheduledBlock | None:
        """Return a ScheduledBlock covering utc_ms from ScheduleManager.

        Uses get_program_at() which returns ProgramBlock with grid-aligned
        block_start/block_end and segments. Grid math lives here in the
        schedule layer, where it belongs.
        """
        at_dt = datetime.fromtimestamp(utc_ms / 1000.0, tz=timezone.utc)
        self._ensure_day_resolved(channel_id, at_dt)

        block = self._manager.get_program_at(channel_id, at_dt)
        if not block or not block.segments:
            return None

        start_utc_ms = int(block.block_start.timestamp() * 1000)
        end_utc_ms = int(block.block_end.timestamp() * 1000)

        return ScheduledBlock(
            block_id=f"BLOCK-{channel_id}-{start_utc_ms}",
            start_utc_ms=start_utc_ms,
            end_utc_ms=end_utc_ms,
            segments=tuple(
                ScheduledSegment(
                    segment_type=seg.segment_type,
                    asset_uri=seg.file_path or "",
                    asset_start_offset_ms=int(seg.seek_offset_seconds * 1000),
                    segment_duration_ms=int((seg.end_utc - seg.start_utc).total_seconds() * 1000),
                )
                for seg in block.segments
            ),
        )

    def get_epg_events(
        self,
        channel_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict[str, Any]]:
        """
        Get EPG events for the specified time range.

        INV-P5-004: EPG Endpoint Independence - works without active viewers.
        """
        with self._lock:
            slots = self._schedules.get(channel_id, [])

        if not slots:
            return []

        # Ensure timezone awareness
        start = start_time
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        end = end_time
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        # INV-P5-005: Missing data is a planning failure. No consumer-triggered resolution.
        current = start
        while current < end:
            programming_day_date = self._get_programming_day_date(current)
            if not self._resolved_store.exists(channel_id, programming_day_date):
                msg = (
                    f"POLICY_VIOLATION: Programming day {programming_day_date} "
                    f"not resolved for EPG query on channel {channel_id}. "
                    f"HorizonManager planning failure."
                )
                self._logger.error(msg)
                raise HorizonNoScheduleDataError(msg)
            current += timedelta(days=1)

        # Get EPG events from manager
        epg_events = self._manager.get_epg_events(channel_id, start, end)

        # Transform to JSON-serializable format
        return [
            {
                "channel_id": event.channel_id,
                "start_time": event.start_time.isoformat(),
                "end_time": event.end_time.isoformat(),
                "title": event.title,
                "episode_title": event.episode_title,
                "episode_id": event.episode_id,
                "programming_day_date": event.programming_day_date.isoformat(),
                "asset": {
                    "file_path": event.resolved_asset.file_path,
                    "asset_id": event.resolved_asset.asset_id,
                    "duration_seconds": event.resolved_asset.content_duration_seconds,
                },
            }
            for event in epg_events
        ]

    def _get_programming_day_date(self, t: datetime) -> date:
        """Get the programming day date for a given time."""
        if t.hour < self._programming_day_start_hour:
            return (t - timedelta(days=1)).date()
        return t.date()
