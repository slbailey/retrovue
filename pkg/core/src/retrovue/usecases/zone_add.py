from __future__ import annotations

import uuid as uuid_module
from datetime import UTC, date, datetime
from datetime import time as dt_time
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..domain.entities import SchedulePlan, Zone

# Valid day filter values
VALID_DAYS = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}

# Valid DST policies
VALID_DST_POLICIES = {"reject", "shrink_one_block", "expand_one_block"}

# End of day sentinel (24:00 stored as 23:59:59.999999)
END_OF_DAY = dt_time(23, 59, 59, 999999)


def _resolve_plan(db: Session, identifier: str) -> SchedulePlan:
    """Resolve plan by UUID or name (case-insensitive).

    Raises ValueError if plan not found.
    """
    plan = None
    # Try UUID first
    try:
        plan_uuid = uuid_module.UUID(identifier)
        plan = db.query(SchedulePlan).filter(SchedulePlan.id == plan_uuid).first()
    except ValueError:
        pass

    # Try name (case-insensitive)
    if not plan:
        plan = (
            db.query(SchedulePlan)
            .filter(func.lower(SchedulePlan.name) == identifier.lower())
            .first()
        )

    if not plan:
        raise ValueError(f"Plan '{identifier}' not found")

    return plan


def _normalize_zone_name(name: str) -> str:
    """Normalize zone name for uniqueness comparison (case-insensitive, trimmed)."""
    return name.strip()


def _check_name_uniqueness(db: Session, plan_id: uuid_module.UUID, name: str) -> None:
    """Check if zone name is unique within plan.

    Raises ValueError if name already exists.
    """
    normalized_name = _normalize_zone_name(name)
    existing_zones = (
        db.query(Zone)
        .filter(Zone.plan_id == plan_id)
        .all()
    )
    for zone in existing_zones:
        if _normalize_zone_name(zone.name).lower() == normalized_name.lower():
            raise ValueError(f"Zone name '{name}' already exists in plan")


def _parse_time(time_str: str) -> dt_time:
    """Parse time string in HH:MM or HH:MM:SS format.

    Special handling for 24:00 which is stored as 23:59:59.999999.
    Raises ValueError if format is invalid.
    """
    time_str = time_str.strip()

    # Handle 24:00 special case (end of broadcast day)
    if time_str in ("24:00", "24:00:00"):
        return END_OF_DAY

    parts = time_str.split(":")
    if len(parts) == 2:
        h, m = parts
        return dt_time(int(h), int(m), 0)
    elif len(parts) == 3:
        h, m, s = parts
        return dt_time(int(h), int(m), int(s))
    else:
        raise ValueError(f"Invalid time format '{time_str}'. Use HH:MM or HH:MM:SS")


def _validate_time_range(start_time: dt_time, end_time: dt_time) -> None:
    """Validate time range. Allows midnight-spanning zones (end < start).

    Raises ValueError if times are identical.
    """
    if start_time == end_time:
        raise ValueError("start_time and end_time cannot be identical")


def _validate_day_filters(day_filters: list[str] | None) -> list[str] | None:
    """Validate day filter values.

    Raises ValueError if any invalid day is found.
    """
    if day_filters is None:
        return None

    validated = []
    for day in day_filters:
        day_upper = day.upper().strip()
        if day_upper not in VALID_DAYS:
            raise ValueError(f"Invalid day filter '{day}'. Valid values: {sorted(VALID_DAYS)}")
        validated.append(day_upper)

    return validated


def _validate_dst_policy(dst_policy: str | None) -> str | None:
    """Validate DST policy value.

    Raises ValueError if invalid policy.
    """
    if dst_policy is None:
        return None

    policy_lower = dst_policy.lower().strip()
    if policy_lower not in VALID_DST_POLICIES:
        raise ValueError(f"Invalid DST policy '{dst_policy}'. Valid values: {sorted(VALID_DST_POLICIES)}")

    return policy_lower


def _validate_date_format(date_str: str) -> date:
    """Validate and parse date string in YYYY-MM-DD format.

    Raises ValueError if format is invalid.
    """
    try:
        return date.fromisoformat(date_str)
    except ValueError as e:
        raise ValueError(f"Invalid date format. Use YYYY-MM-DD: {e}")


def _validate_date_range(effective_start: date | None, effective_end: date | None) -> None:
    """Validate that effective_start <= effective_end if both are provided.

    Raises ValueError if effective_start > effective_end.
    """
    if effective_start is not None and effective_end is not None:
        if effective_start > effective_end:
            raise ValueError("effective_start must be <= effective_end")


def _format_time(t: dt_time) -> str:
    """Format time for output. Returns 24:00 for end-of-day sentinel."""
    if t == END_OF_DAY:
        return "24:00:00"
    return t.strftime("%H:%M:%S")


def _format_date(d: date | None) -> str | None:
    """Format date for output."""
    return d.isoformat() if d else None


def _format_datetime(dt: datetime | None) -> str | None:
    """Format datetime for output in ISO-8601 UTC format."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.isoformat() + "Z"
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def add_zone(
    db: Session,
    *,
    plan_identifier: str,
    name: str,
    start_time: str,
    end_time: str,
    schedulable_assets: list[str] | None = None,
    day_filters: list[str] | None = None,
    enabled: bool = True,
    effective_start: str | None = None,
    effective_end: str | None = None,
    dst_policy: str | None = None,
) -> dict[str, Any]:
    """Create a Zone and return a contract-aligned dict.

    Args:
        db: Database session
        plan_identifier: Plan UUID or name
        name: Zone name (must be unique within plan)
        start_time: Start time in HH:MM or HH:MM:SS format (broadcast day time)
        end_time: End time in HH:MM or HH:MM:SS format (24:00 for end of day)
        schedulable_assets: List of asset/program UUIDs
        day_filters: Day-of-week constraints (MON,TUE,WED,THU,FRI,SAT,SUN)
        enabled: Active status (default: True)
        effective_start: Start date for zone validity (YYYY-MM-DD)
        effective_end: End date for zone validity (YYYY-MM-DD)
        dst_policy: DST handling policy

    Returns:
        Dictionary with zone details

    Raises:
        ValueError: If validation fails
    """
    # Resolve plan
    plan = _resolve_plan(db, plan_identifier)

    # Check name uniqueness
    _check_name_uniqueness(db, plan.id, name)

    # Parse and validate times
    parsed_start = _parse_time(start_time)
    parsed_end = _parse_time(end_time)
    _validate_time_range(parsed_start, parsed_end)

    # Validate day filters
    validated_day_filters = _validate_day_filters(day_filters)

    # Validate DST policy
    validated_dst_policy = _validate_dst_policy(dst_policy)

    # Parse and validate effective dates
    parsed_effective_start = _validate_date_format(effective_start) if effective_start else None
    parsed_effective_end = _validate_date_format(effective_end) if effective_end else None
    _validate_date_range(parsed_effective_start, parsed_effective_end)

    # Create zone
    zone = Zone(
        plan_id=plan.id,
        name=name.strip(),
        start_time=parsed_start,
        end_time=parsed_end,
        schedulable_assets=schedulable_assets or [],
        day_filters=validated_day_filters,
        enabled=enabled,
        effective_start=parsed_effective_start,
        effective_end=parsed_effective_end,
        dst_policy=validated_dst_policy,
    )

    db.add(zone)
    db.commit()
    db.refresh(zone)

    return {
        "id": str(zone.id),
        "plan_id": str(zone.plan_id),
        "name": zone.name,
        "start_time": _format_time(zone.start_time),
        "end_time": _format_time(zone.end_time),
        "schedulable_assets": zone.schedulable_assets,
        "day_filters": zone.day_filters,
        "enabled": zone.enabled,
        "effective_start": _format_date(zone.effective_start),
        "effective_end": _format_date(zone.effective_end),
        "dst_policy": zone.dst_policy,
        "created_at": _format_datetime(zone.created_at),
        "updated_at": _format_datetime(zone.updated_at),
    }


__all__ = ["add_zone"]
