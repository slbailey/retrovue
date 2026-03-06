"""Stage 3 reader: Tier-1 editorial rows -> segmented block dicts for PlaylistBuilder.

Reads active ScheduleRevision + ordered ScheduleItems and converts them into the
same serialized ScheduledBlock dict structure previously sourced from
ProgramLogDay.program_log_json["segmented_blocks"].
"""

from __future__ import annotations

from datetime import date
from typing import Any

from retrovue.domain.entities import (
    Channel,
    ChannelActiveRevision,
    ScheduleItem,
    ScheduleRevision,
)
from retrovue.runtime.catalog_resolver import CatalogAssetResolver
from retrovue.runtime.playout_log_expander import expand_program_block
from retrovue.runtime.dsl_schedule_service import _serialize_scheduled_block


def load_segmented_blocks_from_active_revision(
    db,
    *,
    channel_slug: str,
    broadcast_day: date,
) -> list[dict[str, Any]] | None:
    """Return serialized segmented blocks for active revision, or None if missing."""
    channel = db.query(Channel).filter(Channel.slug == channel_slug).first()
    if channel is None:
        return None

    pointer = (
        db.query(ChannelActiveRevision)
        .filter(
            ChannelActiveRevision.channel_id == channel.id,
            ChannelActiveRevision.broadcast_day == broadcast_day,
        )
        .first()
    )

    revision = None
    if pointer is not None:
        revision = (
            db.query(ScheduleRevision)
            .filter(ScheduleRevision.id == pointer.schedule_revision_id)
            .first()
        )

    if revision is None:
        revision = (
            db.query(ScheduleRevision)
            .filter(
                ScheduleRevision.channel_id == channel.id,
                ScheduleRevision.broadcast_day == broadcast_day,
                ScheduleRevision.status == "active",
            )
            .first()
        )
    if revision is None:
        return None

    items = (
        db.query(ScheduleItem)
        .filter(ScheduleItem.schedule_revision_id == revision.id)
        .order_by(ScheduleItem.slot_index.asc())
        .all()
    )

    resolver = CatalogAssetResolver(db)
    out: list[dict[str, Any]] = []

    for item in items:
        meta = item.metadata_ or {}
        raw_asset_id = (
            meta.get("asset_id_raw")
            or (str(item.asset_id) if item.asset_id else None)
            or ""
        )

        if not raw_asset_id:
            # Keep behavior safe; skip invalid rows and let fallback path handle if needed.
            continue

        asset_meta = resolver.lookup(raw_asset_id)
        chapter_ms = None
        if asset_meta.chapter_markers_sec:
            chapter_ms = tuple(int(c * 1000) for c in asset_meta.chapter_markers_sec if c > 0)

        start_utc_ms = int(item.start_time.timestamp() * 1000)
        slot_duration_ms = int(item.duration_sec) * 1000
        episode_duration_ms = int(meta.get("episode_duration_sec") or item.duration_sec) * 1000

        channel_type = "movie" if item.content_type == "movie" else "network"

        expanded = expand_program_block(
            asset_id=raw_asset_id,
            asset_uri=asset_meta.file_uri or "",
            start_utc_ms=start_utc_ms,
            slot_duration_ms=slot_duration_ms,
            episode_duration_ms=episode_duration_ms,
            chapter_markers_ms=chapter_ms,
            channel_type=channel_type,
            gain_db=asset_meta.loudness_gain_db,
        )

        d = _serialize_scheduled_block(expanded)
        if item.window_uuid is not None:
            d["window_uuid"] = str(item.window_uuid)
        out.append(d)

    return out
