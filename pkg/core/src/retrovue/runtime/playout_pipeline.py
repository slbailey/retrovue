"""
Phase 4 — PlayoutPipeline: conceptual intent → PlayoutSegment.

Pure logic: (ScheduleItem, grid_start, grid_end, elapsed_in_grid_ms, channel_id, Assets)
→ PlayoutSegment (asset_path, start_offset_ms, hard_stop_time_ms).
No execution, no Air. Phase 2.5: paths and duration from Asset metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from retrovue.runtime.asset_metadata import Asset
from retrovue.runtime.mock_schedule import ScheduleItem, ScheduleItemId


@dataclass(frozen=True)
class PlayoutSegment:
    """
    Explicit segment for broadcast. All offsets in milliseconds (int64).
    hard_stop_time_ms is authoritative; end_offset is optional and advisory.
    """

    asset_path: str
    start_offset_ms: int  # media-relative only
    hard_stop_time_ms: int  # wall-clock epoch ms; authoritative


def build_playout_segment(
    schedule_item: ScheduleItem,
    grid_start: datetime,
    grid_end: datetime,
    elapsed_in_grid_ms: int,
    channel_id: str,
    *,
    samplecontent_asset: Asset,
    filler_asset: Asset,
) -> tuple[PlayoutSegment, str]:
    """
    Build a PlayoutSegment for the current moment. Pure logic; creates new instance each call.
    Phase 2.5: uses Asset.asset_path and Asset.duration_ms (authoritative, no probing).

    Args:
        schedule_item: Active item from Phase 3 (samplecontent or filler).
        grid_start: Start of current grid block (Phase 1).
        grid_end: End of current grid block / next boundary (Phase 1).
        elapsed_in_grid_ms: Elapsed time in grid in ms (Phase 1).
        channel_id: Channel id (for PlayoutRequest envelope; returned with segment).
        samplecontent_asset: Phase 2.5 Asset for samplecontent (path + duration_ms).
        filler_asset: Phase 2.5 Asset for filler (path + duration_ms).

    Returns:
        (PlayoutSegment, channel_id). PlayoutRequest = segment + channel_id (envelope only).
    """
    # Ensure aware for timestamp
    if grid_end.tzinfo is None:
        grid_end = grid_end.replace(tzinfo=timezone.utc)
    hard_stop_time_ms = int(grid_end.timestamp() * 1000)

    item_id: ScheduleItemId = schedule_item.id
    if item_id == "samplecontent":
        asset_path = samplecontent_asset.asset_path
        start_offset_ms = elapsed_in_grid_ms
    else:
        asset_path = filler_asset.asset_path
        # start_offset = elapsed_in_grid − sample_duration (media-relative into filler segment)
        start_offset_ms = elapsed_in_grid_ms - samplecontent_asset.duration_ms
        if start_offset_ms < 0:
            start_offset_ms = 0

    segment = PlayoutSegment(
        asset_path=asset_path,
        start_offset_ms=start_offset_ms,
        hard_stop_time_ms=hard_stop_time_ms,
    )
    return (segment, channel_id)
