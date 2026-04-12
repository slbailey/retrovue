"""
Template resolution and day-of-week schedule layering.

INV-SCHEDULE-COMPILER-MODULE-SPLIT-001: This module owns all resolution logic
that transforms DSL references into concrete configuration. No compilation.
No validation.

Symbols:
- Template extends chains (_resolve_template, _resolve_template_for_program)
- Presentation reference resolution (_resolve_presentation_ref)
- DOW schedule layering (resolve_day_schedule, VALID_SCHEDULE_KEYS, DOW_NAMES, etc.)
- Traffic profile resolution (_resolve_block_traffic_profile)
- Channel template helpers (get_channel_template, get_grid_minutes)
- Scheduling policy DSL resolution (resolve_scheduling_policy, _PolicyAssetAdapter)
"""

from __future__ import annotations

from datetime import date
from typing import Any, TYPE_CHECKING

from retrovue.runtime.asset_resolver import AssetResolver
from retrovue.scheduling.policies import (
    DurationGateRule,
    FrequencyCapRule,
    RepeatWindowRule,
    SchedulingPolicy,
    TagEligibilityRule,
)

if TYPE_CHECKING:
    from retrovue.runtime.schedule_compiler import ProgramBlockOutput


# ---------------------------------------------------------------------------
# Template resolution (timeline_compilation_templates.md)
# ---------------------------------------------------------------------------

# Fields forbidden in template break config per INV-TEMPLATE-BEHAVIOR-NOT-DURATION-001
_FORBIDDEN_TEMPLATE_BREAK_FIELDS = frozenset({"break_count", "break_duration_sec", "grid_slots"})


def _resolve_template(
    name: str,
    templates: dict[str, Any],
    _chain: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Resolve a template by name, following extends chains depth-first.

    Raises ValueError on circular references or missing templates.
    """
    if _chain is None:
        _chain = frozenset()

    if name in _chain:
        raise ValueError(
            f"Circular template extends reference: "
            f"{' -> '.join(_chain)} -> {name}"
        )

    if name not in templates:
        raise ValueError(f"Template '{name}' not found in templates section")

    tpl = dict(templates[name])
    extends = tpl.pop("extends", None)

    if extends is not None:
        parent = _resolve_template(extends, templates, _chain | {name})
        merged = dict(parent)
        for key, value in tpl.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
        return merged

    return tpl


def _resolve_template_for_program(
    prog_def: dict[str, Any],
    templates: dict[str, Any] | None,
    presentation_defs: dict[str, Any] | None,
) -> dict[str, Any]:
    """Resolve template reference on a program definition.

    If prog_def has 'template' key and templates section exists:
    - Resolve the template (with extends)
    - Template wins over 'presentation' (backward compat)

    Returns modified prog_def with '_resolved_template' attached.
    """
    template_name = prog_def.get("template")
    if template_name is None or templates is None:
        return prog_def

    resolved = _resolve_template(template_name, templates)
    prog_def = dict(prog_def)
    prog_def["_resolved_template"] = resolved

    # Template wins over presentation: strip presentation ref
    if "presentation" in prog_def:
        prog_def.pop("presentation", None)

    return prog_def


def _resolve_presentation_ref(
    prog_def: dict[str, Any],
    presentation_defs: dict[str, Any] | None,
) -> dict[str, Any]:
    """Resolve a presentation string reference to inline preroll, postroll, and midroll.

    If prog_def["presentation"] is a string (e.g., "movies"), look it up
    in presentation_defs["programs"]["movies"] and resolve preroll,
    postroll, and midroll phases.

    If it's already a list (old inline format), return prog_def unchanged.
    If presentation_defs is None or the reference doesn't resolve, clear it.

    Validates:
        INV-POSTROLL-TRAFFIC-PREROLL-FORBIDDEN-001 — no traffic in preroll.
        INV-DSL-SINGLE-FILL-DIRECTIVE-001 — at most one traffic directive
        across preroll + postroll.
    INV-SC-PRESENTATION-MIDROLL-001: midroll extracted and attached as
        presentation_midroll. No validation here — build_break_layout validates.
    """
    pres = prog_def.get("presentation")
    if pres is None or isinstance(pres, list):
        return prog_def  # already inline or absent

    if not isinstance(pres, str):
        return prog_def

    # It's a string reference — resolve from presentation_defs
    if presentation_defs is None:
        # No presentation section in DSL — drop the reference
        resolved = dict(prog_def)
        resolved.pop("presentation", None)
        return resolved

    program_presentations = presentation_defs.get("programs", {})
    pres_block = program_presentations.get(pres, {})
    preroll = pres_block.get("preroll", [])
    postroll = pres_block.get("postroll", [])
    midroll = pres_block.get("midroll")

    # INV-POSTROLL-TRAFFIC-PREROLL-FORBIDDEN-001: no traffic in preroll
    for entry in preroll:
        if isinstance(entry, dict) and entry.get("type") == "traffic":
            raise ValueError(
                "INV-POSTROLL-TRAFFIC-PREROLL-FORBIDDEN-001: "
                "traffic directive is forbidden in preroll"
            )

    # INV-DSL-SINGLE-FILL-DIRECTIVE-001: at most one traffic directive total
    all_entries = list(preroll) + list(postroll)
    traffic_count = sum(
        1 for e in all_entries
        if isinstance(e, dict) and e.get("type") == "traffic"
    )
    if traffic_count > 1:
        raise ValueError(
            f"INV-DSL-SINGLE-FILL-DIRECTIVE-001: {traffic_count} traffic "
            f"directives found across preroll+postroll, max 1 allowed"
        )

    resolved = dict(prog_def)
    if preroll:
        resolved["presentation"] = preroll
    else:
        resolved.pop("presentation", None)
    resolved["presentation_postroll"] = postroll
    resolved["presentation_midroll"] = midroll

    return resolved


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


def get_grid_minutes(template: str, grid_minutes: dict[str, int] | None = None) -> int:
    if grid_minutes is not None:
        if template == "premium_movie":
            return grid_minutes["premium_movie"]
        return grid_minutes["network_television"]
    # Unreachable in production (resolved_config always provides grid_minutes).
    if template == "premium_movie":
        return 15
    return 30


# ---------------------------------------------------------------------------
# Traffic profile resolution (traffic_profiles_conformance.md)
# ---------------------------------------------------------------------------


def _resolve_block_traffic_profile(
    block_def: dict[str, Any],
    resolved_template: dict[str, Any] | None,
    dsl: dict[str, Any],
) -> str | None:
    """Resolve traffic profile for a compiled block.

    INV-TRAFFIC-PROFILE-RESOLVED-001: Resolution precedence:
        1. Block-level override (schedule block traffic_profile)
        2. Template breaks.traffic_profile
        3. Channel traffic.default

    Returns the resolved profile name, or None if no traffic section exists.
    """
    # 1. Block-level override
    block_profile = block_def.get("traffic_profile")
    if block_profile:
        return block_profile

    # 2. Template breaks.traffic_profile
    if resolved_template:
        template_profile = (
            resolved_template.get("breaks", {}).get("traffic_profile")
        )
        if template_profile:
            return template_profile

    # 3. Channel traffic.default
    traffic = dsl.get("traffic")
    if traffic:
        return traffic.get("default")

    return None


# ---------------------------------------------------------------------------
# Scheduling policy DSL resolution (INV-POLICY-DSL-DECLARED-001)
# ---------------------------------------------------------------------------


def resolve_scheduling_policy(dsl: dict[str, Any]) -> SchedulingPolicy | None:
    """Resolve the optional ``policies:`` key from channel DSL YAML.

    Returns a frozen SchedulingPolicy if the key is present, None otherwise.
    This is the **only** construction site for SchedulingPolicy objects
    (INV-POLICY-DSL-DECLARED-001).
    """
    raw = dsl.get("policies")
    if not raw:
        return None

    repeat_window = None
    rw = raw.get("repeat_window")
    if rw:
        repeat_window = RepeatWindowRule(
            same_episode_days=rw.get("same_episode_days", 7),
        )

    frequency_cap = None
    fc = raw.get("frequency_cap")
    if fc:
        per_day = fc.get("per_day", fc)
        frequency_cap = FrequencyCapRule(
            max_episodes_per_show=per_day.get("max_episodes_per_show", 0),
        )

    tag_eligibility: list[TagEligibilityRule] = []
    te_raw = raw.get("tag_eligibility")
    if te_raw and isinstance(te_raw, list):
        for entry in te_raw:
            tag_eligibility.append(
                TagEligibilityRule(
                    context=entry.get("context", ""),
                    require_tags=frozenset(entry.get("require_tags", [])),
                    exclude_tags=frozenset(entry.get("exclude_tags", [])),
                )
            )

    duration_gate: list[DurationGateRule] = []
    dg_raw = raw.get("duration_gate")
    if dg_raw and isinstance(dg_raw, list):
        for entry in dg_raw:
            duration_gate.append(
                DurationGateRule(
                    context=entry.get("context", ""),
                    min_duration_sec=entry.get("min_duration_sec", 0),
                    max_duration_sec=entry.get("max_duration_sec", 0),
                )
            )

    return SchedulingPolicy(
        repeat_window=repeat_window,
        frequency_cap=frequency_cap,
        tag_eligibility=tag_eligibility,
        duration_gate=duration_gate,
    )


class _PolicyAssetAdapter:
    """Adapts a ProgramBlockOutput + AssetMetadata to the _SchedulableAsset protocol.

    This adapter bridges the compilation output to the policy evaluation
    interface without coupling the policy layer to compilation internals.
    """

    __slots__ = (
        "asset_id", "show_id", "episode_id",
        "duration_ms", "tags", "state", "approved_for_broadcast",
    )

    def __init__(
        self,
        block: "ProgramBlockOutput",
        resolver: AssetResolver,
    ) -> None:
        self.asset_id = block.asset_id
        self.episode_id = block.asset_id
        # Use pool/collection as show grouping key
        self.show_id = block.collection or ""
        self.state = "ready"
        self.approved_for_broadcast = True
        try:
            meta = resolver.lookup(block.asset_id)
            self.duration_ms = meta.duration_sec * 1000
            self.tags = frozenset(meta.tags)
        except (KeyError, AttributeError):
            self.duration_ms = block.episode_duration_sec * 1000
            self.tags = frozenset()
