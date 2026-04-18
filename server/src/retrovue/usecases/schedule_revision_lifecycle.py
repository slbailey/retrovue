"""ScheduleRevision REST lifecycle operations.

Service layer for operator-facing revision management:
create draft, publish, list, and get.

Contract: docs/contracts/schedule_revision_lifecycle.md
Invariants: INV-SCHEDULEREVISION-IMMUTABLE-001, INV-PERSISTENCE-GUARD-NONEMPTY-001
"""

from __future__ import annotations

import uuid as uuid_mod
from datetime import date, datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from retrovue.domain.entities import (
    Channel,
    ChannelActiveRevision,
    ScheduleItem,
    ScheduleRevision,
)


# ---------------------------------------------------------------------------
# Domain errors
# ---------------------------------------------------------------------------

class RevisionNotFoundError(Exception):
    pass


class RevisionNotDraftError(Exception):
    pass


class RevisionEmptyError(Exception):
    pass


class ChannelNotFoundError(Exception):
    pass


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------

def create_draft_revision(
    db: Session,
    *,
    channel_id: uuid_mod.UUID,
    broadcast_day: date,
    items: list[dict[str, Any]],
    created_by: str | None = None,
) -> ScheduleRevision:
    """Create a draft revision with items.

    INV-PERSISTENCE-GUARD-NONEMPTY-001: Rejects empty item lists.
    """
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if channel is None:
        raise ChannelNotFoundError(f"Channel {channel_id} not found")

    if not items:
        raise RevisionEmptyError("Revision must have at least one item")

    revision = ScheduleRevision(
        channel_id=channel_id,
        broadcast_day=broadcast_day,
        status="draft",
        created_by=created_by,
    )
    db.add(revision)
    db.flush()

    for slot_index, item_data in enumerate(items):
        start_time = item_data["start_time"]
        if isinstance(start_time, str):
            start_time = datetime.fromisoformat(start_time)

        asset_id = item_data.get("asset_id")
        if isinstance(asset_id, str):
            try:
                asset_id = uuid_mod.UUID(asset_id)
            except ValueError:
                asset_id = None

        item = ScheduleItem(
            schedule_revision_id=revision.id,
            start_time=start_time,
            duration_sec=int(item_data["duration_sec"]),
            asset_id=asset_id,
            content_type=item_data.get("content_type", "episode"),
            slot_index=slot_index,
            metadata_=item_data.get("metadata"),
        )
        db.add(item)

    db.flush()
    db.refresh(revision)
    return revision


def publish_revision(
    db: Session,
    *,
    revision_id: uuid_mod.UUID,
    now: datetime,
) -> ScheduleRevision:
    """Publish a draft revision: draft → active with atomic supersession.

    INV-SCHEDULEREVISION-IMMUTABLE-001: Active revisions are immutable.
    INV-PERSISTENCE-GUARD-NONEMPTY-001: Empty revisions cannot be published.
    """
    revision = db.query(ScheduleRevision).filter(
        ScheduleRevision.id == revision_id,
    ).first()

    if revision is None:
        raise RevisionNotFoundError(f"Revision {revision_id} not found")

    if revision.status != "draft":
        raise RevisionNotDraftError(
            f"Revision {revision_id} is '{revision.status}', not 'draft'"
        )

    item_count = db.query(ScheduleItem).filter(
        ScheduleItem.schedule_revision_id == revision_id,
    ).count()

    if item_count == 0:
        raise RevisionEmptyError(
            f"Revision {revision_id} has no items — cannot publish empty revision"
        )

    # Supersede existing active revisions for same channel+day
    db.query(ScheduleRevision).filter(
        ScheduleRevision.channel_id == revision.channel_id,
        ScheduleRevision.broadcast_day == revision.broadcast_day,
        ScheduleRevision.status == "active",
    ).update(
        {"status": "superseded", "superseded_at": now},
        synchronize_session="fetch",
    )

    # Activate this revision
    revision.status = "active"
    revision.activated_at = now
    db.flush()

    # Upsert ChannelActiveRevision pointer
    # Use raw SQL for SQLite compatibility in tests (no pg_insert)
    existing_pointer = db.query(ChannelActiveRevision).filter(
        ChannelActiveRevision.channel_id == revision.channel_id,
        ChannelActiveRevision.broadcast_day == revision.broadcast_day,
    ).first()

    if existing_pointer is not None:
        existing_pointer.schedule_revision_id = revision.id
    else:
        pointer = ChannelActiveRevision(
            channel_id=revision.channel_id,
            broadcast_day=revision.broadcast_day,
            schedule_revision_id=revision.id,
        )
        db.add(pointer)

    db.flush()
    db.refresh(revision)
    return revision


def list_revisions(
    db: Session,
    *,
    channel_id: uuid_mod.UUID,
    broadcast_day: date | None = None,
    status: str | None = None,
) -> list[ScheduleRevision]:
    """List revisions for a channel with optional filters."""
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if channel is None:
        raise ChannelNotFoundError(f"Channel {channel_id} not found")

    query = db.query(ScheduleRevision).filter(
        ScheduleRevision.channel_id == channel_id,
    )

    if broadcast_day is not None:
        query = query.filter(ScheduleRevision.broadcast_day == broadcast_day)

    if status is not None:
        query = query.filter(ScheduleRevision.status == status)

    return query.order_by(ScheduleRevision.created_at.desc()).all()


def get_revision(
    db: Session,
    *,
    revision_id: uuid_mod.UUID,
) -> ScheduleRevision:
    """Get a single revision with its items."""
    revision = db.query(ScheduleRevision).filter(
        ScheduleRevision.id == revision_id,
    ).first()

    if revision is None:
        raise RevisionNotFoundError(f"Revision {revision_id} not found")

    return revision
