"""Contract tests for BlockBreakLayout.

Validates all invariants defined in:
    docs/contracts/block_break_layout.md

Derived from: LAW-CONTENT-AUTHORITY, LAW-GRID, LAW-DERIVATION.

These tests call interfaces that do not yet exist (BlockBreakLayout,
MidrollPlan, build_break_layout, expand_break_layout). They are
expected to fail with ImportError until the implementation is provided.

Invariant groups:
    Budget:     INV-BBL-BUDGET-001 through 010
    Source:     INV-BBL-SOURCE-001 through 009
    Policy:     INV-BBL-POLICY-001 through 007
    Structural: INV-BBL-STRUCT-001 through 008
    Ordering:   INV-BBL-ORDER-001 through 008
    Transition: INV-BBL-TRANS-001 through 003
    Builder:    INV-BBL-BUILDER-001
    Output:     INV-BBL-OUTPUT-001
    Determinism: INV-BBL-DETERMINISM-002
    Time:       INV-BBL-TIME-001
"""

from __future__ import annotations

import inspect

import pytest

try:
    from retrovue.runtime.block_break_layout import (
        BlockBreakLayout,
        MidrollOpportunity,
        MidrollPlan,
        PostrollEntry,
        StructuralEntry,
        SuppressedSource,
        build_break_layout,
        expand_break_layout,
    )
except ImportError:
    pytest.skip(
        "retrovue.runtime.block_break_layout not available — "
        "implementation not yet provided",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GRID_30_MIN = 1_800_000
GRID_60_MIN = 3_600_000
GRID_120_MIN = 7_200_000

EPISODE_22_MIN = 1_320_000  # 22-min sitcom
EPISODE_44_MIN = 2_640_000  # 44-min drama
MOVIE_90_MIN = 5_400_000    # 90-min movie

# Fixed anchor: 2026-03-27T20:00:00Z in ms
BLOCK_START_UTC_MS = 1_774_929_600_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _preroll_total(layout: BlockBreakLayout) -> int:
    return sum(e.duration_ms for e in layout.preroll)


def _postroll_structural_total(layout: BlockBreakLayout) -> int:
    return sum(
        e.duration_ms for e in layout.postroll if not e.is_traffic_marker
    )


def _sum_allocated(layout: BlockBreakLayout) -> int:
    return sum(o.allocated_ms for o in layout.midroll.opportunities)


def _build_network(
    *,
    grid_slot_ms: int = GRID_30_MIN,
    content_duration_ms: int = EPISODE_22_MIN,
    chapter_markers_ms: tuple[int, ...] | None = None,
    dsl_midroll: list[dict] | None = None,
    preroll: list[StructuralEntry] | None = None,
    postroll: list[PostrollEntry] | None = None,
    min_segment_ms: int = 0,
    block_start_utc_ms: int = BLOCK_START_UTC_MS,
) -> BlockBreakLayout:
    """Build a network-channel layout with sensible defaults."""
    return build_break_layout(
        grid_slot_ms=grid_slot_ms,
        content_duration_ms=content_duration_ms,
        channel_type="network",
        block_start_utc_ms=block_start_utc_ms,
        chapter_markers_ms=chapter_markers_ms,
        dsl_midroll=dsl_midroll,
        preroll=preroll or [],
        postroll=postroll or [],
        min_segment_ms=min_segment_ms,
    )


def _build_premium(
    *,
    grid_slot_ms: int = GRID_120_MIN,
    content_duration_ms: int = MOVIE_90_MIN,
    chapter_markers_ms: tuple[int, ...] | None = None,
    dsl_midroll: list[dict] | None = None,
    preroll: list[StructuralEntry] | None = None,
    postroll: list[PostrollEntry] | None = None,
    block_start_utc_ms: int = BLOCK_START_UTC_MS,
) -> BlockBreakLayout:
    """Build a premium-channel layout with sensible defaults."""
    return build_break_layout(
        grid_slot_ms=grid_slot_ms,
        content_duration_ms=content_duration_ms,
        channel_type="premium",
        block_start_utc_ms=block_start_utc_ms,
        chapter_markers_ms=chapter_markers_ms,
        dsl_midroll=dsl_midroll,
        preroll=preroll or [],
        postroll=postroll or [],
    )


def _build_movie(
    *,
    grid_slot_ms: int = GRID_120_MIN,
    content_duration_ms: int = MOVIE_90_MIN,
    chapter_markers_ms: tuple[int, ...] | None = None,
    dsl_midroll: list[dict] | None = None,
    preroll: list[StructuralEntry] | None = None,
    postroll: list[PostrollEntry] | None = None,
    block_start_utc_ms: int = BLOCK_START_UTC_MS,
) -> BlockBreakLayout:
    """Build a movie-channel layout with sensible defaults."""
    return build_break_layout(
        grid_slot_ms=grid_slot_ms,
        content_duration_ms=content_duration_ms,
        channel_type="movie",
        block_start_utc_ms=block_start_utc_ms,
        chapter_markers_ms=chapter_markers_ms,
        dsl_midroll=dsl_midroll,
        preroll=preroll or [],
        postroll=postroll or [],
    )


def _dsl_midroll(positions: list[float], weights: list[float] | None = None):
    """DSL midroll config helper."""
    return [{
        "type": "traffic",
        "placement": {
            "fallback": {
                "strategy": "weighted_positions",
                "positions": positions,
                "weights": weights or [1.0] * len(positions),
            }
        }
    }]


def _structural(asset_id: str, duration_ms: int, segment_type: str = "presentation"):
    return StructuralEntry(
        asset_id=asset_id, duration_ms=duration_ms, segment_type=segment_type,
    )


def _postroll_asset(asset_id: str, duration_ms: int):
    return PostrollEntry(
        asset_id=asset_id, duration_ms=duration_ms,
        segment_type="presentation", is_traffic_marker=False,
    )


def _traffic_marker():
    return PostrollEntry(
        asset_id="", duration_ms=0,
        segment_type="postroll_traffic", is_traffic_marker=True,
    )


# ===========================================================================
# BUDGET INVARIANTS
# ===========================================================================


@pytest.mark.contract
class TestBblBudget001:
    """INV-BBL-BUDGET-001 — Grid equation exact."""

    def test_grid_equation_network_with_midroll(self):
        layout = _build_network(chapter_markers_ms=(420_000, 900_000))
        total = (
            _preroll_total(layout)
            + layout.content_duration_ms
            + layout.midroll.total_filler_ms
            + _postroll_structural_total(layout)
            + layout.trailing_filler_ms
        )
        assert total == layout.grid_slot_ms

    def test_grid_equation_premium_no_midroll(self):
        layout = _build_premium()
        total = (
            _preroll_total(layout)
            + layout.content_duration_ms
            + layout.midroll.total_filler_ms
            + _postroll_structural_total(layout)
            + layout.trailing_filler_ms
        )
        assert total == layout.grid_slot_ms

    def test_grid_equation_with_preroll_and_postroll(self):
        layout = _build_network(
            preroll=[_structural("intro-1", 74_000)],
            postroll=[_postroll_asset("station-id", 10_000), _traffic_marker()],
            chapter_markers_ms=(420_000, 900_000),
        )
        total = (
            _preroll_total(layout)
            + layout.content_duration_ms
            + layout.midroll.total_filler_ms
            + _postroll_structural_total(layout)
            + layout.trailing_filler_ms
        )
        assert total == layout.grid_slot_ms

    def test_grid_equation_zero_filler_budget(self):
        # Content exactly fills the slot
        layout = _build_network(
            grid_slot_ms=EPISODE_22_MIN,
            content_duration_ms=EPISODE_22_MIN,
        )
        total = (
            _preroll_total(layout)
            + layout.content_duration_ms
            + layout.midroll.total_filler_ms
            + _postroll_structural_total(layout)
            + layout.trailing_filler_ms
        )
        assert total == layout.grid_slot_ms


@pytest.mark.contract
class TestBblBudget002:
    """INV-BBL-BUDGET-002 — Midroll allocation exact."""

    def test_allocation_sums_to_total_filler(self):
        layout = _build_network(chapter_markers_ms=(420_000, 900_000))
        assert _sum_allocated(layout) == layout.midroll.total_filler_ms

    def test_allocation_sums_with_dsl_three_breaks(self):
        layout = _build_network(
            dsl_midroll=_dsl_midroll([0.25, 0.50, 0.75]),
        )
        assert _sum_allocated(layout) == layout.midroll.total_filler_ms

    def test_allocation_sums_single_opportunity(self):
        layout = _build_network(
            dsl_midroll=_dsl_midroll([0.50]),
        )
        assert _sum_allocated(layout) == layout.midroll.total_filler_ms

    def test_zero_opportunities_zero_total(self):
        layout = _build_premium()
        assert layout.midroll.total_filler_ms == 0
        assert _sum_allocated(layout) == 0


@pytest.mark.contract
class TestBblBudget003:
    """INV-BBL-BUDGET-003 — Trailing filler is remainder."""

    def test_trailing_equals_available_minus_midroll(self):
        layout = _build_network(chapter_markers_ms=(420_000, 900_000))
        assert layout.trailing_filler_ms == (
            layout.available_filler_ms - layout.midroll.total_filler_ms
        )

    def test_premium_trailing_equals_full_available(self):
        layout = _build_premium()
        assert layout.trailing_filler_ms == layout.available_filler_ms


@pytest.mark.contract
class TestBblBudget004:
    """INV-BBL-BUDGET-004 — No negative durations."""

    def test_no_negative_on_layout(self):
        layout = _build_network(chapter_markers_ms=(420_000,))
        assert layout.grid_slot_ms >= 0
        assert layout.content_duration_ms >= 0
        assert layout.available_filler_ms >= 0
        assert layout.trailing_filler_ms >= 0
        assert layout.midroll.total_filler_ms >= 0

    def test_no_negative_on_opportunities(self):
        layout = _build_network(chapter_markers_ms=(420_000, 900_000))
        for opp in layout.midroll.opportunities:
            assert opp.allocated_ms >= 0
            assert opp.position_ms >= 0

    def test_no_negative_on_structural_entries(self):
        layout = _build_network(
            preroll=[_structural("intro-1", 74_000)],
            postroll=[_postroll_asset("sid", 10_000)],
        )
        for entry in layout.preroll:
            assert entry.duration_ms >= 0
        for entry in layout.postroll:
            assert entry.duration_ms >= 0


@pytest.mark.contract
class TestBblBudget005:
    """INV-BBL-BUDGET-005 — Midroll cannot exceed available budget."""

    def test_midroll_within_available(self):
        layout = _build_network(chapter_markers_ms=(420_000, 900_000))
        assert layout.midroll.total_filler_ms <= layout.available_filler_ms

    def test_midroll_within_available_with_structural(self):
        layout = _build_network(
            preroll=[_structural("intro-1", 74_000)],
            postroll=[_postroll_asset("sid", 10_000)],
            chapter_markers_ms=(420_000,),
        )
        assert layout.midroll.total_filler_ms <= layout.available_filler_ms


@pytest.mark.contract
class TestBblBudget006:
    """INV-BBL-BUDGET-006 — Zero available budget produces zero midroll."""

    def test_exact_fit_no_midroll(self):
        layout = _build_network(
            grid_slot_ms=EPISODE_22_MIN,
            content_duration_ms=EPISODE_22_MIN,
            chapter_markers_ms=(420_000,),
        )
        assert layout.midroll.opportunities == []
        assert layout.midroll.total_filler_ms == 0

    def test_content_exceeds_slot_no_midroll(self):
        layout = _build_network(
            grid_slot_ms=EPISODE_22_MIN,
            content_duration_ms=EPISODE_22_MIN + 10_000,
        )
        assert layout.midroll.opportunities == []
        assert layout.midroll.total_filler_ms == 0

    def test_structural_consumes_all_budget(self):
        # preroll + postroll + content = grid
        content = 1_000_000
        preroll_ms = 500_000
        postroll_ms = 300_000
        grid = content + preroll_ms + postroll_ms
        layout = _build_network(
            grid_slot_ms=grid,
            content_duration_ms=content,
            preroll=[_structural("intro", preroll_ms)],
            postroll=[_postroll_asset("sid", postroll_ms)],
            chapter_markers_ms=(400_000,),
        )
        assert layout.midroll.opportunities == []


@pytest.mark.contract
class TestBblBudget007:
    """INV-BBL-BUDGET-007 — Weight-proportional allocation deterministic."""

    def test_repeated_builds_identical(self):
        for _ in range(10):
            layout = _build_network(
                dsl_midroll=_dsl_midroll([0.30, 0.72], [1.0, 2.0]),
            )
            allocations = [o.allocated_ms for o in layout.midroll.opportunities]
            # Build again with same inputs
            layout2 = _build_network(
                dsl_midroll=_dsl_midroll([0.30, 0.72], [1.0, 2.0]),
            )
            allocations2 = [o.allocated_ms for o in layout2.midroll.opportunities]
            assert allocations == allocations2


@pytest.mark.contract
class TestBblBudget008:
    """INV-BBL-BUDGET-008 — Content duration positive."""

    def test_zero_content_rejected(self):
        with pytest.raises((ValueError, TypeError)):
            build_break_layout(
                grid_slot_ms=GRID_30_MIN,
                content_duration_ms=0,
                channel_type="network",
                block_start_utc_ms=BLOCK_START_UTC_MS,
                preroll=[], postroll=[],
            )

    def test_negative_content_rejected(self):
        with pytest.raises((ValueError, TypeError)):
            build_break_layout(
                grid_slot_ms=GRID_30_MIN,
                content_duration_ms=-1,
                channel_type="network",
                block_start_utc_ms=BLOCK_START_UTC_MS,
                preroll=[], postroll=[],
            )


@pytest.mark.contract
class TestBblBudget009:
    """INV-BBL-BUDGET-009 — Available filler budget is explicit and correct."""

    def test_available_filler_explicit_field(self):
        layout = _build_network(chapter_markers_ms=(420_000,))
        assert hasattr(layout, "available_filler_ms")

    def test_available_filler_equals_derivation(self):
        layout = _build_network(
            preroll=[_structural("intro", 74_000)],
            postroll=[_postroll_asset("sid", 10_000)],
            chapter_markers_ms=(420_000,),
        )
        expected = (
            layout.grid_slot_ms
            - _preroll_total(layout)
            - _postroll_structural_total(layout)
            - layout.content_duration_ms
        )
        assert layout.available_filler_ms == expected

    def test_available_filler_no_structural(self):
        layout = _build_network()
        expected = layout.grid_slot_ms - layout.content_duration_ms
        assert layout.available_filler_ms == expected


@pytest.mark.contract
class TestBblBudget010:
    """INV-BBL-BUDGET-010 — Allocation rounding is stable."""

    def test_uneven_budget_three_equal_weights(self):
        # 480_000ms / 3 = 160_000 each, 0 remainder
        layout = _build_network(
            dsl_midroll=_dsl_midroll([0.25, 0.50, 0.75], [1.0, 1.0, 1.0]),
        )
        allocs = [o.allocated_ms for o in layout.midroll.opportunities]
        assert sum(allocs) == layout.midroll.total_filler_ms
        # Verify stable on repeat
        layout2 = _build_network(
            dsl_midroll=_dsl_midroll([0.25, 0.50, 0.75], [1.0, 1.0, 1.0]),
        )
        allocs2 = [o.allocated_ms for o in layout2.midroll.opportunities]
        assert allocs == allocs2

    def test_remainder_goes_to_highest_weight(self):
        # Two breaks: weights 1.0, 2.0. Budget likely not evenly divisible.
        layout = _build_network(
            dsl_midroll=_dsl_midroll([0.30, 0.72], [1.0, 2.0]),
        )
        allocs = [o.allocated_ms for o in layout.midroll.opportunities]
        assert sum(allocs) == layout.midroll.total_filler_ms
        # Second break (weight 2.0) should get >= double the first
        # (within 1ms rounding)
        assert allocs[1] >= allocs[0] * 2 - 1


# ===========================================================================
# SOURCE INVARIANTS
# ===========================================================================


@pytest.mark.contract
class TestBblSource001:
    """INV-BBL-SOURCE-001 — Single source per block."""

    def test_source_is_valid_enum(self):
        layout = _build_network(chapter_markers_ms=(420_000,))
        assert layout.midroll.source in ("dsl", "chapter", "algorithmic", "none")

    def test_premium_source_is_none(self):
        layout = _build_premium()
        assert layout.midroll.source == "none"


@pytest.mark.contract
class TestBblSource002:
    """INV-BBL-SOURCE-002 — Source consistent with opportunities."""

    def test_none_means_empty(self):
        layout = _build_premium()
        assert layout.midroll.source == "none"
        assert layout.midroll.opportunities == []

    def test_dsl_means_nonempty(self):
        layout = _build_network(
            dsl_midroll=_dsl_midroll([0.30, 0.72]),
        )
        assert layout.midroll.source == "dsl"
        assert len(layout.midroll.opportunities) > 0

    def test_chapter_means_nonempty(self):
        layout = _build_network(chapter_markers_ms=(420_000, 900_000))
        assert layout.midroll.source == "chapter"
        assert len(layout.midroll.opportunities) > 0

    def test_algorithmic_means_nonempty(self):
        layout = _build_network()  # no DSL, no chapters
        assert layout.midroll.source == "algorithmic"
        assert len(layout.midroll.opportunities) > 0


@pytest.mark.contract
class TestBblSource003:
    """INV-BBL-SOURCE-003 — Chapter supersedes DSL."""

    def test_chapter_present_dsl_ignored(self):
        layout = _build_network(
            dsl_midroll=_dsl_midroll([0.30, 0.72]),
            chapter_markers_ms=(420_000, 900_000),
        )
        assert layout.midroll.source == "chapter"
        # Positions from chapter markers, not from DSL
        positions = [o.position_ms for o in layout.midroll.opportunities]
        assert 420_000 in positions
        assert 900_000 in positions
        # DSL fractional positions should NOT appear
        assert round(0.30 * EPISODE_22_MIN) not in positions
        assert round(0.72 * EPISODE_22_MIN) not in positions

    def test_dsl_suppressed_when_chapters_win(self):
        layout = _build_network(
            dsl_midroll=_dsl_midroll([0.30, 0.72]),
            chapter_markers_ms=(420_000, 900_000),
        )
        suppressed_names = {s.source for s in layout.suppressed_sources}
        assert "dsl" in suppressed_names
        reasons = {s.reason for s in layout.suppressed_sources if s.source == "dsl"}
        assert "chapter_precedence" in reasons


@pytest.mark.contract
class TestBblSource004:
    """INV-BBL-SOURCE-004 — DSL supersedes algorithmic."""

    def test_chapters_present_algorithmic_suppressed(self):
        layout = _build_network(chapter_markers_ms=(420_000, 900_000))
        assert layout.midroll.source == "chapter"
        positions = [o.position_ms for o in layout.midroll.opportunities]
        assert 420_000 in positions
        assert 900_000 in positions

    def test_dsl_used_when_chapters_absent(self):
        layout = _build_network(dsl_midroll=_dsl_midroll([0.50]))
        assert layout.midroll.source == "dsl"

    def test_dsl_used_when_chapters_all_invalid(self):
        # All chapter markers at boundary → filtered → DSL takes over
        layout = _build_network(
            dsl_midroll=_dsl_midroll([0.50]),
            chapter_markers_ms=(0, EPISODE_22_MIN),
        )
        assert layout.midroll.source == "dsl"


@pytest.mark.contract
class TestBblSource005:
    """INV-BBL-SOURCE-005 — Algorithmic is last resort."""

    def test_no_dsl_no_chapters_uses_algorithmic(self):
        layout = _build_network()
        assert layout.midroll.source == "algorithmic"

    def test_algorithmic_not_used_when_dsl_present(self):
        layout = _build_network(dsl_midroll=_dsl_midroll([0.50]))
        assert layout.midroll.source != "algorithmic"

    def test_algorithmic_not_used_when_chapters_present(self):
        layout = _build_network(chapter_markers_ms=(600_000,))
        assert layout.midroll.source != "algorithmic"


@pytest.mark.contract
class TestBblSource006:
    """INV-BBL-SOURCE-006 — DSL positions are fractional-derived."""

    def test_dsl_position_matches_fraction(self):
        fractions = [0.30, 0.72]
        layout = _build_network(dsl_midroll=_dsl_midroll(fractions))
        for opp, frac in zip(layout.midroll.opportunities, fractions):
            expected = round(frac * layout.content_duration_ms)
            assert opp.position_ms == expected, (
                f"DSL fraction {frac} → expected {expected}, got {opp.position_ms}"
            )


@pytest.mark.contract
class TestBblSource007:
    """INV-BBL-SOURCE-007 — Chapter positions are catalog-derived."""

    def test_chapter_positions_match_catalog(self):
        markers = (360_000, 720_000, 1_080_000)
        layout = _build_network(chapter_markers_ms=markers)
        positions = [o.position_ms for o in layout.midroll.opportunities]
        for m in markers:
            assert m in positions


@pytest.mark.contract
class TestBblSource008:
    """INV-BBL-SOURCE-008 — Zero budget forces source to none."""

    def test_zero_budget_source_none(self):
        layout = _build_network(
            grid_slot_ms=EPISODE_22_MIN,
            content_duration_ms=EPISODE_22_MIN,
            chapter_markers_ms=(420_000,),
        )
        assert layout.midroll.source == "none"

    def test_negative_budget_source_none(self):
        layout = _build_network(
            grid_slot_ms=EPISODE_22_MIN,
            content_duration_ms=EPISODE_22_MIN + 10_000,
        )
        assert layout.midroll.source == "none"

    def test_dsl_present_but_zero_budget(self):
        layout = _build_network(
            grid_slot_ms=EPISODE_22_MIN,
            content_duration_ms=EPISODE_22_MIN,
            dsl_midroll=_dsl_midroll([0.30, 0.72]),
        )
        assert layout.midroll.source == "none"
        assert layout.midroll.opportunities == []


@pytest.mark.contract
class TestBblSource009:
    """INV-BBL-SOURCE-009 — No implicit break creation."""

    def test_dsl_two_breaks_produces_exactly_two(self):
        layout = _build_network(dsl_midroll=_dsl_midroll([0.30, 0.72]))
        assert len(layout.midroll.opportunities) == 2

    def test_chapter_three_markers_produces_exactly_three(self):
        markers = (360_000, 720_000, 1_080_000)
        layout = _build_network(chapter_markers_ms=markers)
        assert len(layout.midroll.opportunities) == len(markers)


# ===========================================================================
# POLICY INVARIANTS
# ===========================================================================


@pytest.mark.contract
class TestBblPolicy001:
    """INV-BBL-POLICY-001 — Premium forbids midroll."""

    def test_premium_no_midroll(self):
        layout = _build_premium(chapter_markers_ms=(1_800_000, 3_600_000))
        assert layout.midroll.opportunities == []
        assert layout.midroll.source == "none"

    def test_premium_no_midroll_with_dsl(self):
        layout = _build_premium(dsl_midroll=_dsl_midroll([0.30, 0.72]))
        assert layout.midroll.opportunities == []
        assert layout.midroll.source == "none"


@pytest.mark.contract
class TestBblPolicy002:
    """INV-BBL-POLICY-002 — Movie forbids midroll."""

    def test_movie_no_midroll(self):
        layout = _build_movie(chapter_markers_ms=(1_800_000, 3_600_000))
        assert layout.midroll.opportunities == []
        assert layout.midroll.source == "none"

    def test_movie_no_midroll_with_dsl(self):
        layout = _build_movie(dsl_midroll=_dsl_midroll([0.30, 0.72]))
        assert layout.midroll.opportunities == []
        assert layout.midroll.source == "none"


@pytest.mark.contract
class TestBblPolicy003:
    """INV-BBL-POLICY-003 — Suppressed budget becomes trailing filler."""

    def test_premium_trailing_is_full_available(self):
        layout = _build_premium()
        assert layout.midroll.total_filler_ms == 0
        assert layout.trailing_filler_ms == layout.available_filler_ms

    def test_movie_trailing_is_full_available(self):
        layout = _build_movie()
        assert layout.midroll.total_filler_ms == 0
        assert layout.trailing_filler_ms == layout.available_filler_ms


@pytest.mark.contract
class TestBblPolicy004:
    """INV-BBL-POLICY-004 — Algorithmic unavailable on forbidden channels."""

    def test_premium_no_algorithmic(self):
        # No DSL, no chapters — would normally trigger algorithmic
        layout = _build_premium()
        assert layout.midroll.source == "none"

    def test_movie_no_algorithmic(self):
        layout = _build_movie()
        assert layout.midroll.source == "none"


@pytest.mark.contract
class TestBblPolicy005:
    """INV-BBL-POLICY-005 — Network allows all sources."""

    def test_network_dsl(self):
        layout = _build_network(dsl_midroll=_dsl_midroll([0.50]))
        assert layout.midroll.source == "dsl"

    def test_network_chapter(self):
        layout = _build_network(chapter_markers_ms=(600_000,))
        assert layout.midroll.source == "chapter"

    def test_network_algorithmic(self):
        layout = _build_network()
        assert layout.midroll.source == "algorithmic"


@pytest.mark.contract
class TestBblPolicy006:
    """INV-BBL-POLICY-006 — Suppressed sources are recorded structurally."""

    def test_premium_with_dsl_records_suppression(self):
        layout = _build_premium(dsl_midroll=_dsl_midroll([0.30]))
        assert hasattr(layout, "suppressed_sources")
        sources = {s.source for s in layout.suppressed_sources}
        assert "dsl" in sources

    def test_premium_with_chapters_records_suppression(self):
        layout = _build_premium(chapter_markers_ms=(1_800_000,))
        sources = {s.source for s in layout.suppressed_sources}
        assert "chapter" in sources

    def test_zero_budget_records_suppression(self):
        layout = _build_network(
            grid_slot_ms=EPISODE_22_MIN,
            content_duration_ms=EPISODE_22_MIN,
            dsl_midroll=_dsl_midroll([0.30]),
        )
        sources = {s.source for s in layout.suppressed_sources}
        assert "dsl" in sources
        reasons = {s.reason for s in layout.suppressed_sources if s.source == "dsl"}
        assert "zero_budget" in reasons

    def test_network_no_suppression_when_used(self):
        layout = _build_network(chapter_markers_ms=(420_000,))
        # Chapter was used, no sources suppressed (algorithmic not eligible
        # because chapter won)
        suppressed_names = {s.source for s in layout.suppressed_sources}
        assert "chapter" not in suppressed_names


@pytest.mark.contract
class TestBblPolicy007:
    """INV-BBL-POLICY-007 — Suppression reasons are exhaustive."""

    def test_policy_reason_on_premium(self):
        layout = _build_premium(dsl_midroll=_dsl_midroll([0.30]))
        for s in layout.suppressed_sources:
            assert s.reason in ("policy", "zero_budget", "invalid_positions", "chapter_precedence")
        reasons = {s.reason for s in layout.suppressed_sources if s.source == "dsl"}
        assert "policy" in reasons

    def test_zero_budget_reason(self):
        layout = _build_network(
            grid_slot_ms=EPISODE_22_MIN,
            content_duration_ms=EPISODE_22_MIN,
            chapter_markers_ms=(420_000,),
        )
        for s in layout.suppressed_sources:
            assert s.reason in ("policy", "zero_budget", "invalid_positions", "chapter_precedence")

    def test_invalid_positions_reason(self):
        # All positions outside bounds → filtered → invalid_positions
        layout = _build_network(
            dsl_midroll=_dsl_midroll([0.0, 1.0]),  # both invalid
        )
        # If DSL was present but all positions invalid, should appear as
        # suppressed with reason invalid_positions, and fall through
        suppressed_names = {s.source for s in layout.suppressed_sources}
        if layout.midroll.source != "dsl":
            assert "dsl" in suppressed_names
            reasons = {
                s.reason for s in layout.suppressed_sources if s.source == "dsl"
            }
            assert "invalid_positions" in reasons


# ===========================================================================
# STRUCTURAL INVARIANTS
# ===========================================================================


@pytest.mark.contract
class TestBblStruct001:
    """INV-BBL-STRUCT-001 — Preroll entries have asset identity."""

    def test_preroll_entries_valid(self):
        layout = _build_network(
            preroll=[_structural("intro-1", 74_000)],
        )
        for entry in layout.preroll:
            assert entry.asset_id != ""
            assert entry.duration_ms > 0


@pytest.mark.contract
class TestBblStruct002:
    """INV-BBL-STRUCT-002 — Postroll non-marker entries have asset identity."""

    def test_postroll_assets_valid(self):
        layout = _build_network(
            postroll=[
                _postroll_asset("station-id-1", 10_000),
                _traffic_marker(),
            ],
        )
        for entry in layout.postroll:
            if not entry.is_traffic_marker:
                assert entry.asset_id != ""
                assert entry.duration_ms > 0


@pytest.mark.contract
class TestBblStruct003:
    """INV-BBL-STRUCT-003 — Traffic marker has zero duration."""

    def test_traffic_marker_zero_duration(self):
        layout = _build_network(
            postroll=[_postroll_asset("sid", 10_000), _traffic_marker()],
        )
        markers = [e for e in layout.postroll if e.is_traffic_marker]
        for m in markers:
            assert m.duration_ms == 0


@pytest.mark.contract
class TestBblStruct004:
    """INV-BBL-STRUCT-004 — At most one traffic marker."""

    def test_single_traffic_marker(self):
        layout = _build_network(
            postroll=[_traffic_marker()],
        )
        marker_count = sum(1 for e in layout.postroll if e.is_traffic_marker)
        assert marker_count <= 1

    def test_no_traffic_marker_allowed(self):
        layout = _build_network(
            postroll=[_postroll_asset("sid", 10_000)],
        )
        marker_count = sum(1 for e in layout.postroll if e.is_traffic_marker)
        assert marker_count == 0


@pytest.mark.contract
class TestBblStruct005:
    """INV-BBL-STRUCT-005 — Single content timeline."""

    def test_content_duration_is_scalar(self):
        layout = _build_network()
        assert isinstance(layout.content_duration_ms, int)
        assert layout.content_duration_ms > 0


@pytest.mark.contract
class TestBblStruct006:
    """INV-BBL-STRUCT-006 — Opportunity weights positive."""

    def test_all_weights_positive(self):
        layout = _build_network(
            dsl_midroll=_dsl_midroll([0.25, 0.50, 0.75], [1.0, 2.0, 3.0]),
        )
        for opp in layout.midroll.opportunities:
            assert opp.weight > 0.0

    def test_chapter_weights_positive(self):
        layout = _build_network(chapter_markers_ms=(420_000, 900_000))
        for opp in layout.midroll.opportunities:
            assert opp.weight > 0.0

    def test_algorithmic_weights_positive(self):
        layout = _build_network()
        for opp in layout.midroll.opportunities:
            assert opp.weight > 0.0


@pytest.mark.contract
class TestBblStruct007:
    """INV-BBL-STRUCT-007 — Grid slot positive."""

    def test_zero_grid_rejected(self):
        with pytest.raises((ValueError, TypeError)):
            build_break_layout(
                grid_slot_ms=0,
                content_duration_ms=1_000,
                channel_type="network",
                block_start_utc_ms=BLOCK_START_UTC_MS,
                preroll=[], postroll=[],
            )

    def test_negative_grid_rejected(self):
        with pytest.raises((ValueError, TypeError)):
            build_break_layout(
                grid_slot_ms=-1,
                content_duration_ms=1_000,
                channel_type="network",
                block_start_utc_ms=BLOCK_START_UTC_MS,
                preroll=[], postroll=[],
            )


@pytest.mark.contract
class TestBblStruct008:
    """INV-BBL-STRUCT-008 — Minimum content segment duration."""

    def test_breaks_too_close_rejected(self):
        # Two breaks 1ms apart → content segment of 1ms
        min_seg = 30_000  # 30 seconds
        content = EPISODE_22_MIN
        pos_a = 0.50
        pos_b = pos_a + (1 / content)  # ~1ms apart
        layout = _build_network(
            dsl_midroll=_dsl_midroll([pos_a, pos_b]),
            min_segment_ms=min_seg,
        )
        # Layout must either reject or filter one position
        positions = [o.position_ms for o in layout.midroll.opportunities]
        # All content segments must exceed min
        prev = 0
        for p in positions:
            assert p - prev >= min_seg, (
                f"Segment {prev}→{p} is {p - prev}ms, below min {min_seg}ms"
            )
            prev = p
        # Final act
        assert content - prev >= min_seg

    def test_break_too_close_to_start(self):
        min_seg = 30_000
        layout = _build_network(
            dsl_midroll=_dsl_midroll([0.01]),  # ~13.2s into 22min
            min_segment_ms=min_seg,
        )
        if layout.midroll.opportunities:
            assert layout.midroll.opportunities[0].position_ms >= min_seg

    def test_break_too_close_to_end(self):
        min_seg = 30_000
        content = EPISODE_22_MIN
        # Position at 99.9% → ~1.3s before end
        layout = _build_network(
            dsl_midroll=_dsl_midroll([0.999]),
            min_segment_ms=min_seg,
        )
        if layout.midroll.opportunities:
            last_pos = layout.midroll.opportunities[-1].position_ms
            assert content - last_pos >= min_seg


# ===========================================================================
# ORDERING INVARIANTS
# ===========================================================================


@pytest.mark.contract
class TestBblOrder001:
    """INV-BBL-ORDER-001 — Midroll positions strictly ascending."""

    def test_positions_ascending(self):
        layout = _build_network(
            dsl_midroll=_dsl_midroll([0.25, 0.50, 0.75]),
        )
        positions = [o.position_ms for o in layout.midroll.opportunities]
        for i in range(len(positions) - 1):
            assert positions[i] < positions[i + 1]

    def test_chapter_positions_ascending(self):
        layout = _build_network(
            chapter_markers_ms=(900_000, 420_000, 1_080_000),  # unsorted input
        )
        positions = [o.position_ms for o in layout.midroll.opportunities]
        for i in range(len(positions) - 1):
            assert positions[i] < positions[i + 1]


@pytest.mark.contract
class TestBblOrder002:
    """INV-BBL-ORDER-002 — Midroll positions within content bounds."""

    def test_all_positions_within_bounds(self):
        layout = _build_network(chapter_markers_ms=(420_000, 900_000))
        for opp in layout.midroll.opportunities:
            assert 0 < opp.position_ms < layout.content_duration_ms

    def test_dsl_positions_within_bounds(self):
        layout = _build_network(
            dsl_midroll=_dsl_midroll([0.10, 0.90]),
        )
        for opp in layout.midroll.opportunities:
            assert 0 < opp.position_ms < layout.content_duration_ms


@pytest.mark.contract
class TestBblOrder003:
    """INV-BBL-ORDER-003 — No duplicate positions."""

    def test_no_duplicates(self):
        layout = _build_network(
            dsl_midroll=_dsl_midroll([0.25, 0.50, 0.75]),
        )
        positions = [o.position_ms for o in layout.midroll.opportunities]
        assert len(positions) == len(set(positions))

    def test_chapter_duplicates_deduplicated(self):
        # Two markers at same position
        layout = _build_network(
            chapter_markers_ms=(420_000, 420_000, 900_000),
        )
        positions = [o.position_ms for o in layout.midroll.opportunities]
        assert len(positions) == len(set(positions))


@pytest.mark.contract
class TestBblOrder004:
    """INV-BBL-ORDER-004 — Phase sequence canonical."""

    def test_no_preroll_after_content(self):
        # This is a structural guarantee of the layout, not directly
        # testable on BlockBreakLayout (which stores phases separately).
        # Validated by checking that expansion output follows the rule.
        # At the layout level: preroll, midroll, postroll are separate lists.
        layout = _build_network(
            preroll=[_structural("intro", 74_000)],
            postroll=[_postroll_asset("sid", 10_000)],
            chapter_markers_ms=(420_000,),
        )
        # Phases exist as distinct fields — structural guarantee
        assert isinstance(layout.preroll, list)
        assert isinstance(layout.midroll, MidrollPlan)
        assert isinstance(layout.postroll, list)


@pytest.mark.contract
class TestBblOrder005:
    """INV-BBL-ORDER-005 — Preroll in declared order."""

    def test_preroll_order_preserved(self):
        entries = [
            _structural("intro-hbo", 74_000),
            _structural("rating-pg13", 5_000),
        ]
        layout = _build_network(preroll=entries)
        assert layout.preroll[0].asset_id == "intro-hbo"
        assert layout.preroll[1].asset_id == "rating-pg13"


@pytest.mark.contract
class TestBblOrder006:
    """INV-BBL-ORDER-006 — Postroll in declared order."""

    def test_postroll_order_preserved(self):
        entries = [
            _postroll_asset("coming-up", 15_000),
            _traffic_marker(),
            _postroll_asset("station-id", 10_000),
        ]
        layout = _build_network(postroll=entries)
        assert layout.postroll[0].asset_id == "coming-up"
        assert layout.postroll[1].is_traffic_marker
        assert layout.postroll[2].asset_id == "station-id"


@pytest.mark.contract
class TestBblOrder007:
    """INV-BBL-ORDER-007 — Allocation order is stable."""

    def test_allocation_follows_position_order(self):
        layout = _build_network(
            dsl_midroll=_dsl_midroll([0.30, 0.72], [1.0, 2.0]),
        )
        opps = layout.midroll.opportunities
        # Verify opportunities are in position order (ORDER-001) and
        # allocation was applied in that order
        positions = [o.position_ms for o in opps]
        assert positions == sorted(positions)
        # Weight 2.0 break should get ~2x the allocation of weight 1.0
        if len(opps) == 2 and opps[0].allocated_ms > 0:
            ratio = opps[1].allocated_ms / opps[0].allocated_ms
            assert 1.9 <= ratio <= 2.1


@pytest.mark.contract
class TestBblOrder008:
    """INV-BBL-ORDER-008 — Trailing filler placement deterministic."""

    def test_with_traffic_marker(self):
        layout = _build_network(
            postroll=[_postroll_asset("sid", 10_000), _traffic_marker()],
            chapter_markers_ms=(420_000,),
        )
        # Traffic marker exists → trailing filler goes there
        has_marker = any(e.is_traffic_marker for e in layout.postroll)
        assert has_marker
        # trailing_filler_ms is explicitly computed
        assert layout.trailing_filler_ms >= 0

    def test_without_traffic_marker(self):
        layout = _build_network(
            postroll=[_postroll_asset("sid", 10_000)],
            chapter_markers_ms=(420_000,),
        )
        # No traffic marker → trailing filler goes after postroll
        has_marker = any(e.is_traffic_marker for e in layout.postroll)
        assert not has_marker
        assert layout.trailing_filler_ms >= 0

    def test_no_postroll_at_all(self):
        layout = _build_network(chapter_markers_ms=(420_000,))
        assert layout.trailing_filler_ms >= 0


# ===========================================================================
# TRANSITION INVARIANTS
# ===========================================================================


@pytest.mark.contract
class TestBblTrans001:
    """INV-BBL-TRANS-001 — DSL breaks are clean."""

    def test_dsl_transitions_clean(self):
        layout = _build_network(dsl_midroll=_dsl_midroll([0.30, 0.72]))
        for opp in layout.midroll.opportunities:
            assert opp.transition_style == "clean"


@pytest.mark.contract
class TestBblTrans002:
    """INV-BBL-TRANS-002 — Chapter breaks are clean."""

    def test_chapter_transitions_clean(self):
        layout = _build_network(chapter_markers_ms=(420_000, 900_000))
        for opp in layout.midroll.opportunities:
            assert opp.transition_style == "clean"


@pytest.mark.contract
class TestBblTrans003:
    """INV-BBL-TRANS-003 — Algorithmic breaks are faded."""

    def test_algorithmic_transitions_fade(self):
        layout = _build_network()
        assert layout.midroll.source == "algorithmic"
        for opp in layout.midroll.opportunities:
            assert opp.transition_style == "fade"


# ===========================================================================
# EDGE CASE TESTS
# ===========================================================================


@pytest.mark.contract
class TestBblEdgeCases:
    """Edge cases not covered by single-invariant tests."""

    def test_single_opportunity_gets_full_budget(self):
        layout = _build_network(dsl_midroll=_dsl_midroll([0.50]))
        assert len(layout.midroll.opportunities) == 1
        opp = layout.midroll.opportunities[0]
        assert opp.allocated_ms == layout.midroll.total_filler_ms

    def test_dsl_boundary_positions_filtered(self):
        # 0.0 and 1.0 are invalid (at content start/end)
        layout = _build_network(
            dsl_midroll=_dsl_midroll([0.0, 0.50, 1.0]),
        )
        positions = [o.position_ms for o in layout.midroll.opportunities]
        assert 0 not in positions
        assert layout.content_duration_ms not in positions

    def test_chapter_marker_at_zero_filtered(self):
        layout = _build_network(chapter_markers_ms=(0, 420_000, 900_000))
        positions = [o.position_ms for o in layout.midroll.opportunities]
        assert 0 not in positions

    def test_chapter_marker_at_end_filtered(self):
        layout = _build_network(
            chapter_markers_ms=(420_000, EPISODE_22_MIN),
        )
        positions = [o.position_ms for o in layout.midroll.opportunities]
        assert EPISODE_22_MIN not in positions

    def test_dsl_weights_shorter_than_positions(self):
        # 3 positions but only 2 weights → third gets 1.0
        layout = _build_network(
            dsl_midroll=_dsl_midroll([0.25, 0.50, 0.75], [2.0, 3.0]),
        )
        assert len(layout.midroll.opportunities) == 3
        assert layout.midroll.opportunities[2].weight == 1.0

    def test_very_small_filler_budget(self):
        # Slot only 1ms larger than content
        layout = _build_network(
            grid_slot_ms=EPISODE_22_MIN + 1,
            content_duration_ms=EPISODE_22_MIN,
        )
        # Budget is 1ms. Should still be valid.
        assert layout.available_filler_ms == 1
        assert layout.midroll.total_filler_ms + layout.trailing_filler_ms == 1

    def test_many_opportunities_tiny_budget(self):
        # 5 break positions, only 3ms budget
        layout = _build_network(
            grid_slot_ms=EPISODE_22_MIN + 3,
            content_duration_ms=EPISODE_22_MIN,
            dsl_midroll=_dsl_midroll(
                [0.10, 0.30, 0.50, 0.70, 0.90],
                [1.0, 1.0, 1.0, 1.0, 1.0],
            ),
        )
        total_alloc = sum(o.allocated_ms for o in layout.midroll.opportunities)
        assert total_alloc == layout.midroll.total_filler_ms
        assert layout.midroll.total_filler_ms <= 3

    def test_premium_with_preroll_postroll_no_midroll(self):
        layout = _build_premium(
            preroll=[_structural("hbo-intro", 74_000)],
            postroll=[
                _postroll_asset("coming-up", 15_000),
                _traffic_marker(),
                _postroll_asset("station-id", 10_000),
            ],
            chapter_markers_ms=(1_800_000, 3_600_000),
        )
        assert layout.midroll.opportunities == []
        assert layout.midroll.source == "none"
        assert layout.trailing_filler_ms == layout.available_filler_ms
        # Grid equation still holds
        total = (
            _preroll_total(layout)
            + layout.content_duration_ms
            + layout.midroll.total_filler_ms
            + _postroll_structural_total(layout)
            + layout.trailing_filler_ms
        )
        assert total == layout.grid_slot_ms


# ===========================================================================
# INVALID STATE TESTS
# ===========================================================================


@pytest.mark.contract
class TestBblInvalidStates:
    """Tests that invalid inputs are rejected."""

    def test_zero_grid_slot_rejected(self):
        with pytest.raises((ValueError, TypeError)):
            build_break_layout(
                grid_slot_ms=0,
                content_duration_ms=1_000,
                channel_type="network",
                block_start_utc_ms=BLOCK_START_UTC_MS,
                preroll=[], postroll=[],
            )

    def test_negative_grid_slot_rejected(self):
        with pytest.raises((ValueError, TypeError)):
            build_break_layout(
                grid_slot_ms=-100,
                content_duration_ms=1_000,
                channel_type="network",
                block_start_utc_ms=BLOCK_START_UTC_MS,
                preroll=[], postroll=[],
            )

    def test_zero_content_duration_rejected(self):
        with pytest.raises((ValueError, TypeError)):
            build_break_layout(
                grid_slot_ms=GRID_30_MIN,
                content_duration_ms=0,
                channel_type="network",
                block_start_utc_ms=BLOCK_START_UTC_MS,
                preroll=[], postroll=[],
            )

    def test_negative_content_duration_rejected(self):
        with pytest.raises((ValueError, TypeError)):
            build_break_layout(
                grid_slot_ms=GRID_30_MIN,
                content_duration_ms=-1,
                channel_type="network",
                block_start_utc_ms=BLOCK_START_UTC_MS,
                preroll=[], postroll=[],
            )

    def test_unknown_channel_type_rejected(self):
        with pytest.raises((ValueError, TypeError)):
            build_break_layout(
                grid_slot_ms=GRID_30_MIN,
                content_duration_ms=EPISODE_22_MIN,
                channel_type="unknown_type",
                block_start_utc_ms=BLOCK_START_UTC_MS,
                preroll=[], postroll=[],
            )


# ===========================================================================
# BUILDER INVARIANTS
# ===========================================================================


@pytest.mark.contract
class TestBblBuilder001:
    """INV-BBL-BUILDER-001 — Builder inputs fully determine layout."""

    def test_builder_is_pure_function(self):
        """Same inputs → same output, no external state."""
        kwargs = dict(
            grid_slot_ms=GRID_30_MIN,
            content_duration_ms=EPISODE_22_MIN,
            channel_type="network",
            block_start_utc_ms=BLOCK_START_UTC_MS,
            dsl_midroll=_dsl_midroll([0.30, 0.72], [1.0, 2.0]),
            chapter_markers_ms=(420_000, 900_000),
            preroll=[_structural("intro", 74_000)],
            postroll=[_postroll_asset("sid", 10_000), _traffic_marker()],
            min_segment_ms=0,
        )
        layout_a = build_break_layout(**kwargs)
        layout_b = build_break_layout(**kwargs)
        assert layout_a == layout_b

    def test_builder_signature_keyword_only(self):
        """All parameters must be keyword-only (no positional accidents)."""
        sig = inspect.signature(build_break_layout)
        for name, param in sig.parameters.items():
            assert param.kind in (
                inspect.Parameter.KEYWORD_ONLY,
                inspect.Parameter.VAR_KEYWORD,
            ), f"Parameter '{name}' must be keyword-only"

    def test_builder_requires_all_inputs(self):
        """Builder must require grid_slot_ms, content_duration_ms,
        channel_type, and block_start_utc_ms."""
        sig = inspect.signature(build_break_layout)
        params = sig.parameters
        for required in (
            "grid_slot_ms", "content_duration_ms",
            "channel_type", "block_start_utc_ms",
        ):
            assert required in params, f"Missing required param: {required}"

    def test_builder_does_not_accept_resolver(self):
        """Builder must not accept a resolver — all inputs pre-resolved."""
        sig = inspect.signature(build_break_layout)
        param_names = set(sig.parameters.keys())
        forbidden = {"resolver", "catalog", "db", "session", "store"}
        assert param_names.isdisjoint(forbidden), (
            f"Builder accepts forbidden params: {param_names & forbidden}"
        )


# ===========================================================================
# OUTPUT INVARIANTS
# ===========================================================================


@pytest.mark.contract
class TestBblOutput001:
    """INV-BBL-OUTPUT-001 — Expansion requires no decision-making."""

    def test_expansion_does_not_import_break_detection(self):
        """expand_break_layout must not depend on break_detection module."""
        import retrovue.runtime.block_break_layout as bbl_mod
        source = inspect.getsource(bbl_mod.expand_break_layout)
        assert "detect_breaks" not in source
        assert "break_detection" not in source

    def test_expansion_does_not_accept_channel_type(self):
        """Expansion signature must not include channel_type —
        policy was already applied at layout construction."""
        sig = inspect.signature(expand_break_layout)
        assert "channel_type" not in sig.parameters

    def test_expansion_does_not_accept_chapter_markers(self):
        """Expansion must not receive raw chapter markers."""
        sig = inspect.signature(expand_break_layout)
        assert "chapter_markers_ms" not in sig.parameters
        assert "chapter_markers" not in sig.parameters

    def test_expansion_accepts_layout(self):
        """Expansion must accept a BlockBreakLayout."""
        sig = inspect.signature(expand_break_layout)
        # Must have at least one param that could be the layout
        param_names = list(sig.parameters.keys())
        assert len(param_names) >= 1

    def test_expansion_produces_segments_from_layout(self):
        """Given a layout, expansion produces ordered segments."""
        layout = _build_network(
            dsl_midroll=_dsl_midroll([0.30, 0.72]),
            preroll=[_structural("intro", 74_000)],
            postroll=[_postroll_asset("sid", 10_000), _traffic_marker()],
        )
        segments = expand_break_layout(layout)
        assert isinstance(segments, list)
        assert len(segments) > 0

    def test_expansion_segment_types_from_layout(self):
        """Segments produced by expansion match layout structure."""
        layout = _build_network(
            dsl_midroll=_dsl_midroll([0.30, 0.72]),
        )
        segments = expand_break_layout(layout)
        types = [s["segment_type"] for s in segments]
        # Must contain content segments
        assert "content" in types
        # For network with 2 midroll breaks: at least 3 content acts
        content_count = types.count("content")
        assert content_count >= 3

    def test_expansion_durations_match_layout(self):
        """Total segment duration equals grid_slot_ms."""
        layout = _build_network(
            dsl_midroll=_dsl_midroll([0.50]),
            preroll=[_structural("intro", 74_000)],
            postroll=[_postroll_asset("sid", 10_000)],
        )
        segments = expand_break_layout(layout)
        total_ms = sum(s["duration_ms"] for s in segments)
        assert total_ms == layout.grid_slot_ms

    def test_expansion_no_policy_recomputation(self):
        """Premium layout with zero midroll → expansion produces
        single content + trailing filler, no midroll inserted."""
        layout = _build_premium()
        segments = expand_break_layout(layout)
        types = [s["segment_type"] for s in segments]
        # Count content segments between preroll and postroll
        # Premium: exactly 1 content segment (no splits)
        content_in_body = [
            s for s in segments if s["segment_type"] == "content"
        ]
        assert len(content_in_body) == 1


# ===========================================================================
# DETERMINISM INVARIANTS
# ===========================================================================


@pytest.mark.contract
class TestBblDeterminism002:
    """INV-BBL-DETERMINISM-002 — Layout replay stability."""

    def test_layout_replay_stable_network(self):
        """Two builds with identical inputs produce structurally equal layouts."""
        kwargs = dict(
            grid_slot_ms=GRID_30_MIN,
            content_duration_ms=EPISODE_22_MIN,
            channel_type="network",
            block_start_utc_ms=BLOCK_START_UTC_MS,
            dsl_midroll=_dsl_midroll([0.30, 0.72], [1.0, 2.0]),
            chapter_markers_ms=None,
            preroll=[_structural("intro", 74_000)],
            postroll=[_postroll_asset("sid", 10_000), _traffic_marker()],
            min_segment_ms=0,
        )
        a = build_break_layout(**kwargs)
        b = build_break_layout(**kwargs)

        # Deep field equality
        assert a.grid_slot_ms == b.grid_slot_ms
        assert a.content_duration_ms == b.content_duration_ms
        assert a.available_filler_ms == b.available_filler_ms
        assert a.trailing_filler_ms == b.trailing_filler_ms
        assert a.block_start_utc_ms == b.block_start_utc_ms

        # Midroll plan
        assert a.midroll.source == b.midroll.source
        assert a.midroll.total_filler_ms == b.midroll.total_filler_ms
        assert len(a.midroll.opportunities) == len(b.midroll.opportunities)
        for oa, ob in zip(a.midroll.opportunities, b.midroll.opportunities):
            assert oa.position_ms == ob.position_ms
            assert oa.weight == ob.weight
            assert oa.allocated_ms == ob.allocated_ms
            assert oa.transition_style == ob.transition_style

        # Suppressed sources (order matters)
        assert len(a.suppressed_sources) == len(b.suppressed_sources)
        for sa, sb in zip(a.suppressed_sources, b.suppressed_sources):
            assert sa.source == sb.source
            assert sa.reason == sb.reason

    def test_layout_replay_stable_premium(self):
        """Premium channel replay stability."""
        kwargs = dict(
            grid_slot_ms=GRID_120_MIN,
            content_duration_ms=MOVIE_90_MIN,
            channel_type="premium",
            block_start_utc_ms=BLOCK_START_UTC_MS,
            dsl_midroll=_dsl_midroll([0.30]),  # suppressed by policy
            chapter_markers_ms=(1_800_000, 3_600_000),
            preroll=[_structural("hbo-intro", 74_000)],
            postroll=[
                _postroll_asset("coming-up", 15_000),
                _traffic_marker(),
                _postroll_asset("sid", 10_000),
            ],
        )
        a = build_break_layout(**kwargs)
        b = build_break_layout(**kwargs)
        assert a == b

    def test_expansion_replay_stable(self):
        """Expansion of identical layouts produces identical segments."""
        layout = _build_network(
            dsl_midroll=_dsl_midroll([0.30, 0.72], [1.0, 2.0]),
            preroll=[_structural("intro", 74_000)],
            postroll=[_postroll_asset("sid", 10_000), _traffic_marker()],
        )
        seg_a = expand_break_layout(layout)
        seg_b = expand_break_layout(layout)
        assert seg_a == seg_b


# ===========================================================================
# TIME INVARIANTS
# ===========================================================================


@pytest.mark.contract
class TestBblTime001:
    """INV-BBL-TIME-001 — Block time anchoring."""

    def test_block_start_utc_ms_present(self):
        layout = _build_network()
        assert hasattr(layout, "block_start_utc_ms")
        assert isinstance(layout.block_start_utc_ms, int)

    def test_block_start_utc_ms_preserved(self):
        """Builder must store the caller-provided timestamp unchanged."""
        anchor = 1_774_929_600_000  # specific value
        layout = _build_network(block_start_utc_ms=anchor)
        assert layout.block_start_utc_ms == anchor

    def test_different_anchors_different_layouts(self):
        """Two blocks at different times are distinct layouts."""
        a = _build_network(block_start_utc_ms=1_000_000_000_000)
        b = _build_network(block_start_utc_ms=2_000_000_000_000)
        assert a.block_start_utc_ms != b.block_start_utc_ms

    def test_anchor_does_not_affect_budget(self):
        """Time anchor is metadata — must not change budget math."""
        a = _build_network(
            block_start_utc_ms=1_000_000_000_000,
            dsl_midroll=_dsl_midroll([0.50]),
        )
        b = _build_network(
            block_start_utc_ms=9_999_999_999_999,
            dsl_midroll=_dsl_midroll([0.50]),
        )
        assert a.available_filler_ms == b.available_filler_ms
        assert a.midroll.total_filler_ms == b.midroll.total_filler_ms
        assert a.trailing_filler_ms == b.trailing_filler_ms

    def test_builder_requires_block_start(self):
        """block_start_utc_ms is mandatory — builder must not default it."""
        sig = inspect.signature(build_break_layout)
        param = sig.parameters.get("block_start_utc_ms")
        assert param is not None
        assert param.default is inspect.Parameter.empty, (
            "block_start_utc_ms must not have a default value"
        )
