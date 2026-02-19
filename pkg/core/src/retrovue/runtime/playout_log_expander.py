"""
Playout Log Expander.

Expands a program block from the Program Schedule into a ScheduledBlock
containing ScheduledSegments — the exact types ChannelManager consumes.

Break placement is determined by channel_type (B-CT-1):
  - "network": Mid-content breaks at chapter markers or computed breakpoints
  - "movie": Post-content only — content plays uninterrupted, filler after

Uses chapter markers from asset metadata to determine act boundaries.
If no chapter markers, approximates by dividing the episode evenly.

Pure function — no DB writes, no globals.
"""

from __future__ import annotations

import hashlib

from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment


def expand_program_block(
    *,
    asset_id: str,
    asset_uri: str,
    start_utc_ms: int,
    slot_duration_ms: int,
    episode_duration_ms: int,
    chapter_markers_ms: tuple[int, ...] | None = None,
    num_breaks: int = 3,
    fade_duration_ms: int = 500,
    channel_type: str = "network",
) -> ScheduledBlock:
    """
    Expand a program block into a ScheduledBlock with content and filler segments.

    Break placement is driven by channel_type (INV-CHANNEL-TYPE-BREAK-PLACEMENT):
      - "network": mid-content breaks (chapter markers or computed)
      - "movie": single post-content filler block (no interruption)

    Args:
        asset_id: Asset identifier (for block_id generation).
        asset_uri: File path to the episode/movie.
        start_utc_ms: Grid-aligned start time in UTC milliseconds.
        slot_duration_ms: Total grid slot duration in ms.
        episode_duration_ms: Actual episode runtime in ms.
        chapter_markers_ms: Optional chapter marker times in ms from episode start.
        num_breaks: Number of ad breaks if no chapter markers (default 3).
        fade_duration_ms: Duration of fade transitions for second-class breakpoints (default 500ms).
        channel_type: Channel type driving break placement ("network" or "movie").

    Returns:
        ScheduledBlock with content and filler segments.
    """
    if channel_type == "movie":
        return _expand_movie(
            asset_id=asset_id,
            asset_uri=asset_uri,
            start_utc_ms=start_utc_ms,
            slot_duration_ms=slot_duration_ms,
            episode_duration_ms=episode_duration_ms,
        )

    return _expand_network(
        asset_id=asset_id,
        asset_uri=asset_uri,
        start_utc_ms=start_utc_ms,
        slot_duration_ms=slot_duration_ms,
        episode_duration_ms=episode_duration_ms,
        chapter_markers_ms=chapter_markers_ms,
        num_breaks=num_breaks,
        fade_duration_ms=fade_duration_ms,
    )


def _expand_movie(
    *,
    asset_id: str,
    asset_uri: str,
    start_utc_ms: int,
    slot_duration_ms: int,
    episode_duration_ms: int,
) -> ScheduledBlock:
    """Movie channel: content plays uninterrupted, all filler after content.

    B-CT-2: Zero mid-content breaks. Single content segment + optional
    post-content filler segment for the remaining time.

    Segment layout:
        [Full Movie] → [Promos/Trailers until next grid boundary]
    """
    segments: list[ScheduledSegment] = []

    # Single uninterrupted content segment
    segments.append(ScheduledSegment(
        segment_type="content",
        asset_uri=asset_uri,
        asset_start_offset_ms=0,
        segment_duration_ms=episode_duration_ms,
    ))

    # Post-content filler (remaining time in the grid slot)
    remaining_ms = max(0, slot_duration_ms - episode_duration_ms)
    if remaining_ms > 0:
        segments.append(ScheduledSegment(
            segment_type="filler",
            asset_uri="",
            asset_start_offset_ms=0,
            segment_duration_ms=remaining_ms,
        ))

    end_utc_ms = start_utc_ms + slot_duration_ms
    block_id = _make_block_id(asset_id, start_utc_ms)

    return ScheduledBlock(
        block_id=block_id,
        start_utc_ms=start_utc_ms,
        end_utc_ms=end_utc_ms,
        segments=tuple(segments),
    )


def _expand_network(
    *,
    asset_id: str,
    asset_uri: str,
    start_utc_ms: int,
    slot_duration_ms: int,
    episode_duration_ms: int,
    chapter_markers_ms: tuple[int, ...] | None = None,
    num_breaks: int = 3,
    fade_duration_ms: int = 500,
) -> ScheduledBlock:
    """Network channel: mid-content breaks at chapter markers or computed breakpoints.

    B-CT-3: Existing behavior for ad-supported channels.

    Break classification (INV-TRANSITION-001, SegmentTransitionContract.md):
    - First-class: from chapter_markers_ms — clean cuts, TRANSITION_NONE.
    - Second-class: computed by dividing episode evenly — TRANSITION_FADE applied.
    """
    total_ad_ms = max(0, slot_duration_ms - episode_duration_ms)

    # Determine break points and their class (first vs second).
    if chapter_markers_ms and len(chapter_markers_ms) > 0:
        break_points = sorted(bp for bp in chapter_markers_ms if 0 < bp < episode_duration_ms)
        second_class_set: set[int] = set()
    else:
        if num_breaks <= 0:
            break_points = []
        else:
            interval = episode_duration_ms / (num_breaks + 1)
            break_points = [int(interval * (i + 1)) for i in range(num_breaks)]
        second_class_set = set(break_points)

    actual_num_breaks = len(break_points)
    ad_block_ms = total_ad_ms // actual_num_breaks if actual_num_breaks > 0 else 0
    ad_remainder = total_ad_ms - (ad_block_ms * actual_num_breaks) if actual_num_breaks > 0 else 0

    raw_segments: list[ScheduledSegment] = []
    prev_break = 0
    pending_fade_in = False

    for i, bp in enumerate(break_points):
        act_duration = bp - prev_break
        is_second_class = bp in second_class_set

        raw_segments.append(ScheduledSegment(
            segment_type="content",
            asset_uri=asset_uri,
            asset_start_offset_ms=prev_break,
            segment_duration_ms=act_duration,
            transition_in="TRANSITION_FADE" if pending_fade_in else "TRANSITION_NONE",
            transition_in_duration_ms=fade_duration_ms if pending_fade_in else 0,
            transition_out="TRANSITION_FADE" if is_second_class else "TRANSITION_NONE",
            transition_out_duration_ms=fade_duration_ms if is_second_class else 0,
        ))

        this_ad = ad_block_ms + (1 if i < ad_remainder else 0)
        if this_ad > 0:
            raw_segments.append(ScheduledSegment(
                segment_type="filler",
                asset_uri="",
                asset_start_offset_ms=0,
                segment_duration_ms=this_ad,
            ))

        pending_fade_in = is_second_class and this_ad > 0
        prev_break = bp

    # Final act segment
    final_act_ms = episode_duration_ms - prev_break
    if final_act_ms > 0:
        raw_segments.append(ScheduledSegment(
            segment_type="content",
            asset_uri=asset_uri,
            asset_start_offset_ms=prev_break,
            segment_duration_ms=final_act_ms,
            transition_in="TRANSITION_FADE" if pending_fade_in else "TRANSITION_NONE",
            transition_in_duration_ms=fade_duration_ms if pending_fade_in else 0,
        ))

    end_utc_ms = start_utc_ms + slot_duration_ms
    block_id = _make_block_id(asset_id, start_utc_ms)

    return ScheduledBlock(
        block_id=block_id,
        start_utc_ms=start_utc_ms,
        end_utc_ms=end_utc_ms,
        segments=tuple(raw_segments),
    )


def _make_block_id(asset_id: str, start_utc_ms: int) -> str:
    """Deterministic block ID from asset + start time."""
    raw = f"{asset_id}:{start_utc_ms}"
    return f"blk-{hashlib.sha256(raw.encode()).hexdigest()[:12]}"
