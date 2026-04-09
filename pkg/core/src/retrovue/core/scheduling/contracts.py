"""
Scheduling domain contracts and validation.

This module implements validation contracts for the scheduling domain:
- ScheduleDayContract
- PlaylogEventContract

These contracts enforce structural integrity, policy compliance, and playout safety.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

from .exceptions import (
    PlaylogEventValidationError,
    ScheduleDayValidationError,
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

