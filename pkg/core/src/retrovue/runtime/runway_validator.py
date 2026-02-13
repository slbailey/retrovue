"""
Runway readiness validation utilities.

Enforces RunwayReadinessContract v0.1 invariants:
- INV-RUNWAY-001 (runway sufficiency)
- INV-RUNWAY-002 (no fence without ready successor)

Pure validation. No execution behavior. No Horizon dependency. No AIR dependency.
See: docs/contracts/core/RunwayReadinessContract_v0.1.md
"""

from __future__ import annotations

from dataclasses import dataclass


class RunwayReadinessError(Exception):
    """Raised when runway readiness invariants are violated."""


@dataclass(frozen=True)
class SegmentPlan:
    """One planned segment within a block."""

    segment_type: str
    segment_duration_ms: int
    runtime_recovery: bool = False


@dataclass(frozen=True)
class BlockPlan:
    """A queued block with ordered segments."""

    block_id: str
    start_utc_ms: int
    end_utc_ms: int
    segments: tuple[SegmentPlan, ...]


def _is_recovery(segment: SegmentPlan) -> bool:
    """Recovery: segment_type == 'pad' AND runtime_recovery is True."""
    return segment.segment_type == "pad" and segment.runtime_recovery


def compute_runway_ms(
    block_queue: list[BlockPlan],
    current_position_ms: int,
) -> int:
    """Compute cumulative non-recovery runway (ms) ahead of current playhead.

    Walks the block queue forward from current_position_ms.
    Sums segment durations for non-recovery segments only.
    All queued blocks are treated as READY.
    """
    runway_ms = 0

    for block in block_queue:
        if block.end_utc_ms <= current_position_ms:
            continue

        if block.start_utc_ms >= current_position_ms:
            for seg in block.segments:
                if not _is_recovery(seg):
                    runway_ms += seg.segment_duration_ms
        else:
            elapsed = current_position_ms - block.start_utc_ms
            cursor = 0
            for seg in block.segments:
                seg_end = cursor + seg.segment_duration_ms
                if seg_end <= elapsed:
                    cursor = seg_end
                    continue
                remaining = seg.segment_duration_ms - max(0, elapsed - cursor)
                if not _is_recovery(seg):
                    runway_ms += remaining
                cursor = seg_end

    return runway_ms


def validate_runway(
    runway_ms: int,
    preload_budget_ms: int,
) -> None:
    """INV-RUNWAY-001: runway_ms must be >= preload_budget_ms.

    Raises RunwayReadinessError if runway is insufficient.
    """
    if runway_ms < preload_budget_ms:
        raise RunwayReadinessError(
            f"INV-RUNWAY-001 violated: runway {runway_ms} ms < "
            f"preload_budget {preload_budget_ms} ms"
        )


def validate_fence_readiness(
    block_queue: list[BlockPlan],
    current_position_ms: int,
    successor_ready: bool = True,
    successor_is_recovery: bool = False,
) -> None:
    """INV-RUNWAY-002: At fence boundaries, the successor must be READY.

    All queued blocks are treated as READY, so internal fences are satisfied.
    The terminal fence (end of queue) is validated via successor_ready.

    If successor_ready is False and successor_is_recovery is False,
    raises RunwayReadinessError.
    """
    ahead = [b for b in block_queue if b.end_utc_ms > current_position_ms]

    if not ahead:
        if not successor_ready and not successor_is_recovery:
            raise RunwayReadinessError(
                "INV-RUNWAY-002 violated: no queued blocks ahead of playhead "
                "and no ready successor"
            )
        return

    if not successor_ready and not successor_is_recovery:
        raise RunwayReadinessError(
            "INV-RUNWAY-002 violated: terminal fence at block "
            f"{ahead[-1].block_id!r} has no ready successor"
        )
