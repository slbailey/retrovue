"""Program Assembly — V2 pipeline stage (channel_dsl.md §5–§6).

Bridges schedule compilation (progression, timing) with program definition
(fill_mode, bleed, intro/outro). Receives a resolved schedule block and
program definition, queries assets from the pool via the resolver, applies
progression ordering, and delegates to assemble_program for fill/bleed logic.

Entry point: assemble_schedule_block()
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date as _date, timedelta as _timedelta
from typing import Any

# Migration epoch — backward-compatible anchor origin for channels that
# predate ProgressionRun persistence.  Monday 2026-01-05 was the bootstrap
# epoch used before persistent runs were introduced.  Every placement
# pattern (weekday, weekend, daily, single DOW) has a matching date
# within the first 7 days from this Monday.
_MIGRATION_EPOCH = _date(2026, 1, 5)

from retrovue.runtime.asset_resolver import AssetResolver
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
    bleed = program_def.get("bleed", False)
    intro_ref = program_def.get("intro")
    outro_ref = program_def.get("outro")
    presentation_refs = program_def.get("presentation")

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
        bleed=bleed,
        intro=intro_ref,
        outro=outro_ref,
        presentation=presentation_refs,
        grid_blocks_max=grid_blocks_max,
    )

    # Resolve intro/outro assets if referenced
    intro_asset = _resolve_wrapper_asset(intro_ref, resolver) if intro_ref else None
    outro_asset = _resolve_wrapper_asset(outro_ref, resolver) if outro_ref else None

    # Get all pool candidates from the resolver
    pool_meta = resolver.lookup(pool_name)
    all_candidate_ids = list(pool_meta.tags)
    if not all_candidate_ids:
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
            bleed=bleed,
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

        # Resolve presentation entries per execution (pool entries may vary)
        presentation_assets = None
        if presentation_refs:
            presentation_assets = _resolve_presentation_entries(
                presentation_refs, resolver, rng,
            )

        result = assemble_program(
            prog,
            pool,
            grid_minutes=grid_minutes,
            block_start_ms=running_offset_ms,
            intro_asset=intro_asset,
            outro_asset=outro_asset,
            presentation_assets=presentation_assets,
        )

        results.append(result)
        running_offset_ms = result.next_block_start_offset_ms

    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_presentation_entries(
    entries: list,
    resolver: AssetResolver,
    rng: random.Random,
) -> list[_PoolAsset]:
    """Resolve a mixed list of presentation entries to assets.

    Each entry is either:
      - str: direct asset reference → resolver.lookup()
      - dict with "pool" key: pool reference → resolver.resolve_pool() + rng.choice()
    """
    assets: list[_PoolAsset] = []
    for entry in entries:
        if isinstance(entry, str):
            assets.append(_resolve_wrapper_asset(entry, resolver))
        elif isinstance(entry, dict) and "pool" in entry:
            pool_name = entry["pool"]
            candidates = resolver.resolve_pool(pool_name)
            if not candidates:
                raise AssemblyFault(
                    f"Presentation pool '{pool_name}' matched 0 assets"
                )
            chosen_id = rng.choice(candidates)
            assets.append(_resolve_wrapper_asset(chosen_id, resolver))
        else:
            raise AssemblyFault(
                f"Invalid presentation entry: {entry!r} "
                f"(expected string or {{pool: '...'}})"
            )
    return assets


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
    bleed: bool,
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
