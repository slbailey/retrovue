from __future__ import annotations

import uuid as uuid_module
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..domain.entities import Channel, SchedulePlan


def _resolve_channel(db: Session, identifier: str) -> Channel:
    """Resolve channel by UUID or slug (case-insensitive).
    
    Raises ValueError if channel not found.
    """
    channel = None
    # Try UUID first
    try:
        channel_uuid = uuid_module.UUID(identifier)
        channel = db.query(Channel).filter(Channel.id == channel_uuid).first()
    except ValueError:
        pass
    
    # Try slug (case-insensitive)
    if not channel:
        channel = (
            db.query(Channel)
            .filter(func.lower(Channel.slug) == identifier.lower())
            .first()
        )
    
    if not channel:
        raise ValueError(f"Channel '{identifier}' not found")
    
    return channel


def _normalize_plan_name(name: str) -> str:
    """Normalize plan name for uniqueness comparison (case-insensitive, trimmed)."""
    return name.strip()


def _check_name_uniqueness(db: Session, channel_id: uuid_module.UUID, name: str) -> None:
    """Check if plan name is unique within channel.
    
    Raises ValueError if name already exists.
    Uses case-insensitive, trimmed comparison matching lookup normalization.
    """
    normalized_name = _normalize_plan_name(name)
    # Query all plans for the channel and check normalized names
    existing_plans = (
        db.query(SchedulePlan)
        .filter(SchedulePlan.channel_id == channel_id)
        .all()
    )
    for plan in existing_plans:
        if _normalize_plan_name(plan.name).lower() == normalized_name.lower():
            channel = db.query(Channel).filter(Channel.id == channel_id).first()
            channel_name = channel.slug if channel else str(channel_id)
            raise ValueError(f"Plan name '{name}' already exists in channel '{channel_name}'")


def _validate_date_format(date_str: str) -> date:
    """Validate and parse date string in YYYY-MM-DD format.
    
    Raises ValueError if format is invalid.
    """
    try:
        return date.fromisoformat(date_str)
    except ValueError as e:
        raise ValueError(f"Invalid date format. Use YYYY-MM-DD: {e}")


def _validate_date_range(start_date: date | None, end_date: date | None) -> None:
    """Validate that start_date <= end_date if both are provided.
    
    Raises ValueError if start_date > end_date.
    """
    if start_date is not None and end_date is not None:
        if start_date > end_date:
            raise ValueError("start_date must be <= end_date")


def _validate_cron_expression(cron: str | None) -> None:
    """Validate cron expression syntax.
    
    Raises ValueError if cron syntax is invalid.
    Note: Hour and minute fields are parsed but ignored per contract.
    """
    if cron is None:
        return
    
    # Basic validation - check it has 5 fields
    parts = cron.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: {cron}")
    
    # Try to parse with croniter if available, otherwise basic format check
    try:
        from croniter import croniter  # type: ignore[import-untyped]
        croniter(cron)
    except ImportError:
        # If croniter not available, do basic format check
        # Cron format: minute hour day month day-of-week
        # We only care about day/month/day-of-week fields (last 3)
        # Basic validation: check that fields are not empty
        if not all(part.strip() for part in parts):
            raise ValueError(f"Invalid cron expression: {cron}")
    except Exception:
        raise ValueError(f"Invalid cron expression: {cron}")


def _validate_priority(priority: int | None) -> int:
    """Validate priority is non-negative.
    
    Returns default priority (0) if None.
    Raises ValueError if priority is negative.
    """
    if priority is None:
        return 0
    if priority < 0:
        raise ValueError("Priority must be non-negative")
    return priority


def add_plan(
    db: Session,
    *,
    channel_identifier: str,
    name: str,
    description: str | None = None,
    cron_expression: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    priority: int | None = None,
    is_active: bool = True,
) -> dict[str, Any]:
    """Create a SchedulePlan and return a contract-aligned dict.
    
    Implements SchedulePlanAddContract.md behavioral rules.
    
    Args:
        db: Database session
        channel_identifier: Channel UUID or slug
        name: Plan name (must be unique within channel)
        description: Optional description
        cron_expression: Optional cron expression (hour/minute ignored)
        start_date: Optional start date (YYYY-MM-DD)
        end_date: Optional end date (YYYY-MM-DD)
        priority: Optional priority (default: 0, must be non-negative)
        is_active: Active status (default: True)
    
    Returns:
        Dictionary with plan details matching contract output format
    
    Raises:
        ValueError: If validation fails (channel not found, name duplicate, invalid dates/cron/priority)
    """
    # B-1: Resolve channel
    channel = _resolve_channel(db, channel_identifier)
    
    # B-2: Check name uniqueness (case-insensitive, trimmed)
    _check_name_uniqueness(db, channel.id, name)
    
    # B-3: Validate date range
    parsed_start_date = _validate_date_format(start_date) if start_date else None
    parsed_end_date = _validate_date_format(end_date) if end_date else None
    _validate_date_range(parsed_start_date, parsed_end_date)
    
    # B-4: Validate cron expression
    _validate_cron_expression(cron_expression)
    
    # B-5: Validate priority
    validated_priority = _validate_priority(priority)
    
    # Create plan
    plan = SchedulePlan(
        channel_id=channel.id,
        name=name,
        description=description,
        cron_expression=cron_expression,
        start_date=parsed_start_date,
        end_date=parsed_end_date,
        priority=validated_priority,
        is_active=is_active,
    )
    
    db.add(plan)
    db.commit()
    db.refresh(plan)
    
    # Format output matching contract
    def format_date(d: date | None) -> str | None:
        return d.isoformat() if d else None
    
    def format_datetime(dt: datetime | None) -> str | None:
        if dt is None:
            return None
        # Format as ISO-8601 UTC with Z suffix
        if dt.tzinfo is None:
            # Assume UTC if no timezone
            return dt.isoformat() + "Z"
        return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")
    
    return {
        "id": str(plan.id),
        "channel_id": str(plan.channel_id),
        "name": plan.name,
        "description": plan.description,
        "cron_expression": plan.cron_expression,
        "start_date": format_date(plan.start_date),
        "end_date": format_date(plan.end_date),
        "priority": plan.priority,
        "is_active": plan.is_active,
        "created_at": format_datetime(plan.created_at),
        "updated_at": format_datetime(plan.updated_at),
    }


__all__ = ["add_plan"]
