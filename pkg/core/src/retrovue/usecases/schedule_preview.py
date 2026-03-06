"""Preview Tier-2 playout segments for a schedule block.

Read-only — reads pre-filled PlaylistEvent rows from the database.
Shows exactly what the daemon wrote (or will write) to Tier-2.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from retrovue.domain.entities import PlaylistEvent


def preview_at(
    db: Session,
    *,
    channel_slug: str,
    at: datetime,
) -> dict[str, Any]:
    """Return Tier-2 segments for the block covering `at`.

    Read-only — reads directly from PlaylistEvent (Tier-2 truth).
    This shows exactly what the daemon produced, including real
    interstitials from the traffic manager.
    """
    at_ms = int(at.timestamp() * 1000)

    # Find the PlaylistEvent covering this time
    row = (
        db.query(PlaylistEvent)
        .filter(
            PlaylistEvent.channel_slug == channel_slug,
            PlaylistEvent.start_utc_ms <= at_ms,
            PlaylistEvent.end_utc_ms > at_ms,
        )
        .first()
    )

    if row is None:
        return {
            "error": "No Tier-2 block covers this time",
            "channel": channel_slug,
            "time": at.isoformat(),
        }

    # Build segment list from stored segments
    segments_out = []
    cursor_ms = row.start_utc_ms
    for i, seg in enumerate(row.segments):
        seg_start = datetime.fromtimestamp(cursor_ms / 1000, tz=timezone.utc)
        duration_ms = seg.get("segment_duration_ms", 0)
        segments_out.append({
            "index": i,
            "segment_type": seg.get("segment_type", "unknown"),
            "start_time": seg_start.isoformat(),
            "duration_ms": duration_ms,
            "duration_display": _format_duration(duration_ms),
            "asset_uri": seg.get("asset_uri") or "(none)",
            "asset_start_offset_ms": seg.get("asset_start_offset_ms", 0),
        })
        cursor_ms += duration_ms

    return {
        "channel": channel_slug,
        "time": at.isoformat(),
        "block_id": row.block_id,
        "block_start": datetime.fromtimestamp(
            row.start_utc_ms / 1000, tz=timezone.utc
        ).isoformat(),
        "block_end": datetime.fromtimestamp(
            row.end_utc_ms / 1000, tz=timezone.utc
        ).isoformat(),
        "block_duration_ms": row.end_utc_ms - row.start_utc_ms,
        "segment_count": len(row.segments),
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
