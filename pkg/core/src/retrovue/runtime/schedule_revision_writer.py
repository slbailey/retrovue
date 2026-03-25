"""Helpers for writing ScheduleRevision + ScheduleItem from compiler output.

Stage 2 dual-write authority:
- Legacy ProgramLogDay storage may still exist during migration, but is non-authoritative.
- Relational schedule rows are written from the SAME compiler output object.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import logging
import uuid as uuid_mod
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert

from retrovue.domain.entities import (
    Channel,
    ChannelActiveRevision,
    ScheduleItem,
    ScheduleRevision,
)
from retrovue.runtime.clock import MasterClock

logger = logging.getLogger(__name__)

# LAW-CLOCK: Single time authority for all scheduling decisions.
# Module-level instance — stateless, equivalent to datetime.now(UTC)
# in production but conformant with the MasterClock protocol.
_clock = MasterClock()


def _parse_uuid(value: Any) -> uuid_mod.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid_mod.UUID):
        return value
    if isinstance(value, str):
        try:
            return uuid_mod.UUID(value)
        except ValueError:
            return None
    return None


def _infer_content_type(block: dict[str, Any]) -> str:
    """Infer ScheduleItem.content_type from V2 compiler block metadata.

    V2 blocks carry a selector dict with fill_mode. Long-form single-asset
    programs (fill_mode=single with episode_duration > 1h) are movies.
    Selector rating filters also indicate movie content.

    Unknowns default to "episode".
    """
    selector = block.get("selector")
    if isinstance(selector, dict):
        if any(k in selector for k in ("rating_include", "rating_exclude", "max_duration_sec")):
            return "movie"

    # Long-form content heuristic: episode_duration > 1 hour = movie
    ep_dur = block.get("episode_duration_sec", 0)
    if ep_dur and ep_dur > 3600:
        return "movie"

    title = str(block.get("title") or "").lower()
    if "movie" in title:
        return "movie"
    if "filler" in title:
        return "filler"
    if "bumper" in title:
        return "bumper"
    if "promo" in title:
        return "promo"
    if "station" in title and "id" in title:
        return "station_id"
    return "episode"


def write_active_revision_from_compiled_schedule(
    db,
    *,
    channel_slug: str,
    broadcast_day: date,
    schedule: dict[str, Any],
    created_by: str = "dsl_schedule_service",
) -> bool:
    """Write relational schedule rows from compiled schedule output.

    INV-TIMELINE-BOUNDARY-IMMUTABLE-001: The wall-clock time at invocation
    defines an immutable boundary.  If an active revision exists and
    contains ANY ScheduleItem with start_time before the boundary, the
    write is refused — those items represent committed (past or in-flight)
    timeline that MUST NOT be modified.

    INV-TIMELINE-APPEND-ONLY-001: A revision whose items are ALL in the
    future (start_time >= boundary) MAY be superseded — the timeline for
    that day has not yet committed to the viewer.

    Lifecycle (when write is permitted):
      1) supersede existing future-only revision (if any)
      2) insert new active ScheduleRevision
      3) insert deterministic ScheduleItems
      4) upsert ChannelActiveRevision pointer

    Returns True when relational rows were written, False when the write
    was skipped.
    """
    channel = db.query(Channel).filter(Channel.slug == channel_slug).first()
    if channel is None:
        logger.warning(
            "ScheduleRevision dual-write skipped: unknown channel slug=%s",
            channel_slug,
        )
        return False

    # INV-TIMELINE-BOUNDARY-IMMUTABLE-001: Capture the immutable boundary
    # at the moment this write is attempted.  Everything before this time
    # is committed history.
    # LAW-CLOCK: MasterClock is the single time authority.
    boundary = _clock.now_utc()

    # INV-TIMELINE-BOUNDARY-IMMUTABLE-001: Check whether the existing
    # active revision (if any) has committed items.
    existing_active = db.query(ScheduleRevision).filter(
        ScheduleRevision.channel_id == channel.id,
        ScheduleRevision.broadcast_day == broadcast_day,
        ScheduleRevision.status == "active",
    ).first()

    if existing_active is not None:
        has_committed = db.query(ScheduleItem).filter(
            ScheduleItem.schedule_revision_id == existing_active.id,
            ScheduleItem.start_time < boundary,
        ).first()

        if has_committed is not None:
            logger.info(
                "INV-TIMELINE-BOUNDARY-IMMUTABLE-001: refusing to modify "
                "committed timeline — revision %s for %s/%s has items "
                "before boundary %s (created_by=%s, activated_at=%s)",
                existing_active.id,
                channel_slug,
                broadcast_day,
                boundary.isoformat(),
                existing_active.created_by,
                existing_active.activated_at,
            )
            return False

    # Supersede ALL active revisions for this channel+day via bulk update.
    # This is idempotent — if none exist, zero rows are affected.
    db.query(ScheduleRevision).filter(
        ScheduleRevision.channel_id == channel.id,
        ScheduleRevision.broadcast_day == broadcast_day,
        ScheduleRevision.status == "active",
    ).update(
        {"status": "superseded", "superseded_at": boundary},
        synchronize_session=False,
    )
    db.flush()

    now = _clock.now_utc()

    revision = ScheduleRevision(
        channel_id=channel.id,
        broadcast_day=broadcast_day,
        status="active",
        activated_at=now,
        created_by=created_by,
        metadata_={
            "source": schedule.get("source"),
            "hash": schedule.get("hash"),
            "version": schedule.get("version"),
        },
    )
    db.add(revision)
    db.flush()  # acquire revision.id for FK rows

    blocks = schedule.get("program_blocks", [])
    for slot_index, block in enumerate(blocks):
        start_at = datetime.fromisoformat(block["start_at"])
        item = ScheduleItem(
            schedule_revision_id=revision.id,
            start_time=start_at,
            duration_sec=int(block["slot_duration_sec"]),
            asset_id=_parse_uuid(block.get("asset_id")),
            container_id=_parse_uuid(block.get("collection")),
            content_type=_infer_content_type(block),
            window_uuid=_parse_uuid(block.get("window_uuid")),
            slot_index=slot_index,
            metadata_={
                "title": block.get("title"),
                "asset_id_raw": block.get("asset_id"),
                "collection_raw": block.get("collection"),
                "selector": block.get("selector"),
                "episode_duration_sec": block.get("episode_duration_sec"),
                "compiled_segments": block.get("compiled_segments"),
            },
        )
        db.add(item)

    upsert_stmt = pg_insert(ChannelActiveRevision.__table__).values(
        channel_id=channel.id,
        broadcast_day=broadcast_day,
        schedule_revision_id=revision.id,
        updated_at=now,
    ).on_conflict_do_update(
        index_elements=["channel_id", "broadcast_day"],
        set_={
            "schedule_revision_id": revision.id,
            "updated_at": now,
        },
    )
    db.execute(upsert_stmt)

    return True
