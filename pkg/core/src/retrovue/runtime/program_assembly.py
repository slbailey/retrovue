"""Program Assembly — V2 pipeline stage (channel_dsl.md §5–§6).

Bridges schedule compilation (progression, timing) with program definition
(fill_mode, intro/outro) and schedule block (bleed). Receives a resolved
schedule block and program definition, queries assets from the pool via
the resolver, applies progression ordering, and delegates to
assemble_program for fill/bleed logic.

Entry point: assemble_schedule_block()
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass

logger = logging.getLogger(__name__)
from datetime import date as _date, timedelta as _timedelta
from typing import Any

# Migration epoch — backward-compatible anchor origin for channels that
# predate ProgressionRun persistence.  Monday 2026-01-05 was the bootstrap
# epoch used before persistent runs were introduced.  Every placement
# pattern (weekday, weekend, daily, single DOW) has a matching date
# within the first 7 days from this Monday.
_MIGRATION_EPOCH = _date(2026, 1, 5)

from retrovue.runtime.asset_resolver import AssetResolver, PoolDiagnostics
from retrovue.runtime.program_definition import (
    AssemblyFault,
    AssemblyResult,
    AssemblySegment,
    ProgramDefinition,
    assemble_program,
)
from retrovue.runtime.serial_episode_resolver import (
    SerialRunInfo,
    count_occurrences,
    apply_wrap_policy,
    dsl_layer_key_to_mask,
    resolve_serial_episode,
)


# ---------------------------------------------------------------------------
# Pool adapter — wraps AssetResolver + progression into the pool interface
# expected by assemble_program.
# ---------------------------------------------------------------------------


@dataclass
class _PoolAsset:
    """Minimal asset object compatible with assemble_program's duck-typed pool."""

    asset_id: str
    duration_ms: int
    state: str = "ready"
    approved_for_broadcast: bool = True


@dataclass
class _ProgressionPool:
    """A pool whose assets are pre-ordered according to progression mode.

    assemble_program iterates assets in order. This pool presents assets
    in the order determined by the schedule block's progression, so
    assembly picks content in the correct progression sequence.
    """

    name: str
    assets: list[_PoolAsset]

    def eligible_assets(self) -> list[_PoolAsset]:
        return [a for a in self.assets if a.state == "ready" and a.approved_for_broadcast]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def assemble_schedule_block(
    *,
    program_ref: str,
    program_def: dict[str, Any],
    pool_name: str,
    slots: int,
    progression: str,
    grid_minutes: int,
    resolver: AssetResolver,
    bleed: bool = False,
    seed: int | None = None,
    channel_id: str = "",
    broadcast_day: str = "",
    schedule_layer: str = "all_day",
    start_time: str = "00:00",
    run_id: str | None = None,
    exhaustion_policy: str = "wrap",
    run_store: object | None = None,
    emissions_per_occurrence: int = 1,
    prior_same_day_emissions: int = 0,
) -> list[AssemblyResult]:
    """Assemble all program executions for a single schedule block.

    This is the V2 Program Assembly entry point called by the schedule
    compiler after Schedule Resolution and Program Resolution.

    Returns one AssemblyResult per program execution.

    Raises:
        AssemblyFault: if any execution cannot assemble valid content.
    """
    grid_blocks = program_def.get("grid_blocks", 1)
    grid_blocks_max = program_def.get("grid_blocks_max")
    is_dynamic = grid_blocks_max is not None
    fill_mode = program_def.get("fill_mode", "single")
    intro_ref = program_def.get("intro")
    outro_ref = program_def.get("outro")
    presentation_refs = program_def.get("presentation")
    postroll_refs = program_def.get("presentation_postroll")

    # INV-PROGRAM-GRID-001: slots must be exact multiple of grid_blocks
    # (only for fixed-grid programs; dynamic uses slots as budget)
    if is_dynamic:
        grid_blocks = 0  # signal dynamic mode to ProgramDefinition
        executions = 1   # greedy loop handled by caller
    else:
        if grid_blocks <= 0 or slots % grid_blocks != 0:
            raise AssemblyFault(
                f"INV-PROGRAM-GRID-001: slots ({slots}) is not a multiple of "
                f"grid_blocks ({grid_blocks}) for program '{program_ref}'"
            )
        executions = slots // grid_blocks

    prog = ProgramDefinition(
        name=program_ref,
        pool=pool_name,
        grid_blocks=grid_blocks,
        fill_mode=fill_mode,
        intro=intro_ref,
        outro=outro_ref,
        presentation=presentation_refs,
        presentation_postroll=postroll_refs,
        grid_blocks_max=grid_blocks_max,
    )

    # Resolve intro/outro assets if referenced
    intro_asset = _resolve_wrapper_asset(intro_ref, resolver) if intro_ref else None
    outro_asset = _resolve_wrapper_asset(outro_ref, resolver) if outro_ref else None

    # INV-POOL-RESOLUTION-VISIBILITY-001: collect diagnostics for every pool
    # resolution that occurs during assembly.
    block_pool_diagnostics: dict[str, PoolDiagnostics] = {}

    # Get all pool candidates from the resolver
    pool_meta = resolver.lookup(pool_name)
    all_candidate_ids = list(pool_meta.tags)
    if not all_candidate_ids:
        # Content pool is empty — emit diagnostics before raising.
        _emit_pool_diagnostics(
            pool_name, resolver, block_pool_diagnostics,
        )
        raise AssemblyFault(
            f"INV-PROGRAM-POOL-002: pool '{pool_name}' has zero assets"
        )

    rng = random.Random(seed)
    results: list[AssemblyResult] = []
    running_offset_ms = 0

    for exec_idx in range(executions):
        # Order candidates according to progression mode
        ordered_ids = _apply_progression(
            candidate_ids=all_candidate_ids,
            progression=progression,
            program_ref=program_ref,
            channel_id=channel_id,
            rng=rng,
            fill_mode=fill_mode,
            grid_blocks=grid_blocks,
            grid_minutes=grid_minutes,
            seed=seed,
            broadcast_day=broadcast_day,
            schedule_layer=schedule_layer,
            start_time=start_time,
            run_id=run_id,
            exhaustion_policy=exhaustion_policy,
            execution_index=exec_idx,
            run_store=run_store,
            emissions_per_occurrence=emissions_per_occurrence,
            prior_same_day_emissions=prior_same_day_emissions,
        )

        # Build pool adapter with progression-ordered assets
        pool_assets = _build_pool_assets(ordered_ids, resolver)
        pool = _ProgressionPool(name=pool_name, assets=pool_assets)

        # INV-PRESENTATION-CONTEXTUAL-SELECT-001: peek at content selection
        # to build program context BEFORE resolving presentation entries.
        program_ctx = None
        if presentation_refs or postroll_refs:
            # Approximate wrapper overhead for eligibility check (intro/outro only;
            # presentation overhead is what we're resolving, so excluded here).
            intro_ms = getattr(intro_asset, "duration_ms", 0) if intro_asset else 0
            outro_ms = getattr(outro_asset, "duration_ms", 0) if outro_asset else 0
            peek_wrapper_ms = intro_ms + outro_ms

            if is_dynamic and grid_blocks_max is not None:
                peek_grid_ms = grid_blocks_max * grid_minutes * 60 * 1000
            else:
                peek_grid_ms = prog.grid_duration_ms(grid_minutes)

            content_id = _peek_content_selection(
                pool_assets, fill_mode, peek_grid_ms, peek_wrapper_ms, bleed,
            )
            if content_id:
                program_ctx = _resolve_program_context(content_id, resolver)

        # Resolve presentation entries per execution (pool entries may vary)
        presentation_assets = None
        if presentation_refs:
            presentation_assets = _resolve_presentation_entries(
                presentation_refs, resolver, rng,
                pool_diagnostics=block_pool_diagnostics,
                program_context=program_ctx,
            )

        # Resolve postroll entries in declared order, preserving the traffic
        # directive's position as a sentinel marker in the resolved list.
        # INV-DSL-SEGMENT-ORDER-DETERMINISTIC-001: declared order is visual order.
        postroll_resolved = None
        if postroll_refs:
            postroll_resolved = _resolve_postroll_entries(
                postroll_refs, resolver, rng,
                pool_diagnostics=block_pool_diagnostics,
                program_context=program_ctx,
            )

        result = assemble_program(
            prog,
            pool,
            grid_minutes=grid_minutes,
            bleed=bleed,
            block_start_ms=running_offset_ms,
            intro_asset=intro_asset,
            outro_asset=outro_asset,
            presentation_assets=presentation_assets,
            postroll_resolved=postroll_resolved,
        )

        # INV-POOL-RESOLUTION-VISIBILITY-001: attach collected diagnostics
        result.pool_diagnostics = dict(block_pool_diagnostics)

        results.append(result)
        running_offset_ms = result.next_block_start_offset_ms

    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _rating_to_tag(rating: str | None) -> str | None:
    """Convert an MPAA rating to its normalized tag form.

    PG-13 → pg13, PG → pg, R → r, G → g, etc.
    """
    if not rating:
        return None
    return rating.lower().replace("-", "")


def _resolve_program_context(
    content_asset_id: str,
    resolver: AssetResolver,
) -> dict[str, Any]:
    """Extract program context from selected content for presentation filtering.

    INV-PRESENTATION-CONTEXTUAL-SELECT-001: builds the context dict used to
    resolve ``program.*`` references in presentation pool entries.
    """
    meta = resolver.lookup(content_asset_id)
    return {
        "program.rating": meta.rating,
        "program.rating_tag": _rating_to_tag(meta.rating),
    }


def _apply_contextual_select(
    entry: dict,
    candidates: list[str],
    resolver: AssetResolver,
    program_ctx: dict[str, Any],
) -> list[str]:
    """Filter pool candidates using entry-level select.where with program.* refs.

    INV-PRESENTATION-CONTEXTUAL-SELECT-001: resolves ``program.*`` references
    against the selected primary content's metadata, then filters candidates.

    Returns the filtered list.  If a ``program.*`` reference resolves to None
    (missing metadata), that filter clause is skipped — graceful degradation.
    """
    select = entry.get("select")
    if not select or "where" not in select:
        return candidates  # no entry-level filter

    where = select["where"]
    filtered = list(candidates)
    for field, spec in where.items():
        if not isinstance(spec, dict):
            continue
        for op, val in spec.items():
            # Resolve program.* references
            if isinstance(val, str) and val.startswith("program."):
                resolved_val = program_ctx.get(val)
            else:
                resolved_val = val

            if resolved_val is None:
                # Missing metadata — skip this filter clause (graceful)
                continue

            if op == "eq":
                if field == "tags":
                    # Tag containment: check if resolved_val is in asset tags.
                    # Tags are stored with TAG: prefix; try both raw and prefixed.
                    from retrovue.domain.tag_normalization import expand_tag_match_set
                    filtered = [
                        c for c in filtered
                        if resolved_val in expand_tag_match_set(
                            set(resolver.lookup(c).tags)
                        )
                    ]
                else:
                    filtered = [
                        c for c in filtered
                        if _asset_field(resolver, c, field) == resolved_val
                    ]
    return filtered


def _asset_field(resolver: AssetResolver, asset_id: str, field: str) -> Any:
    """Look up a single metadata field for an asset by ID."""
    meta = resolver.lookup(asset_id)
    return getattr(meta, field, None)


def _peek_content_selection(
    pool_assets: list[_PoolAsset],
    fill_mode: str,
    grid_ms: int,
    wrapper_ms: int,
    bleed: bool,
) -> str | None:
    """Determine which content asset will be selected without consuming it.

    Mirrors the selection logic of ``_assemble_single`` / ``_assemble_accumulate``
    to identify the primary content asset before presentation resolution.

    Returns the asset_id of the first eligible asset, or None if no content
    can be determined (assembly will raise later).
    """
    eligible = [a for a in pool_assets if getattr(a, "state", "ready") == "ready"
                and getattr(a, "approved_for_broadcast", True)]
    if not eligible:
        return None

    if fill_mode == "single":
        for asset in eligible:
            duration = getattr(asset, "duration_ms", 0)
            total = duration + wrapper_ms
            if not bleed and total > grid_ms:
                continue
            return asset.asset_id
        return None
    else:
        # accumulate: first eligible is always taken
        return eligible[0].asset_id if eligible else None


def _resolve_presentation_entries(
    entries: list,
    resolver: AssetResolver,
    rng: random.Random,
    *,
    pool_diagnostics: dict[str, PoolDiagnostics] | None = None,
    program_context: dict[str, Any] | None = None,
) -> list[_PoolAsset]:
    """Resolve a mixed list of presentation entries to assets.

    Each entry is either:
      - str: direct asset reference → resolver.lookup()
      - dict with "pool" key: pool reference → resolver.resolve_pool() + rng.choice()

    INV-PRESENTATION-CONTEXTUAL-SELECT-001: when ``program_context`` is provided
    and an entry has a ``select.where`` clause with ``program.*`` references,
    the pool candidates are filtered against the resolved content metadata.

    INV-DSL-MISSING-ASSET-NONFATAL-001: A pool matching zero assets is
    skipped with a warning — it does not prevent compilation.
    """
    assets: list[_PoolAsset] = []
    for entry in entries:
        if isinstance(entry, str):
            assets.append(_resolve_wrapper_asset(entry, resolver))
        elif isinstance(entry, dict) and "pool" in entry:
            pool_name = entry["pool"]
            try:
                candidates = resolver.resolve_pool(pool_name)
            except Exception:
                # INV-DSL-MISSING-ASSET-NONFATAL-001: degrade gracefully
                candidates = []

            # INV-PRESENTATION-CONTEXTUAL-SELECT-001: apply entry-level
            # contextual filters when program context is available.
            if candidates and program_context and "select" in entry:
                candidates = _apply_contextual_select(
                    entry, candidates, resolver, program_context,
                )

            if not candidates:
                # INV-POOL-RESOLUTION-VISIBILITY-001: emit diagnostics
                _emit_pool_diagnostics(
                    pool_name, resolver,
                    pool_diagnostics if pool_diagnostics is not None else {},
                )
                logger.warning(
                    "INV-DSL-MISSING-ASSET-NONFATAL-001: presentation pool "
                    "'%s' matched 0 assets — omitting segment",
                    pool_name,
                )
                continue
            chosen_id = rng.choice(candidates)
            assets.append(_resolve_wrapper_asset(chosen_id, resolver))
        else:
            raise AssemblyFault(
                f"Invalid presentation entry: {entry!r} "
                f"(expected string or {{pool: '...'}})"
            )
    return assets


# Sentinel value used in postroll_resolved to mark traffic directive position.
POSTROLL_TRAFFIC_MARKER = "_traffic_fill_position"


def _resolve_postroll_entries(
    entries: list,
    resolver: AssetResolver,
    rng: random.Random,
    *,
    pool_diagnostics: dict[str, PoolDiagnostics] | None = None,
    program_context: dict[str, Any] | None = None,
) -> list[_PoolAsset | str]:
    """Resolve postroll entries in declared order.

    Pool/asset entries become _PoolAsset. Traffic directives become
    POSTROLL_TRAFFIC_MARKER strings, preserving their declared position.
    INV-DSL-SEGMENT-ORDER-DETERMINISTIC-001.

    INV-PRESENTATION-CONTEXTUAL-SELECT-001: when ``program_context`` is
    provided, entry-level ``select.where`` with ``program.*`` refs is applied.
    """
    result: list[_PoolAsset | str] = []
    for entry in entries:
        if isinstance(entry, dict) and entry.get("type") == "traffic":
            result.append(POSTROLL_TRAFFIC_MARKER)
        elif isinstance(entry, str):
            result.append(_resolve_wrapper_asset(entry, resolver))
        elif isinstance(entry, dict) and "pool" in entry:
            pool_name = entry["pool"]
            try:
                candidates = resolver.resolve_pool(pool_name)
            except Exception:
                candidates = []

            # INV-PRESENTATION-CONTEXTUAL-SELECT-001
            if candidates and program_context and "select" in entry:
                candidates = _apply_contextual_select(
                    entry, candidates, resolver, program_context,
                )

            if not candidates:
                # INV-POOL-RESOLUTION-VISIBILITY-001: emit diagnostics
                _emit_pool_diagnostics(
                    pool_name, resolver,
                    pool_diagnostics if pool_diagnostics is not None else {},
                )
                logger.warning(
                    "INV-DSL-MISSING-ASSET-NONFATAL-001: postroll pool "
                    "'%s' matched 0 assets — omitting segment",
                    pool_name,
                )
                continue
            chosen_id = rng.choice(candidates)
            result.append(_resolve_wrapper_asset(chosen_id, resolver))
        else:
            raise AssemblyFault(
                f"Invalid postroll entry: {entry!r}"
            )
    return result


def _emit_pool_diagnostics(
    pool_name: str,
    resolver: AssetResolver,
    pool_diagnostics: dict[str, PoolDiagnostics],
) -> None:
    """Run query_with_diagnostics for a pool and log + store the result.

    INV-POOL-RESOLUTION-VISIBILITY-001: every empty pool must be explainable.
    Only calls query_with_diagnostics if the resolver supports it; otherwise
    falls back to logging without diagnostics (backward compatible).
    """
    query_with_diag = getattr(resolver, "query_with_diagnostics", None)
    if query_with_diag is None:
        return

    # Retrieve match criteria for this pool
    pools_dict = getattr(resolver, "_pools", {})
    if pool_name not in pools_dict:
        return

    match = pools_dict[pool_name].get("match", {})
    _, diag = query_with_diag(match)

    pool_diagnostics[pool_name] = diag
    logger.warning(
        "INV-POOL-RESOLUTION-VISIBILITY-001: pool_empty | "
        "pool_name=%s | total_considered=%d | "
        "excluded_by_type=%d | excluded_by_tags=%d | "
        "excluded_by_rating=%d | excluded_by_duration=%d | "
        "excluded_by_editorial=%d | matched=%d",
        pool_name,
        diag.total_considered,
        diag.excluded_by_type,
        diag.excluded_by_tags,
        diag.excluded_by_rating,
        diag.excluded_by_duration,
        diag.excluded_by_editorial,
        diag.matched,
    )


def _resolve_wrapper_asset(
    asset_ref: str,
    resolver: AssetResolver,
) -> _PoolAsset:
    """Resolve an intro/outro asset reference into a _PoolAsset."""
    meta = resolver.lookup(asset_ref)
    return _PoolAsset(
        asset_id=asset_ref,
        duration_ms=int(meta.duration_sec * 1000),
    )


def _build_pool_assets(
    asset_ids: list[str],
    resolver: AssetResolver,
) -> list[_PoolAsset]:
    """Convert resolver asset IDs into _PoolAsset objects."""
    assets: list[_PoolAsset] = []
    for aid in asset_ids:
        meta = resolver.lookup(aid)
        assets.append(_PoolAsset(
            asset_id=aid,
            duration_ms=int(meta.duration_sec * 1000),
        ))
    return assets


def _apply_progression(
    *,
    candidate_ids: list[str],
    progression: str,
    program_ref: str,
    channel_id: str,
    rng: random.Random,
    fill_mode: str,
    grid_blocks: int,
    grid_minutes: int,
    seed: int | None,
    broadcast_day: str = "",
    schedule_layer: str = "all_day",
    start_time: str = "00:00",
    run_id: str | None = None,
    exhaustion_policy: str = "wrap",
    execution_index: int = 0,
    run_store: object | None = None,
    emissions_per_occurrence: int = 1,
    prior_same_day_emissions: int = 0,
) -> list[str]:
    """Order candidate asset IDs according to progression mode.

    For single fill_mode, returns a list starting with the selected asset
    followed by remaining candidates (for fallback if the first is rejected
    by bleed constraints).

    For accumulate fill_mode, returns the full candidate list in
    progression order.
    """
    if progression == "sequential":
        return _apply_sequential_progression(
            candidate_ids=candidate_ids,
            program_ref=program_ref,
            channel_id=channel_id,
            broadcast_day=broadcast_day,
            schedule_layer=schedule_layer,
            start_time=start_time,
            run_id=run_id,
            exhaustion_policy=exhaustion_policy,
            execution_index=execution_index,
            fill_mode=fill_mode,
            run_store=run_store,
            emissions_per_occurrence=emissions_per_occurrence,
            prior_same_day_emissions=prior_same_day_emissions,
        )

    elif progression == "random":
        shuffled = list(candidate_ids)
        rng.shuffle(shuffled)
        return shuffled

    elif progression == "shuffle":
        shuffled = list(candidate_ids)
        rng.shuffle(shuffled)
        return shuffled

    else:
        # Fallback: natural order
        return list(candidate_ids)


def _derive_run_id(
    channel_id: str,
    schedule_layer: str,
    start_time: str,
    program_ref: str,
) -> str:
    """Derive a deterministic run identity from placement components.

    Contract: docs/contracts/episode_progression.md § Identity Rules
    """
    return f"{channel_id}:{schedule_layer}:{start_time}:{program_ref}"


def _apply_sequential_progression(
    *,
    candidate_ids: list[str],
    program_ref: str,
    channel_id: str,
    broadcast_day: str,
    schedule_layer: str,
    start_time: str = "00:00",
    run_id: str | None,
    exhaustion_policy: str,
    execution_index: int,
    fill_mode: str,
    run_store: object | None = None,
    emissions_per_occurrence: int = 1,
    prior_same_day_emissions: int = 0,
) -> list[str]:
    """Select episodes using the canonical episode progression resolver.

    Contract: docs/contracts/episode_progression.md
    Invariants: INV-EPISODE-PROGRESSION-001 through 012

    Uses calendar-based occurrence counting scaled by emissions_per_occurrence.
    Episode selection is a pure function of the run record, broadcast day,
    and the block's position among same-run_id blocks on that day.

    The run record (anchor, placement_days, exhaustion_policy) is loaded
    from the ProgressionRunStore.  If no record exists, a new one is created
    with anchor_date = migration epoch (2026-01-05).
    """
    from datetime import date as date_type

    if not broadcast_day or not candidate_ids:
        return list(candidate_ids)

    episode_count = len(candidate_ids)
    target_date = date_type.fromisoformat(broadcast_day)

    # Resolve placement_days from schedule layer key.
    # dsl_layer_key_to_mask raises on unknown keys; fall back to DAILY (127).
    try:
        placement_days = dsl_layer_key_to_mask(schedule_layer)
    except ValueError:
        placement_days = 127  # DAILY

    # Derive the effective run identity using block's actual start_time.
    effective_run_id = run_id or _derive_run_id(
        channel_id, schedule_layer, start_time, program_ref,
    )

    # Ensure a run store is available (default to in-memory for tests).
    if run_store is None:
        from retrovue.runtime.progression_run_store import InMemoryProgressionRunStore
        run_store = InMemoryProgressionRunStore()

    # Load or create the ProgressionRun record.
    run_info = run_store.load(channel_id, effective_run_id)

    if run_info is None:
        # First encounter — create and persist a new ProgressionRun.
        #
        # Anchor selection: use the MIGRATION EPOCH (2026-01-05, Monday)
        # for backward compatibility with the pre-persistence era.
        anchor = _find_matching_anchor(_MIGRATION_EPOCH, placement_days)

        run_info = run_store.create(
            channel_id=channel_id,
            run_id=effective_run_id,
            content_source_id=program_ref,
            anchor_date=anchor,
            anchor_episode_index=0,
            placement_days=placement_days,
            exhaustion_policy=exhaustion_policy,
        )

    # INV-EPISODE-PROGRESSION-009: Multi-execution sequencing.
    # INV-EPISODE-PROGRESSION-003: Monotonic advancement scales with emissions.
    #
    # Formula: raw_index = anchor_episode_index
    #                    + (occurrences × emissions_per_occurrence)
    #                    + prior_same_day_emissions
    #                    + execution_index
    #
    # - occurrences: matching calendar days in [anchor, target)
    # - emissions_per_occurrence: total executions across ALL blocks sharing
    #   this run_id on a single matching day
    # - prior_same_day_emissions: cumulative executions from earlier blocks
    #   sharing this run_id on the SAME day (schedule order)
    # - execution_index: this block's execution offset (0..slots/grid_blocks-1)
    occ = count_occurrences(run_info.anchor_date, target_date, run_info.placement_days)
    raw_index = (run_info.anchor_episode_index
                 + (occ * emissions_per_occurrence)
                 + prior_same_day_emissions
                 + execution_index)

    selected_index = apply_wrap_policy(raw_index, episode_count, run_info.wrap_policy)

    if selected_index is None:
        # Exhaustion under "stop" policy — return empty or filler.
        # The caller handles empty candidate lists gracefully.
        return list(candidate_ids)

    # Place the selected episode first; rest follow for fallback.
    selected = candidate_ids[selected_index]
    if fill_mode == "single":
        rest = [c for c in candidate_ids if c != selected]
        return [selected] + rest
    else:
        # Accumulate: return full catalog starting from selected_index
        rotated = candidate_ids[selected_index:] + candidate_ids[:selected_index]
        return rotated


def _find_matching_anchor(origin: object, placement_days: int) -> object:
    """Find the origin date itself, or the nearest future matching date.

    Contract: episode_progression.md § Anchor Rules:
        anchor_date MUST match the placement_days pattern.

    Walks forward up to 6 days from *origin* to find a day whose
    weekday bit is set in *placement_days*.
    """
    # Origin itself matches — most common case (epoch is Monday).
    if placement_days & (1 << origin.weekday()):
        return origin

    # Walk forward up to 6 days to find a matching date.
    for i in range(1, 7):
        candidate = origin + _timedelta(days=i)
        if placement_days & (1 << candidate.weekday()):
            return candidate

    # Should never happen with valid placement_days (1-127).
    return origin
