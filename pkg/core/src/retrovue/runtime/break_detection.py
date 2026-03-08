"""Break Detection — dedicated pipeline stage for break opportunity identification.

Contract: docs/contracts/break_detection.md

Consumes an assembled program result (from ProgramDefinition assembly) and
produces a BreakPlan containing ordered break opportunities and a break budget.
Traffic fill consumes the BreakPlan — it must not invent break locations.

This module is pure domain logic with no database, scheduler, or media
dependencies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Domain objects
# ---------------------------------------------------------------------------


@dataclass
class BreakOpportunity:
    """A single identified point where a break may be inserted."""

    position_ms: int
    source: str  # "chapter" | "boundary" | "algorithmic"
    weight: float = 1.0


@dataclass
class BreakPlan:
    """Complete output of break detection for one program execution."""

    opportunities: list[BreakOpportunity]
    break_budget_ms: int
    program_runtime_ms: int
    grid_duration_ms: int


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_breaks(
    *,
    assembly_result: object,
    grid_duration_ms: int,
) -> BreakPlan:
    """Detect break opportunities in an assembled program.

    INV-BREAK-001: Accepts AssemblyResult, not raw asset duration.
    INV-BREAK-005: Budget derived from assembled runtime.
    INV-BREAK-008: Dedicated stage, independent of expander/traffic.
    """
    program_runtime_ms = assembly_result.total_runtime_ms
    break_budget_ms = grid_duration_ms - program_runtime_ms

    # INV-BREAK-011: zero or negative budget → empty plan
    if break_budget_ms <= 0:
        return BreakPlan(
            opportunities=[],
            break_budget_ms=break_budget_ms,
            program_runtime_ms=program_runtime_ms,
            grid_duration_ms=grid_duration_ms,
        )

    segments = assembly_result.segments

    # INV-BREAK-002: extract chapter markers (priority 1)
    chapter_opps = _extract_chapter_opportunities(segments)

    # INV-BREAK-004: extract asset boundary opportunities (priority 2)
    boundary_opps = _extract_boundary_opportunities(segments)

    # INV-BREAK-003/007: algorithmic placement (priority 3)
    # Suppressed when chapter or boundary breaks already exist.
    algo_opps: list[BreakOpportunity] = []
    if not chapter_opps and not boundary_opps:
        algo_opps = _compute_algorithmic_breaks(segments, program_runtime_ms)

    # Combine, sort by position, assign weights
    all_opps = chapter_opps + boundary_opps + algo_opps
    all_opps.sort(key=lambda o: o.position_ms)

    # Assign monotonically increasing weights by position order
    for i, opp in enumerate(all_opps):
        opp.weight = float(i + 1)

    return BreakPlan(
        opportunities=all_opps,
        break_budget_ms=break_budget_ms,
        program_runtime_ms=program_runtime_ms,
        grid_duration_ms=grid_duration_ms,
    )


# ---------------------------------------------------------------------------
# Chapter marker extraction (Priority 1)
# ---------------------------------------------------------------------------


def _extract_chapter_opportunities(
    segments: list,
) -> list[BreakOpportunity]:
    """Extract chapter-marker break opportunities from segments.

    Markers at position 0 or at the segment boundary are ignored.
    Marker positions are converted to program-timeline positions.
    """
    opps: list[BreakOpportunity] = []
    timeline_offset = 0

    for seg in segments:
        markers = getattr(seg, "chapter_markers_ms", None)
        if markers and seg.segment_type == "content":
            for marker in markers:
                # Ignore markers at segment start or boundary
                if marker <= 0 or marker >= seg.duration_ms:
                    continue
                opps.append(BreakOpportunity(
                    position_ms=timeline_offset + marker,
                    source="chapter",
                ))
        timeline_offset += seg.duration_ms

    return opps


# ---------------------------------------------------------------------------
# Asset boundary extraction (Priority 2)
# ---------------------------------------------------------------------------


def _extract_boundary_opportunities(
    segments: list,
) -> list[BreakOpportunity]:
    """Extract content-to-content seam opportunities.

    INV-BREAK-004: Every content-to-content seam is emitted.
    INV-BREAK-009: Intro-to-content and content-to-outro seams are excluded.
    """
    opps: list[BreakOpportunity] = []
    timeline_offset = 0
    prev_was_content = False

    for seg in segments:
        if seg.segment_type == "content" and prev_was_content:
            opps.append(BreakOpportunity(
                position_ms=timeline_offset,
                source="boundary",
            ))
        prev_was_content = seg.segment_type == "content"
        timeline_offset += seg.duration_ms

    return opps


# ---------------------------------------------------------------------------
# Algorithmic placement (Priority 3)
# ---------------------------------------------------------------------------


def _compute_algorithmic_breaks(
    segments: list,
    program_runtime_ms: int,
) -> list[BreakOpportunity]:
    """Place algorithmic breaks using non-uniform spacing.

    INV-BREAK-003: Protected zone (first 20%) excludes algorithmic breaks.
    INV-BREAK-007: Spacing widens toward end (intervals decrease).
    INV-BREAK-009: Breaks only within content segments.
    INV-BREAK-010: Cold open protection per segment.
    """
    # Compute content-only ranges on the program timeline
    content_ranges = _content_ranges(segments)
    if not content_ranges:
        return []

    content_start = content_ranges[0][0]
    content_end = content_ranges[-1][1]
    content_runtime = sum(end - start for start, end in content_ranges)

    if content_runtime <= 0:
        return []

    # Protected zone: first 20% of total program runtime
    protected_end = math.floor(program_runtime_ms * 0.20)

    # Cold open: per content segment, no algo break before first chapter marker.
    # Since algo is only invoked when no chapters exist, cold open constraints
    # come from segments with chapter_markers_ms. In practice, when algo runs,
    # there are no chapter markers, so cold_open_end = 0.
    cold_open_end = _cold_open_boundary(segments)

    # Effective start for algorithmic breaks
    algo_start = max(protected_end, content_start, cold_open_end)
    algo_end = content_end

    if algo_start >= algo_end:
        return []

    # Number of breaks: ~1 per 8 minutes of content, minimum 2
    num_breaks = max(2, content_runtime // 480_000)

    # Non-uniform spacing: intervals decrease toward end
    # Uses harmonic-decreasing weights: (N+1-i) for interval i
    positions = _place_non_uniform(algo_start, algo_end, num_breaks)

    # Filter to positions within content ranges only
    positions = [p for p in positions if _in_content_range(p, content_ranges)]

    return [
        BreakOpportunity(position_ms=pos, source="algorithmic")
        for pos in positions
    ]


def _content_ranges(segments: list) -> list[tuple[int, int]]:
    """Return (start_ms, end_ms) for each content segment on the timeline."""
    ranges: list[tuple[int, int]] = []
    offset = 0
    for seg in segments:
        if seg.segment_type == "content" and seg.duration_ms > 0:
            ranges.append((offset, offset + seg.duration_ms))
        offset += seg.duration_ms
    return ranges


def _cold_open_boundary(segments: list) -> int:
    """Return the program-timeline position of the earliest cold-open boundary.

    If any content segment has chapter markers, the cold open extends from
    that segment's start to its first marker.
    """
    offset = 0
    boundary = 0
    for seg in segments:
        if seg.segment_type == "content":
            markers = getattr(seg, "chapter_markers_ms", None)
            if markers:
                valid = [m for m in markers if 0 < m < seg.duration_ms]
                if valid:
                    boundary = max(boundary, offset + min(valid))
        offset += seg.duration_ms
    return boundary


def _place_non_uniform(
    start_ms: int,
    end_ms: int,
    num_breaks: int,
) -> list[int]:
    """Place breaks with decreasing interval sizes (first interval longest).

    Uses harmonic weights: interval i has weight (num_intervals - i),
    producing larger early acts and shorter later acts.
    """
    total_range = end_ms - start_ms
    if total_range <= 0 or num_breaks <= 0:
        return []

    num_intervals = num_breaks + 1
    weights = [num_intervals - i for i in range(num_intervals)]
    total_weight = sum(weights)

    positions: list[int] = []
    cursor = start_ms
    for i in range(num_breaks):
        interval = total_range * weights[i] / total_weight
        cursor += int(interval)
        positions.append(cursor)

    return positions


def _in_content_range(
    position_ms: int,
    content_ranges: list[tuple[int, int]],
) -> bool:
    """Check if a position falls within any content range."""
    for start, end in content_ranges:
        if start <= position_ms < end:
            return True
    return False
