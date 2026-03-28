"""
Traffic Manager v3.

Fills empty filler slots in a ScheduledBlock with real interstitial
assets from the database, respecting channel policy (allowed types,
cooldowns, daily caps) and break structure (bumpers framing interstitial pool).

When a BreakConfig is provided, each filler placeholder is first expanded
through build_break_structure() to produce typed slots. Bumper slots are
filled with bumper assets; interstitial slots are filled via the traffic
policy engine. When no BreakConfig is provided, the legacy flat-fill
behavior is preserved.

Falls back to the static filler file when no interstitials are available.

Leftover time within each ad break is distributed evenly as black pad
between spots (INV-BREAK-PAD-DISTRIBUTED-001).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from retrovue.runtime.break_structure import BreakConfig, build_break_structure
from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment
from retrovue.runtime.traffic_inventory import apply_category_ordering
from retrovue.runtime.traffic_policy import (
    PlayRecord,
    TrafficCandidate,
    TrafficPolicy,
    evaluate_candidates,
)

if TYPE_CHECKING:
    from retrovue.catalog.db_asset_library import DatabaseAssetLibrary


def _build_filler_segments(
    gap_ms: int,
    filler_uri: str,
    filler_duration_ms: int,
    alignment: str = "start",
    wrapping_offset_ms: int = 0,
) -> tuple[list[ScheduledSegment], int]:
    """Build filler segments to fill a gap of ``gap_ms`` milliseconds.

    INV-FILLER-ALIGNMENT-001: Two alignment modes.

    **Start mode** — plays filler forward from ``wrapping_offset_ms``, wrapping
    at the end of the filler file. Returns the new wrapping offset so
    consecutive gaps continue seamlessly.

    **End mode** — positions filler so the closing frames coincide with the
    gap boundary (block seam). Stateless: returned offset is always 0.

    Returns:
        (segments, new_wrapping_offset)
    """
    if gap_ms <= 0:
        return [], wrapping_offset_ms

    segments: list[ScheduledSegment] = []

    if alignment == "end":
        remainder = gap_ms % filler_duration_ms
        full_loops = gap_ms // filler_duration_ms

        if remainder == 0:
            # Exact multiple — all full loops, no partial
            for _ in range(full_loops):
                segments.append(ScheduledSegment(
                    segment_type="filler",
                    asset_uri=filler_uri,
                    asset_start_offset_ms=0,
                    segment_duration_ms=filler_duration_ms,
                ))
        else:
            # Partial segment first (seam-aligned), then full loops
            partial_offset = filler_duration_ms - remainder
            segments.append(ScheduledSegment(
                segment_type="filler",
                asset_uri=filler_uri,
                asset_start_offset_ms=partial_offset,
                segment_duration_ms=remainder,
            ))
            for _ in range(full_loops):
                segments.append(ScheduledSegment(
                    segment_type="filler",
                    asset_uri=filler_uri,
                    asset_start_offset_ms=0,
                    segment_duration_ms=filler_duration_ms,
                ))

        # INV-FILLER-ALIGNMENT-END-STATELESS-001: end mode is stateless
        return segments, 0

    # --- Start alignment (default) ---
    offset = wrapping_offset_ms
    remaining = gap_ms
    while remaining > 0:
        playable = min(remaining, filler_duration_ms - offset)
        segments.append(ScheduledSegment(
            segment_type="filler",
            asset_uri=filler_uri,
            asset_start_offset_ms=offset,
            segment_duration_ms=playable,
        ))
        offset = (offset + playable) % filler_duration_ms
        remaining -= playable

    return segments, offset


def fill_ad_blocks(
    block: ScheduledBlock,
    filler_uri: str,
    filler_duration_ms: int,
    asset_library: "DatabaseAssetLibrary | None" = None,
    policy: TrafficPolicy | None = None,
    play_history: list[PlayRecord] | None = None,
    now_ms: int = 0,
    day_start_ms: int = 0,
    break_config: BreakConfig | None = None,
    filler_alignment: str = "start",
) -> ScheduledBlock:
    """
    Fill all empty filler placeholders in a ScheduledBlock.

    INV-TRAFFIC-FILL-STRUCTURED-001: When break_config is provided, each
    filler placeholder is expanded through build_break_structure() before
    filling. Bumper slots are filled with bumper assets; interstitial slots
    are filled via the traffic policy engine.

    Args:
        block: ScheduledBlock with empty filler placeholders.
        filler_uri: Path to the fallback filler video file.
        filler_duration_ms: Total duration of the fallback filler file in ms.
        asset_library: Optional DatabaseAssetLibrary for real interstitial selection.
        policy: Optional TrafficPolicy for policy-driven selection.
        play_history: Play records for cooldown/cap evaluation. Caller-owned.
        now_ms: Current timestamp in ms for cooldown evaluation.
        day_start_ms: Channel traffic day start in ms for daily cap evaluation.
        break_config: Optional BreakConfig for structured break expansion.
        filler_alignment: "start" or "end" (INV-FILLER-ALIGNMENT-001).

    Returns:
        New ScheduledBlock with filled segments.
    """
    if filler_duration_ms <= 0:
        raise ValueError("filler_duration_ms must be positive")
    # INV-TIME-TYPE-001: Fail fast — upstream must pass int ms.
    if not isinstance(filler_duration_ms, int):
        raise TypeError(
            f"INV-TIME-TYPE-001: filler_duration_ms must be int, "
            f"got {type(filler_duration_ms).__name__}: {filler_duration_ms!r}"
        )

    # INV-MOVIE-PRIMARY-ATOMIC: If block contains a primary segment,
    # no filler placeholder may appear before the primary segment ends.
    _assert_no_filler_before_primary(block.segments)

    new_segments: list[ScheduledSegment] = []
    filler_offset_ms = 0  # v1: running offset into filler file, wraps at end

    # Accumulate play records across breaks within this block so rotation
    # advances between breaks. Copy to avoid mutating the caller's list.
    running_history: list[PlayRecord] = list(play_history) if play_history else []

    for seg in block.segments:
        if seg.segment_type == "filler" and seg.asset_uri == "":
            if asset_library is not None:
                if break_config is not None:
                    # INV-TRAFFIC-FILL-STRUCTURED-001: Expand through BreakStructure
                    filled = _fill_structured_break(
                        break_duration_ms=seg.segment_duration_ms,
                        break_config=break_config,
                        asset_library=asset_library,
                        policy=policy,
                        play_history=running_history,
                        now_ms=now_ms,
                        day_start_ms=day_start_ms,
                        filler_uri=filler_uri,
                        filler_duration_ms=filler_duration_ms,
                    )
                else:
                    filled = _fill_break_with_interstitials(
                        break_duration_ms=seg.segment_duration_ms,
                        asset_library=asset_library,
                        policy=policy,
                        play_history=running_history,
                        now_ms=now_ms,
                        day_start_ms=day_start_ms,
                    )
                if filled:
                    new_segments.extend(filled)
                    continue

            # Fallback: static filler via _build_filler_segments
            # INV-FILLER-ALIGNMENT-001: delegates to alignment-aware builder.
            filler_segs, filler_offset_ms = _build_filler_segments(
                gap_ms=seg.segment_duration_ms,
                filler_uri=filler_uri,
                filler_duration_ms=filler_duration_ms,
                alignment=filler_alignment,
                wrapping_offset_ms=filler_offset_ms,
            )
            new_segments.extend(filler_segs)
        else:
            new_segments.append(seg)

    filled = ScheduledBlock(
        block_id=block.block_id,
        start_utc_ms=block.start_utc_ms,
        end_utc_ms=block.end_utc_ms,
        segments=tuple(new_segments),
        traffic_profile=block.traffic_profile,
    )

    # INV-BLOCK-SEGMENT-CONSERVATION-001: Verify segment sum == block duration
    # after playlog plan fill.  If overflow, trim final non-content segment to fit.
    block_duration_ms = filled.end_utc_ms - filled.start_utc_ms
    sum_segment_ms = sum(s.segment_duration_ms for s in filled.segments)
    delta_ms = sum_segment_ms - block_duration_ms
    if delta_ms > 0:
        import logging
        _log = logging.getLogger(__name__)
        _log.warning(
            "INV-BLOCK-SEGMENT-CONSERVATION-001: trimming overflow "
            "block_id=%s sum_segment_ms=%d block_duration_ms=%d "
            "delta_ms=%d",
            filled.block_id, sum_segment_ms, block_duration_ms, delta_ms,
        )
        # Trim the last non-content segment (filler/pad) to absorb overflow.
        trimmed = list(filled.segments)
        for i in range(len(trimmed) - 1, -1, -1):
            seg = trimmed[i]
            if seg.segment_type in ("filler", "padding") and seg.segment_duration_ms > delta_ms:
                trimmed[i] = ScheduledSegment(
                    segment_type=seg.segment_type,
                    asset_uri=seg.asset_uri,
                    asset_start_offset_ms=seg.asset_start_offset_ms,
                    segment_duration_ms=seg.segment_duration_ms - delta_ms,
                    gain_db=seg.gain_db,
                )
                filled = ScheduledBlock(
                    block_id=filled.block_id,
                    start_utc_ms=filled.start_utc_ms,
                    end_utc_ms=filled.end_utc_ms,
                    segments=tuple(trimmed),
                    traffic_profile=filled.traffic_profile,
                )
                break

    return filled


def _assert_no_filler_before_primary(
    segments: tuple[ScheduledSegment, ...],
) -> None:
    """Reject blocks where filler placeholders appear before primary content ends.

    INV-MOVIE-PRIMARY-ATOMIC: Primary segments must never be split by ads.
    If a block contains a primary segment, all filler placeholders must
    appear after the primary segment — never before or between primary content.
    """
    primary_indices = [
        i for i, s in enumerate(segments) if s.is_primary
    ]
    if not primary_indices:
        return  # No primary segments — nothing to guard

    last_primary_idx = max(primary_indices)
    for i in range(last_primary_idx):
        seg = segments[i]
        if seg.segment_type == "filler" and seg.asset_uri == "":
            raise ValueError(
                f"INV-MOVIE-PRIMARY-ATOMIC violated: filler placeholder at "
                f"segment index {i} appears before primary segment at "
                f"index {last_primary_idx}. Primary content must never be "
                f"split by ad breaks."
            )


# ---------------------------------------------------------------------------
# Structured break fill (INV-TRAFFIC-FILL-STRUCTURED-001)
# ---------------------------------------------------------------------------


def _fill_structured_break(
    break_duration_ms: int,
    break_config: BreakConfig,
    asset_library: "DatabaseAssetLibrary",
    policy: TrafficPolicy | None = None,
    play_history: list[PlayRecord] | None = None,
    now_ms: int = 0,
    day_start_ms: int = 0,
    filler_uri: str = "",
    filler_duration_ms: int = 30_000,
) -> list[ScheduledSegment] | None:
    """Fill a single break using BreakStructure slot expansion.

    1. build_break_structure() produces typed slots.
    2. Bumper slots are filled with bumper assets from the library.
    3. Station ID slots are filled with station_id assets from the library.
    4. Unfilled structural slots (bumper or station_id) degrade: their
       duration merges into the interstitial pool.
    5. The interstitial pool is filled via the existing fill loop.
    """
    if not isinstance(break_duration_ms, int):
        raise TypeError(
            f"INV-TIME-TYPE-001: break_duration_ms must be int, "
            f"got {type(break_duration_ms).__name__}: {break_duration_ms!r}"
        )

    structure = build_break_structure(
        allocated_budget_ms=break_duration_ms,
        config=break_config,
    )

    if not structure.slots:
        return None

    # Phase 1: Attempt bumper and station_id selection; compute effective
    # interstitial pool. Walk the structure, resolve structural slots, and
    # accumulate degraded duration from unfilled structural slots.
    structural_segments: dict[int, ScheduledSegment] = {}  # slot_index → segment
    degraded_ms = 0

    for i, slot in enumerate(structure.slots):
        if slot.fill_rule == "bumper":
            bumper_seg = _select_bumper(
                slot_duration_ms=slot.duration_ms,
                asset_library=asset_library,
            )
            if bumper_seg is not None:
                structural_segments[i] = bumper_seg
                # INV-TRAFFIC-FILL-EXACT-001: if asset is shorter than slot,
                # the unused portion degrades into the interstitial pool.
                shortfall = slot.duration_ms - bumper_seg.segment_duration_ms
                if shortfall > 0:
                    degraded_ms += shortfall
            else:
                # INV-TRAFFIC-FILL-BUMPER-DEGRADE-001: merge to pool
                degraded_ms += slot.duration_ms
        elif slot.fill_rule == "station_id":
            sid_seg = _select_station_id(
                slot_duration_ms=slot.duration_ms,
                asset_library=asset_library,
            )
            if sid_seg is not None:
                structural_segments[i] = sid_seg
                # INV-TRAFFIC-FILL-EXACT-001: shortfall degrades to pool.
                shortfall = slot.duration_ms - sid_seg.segment_duration_ms
                if shortfall > 0:
                    degraded_ms += shortfall
            else:
                # Station ID degradation: merge to interstitial pool
                degraded_ms += slot.duration_ms

    # Phase 2: Fill interstitial pool (original pool + degraded bumper time).
    interstitial_pool_ms = 0
    for slot in structure.slots:
        if slot.fill_rule == "traffic":
            interstitial_pool_ms += slot.duration_ms
    interstitial_pool_ms += degraded_ms

    interstitial_segments = _fill_interstitial_pool(
        pool_duration_ms=interstitial_pool_ms,
        asset_library=asset_library,
        policy=policy,
        play_history=play_history,
        now_ms=now_ms,
        day_start_ms=day_start_ms,
        filler_uri=filler_uri,
        filler_duration_ms=filler_duration_ms,
    )

    # Phase 3: Assemble final segment list in slot order.
    segments: list[ScheduledSegment] = []
    for i, slot in enumerate(structure.slots):
        if slot.fill_rule in ("bumper", "station_id"):
            if i in structural_segments:
                segments.append(structural_segments[i])
            # else: degraded — duration already merged into interstitial pool
        elif slot.fill_rule == "traffic":
            segments.extend(interstitial_segments)
            interstitial_segments = []  # only emit once

    if not segments:
        return None

    # Verify invariant: total must equal break duration
    total = sum(s.segment_duration_ms for s in segments)
    assert total == break_duration_ms, (
        f"INV-TRAFFIC-FILL-EXACT-001 violated: {total}ms != {break_duration_ms}ms"
    )

    return segments


def _select_bumper(
    slot_duration_ms: int,
    asset_library: "DatabaseAssetLibrary",
) -> ScheduledSegment | None:
    """Select a single bumper asset for a bumper slot.

    Queries the asset library for bumper-type assets that fit within the
    slot duration. Returns the first eligible bumper, or None if none found.

    Bumper selection does not use the traffic policy engine. Bumpers are
    not subject to cooldown, daily caps, or rotation.
    """
    candidates = asset_library.get_filler_assets(
        max_duration_ms=slot_duration_ms,
        count=10,
    )
    # Filter to bumper type only
    bumpers = [c for c in candidates if c.asset_type == "bumper"]
    if not bumpers:
        return None

    # Pick the first eligible bumper (longest that fits, for best fill)
    bumpers.sort(key=lambda c: c.duration_ms, reverse=True)
    pick = bumpers[0]

    return ScheduledSegment(
        segment_type="bumper",
        asset_uri=pick.asset_uri,
        asset_start_offset_ms=0,
        segment_duration_ms=pick.duration_ms,
    )


def _select_station_id(
    slot_duration_ms: int,
    asset_library: "DatabaseAssetLibrary",
) -> ScheduledSegment | None:
    """Select a single station ID asset for a station_id slot.

    Queries the asset library for station_id-type assets that fit within the
    slot duration. Returns the first eligible station ID, or None if none found.

    Station ID selection does not use the traffic policy engine. Station IDs
    are structural elements, not subject to cooldown, daily caps, or rotation.
    """
    candidates = asset_library.get_filler_assets(
        max_duration_ms=slot_duration_ms,
        count=10,
    )
    # Filter to station_id type only
    station_ids = [c for c in candidates if c.asset_type == "station_id"]
    if not station_ids:
        return None

    # Pick the longest that fits
    station_ids.sort(key=lambda c: c.duration_ms, reverse=True)
    pick = station_ids[0]

    return ScheduledSegment(
        segment_type="station_id",
        asset_uri=pick.asset_uri,
        asset_start_offset_ms=0,
        segment_duration_ms=pick.duration_ms,
    )


def _fill_interstitial_pool(
    pool_duration_ms: int,
    asset_library: "DatabaseAssetLibrary",
    policy: TrafficPolicy | None = None,
    play_history: list[PlayRecord] | None = None,
    now_ms: int = 0,
    day_start_ms: int = 0,
    filler_uri: str = "",
    filler_duration_ms: int = 30_000,
) -> list[ScheduledSegment]:
    """Fill the interstitial pool with traffic assets + pad.

    Same logic as _fill_break_with_interstitials but always returns segments
    (falls back to filler loop internally rather than returning None).
    """
    if pool_duration_ms <= 0:
        return []

    result = _fill_break_with_interstitials(
        break_duration_ms=pool_duration_ms,
        asset_library=asset_library,
        policy=policy,
        play_history=play_history,
        now_ms=now_ms,
        day_start_ms=day_start_ms,
    )
    if result:
        return result

    # Filler fallback for the pool
    segments: list[ScheduledSegment] = []
    remaining_ms = pool_duration_ms
    filler_offset_ms = 0
    while remaining_ms > 0:
        playable = min(remaining_ms, filler_duration_ms - filler_offset_ms)
        segments.append(ScheduledSegment(
            segment_type="filler",
            asset_uri=filler_uri,
            asset_start_offset_ms=filler_offset_ms,
            segment_duration_ms=playable,
        ))
        filler_offset_ms = (filler_offset_ms + playable) % filler_duration_ms
        remaining_ms -= playable
    return segments


# ---------------------------------------------------------------------------
# Pad invariant enforcement (post-assembly)
# ---------------------------------------------------------------------------


def _assert_pad_invariants(segments: list[ScheduledSegment]) -> None:
    """Enforce pad structural invariants after break fill assembly.

    INV-PAD-SPOT-AFFINITY-001: pad.spot_index == predecessor.spot_index
    INV-PAD-NEVER-ORPHAN-001: pad never first; predecessor has spot_index != None
    INV-PAD-SPOT-UNIQUE-001: each spot_index → exactly 1 asset + at most 1 pad
    INV-PAD-ONLY-TRAFFIC-001: traffic pads have spot_index != None
    No adjacent pad segments.
    """
    from collections import Counter

    spot_assets: Counter[int] = Counter()
    spot_pads: Counter[int] = Counter()

    for i, seg in enumerate(segments):
        if seg.segment_type == "pad":
            # INV-PAD-ONLY-TRAFFIC-001: traffic pad must have spot_index
            assert seg.spot_index is not None, (
                f"INV-PAD-ONLY-TRAFFIC-001 violated: pad at index {i} has spot_index=None"
            )
            # INV-PAD-NEVER-ORPHAN-001: pad must not be first
            assert i > 0, (
                f"INV-PAD-NEVER-ORPHAN-001 violated: pad at index 0"
            )
            pred = segments[i - 1]
            # INV-PAD-NEVER-ORPHAN-001: predecessor must be a traffic pick
            assert pred.spot_index is not None, (
                f"INV-PAD-NEVER-ORPHAN-001 violated: pad at index {i} "
                f"follows segment with spot_index=None (type={pred.segment_type!r})"
            )
            # INV-PAD-SPOT-AFFINITY-001: same spot_index as predecessor
            assert seg.spot_index == pred.spot_index, (
                f"INV-PAD-SPOT-AFFINITY-001 violated: pad at index {i} "
                f"has spot_index={seg.spot_index} but predecessor has "
                f"spot_index={pred.spot_index}"
            )
            # No adjacent pads
            assert pred.segment_type != "pad", (
                f"Adjacent pad segments at indices {i-1} and {i}"
            )
            spot_pads[seg.spot_index] += 1
        elif seg.spot_index is not None:
            spot_assets[seg.spot_index] += 1

    # INV-PAD-SPOT-UNIQUE-001: each spot_index → 1 asset, ≤1 pad
    for si in set(spot_assets) | set(spot_pads):
        assert spot_assets[si] == 1, (
            f"INV-PAD-SPOT-UNIQUE-001 violated: spot_index={si} "
            f"has {spot_assets[si]} asset segments (expected 1)"
        )
        assert spot_pads[si] <= 1, (
            f"INV-PAD-SPOT-UNIQUE-001 violated: spot_index={si} "
            f"has {spot_pads[si]} pad segments (expected ≤1)"
        )


# ---------------------------------------------------------------------------
# Legacy flat fill (no BreakStructure)
# ---------------------------------------------------------------------------


def _fill_break_with_interstitials(
    break_duration_ms: int,
    asset_library: "DatabaseAssetLibrary",
    policy: TrafficPolicy | None = None,
    play_history: list[PlayRecord] | None = None,
    now_ms: int = 0,
    day_start_ms: int = 0,
) -> list[ScheduledSegment] | None:
    """
    Fill a single ad break with interstitials from the asset library.

    When a TrafficPolicy is provided, candidates are evaluated through
    the traffic policy engine (evaluate_candidates) which enforces allowed
    types, cooldowns, daily caps, and deterministic rotation, then reordered
    by apply_category_ordering for break-level category diversity.

    When no policy is provided, falls back to candidates[0] (legacy).

    Packs spots until the break is full (or no more fit), then distributes
    remaining time as evenly-spaced black pads between spots.

    Returns None if no interstitials were found (caller falls back to v1).

    When policy is provided, new PlayRecord entries are appended to
    play_history so rotation advances across breaks within a block.
    """
    # INV-TIME-TYPE-001: Fail fast — upstream must pass int ms.
    if not isinstance(break_duration_ms, int):
        raise TypeError(
            f"INV-TIME-TYPE-001: break_duration_ms must be int, "
            f"got {type(break_duration_ms).__name__}: {break_duration_ms!r}"
        )
    remaining_ms = break_duration_ms
    picks: list[tuple[str, int, str]] = []  # (uri, duration_ms, asset_type)
    break_categories: list[str | None] = []  # category of each pick in this break
    history = play_history if play_history is not None else []

    while remaining_ms > 0:
        candidates = asset_library.get_filler_assets(
            max_duration_ms=remaining_ms, count=20 if policy else 5,
        )
        if not candidates:
            break

        if policy is not None:
            # Convert FillerAsset → TrafficCandidate for policy evaluation
            traffic_candidates = [
                TrafficCandidate(
                    asset_id=c.asset_uri,
                    asset_type=c.asset_type,
                    duration_ms=c.duration_ms,
                    asset_category=getattr(c, "asset_category", None),
                    cooldown_group=getattr(c, "cooldown_group", None),
                    tags=getattr(c, "tags", ()),
                )
                for c in candidates
            ]
            # Stage 2: filter + rotation sort
            ordered = evaluate_candidates(
                traffic_candidates, policy, history, now_ms, day_start_ms,
            )
            logger.debug(
                "break fill: remaining_ms=%d eligible_candidates=%d",
                remaining_ms, len(ordered),
            )
            # Stage 3: category diversity + separation ordering
            ordered = apply_category_ordering(ordered, break_categories)
            if not ordered:
                break
            picked = ordered[0]
            logger.debug(
                "selected_candidate: id=%s category=%r",
                picked.asset_id, picked.asset_category,
            )
            # Record the play so rotation advances within this block
            history.append(PlayRecord(
                asset_id=picked.asset_id,
                asset_type=picked.asset_type,
                played_at_ms=now_ms,
                cooldown_group=picked.cooldown_group,
            ))
            picks.append((picked.asset_id, picked.duration_ms, picked.asset_type))
            break_categories.append(picked.asset_category)
            remaining_ms -= picked.duration_ms
        else:
            pick = candidates[0]
            picks.append((pick.asset_uri, pick.duration_ms, pick.asset_type))
            break_categories.append(getattr(pick, "asset_category", None))
            remaining_ms -= pick.duration_ms

    if not picks:
        return None

    # Calculate gap and distribute (INV-PAD-FRAME-DISTRIBUTION-001)
    # Base allocation per spot; ALL remainder goes to final spot only.
    filled_ms = sum(d for _, d, _ in picks)
    gap_ms = break_duration_ms - filled_ms
    num_items = len(picks)

    if gap_ms > 0 and num_items > 0:
        base_pad = gap_ms // num_items
        extra = gap_ms % num_items
        pad_sizes = [base_pad] * num_items
        # INV-PAD-FRAME-DISTRIBUTION-001: remainder to final spot only
        pad_sizes[-1] += extra
    else:
        pad_sizes = [0] * num_items

    # Build segments: [spot, pad?, spot, pad?, ...]
    # INV-PAD-SPOT-AFFINITY-001: pad gets same spot_index as its asset
    # INV-PAD-ONLY-TRAFFIC-001: traffic pads have spot_index != None
    segments: list[ScheduledSegment] = []
    for i, (uri, duration_ms, asset_type) in enumerate(picks):
        seg_type = asset_type if asset_type in ("filler", "promo", "ad", "commercial") else "filler"
        segments.append(ScheduledSegment(
            segment_type=seg_type,
            asset_uri=uri,
            asset_start_offset_ms=0,
            segment_duration_ms=duration_ms,
            spot_index=i,
        ))
        if pad_sizes[i] > 0:
            segments.append(ScheduledSegment(
                segment_type="pad",
                asset_uri="",
                asset_start_offset_ms=0,
                segment_duration_ms=pad_sizes[i],
                spot_index=i,
            ))

    # Verify invariant: total must equal break duration
    total = sum(s.segment_duration_ms for s in segments)
    assert total == break_duration_ms, (
        f"INV-BREAK-PAD-EXACT-001 violated: {total}ms != {break_duration_ms}ms"
    )

    # --- Post-assembly invariant checks ---
    _assert_pad_invariants(segments)

    return segments
