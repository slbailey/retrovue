"""BlockBreakLayout — unified break system for RetroVue playout blocks.

Defines the complete break structure for a single program block:
preroll, midroll, and postroll phases with explicit budget accounting.

The builder (`build_break_layout`) is a pure function: all decisions
happen here. The expander (`expand_break_layout`) is mechanical:
layout in, segments out, zero decisions.

Contract: docs/contracts/block_break_layout.md
Invariants: INV-BBL-BUDGET-001 through INV-BBL-TIME-001
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Domain objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StructuralEntry:
    """A preroll or postroll structural asset."""

    asset_id: str
    duration_ms: int
    segment_type: str  # "presentation" | "intro" | "outro"


@dataclass(frozen=True)
class PostrollEntry:
    """A postroll asset or traffic fill marker."""

    asset_id: str
    duration_ms: int
    segment_type: str  # "presentation" | "postroll_traffic"
    is_traffic_marker: bool


@dataclass(frozen=True)
class MidrollOpportunity:
    """A single break position within the content timeline."""

    position_ms: int
    weight: float
    allocated_ms: int
    transition_style: str  # "clean" | "fade"


@dataclass(frozen=True)
class MidrollPlan:
    """Complete midroll specification for a block."""

    source: str  # "dsl" | "chapter" | "algorithmic" | "none"
    opportunities: list[MidrollOpportunity]
    total_filler_ms: int
    min_segment_ms: int = 0


@dataclass(frozen=True)
class SuppressedSource:
    """A break source that was eligible but disallowed."""

    source: str   # "dsl" | "chapter" | "algorithmic"
    reason: str   # "policy" | "zero_budget" | "invalid_positions" | "chapter_precedence"


@dataclass(frozen=True)
class BlockBreakLayout:
    """Complete break structure for a single program block."""

    grid_slot_ms: int
    content_duration_ms: int
    channel_type: str
    block_start_utc_ms: int
    available_filler_ms: int
    trailing_filler_ms: int
    preroll: list[StructuralEntry]
    midroll: MidrollPlan
    postroll: list[PostrollEntry]
    suppressed_sources: list[SuppressedSource]


# ---------------------------------------------------------------------------
# Valid channel types
# ---------------------------------------------------------------------------

_VALID_CHANNEL_TYPES = frozenset({"network", "movie", "premium"})
_MIDROLL_FORBIDDEN_TYPES = frozenset({"movie", "premium"})


# ---------------------------------------------------------------------------
# Builder — pure function, all decisions here
# ---------------------------------------------------------------------------


def build_break_layout(
    *,
    grid_slot_ms: int,
    content_duration_ms: int,
    channel_type: str,
    block_start_utc_ms: int,
    dsl_midroll: list[dict] | None = None,
    chapter_markers_ms: tuple[int, ...] | None = None,
    preroll: list[StructuralEntry],
    postroll: list[PostrollEntry],
    min_segment_ms: int = 0,
    target_segment_minutes: int | None = None,
    break_strategy: str | None = None,
) -> BlockBreakLayout:
    """Build a complete break layout from resolved inputs.

    INV-BBL-BUILDER-001: Pure function of inputs. No external state.
    INV-BBL-BUDGET-009: available_filler_ms computed once here.

    target_segment_minutes: when provided (from template config),
    overrides the algorithmic break count formula per
    INV-BREAK-DENSITY-SCALES-001.
    """
    # --- Input validation ---
    # INV-BBL-STRUCT-007
    if grid_slot_ms <= 0:
        raise ValueError(
            f"INV-BBL-STRUCT-007: grid_slot_ms must be > 0, got {grid_slot_ms}"
        )
    # INV-BBL-BUDGET-008
    if content_duration_ms <= 0:
        raise ValueError(
            f"INV-BBL-BUDGET-008: content_duration_ms must be > 0, "
            f"got {content_duration_ms}"
        )
    if channel_type not in _VALID_CHANNEL_TYPES:
        raise ValueError(
            f"Invalid channel_type: {channel_type!r}. "
            f"Must be one of {sorted(_VALID_CHANNEL_TYPES)}"
        )

    # --- Budget computation (INV-BBL-BUDGET-009) ---
    preroll_total = sum(e.duration_ms for e in preroll)
    postroll_structural_total = sum(
        e.duration_ms for e in postroll if not e.is_traffic_marker
    )
    available_filler_ms = max(
        0,
        grid_slot_ms - preroll_total - postroll_structural_total - content_duration_ms,
    )

    # --- Policy check ---
    midroll_allowed = channel_type not in _MIDROLL_FORBIDDEN_TYPES
    suppressed: list[SuppressedSource] = []

    # --- Source resolution (exclusive) ---
    if available_filler_ms <= 0:
        # INV-BBL-BUDGET-006 + INV-BBL-SOURCE-008: zero budget → none
        opps: list[MidrollOpportunity] = []
        source = "none"
        # Record any eligible sources as suppressed
        if dsl_midroll:
            suppressed.append(SuppressedSource(source="dsl", reason="zero_budget"))
        if chapter_markers_ms:
            valid_ch = [m for m in chapter_markers_ms if 0 < m < content_duration_ms]
            if valid_ch:
                suppressed.append(
                    SuppressedSource(source="chapter", reason="zero_budget")
                )
    elif not midroll_allowed:
        # INV-BBL-POLICY-001/002: premium/movie → suppress all
        opps = []
        source = "none"
        if dsl_midroll:
            suppressed.append(SuppressedSource(source="dsl", reason="policy"))
        if chapter_markers_ms:
            valid_ch = [m for m in chapter_markers_ms if 0 < m < content_duration_ms]
            if valid_ch:
                suppressed.append(
                    SuppressedSource(source="chapter", reason="policy")
                )
    else:
        # Network: try DSL → chapter → algorithmic
        opps, source, src_suppressed = _resolve_midroll_source(
            dsl_midroll=dsl_midroll,
            chapter_markers_ms=chapter_markers_ms,
            content_duration_ms=content_duration_ms,
            min_segment_ms=min_segment_ms,
            target_segment_minutes=target_segment_minutes,
            break_strategy=break_strategy,
        )
        suppressed.extend(src_suppressed)

    # --- Budget allocation ---
    if opps:
        midroll_budget = available_filler_ms
        allocated = _allocate_weighted_budget(opps, midroll_budget)
        final_opps = [
            MidrollOpportunity(
                position_ms=o.position_ms,
                weight=o.weight,
                allocated_ms=a,
                transition_style=o.transition_style,
            )
            for o, a in zip(opps, allocated)
        ]
        total_filler_ms = sum(allocated)
    else:
        final_opps = []
        total_filler_ms = 0

    trailing_filler_ms = available_filler_ms - total_filler_ms

    midroll = MidrollPlan(
        source=source,
        opportunities=final_opps,
        total_filler_ms=total_filler_ms,
        min_segment_ms=min_segment_ms,
    )

    return BlockBreakLayout(
        grid_slot_ms=grid_slot_ms,
        content_duration_ms=content_duration_ms,
        channel_type=channel_type,
        block_start_utc_ms=block_start_utc_ms,
        available_filler_ms=available_filler_ms,
        trailing_filler_ms=trailing_filler_ms,
        preroll=list(preroll),
        midroll=midroll,
        postroll=list(postroll),
        suppressed_sources=suppressed,
    )


# ---------------------------------------------------------------------------
# Source resolution — exclusive selection
# ---------------------------------------------------------------------------


def _resolve_midroll_source(
    *,
    dsl_midroll: list[dict] | None,
    chapter_markers_ms: tuple[int, ...] | None,
    content_duration_ms: int,
    min_segment_ms: int,
    target_segment_minutes: int | None = None,
    break_strategy: str | None = None,
) -> tuple[list[MidrollOpportunity], str, list[SuppressedSource]]:
    """Resolve midroll opportunities from exactly one source.

    Returns (opportunities, source_name, suppressed_sources).
    INV-BBL-SOURCE-001: Exactly one source wins.
    INV-BBL-SOURCE-003: Chapter supersedes DSL.
    INV-BBL-SOURCE-004: DSL supersedes algorithmic.
    """
    suppressed: list[SuppressedSource] = []

    # INV-BREAK-PLACEMENT-PRIORITY-001: strategy-driven source selection
    # "synthetic" → skip chapter markers entirely, even if present
    # "chapter_markers_preferred" or None → existing priority model
    use_chapters = break_strategy != "synthetic"

    if not use_chapters and chapter_markers_ms:
        valid_ch = [m for m in chapter_markers_ms if 0 < m < content_duration_ms]
        if valid_ch:
            suppressed.append(
                SuppressedSource(source="chapter", reason="strategy_synthetic")
            )

    # Priority 1: Chapter markers (skipped when strategy=synthetic)
    if use_chapters and chapter_markers_ms:
        chapter_opps = _extract_chapter_opportunities(
            chapter_markers_ms, content_duration_ms, min_segment_ms,
        )
        if chapter_opps:
            # Chapters win — suppress DSL if it was provided
            if dsl_midroll:
                suppressed.append(
                    SuppressedSource(source="dsl", reason="chapter_precedence")
                )
            return chapter_opps, "chapter", suppressed
        # Chapters present but all filtered
        suppressed.append(
            SuppressedSource(source="chapter", reason="invalid_positions")
        )

    # Priority 2: DSL (fallback when chapters absent or unusable)
    if dsl_midroll:
        dsl_opps = _extract_dsl_opportunities(
            dsl_midroll, content_duration_ms, min_segment_ms,
        )
        if dsl_opps:
            return dsl_opps, "dsl", suppressed
        # DSL was present but produced zero valid positions
        suppressed.append(
            SuppressedSource(source="dsl", reason="invalid_positions")
        )

    # Priority 3: Algorithmic
    algo_opps = _compute_algorithmic_opportunities(
        content_duration_ms, min_segment_ms,
        target_segment_minutes=target_segment_minutes,
    )
    if algo_opps:
        return algo_opps, "algorithmic", suppressed

    return [], "none", suppressed


# ---------------------------------------------------------------------------
# DSL source
# ---------------------------------------------------------------------------


def _extract_dsl_opportunities(
    dsl_entries: list[dict],
    content_duration_ms: int,
    min_segment_ms: int,
) -> list[MidrollOpportunity]:
    """Extract midroll opportunities from DSL config.

    INV-BBL-SOURCE-006: positions are fractional-derived.
    INV-BBL-TRANS-001: DSL breaks get transition_style="clean".
    """
    all_positions: list[tuple[int, float]] = []  # (position_ms, weight)

    for entry in dsl_entries:
        placement = entry.get("placement", {})
        fallback = placement.get("fallback", {})
        positions = fallback.get("positions", [])
        weights = fallback.get("weights", [])

        for i, frac in enumerate(positions):
            pos_ms = round(frac * content_duration_ms)
            # INV-BBL-ORDER-002: filter out-of-bounds
            if pos_ms <= 0 or pos_ms >= content_duration_ms:
                continue
            w = weights[i] if i < len(weights) else 1.0
            all_positions.append((pos_ms, w))

    # Deduplicate by position_ms (keep first)
    seen: set[int] = set()
    unique: list[tuple[int, float]] = []
    for pos, w in all_positions:
        if pos not in seen:
            seen.add(pos)
            unique.append((pos, w))

    # Sort by position
    unique.sort(key=lambda x: x[0])

    # Apply min_segment_ms filter
    unique = _filter_min_segment(unique, content_duration_ms, min_segment_ms)

    return [
        MidrollOpportunity(
            position_ms=pos, weight=w, allocated_ms=0, transition_style="clean",
        )
        for pos, w in unique
    ]


# ---------------------------------------------------------------------------
# Chapter source
# ---------------------------------------------------------------------------


def _extract_chapter_opportunities(
    markers_ms: tuple[int, ...],
    content_duration_ms: int,
    min_segment_ms: int,
) -> list[MidrollOpportunity]:
    """Extract midroll opportunities from chapter markers.

    INV-BBL-SOURCE-007: positions are catalog-derived.
    INV-BBL-TRANS-002: Chapter breaks get transition_style="clean".
    Weights: monotonically increasing by position index (1.0, 2.0, ...).
    """
    # Filter and deduplicate
    seen: set[int] = set()
    valid: list[int] = []
    for m in markers_ms:
        if m <= 0 or m >= content_duration_ms:
            continue
        if m not in seen:
            seen.add(m)
            valid.append(m)

    valid.sort()

    # Apply min_segment_ms filter (with equal weight placeholder)
    pairs = [(pos, 1.0) for pos in valid]
    pairs = _filter_min_segment(pairs, content_duration_ms, min_segment_ms)

    # Assign monotonically increasing weights
    return [
        MidrollOpportunity(
            position_ms=pos,
            weight=float(idx + 1),
            allocated_ms=0,
            transition_style="clean",
        )
        for idx, (pos, _) in enumerate(pairs)
    ]


# ---------------------------------------------------------------------------
# Algorithmic source
# ---------------------------------------------------------------------------


def _compute_algorithmic_opportunities(
    content_duration_ms: int,
    min_segment_ms: int,
    *,
    target_segment_minutes: int | None = None,
) -> list[MidrollOpportunity]:
    """Compute algorithmic break positions.

    Replicates the logic from break_detection._compute_algorithmic_breaks
    for a single-content-segment program:
    - Protected zone: first 20%
    - Break count: max(2, content_runtime // 480_000) (legacy)
      OR floor(content_minutes / target_segment_minutes) when template
      provides target_segment_minutes (INV-BREAK-DENSITY-SCALES-001)
    - Non-uniform harmonic spacing

    INV-BBL-TRANS-003: Algorithmic breaks get transition_style="fade".
    """
    if content_duration_ms <= 0:
        return []

    protected_end = math.floor(content_duration_ms * 0.20)
    algo_start = protected_end
    algo_end = content_duration_ms

    if algo_start >= algo_end:
        return []

    # INV-BREAK-DENSITY-SCALES-001: template-driven break count
    if target_segment_minutes is not None and target_segment_minutes > 0:
        content_minutes = content_duration_ms / 60_000
        num_breaks = math.floor(content_minutes / target_segment_minutes)
        if num_breaks <= 0:
            return []
    else:
        # Legacy algorithmic formula
        num_breaks = max(2, content_duration_ms // 480_000)

    positions = _place_non_uniform(algo_start, algo_end, num_breaks)

    # Filter to within content bounds
    positions = [p for p in positions if 0 < p < content_duration_ms]

    # Apply min_segment_ms filter
    pairs = [(pos, 1.0) for pos in positions]
    pairs = _filter_min_segment(pairs, content_duration_ms, min_segment_ms)

    return [
        MidrollOpportunity(
            position_ms=pos, weight=1.0, allocated_ms=0, transition_style="fade",
        )
        for pos, _ in pairs
    ]


def _place_non_uniform(
    start_ms: int,
    end_ms: int,
    num_breaks: int,
) -> list[int]:
    """Place breaks with decreasing interval sizes.

    Harmonic weights: interval i has weight (num_intervals - i).
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


# ---------------------------------------------------------------------------
# Min-segment filter (INV-BBL-STRUCT-008)
# ---------------------------------------------------------------------------


def _filter_min_segment(
    positions_weights: list[tuple[int, float]],
    content_duration_ms: int,
    min_segment_ms: int,
) -> list[tuple[int, float]]:
    """Filter positions that would create content segments shorter than min."""
    if min_segment_ms <= 0 or not positions_weights:
        return positions_weights

    result: list[tuple[int, float]] = []
    prev = 0
    for pos, w in positions_weights:
        if pos - prev < min_segment_ms:
            continue
        # Check that remaining content after this break is also long enough
        # (we check against content_duration_ms, not next break — next break
        # will be checked on its own iteration)
        result.append((pos, w))
        prev = pos

    # Check final segment (last position to content end)
    while result and content_duration_ms - result[-1][0] < min_segment_ms:
        result.pop()

    return result


# ---------------------------------------------------------------------------
# Budget allocation (INV-BBL-BUDGET-002, 007, 010)
# ---------------------------------------------------------------------------


def _allocate_weighted_budget(
    opportunities: list[MidrollOpportunity],
    budget_ms: int,
) -> list[int]:
    """Allocate budget proportional to weights.

    INV-BBL-BUDGET-010: Remainder distributed deterministically.
    Remainder ms assigned one-at-a-time to opportunities in descending
    weight order. Ties broken by descending position order.
    INV-BBL-ORDER-007: Processed in ascending position_ms order.
    """
    if not opportunities or budget_ms <= 0:
        return [0] * len(opportunities)

    weights = [o.weight for o in opportunities]
    total_weight = sum(weights)

    if total_weight <= 0:
        base = budget_ms // len(opportunities)
        durations = [base] * len(opportunities)
        remainder = budget_ms - sum(durations)
        for i in range(remainder):
            durations[-(i + 1)] += 1
        return durations

    # Base allocation: floor of proportional share
    durations = [int(budget_ms * w / total_weight) for w in weights]
    remainder = budget_ms - sum(durations)

    # Distribute remainder: descending weight, ties broken by descending position
    ranked = sorted(
        range(len(weights)),
        key=lambda i: (-weights[i], -opportunities[i].position_ms),
    )
    for r in range(remainder):
        durations[ranked[r % len(ranked)]] += 1

    return durations


# ---------------------------------------------------------------------------
# Expansion — mechanical transformer, zero decisions
# ---------------------------------------------------------------------------


def expand_break_layout(layout: BlockBreakLayout) -> list[dict]:
    """Expand a BlockBreakLayout into an ordered segment list.

    INV-BBL-OUTPUT-001: No policy evaluation, no break detection,
    no budget recomputation. Layout is the complete instruction set.

    Returns list of segment dicts with keys:
        segment_type, duration_ms, asset_id (optional),
        asset_start_offset_ms (for content), transition_style (for content).
    """
    segments: list[dict] = []

    # Phase 1: Preroll (INV-BBL-ORDER-005)
    for entry in layout.preroll:
        segments.append({
            "segment_type": entry.segment_type,
            "duration_ms": entry.duration_ms,
            "asset_id": entry.asset_id,
        })

    # Phase 2: Content + midroll interleaved (INV-BBL-ORDER-004)
    prev_break = 0
    for opp in layout.midroll.opportunities:
        # Content act before this break
        act_duration = opp.position_ms - prev_break
        if act_duration > 0:
            segments.append({
                "segment_type": "content",
                "duration_ms": act_duration,
                "asset_start_offset_ms": prev_break,
                "transition_style": opp.transition_style,
            })
        # Midroll filler
        if opp.allocated_ms > 0:
            segments.append({
                "segment_type": "filler",
                "duration_ms": opp.allocated_ms,
            })
        prev_break = opp.position_ms

    # Final content act
    final_act = layout.content_duration_ms - prev_break
    if final_act > 0:
        segments.append({
            "segment_type": "content",
            "duration_ms": final_act,
            "asset_start_offset_ms": prev_break,
        })

    # Phase 3: Postroll + trailing filler (INV-BBL-ORDER-006, ORDER-008)
    trailing_emitted = False
    for entry in layout.postroll:
        if entry.is_traffic_marker:
            # INV-BBL-ORDER-008: trailing filler at traffic marker position
            if layout.trailing_filler_ms > 0:
                segments.append({
                    "segment_type": "filler",
                    "duration_ms": layout.trailing_filler_ms,
                })
                trailing_emitted = True
        else:
            segments.append({
                "segment_type": entry.segment_type,
                "duration_ms": entry.duration_ms,
                "asset_id": entry.asset_id,
            })

    # INV-BBL-ORDER-008: no traffic marker → trailing filler after postroll
    if not trailing_emitted and layout.trailing_filler_ms > 0:
        segments.append({
            "segment_type": "filler",
            "duration_ms": layout.trailing_filler_ms,
        })

    return segments
