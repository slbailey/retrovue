"""Contract tests for the Program Presentation Stack.

Validates all invariants defined in:
    docs/contracts/program_presentation.md

Derived from: LAW-CONTENT-AUTHORITY, LAW-GRID, LAW-ELIGIBILITY, LAW-DERIVATION.

These tests enforce the contract outcomes for presentation segments — the
ordered stack of 0..n non-primary segments (rating cards, feature-presentation
bumpers, studio logos) that precede the primary content segment in an assembled
program block.

Tests are written against the public assembly, break-detection, and traffic-
manager interfaces.  They are expected to fail until the presentation stack
implementation is provided.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from retrovue.runtime.program_definition import (
    AssemblyFault,
    AssemblyResult,
    AssemblySegment,
    ProgramDefinition,
    assemble_program,
)
from retrovue.runtime.break_detection import detect_breaks
from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment
from retrovue.runtime.traffic_manager import fill_ad_blocks


# ---------------------------------------------------------------------------
# Deterministic test fixtures
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
            a for a in self.assets
            if a.state == "ready" and a.approved_for_broadcast
        ]


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
    intro: str | None = None,
    outro: str | None = None,
    presentation: list[str] | None = None,
) -> ProgramDefinition:
    return ProgramDefinition(
        name=name,
        pool=pool,
        grid_blocks=grid_blocks,
        fill_mode=fill_mode,
        intro=intro,
        outro=outro,
        presentation=presentation,
    )


def _build_scheduled_block_from_assembly(
    result: AssemblyResult,
    *,
    start_utc_ms: int = 0,
    slot_duration_ms: int | None = None,
) -> ScheduledBlock:
    """Convert an AssemblyResult into a ScheduledBlock for downstream tests.

    Mirrors the schedule compiler's segment serialization path. Presentation
    segments are asset-backed; filler placeholder appended for remaining time.
    """
    if slot_duration_ms is None:
        slot_duration_ms = _ms(GRID_MINUTES * 2)  # 2 grid blocks

    segments: list[ScheduledSegment] = []
    for seg in result.segments:
        is_primary = seg.segment_type == "content"
        segments.append(ScheduledSegment(
            segment_type=seg.segment_type,
            asset_uri=f"/media/{seg.asset_id}.ts" if seg.asset_id else "",
            asset_start_offset_ms=0,
            segment_duration_ms=seg.duration_ms,
            is_primary=is_primary,
        ))

    # Append filler placeholder for remaining slot time
    content_total_ms = sum(s.segment_duration_ms for s in segments)
    remaining_ms = slot_duration_ms - content_total_ms
    if remaining_ms > 0:
        segments.append(ScheduledSegment(
            segment_type="filler",
            asset_uri="",
            asset_start_offset_ms=0,
            segment_duration_ms=remaining_ms,
        ))

    return ScheduledBlock(
        block_id="blk-test-001",
        start_utc_ms=start_utc_ms,
        end_utc_ms=start_utc_ms + slot_duration_ms,
        segments=tuple(segments),
    )


# ===========================================================================
# INV-PRESENTATION-SINGLE-PRIMARY-001
# Exactly one primary content segment per assembled program block.
# Presentation segments are always non-primary.
# ===========================================================================


@pytest.mark.contract
class TestInvPresentationSinglePrimary001:
    """INV-PRESENTATION-SINGLE-PRIMARY-001"""

    # Tier: 2 | Scheduling logic invariant
    def test_zero_presentation_segments(self):
        # INV-PRESENTATION-SINGLE-PRIMARY-001 — empty presentation stack
        # produces exactly one content segment; no presentation segments.
        prog = _make_program(
            fill_mode="single", grid_blocks=2,
            presentation=[],
        )
        pool = _make_pool(50, name="movies")

        result = assemble_program(prog, pool, grid_minutes=GRID_MINUTES, bleed=True)

        content_segments = [s for s in result.segments if s.segment_type == "content"]
        presentation_segments = [s for s in result.segments if s.segment_type == "presentation"]
        assert len(content_segments) == 1
        assert len(presentation_segments) == 0

    # Tier: 2 | Scheduling logic invariant
    def test_presentation_segments_are_never_primary(self):
        # INV-PRESENTATION-SINGLE-PRIMARY-001 — presentation segments have
        # segment_type="presentation", never "content"; only one content
        # segment exists.
        prog = _make_program(
            fill_mode="single", grid_blocks=2,
            presentation=["rating_card", "feature_bumper"],
        )
        pool = _make_pool(50, name="movies")
        rating = FakeAsset(asset_id="rating_card", duration_ms=_ms(1))
        bumper = FakeAsset(asset_id="feature_bumper", duration_ms=_ms(1))

        result = assemble_program(
            prog, pool, grid_minutes=GRID_MINUTES,
            bleed=True,
            presentation_assets=[rating, bumper],
        )

        content_segments = [s for s in result.segments if s.segment_type == "content"]
        presentation_segments = [s for s in result.segments if s.segment_type == "presentation"]
        assert len(content_segments) == 1, "Exactly one primary content segment"
        assert len(presentation_segments) == 2, "Two presentation segments"

    # Tier: 2 | Scheduling logic invariant
    def test_scheduled_block_exactly_one_primary(self):
        # INV-PRESENTATION-SINGLE-PRIMARY-001 — when converted to a
        # ScheduledBlock, exactly one segment has is_primary=True.
        prog = _make_program(
            fill_mode="single", grid_blocks=2,
            presentation=["rating_card", "studio_logo"],
        )
        pool = _make_pool(50, name="movies")
        rating = FakeAsset(asset_id="rating_card", duration_ms=_ms(1))
        logo = FakeAsset(asset_id="studio_logo", duration_ms=_ms(1))

        result = assemble_program(
            prog, pool, grid_minutes=GRID_MINUTES,
            bleed=True,
            presentation_assets=[rating, logo],
        )

        block = _build_scheduled_block_from_assembly(result)
        primary_segments = [s for s in block.segments if s.is_primary]
        assert len(primary_segments) == 1, "Exactly one is_primary=True segment"

        # Presentation segments must not be primary
        for seg in block.segments:
            if seg.segment_type == "presentation":
                assert not seg.is_primary, (
                    f"Presentation segment must not be primary: {seg.asset_uri}"
                )


# ===========================================================================
# INV-PRESENTATION-PRECEDES-PRIMARY-001
# Presentation segments appear in declared order before primary content.
# ===========================================================================


@pytest.mark.contract
class TestInvPresentationPrecedesPrimary001:
    """INV-PRESENTATION-PRECEDES-PRIMARY-001"""

    # Tier: 2 | Scheduling logic invariant
    def test_single_presentation_before_primary(self):
        # INV-PRESENTATION-PRECEDES-PRIMARY-001 — single presentation segment
        # appears at index 0; content follows at index 1.
        prog = _make_program(
            fill_mode="single", grid_blocks=2,
            presentation=["hbo_intro"],
        )
        pool = _make_pool(50, name="movies")
        hbo = FakeAsset(asset_id="hbo_intro", duration_ms=_ms(1))

        result = assemble_program(
            prog, pool, grid_minutes=GRID_MINUTES,
            bleed=True,
            presentation_assets=[hbo],
        )

        assert result.segments[0].segment_type == "presentation"
        assert result.segments[0].asset_id == "hbo_intro"
        assert result.segments[1].segment_type == "content"

    # Tier: 2 | Scheduling logic invariant
    def test_multiple_presentation_segments_declared_order(self):
        # INV-PRESENTATION-PRECEDES-PRIMARY-001 — three presentation segments
        # appear in exact declared order [rating, feature, logo] before content.
        prog = _make_program(
            fill_mode="single", grid_blocks=2,
            presentation=["rating_card", "feature_bumper", "studio_logo"],
        )
        pool = _make_pool(50, name="movies")
        assets = [
            FakeAsset(asset_id="rating_card", duration_ms=5_000),
            FakeAsset(asset_id="feature_bumper", duration_ms=15_000),
            FakeAsset(asset_id="studio_logo", duration_ms=10_000),
        ]

        result = assemble_program(
            prog, pool, grid_minutes=GRID_MINUTES,
            bleed=True,
            presentation_assets=assets,
        )

        types = [s.segment_type for s in result.segments]
        ids = [s.asset_id for s in result.segments]

        # First three segments are presentation, in declared order
        assert types[:3] == ["presentation", "presentation", "presentation"]
        assert ids[:3] == ["rating_card", "feature_bumper", "studio_logo"]
        # Fourth segment is content
        assert types[3] == "content"

    # Tier: 2 | Scheduling logic invariant
    def test_no_non_presentation_between_stack_and_content(self):
        # INV-PRESENTATION-PRECEDES-PRIMARY-001 — no filler, pad, or content
        # segment may appear between presentation segments and the primary.
        prog = _make_program(
            fill_mode="single", grid_blocks=2,
            presentation=["bumper_a", "bumper_b"],
        )
        pool = _make_pool(50, name="movies")
        assets = [
            FakeAsset(asset_id="bumper_a", duration_ms=5_000),
            FakeAsset(asset_id="bumper_b", duration_ms=5_000),
        ]

        result = assemble_program(
            prog, pool, grid_minutes=GRID_MINUTES,
            bleed=True,
            presentation_assets=assets,
        )

        # Walk segments: after we see the first presentation segment, all
        # subsequent segments until the first content must be presentation.
        saw_presentation = False
        for seg in result.segments:
            if seg.segment_type == "presentation":
                saw_presentation = True
            elif saw_presentation:
                # First non-presentation after the stack must be content.
                assert seg.segment_type == "content", (
                    f"Expected 'content' after presentation stack, "
                    f"got '{seg.segment_type}'"
                )
                break


# ===========================================================================
# INV-PRESENTATION-FIRST-CONTENT-IDENTITY-001
# Editorial identity resolution uses the first content segment.
# ===========================================================================


@pytest.mark.contract
class TestInvPresentationFirstContentIdentity001:
    """INV-PRESENTATION-FIRST-CONTENT-IDENTITY-001"""

    # Tier: 2 | Scheduling logic invariant
    def test_identity_from_content_not_presentation(self):
        # INV-PRESENTATION-FIRST-CONTENT-IDENTITY-001 — editorial identity
        # must come from the first segment_type="content", not from
        # presentation segments.
        prog = _make_program(
            fill_mode="single", grid_blocks=2,
            presentation=["rating_card", "feature_bumper"],
        )
        pool = _make_pool(50, name="movies")
        assets = [
            FakeAsset(asset_id="rating_card", duration_ms=5_000),
            FakeAsset(asset_id="feature_bumper", duration_ms=15_000),
        ]

        result = assemble_program(
            prog, pool, grid_minutes=GRID_MINUTES,
            bleed=True,
            presentation_assets=assets,
        )

        # Simulate schedule compiler identity extraction:
        # "Primary content asset is the first 'content' segment"
        content_segments = [
            s for s in result.segments if s.segment_type == "content"
        ]
        assert len(content_segments) >= 1, "Must have at least one content segment"
        primary_id = content_segments[0].asset_id

        # Identity must be the pool asset, not a presentation asset
        assert primary_id == "asset-0", (
            f"Expected editorial identity 'asset-0' from content segment, "
            f"got '{primary_id}'"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_primary_is_first_content_type(self):
        # INV-PRESENTATION-FIRST-CONTENT-IDENTITY-001 — the primary content
        # segment must be the first segment with segment_type="content".
        # No presentation segment may have segment_type="content".
        prog = _make_program(
            fill_mode="single", grid_blocks=2,
            presentation=["logo"],
        )
        pool = _make_pool(50, name="movies")
        logo = FakeAsset(asset_id="logo", duration_ms=10_000)

        result = assemble_program(
            prog, pool, grid_minutes=GRID_MINUTES,
            bleed=True,
            presentation_assets=[logo],
        )

        # No presentation segment should have segment_type="content"
        for seg in result.segments:
            if seg.asset_id == "logo":
                assert seg.segment_type == "presentation", (
                    f"Presentation asset 'logo' has wrong segment_type: "
                    f"'{seg.segment_type}'"
                )

        # First content segment is the pool asset
        content_segments = [
            s for s in result.segments if s.segment_type == "content"
        ]
        assert content_segments[0].asset_id == "asset-0"


# ===========================================================================
# INV-PRESENTATION-GRID-BUDGET-001
# Presentation durations deducted from grid budget.
# ===========================================================================


@pytest.mark.contract
class TestInvPresentationGridBudget001:
    """INV-PRESENTATION-GRID-BUDGET-001"""

    # Tier: 2 | Scheduling logic invariant
    def test_presentation_reduces_grid_budget(self):
        # INV-PRESENTATION-GRID-BUDGET-001 — a 5-minute presentation segment
        # in a 60-minute grid leaves only 55 minutes for content.
        # A 58-minute asset must be rejected (5 + 58 = 63 > 60).
        prog = _make_program(
            fill_mode="single", grid_blocks=2,
            presentation=["feature_bumper"],
        )
        pool = _make_pool(58, name="movies")
        bumper = FakeAsset(asset_id="feature_bumper", duration_ms=_ms(5))

        with pytest.raises(AssemblyFault):
            assemble_program(
                prog, pool, grid_minutes=GRID_MINUTES,
                presentation_assets=[bumper],
            )

    # Tier: 2 | Scheduling logic invariant
    def test_content_accepted_within_remaining_budget(self):
        # INV-PRESENTATION-GRID-BUDGET-001 — a 5-minute presentation segment
        # in a 60-minute grid allows a 54-minute asset (5 + 54 = 59 <= 60).
        prog = _make_program(
            fill_mode="single", grid_blocks=2,
            presentation=["feature_bumper"],
        )
        pool = _make_pool(54, name="movies")
        bumper = FakeAsset(asset_id="feature_bumper", duration_ms=_ms(5))

        result = assemble_program(
            prog, pool, grid_minutes=GRID_MINUTES,
            presentation_assets=[bumper],
        )

        # Total runtime = 5min presentation + 54min content = 59min
        assert result.total_runtime_ms == _ms(59)

    # Tier: 2 | Scheduling logic invariant
    def test_multiple_presentation_segments_budget_sum(self):
        # INV-PRESENTATION-GRID-BUDGET-001 — multiple presentation segments:
        # 3min + 2min = 5min overhead. 56-minute asset rejected (5+56=61 > 60).
        prog = _make_program(
            fill_mode="single", grid_blocks=2,
            presentation=["rating_card", "studio_logo"],
        )
        pool = _make_pool(56, name="movies")
        assets = [
            FakeAsset(asset_id="rating_card", duration_ms=_ms(3)),
            FakeAsset(asset_id="studio_logo", duration_ms=_ms(2)),
        ]

        with pytest.raises(AssemblyFault):
            assemble_program(
                prog, pool, grid_minutes=GRID_MINUTES,
                presentation_assets=assets,
            )


# ===========================================================================
# INV-PRESENTATION-NOT-FILLER-001
# Presentation segments are asset-backed, never filler placeholders.
# ===========================================================================


@pytest.mark.contract
class TestInvPresentationNotFiller001:
    """INV-PRESENTATION-NOT-FILLER-001"""

    # Tier: 2 | Scheduling logic invariant
    def test_presentation_does_not_trigger_filler_before_primary(self):
        # INV-PRESENTATION-NOT-FILLER-001 — presentation segments before a
        # primary content segment must not trigger the
        # _assert_no_filler_before_primary guard.
        presentation_seg = ScheduledSegment(
            segment_type="presentation",
            asset_uri="/media/hbo_intro.ts",
            asset_start_offset_ms=0,
            segment_duration_ms=15_000,
            is_primary=False,
        )
        content_seg = ScheduledSegment(
            segment_type="content",
            asset_uri="/media/movie.ts",
            asset_start_offset_ms=0,
            segment_duration_ms=_ms(50),
            is_primary=True,
        )
        filler_seg = ScheduledSegment(
            segment_type="filler",
            asset_uri="",
            asset_start_offset_ms=0,
            segment_duration_ms=_ms(9),
        )

        block = ScheduledBlock(
            block_id="blk-pres-001",
            start_utc_ms=0,
            end_utc_ms=_ms(60),
            segments=(presentation_seg, content_seg, filler_seg),
        )

        # Must not raise ValueError from _assert_no_filler_before_primary.
        # The presentation segment is not segment_type="filler" with
        # asset_uri="" — it is asset-backed.
        result = fill_ad_blocks(
            block,
            filler_uri="/media/filler.ts",
            filler_duration_ms=30_000,
        )
        assert result is not None

    # Tier: 2 | Scheduling logic invariant
    def test_presentation_segments_are_asset_backed(self):
        # INV-PRESENTATION-NOT-FILLER-001 — every presentation segment
        # has a non-empty asset_uri and segment_type="presentation".
        prog = _make_program(
            fill_mode="single", grid_blocks=2,
            presentation=["rating_card", "feature_bumper"],
        )
        pool = _make_pool(50, name="movies")
        assets = [
            FakeAsset(asset_id="rating_card", duration_ms=5_000),
            FakeAsset(asset_id="feature_bumper", duration_ms=15_000),
        ]

        result = assemble_program(
            prog, pool, grid_minutes=GRID_MINUTES,
            bleed=True,
            presentation_assets=assets,
        )

        for seg in result.segments:
            if seg.segment_type == "presentation":
                assert seg.asset_id, (
                    f"Presentation segment must have a non-empty asset_id"
                )
                assert seg.duration_ms > 0, (
                    f"Presentation segment must have positive duration"
                )

    # Tier: 2 | Scheduling logic invariant
    def test_multiple_presentation_before_primary_no_crash(self):
        # INV-PRESENTATION-NOT-FILLER-001 — multiple presentation segments
        # before a primary segment pass through fill_ad_blocks without error.
        segs = [
            ScheduledSegment(
                segment_type="presentation",
                asset_uri="/media/rating_card.ts",
                asset_start_offset_ms=0,
                segment_duration_ms=5_000,
                is_primary=False,
            ),
            ScheduledSegment(
                segment_type="presentation",
                asset_uri="/media/feature_bumper.ts",
                asset_start_offset_ms=0,
                segment_duration_ms=15_000,
                is_primary=False,
            ),
            ScheduledSegment(
                segment_type="content",
                asset_uri="/media/movie.ts",
                asset_start_offset_ms=0,
                segment_duration_ms=_ms(50),
                is_primary=True,
            ),
            ScheduledSegment(
                segment_type="filler",
                asset_uri="",
                asset_start_offset_ms=0,
                segment_duration_ms=_ms(60) - _ms(50) - 20_000,
            ),
        ]

        block = ScheduledBlock(
            block_id="blk-pres-002",
            start_utc_ms=0,
            end_utc_ms=_ms(60),
            segments=tuple(segs),
        )

        result = fill_ad_blocks(
            block,
            filler_uri="/media/filler.ts",
            filler_duration_ms=30_000,
        )
        assert result is not None


# ===========================================================================
# INV-PRESENTATION-BREAK-INVISIBLE-001
# Break detection ignores presentation-to-content boundaries.
# ===========================================================================


@pytest.mark.contract
class TestInvPresentationBreakInvisible001:
    """INV-PRESENTATION-BREAK-INVISIBLE-001"""

    # Tier: 2 | Scheduling logic invariant
    def test_no_break_at_presentation_to_content_boundary(self):
        # INV-PRESENTATION-BREAK-INVISIBLE-001 — break detection must not
        # produce an opportunity at the presentation-to-content boundary.
        # Presentation segments use segment_type="presentation", which is
        # not "content" — boundary seam detection only fires between
        # consecutive "content" segments.
        result = AssemblyResult(
            segments=[
                AssemblySegment(
                    asset_id="feature_bumper",
                    duration_ms=15_000,
                    segment_type="presentation",
                ),
                AssemblySegment(
                    asset_id="movie",
                    duration_ms=_ms(50),
                    segment_type="content",
                ),
            ],
            total_runtime_ms=15_000 + _ms(50),
        )

        plan = detect_breaks(
            assembly_result=result,
            grid_duration_ms=_ms(60),
        )

        # No boundary opportunity should exist at the presentation-to-content
        # seam (15_000 ms). Only chapter or algorithmic breaks may appear
        # within the content segment.
        boundary_opps = [
            o for o in plan.opportunities if o.source == "boundary"
        ]
        assert len(boundary_opps) == 0, (
            f"Expected no boundary break opportunities, got {boundary_opps}"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_presentation_invisible_but_content_breaks_preserved(self):
        # INV-PRESENTATION-BREAK-INVISIBLE-001 — presentation segments are
        # invisible to break detection, but content-to-content boundaries
        # (accumulate mode) still produce opportunities.
        result = AssemblyResult(
            segments=[
                AssemblySegment(
                    asset_id="feature_bumper",
                    duration_ms=15_000,
                    segment_type="presentation",
                ),
                AssemblySegment(
                    asset_id="episode_1",
                    duration_ms=_ms(22),
                    segment_type="content",
                ),
                AssemblySegment(
                    asset_id="episode_2",
                    duration_ms=_ms(22),
                    segment_type="content",
                ),
            ],
            total_runtime_ms=15_000 + _ms(44),
        )

        plan = detect_breaks(
            assembly_result=result,
            grid_duration_ms=_ms(60),
        )

        # The content-to-content boundary (episode_1 → episode_2) should
        # produce a boundary break. The presentation-to-content boundary
        # should produce none.
        boundary_opps = [
            o for o in plan.opportunities if o.source == "boundary"
        ]
        assert len(boundary_opps) == 1, (
            f"Expected exactly 1 content-to-content boundary break, "
            f"got {len(boundary_opps)}"
        )
        # Boundary position: after presentation (15s) + episode_1 (22min)
        expected_pos = 15_000 + _ms(22)
        assert boundary_opps[0].position_ms == expected_pos


# ===========================================================================
# Mutual exclusion: presentation and intro cannot coexist
# ===========================================================================


@pytest.mark.contract
class TestPresentationIntroMutualExclusion:
    """INV-PRESENTATION-PRECEDES-PRIMARY-001 — mutual exclusion with intro"""

    # Tier: 2 | Scheduling logic invariant
    def test_presentation_and_intro_rejected(self):
        # A ProgramDefinition MUST NOT declare both `presentation` and `intro`.
        # Construction or validation must reject this combination.
        with pytest.raises((ValueError, AssemblyFault)):
            _make_program(
                fill_mode="single",
                grid_blocks=2,
                intro="legacy_intro",
                presentation=["rating_card", "feature_bumper"],
            )
