"""
Contract test: INV-BREAK-008 — Expander delegates break detection.

The playout log expander must NOT contain inline break detection logic.
Break positions must come exclusively from detect_breaks() via BreakPlan.

This test proves delegation by verifying that expand_program_block produces
break positions that exactly match detect_breaks() output for the same inputs.
"""

from __future__ import annotations

from dataclasses import dataclass

from retrovue.runtime.break_detection import BreakPlan, detect_breaks
from retrovue.runtime.playout_log_expander import expand_program_block


START_MS = 1_000_000_000_000


# ---------------------------------------------------------------------------
# Assembly helper (mirrors what the expander should build internally)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Seg:
    segment_type: str
    duration_ms: int
    chapter_markers_ms: tuple[int, ...] | None = None


@dataclass(frozen=True)
class _Asm:
    total_runtime_ms: int
    segments: tuple[_Seg, ...]


def _assemble(episode_ms: int, markers: tuple[int, ...] | None = None) -> _Asm:
    return _Asm(
        total_runtime_ms=episode_ms,
        segments=(_Seg("content", episode_ms, markers),),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _break_positions_from_block(block) -> list[int]:
    """Extract content segment start offsets (except the first) as break positions."""
    contents = [s for s in block.segments if s.segment_type == "content"]
    return [s.asset_start_offset_ms for s in contents[1:]]


def _break_positions_from_plan(plan: BreakPlan) -> list[int]:
    return [opp.position_ms for opp in plan.opportunities]


# ===========================================================================
# INV-BREAK-008: Expander break positions match detect_breaks output
# ===========================================================================


class TestExpanderDelegatesChapterBreaks:
    """Chapter marker breaks from expander must match detect_breaks."""

    def test_chapter_positions_match(self):
        markers = (330_000, 660_000, 990_000)
        episode_ms = 1_320_000
        slot_ms = 1_800_000

        block = expand_program_block(
            asset_id="ep1", asset_uri="/ep1.mp4",
            start_utc_ms=START_MS, slot_duration_ms=slot_ms,
            episode_duration_ms=episode_ms,
            chapter_markers_ms=markers,
        )

        plan = detect_breaks(
            assembly_result=_assemble(episode_ms, markers),
            grid_duration_ms=slot_ms,
        )

        assert _break_positions_from_block(block) == _break_positions_from_plan(plan)

    def test_single_chapter_marker(self):
        markers = (600_000,)
        episode_ms = 1_200_000
        slot_ms = 1_800_000

        block = expand_program_block(
            asset_id="ep2", asset_uri="/ep2.mp4",
            start_utc_ms=START_MS, slot_duration_ms=slot_ms,
            episode_duration_ms=episode_ms,
            chapter_markers_ms=markers,
        )

        plan = detect_breaks(
            assembly_result=_assemble(episode_ms, markers),
            grid_duration_ms=slot_ms,
        )

        assert _break_positions_from_block(block) == _break_positions_from_plan(plan)


class TestExpanderDelegatesAlgorithmicBreaks:
    """Algorithmic breaks from expander must match detect_breaks."""

    def test_algorithmic_positions_match(self):
        """No chapter markers — expander must produce same positions as detect_breaks."""
        episode_ms = 1_320_000
        slot_ms = 1_800_000

        block = expand_program_block(
            asset_id="ep3", asset_uri="/ep3.mp4",
            start_utc_ms=START_MS, slot_duration_ms=slot_ms,
            episode_duration_ms=episode_ms,
        )

        plan = detect_breaks(
            assembly_result=_assemble(episode_ms),
            grid_duration_ms=slot_ms,
        )

        assert _break_positions_from_block(block) == _break_positions_from_plan(plan)

    def test_hour_long_episode_positions_match(self):
        """Hour-long episode — verify algorithmic break positions match."""
        episode_ms = 2_640_000  # 44 min
        slot_ms = 3_600_000    # 60 min

        block = expand_program_block(
            asset_id="ep4", asset_uri="/ep4.mp4",
            start_utc_ms=START_MS, slot_duration_ms=slot_ms,
            episode_duration_ms=episode_ms,
        )

        plan = detect_breaks(
            assembly_result=_assemble(episode_ms),
            grid_duration_ms=slot_ms,
        )

        assert _break_positions_from_block(block) == _break_positions_from_plan(plan)


class TestExpanderBreakBudget:
    """Break budget must come from BreakPlan, not inline math."""

    def test_filler_total_equals_break_budget(self):
        """Sum of filler durations must equal break_plan.break_budget_ms."""
        episode_ms = 1_320_000
        slot_ms = 1_800_000

        block = expand_program_block(
            asset_id="ep5", asset_uri="/ep5.mp4",
            start_utc_ms=START_MS, slot_duration_ms=slot_ms,
            episode_duration_ms=episode_ms,
            chapter_markers_ms=(330_000, 660_000, 990_000),
        )

        plan = detect_breaks(
            assembly_result=_assemble(episode_ms, (330_000, 660_000, 990_000)),
            grid_duration_ms=slot_ms,
        )

        filler_total = sum(
            s.segment_duration_ms for s in block.segments if s.segment_type == "filler"
        )
        assert filler_total == plan.break_budget_ms

    def test_zero_budget_no_filler(self):
        """When episode fills slot, no filler segments produced."""
        episode_ms = 1_800_000
        slot_ms = 1_800_000

        block = expand_program_block(
            asset_id="ep6", asset_uri="/ep6.mp4",
            start_utc_ms=START_MS, slot_duration_ms=slot_ms,
            episode_duration_ms=episode_ms,
        )

        fillers = [s for s in block.segments if s.segment_type == "filler"]
        assert len(fillers) == 0


class TestExpanderBreakSourceClassification:
    """Break source from BreakPlan drives transition classification."""

    def test_chapter_breaks_are_first_class(self):
        """Chapter marker breaks produce TRANSITION_NONE (first-class)."""
        block = expand_program_block(
            asset_id="ep7", asset_uri="/ep7.mp4",
            start_utc_ms=START_MS, slot_duration_ms=2_000_000,
            episode_duration_ms=1_800_000,
            chapter_markers_ms=(600_000, 1_200_000),
        )
        contents = [s for s in block.segments if s.segment_type == "content"]
        for seg in contents:
            assert seg.transition_out == "TRANSITION_NONE"

    def test_algorithmic_breaks_are_second_class(self):
        """Algorithmic breaks produce TRANSITION_FADE (second-class)."""
        block = expand_program_block(
            asset_id="ep8", asset_uri="/ep8.mp4",
            start_utc_ms=START_MS, slot_duration_ms=1_800_000,
            episode_duration_ms=1_320_000,
        )
        contents = [s for s in block.segments if s.segment_type == "content"]
        # Non-final content segments at algorithmic breaks should have TRANSITION_FADE
        for seg in contents[:-1]:
            assert seg.transition_out == "TRANSITION_FADE"
