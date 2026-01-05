from __future__ import annotations

import uuid as uuid_module
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..domain.entities import Channel, SchedulePlan
from .plan_add import _normalize_plan_name, _resolve_channel


def _resolve_plan(db: Session, channel_id: uuid_module.UUID, plan_identifier: str) -> SchedulePlan:
    """Resolve plan by UUID or name (case-insensitive, trimmed).
    
    Implements B-4 and B-5 from SchedulePlanShowContract.md.
    
    Raises ValueError if plan not found or doesn't belong to channel.
    """
    plan = None
    
    # Try UUID first
    try:
        plan_uuid = uuid_module.UUID(plan_identifier)
        plan = (
            db.query(SchedulePlan)
            .filter(
                SchedulePlan.id == plan_uuid,
                SchedulePlan.channel_id == channel_id,
            )
            .first()
        )
        if plan:
            return plan
        # UUID exists but belongs to different channel
        other_plan = db.query(SchedulePlan).filter(SchedulePlan.id == plan_uuid).first()
        if other_plan:
            channel = db.query(Channel).filter(Channel.id == channel_id).first()
            channel_name = channel.slug if channel else str(channel_id)
            raise ValueError(
                f"Plan '{plan_identifier}' does not belong to channel '{channel_name}'"
            )
    except ValueError as e:
        # If it's our custom error, re-raise it
        if "does not belong" in str(e):
            raise
        # Otherwise, it's an invalid UUID format, continue to name lookup
        pass
    
    # Try name lookup (case-insensitive, trimmed)
    normalized_identifier = _normalize_plan_name(plan_identifier)
    matching_plans = (
        db.query(SchedulePlan)
        .filter(
            SchedulePlan.channel_id == channel_id,
            func.lower(func.trim(SchedulePlan.name)) == normalized_identifier.lower(),
        )
        .all()
    )
    
    if len(matching_plans) == 0:
        raise ValueError(f"Plan '{plan_identifier}' not found")
    elif len(matching_plans) == 1:
        return matching_plans[0]
    else:
        # Multiple matches (shouldn't happen due to constraint, but handle it)
        channel = db.query(Channel).filter(Channel.id == channel_id).first()
        channel_name = channel.slug if channel else str(channel_id)
        raise ValueError(
            f"Multiple plans match normalized name '{normalized_identifier}' in channel '{channel_name}'"
        )


def show_plan(
    db: Session,
    *,
    channel_identifier: str,
    plan_identifier: str,
    with_contents: bool = False,
    computed: bool = False,
) -> dict[str, Any]:
    """Show a SchedulePlan and return a contract-aligned dict.
    
    Implements SchedulePlanShowContract.md behavioral rules.
    
    Args:
        db: Database session
        channel_identifier: Channel UUID or slug
        plan_identifier: Plan UUID or name
        with_contents: Include lightweight summaries of Zones and Patterns
        computed: Include computed fields (effective_today, next_applicable_date)
    
    Returns:
        Dictionary with status and plan object matching contract output format
    
    Raises:
        ValueError: If channel or plan not found, or plan doesn't belong to channel
    """
    # B-1: Resolve channel
    channel = _resolve_channel(db, channel_identifier)
    
    # B-1: Resolve plan
    plan = _resolve_plan(db, channel.id, plan_identifier)
    
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
    
    result: dict[str, Any] = {
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
    
    # B-6: Add zones and patterns if requested
    if with_contents:
        # TODO: Implement when Zone and Pattern entities exist
        result["plan"]["zones"] = []
        result["plan"]["patterns"] = []
    
    # B-7: Add computed fields if requested
    if computed:
        # TODO: Implement computed fields (effective_today, next_applicable_date)
        # These require MasterClock and cron evaluation
        result["plan"]["effective_today"] = None
        result["plan"]["next_applicable_date"] = None
    
    return result


__all__ = ["show_plan", "_resolve_plan"]

