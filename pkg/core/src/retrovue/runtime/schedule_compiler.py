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
from retrovue.runtime.progression_cursor import CursorStore

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

    # Group layer
    dow_index = target_date.weekday()  # 0=Monday
    dow_name = DOW_NAMES[dow_index]

    if dow_name in WEEKDAY_NAMES and "weekdays" in schedule:
        group_blocks = _blocks_to_dict(_ensure_list(schedule["weekdays"]))
        merged.update(group_blocks)
    elif dow_name in WEEKEND_NAMES and "weekends" in schedule:
        group_blocks = _blocks_to_dict(_ensure_list(schedule["weekends"]))
        merged.update(group_blocks)

    # Specific DOW layer
    if dow_name in schedule:
        dow_blocks = _blocks_to_dict(_ensure_list(schedule[dow_name]))
        merged.update(dow_blocks)

    # Sort by start time and return as list
    sorted_keys = sorted(merged.keys())
    return [merged[k] for k in sorted_keys]


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
    cursor_store: CursorStore | None = None,
    channel_id: str = "",
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

    start_str = block_def.get("start", "06:00")
    slots = block_def.get("slots", 1)
    if not isinstance(slots, int):
        slots = len(slots)
    program_ref = block_def.get("program", "")
    progression = block_def.get("progression", "sequential")

    prog_def = programs.get(program_ref, {})
    pool = prog_def.get("pool", program_ref)

    current_time = _parse_time(start_str, broadcast_day, tz_name)

    if cursor_store is None:
        cursor_store = CursorStore()

    # INV-SCHEDULE-SEED-DAY-VARIANCE-001 Rule 2: window-specific seed
    wseed = _window_seed(seed, start_str)

    # Delegate to Program Assembly (channel_dsl.md §5)
    assembly_results = assemble_schedule_block(
        program_ref=program_ref,
        program_def=prog_def,
        pool_name=pool,
        slots=slots,
        progression=progression,
        grid_minutes=grid_minutes,
        resolver=resolver,
        seed=wseed,
        cursor_store=cursor_store,
        channel_id=channel_id,
    )

    # Convert AssemblyResults into ProgramBlockOutputs
    blocks: list[ProgramBlockOutput] = []
    for result in assembly_results:
        # Primary content asset is the first "content" segment
        content_segments = [
            s for s in result.segments if s.segment_type == "content"
        ]
        if not content_segments:
            continue

        primary = content_segments[0]
        ep_meta = resolver.lookup(primary.asset_id)
        grid_blocks = prog_def.get("grid_blocks", 1)
        slot_duration = grid_blocks * grid_minutes * 60

        # If bleed, slot_duration must cover actual runtime
        if prog_def.get("bleed", False) and result.total_runtime_ms > slot_duration * 1000:
            slot_duration = _grid_slot_duration(grid_minutes, result.total_runtime_ms // 1000)

        block = ProgramBlockOutput(
            title=ep_meta.title or program_ref,
            asset_id=primary.asset_id,
            start_at=current_time,
            slot_duration_sec=slot_duration,
            episode_duration_sec=ep_meta.duration_sec,
            collection=pool,
            selector={
                "mode": progression,
                "pool": pool,
                "program": program_ref,
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
    cursor_store: CursorStore | None = None,
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

    # Cursor store persists across all blocks in this compilation
    if cursor_store is None:
        cursor_store = CursorStore()

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

    # Program execution plan → program assembly
    for block_def in resolved_blocks:
        if isinstance(block_def, dict):
            blocks = _compile_program_block(
                block_def, programs_defs, broadcast_day, tz_name,
                resolver, grid_minutes, seed=seed,
                cursor_store=cursor_store, channel_id=channel_id,
            )
            all_blocks.extend(blocks)

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
