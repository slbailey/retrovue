"""Resample mode selection and cadence eligibility enforcement.

INV-CADENCE-INPUT-CFR-REQUIRED-001: CADENCE only for CFR.
INV-CADENCE-INPUT-VFR-FORBIDDEN-001: CADENCE forbidden for VFR/INDETERMINATE.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from retrovue.playout.timing.exceptions import CadenceVFRViolation

if TYPE_CHECKING:
    from retrovue.playout.timing.classifier import ClassificationResult, FrameRateClass


class ResampleMode(Enum):
    """Resampling strategy for source→output frame rate conversion."""
    CADENCE = "cadence"        # Fixed repeat/drop pattern (CFR only)
    CLOCK_DRIVEN = "clock"     # Output-clock selects nearest frame (VFR safe)


def select_resample_mode(
    classification: "ClassificationResult",
) -> ResampleMode:
    """Select resampling mode based on classification.

    INV-CADENCE-INPUT-VFR-FORBIDDEN-001: CADENCE MUST NOT be returned
    for VFR or INDETERMINATE classifications.
    """
    from retrovue.playout.timing.classifier import FrameRateClass

    if classification.frame_rate_class == FrameRateClass.CFR:
        return classification.selected_mode
    return ResampleMode.CLOCK_DRIVEN


def enforce_cadence_eligibility(
    classification: "ClassificationResult",
    requested_mode: ResampleMode,
) -> ResampleMode:
    """Enforce cadence eligibility with hard rejection.

    INV-CADENCE-INPUT-VFR-FORBIDDEN-001: Attempting to force CADENCE
    on a VFR or INDETERMINATE classification MUST raise CadenceVFRViolation.

    Returns the requested mode if legal for the classification.
    """
    from retrovue.playout.timing.classifier import FrameRateClass

    if requested_mode == ResampleMode.CADENCE:
        if classification.frame_rate_class != FrameRateClass.CFR:
            raise CadenceVFRViolation(
                f"CADENCE mode rejected: input classified as "
                f"{classification.frame_rate_class.value} "
                f"(variance={classification.variance_us:.0f}us, "
                f"drift={classification.cumulative_drift_us:.0f}us)"
            )
    return requested_mode
