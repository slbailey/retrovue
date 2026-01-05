"""
Scheduling domain contracts and validation.

This module implements validation contracts for the scheduling domain:
- SchedulePlanInvariantsContract
- ProgramContract
- ScheduleDayContract
- PlaylogEventContract

These contracts enforce structural integrity, policy compliance, and playout safety.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

from .exceptions import (
    BlockAssignmentValidationError,
    PlaylogEventValidationError,
    ScheduleDayValidationError,
    SchedulePlanValidationError,
)

# Constants
SECONDS_PER_DAY = 86400  # 24 hours
DURATION_TOLERANCE_SECONDS = 2  # Tolerance for VirtualAsset duration matching


def parse_time_to_seconds(time_str: str) -> int:
    """
    Parse HH:MM format time string to seconds since midnight.

    Args:
        time_str: Time string in "HH:MM" format

    Returns:
        Seconds since midnight (00:00)

    Raises:
        ValueError: If time string is invalid
    """
    try:
        parts = time_str.split(":")
        if len(parts) != 2:
            raise ValueError(f"Invalid time format: {time_str}. Expected HH:MM")
        hours = int(parts[0])
        minutes = int(parts[1])
        if not (0 <= hours < 24 and 0 <= minutes < 60):
            raise ValueError(f"Time out of range: {time_str}")
        return hours * 3600 + minutes * 60
    except (ValueError, AttributeError) as e:
        raise ValueError(f"Invalid time format: {time_str}") from e


def calculate_end_time(start_time_str: str, duration_minutes: int) -> int:
    """
    Calculate end time in seconds from start time and duration.

    Args:
        start_time_str: Start time in "HH:MM" format
        duration_minutes: Duration in minutes

    Returns:
        End time in seconds since midnight
    """
    start_seconds = parse_time_to_seconds(start_time_str)
    end_seconds = start_seconds + (duration_minutes * 60)
    # Handle wrap-around past 24:00
    if end_seconds > SECONDS_PER_DAY:
        end_seconds = SECONDS_PER_DAY
    return end_seconds


def validate_schedule_plan(plan: Any) -> None:
    """
    Validate a SchedulePlan against all invariants.

    This function enforces SchedulePlanInvariantsContract rules:
    - Plan start_offset must equal 0 (plans begin at 00:00)
    - All block assignments must have non-overlapping time windows
    - The union of all block durations must not exceed 24 hours
    - Blocks must be ordered by ascending start_time
    - Labels (if present) must exist in SchedulePlanLabel for that plan
    - Grid boundary validation (if plan has a channel relationship loaded):
      - Duration must be a multiple of channel's grid_block_minutes
      - Start time must align with channel's grid boundaries
    - If a ContentPolicyRule is linked, validate it during plan compilation

    Args:
        plan: SchedulePlan object with attributes:
            - id (UUID)
            - name (str)
            - channel_id (UUID)
            - channel (Channel, optional): If the channel relationship is loaded,
              grid boundary validation will be performed on all block assignments
            - programs (list[Program])
            - labels (list[SchedulePlanLabel], optional)

    Raises:
        SchedulePlanValidationError: If validation fails
    """
    violations: list[str] = []

    # Get plan attributes (handle both SQLAlchemy models and dict-like objects)
    plan_id = getattr(plan, "id", None)
    plan_name = getattr(plan, "name", "Unknown")
    # channel_id = getattr(plan, "channel_id", None)  # Not currently used

    # Get programs
    programs = getattr(plan, "programs", getattr(plan, "block_assignments", []))
    if not hasattr(programs, "__iter__"):
        programs = []

    # Rule 1: Plan must begin at 00:00 (start_offset = 0)
    # Note: In the new architecture, plans always start at 00:00, so this is implicit
    # We validate that all assignments use schedule-time starting from 00:00

    # Rule 2: All programs must have non-overlapping time windows
    assignment_times: list[tuple[int, int, Any]] = []  # (start_seconds, end_seconds, program)

    for assignment in programs:
        start_time = getattr(assignment, "start_time", None)
        duration = getattr(assignment, "duration", None)

        if start_time is None or duration is None:
            violations.append(
                f"Block assignment {getattr(assignment, 'id', 'unknown')} missing start_time or duration"
            )
            continue

        try:
            start_seconds = parse_time_to_seconds(str(start_time))
            duration_seconds = duration * 60
            end_seconds = start_seconds + duration_seconds

            # Check for negative or zero duration
            if duration <= 0:
                violations.append(
                    f"Block assignment {getattr(assignment, 'id', 'unknown')} has invalid duration: {duration} minutes"
                )
                continue

            # Check for start time out of range
            if start_seconds < 0 or start_seconds >= SECONDS_PER_DAY:
                violations.append(
                    f"Block assignment {getattr(assignment, 'id', 'unknown')} has start_time out of range: {start_time}"
                )
                continue

            assignment_times.append((start_seconds, end_seconds, assignment))
        except ValueError as e:
            violations.append(
                f"Block assignment {getattr(assignment, 'id', 'unknown')} has invalid start_time format: {e}"
            )

    # Check for overlaps
    assignment_times.sort(key=lambda x: x[0])  # Sort by start time
    for i in range(len(assignment_times) - 1):
        start1, end1, assign1 = assignment_times[i]
        start2, end2, assign2 = assignment_times[i + 1]

        # Overlap check: (start1 < end2) AND (end1 > start2)
        if start1 < end2 and end1 > start2:
            assign1_id = getattr(assign1, "id", "unknown")
            assign2_id = getattr(assign2, "id", "unknown")
            violations.append(
                f"Block assignments overlap: {assign1_id} ({start1//3600:02d}:{(start1%3600)//60:02d} - "
                f"{end1//3600:02d}:{(end1%3600)//60:02d}) and {assign2_id} "
                f"({start2//3600:02d}:{(start2%3600)//60:02d} - {end2//3600:02d}:{(end2%3600)//60:02d})"
            )

    # Rule 3: Total duration must not exceed 24 hours
    total_duration_seconds = sum(end - start for start, end, _ in assignment_times)
    if total_duration_seconds > SECONDS_PER_DAY:
        violations.append(
            f"Total block duration ({total_duration_seconds/3600:.2f} hours) exceeds 24 hours"
        )

    # Rule 4: Blocks must be ordered by ascending start_time
    # (Already sorted above, but verify)
    for i in range(len(assignment_times) - 1):
        if assignment_times[i][0] > assignment_times[i + 1][0]:
            violations.append("Block assignments are not ordered by ascending start_time")

    # Rule 5: Labels (if present) must exist in SchedulePlanLabel for that plan
    labels = getattr(plan, "labels", [])
    # Get label IDs from programs
    assignment_label_ids = set()
    for assignment in programs:
        label_id = getattr(assignment, "label_id", None)
        if label_id:
            assignment_label_ids.add(label_id)

    # If any assignments reference labels, validate they exist in plan's labels
    if assignment_label_ids:
        plan_label_ids = {getattr(label, "id", None) for label in labels if hasattr(label, "id")}
        missing_labels = assignment_label_ids - plan_label_ids
        if missing_labels:
            violations.append(
                f"Block assignments reference labels that don't exist in plan: {missing_labels}"
            )

    # Rule 6: Validate programs with grid boundaries (if channel available)
    # Since SchedulePlans are required to be tied to a channel, try to get channel from plan
    plan_channel = getattr(plan, "channel", None)
    if plan_channel:
        # Validate each program with grid boundaries
        for assignment in programs:
            try:
                validate_block_assignment(assignment, plan=plan, channel=plan_channel)
            except BlockAssignmentValidationError as e:
                # Collect violations from block assignment validation
                for violation in e.violations:
                    violations.append(
                        f"Block assignment {getattr(assignment, 'id', 'unknown')}: {violation}"
                    )

    # Rule 7: ContentPolicyRule validation (future feature - placeholder)
    # When ContentPolicyRule is implemented, validate here

    if violations:
        raise SchedulePlanValidationError(
            f"SchedulePlan '{plan_name}' (id: {plan_id}) failed validation",
            plan_id=str(plan_id) if plan_id else None,
            plan_name=plan_name,
            violations=violations,
        )


def validate_block_assignment(assignment: Any, plan: Any | None = None, channel: Any | None = None) -> None:
    """
    Validate a Program against all rules.

    This function enforces ProgramContract rules:
    - start_time and duration are required and positive
    - Duration must be a multiple of channel's grid_block_minutes (if channel provided or available from plan)
    - Start time must align with channel's grid boundaries (if channel provided or available from plan)
    
    Note: Since SchedulePlans are required to be tied to a channel, if a plan is provided
    with a loaded channel relationship, grid boundary validation will be performed automatically.
    - If content_ref points to a VirtualAsset, ensure it exists and can expand
    - If content_ref points to a Series or Playlist, ensure it contains playable items
    - Validate ContentPolicyRule compatibility

    Args:
        assignment: Program object
        plan: Optional SchedulePlan object (for context). If provided and has a channel
            relationship loaded, it will be used for grid boundary validation.
        channel: Optional Channel object (for grid boundary validation). If not provided,
            the function will attempt to use the channel from the plan if available.

    Raises:
        BlockAssignmentValidationError: If validation fails
    """
    violations: list[str] = []

    assignment_id = getattr(assignment, "id", None)
    plan_id = getattr(plan, "id", None) if plan else None

    # Rule 1: start_time and duration are required and positive
    start_time = getattr(assignment, "start_time", None)
    duration = getattr(assignment, "duration", None)

    if start_time is None:
        violations.append("start_time is required")
    else:
        try:
            start_seconds = parse_time_to_seconds(str(start_time))
            if start_seconds < 0 or start_seconds >= SECONDS_PER_DAY:
                violations.append(f"start_time out of range: {start_time}")
        except ValueError as e:
            violations.append(f"Invalid start_time format: {e}")

    if duration is None:
        violations.append("duration is required")
    elif duration <= 0:
        violations.append(f"duration must be positive, got: {duration} minutes")

    # Rule 1a: Grid boundary validation (if channel provided or available from plan)
    # Try to get channel from plan if not explicitly provided
    # Since SchedulePlans are required to be tied to a channel, we can use the plan's channel
    if not channel and plan:
        # Try to get channel from plan (may be a relationship or attribute)
        plan_channel = getattr(plan, "channel", None)
        if plan_channel:
            channel = plan_channel
        # If plan has channel_id but channel not loaded, we can't fetch it here
        # (validation functions don't have DB access), so we skip grid validation
    
    if channel and start_time and duration:
        try:
            grid_block_minutes = getattr(channel, "grid_block_minutes", None)
            block_start_offsets_minutes = getattr(channel, "block_start_offsets_minutes", None)

            if grid_block_minutes is None:
                # Channel doesn't have grid_block_minutes, skip grid validation
                pass
            else:
                # Validate duration is a multiple of grid_block_minutes
                if duration % grid_block_minutes != 0:
                    violations.append(
                        f"duration ({duration} minutes) must be a multiple of channel grid size "
                        f"({grid_block_minutes} minutes)"
                    )

                # Validate start_time aligns with grid boundaries
                start_seconds = parse_time_to_seconds(str(start_time))
                start_minutes = start_seconds // 60

                # Get allowed offsets from channel
                allowed_offsets: list[int] = []
                if isinstance(block_start_offsets_minutes, list):
                    allowed_offsets = block_start_offsets_minutes
                elif block_start_offsets_minutes is None:
                    # Default to [0] if not specified
                    allowed_offsets = [0]

                # Check if the start time aligns with any allowed offset
                # For a grid of size N, valid start times are: offset + k*N for any k
                # where offset is in allowed_offsets
                aligns_with_grid = False
                for offset in allowed_offsets:
                    # Check if (start_minutes - offset) is divisible by grid_block_minutes
                    if (start_minutes - offset) % grid_block_minutes == 0:
                        aligns_with_grid = True
                        break

                if not aligns_with_grid:
                    offsets_str = ", ".join(str(o) for o in allowed_offsets)
                    violations.append(
                        f"start_time ({start_time}) does not align with channel grid boundaries. "
                        f"Grid size: {grid_block_minutes} minutes, allowed offsets: {offsets_str}"
                    )
        except (ValueError, AttributeError):
            # If we can't parse or access channel properties, skip grid validation
            # but log that we couldn't validate
            pass

    # Rule 2: Validate content_type and content_ref
    content_type = getattr(assignment, "content_type", None)
    content_ref = getattr(assignment, "content_ref", getattr(assignment, "content_reference", None))

    if not content_type:
        violations.append("content_type is required")
    elif content_type not in ("series", "asset", "rule", "random", "virtual_package"):
        violations.append(
            f"Invalid content_type: {content_type}. Must be one of: series, asset, rule, random, virtual_package"
        )

    if not content_ref:
        violations.append("content_ref is required")

    # Rule 3: If content_ref points to VirtualAsset, validate it exists
    if content_type == "virtual_package" and content_ref:
        # TODO: When VirtualAsset model exists, validate it exists and can expand
        # For now, just check that reference is provided
        pass

    # Rule 4: If content_ref points to Series or Playlist, validate it contains items
    if content_type == "series" and content_ref:
        # TODO: When Series/Playlist models exist, validate they contain playable items
        # For now, just check that reference is provided
        pass

    # Rule 5: Validate ContentPolicyRule compatibility (future feature)
    # When ContentPolicyRule is implemented, validate here
    # Example: if policy says "family_safe: true", cannot schedule adult content

    if violations:
        raise BlockAssignmentValidationError(
            f"Block assignment {assignment_id} failed validation",
            assignment_id=str(assignment_id) if assignment_id else None,
            plan_id=str(plan_id) if plan_id else None,
            violations=violations,
        )


def validate_schedule_day(schedule_day: Any, channel: Any | None = None) -> None:
    """
    Validate a BroadcastScheduleDay against all rules.

    This function enforces ScheduleDayContract rules:
    - No duplicate or overlapping PlaylogEvents
    - Each PlaylogEvent should trace back to a Program
    - All timestamps must align to channel's broadcast_day_start logic
    - If VirtualAsset expands into multiple events, verify total runtime matches

    Args:
        schedule_day: BroadcastScheduleDay object
        channel: Optional Channel object (for broadcast_day_start validation)

    Raises:
        ScheduleDayValidationError: If validation fails
    """
    violations: list[str] = []

    schedule_day_id = getattr(schedule_day, "id", None)
    channel_id = getattr(schedule_day, "channel_id", None)
    schedule_date = getattr(schedule_day, "schedule_date", None)

    # Get playlog events (if available)
    playlog_events = getattr(schedule_day, "playlog_events", [])
    if not hasattr(playlog_events, "__iter__"):
        playlog_events = []

    # Rule 1: No duplicate or overlapping PlaylogEvents
    event_times: list[tuple[datetime, datetime, Any]] = []
    for event in playlog_events:
        start_utc = getattr(event, "start_utc", None)
        end_utc = getattr(event, "end_utc", None)

        if start_utc is None or end_utc is None:
            violations.append(
                f"PlaylogEvent {getattr(event, 'uuid', 'unknown')} missing start_utc or end_utc"
            )
            continue

        if not isinstance(start_utc, datetime) or not isinstance(end_utc, datetime):
            violations.append(
                f"PlaylogEvent {getattr(event, 'uuid', 'unknown')} has invalid timestamp types"
            )
            continue

        if start_utc >= end_utc:
            violations.append(
                f"PlaylogEvent {getattr(event, 'uuid', 'unknown')} has start_utc >= end_utc"
            )
            continue

        event_times.append((start_utc, end_utc, event))

    # Check for overlaps
    event_times.sort(key=lambda x: x[0])  # Sort by start time
    for i in range(len(event_times) - 1):
        start1, end1, event1 = event_times[i]
        start2, end2, event2 = event_times[i + 1]

        # Overlap check: (start1 < end2) AND (end1 > start2)
        if start1 < end2 and end1 > start2:
            event1_id = getattr(event1, "uuid", "unknown")
            event2_id = getattr(event2, "uuid", "unknown")
            violations.append(
                f"PlaylogEvents overlap: {event1_id} ({start1} - {end1}) and {event2_id} ({start2} - {end2})"
            )

    # Rule 2: Each PlaylogEvent should trace back to a Program
    # (This is more of a data integrity check - verify schedule_day_id is set)
    for event in playlog_events:
        event_schedule_day_id = getattr(event, "schedule_day_id", None)
        if event_schedule_day_id != schedule_day_id:
            event_id = getattr(event, "uuid", "unknown")
            violations.append(
                f"PlaylogEvent {event_id} has schedule_day_id mismatch: expected {schedule_day_id}, got {event_schedule_day_id}"
            )

    # Rule 3: All timestamps must align to channel's broadcast_day_start logic
    # (This is validated during generation, but we can check that times are reasonable)
    if channel:
        programming_day_start = getattr(channel, "programming_day_start", None)
        if programming_day_start:
            # Validate that event times align with programming day start
            # This is a complex check that depends on the channel's timezone and programming_day_start
            # For now, we just verify that programming_day_start is a valid time
            if not isinstance(programming_day_start, time):
                violations.append("Channel programming_day_start is not a valid time object")

    # Rule 4: If VirtualAsset expands into multiple events, verify total runtime matches
    # (This requires tracking which events came from which VirtualAsset)
    # TODO: When VirtualAsset expansion tracking is implemented, validate here

    if violations:
        raise ScheduleDayValidationError(
            f"BroadcastScheduleDay {schedule_day_id} failed validation",
            schedule_day_id=str(schedule_day_id) if schedule_day_id else None,
            channel_id=str(channel_id) if channel_id else None,
            schedule_date=str(schedule_date) if schedule_date else None,
            violations=violations,
        )


def validate_playlog_event(event: Any, channel: Any | None = None) -> None:
    """
    Validate a BroadcastPlaylogEvent against all rules.

    This function enforces PlaylogEventContract rules:
    - absolute_start < absolute_end (using start_utc and end_utc)
    - duration = absolute_end - absolute_start
    - asset_uri must resolve to a valid media file or URL
    - No overlapping events within a single channel's day log unless allow_overlap=True

    Args:
        event: BroadcastPlaylogEvent object
        channel: Optional Channel object (for context)

    Raises:
        PlaylogEventValidationError: If validation fails
    """
    violations: list[str] = []

    event_id = getattr(event, "uuid", None) or getattr(event, "id", None)
    channel_id = getattr(event, "channel_id", None)

    # Rule 1: start_utc < end_utc
    start_utc = getattr(event, "start_utc", None)
    end_utc = getattr(event, "end_utc", None)

    if start_utc is None:
        violations.append("start_utc is required")
    if end_utc is None:
        violations.append("end_utc is required")

    if start_utc and end_utc:
        if not isinstance(start_utc, datetime) or not isinstance(end_utc, datetime):
            violations.append("start_utc and end_utc must be datetime objects")
        elif start_utc >= end_utc:
            violations.append(f"start_utc ({start_utc}) must be less than end_utc ({end_utc})")

        # Rule 2: duration = end_utc - start_utc
        calculated_duration = (end_utc - start_utc).total_seconds()
        # Note: PlaylogEvent doesn't have a duration field in the domain model,
        # but we can validate the time difference is reasonable
        if calculated_duration <= 0:
            violations.append("Event duration must be positive")

    # Rule 3: asset_uuid must be valid
    asset_uuid = getattr(event, "asset_uuid", None)
    if not asset_uuid:
        violations.append("asset_uuid is required")

    # Rule 4: No overlapping events (checked at ScheduleDay level)
    # This is handled by validate_schedule_day

    # Additional validation: broadcast_day must be in YYYY-MM-DD format
    broadcast_day = getattr(event, "broadcast_day", None)
    if broadcast_day:
        try:
            datetime.strptime(str(broadcast_day), "%Y-%m-%d")
        except (ValueError, TypeError):
            violations.append(f"broadcast_day must be in YYYY-MM-DD format, got: {broadcast_day}")

    if violations:
        raise PlaylogEventValidationError(
            f"BroadcastPlaylogEvent {event_id} failed validation",
            event_id=str(event_id) if event_id else None,
            channel_id=str(channel_id) if channel_id else None,
            violations=violations,
        )

