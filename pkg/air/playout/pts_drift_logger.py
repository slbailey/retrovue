"""
INV-FIVS-PTS-CONSISTENCY: Rate-limited PTS slope drift logging.

Contract: pkg/air/docs/contracts/playout/INV-FIVS-PTS-CONSISTENCY.md

DEPRECATED: The authoritative enforcement is in C++ (PipelineManager.cpp).
This Python module exists as a reference implementation for testing the
slope-based contract. It is NOT called in the production emission path.

Wraps the PTSSlopeValidator with:
  - Rate limiting: max 1 PTS_DRIFT_DETECTED per second per asset
  - Segment boundary reset: clears slope state when segment changes
  - Emission-path integration: validate → log (if drift) → emit (always)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from .pts_validator import PTSSlopeDriftEvent, PTSSlopeValidator

logger = logging.getLogger("retrovue.air.playout")


class PTSDriftLogger:
    """Rate-limited PTS slope drift diagnostic logger.

    Wraps PTSSlopeValidator with:
      - Per-asset rate limiting (max 1 log per second)
      - Segment boundary detection (reset on segment_id change)

    Thread safety: not internally synchronized. Intended for single-thread
    use from the tick loop.
    """

    def __init__(
        self,
        clock: Callable[[], float] | None = None,
        slope_window: int = 24,
    ) -> None:
        """
        Args:
            clock: Optional monotonic clock function returning seconds.
                   Defaults to time.monotonic. Injectable for testing.
            slope_window: Number of initial deltas to establish slope.
        """
        self._clock = clock or time.monotonic
        self._last_log_time: dict[str, float] = {}
        self._validator = PTSSlopeValidator(slope_window=slope_window)
        self._last_segment_id: int | None = None

    def validate_and_log(
        self,
        frame,
        segment_id: int = -1,
        asset_uri: str = "",
        emit_fn: Callable | None = None,
    ) -> tuple[Any, PTSSlopeDriftEvent | None]:
        """Validate PTS slope, log drift if rate limit allows, emit frame always.

        Args:
            frame: Frame object with pts_us and was_decoded attributes.
            segment_id: Segment origin ID. Change triggers slope reset.
            asset_uri: Source asset URI for diagnostic correlation.
            emit_fn: Optional emission callback. Called with the frame
                     after validation. Frame is always emitted.

        Returns:
            (frame, drift_event_or_none).
        """
        # Segment boundary detection: reset slope on segment change.
        if segment_id >= 0 and self._last_segment_id is not None and segment_id != self._last_segment_id:
            self._validator.reset()
            self._last_log_time.clear()
        if segment_id >= 0:
            self._last_segment_id = segment_id

        # Only validate real decodes (skip cadence repeats).
        drift_event = None
        if getattr(frame, 'was_decoded', True):
            drift_event = self._validator.validate(
                frame.pts_us, asset_uri=asset_uri
            )

        # Rate-limited logging.
        if drift_event is not None:
            now = self._clock()
            key = asset_uri or ""
            last = self._last_log_time.get(key)
            if last is None or (now - last) >= 1.0:
                self._last_log_time[key] = now
                logger.warning(
                    "PTS_DRIFT_DETECTED "
                    "actual_delta_us=%d established_delta_us=%d "
                    "deviation_us=%d prev_pts_us=%d actual_pts_us=%d "
                    "asset_uri=%s",
                    drift_event.actual_delta_us,
                    drift_event.established_delta_us,
                    drift_event.deviation_us,
                    drift_event.prev_pts_us,
                    drift_event.actual_pts_us,
                    drift_event.asset_uri,
                )

        # Emission: frame is ALWAYS emitted regardless of drift.
        if emit_fn is not None:
            emit_fn(frame)

        return frame, drift_event

    def reset(self) -> None:
        """Clear all state (e.g. on session reset)."""
        self._validator.reset()
        self._last_log_time.clear()
        self._last_segment_id = None
