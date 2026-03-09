"""Explain why a particular program is airing at a given time.

Read-only introspection of Tier-1 editorial schedule for debugging.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from retrovue.domain.entities import (
    Channel,
    ChannelActiveRevision,
    ScheduleItem,
    ScheduleRevision,
)


def _broadcast_date_for(dt: datetime, day_start_hour: int = 6):
    from datetime import date
    if dt.hour < day_start_hour:
        return (dt - timedelta(days=1)).date()
    return dt.date()


def explain_at(
    db: Session,
    *,
    channel_slug: str,
    at: datetime,
) -> dict[str, Any]:
    """Return Tier-1 explanation for what is airing at the given time.

    Read-only — no database mutations.
    """
    channel = db.query(Channel).filter(Channel.slug == channel_slug).first()
    if channel is None:
        return {"error": f"Channel not found: {channel_slug}"}

    # Search across two broadcast days (day boundary handling)
    target_bd = _broadcast_date_for(at)
    revision = None
    for bd in (target_bd - timedelta(days=1), target_bd):
        pointer = (
            db.query(ChannelActiveRevision)
            .filter(
                ChannelActiveRevision.channel_id == channel.id,
                ChannelActiveRevision.broadcast_day == bd,
            )
            .first()
        )
        if pointer is not None:
            rev = (
                db.query(ScheduleRevision)
                .filter(ScheduleRevision.id == pointer.schedule_revision_id)
                .first()
            )
            if rev is not None:
                # Check if any item in this revision covers the target time
                item = _find_item_at(db, rev.id, at)
                if item is not None:
                    revision = rev
                    break

    if revision is None:
        # Fallback: try status='active' query
        for bd in (target_bd - timedelta(days=1), target_bd):
            rev = (
                db.query(ScheduleRevision)
                .filter(
                    ScheduleRevision.channel_id == channel.id,
                    ScheduleRevision.broadcast_day == bd,
                    ScheduleRevision.status == "active",
                )
                .first()
            )
            if rev is not None:
                item = _find_item_at(db, rev.id, at)
                if item is not None:
                    revision = rev
                    break

    if revision is None:
        return {
            "error": "No active revision found covering this time",
            "channel": channel_slug,
            "time": at.isoformat(),
        }

    item = _find_item_at(db, revision.id, at)
    if item is None:
        return {
            "error": "No ScheduleItem covers this time in the active revision",
            "channel": channel_slug,
            "time": at.isoformat(),
            "revision_id": str(revision.id),
        }

    meta = item.metadata_ or {}
    compiled_segments = meta.get("compiled_segments")
    slot_end = item.start_time + timedelta(seconds=item.duration_sec)

    result: dict[str, Any] = {
        "channel": channel_slug,
        "time": at.isoformat(),
        "tier1": {
            "revision_id": str(revision.id),
            "broadcast_day": str(revision.broadcast_day),
            "revision_status": revision.status,
            "revision_created_by": revision.created_by,
        },
        "schedule_item": {
            "slot_index": item.slot_index,
            "slot_start": item.start_time.isoformat(),
            "slot_end": slot_end.isoformat(),
            "duration_sec": item.duration_sec,
            "content_type": item.content_type,
            "asset_id": str(item.asset_id) if item.asset_id else None,
            "title": meta.get("title"),
        },
    }

    if compiled_segments:
        result["expansion_path"] = "compiled_segments"
        result["compiled_segments"] = compiled_segments
    else:
        result["expansion_path"] = "expand_program_block"
        result["block_info"] = {
            "asset_id_raw": meta.get("asset_id_raw"),
            "episode_duration_sec": meta.get("episode_duration_sec"),
            "selector": meta.get("selector"),
            "note": "Block will be expanded at runtime via Tier 2 playlog expander",
        }

    return result


def _find_item_at(db: Session, revision_id, at: datetime) -> ScheduleItem | None:
    """Find the ScheduleItem in a revision whose time range covers `at`."""
    items = (
        db.query(ScheduleItem)
        .filter(ScheduleItem.schedule_revision_id == revision_id)
        .order_by(ScheduleItem.slot_index.asc())
        .all()
    )
    for item in items:
        end_time = item.start_time + timedelta(seconds=item.duration_sec)
        if item.start_time <= at < end_time:
            return item
    return None
