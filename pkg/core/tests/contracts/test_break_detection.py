"""Contract tests for Break Detection.

Validates all invariants defined in:
    docs/contracts/break_detection.md

Derived from: LAW-CONTENT-AUTHORITY, LAW-GRID, LAW-DERIVATION.

These tests call interfaces that do not yet exist (detect_breaks,
BreakOpportunity, BreakPlan). They are expected to fail with
ImportError until the implementation is provided.
"""

from __future__ import annotations

import inspect
import math
from dataclasses import dataclass, field

import pytest

from retrovue.runtime.break_detection import (
    BreakOpportunity,
    BreakPlan,
    detect_breaks,
)


# ---------------------------------------------------------------------------
# Fake helpers — no database, no real domain objects
# ---------------------------------------------------------------------------

GRID_30_MIN_MS = 30 * 60 * 1000   # 1_800_000
GRID_60_MIN_MS = 60 * 60 * 1000   # 3_600_000
GRID_120_MIN_MS = 120 * 60 * 1000  # 7_200_000


@dataclass
class FakeAssemblySegment:
    """Minimal segment for break detection tests."""

    asset_id: str
    duration_ms: int
    segment_type: str = "content"
    chapter_markers_ms: tuple[int, ...] | None = None


@dataclass
class FakeAssemblyResult:
    """Minimal assembly result for break detection tests."""

    segments: list[FakeAssemblySegment]
    total_runtime_ms: int = 0

    def __post_init__(self) -> None:
        if self.total_runtime_ms == 0:
            self.total_runtime_ms = sum(s.duration_ms for s in self.segments)


def _single_content(duration_ms: int, chapter_markers_ms=None) -> FakeAssemblyResult:
    """Single content segment, no intro/outro."""
    return FakeAssemblyResult(segments=[
        FakeAssemblySegment(
            asset_id="ep-001",
            duration_ms=duration_ms,
            chapter_markers_ms=chapter_markers_ms,
        ),
    ])


def _accumulate_content(*durations_ms: int) -> FakeAssemblyResult:
    """Multiple content segments simulating accumulate mode."""
    return FakeAssemblyResult(segments=[
        FakeAssemblySegment(
            asset_id=f"ep-{i:03d}",
            duration_ms=d,
        )
        for i, d in enumerate(durations_ms)
    ])


def _with_intro_outro(
    intro_ms: int,
    content_ms: int,
    outro_ms: int,
    chapter_markers_ms=None,
) -> FakeAssemblyResult:
    """Content sandwiched between intro and outro segments."""
    return FakeAssemblyResult(segments=[
        FakeAssemblySegment(
            asset_id="intro-asset",
            duration_ms=intro_ms,
            segment_type="intro",
        ),
        FakeAssemblySegment(
            asset_id="ep-001",
            duration_ms=content_ms,
            segment_type="content",
            chapter_markers_ms=chapter_markers_ms,
        ),
        FakeAssemblySegment(
            asset_id="outro-asset",
            duration_ms=outro_ms,
            segment_type="outro",
        ),
    ])


# ===========================================================================
# INV-BREAK-001
# Break detection must consume assembled program output
# ===========================================================================


@pytest.mark.contract
class TestInvBreak001:
    """INV-BREAK-001"""

    # Tier: 2 | Scheduling logic invariant
    def test_detect_breaks_from_assembly_result(self):
        # INV-BREAK-001 — detect_breaks accepts an AssemblyResult and returns a BreakPlan
        assembly = _single_content(duration_ms=1_320_000)  # 22 minutes
        grid_ms = GRID_30_MIN_MS

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=grid_ms)

        assert isinstance(plan, BreakPlan)
        assert plan.program_runtime_ms == 1_320_000
        assert plan.grid_duration_ms == grid_ms

    # Tier: 2 | Scheduling logic invariant
    def test_rejects_raw_asset_duration(self):
        # INV-BREAK-001 — detect_breaks signature requires assembly_result, not raw duration
        sig = inspect.signature(detect_breaks)
        param_names = list(sig.parameters.keys())

        assert "assembly_result" in param_names
        assert "asset_duration_ms" not in param_names
        assert "episode_duration_ms" not in param_names
        assert "asset_id" not in param_names


# ===========================================================================
# INV-BREAK-002
# Break priority order must be chapter > boundary > algorithmic
# ===========================================================================


@pytest.mark.contract
class TestInvBreak002:
    """INV-BREAK-002"""

    # Tier: 2 | Scheduling logic invariant
    def test_chapter_markers_emit_chapter_breaks(self):
        # INV-BREAK-002 — 3 chapter markers → 3 chapter-source opportunities
        assembly = _single_content(
            duration_ms=1_320_000,  # 22 min
            chapter_markers_ms=(360_000, 720_000, 1_080_000),  # 6, 12, 18 min
        )

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=GRID_30_MIN_MS)

        chapter_opps = [o for o in plan.opportunities if o.source == "chapter"]
        assert len(chapter_opps) == 3
        assert chapter_opps[0].position_ms == 360_000
        assert chapter_opps[1].position_ms == 720_000
        assert chapter_opps[2].position_ms == 1_080_000

    # Tier: 2 | Scheduling logic invariant
    def test_boundary_breaks_coexist_with_chapter_breaks(self):
        # INV-BREAK-002 — accumulate program with chapters on one segment
        # produces both chapter and boundary opportunities
        seg_a = FakeAssemblySegment(
            asset_id="ep-001",
            duration_ms=600_000,  # 10 min, with chapter at 5 min
            chapter_markers_ms=(300_000,),
        )
        seg_b = FakeAssemblySegment(
            asset_id="ep-002",
            duration_ms=600_000,  # 10 min, no markers
        )
        assembly = FakeAssemblyResult(segments=[seg_a, seg_b])

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=GRID_30_MIN_MS)

        sources = {o.source for o in plan.opportunities}
        assert "chapter" in sources, "Chapter markers must be emitted"
        assert "boundary" in sources, "Asset boundaries must be emitted"

        # Chapter at 300_000ms (within seg_a)
        chapter_opps = [o for o in plan.opportunities if o.source == "chapter"]
        assert any(o.position_ms == 300_000 for o in chapter_opps)

        # Boundary at 600_000ms (seam between seg_a and seg_b)
        boundary_opps = [o for o in plan.opportunities if o.source == "boundary"]
        assert any(o.position_ms == 600_000 for o in boundary_opps)

    # Tier: 2 | Scheduling logic invariant
    def test_algorithmic_does_not_override_chapter(self):
        # INV-BREAK-002 — when chapter markers present on single content segment,
        # no algorithmic break at the same position
        assembly = _single_content(
            duration_ms=1_320_000,
            chapter_markers_ms=(360_000, 720_000, 1_080_000),
        )

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=GRID_30_MIN_MS)

        chapter_positions = {o.position_ms for o in plan.opportunities if o.source == "chapter"}
        algo_positions = {o.position_ms for o in plan.opportunities if o.source == "algorithmic"}

        # No algorithmic break may occupy a chapter position
        assert chapter_positions.isdisjoint(algo_positions), (
            f"Algorithmic breaks overlap chapter positions: "
            f"{chapter_positions & algo_positions}"
        )


# ===========================================================================
# INV-BREAK-003
# Algorithmic breaks must not fall in protected zone
# ===========================================================================


@pytest.mark.contract
class TestInvBreak003:
    """INV-BREAK-003"""

    # Tier: 2 | Scheduling logic invariant
    def test_algorithmic_not_in_protected_zone(self):
        # INV-BREAK-003 — all algorithmic breaks >= 20% of runtime
        assembly = _single_content(duration_ms=1_320_000)  # 22 min
        protected_end = math.floor(1_320_000 * 0.20)  # 264_000ms

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=GRID_30_MIN_MS)

        algo_opps = [o for o in plan.opportunities if o.source == "algorithmic"]
        for opp in algo_opps:
            assert opp.position_ms >= protected_end, (
                f"INV-BREAK-003: algorithmic break at {opp.position_ms}ms "
                f"falls within protected zone (ends at {protected_end}ms)"
            )

    # Tier: 2 | Scheduling logic invariant
    def test_chapter_breaks_allowed_in_protected_zone(self):
        # INV-BREAK-003 — chapter marker at 5% of runtime is emitted;
        # protected zone does not apply to chapter-source breaks
        runtime_ms = 1_320_000  # 22 min
        early_marker = math.floor(runtime_ms * 0.05)  # ~66_000ms
        assembly = _single_content(
            duration_ms=runtime_ms,
            chapter_markers_ms=(early_marker, 720_000),
        )

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=GRID_30_MIN_MS)

        chapter_opps = [o for o in plan.opportunities if o.source == "chapter"]
        assert any(o.position_ms == early_marker for o in chapter_opps), (
            f"Chapter marker at {early_marker}ms must be emitted "
            f"regardless of protected zone"
        )


# ===========================================================================
# INV-BREAK-004
# Accumulate boundaries must be emitted as break opportunities
# ===========================================================================


@pytest.mark.contract
class TestInvBreak004:
    """INV-BREAK-004"""

    # Tier: 2 | Scheduling logic invariant
    def test_accumulate_boundaries_emitted(self):
        # INV-BREAK-004 — 3 content segments → exactly 2 boundary opportunities
        assembly = _accumulate_content(400_000, 400_000, 400_000)  # 3 × ~6.7 min

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=GRID_30_MIN_MS)

        boundary_opps = [o for o in plan.opportunities if o.source == "boundary"]
        assert len(boundary_opps) == 2

        # Seams at 400_000 and 800_000
        positions = sorted(o.position_ms for o in boundary_opps)
        assert positions == [400_000, 800_000]

    # Tier: 2 | Scheduling logic invariant
    def test_single_segment_no_boundary_breaks(self):
        # INV-BREAK-004 — single content segment → 0 boundary opportunities
        assembly = _single_content(duration_ms=1_320_000)

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=GRID_30_MIN_MS)

        boundary_opps = [o for o in plan.opportunities if o.source == "boundary"]
        assert len(boundary_opps) == 0

    # Tier: 2 | Scheduling logic invariant
    def test_five_segments_four_boundaries(self):
        # INV-BREAK-004 — 5 content segments → exactly 4 boundary opportunities
        assembly = _accumulate_content(300_000, 300_000, 300_000, 300_000, 300_000)

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=GRID_30_MIN_MS)

        boundary_opps = [o for o in plan.opportunities if o.source == "boundary"]
        assert len(boundary_opps) == 4

        positions = sorted(o.position_ms for o in boundary_opps)
        assert positions == [300_000, 600_000, 900_000, 1_200_000]


# ===========================================================================
# INV-BREAK-005
# Break budget must be derived from assembled runtime
# ===========================================================================


@pytest.mark.contract
class TestInvBreak005:
    """INV-BREAK-005"""

    # Tier: 2 | Scheduling logic invariant
    def test_budget_from_assembled_runtime(self):
        # INV-BREAK-005 — budget = grid_duration - total_runtime,
        # including intro + outro in runtime
        assembly = _with_intro_outro(
            intro_ms=15_000,        # 15s intro
            content_ms=1_260_000,   # 21 min content
            outro_ms=15_000,        # 15s outro
        )
        # total = 15_000 + 1_260_000 + 15_000 = 1_290_000 (21.5 min)
        assert assembly.total_runtime_ms == 1_290_000

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=GRID_30_MIN_MS)

        expected_budget = GRID_30_MIN_MS - 1_290_000  # 510_000ms
        assert plan.break_budget_ms == expected_budget
        assert plan.program_runtime_ms == 1_290_000

    # Tier: 2 | Scheduling logic invariant
    def test_budget_not_from_single_asset(self):
        # INV-BREAK-005 — accumulate program: budget uses sum of all segments,
        # not just the first segment's duration
        assembly = _accumulate_content(600_000, 600_000)  # 10 + 10 = 20 min
        assert assembly.total_runtime_ms == 1_200_000

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=GRID_30_MIN_MS)

        # Budget from total (20 min), not from first segment (10 min)
        expected_budget = GRID_30_MIN_MS - 1_200_000  # 600_000ms
        assert plan.break_budget_ms == expected_budget


# ===========================================================================
# INV-BREAK-006
# Traffic fill must consume break plan, not invent break points
# ===========================================================================


@pytest.mark.contract
class TestInvBreak006:
    """INV-BREAK-006"""

    # Tier: 2 | Scheduling logic invariant
    def test_break_plan_is_sole_authority(self):
        # INV-BREAK-006 — BreakPlan contains all information traffic fill needs:
        # opportunities list, break_budget_ms, grid_duration_ms, program_runtime_ms.
        # No asset resolver or raw metadata access is needed.
        assembly = _single_content(
            duration_ms=1_320_000,
            chapter_markers_ms=(400_000, 800_000),
        )

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=GRID_30_MIN_MS)

        # Plan must carry all required fields
        assert hasattr(plan, "opportunities")
        assert hasattr(plan, "break_budget_ms")
        assert hasattr(plan, "program_runtime_ms")
        assert hasattr(plan, "grid_duration_ms")

        # Opportunities must carry position and weight for budget distribution
        for opp in plan.opportunities:
            assert hasattr(opp, "position_ms")
            assert hasattr(opp, "source")
            assert hasattr(opp, "weight")
            assert opp.weight > 0

    # Tier: 2 | Scheduling logic invariant
    def test_break_plan_opportunities_ordered(self):
        # INV-BREAK-006 — opportunities must be in timeline order
        assembly = _accumulate_content(400_000, 400_000, 400_000)

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=GRID_30_MIN_MS)

        positions = [o.position_ms for o in plan.opportunities]
        assert positions == sorted(positions), (
            "Break opportunities must be ordered by position_ms"
        )


# ===========================================================================
# INV-BREAK-007
# Algorithmic break spacing must be non-uniform
# ===========================================================================


@pytest.mark.contract
class TestInvBreak007:
    """INV-BREAK-007"""

    # Tier: 2 | Scheduling logic invariant
    def test_algorithmic_spacing_non_uniform(self):
        # INV-BREAK-007 — 3+ algorithmic breaks: first interval > last interval
        # Use a long single-asset program with no chapter markers to force
        # algorithmic placement.
        assembly = _single_content(duration_ms=2_400_000)  # 40 min

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=GRID_60_MIN_MS)

        algo_opps = sorted(
            [o for o in plan.opportunities if o.source == "algorithmic"],
            key=lambda o: o.position_ms,
        )
        assert len(algo_opps) >= 3, (
            "Expected at least 3 algorithmic breaks for a 40-min program in 60-min grid"
        )

        # Compute intervals between consecutive breaks
        positions = [o.position_ms for o in algo_opps]
        # First interval: from program start (or protected zone end) to first break
        intervals = []
        for i in range(1, len(positions)):
            intervals.append(positions[i] - positions[i - 1])

        # First interval must be greater than last interval (acts shorten toward end)
        assert intervals[0] > intervals[-1], (
            f"INV-BREAK-007: first interval ({intervals[0]}ms) must be > "
            f"last interval ({intervals[-1]}ms). Intervals: {intervals}"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_two_algorithmic_breaks_not_equal(self):
        # INV-BREAK-007 — 2 algorithmic breaks: intervals must differ
        assembly = _single_content(duration_ms=1_320_000)  # 22 min

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=GRID_30_MIN_MS)

        algo_opps = sorted(
            [o for o in plan.opportunities if o.source == "algorithmic"],
            key=lambda o: o.position_ms,
        )
        if len(algo_opps) >= 2:
            # Interval from first to second break vs. second to next reference point
            interval_1 = algo_opps[1].position_ms - algo_opps[0].position_ms
            interval_0 = algo_opps[0].position_ms  # from content start to first break
            assert interval_0 != interval_1, (
                "INV-BREAK-007: equal algorithmic spacing is prohibited"
            )

    # Tier: 2 | Scheduling logic invariant
    def test_weight_increases_toward_end(self):
        # INV-BREAK-007 — algorithmic break weights increase monotonically
        assembly = _single_content(duration_ms=2_400_000)  # 40 min

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=GRID_60_MIN_MS)

        algo_opps = sorted(
            [o for o in plan.opportunities if o.source == "algorithmic"],
            key=lambda o: o.position_ms,
        )
        if len(algo_opps) >= 2:
            weights = [o.weight for o in algo_opps]
            for i in range(1, len(weights)):
                assert weights[i] > weights[i - 1], (
                    f"INV-BREAK-007: weights must increase monotonically. "
                    f"weight[{i-1}]={weights[i-1]}, weight[{i}]={weights[i]}"
                )


# ===========================================================================
# INV-BREAK-008
# Break detection must be a dedicated stage
# ===========================================================================


@pytest.mark.contract
class TestInvBreak008:
    """INV-BREAK-008"""

    # Tier: 2 | Scheduling logic invariant
    def test_detect_breaks_callable_independently(self):
        # INV-BREAK-008 — detect_breaks is importable from retrovue.runtime.break_detection
        # and callable without importing playout_log_expander or traffic_manager.
        # The import at module top already proves importability.
        # Verify it is callable with the documented signature.
        assembly = _single_content(duration_ms=1_320_000)

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=GRID_30_MIN_MS)

        assert isinstance(plan, BreakPlan)

    # Tier: 2 | Scheduling logic invariant
    def test_detect_breaks_does_not_import_expander(self):
        # INV-BREAK-008 — break_detection module must not depend on playout_log_expander
        import retrovue.runtime.break_detection as bd_module
        source = inspect.getsource(bd_module)
        assert "playout_log_expander" not in source, (
            "INV-BREAK-008: break_detection must not import playout_log_expander"
        )


# ===========================================================================
# INV-BREAK-009
# No break within intro or outro segments
# ===========================================================================


@pytest.mark.contract
class TestInvBreak009:
    """INV-BREAK-009"""

    # Tier: 2 | Scheduling logic invariant
    def test_no_break_in_intro(self):
        # INV-BREAK-009 — no break opportunity falls within intro timeline range
        assembly = _with_intro_outro(
            intro_ms=30_000,        # 30s intro
            content_ms=1_260_000,   # 21 min content
            outro_ms=0,
        )
        intro_end_ms = 30_000

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=GRID_30_MIN_MS)

        for opp in plan.opportunities:
            assert opp.position_ms >= intro_end_ms, (
                f"INV-BREAK-009: break at {opp.position_ms}ms falls within "
                f"intro segment (0–{intro_end_ms}ms)"
            )

    # Tier: 2 | Scheduling logic invariant
    def test_no_break_in_outro(self):
        # INV-BREAK-009 — no break opportunity falls within outro timeline range
        assembly = _with_intro_outro(
            intro_ms=0,
            content_ms=1_260_000,   # 21 min content
            outro_ms=30_000,        # 30s outro
        )
        outro_start_ms = 1_260_000
        outro_end_ms = 1_290_000

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=GRID_30_MIN_MS)

        for opp in plan.opportunities:
            assert opp.position_ms < outro_start_ms or opp.position_ms >= outro_end_ms, (
                f"INV-BREAK-009: break at {opp.position_ms}ms falls within "
                f"outro segment ({outro_start_ms}–{outro_end_ms}ms)"
            )

    # Tier: 2 | Scheduling logic invariant
    def test_no_break_at_intro_content_seam(self):
        # INV-BREAK-009 — intro-to-content transition is NOT a boundary break
        assembly = _with_intro_outro(
            intro_ms=15_000,
            content_ms=1_260_000,
            outro_ms=15_000,
        )
        intro_end = 15_000

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=GRID_30_MIN_MS)

        boundary_opps = [o for o in plan.opportunities if o.source == "boundary"]
        boundary_positions = {o.position_ms for o in boundary_opps}
        assert intro_end not in boundary_positions, (
            "INV-BREAK-009: intro-to-content seam must not be a boundary break"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_no_break_at_content_outro_seam(self):
        # INV-BREAK-009 — content-to-outro transition is NOT a boundary break
        assembly = _with_intro_outro(
            intro_ms=15_000,
            content_ms=1_260_000,
            outro_ms=15_000,
        )
        content_end = 15_000 + 1_260_000  # 1_275_000

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=GRID_30_MIN_MS)

        boundary_opps = [o for o in plan.opportunities if o.source == "boundary"]
        boundary_positions = {o.position_ms for o in boundary_opps}
        assert content_end not in boundary_positions, (
            "INV-BREAK-009: content-to-outro seam must not be a boundary break"
        )


# ===========================================================================
# INV-BREAK-010
# Cold open must be respected
# ===========================================================================


@pytest.mark.contract
class TestInvBreak010:
    """INV-BREAK-010"""

    # Tier: 2 | Scheduling logic invariant
    def test_cold_open_respected(self):
        # INV-BREAK-010 — chapter marker at 180s; no algorithmic break before 180s
        # in that segment's contribution to the program timeline.
        assembly = _single_content(
            duration_ms=1_320_000,  # 22 min
            chapter_markers_ms=(180_000, 720_000, 1_080_000),
        )

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=GRID_30_MIN_MS)

        # The first chapter marker defines the cold-open boundary
        first_chapter = 180_000
        algo_opps = [o for o in plan.opportunities if o.source == "algorithmic"]
        for opp in algo_opps:
            assert opp.position_ms >= first_chapter, (
                f"INV-BREAK-010: algorithmic break at {opp.position_ms}ms "
                f"violates cold open (first chapter marker at {first_chapter}ms)"
            )

    # Tier: 2 | Scheduling logic invariant
    def test_cold_open_per_segment(self):
        # INV-BREAK-010 — in accumulate mode, cold open applies per segment.
        # First segment has chapter at 120s, second has no markers.
        seg_a = FakeAssemblySegment(
            asset_id="ep-001",
            duration_ms=600_000,
            chapter_markers_ms=(120_000, 400_000),
        )
        seg_b = FakeAssemblySegment(
            asset_id="ep-002",
            duration_ms=600_000,
        )
        assembly = FakeAssemblyResult(segments=[seg_a, seg_b])

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=GRID_30_MIN_MS)

        # No algorithmic break before 120_000ms (cold open of seg_a)
        algo_opps = [o for o in plan.opportunities if o.source == "algorithmic"]
        for opp in algo_opps:
            # Within seg_a's range (0–600_000), must be >= 120_000
            if opp.position_ms < 600_000:
                assert opp.position_ms >= 120_000, (
                    f"INV-BREAK-010: algorithmic break at {opp.position_ms}ms "
                    f"violates cold open in first segment (chapter at 120_000ms)"
                )


# ===========================================================================
# INV-BREAK-011
# Bleed programs produce empty break plans
# ===========================================================================


@pytest.mark.contract
class TestInvBreak011:
    """INV-BREAK-011"""

    # Tier: 2 | Scheduling logic invariant
    def test_bleed_program_empty_plan(self):
        # INV-BREAK-011 — program runtime > grid duration → empty opportunities
        assembly = _single_content(
            duration_ms=2_100_000,  # 35 min, exceeds 30-min grid
            chapter_markers_ms=(600_000, 1_200_000),
        )

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=GRID_30_MIN_MS)

        assert len(plan.opportunities) == 0
        assert plan.break_budget_ms <= 0

    # Tier: 2 | Scheduling logic invariant
    def test_zero_budget_empty_plan(self):
        # INV-BREAK-011 — program runtime == grid duration → empty opportunities
        assembly = _single_content(duration_ms=GRID_30_MIN_MS)

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=GRID_30_MIN_MS)

        assert len(plan.opportunities) == 0
        assert plan.break_budget_ms == 0

    # Tier: 2 | Scheduling logic invariant
    def test_bleed_with_markers_still_empty(self):
        # INV-BREAK-011 — even with chapter markers, bleed means no breaks
        assembly = _single_content(
            duration_ms=GRID_60_MIN_MS + 60_000,  # 61 min in 60-min grid
            chapter_markers_ms=(600_000, 1_800_000, 3_000_000),
        )

        plan = detect_breaks(
            assembly_result=assembly,
            grid_duration_ms=GRID_60_MIN_MS,
        )

        assert len(plan.opportunities) == 0
        assert plan.break_budget_ms < 0


# ===========================================================================
# Additional edge case tests
# ===========================================================================


@pytest.mark.contract
class TestBreakDetectionEdgeCases:
    """Additional edge cases from the contract."""

    # Tier: 2 | Scheduling logic invariant
    def test_clustered_chapter_markers_all_emitted(self):
        # Contract edge case: clustered markers within 30s must all be emitted
        assembly = _single_content(
            duration_ms=1_320_000,
            chapter_markers_ms=(600_000, 610_000, 620_000, 1_000_000),
        )

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=GRID_30_MIN_MS)

        chapter_positions = sorted(
            o.position_ms for o in plan.opportunities if o.source == "chapter"
        )
        assert 600_000 in chapter_positions
        assert 610_000 in chapter_positions
        assert 620_000 in chapter_positions
        assert 1_000_000 in chapter_positions

    # Tier: 2 | Scheduling logic invariant
    def test_chapter_markers_at_boundaries_ignored(self):
        # Contract: markers at position 0 or segment boundary are ignored
        assembly = _single_content(
            duration_ms=1_320_000,
            chapter_markers_ms=(0, 660_000, 1_320_000),
        )

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=GRID_30_MIN_MS)

        chapter_opps = [o for o in plan.opportunities if o.source == "chapter"]
        chapter_positions = {o.position_ms for o in chapter_opps}

        assert 0 not in chapter_positions, "Marker at position 0 must be ignored"
        assert 1_320_000 not in chapter_positions, "Marker at segment boundary must be ignored"
        assert 660_000 in chapter_positions, "Interior marker must be emitted"

    # Tier: 2 | Scheduling logic invariant
    def test_accumulate_with_intro_boundaries_correct(self):
        # Accumulate with intro: only content-to-content seams are boundaries.
        # Intro-to-content seam must NOT be a boundary.
        segments = [
            FakeAssemblySegment(asset_id="intro", duration_ms=15_000, segment_type="intro"),
            FakeAssemblySegment(asset_id="ep-001", duration_ms=500_000, segment_type="content"),
            FakeAssemblySegment(asset_id="ep-002", duration_ms=500_000, segment_type="content"),
        ]
        assembly = FakeAssemblyResult(segments=segments)

        plan = detect_breaks(assembly_result=assembly, grid_duration_ms=GRID_30_MIN_MS)

        boundary_opps = [o for o in plan.opportunities if o.source == "boundary"]
        boundary_positions = {o.position_ms for o in boundary_opps}

        # Content-to-content seam at 15_000 + 500_000 = 515_000
        assert 515_000 in boundary_positions

        # Intro-to-content seam at 15_000 must NOT be a boundary
        assert 15_000 not in boundary_positions
