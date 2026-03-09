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
from typing import Any

from retrovue.runtime.asset_resolver import AssetResolver
from retrovue.runtime.program_definition import (
    AssemblyFault,
    AssemblyResult,
    AssemblySegment,
    ProgramDefinition,
    assemble_program,
)
from retrovue.runtime.progression_cursor import (
    CursorStore,
    ScheduleBlockIdentity,
    advance_cursor,
    initialize_cursor,
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
    cursor_store: CursorStore | None = None,
    channel_id: str = "",
) -> list[AssemblyResult]:
    """Assemble all program executions for a single schedule block.

    This is the V2 Program Assembly entry point called by the schedule
    compiler after Schedule Resolution and Program Resolution.

    Returns one AssemblyResult per program execution.

    Raises:
        AssemblyFault: if any execution cannot assemble valid content.
    """
    grid_blocks = program_def.get("grid_blocks", 1)
    fill_mode = program_def.get("fill_mode", "single")
    bleed = program_def.get("bleed", False)
    intro_ref = program_def.get("intro")
    outro_ref = program_def.get("outro")

    # INV-PROGRAM-GRID-001: slots must be exact multiple of grid_blocks
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
    )

    if cursor_store is None:
        cursor_store = CursorStore()

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
            cursor_store=cursor_store,
            rng=rng,
            fill_mode=fill_mode,
            grid_blocks=grid_blocks,
            grid_minutes=grid_minutes,
            bleed=bleed,
            seed=seed,
        )

        # Build pool adapter with progression-ordered assets
        pool_assets = _build_pool_assets(ordered_ids, resolver)
        pool = _ProgressionPool(name=pool_name, assets=pool_assets)

        result = assemble_program(
            prog,
            pool,
            grid_minutes=grid_minutes,
            block_start_ms=running_offset_ms,
            intro_asset=intro_asset,
            outro_asset=outro_asset,
        )

        results.append(result)
        running_offset_ms = result.next_block_start_offset_ms

    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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
    cursor_store: CursorStore,
    rng: random.Random,
    fill_mode: str,
    grid_blocks: int,
    grid_minutes: int,
    bleed: bool,
    seed: int | None,
) -> list[str]:
    """Order candidate asset IDs according to progression mode.

    For single fill_mode, returns a list starting with the selected asset
    followed by remaining candidates (for fallback if the first is rejected
    by bleed constraints).

    For accumulate fill_mode, returns the full candidate list in
    progression order.
    """
    if progression == "sequential":
        identity = ScheduleBlockIdentity(
            channel_id=channel_id,
            schedule_layer="compilation",
            start_time="00:00",
            program_ref=program_ref,
        )
        cursor = cursor_store.load(identity)
        if cursor is None:
            cursor = initialize_cursor(identity)

        if fill_mode == "single":
            # Advance cursor once, put selected first, then rest for fallback
            result = advance_cursor(
                cursor=cursor,
                pool_assets=candidate_ids,
                progression="sequential",
            )
            cursor_store.save(result.cursor)
            selected = result.selected_asset
            rest = [c for c in candidate_ids if c != selected]
            return [selected] + rest
        else:
            # Accumulate: build ordered list by advancing cursor repeatedly
            ordered: list[str] = []
            seen: set[str] = set()
            for _ in range(len(candidate_ids)):
                result = advance_cursor(
                    cursor=cursor,
                    pool_assets=candidate_ids,
                    progression="sequential",
                )
                cursor_store.save(result.cursor)
                cursor = result.cursor
                if result.selected_asset in seen:
                    break
                seen.add(result.selected_asset)
                ordered.append(result.selected_asset)
            return ordered

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
