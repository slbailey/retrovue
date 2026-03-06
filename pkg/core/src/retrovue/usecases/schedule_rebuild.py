"""Tier-2 schedule rebuild operations.

Rebuilds Tier-2 (PlaylistEvent) segmented blocks from Tier-1
(ScheduleRevision/ScheduleItems) without modifying editorial data.

Used after logic fixes (e.g. template segment compilation) to regenerate
playout-ready blocks while preserving the Tier-1 editorial schedule.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from retrovue.domain.entities import PlaylistEvent
from retrovue.runtime.dsl_schedule_service import _deserialize_scheduled_block
from retrovue.runtime.schedule_items_reader import (
    load_segmented_blocks_from_active_revision,
)
from retrovue.runtime.traffic_manager import fill_ad_blocks

logger = logging.getLogger(__name__)


@dataclass
class RebuildResult:
    """Result of a Tier-2 rebuild operation."""
    channel_slug: str
    start_utc_ms: int
    end_utc_ms: int
    deleted: int
    rebuilt: int
    errors: list[str] = field(default_factory=list)
    live_safe_skipped: bool = False


def _get_currently_playing_block(
    db: Session,
    channel_slug: str,
    now_ms: int,
) -> dict[str, int] | None:
    """Return start/end of the PlaylistEvent covering now_ms, or None."""
    row = (
        db.query(PlaylistEvent)
        .filter(
            PlaylistEvent.channel_slug == channel_slug,
            PlaylistEvent.start_utc_ms <= now_ms,
            PlaylistEvent.end_utc_ms > now_ms,
        )
        .first()
    )
    if row is None:
        return None
    return {"start_utc_ms": row.start_utc_ms, "end_utc_ms": row.end_utc_ms}


def _broadcast_date_for(dt: datetime, day_start_hour: int = 6) -> date:
    """Compute broadcast day (UTC-based, configurable day start)."""
    if dt.hour < day_start_hour:
        return (dt - timedelta(days=1)).date()
    return dt.date()


def rebuild_tier2(
    db: Session,
    *,
    channel_slug: str,
    start_utc_ms: int,
    end_utc_ms: int,
    filler_uri: str = "/opt/retrovue/assets/filler.mp4",
    filler_duration_ms: int = 3_650_000,
    live_safe: bool = False,
    dry_run: bool = False,
) -> RebuildResult:
    """Rebuild Tier-2 PlaylistEvent rows in a time window.

    Steps:
      1. Optionally shift start past currently-playing block (--live-safe)
      2. Delete PlaylistEvent rows in [start, end)
      3. Load Tier-1 blocks via load_segmented_blocks_from_active_revision
      4. Deserialize, fill ads, write back as PlaylistEvent

    Does NOT modify Tier-1 ScheduleItems.
    """
    result = RebuildResult(
        channel_slug=channel_slug,
        start_utc_ms=start_utc_ms,
        end_utc_ms=end_utc_ms,
        deleted=0,
        rebuilt=0,
    )

    # Step 1: live-safe — shift start past currently playing block
    if live_safe:
        playing = _get_currently_playing_block(db, channel_slug, start_utc_ms)
        if playing and start_utc_ms >= playing["start_utc_ms"] and start_utc_ms < playing["end_utc_ms"]:
            result.start_utc_ms = playing["end_utc_ms"]
            result.live_safe_skipped = True
            start_utc_ms = result.start_utc_ms
            logger.info(
                "rebuild_tier2[%s]: live-safe shifted start to %d (end of playing block)",
                channel_slug, start_utc_ms,
            )

    if start_utc_ms >= end_utc_ms:
        return result

    if dry_run:
        # Count what would be deleted
        result.deleted = db.query(PlaylistEvent).filter(
            PlaylistEvent.channel_slug == channel_slug,
            PlaylistEvent.start_utc_ms >= start_utc_ms,
            PlaylistEvent.start_utc_ms < end_utc_ms,
        ).count()
        return result

    # Step 2: delete existing Tier-2 rows in window
    result.deleted = db.query(PlaylistEvent).filter(
        PlaylistEvent.channel_slug == channel_slug,
        PlaylistEvent.start_utc_ms >= start_utc_ms,
        PlaylistEvent.start_utc_ms < end_utc_ms,
    ).delete(synchronize_session=False)

    # Step 3: determine broadcast days to scan
    start_dt = datetime.fromtimestamp(start_utc_ms / 1000, tz=timezone.utc)
    end_dt = datetime.fromtimestamp(end_utc_ms / 1000, tz=timezone.utc)
    scan_date = _broadcast_date_for(start_dt) - timedelta(days=1)
    end_date = _broadcast_date_for(end_dt) + timedelta(days=1)

    # Step 4: load Tier-1, rebuild Tier-2
    while scan_date <= end_date:
        blocks = load_segmented_blocks_from_active_revision(
            db, channel_slug=channel_slug, broadcast_day=scan_date,
        )
        if blocks is None:
            scan_date += timedelta(days=1)
            continue

        for sb_dict in blocks:
            block_start = sb_dict["start_utc_ms"]
            block_end = sb_dict["end_utc_ms"]

            # Only rebuild blocks that start within the window
            if block_start < start_utc_ms or block_start >= end_utc_ms:
                continue

            try:
                scheduled_block = _deserialize_scheduled_block(sb_dict)
                filled_block = fill_ad_blocks(
                    scheduled_block,
                    filler_uri=filler_uri,
                    filler_duration_ms=filler_duration_ms,
                )

                row = PlaylistEvent(
                    block_id=filled_block.block_id,
                    channel_slug=channel_slug,
                    broadcast_day=scan_date,
                    start_utc_ms=filled_block.start_utc_ms,
                    end_utc_ms=filled_block.end_utc_ms,
                    segments=[
                        {
                            "segment_index": i,
                            "segment_type": seg.segment_type,
                            "asset_uri": seg.asset_uri,
                            "asset_start_offset_ms": seg.asset_start_offset_ms,
                            "segment_duration_ms": seg.segment_duration_ms,
                        }
                        for i, seg in enumerate(filled_block.segments)
                    ],
                    window_uuid=sb_dict.get("window_uuid"),
                )
                db.merge(row)
                result.rebuilt += 1
            except Exception as e:
                msg = f"Failed to rebuild block {sb_dict.get('block_id', '?')}: {e}"
                result.errors.append(msg)
                logger.error("rebuild_tier2[%s]: %s", channel_slug, msg)

        scan_date += timedelta(days=1)

    db.flush()
    return result
