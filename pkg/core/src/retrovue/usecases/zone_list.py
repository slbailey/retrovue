from __future__ import annotations

import uuid as uuid_module
from datetime import UTC, date, datetime
from datetime import time as dt_time
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..domain.entities import SchedulePlan, Zone

# End of day sentinel (24:00 stored as 23:59:59.999999)
END_OF_DAY = dt_time(23, 59, 59, 999999)


def _resolve_plan(db: Session, identifier: str) -> SchedulePlan:
    """Resolve plan by UUID or name (case-insensitive).

    Raises ValueError if plan not found.
    """
    plan = None
    try:
        plan_uuid = uuid_module.UUID(identifier)
        plan = db.query(SchedulePlan).filter(SchedulePlan.id == plan_uuid).first()
    except ValueError:
        pass

    if not plan:
        plan = (
            db.query(SchedulePlan)
            .filter(func.lower(SchedulePlan.name) == identifier.lower())
            .first()
        )

    if not plan:
        raise ValueError(f"Plan '{identifier}' not found")

    return plan


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


def _zone_to_dict(zone: Zone) -> dict[str, Any]:
    """Convert Zone entity to output dictionary."""
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


def list_zones(
    db: Session,
    *,
    plan_identifier: str | None = None,
    enabled_only: bool = False,
) -> dict[str, Any]:
    """List zones, optionally filtered by plan.

    Args:
        db: Database session
        plan_identifier: Optional plan UUID or name to filter by
        enabled_only: If True, only return enabled zones

    Returns:
        Dictionary with zones list and count

    Raises:
        ValueError: If specified plan is not found
    """
    query = db.query(Zone)

    if plan_identifier:
        plan = _resolve_plan(db, plan_identifier)
        query = query.filter(Zone.plan_id == plan.id)

    if enabled_only:
        query = query.filter(Zone.enabled == True)  # noqa: E712

    # Order by plan_id, then start_time for consistent output
    query = query.order_by(Zone.plan_id, Zone.start_time)

    zones = query.all()

    return {
        "zones": [_zone_to_dict(z) for z in zones],
        "count": len(zones),
    }


def get_zone(
    db: Session,
    *,
    zone_identifier: str,
) -> dict[str, Any]:
    """Get a single zone by UUID or name.

    Args:
        db: Database session
        zone_identifier: Zone UUID or name

    Returns:
        Dictionary with zone details

    Raises:
        ValueError: If zone is not found
    """
    zone = None

    # Try UUID first
    try:
        zone_uuid = uuid_module.UUID(zone_identifier)
        zone = db.query(Zone).filter(Zone.id == zone_uuid).first()
    except ValueError:
        pass

    # Try name (may match multiple zones across plans, return first)
    if not zone:
        zone = (
            db.query(Zone)
            .filter(func.lower(Zone.name) == zone_identifier.lower())
            .first()
        )

    if not zone:
        raise ValueError(f"Zone '{zone_identifier}' not found")

    return _zone_to_dict(zone)


__all__ = ["list_zones", "get_zone"]
