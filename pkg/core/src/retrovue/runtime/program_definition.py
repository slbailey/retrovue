"""ProgramDefinition — editorial unit referenced by schedule blocks.

Contract: docs/contracts/program_definition.md

Defines how content is assembled from a pool into a grid-aligned block
of programming. ProgramDefinitions are reusable, named, declarative
recipes owned by Core.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ValidationFault(Exception):
    """Raised when a ProgramDefinition or schedule block fails validation."""


class AssemblyFault(Exception):
    """Raised when program assembly cannot produce a valid result."""


# ---------------------------------------------------------------------------
# Assembly result types
# ---------------------------------------------------------------------------


@dataclass
class AssemblySegment:
    asset_id: str
    duration_ms: int
    segment_type: str = "content"


@dataclass
class AssemblyResult:
    segments: list[AssemblySegment]
    total_runtime_ms: int
    block_start_ms: int = 0
    next_block_start_offset_ms: int = 0
    actual_end_ms: int = 0


# ---------------------------------------------------------------------------
# Domain object
# ---------------------------------------------------------------------------


@dataclass
class ProgramDefinition:
    name: str
    pool: str
    grid_blocks: int
    fill_mode: str
    intro: str | None = None
    outro: str | None = None
    presentation: list | None = None
    grid_blocks_max: int | None = None

    def __post_init__(self) -> None:
        # Contract: program_presentation.md — mutual exclusion
        if self.intro is not None and self.presentation is not None:
            raise ValueError(
                "ProgramDefinition MUST NOT declare both 'intro' and "
                "'presentation' simultaneously"
            )
        # INV-SBLOCK-PROGRAM-003: grid_blocks and grid_blocks_max are
        # mutually exclusive. grid_blocks > 0 means fixed allocation;
        # grid_blocks_max means dynamic (greedy packing).
        if self.grid_blocks > 0 and self.grid_blocks_max is not None:
            raise ValueError(
                "ProgramDefinition MUST NOT declare both 'grid_blocks' > 0 "
                "and 'grid_blocks_max'. Use one or the other."
            )

    @property
    def is_dynamic_grid(self) -> bool:
        """True when this program uses greedy grid packing (grid_blocks_max)."""
        return self.grid_blocks_max is not None

    def grid_duration_ms(self, grid_minutes: int) -> int:
        return self.grid_blocks * grid_minutes * 60 * 1000


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


def _is_eligible(asset: Any) -> bool:
    return (
        getattr(asset, "state", "ready") == "ready"
        and getattr(asset, "approved_for_broadcast", True) is True
    )


# ---------------------------------------------------------------------------
# Validation functions
# ---------------------------------------------------------------------------


def validate_schedule_block(
    block: Any,
    program: ProgramDefinition | None = None,
    *,
    grid_minutes: int,
) -> None:
    """Validate a schedule block against its referenced ProgramDefinition.

    Enforces:
        INV-PROGRAM-GRID-001 — slots must be a multiple of grid_blocks.
        INV-PROGRAM-SEPARATION-001 — no inline assembly fields (except bleed).
    """
    # INV-PROGRAM-SEPARATION-001: block must reference a program
    block_program = getattr(block, "program", None)
    if not block_program or program is None:
        raise ValidationFault(
            "INV-PROGRAM-SEPARATION-001: schedule block must reference a ProgramDefinition"
        )

    # INV-PROGRAM-SEPARATION-001: reject inline assembly fields
    # Note: bleed is intentionally NOT in the forbidden list — it belongs
    # on the schedule block, not the program definition.
    for forbidden in ("fill_mode", "pool", "intro", "outro"):
        val = getattr(block, forbidden, None)
        if val is not None:
            raise ValidationFault(
                f"INV-PROGRAM-SEPARATION-001: schedule block must not contain "
                f"inline '{forbidden}' (found {val!r})"
            )

    # INV-SBLOCK-PROGRAM-005: progression must be valid
    _VALID_PROGRESSIONS = {"sequential", "random", "shuffle"}
    progression = getattr(block, "progression", None)
    if progression not in _VALID_PROGRESSIONS:
        raise ValidationFault(
            f"INV-SBLOCK-PROGRAM-005: progression '{progression}' is not valid "
            f"(must be one of {sorted(_VALID_PROGRESSIONS)})"
        )

    # INV-PROGRAM-GRID-001: slots must be exact multiple of grid_blocks
    # (only applies to fixed-grid programs; dynamic grid_blocks_max
    # programs use slots as a budget — no modulus check).
    slots = getattr(block, "slots", 0)
    if slots <= 0:
        raise ValidationFault(
            "INV-PROGRAM-GRID-001: slots must be positive"
        )
    if not program.is_dynamic_grid:
        if program.grid_blocks <= 0:
            raise ValidationFault(
                "INV-PROGRAM-GRID-001: grid_blocks must be positive"
            )
        if slots % program.grid_blocks != 0:
            raise ValidationFault(
                f"INV-PROGRAM-GRID-001: slots ({slots}) is not a multiple of "
                f"grid_blocks ({program.grid_blocks})"
            )


def validate_channel_programs(
    *,
    programs: list[ProgramDefinition],
    pools: dict[str, Any],
) -> None:
    """Validate a set of ProgramDefinitions against defined pools.

    Enforces:
        INV-PROGRAM-IDENTITY-001 — unique names.
        INV-PROGRAM-POOL-001 — pool references must resolve.
    """
    # INV-PROGRAM-IDENTITY-001: unique names
    seen: set[str] = set()
    for prog in programs:
        if prog.name in seen:
            raise ValidationFault(
                f"INV-PROGRAM-IDENTITY-001: duplicate program name '{prog.name}'"
            )
        seen.add(prog.name)

    # INV-PROGRAM-POOL-001: pool references must resolve
    for prog in programs:
        if prog.pool not in pools:
            raise ValidationFault(
                f"INV-PROGRAM-POOL-001: program '{prog.name}' references "
                f"undefined pool '{prog.pool}'"
            )


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def assemble_program(
    program: ProgramDefinition,
    pool: Any,
    *,
    grid_minutes: int,
    bleed: bool = False,
    block_start_ms: int = 0,
    intro_asset: Any | None = None,
    outro_asset: Any | None = None,
    presentation_assets: list[Any] | None = None,
) -> AssemblyResult:
    """Assemble content for a single program execution.

    Args:
        bleed: Whether the program may overrun its grid allocation.
            This is a schedule-block-level decision, not a program property.

    Enforces:
        INV-PROGRAM-FILL-001 — single mode selects exactly one asset.
        INV-PROGRAM-FILL-002 — accumulate stops at grid target.
        INV-PROGRAM-BLEED-001 — non-bleeding must not exceed grid.
        INV-PROGRAM-BLEED-002 — bleeding may exceed grid.
        INV-PROGRAM-BLEED-003 — next block start = actual end.
        INV-PROGRAM-POOL-002 — empty eligible pool raises fault.
        INV-PROGRAM-ASSEMBLY-ELIGIBLE-001 — only eligible assets.
        INV-PROGRAM-INTRO-OUTRO-001 — intro/outro in runtime calc.
        INV-PRESENTATION-GRID-BUDGET-001 — presentation deducted from grid.
        INV-PRESENTATION-PRECEDES-PRIMARY-001 — presentation before content.
    """
    grid_ms = program.grid_duration_ms(grid_minutes)

    # INV-PROGRAM-ASSEMBLY-ELIGIBLE-001: check intro/outro eligibility
    if intro_asset is not None and not _is_eligible(intro_asset):
        raise AssemblyFault(
            "INV-PROGRAM-ASSEMBLY-ELIGIBLE-001: intro asset is not eligible"
        )
    if outro_asset is not None and not _is_eligible(outro_asset):
        raise AssemblyFault(
            "INV-PROGRAM-ASSEMBLY-ELIGIBLE-001: outro asset is not eligible"
        )

    # INV-PROGRAM-ASSEMBLY-ELIGIBLE-001: check presentation asset eligibility
    if presentation_assets:
        for pa in presentation_assets:
            if not _is_eligible(pa):
                raise AssemblyFault(
                    "INV-PROGRAM-ASSEMBLY-ELIGIBLE-001: presentation asset "
                    f"'{getattr(pa, 'asset_id', '?')}' is not eligible"
                )

    # Get eligible assets from pool
    if hasattr(pool, "eligible_assets"):
        eligible = pool.eligible_assets()
    else:
        eligible = [a for a in getattr(pool, "assets", []) if _is_eligible(a)]

    # INV-PROGRAM-POOL-002: pool must have eligible assets
    if not eligible:
        raise AssemblyFault(
            "INV-PROGRAM-POOL-002: pool has zero eligible assets"
        )

    # Compute wrapper overhead (INV-PROGRAM-INTRO-OUTRO-001)
    intro_ms = getattr(intro_asset, "duration_ms", 0) if intro_asset else 0
    outro_ms = getattr(outro_asset, "duration_ms", 0) if outro_asset else 0

    # INV-PRESENTATION-GRID-BUDGET-001: presentation durations deducted
    presentation_ms = 0
    if presentation_assets:
        presentation_ms = sum(
            getattr(pa, "duration_ms", 0) for pa in presentation_assets
        )

    wrapper_ms = intro_ms + outro_ms + presentation_ms

    segments: list[AssemblySegment] = []

    if program.fill_mode == "single":
        segments = _assemble_single(
            eligible, grid_ms, wrapper_ms, bleed,
        )
    elif program.fill_mode == "accumulate":
        segments = _assemble_accumulate(
            eligible, grid_ms, wrapper_ms, bleed,
        )
    else:
        raise AssemblyFault(
            f"Unknown fill_mode: {program.fill_mode!r}"
        )

    # INV-PRESENTATION-PRECEDES-PRIMARY-001: prepend presentation stack
    if presentation_assets:
        for i, pa in enumerate(presentation_assets):
            segments.insert(
                i,
                AssemblySegment(
                    asset_id=getattr(pa, "asset_id", f"presentation-{i}"),
                    duration_ms=getattr(pa, "duration_ms", 0),
                    segment_type="presentation",
                ),
            )

    # Prepend intro / append outro
    if intro_asset is not None:
        segments.insert(
            0,
            AssemblySegment(
                asset_id=getattr(intro_asset, "asset_id", "intro"),
                duration_ms=intro_ms,
                segment_type="intro",
            ),
        )
    if outro_asset is not None:
        segments.append(
            AssemblySegment(
                asset_id=getattr(outro_asset, "asset_id", "outro"),
                duration_ms=outro_ms,
                segment_type="outro",
            ),
        )

    total_ms = sum(s.duration_ms for s in segments)

    return AssemblyResult(
        segments=segments,
        total_runtime_ms=total_ms,
        block_start_ms=block_start_ms,
        next_block_start_offset_ms=block_start_ms + total_ms,
        actual_end_ms=block_start_ms + total_ms,
    )


def _assemble_single(
    eligible: list[Any],
    grid_ms: int,
    wrapper_ms: int,
    bleed: bool,
) -> list[AssemblySegment]:
    """INV-PROGRAM-FILL-001: select exactly one content asset."""
    for asset in eligible:
        duration = getattr(asset, "duration_ms", 0)
        total = duration + wrapper_ms
        # INV-PROGRAM-BLEED-001: reject if non-bleeding and exceeds grid
        if not bleed and total > grid_ms:
            continue
        return [
            AssemblySegment(
                asset_id=getattr(asset, "asset_id", "unknown"),
                duration_ms=duration,
            )
        ]
    raise AssemblyFault(
        "INV-PROGRAM-FILL-001: no eligible asset fits the program constraints"
    )


def _assemble_accumulate(
    eligible: list[Any],
    grid_ms: int,
    wrapper_ms: int,
    bleed: bool,
) -> list[AssemblySegment]:
    """INV-PROGRAM-FILL-002: accumulate assets until grid target is met."""
    segments: list[AssemblySegment] = []
    running_ms = wrapper_ms

    for asset in eligible:
        duration = getattr(asset, "duration_ms", 0)

        if not bleed and running_ms + duration > grid_ms:
            # INV-PROGRAM-BLEED-001: would exceed grid, skip
            continue

        segments.append(
            AssemblySegment(
                asset_id=getattr(asset, "asset_id", "unknown"),
                duration_ms=duration,
            )
        )
        running_ms += duration

        # INV-PROGRAM-FILL-002: stop once target met or exceeded
        if running_ms >= grid_ms:
            break

    if not segments:
        raise AssemblyFault(
            "INV-PROGRAM-FILL-002: no eligible assets could be accumulated"
        )

    return segments
