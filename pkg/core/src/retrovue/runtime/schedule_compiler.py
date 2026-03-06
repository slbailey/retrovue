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
import uuid as uuid_mod
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, date
from typing import Any

import yaml

from retrovue.runtime.asset_resolver import AssetMetadata, AssetResolver

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COMPILER_VERSION = "2.2.0"
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
    window_uuid: str | None = None
    template_id: str | None = None
    epg_title: str | None = None
    compiled_segments: list[dict[str, Any]] | None = None

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
        if self.window_uuid:
            d["window_uuid"] = self.window_uuid
        if self.template_id:
            d["template_id"] = self.template_id
        if self.epg_title:
            d["epg_title"] = self.epg_title
        if self.compiled_segments:
            d["compiled_segments"] = self.compiled_segments
        return d


# ---------------------------------------------------------------------------
# Selector helpers
# ---------------------------------------------------------------------------


def select_episode(
    collection_id: str,
    mode: str,
    resolver: AssetResolver,
    seed: int | None = None,
    sequential_counters: dict[str, int] | None = None,
    **kwargs: Any,
) -> str:
    """Select an episode asset from a collection or pool."""
    col_meta = resolver.lookup(collection_id)
    episode_ids = list(col_meta.tags)
    if not episode_ids:
        raise AssetResolutionError(f"Pool/collection {collection_id} has no episodes")

    if mode == "sequential":
        if sequential_counters is not None:
            idx = sequential_counters.get(collection_id, 0) % len(episode_ids)
            sequential_counters[collection_id] = sequential_counters.get(collection_id, 0) + 1
        else:
            idx = (seed or 0) % len(episode_ids)
        return episode_ids[idx]
    elif mode == "random":
        rng = random.Random(seed)
        return rng.choice(episode_ids)
    elif mode == "weighted":
        rng = random.Random(seed)
        return rng.choice(episode_ids)
    elif mode == "serial":
        # INV-SERIAL-001: Deterministic serial progression via calendar
        # occurrence counting.  Requires serial_run_info and broadcast_day
        # to be passed via kwargs by the caller.
        from retrovue.runtime.serial_episode_resolver import (
            SerialRunInfo,
            resolve_serial_episode,
        )

        serial_run_info: SerialRunInfo | None = kwargs.get("serial_run_info")
        broadcast_day_str: str | None = kwargs.get("broadcast_day")
        if serial_run_info is None or broadcast_day_str is None:
            raise CompileError(
                f"Serial mode for pool {collection_id} requires "
                "'serial_run_info' and 'broadcast_day' kwargs"
            )
        from datetime import date as date_type

        target = date_type.fromisoformat(broadcast_day_str)
        idx = resolve_serial_episode(serial_run_info, target, len(episode_ids))
        if idx is None:
            # stop policy exhausted — return first episode as filler fallback
            # (the caller can handle this differently if needed)
            return episode_ids[0]
        return episode_ids[idx]
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
        if meta.duration_sec and meta.duration_sec < 3600:
            continue  # skip movies with bad/short duration metadata
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
    # Disambiguation (INV-TEMPLATE-GRAFT-DUAL-YAML-001): if any template
    # entry has a "segments" key, this is a new-style template registry
    # (segment-composition templates), NOT legacy day-schedule aliases.
    # Skip expansion — schedule entries use type:template dispatch instead.
    if any(isinstance(v, dict) and "segments" in v for v in templates.values()):
        # Rule 6: no mixed mapping — all entries must be segment-composition.
        legacy_aliases = [
            k for k, v in templates.items()
            if not (isinstance(v, dict) and "segments" in v)
        ]
        if legacy_aliases:
            raise CompileError(
                f"templates: cannot mix segment-composition templates with "
                f"legacy day-aliases in the same mapping. "
                f"Legacy aliases found: {legacy_aliases}"
            )
        return dsl
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
    """Index a list of block defs by their 'start' time.

    Handles nested block types where start is inside a sub-key:
        - block: { start: "06:00", ... }
        - movie_marathon: { start: "09:00", ... }
    """
    result: dict[str, dict] = {}
    for b in blocks:
        if isinstance(b, dict):
            # Check for nested block types first
            key = b.get("start", "")
            if not key:
                for nested_key in ("block", "movie_marathon", "movie_block"):
                    nested = b.get(nested_key)
                    if isinstance(nested, dict):
                        key = nested.get("start", "")
                        break
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
# Time parsing
# ---------------------------------------------------------------------------


def _parse_duration(dur_str: str) -> timedelta:
    """Parse a duration string like '24h', '3h', '90m', '3h30m', '2h 15m'.

    Supports:
        '24h'    -> 24 hours
        '3h'     -> 3 hours
        '90m'    -> 90 minutes
        '3h30m'  -> 3 hours 30 minutes
        '2h 15m' -> 2 hours 15 minutes
    """
    import re
    dur_str = dur_str.strip().lower()
    hours = 0
    minutes = 0

    h_match = re.search(r'(\d+)\s*h', dur_str)
    m_match = re.search(r'(\d+)\s*m', dur_str)

    if h_match:
        hours = int(h_match.group(1))
    if m_match:
        minutes = int(m_match.group(1))

    if not h_match and not m_match:
        # Try plain number as hours
        try:
            hours = int(dur_str)
        except ValueError:
            raise ValueError(f"Cannot parse duration: {dur_str!r}")

    return timedelta(hours=hours, minutes=minutes)


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
    sequential_counters: dict[str, int] | None = None,
) -> list[ProgramBlockOutput]:
    """Compile a sitcom/rerun block — program blocks only.

    Supports episode preemption: if an episode's duration exceeds one grid
    slot, it claims ceil(duration / grid_slot) slots. Preempted slots are
    consumed and their corresponding slot definitions are skipped. The
    sequential counter only increments when an episode is actually placed.
    """
    blocks: list[ProgramBlockOutput] = []
    start_str = block_def.get("start", "20:00")
    current_time = _parse_time(start_str, broadcast_day, tz_name)
    slots = block_def.get("slots", [])

    slot_sec = grid_minutes * 60
    slot_idx = 0
    while slot_idx < len(slots):
        slot = slots[slot_idx]
        title = slot.get("title", "")
        program_id = slot.get("program", "")
        ep_sel = slot.get("episode_selector", {})

        if ep_sel:
            # Support both "pool" (new) and "collection" (legacy) keywords
            pool_id = ep_sel.get("pool") or ep_sel.get("collection", "")
            mode = ep_sel.get("mode", "sequential")
            ep_seed = ep_sel.get("seed", seed)
            asset_id = select_episode(pool_id, mode, resolver, seed=ep_seed, sequential_counters=sequential_counters)
        else:
            asset_id = program_id

        ep_meta = resolver.lookup(asset_id)
        slot_duration = _grid_slot_duration(grid_minutes, ep_meta.duration_sec)
        slots_consumed = max(1, -(-ep_meta.duration_sec // slot_sec))  # ceil division

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

        # Skip preempted slots
        slot_idx += slots_consumed

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

    # INV-SCHEDULE-SEED-DAY-VARIANCE-001 Rule 2: window-specific seed
    wseed = _window_seed(seed, start_str)

    mb = block_def.get("movie_block", {})
    ms = mb.get("movie_selector", {}) if mb else block_def.get("movie_selector", {})

    # Support singular 'pool' (wraps to list) and plural 'pools'/'collections'
    collections = ms.get("pools", ms.get("collections", []))
    if not collections:
        single_pool = ms.get("pool")
        if single_pool:
            collections = [single_pool]
    rating_cfg = ms.get("rating", {})
    movie_asset_id = select_movie(
        collections=collections,
        resolver=resolver,
        rating_include=rating_cfg.get("include"),
        rating_exclude=rating_cfg.get("exclude"),
        max_duration_sec=ms.get("max_duration_sec"),
        seed=wseed,
    )

    movie_meta = resolver.lookup(movie_asset_id)
    slot_duration = _grid_slot_duration(grid_minutes, movie_meta.duration_sec)

    block = ProgramBlockOutput(
        title=movie_meta.title or movie_asset_id,
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



def _compile_movie_marathon(
    block_def: dict[str, Any],
    broadcast_day: str,
    tz_name: str,
    resolver: AssetResolver,
    grid_minutes: int,
    seed: int | None = None,
    used_movie_ids: set | None = None,
) -> list[ProgramBlockOutput]:
    """Compile a contiguous movie marathon — fills a time range with back-to-back movies.

    DSL shape:
        - movie_marathon:
            start: "09:00"
            end: "22:00"
            title: "Horror Movie Marathon"
            movie_selector: { pool: horror_80s, mode: random }
            allow_bleed: true   # optional, default false

    When allow_bleed is true, if the last movie would end before `end`, one
    more movie is scheduled even if it bleeds past `end`. The compaction pass
    resolves overlaps by pushing subsequent blocks forward to the bleed
    block's grid-aligned end.
    """
    mm = block_def.get("movie_marathon", {})
    start_str = mm.get("start") or block_def.get("start", "09:00")
    end_str = mm.get("end", "22:00")
    allow_bleed = mm.get("allow_bleed", False)
    ms = mm.get("movie_selector", {})
    marathon_title = mm.get("title", "Movie Marathon")

    current_time = _parse_time(start_str, broadcast_day, tz_name)
    end_time = _parse_time(end_str, broadcast_day, tz_name)

    # If end <= start, it means overnight wrap (e.g. 22:00 -> 06:00)
    if end_time <= current_time:
        end_time = end_time + timedelta(hours=24)

    # Support both "pool"/"pools"/"collections"
    collections = ms.get("pools", ms.get("collections", []))
    if not collections:
        single_pool = ms.get("pool")
        if single_pool:
            collections = [single_pool]
    rating_cfg = ms.get("rating", {})

    if used_movie_ids is None:
        used_movie_ids = set()

    blocks: list[ProgramBlockOutput] = []
    # INV-SCHEDULE-SEED-DAY-VARIANCE-001 Rule 2: window-specific seed
    movie_seed = _window_seed(seed, start_str)
    max_attempts = 200  # safety valve

    while max_attempts > 0:
        # Stop if we have already filled past end_time
        if current_time >= end_time:
            break

        max_attempts -= 1

        movie_asset_id = _select_movie_no_repeat(
            collections=collections,
            resolver=resolver,
            rating_include=rating_cfg.get("include"),
            rating_exclude=rating_cfg.get("exclude"),
            max_duration_sec=ms.get("max_duration_sec"),
            seed=movie_seed,
            used_ids=used_movie_ids,
        )
        movie_seed += 1  # increment seed for next pick

        if movie_asset_id is None:
            # Exhausted pool, reset used set and try again
            used_movie_ids.clear()
            continue

        used_movie_ids.add(movie_asset_id)
        movie_meta = resolver.lookup(movie_asset_id)
        slot_duration = _grid_slot_duration(grid_minutes, movie_meta.duration_sec)

        block = ProgramBlockOutput(
            title=movie_meta.title or movie_asset_id,
            asset_id=movie_asset_id,
            start_at=current_time,
            slot_duration_sec=slot_duration,
            episode_duration_sec=movie_meta.duration_sec,
            collection=collections[0] if collections else None,
            selector={
                "collections": collections,
                "rating": rating_cfg,
                "seed": movie_seed - 1,
            },
        )
        blocks.append(block)
        current_time = block.end_at()

        # This movie bleeds past end_time — keep it if allow_bleed, else remove
        if current_time > end_time and not allow_bleed:
            blocks.pop()
            break

    return blocks


def _resolve_template_segments(
    *,
    segments: list[dict[str, Any]],
    primary_seg: dict[str, Any],
    primary_asset_id: str,
    primary_meta: "AssetMetadata",
    resolver: "AssetResolver",
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """Resolve all template segments into an explicit compiled list.

    INV-TEMPLATE-BLOCKS-COMPILE-TO-EXPLICIT-SEGMENTS:
    Each template segment is fully resolved at compile time. The primary
    segment uses the already-selected asset; non-primary segments are
    resolved from their declared source (collection or pool).

    Returns a list of dicts with the stable compiled segment shape.
    """
    compiled: list[dict[str, Any]] = []
    rng = random.Random(seed)

    for seg_def in segments:
        source = seg_def.get("source", {})
        source_type = source.get("type", "")
        source_name = source.get("name", "")
        is_primary = seg_def is primary_seg

        if is_primary:
            asset_id = primary_asset_id
            asset_meta = primary_meta
            seg_type = "content"
        else:
            # Resolve non-primary segment from its source
            # INV-TEMPLATE-COLLECTION-SOURCE-RESOLVE: collection sources
            # must query by collection name, not lookup (which only handles
            # assets, aliases, and pools).
            if source_type == "collection":
                candidates = resolver.query({"collection": source_name})
            else:
                col_meta = resolver.lookup(source_name)
                candidates = list(col_meta.tags)

            # Apply selection filters if declared
            # INV-TEMPLATE-SELECTION-NORMALIZE-001: selection may be a single
            # rule dict (YAML shorthand) or a list of rule dicts (canonical).
            selection = seg_def.get("selection", [])
            if isinstance(selection, dict):
                selection = [selection]
            for rule in selection:
                if rule.get("type") == "tags":
                    # Tag filter: keep candidates whose asset_id contains
                    # any of the required tag values (substring match on ID
                    # or title for lightweight tag filtering at compile time)
                    tag_values = rule.get("values", [])
                    if tag_values:
                        filtered = []
                        for cid in candidates:
                            try:
                                cmeta = resolver.lookup(cid)
                                cid_lower = cid.lower()
                                title_lower = (cmeta.title or "").lower()
                                tags_lower = [t.lower() for t in cmeta.tags]
                                if any(
                                    tv.lower() in cid_lower
                                    or tv.lower() in title_lower
                                    or tv.lower() in tags_lower
                                    for tv in tag_values
                                ):
                                    filtered.append(cid)
                            except KeyError:
                                pass
                        candidates = filtered

            if not candidates:
                raise CompileError(
                    f"Template segment source '{source_name}' "
                    f"resolved to zero candidates after filtering"
                )

            candidates.sort()
            asset_id = rng.choice(candidates)
            asset_meta = resolver.lookup(asset_id)
            seg_type = "intro" if source_type == "collection" else "content"

        compiled.append({
            "segment_type": seg_type,
            "asset_id": asset_id,
            "asset_uri": asset_meta.file_uri or "",
            "asset_start_offset_ms": 0,
            "segment_duration_ms": asset_meta.duration_sec * 1000,
            "source_type": source_type,
            "source_name": source_name,
            "is_primary": is_primary,
            "gain_db": asset_meta.loudness_gain_db,
        })

    return compiled


def _compile_template_entry(
    block_def: dict[str, Any],
    broadcast_day: str,
    tz_name: str,
    resolver: AssetResolver,
    grid_minutes: int,
    templates: dict[str, Any],
    seed: int | None = None,
) -> list[ProgramBlockOutput]:
    """Compile a type:template schedule entry — fills a time range with
    primary content from the template's segment definitions.

    Each iteration selects primary content (from the first pool-source
    segment), producing one ProgramBlockOutput per editorial item.
    All blocks within the window share the same window_uuid.

    DSL shape:
        - type: template
          name: hbo_feature_with_intro
          start: "06:00"
          end: "14:00"
          epg_title: "HBO Feature Presentation"
          allow_bleed: true
    """
    template_name = block_def["name"]
    if template_name not in templates:
        raise CompileError(f"Unknown template: {template_name}")

    tpl = templates[template_name]
    segments = tpl.get("segments", [])
    if not segments:
        raise CompileError(f"Template {template_name} has no segments")

    # INV-TEMPLATE-PRIMARY-SEGMENT-001: Identify the primary content segment.
    #  1. Explicit: exactly one segment with primary: true
    #  2. Convention: exactly one segment with source.type == "pool"
    #  3. Otherwise: fail — operator must set primary: true on one segment.
    marked = [s for s in segments if s.get("primary") is True]
    if len(marked) == 1:
        primary_seg = marked[0]
    elif len(marked) > 1:
        raise CompileError(
            f"Template {template_name} has {len(marked)} segments with "
            f"primary: true; exactly one is required"
        )
    else:
        pools = [s for s in segments if s.get("source", {}).get("type") == "pool"]
        if len(pools) == 1:
            primary_seg = pools[0]
        elif len(pools) == 0:
            raise CompileError(
                f"Template {template_name} has no pool segment — "
                f"set primary: true on exactly one segment"
            )
        else:
            raise CompileError(
                f"Template {template_name} has {len(pools)} pool segments — "
                f"set primary: true on exactly one segment"
            )

    primary_source = primary_seg["source"]
    pool_name = primary_source["name"]

    start_str = block_def.get("start", "06:00")
    end_str = block_def.get("end", "22:00")
    allow_bleed = block_def.get("allow_bleed", False)
    epg_title = block_def.get("epg_title")

    current_time = _parse_time(start_str, broadcast_day, tz_name)
    end_time = _parse_time(end_str, broadcast_day, tz_name)

    # Overnight wrap
    if end_time <= current_time:
        end_time = end_time + timedelta(hours=24)

    window_uuid = str(uuid_mod.uuid4())

    # Per-window dedupe — no duplicate primary assets within a single window.
    used_ids: set[str] = set()

    blocks: list[ProgramBlockOutput] = []
    # INV-SCHEDULE-SEED-DAY-VARIANCE-001 Rule 2: window-specific seed
    pick_seed = _window_seed(seed, start_str)
    max_attempts = 200

    while max_attempts > 0:
        if current_time >= end_time:
            break

        max_attempts -= 1

        asset_id = _select_movie_no_repeat(
            collections=[pool_name],
            resolver=resolver,
            seed=pick_seed,
            used_ids=used_ids,
        )
        pick_seed += 1

        if asset_id is None:
            # Pool exhausted within window — reset and continue
            used_ids.clear()
            continue

        used_ids.add(asset_id)
        meta = resolver.lookup(asset_id)

        # INV-TEMPLATE-BLOCKS-COMPILE-TO-EXPLICIT-SEGMENTS:
        # Resolve ALL template segments (not just primary) into an explicit
        # compiled_segments list that preserves the template's segment order.
        compiled_segs = _resolve_template_segments(
            segments=segments,
            primary_seg=primary_seg,
            primary_asset_id=asset_id,
            primary_meta=meta,
            resolver=resolver,
            seed=pick_seed,
        )

        # Slot duration must cover ALL template segments, not just primary.
        total_content_sec = sum(
            seg["segment_duration_ms"] for seg in compiled_segs
        ) / 1000
        slot_duration = _grid_slot_duration(grid_minutes, total_content_sec)

        block = ProgramBlockOutput(
            title=meta.title or asset_id,
            asset_id=asset_id,
            start_at=current_time,
            slot_duration_sec=slot_duration,
            episode_duration_sec=meta.duration_sec,
            collection=pool_name,
            window_uuid=window_uuid,
            template_id=template_name,
            epg_title=epg_title,
            compiled_segments=compiled_segs,
        )
        blocks.append(block)
        current_time = block.end_at()

        if current_time > end_time and not allow_bleed:
            blocks.pop()
            break

    return blocks


def _compile_episode_block(
    block_def: dict[str, Any],
    broadcast_day: str,
    tz_name: str,
    resolver: AssetResolver,
    grid_minutes: int,
    seed: int | None = None,
    sequential_counters: dict[str, int] | None = None,
) -> list[ProgramBlockOutput]:
    """Compile an episode block — fills a time range with episodes from a pool.

    DSL shape:
        - block:
            start: "22:00"
            end: "06:00"
            title: "Tales from the Crypt"
            pool: tales_from_the_crypt
            mode: sequential

    Multi-pool support:
        - block:
            start: "06:00"
            end: "12:00"
            title: "Morning Sitcoms"
            pool: [cheers, cosby, barney]
            mode: shuffle       # rotate across pools

    When start == end (e.g. both "06:00"), fills a full 24h broadcast day.
    """
    bb = block_def.get("block", {})
    start_str = bb.get("start") or block_def.get("start", "06:00")
    end_str = bb.get("end", "")
    duration_str = bb.get("duration", "")
    title = bb.get("title", "")
    mode = bb.get("mode", "sequential")
    pool_spec = bb.get("pool", "")

    # Normalise pool(s) to a list
    if isinstance(pool_spec, str):
        pools = [pool_spec]
    else:
        pools = list(pool_spec)

    current_time = _parse_time(start_str, broadcast_day, tz_name)

    # Resolve end time: duration takes priority over end
    if duration_str:
        end_time = current_time + _parse_duration(duration_str)
    elif end_str:
        end_time = _parse_time(end_str, broadcast_day, tz_name)
        # If end <= start, it means overnight wrap (e.g. 22:00 -> 06:00)
        if end_time <= current_time:
            end_time = end_time + timedelta(hours=24)
    else:
        # No end or duration — default to full 24h
        end_time = current_time + timedelta(hours=24)

    slot_sec = grid_minutes * 60
    blocks: list[ProgramBlockOutput] = []
    pool_index = 0  # for round-robin across pools
    # INV-SCHEDULE-SEED-DAY-VARIANCE-001 Rule 2: window-specific seed
    rng = random.Random(_window_seed(seed, start_str))

    if sequential_counters is None:
        sequential_counters = {}

    max_iterations = 500  # safety valve

    while current_time < end_time and max_iterations > 0:
        max_iterations -= 1

        # Pick pool: round-robin for shuffle, first pool for sequential/random
        if mode == "shuffle" and len(pools) > 1:
            pool_id = pools[pool_index % len(pools)]
            pool_index += 1
        elif mode == "random" and len(pools) > 1:
            pool_id = rng.choice(pools)
        else:
            pool_id = pools[pool_index % len(pools)]
            if mode == "sequential" and len(pools) > 1:
                pool_index += 1

        # Select episode
        ep_seed = seed if mode != "random" else rng.randint(0, 2**31)
        asset_id = select_episode(
            pool_id, "sequential" if mode in ("sequential", "shuffle") else mode,
            resolver, seed=ep_seed, sequential_counters=sequential_counters,
        )

        ep_meta = resolver.lookup(asset_id)
        slot_duration = _grid_slot_duration(grid_minutes, ep_meta.duration_sec)
        ep_title = title or ep_meta.title or pool_id

        block = ProgramBlockOutput(
            title=ep_title,
            asset_id=asset_id,
            start_at=current_time,
            slot_duration_sec=slot_duration,
            episode_duration_sec=ep_meta.duration_sec,
            collection=pool_id,
            selector={
                "mode": mode,
                "pool": pool_id,
            },
        )
        blocks.append(block)
        current_time = block.end_at()

    return blocks


def _select_movie_no_repeat(
    collections: list[str],
    resolver: AssetResolver,
    rating_include: list[str] | None = None,
    rating_exclude: list[str] | None = None,
    max_duration_sec: int | None = None,
    seed: int | None = None,
    used_ids: set | None = None,
) -> str | None:
    """Select a movie, avoiding already-used IDs. Returns None if exhausted."""
    candidates: list[str] = []
    for col_id in collections:
        col_meta = resolver.lookup(col_id)
        candidates.extend(col_meta.tags)

    if not candidates:
        return None

    filtered: list[str] = []
    for cid in candidates:
        if used_ids and cid in used_ids:
            continue
        meta = resolver.lookup(cid)
        if rating_include and meta.rating not in rating_include:
            continue
        if rating_exclude and meta.rating in rating_exclude:
            continue
        if max_duration_sec and meta.duration_sec > max_duration_sec:
            continue
        if meta.duration_sec and meta.duration_sec < 3600:
            continue  # skip movies with bad/short duration metadata
        filtered.append(cid)

    if not filtered:
        return None

    filtered.sort()
    rng = random.Random(seed)
    return rng.choice(filtered)


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

    # Validate schedule keys
    for day_key in schedule:
        # Legacy keys like "weeknights" are allowed (template refs)
        # New DOW keys are validated
        if day_key not in VALID_SCHEDULE_KEYS:
            # Check if it's a template reference (has "use" key) - allow it
            val = schedule[day_key]
            if not (isinstance(val, dict) and "use" in val):
                # Allow legacy keys that aren't DOW keys (backward compat)
                pass

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
    # Movie selectors: support "pool" (singular), "pools" (new), and "collections" (legacy)
    movie_pool_ids = ms.get("pools", ms.get("collections", []))
    if not movie_pool_ids:
        single_pool = ms.get("pool")
        if single_pool:
            movie_pool_ids = [single_pool]
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
    sequential_counters: dict[str, int] | None = None,
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

    # Sequential counters persist across all blocks in this compilation
    if sequential_counters is None:
        sequential_counters = {}

    # Compile program blocks — use day-of-week resolver if broadcast_day is set
    all_blocks: list[ProgramBlockOutput] = []
    used_movie_ids: set[str] = set()  # track movies across marathon blocks to avoid repeats
    schedule = expanded.get("schedule", {})
    templates = expanded.get("templates", {})

    # Check if schedule uses any DOW/group keys (new layered format)
    schedule_keys = set(schedule.keys())
    uses_dow_keys = bool(schedule_keys & (VALID_SCHEDULE_KEYS - {"all_day"})) or "all_day" in schedule_keys

    if uses_dow_keys and broadcast_day:
        # Use the day-of-week resolver to merge layers for this date
        target = date.fromisoformat(broadcast_day)
        resolved_blocks = resolve_day_schedule(expanded, target)
        for block_def in resolved_blocks:
            if isinstance(block_def, dict):
                if "block" in block_def:
                    blocks = _compile_episode_block(
                        block_def, broadcast_day, tz_name, resolver, grid_minutes, seed=seed,
                        sequential_counters=sequential_counters,
                    )
                elif "movie_marathon" in block_def:
                    blocks = _compile_movie_marathon(
                        block_def, broadcast_day, tz_name, resolver, grid_minutes, seed=seed,
                        used_movie_ids=used_movie_ids,
                    )
                elif "movie_block" in block_def or "movie_selector" in block_def:
                    blocks = _compile_movie_block(
                        block_def, broadcast_day, tz_name, resolver, grid_minutes, seed=seed,
                    )
                elif block_def.get("type") == "template":
                    blocks = _compile_template_entry(
                        block_def, broadcast_day, tz_name, resolver, grid_minutes,
                        templates=templates, seed=seed,
                    )
                else:
                    blocks = _compile_sitcom_block(
                        block_def, broadcast_day, tz_name, resolver, grid_minutes, seed=seed,
                        sequential_counters=sequential_counters,
                    )
                all_blocks.extend(blocks)
    else:
        # Legacy path: iterate schedule keys directly
        for day_key, day_value in schedule.items():
            if isinstance(day_value, dict):
                blocks = _compile_sitcom_block(
                    day_value, broadcast_day, tz_name, resolver, grid_minutes, seed=seed,
                    sequential_counters=sequential_counters,
                )
                all_blocks.extend(blocks)
            elif isinstance(day_value, list):
                for block_def in day_value:
                    if isinstance(block_def, dict):
                        if "block" in block_def:
                            blocks = _compile_episode_block(
                                block_def, broadcast_day, tz_name, resolver, grid_minutes, seed=seed,
                                sequential_counters=sequential_counters,
                            )
                        elif "movie_marathon" in block_def:
                            blocks = _compile_movie_marathon(
                                block_def, broadcast_day, tz_name, resolver, grid_minutes, seed=seed,
                            )
                        elif "movie_block" in block_def or "movie_selector" in block_def:
                            blocks = _compile_movie_block(
                                block_def, broadcast_day, tz_name, resolver, grid_minutes, seed=seed,
                            )
                        elif block_def.get("type") == "template":
                            blocks = _compile_template_entry(
                                block_def, broadcast_day, tz_name, resolver, grid_minutes,
                                templates=templates, seed=seed,
                            )
                        else:
                            blocks = _compile_sitcom_block(
                                block_def, broadcast_day, tz_name, resolver, grid_minutes, seed=seed,
                                sequential_counters=sequential_counters,
                            )
                        all_blocks.extend(blocks)

    # INV-BLEED-NO-GAP-001: Sort, validate, compact, revalidate, check contiguity.
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
            # Both partial and full overlaps get the same treatment: push forward
            new_start = compacted[-1].end_at()
            block = replace(block, start_at=new_start)
        compacted.append(block)
    all_blocks = compacted

    # Post-compaction revalidation — fail fast, no assumptions
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
