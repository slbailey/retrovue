from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .plan_add import _resolve_channel
from .plan_show import _resolve_plan


def delete_plan(
    db: Session,
    *,
    channel_identifier: str,
    plan_identifier: str,
) -> dict[str, Any]:
    """Delete a SchedulePlan and return a contract-aligned dict.
    
    Implements SchedulePlanDeleteContract.md behavioral rules.
    
    Args:
        db: Database session
        channel_identifier: Channel UUID or slug
        plan_identifier: Plan UUID or name
    
    Returns:
        Dictionary with status, deleted count, and id matching contract output format
    
    Raises:
        ValueError: If channel or plan not found, plan doesn't belong to channel, or dependencies exist
    """
    # B-1: Resolve channel
    channel = _resolve_channel(db, channel_identifier)
    
    # B-1: Resolve plan
    plan = _resolve_plan(db, channel.id, plan_identifier)
    
    # B-2: Check dependencies
    # TODO: Implement dependency checks when Zone, Pattern, and ScheduleDay entities exist
    # For now, we'll skip the dependency checks and allow deletion
    # When implemented, check:
    # - Zones: db.query(Zone).filter(Zone.plan_id == plan.id).count()
    # - Patterns: db.query(Pattern).filter(Pattern.plan_id == plan.id).count()
    # - ScheduleDays: db.query(ScheduleDay).filter(ScheduleDay.plan_id == plan.id).count()
    
    plan_id = str(plan.id)
    
    # Delete plan
    db.delete(plan)
    db.commit()
    
    return {
        "status": "ok",
        "deleted": 1,
        "id": plan_id,
    }


__all__ = ["delete_plan"]

