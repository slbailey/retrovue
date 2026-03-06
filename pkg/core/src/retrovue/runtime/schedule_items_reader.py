"""Stage 3 reader: Tier-1 editorial rows -> segmented block dicts for PlaylistBuilder.

Reads active ScheduleRevision + ordered ScheduleItems and converts them into the
same serialized ScheduledBlock dict structure previously sourced from
ProgramLogDay.program_log_json["segmented_blocks"].

INV-TEMPLATE-BLOCKS-COMPILE-TO-EXPLICIT-SEGMENTS:
When a ScheduleItem carries compiled_segments in metadata_, the reader
hydrates the ScheduledBlock directly from that structure, bypassing
expand_program_block(). This preserves template-defined segment order
(e.g. intro + movie) without runtime editorial reconstruction.
"""

from __future__ import annotations

import hashlib
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
from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment
from retrovue.runtime.dsl_schedule_service import _serialize_scheduled_block


def _hydrate_compiled_segments(
    *,
    compiled_segments: list[dict[str, Any]],
    asset_id: str,
    start_utc_ms: int,
    slot_duration_ms: int,
) -> ScheduledBlock:
    """Build a ScheduledBlock from pre-compiled template segments.

    INV-TEMPLATE-BLOCKS-COMPILE-TO-EXPLICIT-SEGMENTS:
    Template-defined segments are authoritative. Runtime must not reshape
    them. Post-content filler is appended only as slot completion behavior.
    """
    segments: list[ScheduledSegment] = []
    content_total_ms = 0

    for cs in compiled_segments:
        segments.append(ScheduledSegment(
            segment_type=cs["segment_type"],
            asset_uri=cs["asset_uri"],
            asset_start_offset_ms=cs.get("asset_start_offset_ms", 0),
            segment_duration_ms=cs["segment_duration_ms"],
            gain_db=cs.get("gain_db", 0.0),
        ))
        content_total_ms += cs["segment_duration_ms"]

    # Post-content filler for remaining slot time (slot completion, not editorial)
    remaining_ms = max(0, slot_duration_ms - content_total_ms)
    if remaining_ms > 0:
        segments.append(ScheduledSegment(
            segment_type="filler",
            asset_uri="",
            asset_start_offset_ms=0,
            segment_duration_ms=remaining_ms,
        ))

    end_utc_ms = start_utc_ms + slot_duration_ms
    raw = f"{asset_id}:{start_utc_ms}"
    block_id = f"blk-{hashlib.sha256(raw.encode()).hexdigest()[:12]}"

    return ScheduledBlock(
        block_id=block_id,
        start_utc_ms=start_utc_ms,
        end_utc_ms=end_utc_ms,
        segments=tuple(segments),
    )


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
            continue

        start_utc_ms = int(item.start_time.timestamp() * 1000)
        slot_duration_ms = int(item.duration_sec) * 1000

        # INV-TEMPLATE-BLOCKS-COMPILE-TO-EXPLICIT-SEGMENTS:
        # Template-derived blocks carry compiled_segments — use them directly
        # instead of heuristic expansion via expand_program_block().
        compiled_segments = meta.get("compiled_segments")
        if compiled_segments:
            expanded = _hydrate_compiled_segments(
                compiled_segments=compiled_segments,
                asset_id=raw_asset_id,
                start_utc_ms=start_utc_ms,
                slot_duration_ms=slot_duration_ms,
            )
        else:
            # Legacy path: heuristic expansion for non-template items
            asset_meta = resolver.lookup(raw_asset_id)
            chapter_ms = None
            if asset_meta.chapter_markers_sec:
                chapter_ms = tuple(int(c * 1000) for c in asset_meta.chapter_markers_sec if c > 0)

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
