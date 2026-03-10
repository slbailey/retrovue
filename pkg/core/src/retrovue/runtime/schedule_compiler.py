"""
Programming DSL Schedule Compiler (v2).

Pure-function compiler that reads a V2 YAML DSL schedule definition,
resolves assets, validates constraints, and emits a normalized
Program Schedule — grid-aligned program blocks only.

Pipeline:
    YAML DSL → schedule resolver → program execution plan →
    program assembly → break detection → traffic → playlog events

No breaks, no commercials, no bumpers, no station IDs.
The Program Schedule is Tier 1; Playout Log expansion is handled
separately by playout_log_expander.py.

No database writes. No global state. Receives an AssetResolver instance.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, date
from typing import Any

import yaml

from retrovue.runtime.asset_resolver import AssetResolver

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COMPILER_VERSION = "3.0.0"
BROADCAST_DAY_START_HOUR = 6  # 06:00 local
NETWORK_GRID_MINUTES = 30
PREMIUM_GRID_MINUTES = 15

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CompileError(Exception):
    """Base error for compilation failures."""
    pass


class ValidationError(CompileError):
    """Raised when DSL validation fails."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"Validation failed with {len(errors)} error(s): {'; '.join(errors)}")


class AssetResolutionError(CompileError):
    """Raised when an asset cannot be resolved."""
    pass


# ---------------------------------------------------------------------------
# Program Block dataclass
# ---------------------------------------------------------------------------


@dataclass
class ProgramBlockOutput:
    """A compiled program block for the program schedule."""

    title: str
    asset_id: str
    start_at: datetime
    slot_duration_sec: int
    episode_duration_sec: int
    collection: str | None = None
    selector: dict[str, Any] | None = None
    compiled_segments: list[dict[str, Any]] | None = None
    traffic_profile: str | None = None

    def end_at(self) -> datetime:
        return self.start_at + timedelta(seconds=self.slot_duration_sec)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "title": self.title,
            "asset_id": self.asset_id,
            "start_at": self.start_at.isoformat(),
            "slot_duration_sec": self.slot_duration_sec,
            "episode_duration_sec": self.episode_duration_sec,
        }
        if self.collection:
            d["collection"] = self.collection
        if self.selector:
            d["selector"] = self.selector
        if self.compiled_segments:
            d["compiled_segments"] = self.compiled_segments
        if self.traffic_profile:
            d["traffic_profile"] = self.traffic_profile
        return d


# ---------------------------------------------------------------------------
# Grid alignment
# ---------------------------------------------------------------------------


def _grid_slot_duration(grid_minutes: int, episode_duration_sec: int) -> int:
    """Calculate the grid slot duration that fits an episode."""
    slot_sec = grid_minutes * 60
    slots_needed = max(1, -(-episode_duration_sec // slot_sec))  # ceil division
    return slots_needed * slot_sec


def _validate_grid_alignment(blocks: list[ProgramBlockOutput], grid_minutes: int) -> None:
    """Assert all blocks are grid-aligned. Raises CompileError on violation.

    Uses epoch-second math for wall-clock alignment independent of hour boundaries
    and timezone edge cases. Does not depend on .minute arithmetic.

    INV-BLEED-NO-GAP-001: Scope applies only to ProgramBlockOutput emitted by
    DSL schedule compilation. Does NOT apply to downstream playlog segmentation
    or ad pod sub-blocks.
    """
    slot_unit = grid_minutes * 60
    for block in blocks:
        if block.start_at.tzinfo is None or block.start_at.utcoffset() != timedelta(0):
            raise CompileError(
                f"Grid violation: block '{block.title}' start_at={block.start_at.isoformat()} "
                f"is not UTC (utcoffset={block.start_at.utcoffset()}). "
                f"All ProgramBlockOutput times MUST be timezone-aware UTC."
            )
        start_epoch = int(block.start_at.timestamp())
        if start_epoch % slot_unit != 0:
            raise CompileError(
                f"Grid violation: block '{block.title}' start_at={block.start_at.isoformat()} "
                f"is not aligned to {grid_minutes}-minute grid "
                f"(epoch {start_epoch} % {slot_unit} = {start_epoch % slot_unit})"
            )
        if block.slot_duration_sec % slot_unit != 0:
            raise CompileError(
                f"Grid violation: block '{block.title}' slot_duration_sec={block.slot_duration_sec} "
                f"is not a multiple of {slot_unit}s ({grid_minutes}min grid)"
            )


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def channel_seed(channel_id: str) -> int:
    """Derive a deterministic channel-specific seed. Stable across process lifetimes.

    INV-SCHEDULE-SEED-DETERMINISTIC-001: Uses hashlib (cryptographic, stable),
    not Python's hash() (randomized per process via PYTHONHASHSEED).
    """
    return int(hashlib.sha256(channel_id.encode("utf-8")).hexdigest(), 16) % 100000


def compilation_seed(channel_id: str, broadcast_day: str) -> int:
    """Day-specific compilation seed. Deterministic for same (channel, day).

    INV-SCHEDULE-SEED-DAY-VARIANCE-001: Incorporates broadcast_day so that
    different days produce different movie selections while rebuilding
    the same day always produces identical output.
    """
    raw = f"{channel_id}:{broadcast_day}"
    return int(hashlib.sha256(raw.encode("utf-8")).hexdigest(), 16) % (2**31)


def _window_seed(seed: int | None, start_str: str) -> int:
    """Derive a window-specific seed by mixing the window start time.

    INV-SCHEDULE-SEED-DAY-VARIANCE-001 Rule 2: Two windows at different
    start times on the same day receive different seeds.
    """
    return int(hashlib.sha256(f"{seed}:{start_str}".encode("utf-8")).hexdigest(), 16) % (2**31)


# ---------------------------------------------------------------------------
# Time parsing
# ---------------------------------------------------------------------------


def _parse_time(time_str: str, broadcast_day: str, tz_name: str) -> datetime:
    """Parse HH:MM into an aware datetime for the broadcast day."""
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(tz_name)
    bd = date.fromisoformat(broadcast_day)
    parts = time_str.split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0

    if hour < BROADCAST_DAY_START_HOUR:
        bd = bd + timedelta(days=1)

    return datetime(bd.year, bd.month, bd.day, hour, minute, tzinfo=tz)


# ---------------------------------------------------------------------------
# Day-of-week schedule resolution (layered merge)
# ---------------------------------------------------------------------------

VALID_SCHEDULE_KEYS = frozenset({
    "all_day", "weekdays", "weekends",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
})

DOW_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

WEEKDAY_NAMES = frozenset({"monday", "tuesday", "wednesday", "thursday", "friday"})
WEEKEND_NAMES = frozenset({"saturday", "sunday"})


def _blocks_to_dict(blocks: list[dict]) -> dict[str, dict]:
    """Index a list of V2 block defs by their 'start' time."""
    result: dict[str, dict] = {}
    for b in blocks:
        if isinstance(b, dict):
            key = b.get("start", "")
            result[key] = b
    return result


def _ensure_list(val: Any) -> list[dict]:
    """Normalise a schedule value to a list of block defs."""
    if isinstance(val, list):
        return val
    if isinstance(val, dict):
        return [val]
    return []


def resolve_day_schedule(dsl: dict[str, Any], target_date: date) -> list[dict[str, Any]]:
    """
    Resolve the schedule blocks for a specific date by merging layers.

    Layer precedence (highest to lowest):
    1. Specific DOW (monday, tuesday, ...)
    2. Group (weekdays, weekends)
    3. Default (all_day)

    Layers MERGE by start time. Higher layers override specific start-time
    blocks but pass through all others from lower layers.
    """
    schedule = dsl.get("schedule", {})

    # Base layer: all_day
    merged = _blocks_to_dict(_ensure_list(schedule.get("all_day", [])))
    # Track which schedule layer each block came from (for derived placement identity)
    layer_map: dict[str, str] = {k: "all_day" for k in merged}

    # Group layer
    dow_index = target_date.weekday()  # 0=Monday
    dow_name = DOW_NAMES[dow_index]

    if dow_name in WEEKDAY_NAMES and "weekdays" in schedule:
        group_blocks = _blocks_to_dict(_ensure_list(schedule["weekdays"]))
        merged.update(group_blocks)
        for k in group_blocks:
            layer_map[k] = "weekdays"
    elif dow_name in WEEKEND_NAMES and "weekends" in schedule:
        group_blocks = _blocks_to_dict(_ensure_list(schedule["weekends"]))
        merged.update(group_blocks)
        for k in group_blocks:
            layer_map[k] = "weekends"

    # Specific DOW layer
    if dow_name in schedule:
        dow_blocks = _blocks_to_dict(_ensure_list(schedule[dow_name]))
        merged.update(dow_blocks)
        for k in dow_blocks:
            layer_map[k] = dow_name

    # Sort by start time and return as list, annotated with source layer
    sorted_keys = sorted(merged.keys())
    result = []
    for k in sorted_keys:
        block = merged[k]
        block["_schedule_layer"] = layer_map.get(k, "all_day")
        result.append(block)
    return result


# ---------------------------------------------------------------------------
# Channel template helpers
# ---------------------------------------------------------------------------


def get_channel_template(dsl: dict[str, Any]) -> str:
    return dsl.get("template", "network_television")


def get_grid_minutes(template: str) -> int:
    if template == "premium_movie":
        return PREMIUM_GRID_MINUTES
    return NETWORK_GRID_MINUTES


# ---------------------------------------------------------------------------
# V2 Program Resolution (channel_dsl.md §5–§6)
# ---------------------------------------------------------------------------


def _compile_program_block(
    block_def: dict[str, Any],
    programs: dict[str, Any],
    broadcast_day: str,
    tz_name: str,
    resolver: AssetResolver,
    grid_minutes: int,
    seed: int | None = None,
    channel_id: str = "",
    run_store: object = None,
    emissions_per_occurrence: int = 1,
    prior_same_day_emissions: int = 0,
) -> list[ProgramBlockOutput]:
    """Compile a V2 schedule block into program blocks.

    V2 DSL shape (channel_dsl.md §5–§6):
        - start: "06:00"
          slots: 48
          program: cheers_30
          progression: sequential

    Pipeline: Schedule Resolver → Program Resolution → Program Assembly

    Delegates to program_assembly.assemble_schedule_block() for fill_mode,
    bleed, grid_blocks, and intro/outro handling.
    """
    from retrovue.runtime.program_assembly import assemble_schedule_block
    from retrovue.runtime.program_definition import AssemblyFault

    start_str = block_def.get("start", "06:00")
    slots = block_def.get("slots", 1)
    if not isinstance(slots, int):
        slots = len(slots)
    progression = block_def.get("progression", "sequential")

    # Episode progression DSL fields (canonical contract: episode_progression.md)
    run_id = block_def.get("run_id")
    exhaustion_policy = block_def.get("exhaustion", "wrap")
    schedule_layer = block_def.get("_schedule_layer", "all_day")

    # INV-SBLOCK-PROGRAM-001: normalize program field to list
    program_field = block_def.get("program", "")
    if isinstance(program_field, str):
        program_refs = [program_field] if program_field else []
    elif isinstance(program_field, list):
        program_refs = program_field
    else:
        program_refs = []

    # INV-SBLOCK-PROGRAM-001: non-empty program reference required
    if not program_refs:
        raise AssemblyFault(
            "INV-SBLOCK-PROGRAM-001: schedule block 'program' must be "
            "a non-empty string or non-empty list of strings"
        )

    # INV-SBLOCK-PROGRAM-002: all members must resolve
    for ref in program_refs:
        if ref not in programs:
            raise AssemblyFault(
                f"INV-SBLOCK-PROGRAM-002: program '{ref}' not found in "
                f"program definitions"
            )

    # INV-SBLOCK-PROGRAM-006: uniform grid sizing across list.
    # All programs must use the same sizing mode (all grid_blocks or all
    # grid_blocks_max) and the same value.
    is_dynamic = any(programs[ref].get("grid_blocks_max") is not None for ref in program_refs)
    if is_dynamic:
        gbm_values = {programs[ref].get("grid_blocks_max") for ref in program_refs}
        # All must have grid_blocks_max set
        if None in gbm_values:
            raise AssemblyFault(
                "INV-SBLOCK-PROGRAM-006: program list mixes grid_blocks and "
                "grid_blocks_max — all must use the same sizing mode"
            )
        if len(gbm_values) > 1:
            raise AssemblyFault(
                f"INV-SBLOCK-PROGRAM-006: program list has mismatched "
                f"grid_blocks_max values: {gbm_values}"
            )
        uniform_grid_blocks_max = gbm_values.pop()
    else:
        grid_blocks_values = {programs[ref].get("grid_blocks", 1) for ref in program_refs}
        if len(grid_blocks_values) > 1:
            raise AssemblyFault(
                f"INV-SBLOCK-PROGRAM-006: program list has mismatched grid_blocks "
                f"values: {grid_blocks_values}"
            )

    current_time = _parse_time(start_str, broadcast_day, tz_name)

    # INV-SCHEDULE-SEED-DAY-VARIANCE-001 Rule 2: window-specific seed
    wseed = _window_seed(seed, start_str)
    rng = __import__("random").Random(wseed)

    blocks: list[ProgramBlockOutput] = []

    if is_dynamic:
        # Greedy packing: fill slots budget by selecting movies one at a
        # time. Each movie takes ceil(duration / grid_slot) blocks.
        remaining_slots = slots
        exec_idx = 0
        slot_sec = grid_minutes * 60

        while remaining_slots > 0:
            chosen_ref = rng.choice(program_refs) if len(program_refs) > 1 else program_refs[0]
            prog_def = programs[chosen_ref]
            pool = prog_def.get("pool", chosen_ref)

            assembly_results = assemble_schedule_block(
                program_ref=chosen_ref,
                program_def=prog_def,
                pool_name=pool,
                slots=1,  # single execution — dynamic mode
                progression=progression,
                grid_minutes=grid_minutes,
                resolver=resolver,
                seed=wseed + exec_idx,
                channel_id=channel_id,
                broadcast_day=broadcast_day,
                schedule_layer=schedule_layer,
                start_time=start_str,
                run_id=run_id,
                exhaustion_policy=exhaustion_policy,
                run_store=run_store,
                emissions_per_occurrence=emissions_per_occurrence,
                prior_same_day_emissions=prior_same_day_emissions + exec_idx,
            )

            for result in assembly_results:
                content_segments = [
                    s for s in result.segments if s.segment_type == "content"
                ]
                if not content_segments:
                    continue

                primary = content_segments[0]
                ep_meta = resolver.lookup(primary.asset_id)

                # Dynamic slot sizing: ceil(total_runtime / grid_slot)
                needed_blocks = max(1, -(-result.total_runtime_ms // (slot_sec * 1000)))
                needed_blocks = min(needed_blocks, uniform_grid_blocks_max, remaining_slots)
                slot_duration = needed_blocks * slot_sec

                # Bleed: if content exceeds even the capped slot, expand
                if prog_def.get("bleed", False) and result.total_runtime_ms > slot_duration * 1000:
                    slot_duration = _grid_slot_duration(grid_minutes, result.total_runtime_ms // 1000)
                    needed_blocks = slot_duration // slot_sec

                block = ProgramBlockOutput(
                    title=ep_meta.title or chosen_ref,
                    asset_id=primary.asset_id,
                    start_at=current_time,
                    slot_duration_sec=slot_duration,
                    episode_duration_sec=ep_meta.duration_sec,
                    collection=pool,
                    selector={
                        "mode": progression,
                        "pool": pool,
                        "program": chosen_ref,
                        "fill_mode": prog_def.get("fill_mode", "single"),
                    },
                    compiled_segments=[
                        {
                            "segment_type": s.segment_type,
                            "asset_id": s.asset_id,
                            "duration_ms": s.duration_ms,
                        }
                        for s in result.segments
                    ],
                    traffic_profile=block_def.get("traffic_profile"),
                )
                blocks.append(block)
                current_time = block.end_at()
                remaining_slots -= needed_blocks

            exec_idx += 1
    else:
        # Fixed grid_blocks: divide slots evenly (original behavior).
        uniform_grid_blocks = grid_blocks_values.pop()
        executions = slots // uniform_grid_blocks

        for exec_idx in range(executions):
            chosen_ref = rng.choice(program_refs) if len(program_refs) > 1 else program_refs[0]
            prog_def = programs[chosen_ref]
            pool = prog_def.get("pool", chosen_ref)

            assembly_results = assemble_schedule_block(
                program_ref=chosen_ref,
                program_def=prog_def,
                pool_name=pool,
                slots=uniform_grid_blocks,  # single execution worth of slots
                progression=progression,
                grid_minutes=grid_minutes,
                resolver=resolver,
                seed=wseed + exec_idx,  # vary seed per execution
                channel_id=channel_id,
                broadcast_day=broadcast_day,
                schedule_layer=schedule_layer,
                start_time=start_str,
                run_id=run_id,
                exhaustion_policy=exhaustion_policy,
                run_store=run_store,
                emissions_per_occurrence=emissions_per_occurrence,
                prior_same_day_emissions=prior_same_day_emissions + exec_idx,
            )

            # Convert AssemblyResults into ProgramBlockOutputs
            for result in assembly_results:
                content_segments = [
                    s for s in result.segments if s.segment_type == "content"
                ]
                if not content_segments:
                    continue

                primary = content_segments[0]
                ep_meta = resolver.lookup(primary.asset_id)
                grid_blocks = prog_def.get("grid_blocks", 1)
                slot_duration = grid_blocks * grid_minutes * 60

                if prog_def.get("bleed", False) and result.total_runtime_ms > slot_duration * 1000:
                    slot_duration = _grid_slot_duration(grid_minutes, result.total_runtime_ms // 1000)

                block = ProgramBlockOutput(
                    title=ep_meta.title or chosen_ref,
                    asset_id=primary.asset_id,
                    start_at=current_time,
                    slot_duration_sec=slot_duration,
                    episode_duration_sec=ep_meta.duration_sec,
                    collection=pool,
                    selector={
                        "mode": progression,
                        "pool": pool,
                        "program": chosen_ref,
                        "fill_mode": prog_def.get("fill_mode", "single"),
                    },
                    compiled_segments=[
                        {
                            "segment_type": s.segment_type,
                            "asset_id": s.asset_id,
                            "duration_ms": s.duration_ms,
                        }
                        for s in result.segments
                    ],
                    traffic_profile=block_def.get("traffic_profile"),
                )
                blocks.append(block)
                current_time = block.end_at()

    return blocks


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_start_grid_alignment(start_time_str: str, grid_minutes: int) -> list[str]:
    """Check that a start time string aligns to grid boundaries."""
    errors: list[str] = []
    parts = start_time_str.split(":")
    if len(parts) >= 2:
        minute = int(parts[1])
        if minute % grid_minutes != 0:
            errors.append(
                f"Start time {start_time_str} is not aligned to {grid_minutes}-minute grid"
            )
    return errors


def validate_dsl(dsl: dict[str, Any], resolver: AssetResolver) -> list[str]:
    """Validate a parsed V2 DSL structure. Returns error messages (empty = valid)."""
    errors: list[str] = []

    for f in ("channel", "broadcast_day", "timezone"):
        if f not in dsl:
            errors.append(f"Missing required field: {f}")

    if "schedule" not in dsl:
        errors.append("Missing required field: schedule")
        return errors

    template = get_channel_template(dsl)
    grid_min = get_grid_minutes(template)
    schedule = dsl.get("schedule", {})

    # Validate grid alignment of schedule block start times
    for day_key, day_value in schedule.items():
        if isinstance(day_value, dict):
            start = day_value.get("start", "")
            if start:
                errors.extend(_validate_start_grid_alignment(start, grid_min))
        elif isinstance(day_value, list):
            for item in day_value:
                if isinstance(item, dict):
                    start = item.get("start", "")
                    if start:
                        errors.extend(_validate_start_grid_alignment(start, grid_min))

    return errors


def validate_program_blocks(blocks: list[ProgramBlockOutput]) -> list[str]:
    """Validate compiled program blocks for overlaps."""
    errors: list[str] = []
    sorted_blocks = sorted(blocks, key=lambda b: b.start_at)
    for i in range(len(sorted_blocks) - 1):
        current = sorted_blocks[i]
        nxt = sorted_blocks[i + 1]
        if current.end_at() > nxt.start_at:
            errors.append(
                f"Overlap: {current.title}@{current.start_at.isoformat()} "
                f"ends at {current.end_at().isoformat()} but "
                f"{nxt.title}@{nxt.start_at.isoformat()} starts before"
            )
    return errors


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_dsl(yaml_text: str) -> dict[str, Any]:
    """Parse YAML DSL text into a dict.

    Uses a loader that ignores !include tags (treated as None)
    so channel YAML files with !include directives can be parsed
    without error by the schedule compiler.
    """
    loader = type('DSLLoader', (yaml.SafeLoader,), {})
    loader.add_constructor('!include', lambda loader, node: None)
    return yaml.load(yaml_text, Loader=loader)


def compile_schedule(
    dsl: dict[str, Any],
    resolver: AssetResolver,
    *,
    dsl_path: str = "unknown",
    git_commit: str = "0000000",
    seed: int | None = 42,
    cursor_store: object = None,  # deprecated, unused — retained for caller compat
    run_store: object = None,
) -> dict[str, Any]:
    """
    Compile a V2 DSL definition into a Program Schedule.

    Pipeline:
        YAML DSL → schedule resolver → program execution plan →
        program assembly → compaction → grid validation → output

    Output contains grid-aligned program blocks only.
    No breaks, commercials, bumpers, or station IDs.

    Pure function — no DB writes, no globals.
    """
    # Register pools from DSL with the resolver (if supported)
    pools = dsl.get("pools", {})
    if pools and hasattr(resolver, "register_pools"):
        resolver.register_pools(pools)

    # Validate
    errors = validate_dsl(dsl, resolver)
    if errors:
        raise ValidationError(errors)

    channel_id = dsl["channel"]
    broadcast_day = str(dsl["broadcast_day"])
    tz_name = dsl["timezone"]
    template = get_channel_template(dsl)
    grid_minutes = get_grid_minutes(template)
    programs_defs = dsl.get("programs", {})

    # Schedule resolution: resolve DOW layering to flat block list
    all_blocks: list[ProgramBlockOutput] = []
    schedule = dsl.get("schedule", {})

    schedule_keys = set(schedule.keys())
    uses_dow_keys = bool(schedule_keys & (VALID_SCHEDULE_KEYS - {"all_day"})) or "all_day" in schedule_keys

    if uses_dow_keys and broadcast_day:
        target = date.fromisoformat(broadcast_day)
        resolved_blocks = resolve_day_schedule(dsl, target)
    else:
        resolved_blocks = []
        for day_value in schedule.values():
            if isinstance(day_value, list):
                resolved_blocks.extend(day_value)
            elif isinstance(day_value, dict):
                resolved_blocks.append(day_value)

    # Pre-scan: compute emissions_per_occurrence and prior_same_day_emissions
    # for each block, keyed by run_id.
    #
    # emissions_per_occurrence = total executions across ALL blocks sharing a
    #   run_id on a single matching day.
    # prior_same_day_emissions = cumulative executions from earlier blocks
    #   sharing the same run_id (in schedule order).
    from retrovue.runtime.program_assembly import _derive_run_id

    # First pass: collect execution counts per effective run_id
    _run_id_exec_counts: dict[str, int] = {}
    _block_run_ids: list[str | None] = []
    _block_executions: list[int] = []

    for block_def in resolved_blocks:
        if not isinstance(block_def, dict):
            _block_run_ids.append(None)
            _block_executions.append(0)
            continue

        prog_field = block_def.get("program", "")
        if isinstance(prog_field, list):
            prog_ref = prog_field[0] if prog_field else ""
        else:
            prog_ref = prog_field
        prog_def = programs_defs.get(prog_ref, {})
        grid_blocks = prog_def.get("grid_blocks", 1)
        grid_blocks_max = prog_def.get("grid_blocks_max")
        b_slots = block_def.get("slots", 1)
        if not isinstance(b_slots, int):
            b_slots = len(b_slots)
        b_progression = block_def.get("progression", "sequential")

        if b_progression != "sequential":
            _block_run_ids.append(None)
            _block_executions.append(0)
            continue

        # Dynamic grid programs: execution count unknown upfront.
        # Use 1 as conservative estimate for emission counting.
        if grid_blocks_max is not None:
            grid_blocks = 1

        b_run_id = block_def.get("run_id")
        b_layer = block_def.get("_schedule_layer", "all_day")
        b_start = block_def.get("start", "06:00")

        effective_rid = b_run_id or _derive_run_id(
            channel_id, b_layer, b_start, prog_ref,
        )
        execs = b_slots // max(grid_blocks, 1)

        _block_run_ids.append(effective_rid)
        _block_executions.append(execs)
        _run_id_exec_counts[effective_rid] = _run_id_exec_counts.get(effective_rid, 0) + execs

    # Second pass: compute prior_same_day_emissions per block
    _run_id_prior: dict[str, int] = {}

    # Program execution plan → program assembly
    for i, block_def in enumerate(resolved_blocks):
        if isinstance(block_def, dict):
            rid = _block_run_ids[i] if i < len(_block_run_ids) else None
            epo = _run_id_exec_counts.get(rid, 1) if rid else 1
            prior = _run_id_prior.get(rid, 0) if rid else 0

            blocks = _compile_program_block(
                block_def, programs_defs, broadcast_day, tz_name,
                resolver, grid_minutes, seed=seed,
                channel_id=channel_id,
                run_store=run_store,
                emissions_per_occurrence=epo,
                prior_same_day_emissions=prior,
            )
            all_blocks.extend(blocks)

            # Advance prior emissions for subsequent blocks with same run_id
            if rid:
                _run_id_prior[rid] = prior + _block_executions[i]

    # INV-BLEED-NO-GAP-001: Sort, validate, compact, revalidate.
    all_blocks.sort(key=lambda b: b.start_at)

    # Normalize all blocks to UTC for consistent epoch math
    from zoneinfo import ZoneInfo
    _utc = ZoneInfo("UTC")
    all_blocks = [
        replace(b, start_at=b.start_at.astimezone(_utc))
        if b.start_at.utcoffset() != timedelta(0)
        else b
        for b in all_blocks
    ]

    # Validate grid alignment before compaction
    _validate_grid_alignment(all_blocks, grid_minutes)

    # Compact: resolve bleed overlaps by pushing blocks forward
    compacted: list[ProgramBlockOutput] = []
    for block in all_blocks:
        if compacted and compacted[-1].end_at() > block.start_at:
            new_start = compacted[-1].end_at()
            block = replace(block, start_at=new_start)
        compacted.append(block)
    all_blocks = compacted

    # Post-compaction revalidation
    _validate_grid_alignment(all_blocks, grid_minutes)

    # Build output
    plan: dict[str, Any] = {
        "version": "program-schedule.v2",
        "channel_id": channel_id,
        "broadcast_day": broadcast_day,
        "timezone": tz_name,
        "source": {
            "dsl_path": dsl_path,
            "git_commit": git_commit,
            "compiler_version": COMPILER_VERSION,
        },
        "program_blocks": [b.to_dict() for b in all_blocks],
    }

    notes = dsl.get("notes")
    if notes:
        plan["notes"] = notes

    plan["hash"] = _compute_hash(plan)
    return plan


def _compute_hash(plan: dict[str, Any]) -> str:
    hashable = {k: v for k, v in plan.items() if k != "hash"}
    canonical = json.dumps(hashable, sort_keys=True, default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
