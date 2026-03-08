"""
Contract test: INV-BREAK-WEIGHT-001 — Weighted break budget allocation.

Break durations must be proportional to BreakOpportunity.weight.
Sum of all break durations must equal break_plan.break_budget_ms.
Remainder milliseconds distributed starting from highest-weight break.
"""

from __future__ import annotations

from retrovue.runtime.playout_log_expander import (
    _allocate_weighted_budget,
    expand_program_block,
)
from retrovue.runtime.break_detection import BreakOpportunity


START_MS = 1_000_000_000_000


# ===========================================================================
# Direct unit tests for _allocate_weighted_budget
# ===========================================================================


class TestAllocateWeightedBudget:
    """Verify the weighted allocation function directly."""

    def test_proportional_distribution(self):
        """Durations must be proportional to weights."""
        opps = [
            BreakOpportunity(position_ms=100, source="chapter", weight=1.0),
            BreakOpportunity(position_ms=200, source="chapter", weight=2.0),
            BreakOpportunity(position_ms=300, source="chapter", weight=3.0),
            BreakOpportunity(position_ms=400, source="chapter", weight=4.0),
        ]
        durations = _allocate_weighted_budget(opps, budget_ms=180_000)
        # weights [1,2,3,4] sum=10
        # base durations: [18000, 36000, 54000, 72000]
        assert durations == [18_000, 36_000, 54_000, 72_000]

    def test_sum_equals_budget(self):
        """Sum of allocated durations must exactly equal the budget."""
        opps = [
            BreakOpportunity(position_ms=100, source="chapter", weight=1.0),
            BreakOpportunity(position_ms=200, source="chapter", weight=2.0),
            BreakOpportunity(position_ms=300, source="chapter", weight=3.0),
        ]
        budget = 100_000
        durations = _allocate_weighted_budget(opps, budget_ms=budget)
        assert sum(durations) == budget

    def test_remainder_to_highest_weight_first(self):
        """Remainder ms distributed starting from highest-weight break."""
        opps = [
            BreakOpportunity(position_ms=100, source="chapter", weight=1.0),
            BreakOpportunity(position_ms=200, source="chapter", weight=2.0),
            BreakOpportunity(position_ms=300, source="chapter", weight=3.0),
        ]
        # weights [1,2,3] sum=6, budget=100_001
        # base: floor(100_001 * w/6) → [16666, 33333, 50000] = 99999
        # remainder = 2, distributed to highest-weight first: idx 2 gets +1, idx 1 gets +1
        durations = _allocate_weighted_budget(opps, budget_ms=100_001)
        assert sum(durations) == 100_001
        # Highest weight (idx 2) gets remainder first
        assert durations[2] >= durations[1]

    def test_single_break_gets_full_budget(self):
        """Single break receives the entire budget."""
        opps = [
            BreakOpportunity(position_ms=500, source="algorithmic", weight=1.0),
        ]
        durations = _allocate_weighted_budget(opps, budget_ms=120_000)
        assert durations == [120_000]

    def test_equal_weights_equal_distribution(self):
        """Identical weights produce equal (or near-equal) distribution."""
        opps = [
            BreakOpportunity(position_ms=100, source="boundary", weight=5.0),
            BreakOpportunity(position_ms=200, source="boundary", weight=5.0),
            BreakOpportunity(position_ms=300, source="boundary", weight=5.0),
        ]
        durations = _allocate_weighted_budget(opps, budget_ms=90_000)
        assert durations == [30_000, 30_000, 30_000]

    def test_equal_weights_with_remainder(self):
        """Equal weights with indivisible budget — remainder to last breaks."""
        opps = [
            BreakOpportunity(position_ms=100, source="boundary", weight=1.0),
            BreakOpportunity(position_ms=200, source="boundary", weight=1.0),
            BreakOpportunity(position_ms=300, source="boundary", weight=1.0),
        ]
        durations = _allocate_weighted_budget(opps, budget_ms=100)
        # 100 / 3 = 33 each, remainder 1 → highest-weight (all equal, last gets it)
        assert sum(durations) == 100
        assert max(durations) - min(durations) <= 1

    def test_zero_budget(self):
        """Zero budget produces all-zero durations."""
        opps = [
            BreakOpportunity(position_ms=100, source="chapter", weight=1.0),
            BreakOpportunity(position_ms=200, source="chapter", weight=2.0),
        ]
        durations = _allocate_weighted_budget(opps, budget_ms=0)
        assert durations == [0, 0]

    def test_empty_opportunities(self):
        """No opportunities produces empty list."""
        durations = _allocate_weighted_budget([], budget_ms=100_000)
        assert durations == []


# ===========================================================================
# Integration: expand_program_block uses weighted allocation
# ===========================================================================


class TestExpanderUsesWeightedAllocation:
    """Verify expand_program_block produces weight-proportional filler durations."""

    def test_chapter_breaks_weighted_fillers(self):
        """3 chapter breaks with monotonic weights produce increasing filler durations."""
        block = expand_program_block(
            asset_id="ep1", asset_uri="/ep1.mp4",
            start_utc_ms=START_MS, slot_duration_ms=1_800_000,
            episode_duration_ms=1_320_000,
            chapter_markers_ms=(330_000, 660_000, 990_000),
        )
        fillers = [s for s in block.segments if s.segment_type == "filler"]
        assert len(fillers) == 3
        filler_durations = [f.segment_duration_ms for f in fillers]
        # Weights assigned as 1.0, 2.0, 3.0 by detect_breaks (monotonic by position)
        # Budget = 480_000, weights [1,2,3], sum=6
        # Durations: [80_000, 160_000, 240_000]
        assert filler_durations == [80_000, 160_000, 240_000]

    def test_filler_total_equals_budget(self):
        """Sum of all filler durations equals break budget."""
        block = expand_program_block(
            asset_id="ep2", asset_uri="/ep2.mp4",
            start_utc_ms=START_MS, slot_duration_ms=1_800_000,
            episode_duration_ms=1_320_000,
            chapter_markers_ms=(330_000, 660_000, 990_000),
        )
        filler_total = sum(
            s.segment_duration_ms for s in block.segments if s.segment_type == "filler"
        )
        assert filler_total == 480_000

    def test_total_segment_duration_equals_slot(self):
        """Content + filler must sum to slot duration."""
        block = expand_program_block(
            asset_id="ep3", asset_uri="/ep3.mp4",
            start_utc_ms=START_MS, slot_duration_ms=1_800_000,
            episode_duration_ms=1_320_000,
            chapter_markers_ms=(330_000, 660_000, 990_000),
        )
        total = sum(s.segment_duration_ms for s in block.segments)
        assert total == 1_800_000
