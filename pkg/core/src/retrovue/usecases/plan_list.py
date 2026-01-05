from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..domain.entities import SchedulePlan
from .plan_add import _resolve_channel


def list_plans(
    db: Session,
    *,
    channel_identifier: str,
) -> dict[str, Any]:
    """List all SchedulePlans for a channel and return a contract-aligned dict.
    
    Implements SchedulePlanListContract.md behavioral rules.
    
    Args:
        db: Database session
        channel_identifier: Channel UUID or slug
    
    Returns:
        Dictionary with status, total, and plans array matching contract output format
    
    Raises:
        ValueError: If channel not found
    """
    # B-1: Resolve channel
    channel = _resolve_channel(db, channel_identifier)
    
    # B-3: Query plans with deterministic sorting
    # Sort by: priority (desc), name (case-insensitive asc), created_at (asc), id (asc)
    plans = (
        db.query(SchedulePlan)
        .filter(SchedulePlan.channel_id == channel.id)
        .order_by(
            SchedulePlan.priority.desc(),
            func.lower(SchedulePlan.name).asc(),
            SchedulePlan.created_at.asc(),
            SchedulePlan.id.asc(),
        )
        .all()
    )
    
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
    
    plan_dicts = [
        {
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
        for plan in plans
    ]
    
    return {
        "status": "ok",
        "total": len(plan_dicts),
        "plans": plan_dicts,
    }


__all__ = ["list_plans"]

