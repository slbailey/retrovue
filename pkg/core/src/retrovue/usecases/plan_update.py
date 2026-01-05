from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from ..domain.entities import SchedulePlan
from .plan_add import (
    _normalize_plan_name,
    _resolve_channel,
    _validate_cron_expression,
    _validate_date_format,
    _validate_date_range,
    _validate_priority,
)
from .plan_show import _resolve_plan


def update_plan(
    db: Session,
    *,
    channel_identifier: str,
    plan_identifier: str,
    name: str | None = None,
    description: str | None = None,
    cron_expression: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    priority: int | None = None,
    is_active: bool | None = None,
) -> dict[str, Any]:
    """Update a SchedulePlan and return a contract-aligned dict.
    
    Implements SchedulePlanUpdateContract.md behavioral rules.
    
    Args:
        db: Database session
        channel_identifier: Channel UUID or slug
        plan_identifier: Plan UUID or name
        name: Optional new plan name (must be unique within channel)
        description: Optional new description
        cron_expression: Optional new cron expression
        start_date: Optional new start date (YYYY-MM-DD)
        end_date: Optional new end date (YYYY-MM-DD)
        priority: Optional new priority (must be non-negative)
        is_active: Optional new active status
    
    Returns:
        Dictionary with status and plan object matching contract output format
    
    Raises:
        ValueError: If validation fails (channel/plan not found, name duplicate, invalid dates/cron/priority)
    """
    # B-1: Resolve channel
    channel = _resolve_channel(db, channel_identifier)
    
    # B-1: Resolve plan
    plan = _resolve_plan(db, channel.id, plan_identifier)
    
    # B-2: Check if at least one field is provided
    has_updates = any(
        [
            name is not None,
            description is not None,
            cron_expression is not None,
            start_date is not None,
            end_date is not None,
            priority is not None,
            is_active is not None,
        ]
    )
    if not has_updates:
        raise ValueError("At least one field must be provided for update")
    
    # B-3: Check name uniqueness if name is being updated
    if name is not None:
        # Only check uniqueness if the name is actually changing
        normalized_new_name = _normalize_plan_name(name)
        normalized_current_name = _normalize_plan_name(plan.name)
        if normalized_new_name.lower() != normalized_current_name.lower():
            # Check against all other plans in the channel (excluding current plan)
            existing_plans = (
                db.query(SchedulePlan)
                .filter(
                    SchedulePlan.channel_id == channel.id,
                    SchedulePlan.id != plan.id,
                )
                .all()
            )
            for existing_plan in existing_plans:
                if _normalize_plan_name(existing_plan.name).lower() == normalized_new_name.lower():
                    channel_name = channel.slug if channel else str(channel.id)
                    raise ValueError(
                        f"Plan name '{name}' already exists in channel '{channel_name}'"
                    )
        plan.name = name
    
    # B-4: Validate and update dates
    parsed_start_date = None
    parsed_end_date = None
    
    if start_date is not None:
        parsed_start_date = _validate_date_format(start_date)
        plan.start_date = parsed_start_date
    else:
        parsed_start_date = plan.start_date
    
    if end_date is not None:
        parsed_end_date = _validate_date_format(end_date)
        plan.end_date = parsed_end_date
    else:
        parsed_end_date = plan.end_date
    
    # Validate date range (both old and new dates)
    _validate_date_range(parsed_start_date, parsed_end_date)
    
    # B-5: Validate and update cron expression
    if cron_expression is not None:
        _validate_cron_expression(cron_expression)
        plan.cron_expression = cron_expression
    
    # B-6: Validate and update priority
    if priority is not None:
        validated_priority = _validate_priority(priority)
        plan.priority = validated_priority
    
    # Update other fields
    if description is not None:
        plan.description = description
    
    if is_active is not None:
        plan.is_active = is_active
    
    # D-2: updated_at is automatically updated by SQLAlchemy onupdate
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
        "status": "ok",
        "plan": {
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
        },
    }


__all__ = ["update_plan"]

