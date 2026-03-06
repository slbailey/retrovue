"""Preview Tier-2 playout segments for a schedule block.

Read-only — generates Tier-2 segments without writing to the database.
Reuses the same logic as PlaylistBuilderDaemon.
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
from retrovue.runtime.schedule_items_reader import (
    _hydrate_compiled_segments,
    load_segmented_blocks_from_active_revision,
)
from retrovue.runtime.dsl_schedule_service import (
    _deserialize_scheduled_block,
)
from retrovue.runtime.traffic_manager import fill_ad_blocks


def _broadcast_date_for(dt: datetime, day_start_hour: int = 6):
    from datetime import date
    if dt.hour < day_start_hour:
        return (dt - timedelta(days=1)).date()
    return dt.date()


def preview_at(
    db: Session,
    *,
    channel_slug: str,
    at: datetime,
) -> dict[str, Any]:
    """Generate and return Tier-2 segments for the block covering `at`.

    Read-only — no database mutations. Uses the same segmentation path
    as PlaylistBuilderDaemon (load_segmented_blocks_from_active_revision).
    """
    at_ms = int(at.timestamp() * 1000)
    target_bd = _broadcast_date_for(at)

    # Scan broadcast days to find the block containing `at`
    block_dict = None
    for bd in (target_bd - timedelta(days=1), target_bd):
        blocks = load_segmented_blocks_from_active_revision(
            db, channel_slug=channel_slug, broadcast_day=bd,
        )
        if blocks is None:
            continue
        for sb in blocks:
            if sb["start_utc_ms"] <= at_ms < sb["end_utc_ms"]:
                block_dict = sb
                break
        if block_dict is not None:
            break

    if block_dict is None:
        return {
            "error": "No Tier-1 block covers this time",
            "channel": channel_slug,
            "time": at.isoformat(),
        }

    # Deserialize and fill (same path as daemon)
    scheduled_block = _deserialize_scheduled_block(block_dict)
    filled_block = fill_ad_blocks(scheduled_block)

    # Build segment list
    segments_out = []
    cursor_ms = filled_block.start_utc_ms
    for i, seg in enumerate(filled_block.segments):
        seg_start = datetime.fromtimestamp(cursor_ms / 1000, tz=timezone.utc)
        segments_out.append({
            "index": i,
            "segment_type": seg.segment_type,
            "start_time": seg_start.isoformat(),
            "duration_ms": seg.segment_duration_ms,
            "duration_display": _format_duration(seg.segment_duration_ms),
            "asset_uri": seg.asset_uri or "(none)",
            "asset_start_offset_ms": seg.asset_start_offset_ms,
        })
        cursor_ms += seg.segment_duration_ms

    return {
        "channel": channel_slug,
        "time": at.isoformat(),
        "block_id": filled_block.block_id,
        "block_start": datetime.fromtimestamp(
            filled_block.start_utc_ms / 1000, tz=timezone.utc
        ).isoformat(),
        "block_end": datetime.fromtimestamp(
            filled_block.end_utc_ms / 1000, tz=timezone.utc
        ).isoformat(),
        "block_duration_ms": filled_block.end_utc_ms - filled_block.start_utc_ms,
        "segment_count": len(filled_block.segments),
        "segments": segments_out,
    }


def _format_duration(ms: int) -> str:
    """Format milliseconds as human-readable duration."""
    total_sec = ms // 1000
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    seconds = total_sec % 60
    if hours > 0:
        return f"{hours}h{minutes:02d}m{seconds:02d}s"
    if minutes > 0:
        return f"{minutes}m{seconds:02d}s"
    return f"{seconds}s"
