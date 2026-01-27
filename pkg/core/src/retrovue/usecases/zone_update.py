from __future__ import annotations

import uuid as uuid_module
from datetime import UTC, date, datetime
from datetime import time as dt_time
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..domain.entities import Zone

# Valid day filter values
VALID_DAYS = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}

# Valid DST policies
VALID_DST_POLICIES = {"reject", "shrink_one_block", "expand_one_block"}

# End of day sentinel (24:00 stored as 23:59:59.999999)
END_OF_DAY = dt_time(23, 59, 59, 999999)


def _resolve_zone(db: Session, identifier: str) -> Zone:
    """Resolve zone by UUID or name (case-insensitive).

    Raises ValueError if zone not found.
    """
    zone = None
    try:
        zone_uuid = uuid_module.UUID(identifier)
        zone = db.query(Zone).filter(Zone.id == zone_uuid).first()
    except ValueError:
        pass

    if not zone:
        zone = (
            db.query(Zone)
            .filter(func.lower(Zone.name) == identifier.lower())
            .first()
        )

    if not zone:
        raise ValueError(f"Zone '{identifier}' not found")

    return zone


def _check_name_uniqueness(db: Session, plan_id: uuid_module.UUID, name: str, exclude_zone_id: uuid_module.UUID) -> None:
    """Check if zone name is unique within plan, excluding current zone.

    Raises ValueError if name already exists.
    """
    normalized_name = name.strip().lower()
    existing_zones = (
        db.query(Zone)
        .filter(Zone.plan_id == plan_id)
        .filter(Zone.id != exclude_zone_id)
        .all()
    )
    for zone in existing_zones:
        if zone.name.strip().lower() == normalized_name:
            raise ValueError(f"Zone name '{name}' already exists in plan")


def _parse_time(time_str: str) -> dt_time:
    """Parse time string in HH:MM or HH:MM:SS format."""
    time_str = time_str.strip()

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


def _validate_day_filters(day_filters: list[str] | None) -> list[str] | None:
    """Validate day filter values."""
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
    """Validate DST policy value."""
    if dst_policy is None:
        return None

    policy_lower = dst_policy.lower().strip()
    if policy_lower not in VALID_DST_POLICIES:
        raise ValueError(f"Invalid DST policy '{dst_policy}'. Valid values: {sorted(VALID_DST_POLICIES)}")

    return policy_lower


def _validate_date_format(date_str: str) -> date:
    """Validate and parse date string in YYYY-MM-DD format."""
    try:
        return date.fromisoformat(date_str)
    except ValueError as e:
        raise ValueError(f"Invalid date format. Use YYYY-MM-DD: {e}")


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


def update_zone(
    db: Session,
    *,
    zone_identifier: str,
    name: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    schedulable_assets: list[str] | None = None,
    day_filters: list[str] | None = None,
    clear_day_filters: bool = False,
    enabled: bool | None = None,
    effective_start: str | None = None,
    effective_end: str | None = None,
    clear_effective_start: bool = False,
    clear_effective_end: bool = False,
    dst_policy: str | None = None,
    clear_dst_policy: bool = False,
) -> dict[str, Any]:
    """Update a Zone and return a contract-aligned dict.

    Args:
        db: Database session
        zone_identifier: Zone UUID or name
        name: New zone name (optional)
        start_time: New start time in HH:MM or HH:MM:SS format (optional)
        end_time: New end time in HH:MM or HH:MM:SS format (optional)
        schedulable_assets: New list of asset/program UUIDs (optional)
        day_filters: New day-of-week constraints (optional)
        clear_day_filters: If True, clear day_filters to null
        enabled: New active status (optional)
        effective_start: New start date for zone validity (optional)
        effective_end: New end date for zone validity (optional)
        clear_effective_start: If True, clear effective_start to null
        clear_effective_end: If True, clear effective_end to null
        dst_policy: New DST handling policy (optional)
        clear_dst_policy: If True, clear dst_policy to null

    Returns:
        Dictionary with updated zone details

    Raises:
        ValueError: If validation fails
    """
    zone = _resolve_zone(db, zone_identifier)

    # Update name if provided
    if name is not None:
        _check_name_uniqueness(db, zone.plan_id, name, zone.id)
        zone.name = name.strip()

    # Update times if provided
    if start_time is not None:
        zone.start_time = _parse_time(start_time)

    if end_time is not None:
        zone.end_time = _parse_time(end_time)

    # Validate time range after updates
    if zone.start_time == zone.end_time:
        raise ValueError("start_time and end_time cannot be identical")

    # Update schedulable_assets if provided
    if schedulable_assets is not None:
        zone.schedulable_assets = schedulable_assets

    # Update day_filters
    if clear_day_filters:
        zone.day_filters = None
    elif day_filters is not None:
        zone.day_filters = _validate_day_filters(day_filters)

    # Update enabled if provided
    if enabled is not None:
        zone.enabled = enabled

    # Update effective dates
    if clear_effective_start:
        zone.effective_start = None
    elif effective_start is not None:
        zone.effective_start = _validate_date_format(effective_start)

    if clear_effective_end:
        zone.effective_end = None
    elif effective_end is not None:
        zone.effective_end = _validate_date_format(effective_end)

    # Validate date range
    if zone.effective_start is not None and zone.effective_end is not None:
        if zone.effective_start > zone.effective_end:
            raise ValueError("effective_start must be <= effective_end")

    # Update DST policy
    if clear_dst_policy:
        zone.dst_policy = None
    elif dst_policy is not None:
        zone.dst_policy = _validate_dst_policy(dst_policy)

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


__all__ = ["update_zone"]
