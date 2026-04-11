"""Input frame timing classifier.

INV-CADENCE-STABILITY-OBSERVED-001: Classification is derived from
measured PTS deltas of decoded frames, not container metadata.

INV-CADENCE-CLASSIFICATION-BEFORE-MODE-001: Classification must complete
during the segment prime phase before any output frame is committed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from retrovue.playout.timing.mode_selection import ResampleMode


class FrameRateClass(Enum):
    """Classification of input frame timing stability."""
    CFR = "cfr"
    VFR = "vfr"
    INDETERMINATE = "indeterminate"


@dataclass
class ContainerMetadata:
    """Container-reported (untrusted) frame rate metadata.

    INV-CADENCE-STABILITY-OBSERVED-001: These values MUST NOT be the
    sole basis for classification. Passed for logging/diagnostics only.
    """
    r_frame_rate_num: int = 24000
    r_frame_rate_den: int = 1001
    avg_frame_rate_num: int = 24000
    avg_frame_rate_den: int = 1001


@dataclass
class ClassificationResult:
    """Output of the frame timing stability classifier."""
    frame_rate_class: FrameRateClass
    nominal_interval_us: int           # Median observed interval (microseconds)
    variance_us: float                 # Variance of observed intervals
    cumulative_drift_us: float         # Sum of per-frame deviations from nominal
    observation_frames: int            # Number of frames in the window
    selected_mode: ResampleMode        # Mode selected based on classification


# Tuning constants — conceptual thresholds per contract §Stability Criteria.
# These may be refined as empirical data accumulates.
_DEFAULT_OBSERVATION_WINDOW = 48       # ~2 seconds at 24fps
_VARIANCE_THRESHOLD_US = 500.0         # Acceptable interval variance (μs²)
_CUMULATIVE_DRIFT_THRESHOLD_US = 5000  # Max cumulative drift in window (μs)
_MIN_FRAMES_FOR_CLASSIFICATION = 12    # Below this → indeterminate


def classify_frame_timing(
    pts_deltas_us: List[int],
    container_metadata: Optional[ContainerMetadata] = None,
    output_fps_num: int = 30000,
    output_fps_den: int = 1001,
) -> ClassificationResult:
    """Classify input frame timing stability from observed PTS deltas.

    INV-CADENCE-STABILITY-OBSERVED-001: Classification uses measured PTS
    deltas only. Container metadata is accepted but ignored for classification.

    INV-CADENCE-JITTER-ACCUMULATION-001: Both per-frame variance AND
    cumulative drift are evaluated. Either exceeding threshold → VFR.

    INV-CADENCE-CLASSIFICATION-BEFORE-MODE-001: This function accepts a
    bounded list of deltas from the prime window, not a live stream.

    Args:
        pts_deltas_us: Consecutive frame PTS deltas in microseconds.
        container_metadata: Container-reported fps (ignored for classification).
        output_fps_num: Output frame rate numerator.
        output_fps_den: Output frame rate denominator.

    Returns:
        ClassificationResult with frame_rate_class and selected_mode.
    """
    n = len(pts_deltas_us)

    if n < _MIN_FRAMES_FOR_CLASSIFICATION:
        return ClassificationResult(
            frame_rate_class=FrameRateClass.INDETERMINATE,
            nominal_interval_us=0,
            variance_us=0.0,
            cumulative_drift_us=0.0,
            observation_frames=n,
            selected_mode=ResampleMode.CLOCK_DRIVEN,
        )

    # Nominal from observed median (not container metadata).
    sorted_deltas = sorted(pts_deltas_us)
    nominal_us = sorted_deltas[n // 2]

    # Variance and cumulative drift.
    deviations = [d - nominal_us for d in pts_deltas_us]
    variance = sum(dev * dev for dev in deviations) / n
    cumulative_drift = sum(deviations)

    is_stable = (
        variance <= _VARIANCE_THRESHOLD_US
        and abs(cumulative_drift) <= _CUMULATIVE_DRIFT_THRESHOLD_US
    )

    frame_rate_class = FrameRateClass.CFR if is_stable else FrameRateClass.VFR

    # Mode selection.
    if frame_rate_class == FrameRateClass.CFR:
        source_fps_approx = 1_000_000 / nominal_us if nominal_us > 0 else 0
        output_fps_approx = output_fps_num / output_fps_den
        if abs(source_fps_approx - output_fps_approx) > 0.5:
            selected_mode = ResampleMode.CADENCE
        else:
            selected_mode = ResampleMode.CLOCK_DRIVEN
    else:
        selected_mode = ResampleMode.CLOCK_DRIVEN

    return ClassificationResult(
        frame_rate_class=frame_rate_class,
        nominal_interval_us=nominal_us,
        variance_us=variance,
        cumulative_drift_us=cumulative_drift,
        observation_frames=n,
        selected_mode=selected_mode,
    )
