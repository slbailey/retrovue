"""Stage 3 reader: Tier-1 editorial rows -> segmented block dicts for PlaylistBuilder.

Reads active ScheduleRevision + ordered ScheduleItems and converts them into the
same serialized ScheduledBlock dict structure previously sourced from
ProgramLogDay.program_log_json["segmented_blocks"].

V2 compiled_segments schema (canonical, stored in ScheduleItem.metadata_):
    {"segment_type": str, "asset_id": str, "duration_ms": int}

During hydration, asset_id is resolved to file URIs via CatalogAssetResolver.
V1 segment fields (asset_uri, segment_duration_ms) are rejected at hydration
time — their presence indicates stale data that must be purged and recompiled.
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
from retrovue.runtime.schedule_compiler import CompileError
from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment
from retrovue.runtime.dsl_schedule_service import (
    _deserialize_scheduled_block,
    _serialize_scheduled_block,
)
from retrovue.runtime.traffic_manager import fill_ad_blocks


def expand_editorial_block(
    sb_dict: dict[str, Any],
    *,
    filler_uri: str,
    filler_duration_ms: int,
    asset_library: Any = None,
    policy: Any = None,
    break_config: Any = None,
) -> ScheduledBlock:
    """Canonical Tier-1 → Tier-2 block expansion pipeline.

    Deserializes a serialized block dict (as produced by
    load_segmented_blocks_from_active_revision) and applies traffic
    fill to produce a playout-ready ScheduledBlock.

    INV-MOVIE-REBUILD-EQUIVALENCE: This is the single expansion function
    that both the horizon daemon and schedule rebuild MUST use. No caller
    may substitute its own deserialization or traffic insertion logic.

    Pipeline:
        serialized block dict → ScheduledBlock → fill_ad_blocks → ScheduledBlock
    """
    scheduled_block = _deserialize_scheduled_block(sb_dict)
    return fill_ad_blocks(
        scheduled_block,
        filler_uri=filler_uri,
        filler_duration_ms=filler_duration_ms,
        asset_library=asset_library,
        policy=policy,
        break_config=break_config,
    )


def _hydrate_compiled_segments(
    *,
    compiled_segments: list[dict[str, Any]],
    asset_id: str,
    start_utc_ms: int,
    slot_duration_ms: int,
    resolver: CatalogAssetResolver | None = None,
) -> ScheduledBlock:
    """Build a ScheduledBlock from V2 compiled segments.

    V2 compiled_segments schema (canonical):
        {"segment_type": str, "asset_id": str, "duration_ms": int}

    During hydration, asset_id is resolved to a file URI via the
    CatalogAssetResolver. V1 segment fields (asset_uri, segment_duration_ms)
    are rejected — their presence indicates stale V1 data that must be purged.
    """
    segments: list[ScheduledSegment] = []
    content_total_ms = 0

    for cs in compiled_segments:
        # Guard: reject V1 segment schema fields
        if "asset_uri" in cs or "segment_duration_ms" in cs:
            v1_keys = [k for k in ("asset_uri", "segment_duration_ms") if k in cs]
            raise CompileError(
                f"V1 segment schema detected in compiled_segments: "
                f"found keys {v1_keys}. V1 segment fields are no longer supported. "
                f"Purge stale schedule data and recompile."
            )

        dur_ms = int(cs["duration_ms"])
        seg_asset_id = cs.get("asset_id", "")

        # Resolve asset_id → file URI via catalog
        asset_uri = ""
        if seg_asset_id and resolver is not None:
            meta = resolver.lookup(seg_asset_id)
            asset_uri = meta.file_uri or ""

        segments.append(ScheduledSegment(
            segment_type=cs["segment_type"],
            asset_uri=asset_uri,
            asset_start_offset_ms=0,
            segment_duration_ms=dur_ms,
        ))
        content_total_ms += dur_ms

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
        # Template-derived blocks carry compiled_segments.
        compiled_segments = meta.get("compiled_segments")
        if compiled_segments:
            # INV-BREAK-V2-SINGLE-CHAPTER-001: single-content blocks without
            # intro/outro wrappers MUST route through expand_program_block()
            # so chapter markers from the catalog produce mid-content breaks
            # via the dedicated break detection stage (INV-BREAK-008).
            content_segs = [
                s for s in compiled_segments if s.get("segment_type") == "content"
            ]
            structural_segs = [
                s for s in compiled_segments
                if s.get("segment_type") in ("intro", "outro", "presentation")
            ]

            if len(content_segs) == 1 and not structural_segs:
                cs = content_segs[0]
                seg_asset_id = cs.get("asset_id", raw_asset_id)
                asset_meta = resolver.lookup(seg_asset_id)

                chapter_ms = None
                if asset_meta.chapter_markers_sec:
                    chapter_ms = tuple(
                        int(c * 1000)
                        for c in asset_meta.chapter_markers_sec
                        if c > 0
                    )

                channel_type = "movie" if item.content_type == "movie" else "network"

                expanded = expand_program_block(
                    asset_id=seg_asset_id,
                    asset_uri=asset_meta.file_uri or "",
                    start_utc_ms=start_utc_ms,
                    slot_duration_ms=slot_duration_ms,
                    episode_duration_ms=int(cs["duration_ms"]),
                    chapter_markers_ms=chapter_ms,
                    channel_type=channel_type,
                    gain_db=asset_meta.loudness_gain_db,
                )
            else:
                # Multi-segment blocks (accumulate, intro/outro): the segment
                # structure itself defines break opportunities (INV-BREAK-004).
                expanded = _hydrate_compiled_segments(
                    compiled_segments=compiled_segments,
                    asset_id=raw_asset_id,
                    start_utc_ms=start_utc_ms,
                    slot_duration_ms=slot_duration_ms,
                    resolver=resolver,
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
