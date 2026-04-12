"""Schedule listing and rescheduling operations.

Stage 4: program_schedule authority is ScheduleRevision + ScheduleItems.
"""

from __future__ import annotations

import uuid as uuid_module
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..domain.entities import PlaylistEvent, ScheduleItem, ScheduleRevision


class RescheduleRejectedError(ValueError):
    """Raised when a reschedule operation is rejected by the future guard."""


def _schedule_layer_filter(
    tier: str | None,
) -> tuple[bool, bool]:
    """Return (include_program_schedule, include_playlog_plan).

    Accepts ``\"1\"`` / ``\"2\"`` or ``program_schedule`` / ``playlog_plan``
    (alias: ``compiled_playlog``, deprecated).
    Unknown values include neither list (empty result for both).
    """
    if tier is None:
        return True, True
    t = str(tier).strip().lower().replace("-", "_")
    if t in ("1", "program_schedule"):
        return True, False
    if t in ("2", "playlog_plan", "compiled_playlog"):
        return False, True
    return False, False


def list_reschedulable(
    db: Session,
    *,
    now: datetime,
    channel_id: str | None = None,
    tier: str | None = None,
) -> dict[str, Any]:
    now_utc_ms = int(now.timestamp() * 1000)
    result: dict[str, Any] = {
        "status": "ok",
        "program_schedule": [],
        "playlog_plan": [],
    }

    inc_ps, inc_cpl = _schedule_layer_filter(tier)

    if inc_ps:
        q = db.query(ScheduleRevision).filter(ScheduleRevision.status == "active")
        if channel_id:
            q = q.join(ScheduleRevision.channel).filter_by(slug=channel_id)
        q = q.order_by(ScheduleRevision.broadcast_day)

        rows = []
        for rev in q.all():
            first_item = (
                db.query(ScheduleItem)
                .filter(ScheduleItem.schedule_revision_id == rev.id)
                .order_by(ScheduleItem.slot_index.asc())
                .first()
            )
            last_item = (
                db.query(ScheduleItem)
                .filter(ScheduleItem.schedule_revision_id == rev.id)
                .order_by(ScheduleItem.slot_index.desc())
                .first()
            )
            if not first_item or first_item.start_time <= now:
                continue
            range_start = first_item.start_time
            range_end = last_item.start_time.replace() if last_item else first_item.start_time
            if last_item:
                from datetime import timedelta

                range_end = last_item.start_time + timedelta(seconds=last_item.duration_sec)

            rows.append(
                {
                    "id": str(rev.id),
                    "channel_id": rev.channel.slug if rev.channel else "",
                    "broadcast_day": rev.broadcast_day.isoformat(),
                    "range_start": range_start.isoformat(),
                    "range_end": range_end.isoformat(),
                    "status": rev.status,
                }
            )
        result["program_schedule"] = rows

    if inc_cpl:
        query = db.query(PlaylistEvent).filter(PlaylistEvent.start_utc_ms > now_utc_ms)
        if channel_id:
            query = query.filter(PlaylistEvent.channel_slug == channel_id)
        query = query.order_by(PlaylistEvent.channel_slug, PlaylistEvent.start_utc_ms)
        result["playlog_plan"] = [
            {
                "block_id": row.block_id,
                "channel_slug": row.channel_slug,
                "broadcast_day": row.broadcast_day.isoformat(),
                "start_utc_ms": row.start_utc_ms,
                "end_utc_ms": row.end_utc_ms,
                "window_uuid": str(row.window_uuid) if row.window_uuid else None,
            }
            for row in query.all()
        ]

    return result


def reschedule_by_id(db: Session, *, identifier: str, now: datetime) -> dict[str, Any]:
    now_utc_ms = int(now.timestamp() * 1000)
    try:
        parsed_uuid = uuid_module.UUID(identifier)
    except ValueError:
        return _reschedule_playlog_plan(db, identifier, now_utc_ms=now_utc_ms)
    return _reschedule_program_schedule(db, parsed_uuid, now=now, now_utc_ms=now_utc_ms)


def _reschedule_program_schedule(
    db: Session,
    revision_id: uuid_module.UUID,
    *,
    now: datetime,
    now_utc_ms: int,
) -> dict[str, Any]:
    row = db.query(ScheduleRevision).filter(ScheduleRevision.id == revision_id).first()
    if row is None:
        raise ValueError(f"ScheduleRevision id={revision_id} not found.")

    first_item = (
        db.query(ScheduleItem)
        .filter(ScheduleItem.schedule_revision_id == row.id)
        .order_by(ScheduleItem.slot_index.asc())
        .first()
    )
    if first_item is None or first_item.start_time <= now:
        raise RescheduleRejectedError(
            "INV-RESCHEDULE-FUTURE-GUARD-001: revision is not fully in the future"
        )

    # Supersede current active revision
    row.status = "superseded"
    row.superseded_at = datetime.now(timezone.utc)

    # Create new active revision (copy items) for deterministic regeneration trigger
    new_rev = ScheduleRevision(
        channel_id=row.channel_id,
        broadcast_day=row.broadcast_day,
        status="active",
        activated_at=datetime.now(timezone.utc),
        created_by="schedule_reschedule",
        metadata_=row.metadata_ or {},
    )
    db.add(new_rev)
    db.flush()

    old_items = (
        db.query(ScheduleItem)
        .filter(ScheduleItem.schedule_revision_id == row.id)
        .order_by(ScheduleItem.slot_index.asc())
        .all()
    )
    for it in old_items:
        db.add(
            ScheduleItem(
                schedule_revision_id=new_rev.id,
                start_time=it.start_time,
                duration_sec=it.duration_sec,
                asset_id=it.asset_id,
                container_id=it.container_id,
                content_type=it.content_type,
                window_uuid=it.window_uuid,
                slot_index=it.slot_index,
                metadata_=it.metadata_ or {},
            )
        )

    channel_slug = row.channel.slug if row.channel else ""
    cpl_deleted = db.query(PlaylistEvent).filter(
        PlaylistEvent.channel_slug == channel_slug,
        PlaylistEvent.broadcast_day == row.broadcast_day,
        PlaylistEvent.start_utc_ms > now_utc_ms,
    ).delete(synchronize_session=False)

    return {
        "status": "ok",
        "layer": "program_schedule",
        "id": str(revision_id),
        "channel_id": channel_slug,
        "broadcast_day": row.broadcast_day.isoformat(),
        "deleted_program_schedule": 0,
        "deleted_playlog_plan": cpl_deleted,
    }


def _reschedule_playlog_plan(db: Session, block_id: str, *, now_utc_ms: int) -> dict[str, Any]:
    row = db.query(PlaylistEvent).filter(PlaylistEvent.block_id == block_id).first()
    if row is None:
        raise ValueError(f"PlaylistEvent block_id={block_id!r} not found.")
    if row.start_utc_ms <= now_utc_ms:
        raise RescheduleRejectedError(
            f"INV-RESCHEDULE-FUTURE-GUARD-001: PlaylistEvent block_id={block_id!r} is not in the future"
        )
    db.delete(row)
    return {
        "status": "ok",
        "layer": "playlog_plan",
        "block_id": block_id,
        "channel_slug": row.channel_slug,
        "broadcast_day": row.broadcast_day.isoformat(),
        "deleted_program_schedule": 0,
        "deleted_playlog_plan": 1,
    }


__all__ = ["RescheduleRejectedError", "list_reschedulable", "reschedule_by_id"]
