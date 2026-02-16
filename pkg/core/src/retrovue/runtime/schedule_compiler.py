"""
Programming DSL Schedule Compiler (v2).

Pure-function compiler that reads a YAML DSL schedule definition,
resolves assets, validates constraints, and emits a normalized
Program Schedule — grid-aligned program blocks only.

No breaks, no commercials, no bumpers, no station IDs.
The Program Schedule is Tier 1; Playout Log expansion is handled
separately by playout_log_expander.py.

No database writes. No global state. Receives an AssetResolver instance.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, date
from typing import Any

import yaml

from retrovue.runtime.asset_resolver import AssetMetadata, AssetResolver

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COMPILER_VERSION = "2.0.0"
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
        return d


# ---------------------------------------------------------------------------
# Selector helpers
# ---------------------------------------------------------------------------


def select_episode(
    collection_id: str,
    mode: str,
    resolver: AssetResolver,
    seed: int | None = None,
    **kwargs: Any,
) -> str:
    """Select an episode asset from a collection or pool."""
    col_meta = resolver.lookup(collection_id)
    episode_ids = list(col_meta.tags)
    if not episode_ids:
        raise AssetResolutionError(f"Pool/collection {collection_id} has no episodes")

    if mode == "sequential":
        idx = (seed or 0) % len(episode_ids)
        return episode_ids[idx]
    elif mode == "random":
        rng = random.Random(seed)
        return rng.choice(episode_ids)
    elif mode == "weighted":
        rng = random.Random(seed)
        return rng.choice(episode_ids)
    else:
        raise CompileError(f"Unknown episode selector mode: {mode}")


def select_movie(
    collections: list[str],
    resolver: AssetResolver,
    rating_include: list[str] | None = None,
    rating_exclude: list[str] | None = None,
    max_duration_sec: int | None = None,
    seed: int | None = None,
    **kwargs: Any,
) -> str:
    """Select a movie asset from collection pools, applying filters."""
    candidates: list[str] = []
    for col_id in collections:
        col_meta = resolver.lookup(col_id)
        candidates.extend(col_meta.tags)

    if not candidates:
        raise AssetResolutionError(f"No movie candidates in collections: {collections}")

    filtered: list[str] = []
    for cid in candidates:
        meta = resolver.lookup(cid)
        if rating_include and meta.rating not in rating_include:
            continue
        if rating_exclude and meta.rating in rating_exclude:
            continue
        if max_duration_sec and meta.duration_sec > max_duration_sec:
            continue
        filtered.append(cid)

    if not filtered:
        raise AssetResolutionError(
            f"No movies match filters (rating_include={rating_include}, max_duration={max_duration_sec})"
        )

    filtered.sort()
    rng = random.Random(seed)
    return rng.choice(filtered)


# ---------------------------------------------------------------------------
# Template expansion
# ---------------------------------------------------------------------------


def expand_templates(dsl: dict[str, Any]) -> dict[str, Any]:
    """Expand template references in the schedule section."""
    templates = dsl.get("templates", {})
    schedule = dsl.get("schedule", {})
    expanded_schedule: dict[str, Any] = {}

    for day_key, day_value in schedule.items():
        if isinstance(day_value, dict) and "use" in day_value:
            tpl_name = day_value["use"]
            if tpl_name not in templates:
                raise CompileError(f"Unknown template: {tpl_name}")
            expanded_schedule[day_key] = templates[tpl_name]
        else:
            expanded_schedule[day_key] = day_value

    result = dict(dsl)
    result["schedule"] = expanded_schedule
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
# Grid alignment
# ---------------------------------------------------------------------------


def validate_grid_alignment(start_time_str: str, grid_minutes: int) -> list[str]:
    """Check that a start time aligns to grid boundaries."""
    errors: list[str] = []
    parts = start_time_str.split(":")
    if len(parts) >= 2:
        minute = int(parts[1])
        if minute % grid_minutes != 0:
            errors.append(
                f"Start time {start_time_str} is not aligned to {grid_minutes}-minute grid"
            )
    return errors


def _grid_slot_duration(grid_minutes: int, episode_duration_sec: int) -> int:
    """Calculate the grid slot duration that fits an episode."""
    slot_sec = grid_minutes * 60
    # How many grid slots needed?
    slots_needed = max(1, -(-episode_duration_sec // slot_sec))  # ceil division
    return slots_needed * slot_sec


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
# Block compilation
# ---------------------------------------------------------------------------


def _compile_sitcom_block(
    block_def: dict[str, Any],
    broadcast_day: str,
    tz_name: str,
    resolver: AssetResolver,
    grid_minutes: int,
    seed: int | None = None,
) -> list[ProgramBlockOutput]:
    """Compile a sitcom/rerun block — program blocks only."""
    blocks: list[ProgramBlockOutput] = []
    start_str = block_def.get("start", "20:00")
    current_time = _parse_time(start_str, broadcast_day, tz_name)
    slots = block_def.get("slots", [])

    for slot in slots:
        title = slot.get("title", "")
        program_id = slot.get("program", "")
        ep_sel = slot.get("episode_selector", {})

        if ep_sel:
            # Support both "pool" (new) and "collection" (legacy) keywords
            pool_id = ep_sel.get("pool") or ep_sel.get("collection", "")
            mode = ep_sel.get("mode", "sequential")
            ep_seed = ep_sel.get("seed", seed)
            asset_id = select_episode(pool_id, mode, resolver, seed=ep_seed)
        else:
            asset_id = program_id

        ep_meta = resolver.lookup(asset_id)
        slot_duration = _grid_slot_duration(grid_minutes, ep_meta.duration_sec)

        block = ProgramBlockOutput(
            title=title,
            asset_id=asset_id,
            start_at=current_time,
            slot_duration_sec=slot_duration,
            episode_duration_sec=ep_meta.duration_sec,
            collection=(ep_sel.get("pool") or ep_sel.get("collection")) if ep_sel else None,
            selector={
                "mode": ep_sel.get("mode", "sequential"),
                "seed": ep_sel.get("seed", seed),
            } if ep_sel else None,
        )
        blocks.append(block)
        current_time = block.end_at()

    return blocks


def _compile_movie_block(
    block_def: dict[str, Any],
    broadcast_day: str,
    tz_name: str,
    resolver: AssetResolver,
    grid_minutes: int,
    seed: int | None = None,
) -> list[ProgramBlockOutput]:
    """Compile a movie block — program block only."""
    start_str = block_def.get("start", "20:00")
    current_time = _parse_time(start_str, broadcast_day, tz_name)

    mb = block_def.get("movie_block", {})
    ms = mb.get("movie_selector", {}) if mb else block_def.get("movie_selector", {})

    collections = ms.get("pools", ms.get("collections", []))
    rating_cfg = ms.get("rating", {})
    movie_asset_id = select_movie(
        collections=collections,
        resolver=resolver,
        rating_include=rating_cfg.get("include"),
        rating_exclude=rating_cfg.get("exclude"),
        max_duration_sec=ms.get("max_duration_sec"),
        seed=seed,
    )

    movie_meta = resolver.lookup(movie_asset_id)
    slot_duration = _grid_slot_duration(grid_minutes, movie_meta.duration_sec)

    block = ProgramBlockOutput(
        title=movie_asset_id,
        asset_id=movie_asset_id,
        start_at=current_time,
        slot_duration_sec=slot_duration,
        episode_duration_sec=movie_meta.duration_sec,
        collection=collections[0] if collections else None,
        selector={
            "collections": collections,
            "rating": rating_cfg,
            "seed": seed,
        },
    )
    return [block]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_dsl(dsl: dict[str, Any], resolver: AssetResolver) -> list[str]:
    """Validate a parsed DSL structure. Returns error messages (empty = valid)."""
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

    # Validate grid alignment
    for day_key, day_value in schedule.items():
        if isinstance(day_value, dict):
            start = day_value.get("start", "")
            if start:
                errors.extend(validate_grid_alignment(start, grid_min))
        elif isinstance(day_value, list):
            for item in day_value:
                if isinstance(item, dict):
                    start = item.get("start", "")
                    if start:
                        errors.extend(validate_grid_alignment(start, grid_min))

    # Validate asset references in templates
    templates = dsl.get("templates", {})
    for tpl_name, tpl_def in templates.items():
        if isinstance(tpl_def, dict):
            _validate_block_assets(tpl_def, resolver, errors, context=f"template:{tpl_name}")

    # Validate schedule block assets
    for day_key, day_value in schedule.items():
        if isinstance(day_value, dict):
            _validate_block_assets(day_value, resolver, errors, context=f"schedule:{day_key}")
        elif isinstance(day_value, list):
            for i, item in enumerate(day_value):
                if isinstance(item, dict):
                    _validate_block_assets(item, resolver, errors, context=f"schedule:{day_key}[{i}]")

    return errors


def _validate_block_assets(
    block: dict[str, Any],
    resolver: AssetResolver,
    errors: list[str],
    context: str,
) -> None:
    """Validate asset references in a block definition."""
    for slot in block.get("slots", []):
        ep_sel = slot.get("episode_selector", {})
        if ep_sel:
            pool_id = ep_sel.get("pool") or ep_sel.get("collection", "")
            if pool_id:
                try:
                    resolver.lookup(pool_id)
                except KeyError:
                    errors.append(f"[{context}] Pool/collection not found: {pool_id}")

    # Movie block / movie_selector
    mb = block.get("movie_block", {})
    ms = mb.get("movie_selector", {}) if mb else block.get("movie_selector", {})
    # Movie selectors: support "pools" (new) alongside "collections" (legacy)
    movie_pool_ids = ms.get("pools", ms.get("collections", []))
    for pool_id in movie_pool_ids:
        try:
            resolver.lookup(pool_id)
        except KeyError:
            errors.append(f"[{context}] Movie pool/collection not found: {pool_id}")


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
    """Parse YAML DSL text into a dict."""
    return yaml.safe_load(yaml_text)


def compile_schedule(
    dsl: dict[str, Any],
    resolver: AssetResolver,
    *,
    dsl_path: str = "unknown",
    git_commit: str = "0000000",
    seed: int | None = 42,
) -> dict[str, Any]:
    """
    Compile a DSL definition into a Program Schedule.

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

    # Expand templates
    expanded = expand_templates(dsl)

    channel_id = expanded["channel"]
    broadcast_day = str(expanded["broadcast_day"])
    tz_name = expanded["timezone"]
    template = get_channel_template(expanded)
    grid_minutes = get_grid_minutes(template)

    # Compile each schedule day into program blocks
    all_blocks: list[ProgramBlockOutput] = []
    schedule = expanded.get("schedule", {})

    for day_key, day_value in schedule.items():
        if isinstance(day_value, dict):
            blocks = _compile_sitcom_block(
                day_value, broadcast_day, tz_name, resolver, grid_minutes, seed=seed,
            )
            all_blocks.extend(blocks)
        elif isinstance(day_value, list):
            for block_def in day_value:
                if isinstance(block_def, dict):
                    if "movie_block" in block_def or "movie_selector" in block_def:
                        blocks = _compile_movie_block(
                            block_def, broadcast_day, tz_name, resolver, grid_minutes, seed=seed,
                        )
                    else:
                        blocks = _compile_sitcom_block(
                            block_def, broadcast_day, tz_name, resolver, grid_minutes, seed=seed,
                        )
                    all_blocks.extend(blocks)

    # Validate compiled blocks
    block_errors = validate_program_blocks(all_blocks)
    if block_errors:
        raise ValidationError(block_errors)

    # Sort
    all_blocks.sort(key=lambda b: b.start_at)

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
