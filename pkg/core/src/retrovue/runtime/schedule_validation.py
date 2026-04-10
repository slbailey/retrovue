"""
Schedule DSL validation.

INV-SCHEDULE-COMPILER-MODULE-SPLIT-001: This module owns all validation logic
for DSL structure, grid alignment, traffic profile references, and post-compile
block validation. No compilation. No resolution.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, TYPE_CHECKING

from retrovue.runtime.asset_resolver import AssetResolver
from retrovue.runtime.template_resolution import (
    _FORBIDDEN_TEMPLATE_BREAK_FIELDS,
    get_channel_template,
    get_grid_minutes,
)

if TYPE_CHECKING:
    from retrovue.runtime.schedule_compiler import ProgramBlockOutput


# ---------------------------------------------------------------------------
# Template validation
# ---------------------------------------------------------------------------


def _validate_templates(templates: dict[str, Any]) -> list[str]:
    """Validate the templates: section of a channel DSL.

    Returns a list of error strings (empty = valid).
    """
    errors: list[str] = []
    for name, tpl in templates.items():
        if not isinstance(tpl, dict):
            errors.append(f"Template '{name}' must be a mapping")
            continue
        breaks = tpl.get("breaks")
        if isinstance(breaks, dict):
            for forbidden in _FORBIDDEN_TEMPLATE_BREAK_FIELDS:
                if forbidden in breaks:
                    errors.append(
                        f"INV-TEMPLATE-BEHAVIOR-NOT-DURATION-001: "
                        f"template '{name}' contains forbidden field "
                        f"'breaks.{forbidden}'"
                    )
    return errors


# ---------------------------------------------------------------------------
# Grid alignment validation
# ---------------------------------------------------------------------------


def _validate_grid_alignment(blocks: "list[ProgramBlockOutput]", grid_minutes: int) -> None:
    """Assert all blocks are grid-aligned. Raises CompileError on violation.

    Uses epoch-second math for wall-clock alignment independent of hour boundaries
    and timezone edge cases. Does not depend on .minute arithmetic.

    INV-BLEED-NO-GAP-001: Scope applies only to ProgramBlockOutput emitted by
    DSL schedule compilation. Does NOT apply to downstream playlog segmentation
    or ad pod sub-blocks.
    """
    from retrovue.runtime.schedule_compiler import CompileError

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


# ---------------------------------------------------------------------------
# Traffic profile reference validation
# ---------------------------------------------------------------------------


def _validate_traffic_profile_refs(dsl: dict[str, Any]) -> list[str]:
    """Validate that all traffic_profile references in templates and schedule
    blocks resolve to profiles declared in traffic.profiles.

    INV-TRAFFIC-PROFILE-RESOLVED-001: Unresolvable references are rejected
    at validation time.
    """
    errors: list[str] = []
    traffic = dsl.get("traffic")
    if not traffic:
        return errors  # No traffic section — validation of missing profiles
        # happens at compile time, not here.

    profiles = traffic.get("profiles", {})

    # Validate traffic.default
    default_ref = traffic.get("default")
    if default_ref and default_ref not in profiles:
        errors.append(
            f"INV-TRAFFIC-PROFILE-RESOLVED-001: traffic.default "
            f"'{default_ref}' not found in traffic.profiles"
        )

    # Validate template breaks.traffic_profile references
    templates = dsl.get("templates", {})
    for tpl_name, tpl in templates.items():
        if not isinstance(tpl, dict):
            continue
        breaks = tpl.get("breaks", {})
        if isinstance(breaks, dict):
            ref = breaks.get("traffic_profile")
            if ref and ref not in profiles:
                errors.append(
                    f"INV-TRAFFIC-PROFILE-RESOLVED-001: template '{tpl_name}' "
                    f"references traffic_profile '{ref}' not found in "
                    f"traffic.profiles"
                )
        # Validate trailing block profiles
        trailing = tpl.get("trailing", [])
        if isinstance(trailing, list):
            for i, entry in enumerate(trailing):
                if isinstance(entry, dict):
                    ref = entry.get("traffic_profile")
                    if ref and ref not in profiles:
                        errors.append(
                            f"INV-TRAFFIC-PROFILE-RESOLVED-001: template "
                            f"'{tpl_name}' trailing[{i}] references "
                            f"traffic_profile '{ref}' not found in "
                            f"traffic.profiles"
                        )

    # Validate schedule block traffic_profile overrides
    schedule = dsl.get("schedule", {})
    for day_key, day_value in schedule.items():
        blocks = [day_value] if isinstance(day_value, dict) else (
            day_value if isinstance(day_value, list) else []
        )
        for item in blocks:
            if not isinstance(item, dict):
                continue
            ref = item.get("traffic_profile")
            if ref and ref not in profiles:
                errors.append(
                    f"INV-TRAFFIC-PROFILE-RESOLVED-001: schedule.{day_key} "
                    f"references traffic_profile '{ref}' not found in "
                    f"traffic.profiles"
                )

    return errors


# ---------------------------------------------------------------------------
# DSL validation entry point
# ---------------------------------------------------------------------------


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

    # INV-SBLOCK-PROGRAM-002 (early): validate program references across all
    # schedule layers so typos surface at validation, not deep in assembly.
    programs_defs = dsl.get("programs", {})
    for day_key, day_value in schedule.items():
        blocks = [day_value] if isinstance(day_value, dict) else (day_value if isinstance(day_value, list) else [])
        for item in blocks:
            if not isinstance(item, dict):
                continue
            prog_field = item.get("program", "")
            if isinstance(prog_field, str):
                refs = [prog_field] if prog_field else []
            elif isinstance(prog_field, list):
                refs = prog_field
            else:
                refs = []
            for ref in refs:
                if ref not in programs_defs:
                    errors.append(
                        f"INV-SBLOCK-PROGRAM-002: program '{ref}' in "
                        f"schedule.{day_key} not found in program definitions"
                    )

    # Validate templates section if present
    raw_templates = dsl.get("templates")
    if raw_templates and isinstance(raw_templates, dict):
        errors.extend(_validate_templates(raw_templates))

    # INV-TRAFFIC-PROFILE-RESOLVED-001: Validate traffic profile references
    errors.extend(_validate_traffic_profile_refs(dsl))

    return errors


# ---------------------------------------------------------------------------
# Post-compile block validation
# ---------------------------------------------------------------------------


def validate_program_blocks(blocks: "list[ProgramBlockOutput]") -> list[str]:
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
# Lazy re-export: ValidationError lives in schedule_compiler (subclass of
# CompileError) but is re-exported here to satisfy backward-compat imports.
# Deferred to avoid circular import.
# ---------------------------------------------------------------------------

def __getattr__(name: str):
    if name == "ValidationError":
        from retrovue.runtime.schedule_compiler import ValidationError
        return ValidationError
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
