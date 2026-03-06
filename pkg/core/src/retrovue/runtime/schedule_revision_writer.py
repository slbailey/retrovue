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

logger = logging.getLogger(__name__)


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
    """Infer ScheduleItem.content_type from compiler block metadata.

    INV-TEMPLATE-BLOCKS-COMPILE-TO-EXPLICIT-SEGMENTS:
    When compiled_segments is present (template-derived block), derive
    content_type from the primary segment's source type. This eliminates
    dependence on title heuristics for template blocks.

    Keep this conservative for legacy blocks; unknowns default to "episode".
    """
    # Template-derived blocks: derive from compiled_segments primary source
    compiled_segs = block.get("compiled_segments")
    if compiled_segs:
        for seg in compiled_segs:
            if seg.get("is_primary"):
                if seg.get("source_type") == "pool":
                    return "movie"
                return "episode"

    selector = block.get("selector")
    if isinstance(selector, dict):
        # movie selector paths include duration/rating-oriented filters in practice
        if any(k in selector for k in ("rating_include", "rating_exclude", "max_duration_sec")):
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

    Lifecycle (atomic within caller transaction):
      1) supersede existing active revision for (channel_slug, broadcast_day)
      2) insert new active ScheduleRevision
      3) insert deterministic ScheduleItems from enumerate(program_blocks)

    Returns True when relational rows were written, False when channel is
    unknown and write is skipped for backward compatibility.
    """
    channel = db.query(Channel).filter(Channel.slug == channel_slug).first()
    if channel is None:
        logger.warning(
            "ScheduleRevision dual-write skipped: unknown channel slug=%s",
            channel_slug,
        )
        return False

    now = datetime.now(timezone.utc)

    db.query(ScheduleRevision).filter(
        ScheduleRevision.channel_id == channel.id,
        ScheduleRevision.broadcast_day == broadcast_day,
        ScheduleRevision.status == "active",
    ).update(
        {
            ScheduleRevision.status: "superseded",
            ScheduleRevision.superseded_at: now,
        },
        synchronize_session=False,
    )

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
            collection_id=_parse_uuid(block.get("collection")),
            content_type=_infer_content_type(block),
            window_uuid=_parse_uuid(block.get("window_uuid")),
            slot_index=slot_index,
            metadata_={
                "title": block.get("title"),
                "asset_id_raw": block.get("asset_id"),
                "collection_raw": block.get("collection"),
                "selector": block.get("selector"),
                "episode_duration_sec": block.get("episode_duration_sec"),
                "template_id": block.get("template_id"),
                "epg_title": block.get("epg_title"),
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
