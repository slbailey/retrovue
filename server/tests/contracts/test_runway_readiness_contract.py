"""
Contract Tests — Runway Readiness Contract

Tests assert runway readiness invariants from
docs/contracts/core/RunwayReadinessContract_v0.1.md.
Uses synthetic BlockPlan objects. No Horizon, no AIR, no pipeline.
"""

from __future__ import annotations

import pytest

from retrovue.runtime.runway_validator import (
    BlockPlan,
    RunwayReadinessError,
    SegmentPlan,
    compute_runway_ms,
    validate_fence_readiness,
    validate_runway,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FRAME_DURATION_MS = 33  # ~30 fps


def _content_segment(duration_ms: int) -> SegmentPlan:
    return SegmentPlan(
        segment_type="content",
        segment_duration_ms=duration_ms,
    )


def _pad_segment(duration_ms: int, recovery: bool = False) -> SegmentPlan:
    return SegmentPlan(
        segment_type="pad",
        segment_duration_ms=duration_ms,
        runtime_recovery=recovery,
    )


def _block(
    block_id: str,
    start_ms: int,
    segments: tuple[SegmentPlan, ...],
) -> BlockPlan:
    total = sum(s.segment_duration_ms for s in segments)
    return BlockPlan(
        block_id=block_id,
        start_utc_ms=start_ms,
        end_utc_ms=start_ms + total,
        segments=segments,
    )


# ---------------------------------------------------------------------------
# INV-RUNWAY-001 — Sufficient runway
# ---------------------------------------------------------------------------


def test_sufficient_runway():
    """INV-RUNWAY-001: Runway >= preload_budget → no error."""
    block = _block("b1", 0, (
        _content_segment(10_000),
        _content_segment(5_000),
    ))
    runway = compute_runway_ms([block], current_position_ms=0)
    assert runway == 15_000
    validate_runway(runway, preload_budget_ms=10_000)


# ---------------------------------------------------------------------------
# INV-RUNWAY-001 — Insufficient runway
# ---------------------------------------------------------------------------


def test_insufficient_runway():
    """INV-RUNWAY-001: Runway < preload_budget → RunwayReadinessError."""
    block = _block("b1", 0, (
        _content_segment(3_000),
    ))
    runway = compute_runway_ms([block], current_position_ms=0)
    assert runway == 3_000
    with pytest.raises(RunwayReadinessError, match="INV-RUNWAY-001"):
        validate_runway(runway, preload_budget_ms=10_000)


# ---------------------------------------------------------------------------
# INV-RUNWAY-002 — Micro PAD (2-frame) followed by non-ready successor
# ---------------------------------------------------------------------------


def test_micro_pad_no_ready_successor():
    """INV-RUNWAY-002: Micro PAD at terminal fence with no ready successor → error."""
    micro_pad_ms = FRAME_DURATION_MS * 2  # 2-frame PAD
    block = _block("b1", 0, (
        _content_segment(10_000),
        _pad_segment(micro_pad_ms),
    ))
    with pytest.raises(RunwayReadinessError, match="INV-RUNWAY-002"):
        validate_fence_readiness(
            [block],
            current_position_ms=0,
            successor_ready=False,
        )


# ---------------------------------------------------------------------------
# Recovery segment allowed
# ---------------------------------------------------------------------------


def test_recovery_segment_allowed():
    """Recovery segments excluded from runway; do not violate fence readiness."""
    recovery = _pad_segment(5_000, recovery=True)
    content = _content_segment(10_000)
    block = _block("b1", 0, (content, recovery))

    # Recovery excluded from runway computation
    runway = compute_runway_ms([block], current_position_ms=0)
    assert runway == 10_000

    # Runway sufficient (only non-recovery content counted)
    validate_runway(runway, preload_budget_ms=10_000)

    # Fence: successor is recovery → exempt from INV-RUNWAY-002
    validate_fence_readiness(
        [block],
        current_position_ms=0,
        successor_ready=False,
        successor_is_recovery=True,
    )
