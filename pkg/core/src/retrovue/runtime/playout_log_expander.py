"""
Playout Log Expander.

Expands a program block from the Program Schedule into a ScheduledBlock
containing ScheduledSegments — the exact types ChannelManager consumes.

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
) -> ScheduledBlock:
    """
    Expand a program block into a ScheduledBlock with act segments
    and empty filler slots for ad breaks.

    Episode acts are "content" segments. Ad block placeholders are
    "filler" segments with empty asset_uri (to be filled by traffic manager).

    Break classification (INV-TRANSITION-001, SegmentTransitionContract.md):
    - First-class: from chapter_markers_ms — clean cuts, TRANSITION_NONE.
    - Second-class: computed by dividing episode evenly — TRANSITION_FADE applied.

    Args:
        asset_id: Asset identifier (for block_id generation).
        asset_uri: File path to the episode/movie.
        start_utc_ms: Grid-aligned start time in UTC milliseconds.
        slot_duration_ms: Total grid slot duration in ms.
        episode_duration_ms: Actual episode runtime in ms.
        chapter_markers_ms: Optional chapter marker times in ms from episode start.
        num_breaks: Number of ad breaks if no chapter markers (default 3).
        fade_duration_ms: Duration of fade transitions for second-class breakpoints (default 500ms).

    Returns:
        ScheduledBlock with content and filler segments.
    """
    total_ad_ms = max(0, slot_duration_ms - episode_duration_ms)

    # Determine break points and their class (first vs second).
    # INV-TRANSITION-001: chapter markers → first-class; computed → second-class.
    if chapter_markers_ms and len(chapter_markers_ms) > 0:
        break_points = sorted(bp for bp in chapter_markers_ms if 0 < bp < episode_duration_ms)
        # First-class: from explicit chapter markers (deliberate editorial cuts).
        second_class_set: set[int] = set()
    else:
        if num_breaks <= 0:
            break_points = []
        else:
            interval = episode_duration_ms / (num_breaks + 1)
            break_points = [int(interval * (i + 1)) for i in range(num_breaks)]
        # Second-class: all computed breakpoints are arbitrary mid-scene cuts.
        second_class_set = set(break_points)

    actual_num_breaks = len(break_points)
    ad_block_ms = total_ad_ms // actual_num_breaks if actual_num_breaks > 0 else 0
    # Distribute remainder across first blocks
    ad_remainder = total_ad_ms - (ad_block_ms * actual_num_breaks) if actual_num_breaks > 0 else 0

    # Build raw segments: track which content segment precedes which breakpoint class.
    # pending_fade_in: set when a second-class filler was just appended; the next
    # content segment should receive transition_in=FADE.
    raw_segments: list[ScheduledSegment] = []
    prev_break = 0
    pending_fade_in = False

    for i, bp in enumerate(break_points):
        act_duration = bp - prev_break
        is_second_class = bp in second_class_set

        # Content (act) segment ending at this breakpoint.
        # transition_in comes from whether the preceding filler was second-class.
        # transition_out: FADE if this is a second-class break, NONE if first-class.
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

        # Ad block placeholder (filler with empty uri — traffic manager fills these)
        this_ad = ad_block_ms + (1 if i < ad_remainder else 0)
        if this_ad > 0:
            raw_segments.append(ScheduledSegment(
                segment_type="filler",
                asset_uri="",
                asset_start_offset_ms=0,
                segment_duration_ms=this_ad,
            ))

        # INV-TRANSITION-002: If this breakpoint is second-class, the next content
        # segment must fade in (symmetry with fade-out just applied).
        pending_fade_in = is_second_class and this_ad > 0
        prev_break = bp

    # Final act segment (after all breaks, or first/only segment if no breaks).
    final_act_ms = episode_duration_ms - prev_break
    if final_act_ms > 0:
        raw_segments.append(ScheduledSegment(
            segment_type="content",
            asset_uri=asset_uri,
            asset_start_offset_ms=prev_break,
            segment_duration_ms=final_act_ms,
            transition_in="TRANSITION_FADE" if pending_fade_in else "TRANSITION_NONE",
            transition_in_duration_ms=fade_duration_ms if pending_fade_in else 0,
            # No transition_out on final act (end of episode, no following filler).
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
