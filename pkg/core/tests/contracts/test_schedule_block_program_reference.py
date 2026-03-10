"""Contract tests for Schedule Block Program Reference.

Validates all invariants defined in:
    docs/contracts/schedule_block_program_reference.md

Derived from: LAW-CONTENT-AUTHORITY, LAW-GRID, LAW-DERIVATION.

These tests call interfaces from retrovue.runtime.program_definition.
Some tests exercise validation paths that may not yet enforce the
exact invariant ID cited. They are expected to fail until enforcement
is complete.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from retrovue.runtime.program_definition import (
    ProgramDefinition,
    ValidationFault,
    validate_schedule_block,
)


# ---------------------------------------------------------------------------
# Minimal helpers — no database, no real domain objects
# ---------------------------------------------------------------------------

GRID_MINUTES = 30


@dataclass
class FakeScheduleBlock:
    """Minimal schedule block for contract testing."""

    start: str
    slots: int
    program: str | None
    progression: str = "sequential"
    # Assembly-level fields that MUST NOT appear on schedule blocks.
    pool: str | None = None
    fill_mode: str | None = None
    bleed: bool | None = None
    intro: str | None = None
    outro: str | None = None


def _prog(name: str = "test_prog", grid_blocks: int = 2) -> ProgramDefinition:
    return ProgramDefinition(
        name=name,
        pool="movies",
        grid_blocks=grid_blocks,
        fill_mode="single",
    )


def _block(
    program: str | None = "test_prog",
    slots: int = 4,
    progression: str = "sequential",
    **overrides,
) -> FakeScheduleBlock:
    return FakeScheduleBlock(
        start="20:00",
        slots=slots,
        program=program,
        progression=progression,
        **overrides,
    )


def _programs_by_name(*progs: ProgramDefinition) -> dict[str, ProgramDefinition]:
    return {p.name: p for p in progs}


def _resolve_and_validate(
    block: FakeScheduleBlock,
    programs: dict[str, ProgramDefinition],
    grid_minutes: int = GRID_MINUTES,
) -> ProgramDefinition:
    """Resolve program reference then validate. Raises ValidationFault on failure."""
    ref = getattr(block, "program", None)
    if not ref:
        raise ValidationFault(
            "INV-SBLOCK-PROGRAM-001: schedule block must contain a program reference"
        )
    program = programs.get(ref)
    if program is None:
        raise ValidationFault(
            f"INV-SBLOCK-PROGRAM-002: program '{ref}' not found in channel configuration"
        )
    validate_schedule_block(block, program, grid_minutes=grid_minutes)
    return program


# ===========================================================================
# INV-SBLOCK-PROGRAM-001
# Schedule block must contain a program reference
# ===========================================================================


@pytest.mark.contract
class TestInvSblockProgram001:
    """INV-SBLOCK-PROGRAM-001"""

    # Tier: 2 | Scheduling logic invariant
    def test_empty_program_reference_rejected(self):
        # INV-SBLOCK-PROGRAM-001 — empty string program field → reject
        block = _block(program="")
        programs = _programs_by_name(_prog())

        with pytest.raises(ValidationFault):
            _resolve_and_validate(block, programs)

    # Tier: 2 | Scheduling logic invariant
    def test_missing_program_reference_rejected(self):
        # INV-SBLOCK-PROGRAM-001 — null program field → reject
        block = _block(program=None)
        programs = _programs_by_name(_prog())

        with pytest.raises(ValidationFault):
            _resolve_and_validate(block, programs)

    # Tier: 2 | Scheduling logic invariant
    def test_valid_program_reference_accepted(self):
        # INV-SBLOCK-PROGRAM-001 — non-empty program field → accept
        prog = _prog()
        block = _block(program=prog.name, slots=4)
        programs = _programs_by_name(prog)

        # Must not raise
        resolved = _resolve_and_validate(block, programs)
        assert resolved.name == prog.name


# ===========================================================================
# INV-SBLOCK-PROGRAM-002
# Program reference must resolve to a defined ProgramDefinition
# ===========================================================================


@pytest.mark.contract
class TestInvSblockProgram002:
    """INV-SBLOCK-PROGRAM-002"""

    # Tier: 2 | Scheduling logic invariant
    def test_undefined_program_rejected(self):
        # INV-SBLOCK-PROGRAM-002 — reference to nonexistent program → reject
        block = _block(program="ghost_program")
        programs = _programs_by_name(_prog(name="real_program"))

        with pytest.raises(ValidationFault):
            _resolve_and_validate(block, programs)

    # Tier: 2 | Scheduling logic invariant
    def test_defined_program_resolves(self):
        # INV-SBLOCK-PROGRAM-002 — reference to existing program → resolves
        prog = _prog(name="weekend_movie")
        block = _block(program="weekend_movie", slots=4)
        programs = _programs_by_name(prog)

        resolved = _resolve_and_validate(block, programs)
        assert resolved is prog


# ===========================================================================
# INV-SBLOCK-PROGRAM-003
# Slots must be a multiple of program grid_blocks
# ===========================================================================


@pytest.mark.contract
class TestInvSblockProgram003:
    """INV-SBLOCK-PROGRAM-003"""

    # Tier: 2 | Scheduling logic invariant
    def test_slots_not_multiple_rejected(self):
        # INV-SBLOCK-PROGRAM-003 — slots=5, grid_blocks=2 → not a multiple → reject
        prog = _prog(grid_blocks=2)
        block = _block(program=prog.name, slots=5)
        programs = _programs_by_name(prog)

        with pytest.raises(ValidationFault):
            _resolve_and_validate(block, programs)

    # Tier: 2 | Scheduling logic invariant
    def test_slots_exact_multiple_accepted(self):
        # INV-SBLOCK-PROGRAM-003 — slots=4, grid_blocks=2 → exact multiple → accept
        prog = _prog(grid_blocks=2)
        block = _block(program=prog.name, slots=4)
        programs = _programs_by_name(prog)

        _resolve_and_validate(block, programs)

    # Tier: 2 | Scheduling logic invariant
    def test_slots_equal_grid_blocks_accepted(self):
        # INV-SBLOCK-PROGRAM-003 — slots=2, grid_blocks=2 → single execution → accept
        prog = _prog(grid_blocks=2)
        block = _block(program=prog.name, slots=2)
        programs = _programs_by_name(prog)

        _resolve_and_validate(block, programs)


# ===========================================================================
# INV-SBLOCK-PROGRAM-004
# Schedule block must not contain assembly fields
# ===========================================================================


@pytest.mark.contract
class TestInvSblockProgram004:
    """INV-SBLOCK-PROGRAM-004"""

    # Tier: 2 | Scheduling logic invariant
    def test_inline_pool_rejected(self):
        # INV-SBLOCK-PROGRAM-004 — schedule block with pool field → reject
        prog = _prog()
        block = _block(program=prog.name, slots=4, pool="movies")
        programs = _programs_by_name(prog)

        with pytest.raises(ValidationFault):
            _resolve_and_validate(block, programs)

    # Tier: 2 | Scheduling logic invariant
    def test_inline_fill_mode_rejected(self):
        # INV-SBLOCK-PROGRAM-004 — schedule block with fill_mode field → reject
        prog = _prog()
        block = _block(program=prog.name, slots=4, fill_mode="single")
        programs = _programs_by_name(prog)

        with pytest.raises(ValidationFault):
            _resolve_and_validate(block, programs)

    # Tier: 2 | Scheduling logic invariant
    def test_inline_intro_rejected(self):
        # INV-SBLOCK-PROGRAM-004 — schedule block with intro field → reject
        prog = _prog()
        block = _block(program=prog.name, slots=4, intro="some_intro")
        programs = _programs_by_name(prog)

        with pytest.raises(ValidationFault):
            _resolve_and_validate(block, programs)

    # Tier: 2 | Scheduling logic invariant
    def test_inline_outro_rejected(self):
        # INV-SBLOCK-PROGRAM-004 — schedule block with outro field → reject
        prog = _prog()
        block = _block(program=prog.name, slots=4, outro="some_outro")
        programs = _programs_by_name(prog)

        with pytest.raises(ValidationFault):
            _resolve_and_validate(block, programs)


# ===========================================================================
# INV-SBLOCK-PROGRAM-005
# Progression mode must be valid
# ===========================================================================


@pytest.mark.contract
class TestInvSblockProgram005:
    """INV-SBLOCK-PROGRAM-005"""

    # Tier: 2 | Scheduling logic invariant
    def test_valid_progression_sequential(self):
        # INV-SBLOCK-PROGRAM-005 — progression: sequential → accept
        prog = _prog()
        block = _block(program=prog.name, slots=4, progression="sequential")
        programs = _programs_by_name(prog)

        _resolve_and_validate(block, programs)

    # Tier: 2 | Scheduling logic invariant
    def test_valid_progression_random(self):
        # INV-SBLOCK-PROGRAM-005 — progression: random → accept
        prog = _prog()
        block = _block(program=prog.name, slots=4, progression="random")
        programs = _programs_by_name(prog)

        _resolve_and_validate(block, programs)

    # Tier: 2 | Scheduling logic invariant
    def test_valid_progression_shuffle(self):
        # INV-SBLOCK-PROGRAM-005 — progression: shuffle → accept
        prog = _prog()
        block = _block(program=prog.name, slots=4, progression="shuffle")
        programs = _programs_by_name(prog)

        _resolve_and_validate(block, programs)

    # Tier: 2 | Scheduling logic invariant
    def test_invalid_progression_rejected(self):
        # INV-SBLOCK-PROGRAM-005 — progression: alphabetical → reject
        prog = _prog()
        block = _block(program=prog.name, slots=4, progression="alphabetical")
        programs = _programs_by_name(prog)

        with pytest.raises(ValidationFault):
            _resolve_and_validate(block, programs)


# ===========================================================================
# INV-SBLOCK-PROGRAM-003 — grid_blocks_max variant
# Slots are a budget when grid_blocks_max is set; no modulus check.
# ===========================================================================


@pytest.mark.contract
class TestInvSblockProgram003GridBlocksMax:
    """INV-SBLOCK-PROGRAM-003 — grid_blocks_max relaxation"""

    # Tier: 2 | Scheduling logic invariant
    def test_grid_blocks_max_slots_not_multiple_accepted(self):
        # With grid_blocks_max, slots=7 is valid even though 7 is not
        # a multiple of grid_blocks_max=5. Slots is just a budget.
        prog = ProgramDefinition(
            name="movie_prog",
            pool="movies",
            grid_blocks=0,
            grid_blocks_max=5,
            fill_mode="single",
        )
        block = _block(program=prog.name, slots=7)
        programs = _programs_by_name(prog)

        # Must not raise — slots is a budget, not a multiple.
        _resolve_and_validate(block, programs)

    # Tier: 2 | Scheduling logic invariant
    def test_grid_blocks_max_single_slot_accepted(self):
        # Even a single slot is valid — the movie may just bleed.
        prog = ProgramDefinition(
            name="movie_prog",
            pool="movies",
            grid_blocks=0,
            grid_blocks_max=5,
            fill_mode="single",
        )
        block = _block(program=prog.name, slots=1)
        programs = _programs_by_name(prog)

        _resolve_and_validate(block, programs)

    # Tier: 2 | Scheduling logic invariant
    def test_grid_blocks_and_grid_blocks_max_mutually_exclusive(self):
        # A ProgramDefinition MUST NOT have both grid_blocks > 0 AND
        # grid_blocks_max set. They are mutually exclusive.
        with pytest.raises((ValueError, ValidationFault)):
            ProgramDefinition(
                name="bad_prog",
                pool="movies",
                grid_blocks=4,
                grid_blocks_max=5,
                fill_mode="single",
            )
