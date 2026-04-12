"""Input timing classification and cadence eligibility.

Public API:
    classify_frame_timing   — CFR/VFR/INDETERMINATE from PTS deltas
    select_resample_mode    — CADENCE or CLOCK_DRIVEN based on classification
    enforce_cadence_eligibility — hard rejection of CADENCE for VFR
    clock_driven_frame_select  — output-clock-authoritative frame picker

    FrameRateClass          — CFR / VFR / INDETERMINATE enum
    ResampleMode            — CADENCE / CLOCK_DRIVEN enum
    ClassificationResult    — classification output dataclass
    CadenceVFRViolation     — exception for illegal CADENCE usage

    SegmentPlayoutLifecycle  — lifecycle orchestrator with classification gate
    OutputBeforeClassificationError — output attempted before classification
    ClassificationImmutableError    — classification overwrite after output
"""

from retrovue.playout.timing.classifier import (
    ClassificationResult,
    FrameRateClass,
    classify_frame_timing,
)
from retrovue.playout.timing.clocking import clock_driven_frame_select
from retrovue.playout.timing.exceptions import CadenceVFRViolation
from retrovue.playout.timing.mode_selection import (
    ResampleMode,
    enforce_cadence_eligibility,
    select_resample_mode,
)

from retrovue.playout.timing.lifecycle import (
    ClassificationImmutableError,
    OutputBeforeClassificationError,
    SegmentPlayoutLifecycle,
)

__all__ = [
    "ClassificationResult",
    "FrameRateClass",
    "ResampleMode",
    "CadenceVFRViolation",
    "OutputBeforeClassificationError",
    "ClassificationImmutableError",
    "SegmentPlayoutLifecycle",
    "classify_frame_timing",
    "select_resample_mode",
    "enforce_cadence_eligibility",
    "clock_driven_frame_select",
]
