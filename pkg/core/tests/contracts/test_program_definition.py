"""Contract tests for ProgramDefinition.

Validates all invariants defined in:
    docs/contracts/program_definition.md

Derived from: LAW-CONTENT-AUTHORITY, LAW-GRID, LAW-ELIGIBILITY, LAW-DERIVATION.

These tests call interfaces that do not yet exist (ProgramDefinition,
validate_channel_programs, assemble_program). They are expected to fail
until the implementation is provided.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from retrovue.runtime.program_definition import (
    AssemblyFault,
    ProgramDefinition,
    ValidationFault,
    assemble_program,
    validate_channel_programs,
    validate_schedule_block,
)


# ---------------------------------------------------------------------------
# Fake domain objects — minimal fields for contract testing
# ---------------------------------------------------------------------------

GRID_MINUTES = 30


@dataclass
class FakeAsset:
    asset_id: str
    duration_ms: int
    state: str = "ready"
    approved_for_broadcast: bool = True


@dataclass
class FakePool:
    name: str
    assets: list[FakeAsset] = field(default_factory=list)

    def eligible_assets(self) -> list[FakeAsset]:
        return [
            a
            for a in self.assets
            if a.state == "ready" and a.approved_for_broadcast
        ]


@dataclass
class FakeScheduleBlock:
    start: str
    slots: int
    program: str
    progression: str = "sequential"
    # Assembly-level fields that must NOT appear on schedule blocks.
    fill_mode: str | None = None
    bleed: bool | None = None
    pool: str | None = None
    intro: str | None = None
    outro: str | None = None


def _ms(minutes: int) -> int:
    return minutes * 60 * 1000


def _make_pool(*durations_min: int, name: str = "movies") -> FakePool:
    return FakePool(
        name=name,
        assets=[
            FakeAsset(asset_id=f"asset-{i}", duration_ms=_ms(d))
            for i, d in enumerate(durations_min)
        ],
    )


def _make_program(
    name: str = "test_prog",
    pool: str = "movies",
    grid_blocks: int = 2,
    fill_mode: str = "single",
    bleed: bool = False,
    intro: str | None = None,
    outro: str | None = None,
) -> ProgramDefinition:
    return ProgramDefinition(
        name=name,
        pool=pool,
        grid_blocks=grid_blocks,
        fill_mode=fill_mode,
        bleed=bleed,
        intro=intro,
        outro=outro,
    )


# ===========================================================================
# INV-PROGRAM-GRID-001
# Schedule block slots must be a multiple of program grid_blocks
# ===========================================================================


@pytest.mark.contract
class TestInvProgramGrid001:
    """INV-PROGRAM-GRID-001"""

    def test_schedule_slots_must_be_multiple_of_grid_blocks(self):
        # INV-PROGRAM-GRID-001 — slots=5, grid_blocks=2 → not a multiple → reject
        prog = _make_program(grid_blocks=2)
        block = FakeScheduleBlock(start="20:00", slots=5, program=prog.name)

        with pytest.raises(ValidationFault):
            validate_schedule_block(block, prog, grid_minutes=GRID_MINUTES)

    def test_schedule_slots_exact_multiple_accepted(self):
        # INV-PROGRAM-GRID-001 — slots=4, grid_blocks=2 → exact multiple → accept
        prog = _make_program(grid_blocks=2)
        block = FakeScheduleBlock(start="20:00", slots=4, program=prog.name)

        # Must not raise
        validate_schedule_block(block, prog, grid_minutes=GRID_MINUTES)


# ===========================================================================
# INV-PROGRAM-FILL-001
# Single fill mode selects exactly one asset per execution
# ===========================================================================


@pytest.mark.contract
class TestInvProgramFill001:
    """INV-PROGRAM-FILL-001"""

    def test_single_fill_selects_one_asset(self):
        # INV-PROGRAM-FILL-001 — single mode produces exactly one content asset
        prog = _make_program(fill_mode="single", grid_blocks=2, bleed=True)
        pool = _make_pool(50, 45, name="movies")

        result = assemble_program(prog, pool, grid_minutes=GRID_MINUTES)

        content_segments = [s for s in result.segments if s.segment_type == "content"]
        assert len(content_segments) == 1

    def test_single_fill_rejects_zero_assets(self):
        # INV-PROGRAM-FILL-001 — single mode with empty pool raises AssemblyFault
        prog = _make_program(fill_mode="single", grid_blocks=2)
        pool = FakePool(name="movies", assets=[])

        with pytest.raises(AssemblyFault):
            assemble_program(prog, pool, grid_minutes=GRID_MINUTES)


# ===========================================================================
# INV-PROGRAM-FILL-002
# Accumulate fill mode stops at or just past grid target
# ===========================================================================


@pytest.mark.contract
class TestInvProgramFill002:
    """INV-PROGRAM-FILL-002"""

    def test_accumulate_stops_at_grid_target(self):
        # INV-PROGRAM-FILL-002 — accumulate stops once running total meets target
        # grid_blocks=2 → target = 60min. Three 25-min assets: first two = 50min
        # (under), third brings to 75min (meets). Expect 3 assets.
        prog = _make_program(
            fill_mode="accumulate", grid_blocks=2, bleed=True,
        )
        pool = _make_pool(25, 25, 25, 25, name="movies")

        result = assemble_program(prog, pool, grid_minutes=GRID_MINUTES)

        content_segments = [s for s in result.segments if s.segment_type == "content"]
        # 25+25=50 < 60, 25+25+25=75 >= 60 → stop at 3
        assert len(content_segments) == 3

    def test_accumulate_does_not_overshoot(self):
        # INV-PROGRAM-FILL-002 — must not add assets past the first one to meet target
        # grid_blocks=2 → target = 60min. 55-min + 10-min = 65 (meets).
        # A trailing 5-min asset must NOT be added.
        prog = _make_program(
            fill_mode="accumulate", grid_blocks=2, bleed=True,
        )
        pool = _make_pool(55, 10, 5, name="movies")

        result = assemble_program(prog, pool, grid_minutes=GRID_MINUTES)

        content_segments = [s for s in result.segments if s.segment_type == "content"]
        total_ms = sum(s.duration_ms for s in content_segments)
        # 55+10=65 >= 60, stop. Must not include the 5-min asset.
        assert len(content_segments) == 2
        assert total_ms == _ms(65)


# ===========================================================================
# INV-PROGRAM-BLEED-001
# Non-bleeding programs must not exceed grid allocation
# ===========================================================================


@pytest.mark.contract
class TestInvProgramBleed001:
    """INV-PROGRAM-BLEED-001"""

    def test_no_bleed_rejects_overlong_single(self):
        # INV-PROGRAM-BLEED-001 — bleed=false, single mode, 90-min asset in
        # 2-slot (60-min) program → asset rejected, next tried.
        # Only a 55-min asset fits.
        prog = _make_program(
            fill_mode="single", grid_blocks=2, bleed=False,
        )
        pool = FakePool(
            name="movies",
            assets=[
                FakeAsset(asset_id="too-long", duration_ms=_ms(90)),
                FakeAsset(asset_id="fits", duration_ms=_ms(55)),
            ],
        )

        result = assemble_program(prog, pool, grid_minutes=GRID_MINUTES)

        content_segments = [s for s in result.segments if s.segment_type == "content"]
        assert len(content_segments) == 1
        assert content_segments[0].asset_id == "fits"

    def test_no_bleed_accumulate_excludes_overflow(self):
        # INV-PROGRAM-BLEED-001 — bleed=false, accumulate mode.
        # grid_blocks=2 → 60min target. Assets: 30, 25, 20.
        # 30+25=55 < 60. Adding 20 → 75 > 60 → excluded.
        # Total must be <= 60min.
        prog = _make_program(
            fill_mode="accumulate", grid_blocks=2, bleed=False,
        )
        pool = _make_pool(30, 25, 20, name="movies")

        result = assemble_program(prog, pool, grid_minutes=GRID_MINUTES)

        content_segments = [s for s in result.segments if s.segment_type == "content"]
        total_ms = sum(s.duration_ms for s in content_segments)
        assert total_ms <= _ms(60)


# ===========================================================================
# INV-PROGRAM-BLEED-002
# Bleeding programs may exceed grid allocation
# ===========================================================================


@pytest.mark.contract
class TestInvProgramBleed002:
    """INV-PROGRAM-BLEED-002"""

    def test_bleed_allows_overrun(self):
        # INV-PROGRAM-BLEED-002 — bleed=true, single mode, 90-min asset in
        # 2-slot (60-min) program → accepted, not truncated.
        prog = _make_program(
            fill_mode="single", grid_blocks=2, bleed=True,
        )
        pool = _make_pool(90, name="movies")

        result = assemble_program(prog, pool, grid_minutes=GRID_MINUTES)

        content_segments = [s for s in result.segments if s.segment_type == "content"]
        assert len(content_segments) == 1
        assert content_segments[0].duration_ms == _ms(90)
        assert result.total_runtime_ms > _ms(60)


# ===========================================================================
# INV-PROGRAM-BLEED-003
# Bleed seam continuity
# ===========================================================================


@pytest.mark.contract
class TestInvProgramBleed003:
    """INV-PROGRAM-BLEED-003"""

    def test_bleed_shifts_next_block_start(self):
        # INV-PROGRAM-BLEED-003 — bleeding program ends at actual_end;
        # next block must start exactly there.
        prog = _make_program(
            name="movie", fill_mode="single", grid_blocks=2, bleed=True,
        )
        pool = _make_pool(90, name="movies")

        result = assemble_program(prog, pool, grid_minutes=GRID_MINUTES)

        # Scheduled start was grid-slot 0. Grid allocation = 60min.
        # Actual runtime = 90min. Next block must start at 90min offset.
        assert result.total_runtime_ms == _ms(90)
        assert result.next_block_start_offset_ms == _ms(90)

    def test_bleed_seam_no_gap_no_overlap(self):
        # INV-PROGRAM-BLEED-003 — verify no gap/overlap at the seam.
        # Two consecutive bleeding programs: each 90min in 60min slots.
        # Block A: starts at 0, ends at 90min.
        # Block B: must start at exactly 90min.
        prog_a = _make_program(
            name="movie_a", fill_mode="single", grid_blocks=2, bleed=True,
        )
        prog_b = _make_program(
            name="movie_b", fill_mode="single", grid_blocks=2, bleed=True,
        )
        pool = _make_pool(90, 85, name="movies")

        result_a = assemble_program(
            prog_a, pool, grid_minutes=GRID_MINUTES, block_start_ms=0,
        )
        result_b = assemble_program(
            prog_b, pool, grid_minutes=GRID_MINUTES,
            block_start_ms=result_a.next_block_start_offset_ms,
        )

        # No gap: B starts exactly where A ends
        assert result_b.block_start_ms == result_a.actual_end_ms
        # No overlap: B does not start before A ends
        assert result_b.block_start_ms >= result_a.actual_end_ms


# ===========================================================================
# INV-PROGRAM-POOL-001
# Program pool reference must resolve to a defined pool
# ===========================================================================


@pytest.mark.contract
class TestInvProgramPool001:
    """INV-PROGRAM-POOL-001"""

    def test_undefined_pool_rejected(self):
        # INV-PROGRAM-POOL-001 — pool reference to nonexistent pool → ValidationFault
        prog = _make_program(pool="nonexistent_pool")
        defined_pools = {"movies": _make_pool(90, name="movies")}

        with pytest.raises(ValidationFault):
            validate_channel_programs(
                programs=[prog], pools=defined_pools,
            )


# ===========================================================================
# INV-PROGRAM-POOL-002
# Assembly must fail when resolved pool has zero eligible assets
# ===========================================================================


@pytest.mark.contract
class TestInvProgramPool002:
    """INV-PROGRAM-POOL-002"""

    def test_empty_pool_raises_assembly_fault(self):
        # INV-PROGRAM-POOL-002 — pool exists but has zero eligible assets
        prog = _make_program(fill_mode="single", grid_blocks=2)
        pool = FakePool(
            name="movies",
            assets=[
                FakeAsset(
                    asset_id="not-ready",
                    duration_ms=_ms(50),
                    state="enriching",
                    approved_for_broadcast=False,
                ),
            ],
        )

        with pytest.raises(AssemblyFault):
            assemble_program(prog, pool, grid_minutes=GRID_MINUTES)


# ===========================================================================
# INV-PROGRAM-IDENTITY-001
# Program names must be unique within channel configuration
# ===========================================================================


@pytest.mark.contract
class TestInvProgramIdentity001:
    """INV-PROGRAM-IDENTITY-001"""

    def test_duplicate_program_name_rejected(self):
        # INV-PROGRAM-IDENTITY-001 — two programs with same name → ValidationFault
        prog_a = _make_program(name="movie_night", pool="movies")
        prog_b = _make_program(name="movie_night", pool="comedies")
        pools = {
            "movies": _make_pool(90, name="movies"),
            "comedies": _make_pool(25, name="comedies"),
        }

        with pytest.raises(ValidationFault):
            validate_channel_programs(
                programs=[prog_a, prog_b], pools=pools,
            )


# ===========================================================================
# INV-PROGRAM-INTRO-OUTRO-001
# Intro and outro durations are included in runtime calculations
# ===========================================================================


@pytest.mark.contract
class TestInvProgramIntroOutro001:
    """INV-PROGRAM-INTRO-OUTRO-001"""

    def test_intro_duration_included_in_grid_calc(self):
        # INV-PROGRAM-INTRO-OUTRO-001 — 5-min intro + 58-min asset = 63min,
        # exceeds 60-min grid with bleed=false → no fitting asset → AssemblyFault.
        prog = _make_program(
            fill_mode="single", grid_blocks=2, bleed=False,
            intro="intro_asset",
        )
        pool = _make_pool(58, name="movies")
        intro_asset = FakeAsset(asset_id="intro_asset", duration_ms=_ms(5))

        with pytest.raises(AssemblyFault):
            assemble_program(
                prog, pool, grid_minutes=GRID_MINUTES,
                intro_asset=intro_asset,
            )

    def test_outro_duration_included_in_grid_calc(self):
        # INV-PROGRAM-INTRO-OUTRO-001 — 58-min asset + 5-min outro = 63min,
        # exceeds 60-min grid with bleed=false → no fitting asset → AssemblyFault.
        prog = _make_program(
            fill_mode="single", grid_blocks=2, bleed=False,
            outro="outro_asset",
        )
        pool = _make_pool(58, name="movies")
        outro_asset = FakeAsset(asset_id="outro_asset", duration_ms=_ms(5))

        with pytest.raises(AssemblyFault):
            assemble_program(
                prog, pool, grid_minutes=GRID_MINUTES,
                outro_asset=outro_asset,
            )

    def test_intro_outro_included_in_bleed_calc(self):
        # INV-PROGRAM-INTRO-OUTRO-001 — bleed=true: intro + content + outro
        # durations all count toward total_runtime_ms.
        prog = _make_program(
            fill_mode="single", grid_blocks=2, bleed=True,
            intro="intro_asset", outro="outro_asset",
        )
        pool = _make_pool(55, name="movies")
        intro_asset = FakeAsset(asset_id="intro_asset", duration_ms=_ms(3))
        outro_asset = FakeAsset(asset_id="outro_asset", duration_ms=_ms(4))

        result = assemble_program(
            prog, pool, grid_minutes=GRID_MINUTES,
            intro_asset=intro_asset,
            outro_asset=outro_asset,
        )

        # 3 + 55 + 4 = 62min total
        assert result.total_runtime_ms == _ms(62)


# ===========================================================================
# INV-PROGRAM-ASSEMBLY-ELIGIBLE-001
# Assembly must only select eligible assets
# ===========================================================================


@pytest.mark.contract
class TestInvProgramAssemblyEligible001:
    """INV-PROGRAM-ASSEMBLY-ELIGIBLE-001"""

    def test_assembly_rejects_ineligible_asset(self):
        # INV-PROGRAM-ASSEMBLY-ELIGIBLE-001 — asset with state != ready excluded
        prog = _make_program(fill_mode="single", grid_blocks=2, bleed=True)
        pool = FakePool(
            name="movies",
            assets=[
                FakeAsset(
                    asset_id="not-ready", duration_ms=_ms(50), state="enriching",
                ),
            ],
        )

        with pytest.raises(AssemblyFault):
            assemble_program(prog, pool, grid_minutes=GRID_MINUTES)

    def test_assembly_rejects_unapproved_asset(self):
        # INV-PROGRAM-ASSEMBLY-ELIGIBLE-001 — asset with approved=false excluded
        prog = _make_program(fill_mode="single", grid_blocks=2, bleed=True)
        pool = FakePool(
            name="movies",
            assets=[
                FakeAsset(
                    asset_id="unapproved", duration_ms=_ms(50),
                    approved_for_broadcast=False,
                ),
            ],
        )

        with pytest.raises(AssemblyFault):
            assemble_program(prog, pool, grid_minutes=GRID_MINUTES)

    def test_ineligible_intro_rejected(self):
        # INV-PROGRAM-ASSEMBLY-ELIGIBLE-001 — ineligible intro asset → fault
        prog = _make_program(
            fill_mode="single", grid_blocks=2, bleed=True,
            intro="bad_intro",
        )
        pool = _make_pool(50, name="movies")
        intro_asset = FakeAsset(
            asset_id="bad_intro", duration_ms=_ms(3),
            state="enriching", approved_for_broadcast=False,
        )

        with pytest.raises(AssemblyFault):
            assemble_program(
                prog, pool, grid_minutes=GRID_MINUTES,
                intro_asset=intro_asset,
            )


# ===========================================================================
# INV-PROGRAM-SEPARATION-001
# Schedule blocks must not embed assembly logic
# ===========================================================================


@pytest.mark.contract
class TestInvProgramSeparation001:
    """INV-PROGRAM-SEPARATION-001"""

    def test_schedule_block_must_reference_program(self):
        # INV-PROGRAM-SEPARATION-001 — schedule block with no program → reject
        block = FakeScheduleBlock(start="20:00", slots=4, program="")

        with pytest.raises(ValidationFault):
            validate_schedule_block(block, program=None, grid_minutes=GRID_MINUTES)

    def test_schedule_block_rejects_inline_fill_mode(self):
        # INV-PROGRAM-SEPARATION-001 — schedule block with inline fill_mode → reject
        prog = _make_program()
        block = FakeScheduleBlock(
            start="20:00", slots=4, program=prog.name, fill_mode="single",
        )

        with pytest.raises(ValidationFault):
            validate_schedule_block(block, prog, grid_minutes=GRID_MINUTES)

    def test_schedule_block_rejects_inline_bleed(self):
        # INV-PROGRAM-SEPARATION-001 — schedule block with inline bleed → reject
        prog = _make_program()
        block = FakeScheduleBlock(
            start="20:00", slots=4, program=prog.name, bleed=True,
        )

        with pytest.raises(ValidationFault):
            validate_schedule_block(block, prog, grid_minutes=GRID_MINUTES)
