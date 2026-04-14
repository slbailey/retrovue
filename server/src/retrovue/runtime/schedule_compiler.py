"""
Programming DSL Schedule Compiler (v2).

Pure-function compiler that reads a V2 YAML DSL schedule definition,
resolves assets, validates constraints, and emits a normalized
Program Schedule — grid-aligned program blocks only.

Pipeline:
    YAML DSL → schedule resolver → program execution plan →
    program assembly → break detection → traffic → playlog events

No breaks, no commercials, no bumpers, no station IDs.
The output is the Program Schedule; playout log expansion is handled
separately by playout_log_expander.py.

No database writes. No global state. Receives an AssetResolver instance.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, date
from typing import Any

import logging
import yaml

from retrovue.runtime.asset_resolver import AssetResolver
from retrovue.runtime.playout_log_expander import expand_program_block
from retrovue.scheduling.policies import (
    PolicyViolation,
    evaluate_scheduling_policies,
)

# INV-SCHEDULE-COMPILER-MODULE-SPLIT-001: import from template_resolution
from retrovue.runtime.template_resolution import (  # noqa: F401 — re-exports
    _FORBIDDEN_TEMPLATE_BREAK_FIELDS,
    _PolicyAssetAdapter,
    _blocks_to_dict,
    _ensure_list,
    _resolve_block_traffic_profile,
    _resolve_presentation_ref,
    _resolve_template,
    _resolve_template_for_program,
    DOW_NAMES,
    get_channel_template,
    get_grid_minutes,
    resolve_day_schedule,
    resolve_scheduling_policy,
    VALID_SCHEDULE_KEYS,
    WEEKDAY_NAMES,
    WEEKEND_NAMES,
)

# INV-SCHEDULE-COMPILER-MODULE-SPLIT-001: import from schedule_validation
# Note: schedule_validation imports ValidationError from this module (no circular
# issue because ValidationError is defined above these imports in this file).
from retrovue.runtime.schedule_validation import (  # noqa: F401 — re-exports
    _validate_grid_alignment,
    _validate_start_grid_alignment,
    _validate_templates,
    _validate_traffic_profile_refs,
    validate_dsl,
    validate_program_blocks,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def _extract_scheduling_constants(resolved_config: dict[str, Any] | None) -> tuple[str, int, int, int]:
    """Extract scheduling constants from resolved config.

    Returns (compiler_version, broadcast_day_start_hour, network_grid_minutes, premium_grid_minutes).
    """
    if resolved_config is None:
        raise RuntimeError(
            "resolved_config is required for schedule compilation — "
            "fallback defaults are no longer supported"
        )
    sched = resolved_config["scheduling"]
    return (
        sched["compiler_version"],
        sched["broadcast_day_start_hour"],
        sched["grid_minutes"]["network_television"],
        sched["grid_minutes"]["premium_movie"],
    )

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
# Compiled segment serialization
# ---------------------------------------------------------------------------


def _serialize_assembly_segment(
    seg: Any,
    resolver: "AssetResolver",
    *,
    is_primary: bool = False,
) -> dict[str, Any]:
    """Serialize an AssemblySegment into the expanded compiled_segments schema.

    INV-STRUCTURAL-RESOLUTION-001: compiled_segments must carry all
    structural fields needed for expansion without re-derivation.

    Fields beyond the assembly output (gain_db, is_primary) are resolved
    from the catalog here. Break-aware fields (asset_start_offset_ms,
    transitions) use safe defaults — break detection will populate them
    in a future step.
    """
    # Resolve gain_db from catalog for asset-backed segments
    gain_db = 0.0
    if seg.asset_id:
        try:
            meta = resolver.lookup(seg.asset_id)
            gain_db = getattr(meta, "loudness_gain_db", 0.0)
        except (KeyError, AttributeError):
            pass

    return {
        "segment_type": seg.segment_type,
        "asset_id": seg.asset_id,
        "duration_ms": seg.duration_ms,
        "asset_start_offset_ms": 0,
        "transition_in": "TRANSITION_NONE",
        "transition_in_duration_ms": 0,
        "transition_out": "TRANSITION_NONE",
        "transition_out_duration_ms": 0,
        "gain_db": gain_db,
        "is_primary": is_primary and seg.segment_type == "content",
    }


def _expand_to_compiled_segments(
    result: Any,
    resolver: "AssetResolver",
    *,
    slot_duration_ms: int,
    start_utc_ms: int,
    channel_type: str,
    dsl_midroll: list[dict[str, Any]] | None = None,
    target_segment_minutes: int | None = None,
    template_preroll: list[dict[str, Any]] | None = None,
    break_strategy: str | None = None,
    traffic_profile: str | None = None,
) -> list[dict[str, Any]]:
    """Expand an AssemblyResult into break-aware compiled_segments.

    INV-STRUCTURAL-RESOLUTION-001: Break detection runs at compile time.
    INV-SC-BBL-CUTOVER-001: Uses BlockBreakLayout for break decisions.

    Constructs a BlockBreakLayout from the assembly result, then expands
    it into compiled_segments via expand_break_layout. All break decisions
    (source selection, budget allocation, policy) happen inside
    build_break_layout. This function bridges BBL output to the
    compiled_segments schema consumed by the hydration layer.
    """
    content_segs = [s for s in result.segments if s.segment_type == "content"]
    non_content_segs = [s for s in result.segments if s.segment_type != "content"]

    if not content_segs:
        compiled: list[dict[str, Any]] = []
        for s in non_content_segs:
            compiled.append(_serialize_assembly_segment(s, resolver, is_primary=False))
        return compiled

    # Split non-content into preroll (before first content) and postroll (after last content)
    # by walking assembly order. This preserves INV-DSL-SEGMENT-ORDER-DETERMINISTIC-001.
    first_content_idx = next(
        i for i, s in enumerate(result.segments) if s.segment_type == "content"
    )
    last_content_idx = max(
        i for i, s in enumerate(result.segments) if s.segment_type == "content"
    )
    preroll_segs = [
        s for i, s in enumerate(result.segments)
        if s.segment_type not in ("content", "postroll_traffic") and i < first_content_idx
    ]
    postroll_segs = [
        s for i, s in enumerate(result.segments)
        if i > last_content_idx  # includes postroll_traffic markers
    ]

    # Check if postroll has a traffic marker — if so, filler goes at
    # the marker position within the postroll, not as a trailing catch-all.
    has_postroll_traffic = any(
        s.segment_type == "postroll_traffic" for s in postroll_segs
    )

    # --- Resolve primary content asset metadata ---
    primary = content_segs[0]
    ep_meta = resolver.lookup(primary.asset_id)
    content_gain_db = ep_meta.loudness_gain_db

    # Resolve chapter markers from catalog
    chapter_ms: tuple[int, ...] | None = None
    if ep_meta.chapter_markers_sec:
        chapter_ms = tuple(
            int(c * 1000) for c in ep_meta.chapter_markers_sec if c > 0
        )

    # --- Convert assembly segments to BBL types ---
    from retrovue.runtime.block_break_layout import (
        BlockBreakLayout,
        PostrollEntry,
        StructuralEntry,
        build_break_layout,
        expand_break_layout,
    )

    bbl_preroll = []

    # INV-CONTINUITY-DURATION-FILTER-001: Resolve template continuity.presentation
    # into preroll StructuralEntry objects. max_duration_sec filters the pool.
    if template_preroll:
        for elem in template_preroll:
            pool_name = elem.get("pool")
            max_dur = elem.get("max_duration_sec")
            fixed_dur = elem.get("duration_sec")
            if pool_name and hasattr(resolver, "query"):
                match = {"type": elem.get("type", "bumper")}
                raw_ids = resolver.query(match)
                # AIR rejects segment_duration_ms<=0. Catalog rows often get
                # duration_sec=0 when assets.duration_ms was never probed — and
                # max_duration_sec would still admit 0s (0<=max). Drop them and
                # keep query order so the next valid bumper wins deterministically.
                candidates = [
                    c for c in raw_ids
                    if resolver.lookup(c).duration_sec > 0
                ]
                if len(raw_ids) > len(candidates):
                    logger.warning(
                        "INV-STRUCTURAL-DURATION-001: pool %r excluded %d asset(s) "
                        "with duration_sec<=0 (set assets.duration_ms via media probe)",
                        pool_name,
                        len(raw_ids) - len(candidates),
                    )
                # Filter by max_duration_sec (pool selection, not truncation)
                if max_dur is not None:
                    candidates = [
                        c for c in candidates
                        if resolver.lookup(c).duration_sec <= max_dur
                    ]
                if candidates:
                    chosen = candidates[0]
                    meta = resolver.lookup(chosen)
                    bbl_preroll.append(StructuralEntry(
                        asset_id=chosen,
                        duration_ms=meta.duration_sec * 1000,
                        segment_type="presentation",
                    ))
                elif fixed_dur is not None:
                    # No matching asset — use fixed duration placeholder
                    bbl_preroll.append(StructuralEntry(
                        asset_id="",
                        duration_ms=fixed_dur * 1000,
                        segment_type="presentation",
                    ))

    for s in preroll_segs:
        if s.duration_ms <= 0:
            logger.warning(
                "INV-STRUCTURAL-DURATION-001: omitting assembly preroll segment "
                "type=%s asset_id=%s duration_ms=%s",
                s.segment_type,
                s.asset_id,
                s.duration_ms,
            )
            continue
        # Resolve gain_db for structural assets
        seg_gain = 0.0
        if s.asset_id:
            try:
                seg_meta = resolver.lookup(s.asset_id)
                seg_gain = getattr(seg_meta, "loudness_gain_db", 0.0)
            except (KeyError, AttributeError):
                pass
        bbl_preroll.append(StructuralEntry(
            asset_id=s.asset_id,
            duration_ms=s.duration_ms,
            segment_type=s.segment_type,
        ))

    bbl_postroll = []
    for s in postroll_segs:
        if s.segment_type == "postroll_traffic":
            bbl_postroll.append(PostrollEntry(
                asset_id="", duration_ms=0,
                segment_type="postroll_traffic", is_traffic_marker=True,
            ))
        else:
            bbl_postroll.append(PostrollEntry(
                asset_id=s.asset_id, duration_ms=s.duration_ms,
                segment_type=s.segment_type, is_traffic_marker=False,
            ))

    # --- Build layout (all decisions happen here) ---
    layout = build_break_layout(
        grid_slot_ms=slot_duration_ms,
        content_duration_ms=primary.duration_ms,
        channel_type=channel_type,
        block_start_utc_ms=start_utc_ms,
        dsl_midroll=dsl_midroll,
        chapter_markers_ms=chapter_ms,
        preroll=bbl_preroll,
        postroll=bbl_postroll,
        target_segment_minutes=target_segment_minutes,
        break_strategy=break_strategy,
    )

    # --- Expand layout into segment dicts ---
    bbl_segments = expand_break_layout(layout)

    # --- Bridge BBL output → compiled_segments schema ---
    # The hydration layer (dsl_schedule_service._expand_blocks_hydrate)
    # expects specific keys on each compiled segment dict.
    _FADE_DURATION_MS = 500

    compiled: list[dict[str, Any]] = []
    for seg in bbl_segments:
        seg_type = seg["segment_type"]

        # Determine asset_id
        if seg_type == "content":
            asset_id = primary.asset_id
        elif seg_type == "filler":
            asset_id = ""
        else:
            # Structural (presentation, intro, outro)
            asset_id = seg.get("asset_id", "")

        # Map transition_style → transition_in/transition_out
        style = seg.get("transition_style")
        if style == "fade":
            transition_out = "TRANSITION_FADE"
            transition_out_ms = _FADE_DURATION_MS
        else:
            transition_out = "TRANSITION_NONE"
            transition_out_ms = 0

        # Fade-in applies to content after a faded break
        # (content segment following a filler that was preceded by a fade-out)
        # We track this: if the PREVIOUS compiled segment was filler and the
        # segment before that had transition_out=FADE, this content fades in.
        transition_in = "TRANSITION_NONE"
        transition_in_ms = 0
        if seg_type == "content" and len(compiled) >= 2:
            prev = compiled[-1]
            prev_prev = compiled[-2] if len(compiled) >= 2 else None
            if (
                prev.get("segment_type") == "filler"
                and prev_prev is not None
                and prev_prev.get("transition_out") == "TRANSITION_FADE"
            ):
                transition_in = "TRANSITION_FADE"
                transition_in_ms = _FADE_DURATION_MS

        # Resolve gain_db
        if seg_type == "content":
            gain_db = content_gain_db
        elif asset_id:
            try:
                seg_meta = resolver.lookup(asset_id)
                gain_db = getattr(seg_meta, "loudness_gain_db", 0.0)
            except (KeyError, AttributeError):
                gain_db = 0.0
        else:
            gain_db = 0.0

        seg_dict: dict[str, Any] = {
            "segment_type": seg_type,
            "asset_id": asset_id,
            "duration_ms": seg["duration_ms"],
            "asset_start_offset_ms": seg.get("asset_start_offset_ms", 0),
            "transition_in": transition_in,
            "transition_in_duration_ms": transition_in_ms,
            "transition_out": transition_out if seg_type == "content" else "TRANSITION_NONE",
            "transition_out_duration_ms": transition_out_ms if seg_type == "content" else 0,
            "gain_db": gain_db,
            "is_primary": (
                seg_type == "content"
                and channel_type in ("movie", "premium")
                and len(layout.midroll.opportunities) == 0
            ),
        }
        # INV-TRAFFIC-PROFILE-RESOLVED-001: carry resolved traffic profile
        # on each filler/break segment.
        if seg_type == "filler" and traffic_profile:
            seg_dict["traffic_profile"] = traffic_profile
        compiled.append(seg_dict)

    return compiled


# ---------------------------------------------------------------------------
# Grid alignment
# ---------------------------------------------------------------------------


def _grid_slot_duration(grid_minutes: int, episode_duration_sec: int) -> int:
    """Calculate the grid slot duration that fits an episode."""
    slot_sec = grid_minutes * 60
    slots_needed = max(1, -(-episode_duration_sec // slot_sec))  # ceil division
    return slots_needed * slot_sec



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


def _parse_time(time_str: str, broadcast_day: str, tz_name: str, broadcast_day_start_hour: int = 6) -> datetime:
    """Parse HH:MM into an aware datetime for the broadcast day."""
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(tz_name)
    bd = date.fromisoformat(broadcast_day)
    parts = time_str.split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0

    if hour < broadcast_day_start_hour:
        bd = bd + timedelta(days=1)

    return datetime(bd.year, bd.month, bd.day, hour, minute, tzinfo=tz)






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
    broadcast_day_start_hour: int = 6,
    channel_type: str = "network",
    presentation_defs: dict[str, Any] | None = None,
    templates_defs: dict[str, Any] | None = None,
    dsl: dict[str, Any] | None = None,
) -> list[ProgramBlockOutput]:
    """Compile a V2 schedule block into program blocks.

    V2 DSL shape (channel_dsl.md §5–§6):
        - start: "06:00"
          slots: 48
          program: cheers_30
          progression: sequential
          bleed: true

    Pipeline: Schedule Resolver → Program Resolution → Program Assembly

    Delegates to program_assembly.assemble_schedule_block() for fill_mode,
    grid_blocks, and intro/outro handling. Bleed is a schedule-block-level
    decision, read from block_def and passed to assembly.
    """
    from retrovue.runtime.program_assembly import assemble_schedule_block
    from retrovue.runtime.program_definition import AssemblyFault

    start_str = block_def.get("start", "06:00")
    slots = block_def.get("slots", 1)
    if not isinstance(slots, int):
        slots = len(slots)
    progression = block_def.get("progression", "sequential")
    bleed = block_def.get("bleed", False)

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

    current_time = _parse_time(start_str, broadcast_day, tz_name, broadcast_day_start_hour)

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
            prog_def = _resolve_template_for_program(programs[chosen_ref], templates_defs, presentation_defs)
            prog_def = _resolve_presentation_ref(prog_def, presentation_defs)
            pool = prog_def.get("pool", chosen_ref)

            assembly_results = assemble_schedule_block(
                program_ref=chosen_ref,
                program_def=prog_def,
                pool_name=pool,
                slots=1,  # single execution — dynamic mode
                progression=progression,
                grid_minutes=grid_minutes,
                resolver=resolver,
                bleed=bleed,
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

                resolved_tpl = prog_def.get("_resolved_template", {})

                # INV-OVERCONSTRAINED-POLICY-001: Check overconstrained policy
                overconstrained_policy = resolved_tpl.get("overconstrained", "bleed")

                # Bleed: if content exceeds even the capped slot, expand
                if bleed and result.total_runtime_ms > slot_duration * 1000:
                    if overconstrained_policy == "reject":
                        raise CompileError(
                            f"INV-OVERCONSTRAINED-POLICY-001: overconstrained "
                            f"reject — block '{ep_meta.title or chosen_ref}' "
                            f"(template '{prog_def.get('template', '?')}') "
                            f"content_duration={result.total_runtime_ms}ms "
                            f"exceeds slot_duration={slot_duration * 1000}ms "
                            f"(deficit={result.total_runtime_ms - slot_duration * 1000}ms)"
                        )
                    slot_duration = _grid_slot_duration(grid_minutes, result.total_runtime_ms // 1000)
                    needed_blocks = slot_duration // slot_sec
                elif not bleed and result.total_runtime_ms > slot_duration * 1000:
                    if overconstrained_policy == "reject":
                        raise CompileError(
                            f"INV-OVERCONSTRAINED-POLICY-001: overconstrained "
                            f"reject — block '{ep_meta.title or chosen_ref}' "
                            f"(template '{prog_def.get('template', '?')}') "
                            f"content_duration={result.total_runtime_ms}ms "
                            f"exceeds slot_duration={slot_duration * 1000}ms "
                            f"(deficit={result.total_runtime_ms - slot_duration * 1000}ms)"
                        )

                # INV-TRAFFIC-PROFILE-RESOLVED-001: Resolve traffic profile
                resolved_profile = _resolve_block_traffic_profile(
                    block_def, resolved_tpl, dsl or {},
                )

                # INV-UNDERRUN-WARNING-001: Emit warning for extreme underrun
                slot_ms = slot_duration * 1000
                if result.total_runtime_ms < 0.5 * slot_ms:
                    utilization = (result.total_runtime_ms / slot_ms) * 100 if slot_ms > 0 else 0
                    logger.warning(
                        "INV-UNDERRUN-WARNING-001: extreme underrun — "
                        "block='%s' template='%s' "
                        "content_duration=%dms slot_duration=%dms "
                        "utilization=%.1f%%",
                        ep_meta.title or chosen_ref,
                        prog_def.get("template", "none"),
                        result.total_runtime_ms,
                        slot_ms,
                        utilization,
                    )

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
                        "_continuity_optional": (
                            resolved_tpl
                            .get("continuity", {})
                            .get("optional")
                        ),
                    },
                    compiled_segments=_expand_to_compiled_segments(
                        result, resolver,
                        slot_duration_ms=slot_duration * 1000,
                        start_utc_ms=int(current_time.timestamp() * 1000),
                        channel_type=channel_type,
                        dsl_midroll=prog_def.get("presentation_midroll"),
                        target_segment_minutes=(
                            resolved_tpl
                            .get("breaks", {})
                            .get("target_segment_minutes")
                        ),
                        template_preroll=(
                            resolved_tpl
                            .get("continuity", {})
                            .get("presentation")
                        ),
                        break_strategy=(
                            resolved_tpl
                            .get("breaks", {})
                            .get("strategy")
                        ),
                        traffic_profile=resolved_profile,
                    ),
                    traffic_profile=resolved_profile,
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
            prog_def = _resolve_template_for_program(programs[chosen_ref], templates_defs, presentation_defs)
            prog_def = _resolve_presentation_ref(prog_def, presentation_defs)
            pool = prog_def.get("pool", chosen_ref)

            assembly_results = assemble_schedule_block(
                program_ref=chosen_ref,
                program_def=prog_def,
                pool_name=pool,
                slots=uniform_grid_blocks,  # single execution worth of slots
                progression=progression,
                grid_minutes=grid_minutes,
                resolver=resolver,
                bleed=bleed,
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

                resolved_tpl = prog_def.get("_resolved_template", {})

                # INV-OVERCONSTRAINED-POLICY-001: Check overconstrained policy
                overconstrained_policy = resolved_tpl.get("overconstrained", "bleed")

                if bleed and result.total_runtime_ms > slot_duration * 1000:
                    if overconstrained_policy == "reject":
                        raise CompileError(
                            f"INV-OVERCONSTRAINED-POLICY-001: overconstrained "
                            f"reject — block '{ep_meta.title or chosen_ref}' "
                            f"(template '{prog_def.get('template', '?')}') "
                            f"content_duration={result.total_runtime_ms}ms "
                            f"exceeds slot_duration={slot_duration * 1000}ms "
                            f"(deficit={result.total_runtime_ms - slot_duration * 1000}ms)"
                        )
                    slot_duration = _grid_slot_duration(grid_minutes, result.total_runtime_ms // 1000)
                elif not bleed and result.total_runtime_ms > slot_duration * 1000:
                    if overconstrained_policy == "reject":
                        raise CompileError(
                            f"INV-OVERCONSTRAINED-POLICY-001: overconstrained "
                            f"reject — block '{ep_meta.title or chosen_ref}' "
                            f"(template '{prog_def.get('template', '?')}') "
                            f"content_duration={result.total_runtime_ms}ms "
                            f"exceeds slot_duration={slot_duration * 1000}ms "
                            f"(deficit={result.total_runtime_ms - slot_duration * 1000}ms)"
                        )

                # INV-TRAFFIC-PROFILE-RESOLVED-001: Resolve traffic profile
                resolved_profile = _resolve_block_traffic_profile(
                    block_def, resolved_tpl, dsl or {},
                )

                # INV-UNDERRUN-WARNING-001: Emit warning for extreme underrun
                slot_ms = slot_duration * 1000
                if result.total_runtime_ms < 0.5 * slot_ms:
                    utilization = (result.total_runtime_ms / slot_ms) * 100 if slot_ms > 0 else 0
                    logger.warning(
                        "INV-UNDERRUN-WARNING-001: extreme underrun — "
                        "block='%s' template='%s' "
                        "content_duration=%dms slot_duration=%dms "
                        "utilization=%.1f%%",
                        ep_meta.title or chosen_ref,
                        prog_def.get("template", "none"),
                        result.total_runtime_ms,
                        slot_ms,
                        utilization,
                    )

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
                        "_continuity_optional": (
                            resolved_tpl
                            .get("continuity", {})
                            .get("optional")
                        ),
                    },
                    compiled_segments=_expand_to_compiled_segments(
                        result, resolver,
                        slot_duration_ms=slot_duration * 1000,
                        start_utc_ms=int(current_time.timestamp() * 1000),
                        channel_type=channel_type,
                        dsl_midroll=prog_def.get("presentation_midroll"),
                        target_segment_minutes=(
                            resolved_tpl
                            .get("breaks", {})
                            .get("target_segment_minutes")
                        ),
                        template_preroll=(
                            resolved_tpl
                            .get("continuity", {})
                            .get("presentation")
                        ),
                        break_strategy=(
                            resolved_tpl
                            .get("breaks", {})
                            .get("strategy")
                        ),
                        traffic_profile=resolved_profile,
                    ),
                    traffic_profile=resolved_profile,
                )
                blocks.append(block)
                current_time = block.end_at()

    return blocks


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
    resolved_config: dict[str, Any] | None = None,
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
    # Extract scheduling constants from resolved config.
    _compiler_version, _bd_start_hour, _net_grid, _prem_grid = _extract_scheduling_constants(resolved_config)
    _grid_mins = {"network_television": _net_grid, "premium_movie": _prem_grid}

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
    grid_minutes = get_grid_minutes(template, _grid_mins)
    programs_defs = dsl.get("programs", {})

    # Resolve scheduling policy from DSL (INV-POLICY-DSL-DECLARED-001)
    scheduling_policy = resolve_scheduling_policy(dsl)

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
                broadcast_day_start_hour=_bd_start_hour,
                channel_type=dsl.get("channel_type", "network"),
                presentation_defs=dsl.get("presentation"),
                templates_defs=dsl.get("templates"),
                dsl=dsl,
            )
            all_blocks.extend(blocks)

            # Advance prior emissions for subsequent blocks with same run_id
            if rid:
                _run_id_prior[rid] = prior + _block_executions[i]

    # Scheduling policy evaluation (INV-POLICY-DSL-DECLARED-001)
    # Evaluate after asset resolution, before block assembly compaction.
    policy_violations: list[PolicyViolation] = []
    if scheduling_policy is not None and all_blocks:
        eligible_blocks: list[ProgramBlockOutput] = []
        for block in all_blocks:
            adapted = _PolicyAssetAdapter(block, resolver)
            violations = evaluate_scheduling_policies(
                asset=adapted,
                policy=scheduling_policy,
                slot_context=block.selector.get("fill_mode", "") if block.selector else "",
                play_history=[],  # TODO: wire air history from as-run log
                broadcast_date=date.fromisoformat(broadcast_day),
            )
            if violations:
                policy_violations.extend(violations)
                logger.info(
                    "Policy violation: asset %s skipped (%d violations)",
                    block.asset_id, len(violations),
                )
            else:
                eligible_blocks.append(block)
        all_blocks = eligible_blocks

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

    # Tier 3 optional presentation second pass
    # INV-TIER3-COMPILE-RESOLUTION-001: Resolve T3 after compaction
    from retrovue.runtime.optional_presentation import evaluate_optional_presentation

    for i, block in enumerate(all_blocks):
        continuity_optional = (
            block.selector.get("_continuity_optional")
            if block.selector else None
        )
        if not continuity_optional:
            continue
        continuity = {"optional": continuity_optional}
        # Build block dicts for this block and all following (for "coming up next" lookahead)
        block_dicts = []
        for b in all_blocks[i:]:
            block_dicts.append({
                "start_utc_ms": int(b.start_at.timestamp() * 1000),
                "slot_duration_ms": b.slot_duration_sec * 1000,
                "compiled_segments": b.compiled_segments or [],
                "title": b.title,
            })
        result = evaluate_optional_presentation(
            blocks=block_dicts,
            continuity=continuity,
            broadcast_day=broadcast_day,
            channel_id=channel_id,
            features=dsl.get("features"),
        )
        # Apply only the first block's result (the current block)
        updated = result[0]
        all_blocks[i] = replace(
            block,
            compiled_segments=updated["compiled_segments"],
            slot_duration_sec=max(
                block.slot_duration_sec,
                updated["slot_duration_ms"] // 1000,
            ),
        )

    # INV-TRAFFIC-PROFILE-RESOLVED-001: Every block with breaks must have a
    # resolvable traffic profile. Only enforced when the DSL declares a
    # traffic section (backward compat: no traffic section → current behavior).
    if dsl.get("traffic"):
        for block in all_blocks:
            if block.compiled_segments:
                has_filler = any(
                    s.get("segment_type") == "filler"
                    for s in block.compiled_segments
                )
                if has_filler and not block.traffic_profile:
                    raise ValidationError([
                        f"INV-TRAFFIC-PROFILE-RESOLVED-001: block '{block.title}' "
                        f"contains breaks but has no resolvable traffic profile "
                        f"(no block-level, template, or channel default traffic_profile)"
                    ])

    # Build output
    plan: dict[str, Any] = {
        "version": "program-schedule.v2",
        "channel_id": channel_id,
        "broadcast_day": broadcast_day,
        "timezone": tz_name,
        "source": {
            "dsl_path": dsl_path,
            "git_commit": git_commit,
            "compiler_version": _compiler_version,
        },
        "program_blocks": [b.to_dict() for b in all_blocks],
    }

    notes = dsl.get("notes")
    if notes:
        plan["notes"] = notes

    if policy_violations:
        plan["policy_violations"] = [
            {
                "invariant_id": v.invariant_id,
                "rule_type": v.rule_type,
                "message": v.message,
                "details": v.details,
            }
            for v in policy_violations
        ]

    plan["hash"] = _compute_hash(plan)
    return plan


def _compute_hash(plan: dict[str, Any]) -> str:
    hashable = {k: v for k, v in plan.items() if k != "hash"}
    canonical = json.dumps(hashable, sort_keys=True, default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
