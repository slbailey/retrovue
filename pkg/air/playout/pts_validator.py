"""
INV-FIVS-PTS-CONSISTENCY: PTS slope consistency validator (Python reference).

Contract: pkg/air/docs/contracts/playout/INV-FIVS-PTS-CONSISTENCY.md

DEPRECATED: The authoritative enforcement of INV-FIVS-PTS-CONSISTENCY is in
C++ (PipelineManager.cpp, FIVS hit path). This Python module exists as a
reference implementation for contract tests. It is NOT called in the
production emission path.

The old formulation (expected_pts = source_frame_index × frame_duration)
produced false positives on telecine and VFR sources. The current contract
uses PTS slope consistency: establish the average PTS delta from the first
N decoded frames, then check subsequent deltas against that slope.
"""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass
class PTSSlopeDriftEvent:
    """Diagnostic event emitted when a PTS delta deviates from established slope."""
    actual_delta_us: int
    established_delta_us: int
    deviation_us: int
    prev_pts_us: int
    actual_pts_us: int
    asset_uri: str = ""


class PTSSlopeValidator:
    """Stateful PTS slope consistency validator.

    Mirrors the C++ implementation in PipelineManager.cpp:
      1. Accumulation phase: gather first `slope_window` PTS deltas.
      2. Checking phase: verify each subsequent delta is within ±50%
         of the established (average) delta.
      3. Segment boundary: reset all state when segment changes.

    Only frames with was_decoded=True should be passed to validate().
    Cadence repeats (was_decoded=False) must be filtered by the caller.
    """

    def __init__(self, slope_window: int = 24) -> None:
        self._slope_window = slope_window
        self.reset()

    def reset(self) -> None:
        """Clear all slope state (e.g. on segment boundary)."""
        self._prev_pts_us: int | None = None
        self._established_delta_us: int | None = None
        self._slope_sum_us: int = 0
        self._slope_count: int = 0

    def validate(
        self,
        pts_us: int,
        asset_uri: str = "",
    ) -> PTSSlopeDriftEvent | None:
        """Validate a single decoded frame's PTS against the established slope.

        Args:
            pts_us: PTS of the current decoded frame in microseconds.
            asset_uri: Source asset URI for diagnostic correlation.

        Returns:
            None if PTS is consistent (or still in accumulation phase).
            PTSSlopeDriftEvent if the delta deviates from established slope.
        """
        if self._prev_pts_us is None:
            self._prev_pts_us = pts_us
            return None

        delta = pts_us - self._prev_pts_us
        prev = self._prev_pts_us
        self._prev_pts_us = pts_us

        if self._slope_count < self._slope_window:
            # Accumulation phase.
            self._slope_sum_us += delta
            self._slope_count += 1
            if self._slope_count == self._slope_window:
                self._established_delta_us = self._slope_sum_us // self._slope_window
            return None

        # Checking phase.
        assert self._established_delta_us is not None
        tolerance = self._established_delta_us // 2
        deviation = delta - self._established_delta_us
        if abs(deviation) > tolerance:
            return PTSSlopeDriftEvent(
                actual_delta_us=delta,
                established_delta_us=self._established_delta_us,
                deviation_us=deviation,
                prev_pts_us=prev,
                actual_pts_us=pts_us,
                asset_uri=asset_uri,
            )
        return None


# ---------------------------------------------------------------------------
# Deprecated: old index-based formulation. Kept only for backward compat
# with any code that imports these names. Do NOT use in new code.
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class PTSDriftEvent:
    """DEPRECATED: Use PTSSlopeDriftEvent instead."""
    source_frame_index: int
    actual_pts_us: int
    expected_pts_us: int
    drift_us: int
    frame_duration_us: int
    asset_uri: str = ""


def validate_pts_consistency(
    frame,
    frame_duration_us: int,
    asset_uri: str = "",
) -> tuple:
    """DEPRECATED: Old index-based PTS validation.

    This function implements the old formulation:
        expected_pts = source_frame_index × frame_duration_us
    which produces false positives on telecine and VFR sources.

    Kept for backward compatibility. The authoritative check is the
    slope-based validator (PTSSlopeValidator) and its C++ counterpart.

    The frame is always returned. Playback is never blocked.
    """
    expected_pts = frame.source_frame_index * frame_duration_us
    drift = frame.pts_us - expected_pts
    tolerance = frame_duration_us // 2

    if abs(drift) <= tolerance:
        return frame, None

    return frame, PTSDriftEvent(
        source_frame_index=frame.source_frame_index,
        actual_pts_us=frame.pts_us,
        expected_pts_us=expected_pts,
        drift_us=drift,
        frame_duration_us=frame_duration_us,
        asset_uri=asset_uri,
    )
