"""Segment playout lifecycle with timing classification integration.

INV-TIMING-CLASSIFICATION-LIFECYCLE-001: Classification during prime.
INV-TIMING-CLASSIFICATION-LIFECYCLE-002: Complete before output.
INV-TIMING-CLASSIFICATION-LIFECYCLE-003: No mid-playback reclassification.
INV-TIMING-CLASSIFICATION-IMMUTABLE-001: Immutable within segment.
INV-TIMING-CLASSIFICATION-SCOPED-001: Segment-scoped, no carryover.
INV-TIMING-CLASSIFICATION-GATE-001: No output without classification.
INV-TIMING-CLASSIFICATION-GATE-002: No bypass of classification gate.
"""

from __future__ import annotations

from typing import Callable, List, Optional

from retrovue.playout.timing.classifier import (
    ClassificationResult,
    FrameRateClass,
    classify_frame_timing,
)
from retrovue.playout.timing.exceptions import CadenceVFRViolation
from retrovue.playout.timing.mode_selection import ResampleMode


class OutputBeforeClassificationError(Exception):
    """Raised when output is attempted before classification completes."""


class ClassificationImmutableError(Exception):
    """Raised when classification is overwritten after output has begun."""


class SegmentPlayoutLifecycle:
    """Orchestrates timing classification within a single segment's lifecycle.

    Enforces the contract's data flow:
        decoder open → prime → collect PTS → classify → select mode →
        enforce → store → activate output → emit frames

    Each instance represents one segment. Create a new instance for each
    segment to enforce INV-TIMING-CLASSIFICATION-SCOPED-001.
    """

    def __init__(
        self,
        classifier: Callable[[List[int]], ClassificationResult] = classify_frame_timing,
    ):
        self._classifier = classifier
        self._classification: Optional[ClassificationResult] = None
        self._output_started = False
        self._prime_complete = False
        self._frames_emitted: int = 0
        self._prime_pts_deltas: List[int] = []

    # --- Prime phase ---

    def decode_prime_frame(self, pts_delta_us: int) -> None:
        """Record a PTS delta from a decoded frame during prime."""
        if self._output_started:
            raise RuntimeError("Cannot prime after output has started")
        self._prime_pts_deltas.append(pts_delta_us)

    def complete_prime(self) -> None:
        """Run classification on collected PTS deltas and store result.

        INV-TIMING-CLASSIFICATION-LIFECYCLE-001: Classification during prime.
        INV-TIMING-CLASSIFICATION-LIFECYCLE-002: Completes before output.
        """
        if self._prime_complete:
            return
        try:
            self._classification = self._classifier(self._prime_pts_deltas)
        except Exception:
            self._classification = ClassificationResult(
                frame_rate_class=FrameRateClass.INDETERMINATE,
                nominal_interval_us=0,
                variance_us=0.0,
                cumulative_drift_us=0.0,
                observation_frames=0,
                selected_mode=ResampleMode.CLOCK_DRIVEN,
            )
        self._prime_complete = True

    # --- Classification access ---

    @property
    def classification(self) -> Optional[ClassificationResult]:
        return self._classification

    @property
    def is_classified(self) -> bool:
        return self._classification is not None

    @property
    def selected_mode(self) -> Optional[ResampleMode]:
        if self._classification is None:
            return None
        return self._classification.selected_mode

    # --- Mode enforcement ---

    def activate_output(
        self, requested_mode: Optional[ResampleMode] = None,
    ) -> ResampleMode:
        """Activate output clock with the classified mode.

        INV-TIMING-CLASSIFICATION-GATE-001: No output without classification.
        INV-TIMING-CLASSIFICATION-GATE-002: No CADENCE bypass.
        """
        if self._classification is None:
            raise OutputBeforeClassificationError(
                "Output activation rejected: classification not complete"
            )
        mode = requested_mode or self._classification.selected_mode
        if mode == ResampleMode.CADENCE:
            if self._classification.frame_rate_class != FrameRateClass.CFR:
                raise CadenceVFRViolation(
                    f"CADENCE rejected: classification is "
                    f"{self._classification.frame_rate_class.value}"
                )
        self._output_started = True
        return mode

    # --- Output ---

    def emit_frame(self) -> None:
        """Emit an output frame.

        INV-TIMING-CLASSIFICATION-GATE-001: Blocked without classification.
        """
        if not self._output_started:
            raise OutputBeforeClassificationError(
                "Cannot emit frame: output not activated"
            )
        self._frames_emitted += 1

    @property
    def frames_emitted(self) -> int:
        return self._frames_emitted

    # --- Immutability ---

    def overwrite_classification(
        self, new_result: ClassificationResult,
    ) -> None:
        """Attempt to overwrite classification.

        INV-TIMING-CLASSIFICATION-IMMUTABLE-001: Rejected after output starts.
        """
        if self._output_started:
            raise ClassificationImmutableError(
                "Classification cannot be changed after output has started"
            )
        self._classification = new_result
