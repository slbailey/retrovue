"""
Playout Log Expander.

Expands a program block from the Program Schedule into a ScheduledBlock
containing ScheduledSegments — the exact types ChannelManager consumes.

Break placement is determined by channel_type (B-CT-1):
  - "network": Mid-content breaks via break detection pipeline (INV-BREAK-008)
  - "movie": Post-content only — content plays uninterrupted, filler after

INV-BREAK-008: Break positions are determined exclusively by detect_breaks().
The expander does NOT contain inline chapter marker extraction or synthetic
break computation. BreakPlan is the sole source of break positions.

Pure function — no DB writes, no globals.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from retrovue.runtime.break_detection import BreakOpportunity, detect_breaks
from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment


# ---------------------------------------------------------------------------
# Assembly helpers — bridge single-asset inputs to detect_breaks interface
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _AssemblySegment:
    """Minimal segment for break detection assembly."""
    segment_type: str
    duration_ms: int
    chapter_markers_ms: tuple[int, ...] | None = None


@dataclass(frozen=True)
class _AssemblyResult:
    """Minimal assembly result for break detection."""
    total_runtime_ms: int
    segments: tuple[_AssemblySegment, ...]


def _assemble_single_asset(
    episode_duration_ms: int,
    chapter_markers_ms: tuple[int, ...] | None = None,
) -> _AssemblyResult:
    """Create an assembly result from a single content asset."""
    seg = _AssemblySegment(
        segment_type="content",
        duration_ms=episode_duration_ms,
        chapter_markers_ms=chapter_markers_ms,
    )
    return _AssemblyResult(
        total_runtime_ms=episode_duration_ms,
        segments=(seg,),
    )


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
    gain_db: float = 0.0,
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
    # INV-TIME-TYPE-001: Fail fast on float contamination.
    if not isinstance(slot_duration_ms, int):
        raise TypeError(
            f"INV-TIME-TYPE-001: slot_duration_ms must be int, "
            f"got {type(slot_duration_ms).__name__}: {slot_duration_ms!r}"
        )
    if not isinstance(episode_duration_ms, int):
        raise TypeError(
            f"INV-TIME-TYPE-001: episode_duration_ms must be int, "
            f"got {type(episode_duration_ms).__name__}: {episode_duration_ms!r}"
        )

    if channel_type == "movie":
        return _expand_movie(
            asset_id=asset_id,
            asset_uri=asset_uri,
            start_utc_ms=start_utc_ms,
            slot_duration_ms=slot_duration_ms,
            episode_duration_ms=episode_duration_ms,
            gain_db=gain_db,
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
        gain_db=gain_db,
    )


def _expand_movie(
    *,
    asset_id: str,
    asset_uri: str,
    start_utc_ms: int,
    slot_duration_ms: int,
    episode_duration_ms: int,
    gain_db: float = 0.0,
) -> ScheduledBlock:
    """Movie channel: content plays uninterrupted, all filler after content.

    B-CT-2: Zero mid-content breaks. Single content segment + optional
    post-content filler segment for the remaining time.

    Segment layout:
        [Full Movie] → [Promos/Trailers until next grid boundary]
    """
    segments: list[ScheduledSegment] = []

    # Single uninterrupted content segment
    # INV-MOVIE-PRIMARY-ATOMIC: movie content is primary and must never be split
    segments.append(ScheduledSegment(
        segment_type="content",
        asset_uri=asset_uri,
        asset_start_offset_ms=0,
        segment_duration_ms=episode_duration_ms,
        gain_db=gain_db,
        is_primary=True,
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


def _allocate_weighted_budget(
    opportunities: list[BreakOpportunity],
    budget_ms: int,
) -> list[int]:
    """Allocate break budget proportional to opportunity weights.

    INV-BREAK-WEIGHT-001:
    - Durations proportional to weight.
    - Sum equals budget_ms exactly.
    - Remainder ms distributed starting from highest-weight break.
    """
    if not opportunities:
        return []
    if budget_ms <= 0:
        return [0] * len(opportunities)

    weights = [opp.weight for opp in opportunities]
    total_weight = sum(weights)
    if total_weight <= 0:
        # Fallback: equal distribution
        base = budget_ms // len(opportunities)
        durations = [base] * len(opportunities)
        remainder = budget_ms - sum(durations)
        for i in range(remainder):
            durations[-(i + 1)] += 1
        return durations

    # Base allocation: floor of proportional share
    durations = [int(budget_ms * w / total_weight) for w in weights]
    remainder = budget_ms - sum(durations)

    # Distribute remainder starting from highest-weight break
    # Build indices sorted by weight descending, then by position (index) descending for ties
    ranked = sorted(range(len(weights)), key=lambda i: (-weights[i], -i))
    for r in range(remainder):
        durations[ranked[r % len(ranked)]] += 1

    return durations


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
    gain_db: float = 0.0,
) -> ScheduledBlock:
    """Network channel: mid-content breaks via break detection pipeline.

    INV-BREAK-008: Break positions determined exclusively by detect_breaks().
    No inline chapter marker extraction or synthetic break computation.

    Break classification (INV-TRANSITION-001, SegmentTransitionContract.md):
    - First-class: chapter-sourced breaks → TRANSITION_NONE.
    - Second-class: algorithmic/boundary breaks → TRANSITION_FADE applied.

    Note: num_breaks parameter is retained for API compatibility but is
    ignored — break count is determined by detect_breaks() algorithm.
    """
    # Step 1: Assemble — create assembly result from single asset
    assembly_result = _assemble_single_asset(
        episode_duration_ms=episode_duration_ms,
        chapter_markers_ms=chapter_markers_ms,
    )

    # Step 2: Detect breaks via dedicated pipeline stage
    break_plan = detect_breaks(
        assembly_result=assembly_result,
        grid_duration_ms=slot_duration_ms,
    )

    # Step 3: Allocate budget proportional to opportunity weights
    break_positions = [opp.position_ms for opp in break_plan.opportunities]
    break_sources = {opp.position_ms: opp.source for opp in break_plan.opportunities}
    ad_durations = _allocate_weighted_budget(
        break_plan.opportunities, max(0, break_plan.break_budget_ms),
    )

    raw_segments: list[ScheduledSegment] = []
    prev_break = 0
    pending_fade_in = False

    for i, bp in enumerate(break_positions):
        act_duration = bp - prev_break
        is_second_class = break_sources.get(bp) != "chapter"

        raw_segments.append(ScheduledSegment(
            segment_type="content",
            asset_uri=asset_uri,
            asset_start_offset_ms=prev_break,
            segment_duration_ms=act_duration,
            transition_in="TRANSITION_FADE" if pending_fade_in else "TRANSITION_NONE",
            transition_in_duration_ms=fade_duration_ms if pending_fade_in else 0,
            transition_out="TRANSITION_FADE" if is_second_class else "TRANSITION_NONE",
            transition_out_duration_ms=fade_duration_ms if is_second_class else 0,
            gain_db=gain_db,
        ))

        this_ad = ad_durations[i]
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
            gain_db=gain_db,
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
