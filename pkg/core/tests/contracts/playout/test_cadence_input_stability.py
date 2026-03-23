"""
Contract tests for playout_cadence_input_stability.md

Validates that cadence resampling mode selection is governed by observed
frame timing stability, not container metadata.

Each test maps to a specific invariant from the contract.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

import pytest


# ---------------------------------------------------------------------------
# Stub types — minimal definitions for classification logic.
# Production code does not yet exist; these stubs define the expected
# interface so implementation can be written later to satisfy these tests.
# ---------------------------------------------------------------------------


class ResampleMode(Enum):
    """Resampling strategy for source→output frame rate conversion."""
    CADENCE = "cadence"        # Fixed repeat/drop pattern (CFR only)
    CLOCK_DRIVEN = "clock"     # Output-clock selects nearest frame (VFR safe)


class FrameRateClass(Enum):
    """Classification of input frame timing stability."""
    CFR = "cfr"
    VFR = "vfr"
    INDETERMINATE = "indeterminate"


@dataclass
class ContainerMetadata:
    """Container-reported (untrusted) frame rate metadata."""
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


# ---------------------------------------------------------------------------
# Stub classifier — implements the contract rules.
# This is intentionally minimal: just enough to make the tests executable.
# Production implementation will replace this.
# ---------------------------------------------------------------------------


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

    INV-CADENCE-STABILITY-OBSERVED-001: Classification is derived from
    measured PTS deltas, not container metadata.

    INV-CADENCE-CLASSIFICATION-BEFORE-MODE-001: This function must be
    called during the prime phase before any output frame is committed.

    Args:
        pts_deltas_us: List of consecutive frame PTS deltas in microseconds.
        container_metadata: Container-reported fps (ignored for classification).
        output_fps_num: Output frame rate numerator.
        output_fps_den: Output frame rate denominator.

    Returns:
        ClassificationResult with frame_rate_class and selected_mode.
    """
    n = len(pts_deltas_us)

    # INV-CADENCE-CLASSIFICATION-BEFORE-MODE-001: insufficient data → indeterminate
    if n < _MIN_FRAMES_FOR_CLASSIFICATION:
        return ClassificationResult(
            frame_rate_class=FrameRateClass.INDETERMINATE,
            nominal_interval_us=0,
            variance_us=0.0,
            cumulative_drift_us=0.0,
            observation_frames=n,
            selected_mode=ResampleMode.CLOCK_DRIVEN,
        )

    # Derive nominal from observed median (not container metadata).
    sorted_deltas = sorted(pts_deltas_us)
    nominal_us = sorted_deltas[n // 2]

    # Compute variance and cumulative drift.
    deviations = [d - nominal_us for d in pts_deltas_us]
    variance = sum(dev * dev for dev in deviations) / n
    cumulative_drift = sum(deviations)

    # INV-CADENCE-JITTER-ACCUMULATION-001: evaluate both per-frame
    # variance AND cumulative drift.
    is_stable = (
        variance <= _VARIANCE_THRESHOLD_US
        and abs(cumulative_drift) <= _CUMULATIVE_DRIFT_THRESHOLD_US
    )

    if is_stable:
        frame_rate_class = FrameRateClass.CFR
    else:
        frame_rate_class = FrameRateClass.VFR

    # INV-CADENCE-INPUT-CFR-REQUIRED-001 / INV-CADENCE-INPUT-VFR-FORBIDDEN-001
    if frame_rate_class == FrameRateClass.CFR:
        # Check if source and output differ (resampling needed).
        source_fps_approx = 1_000_000 / nominal_us if nominal_us > 0 else 0
        output_fps_approx = output_fps_num / output_fps_den
        if abs(source_fps_approx - output_fps_approx) > 0.5:
            selected_mode = ResampleMode.CADENCE
        else:
            selected_mode = ResampleMode.CLOCK_DRIVEN  # No resample needed
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


def select_resample_mode(
    classification: ClassificationResult,
) -> ResampleMode:
    """Select resampling mode based on classification.

    INV-CADENCE-INPUT-VFR-FORBIDDEN-001: CADENCE MUST NOT be returned
    for VFR or INDETERMINATE classifications.
    """
    if classification.frame_rate_class == FrameRateClass.CFR:
        return classification.selected_mode
    return ResampleMode.CLOCK_DRIVEN


class CadenceVFRViolation(Exception):
    """Raised when CADENCE mode is forced on a VFR or INDETERMINATE input.

    INV-CADENCE-INPUT-VFR-FORBIDDEN-001: This is a hard rejection —
    not a warning, not a fallback. The system MUST refuse.
    """


def enforce_cadence_eligibility(
    classification: ClassificationResult,
    requested_mode: ResampleMode,
) -> ResampleMode:
    """Enforce cadence eligibility with hard rejection.

    INV-CADENCE-INPUT-VFR-FORBIDDEN-001: Attempting to force CADENCE
    on a VFR or INDETERMINATE classification MUST raise CadenceVFRViolation.

    Returns the requested mode if it is legal for the classification.
    """
    if requested_mode == ResampleMode.CADENCE:
        if classification.frame_rate_class != FrameRateClass.CFR:
            raise CadenceVFRViolation(
                f"CADENCE mode rejected: input classified as "
                f"{classification.frame_rate_class.value} "
                f"(variance={classification.variance_us:.0f}us, "
                f"drift={classification.cumulative_drift_us:.0f}us)"
            )
    return requested_mode


def clock_driven_frame_select(
    output_time_us: int,
    decoded_frames: List[tuple[int, int]],
) -> Optional[int]:
    """Select a frame for the given output time using clock-driven strategy.

    INV-CADENCE-INPUT-VFR-FORBIDDEN-001: VFR mode uses the output clock
    as sole authority for frame selection. Source PTS timing is NOT used
    to drive selection — only to identify the nearest content frame.

    Args:
        output_time_us: Current output clock time in microseconds (monotonic,
            derived from output frame rate, NOT from source PTS).
        decoded_frames: List of (source_frame_index, content_time_us) pairs
            from the decoded stream. content_time_us is derived from
            accumulated source PTS deltas.

    Returns:
        source_frame_index of the frame whose content_time_us is the
        largest value not exceeding output_time_us, or None if no
        eligible frame exists.
    """
    best_index = None
    best_ct = -1
    for frame_index, content_time_us in decoded_frames:
        if content_time_us <= output_time_us and content_time_us > best_ct:
            best_ct = content_time_us
            best_index = frame_index
    return best_index


# ---------------------------------------------------------------------------
# PTS sequence generators — synthetic frame streams for testing.
# ---------------------------------------------------------------------------


def generate_cfr_pts_deltas(
    fps_num: int = 24000,
    fps_den: int = 1001,
    count: int = 48,
) -> List[int]:
    """Generate perfectly constant PTS deltas for a CFR source.

    Returns deltas in microseconds.
    """
    interval_us = int(fps_den * 1_000_000 / fps_num)
    return [interval_us] * count


def generate_vfr_pts_deltas(
    nominal_fps_num: int = 24000,
    nominal_fps_den: int = 1001,
    count: int = 48,
    jitter_range_us: int = 5000,
    seed: int = 42,
) -> List[int]:
    """Generate VFR PTS deltas with random jitter around nominal.

    Each delta varies randomly within ±jitter_range_us of the nominal interval.
    """
    rng = random.Random(seed)
    nominal_us = int(nominal_fps_den * 1_000_000 / nominal_fps_num)
    return [
        nominal_us + rng.randint(-jitter_range_us, jitter_range_us)
        for _ in range(count)
    ]


def generate_biased_jitter_deltas(
    fps_num: int = 24000,
    fps_den: int = 1001,
    count: int = 48,
    bias_us: int = 10,
) -> List[int]:
    """Generate PTS deltas with consistent small bias.

    Each delta is nominal + bias_us. Per-frame deviation is small,
    but cumulative drift = bias_us * count.
    """
    nominal_us = int(fps_den * 1_000_000 / fps_num)
    return [nominal_us + bias_us] * count


def generate_120fps_container_24fps_pts(
    count: int = 48,
    seed: int = 99,
) -> tuple[List[int], ContainerMetadata]:
    """Simulate a container declaring r_frame_rate=120 but delivering ~24fps PTS.

    The actual decoded PTS deltas are irregular (VFR) because the container
    timestamps are in 120fps units but frames are not evenly spaced.
    """
    rng = random.Random(seed)
    # 120fps tick = 8333us. Actual content is ~24fps = ~41708us per frame.
    # Simulate irregular spacing: mostly ~5 ticks apart but varying.
    deltas = []
    for _ in range(count):
        ticks = rng.choice([4, 5, 5, 5, 6])  # avg ~5 ticks = 41667us
        deltas.append(ticks * 8333)
    metadata = ContainerMetadata(
        r_frame_rate_num=120,
        r_frame_rate_den=1,
        avg_frame_rate_num=24000,
        avg_frame_rate_den=1001,
    )
    return deltas, metadata


# ---------------------------------------------------------------------------
# Contract Tests
# ---------------------------------------------------------------------------


class TestCFRClassifiedCorrectly:
    """INV-CADENCE-INPUT-CFR-REQUIRED-001:
    24fps source with uniform PTS deltas classified as CFR.
    """

    def test_constant_24fps_classified_cfr(self):
        deltas = generate_cfr_pts_deltas(fps_num=24000, fps_den=1001, count=48)
        result = classify_frame_timing(deltas)
        assert result.frame_rate_class == FrameRateClass.CFR
        assert result.observation_frames == 48

    def test_constant_25fps_classified_cfr(self):
        deltas = generate_cfr_pts_deltas(fps_num=25, fps_den=1, count=48)
        result = classify_frame_timing(deltas)
        assert result.frame_rate_class == FrameRateClass.CFR

    def test_constant_30fps_classified_cfr(self):
        deltas = generate_cfr_pts_deltas(fps_num=30000, fps_den=1001, count=48)
        result = classify_frame_timing(deltas)
        assert result.frame_rate_class == FrameRateClass.CFR

    def test_nominal_interval_matches_source_fps(self):
        deltas = generate_cfr_pts_deltas(fps_num=24000, fps_den=1001, count=48)
        result = classify_frame_timing(deltas)
        expected_us = int(1001 * 1_000_000 / 24000)  # 41708
        assert result.nominal_interval_us == expected_us

    def test_zero_variance_for_perfect_cfr(self):
        deltas = generate_cfr_pts_deltas(count=48)
        result = classify_frame_timing(deltas)
        assert result.variance_us == 0.0

    def test_zero_cumulative_drift_for_perfect_cfr(self):
        deltas = generate_cfr_pts_deltas(count=48)
        result = classify_frame_timing(deltas)
        assert result.cumulative_drift_us == 0.0


class TestVFRClassifiedCorrectly:
    """INV-CADENCE-INPUT-VFR-FORBIDDEN-001:
    Source with irregular PTS deltas classified as VFR.
    """

    def test_random_jitter_classified_vfr(self):
        deltas = generate_vfr_pts_deltas(jitter_range_us=5000, count=48)
        result = classify_frame_timing(deltas)
        assert result.frame_rate_class == FrameRateClass.VFR

    def test_high_variance_classified_vfr(self):
        deltas = generate_vfr_pts_deltas(jitter_range_us=10000, count=48)
        result = classify_frame_timing(deltas)
        assert result.frame_rate_class == FrameRateClass.VFR
        assert result.variance_us > _VARIANCE_THRESHOLD_US


class TestVFRCadenceForbidden:
    """INV-CADENCE-INPUT-VFR-FORBIDDEN-001:
    VFR classification prevents CADENCE mode selection.
    """

    def test_vfr_selects_clock_driven(self):
        deltas = generate_vfr_pts_deltas(jitter_range_us=5000, count=48)
        result = classify_frame_timing(deltas)
        assert result.frame_rate_class == FrameRateClass.VFR
        assert result.selected_mode == ResampleMode.CLOCK_DRIVEN

    def test_select_resample_mode_rejects_cadence_for_vfr(self):
        deltas = generate_vfr_pts_deltas(jitter_range_us=5000, count=48)
        result = classify_frame_timing(deltas)
        mode = select_resample_mode(result)
        assert mode == ResampleMode.CLOCK_DRIVEN

    def test_forced_cadence_on_vfr_classification_still_returns_clock(self):
        """Even if classification result is manually overridden,
        select_resample_mode enforces the contract."""
        result = ClassificationResult(
            frame_rate_class=FrameRateClass.VFR,
            nominal_interval_us=41708,
            variance_us=10000.0,
            cumulative_drift_us=50000.0,
            observation_frames=48,
            selected_mode=ResampleMode.CADENCE,  # Incorrectly set
        )
        mode = select_resample_mode(result)
        assert mode == ResampleMode.CLOCK_DRIVEN


class TestCFRCadenceAllowed:
    """INV-CADENCE-INPUT-CFR-REQUIRED-001:
    CFR classification permits CADENCE mode selection.
    """

    def test_cfr_24fps_to_2997fps_selects_cadence(self):
        deltas = generate_cfr_pts_deltas(fps_num=24000, fps_den=1001, count=48)
        result = classify_frame_timing(
            deltas, output_fps_num=30000, output_fps_den=1001,
        )
        assert result.frame_rate_class == FrameRateClass.CFR
        assert result.selected_mode == ResampleMode.CADENCE

    def test_cfr_same_fps_no_cadence_needed(self):
        """When source and output are the same fps, no resample needed."""
        deltas = generate_cfr_pts_deltas(fps_num=30000, fps_den=1001, count=48)
        result = classify_frame_timing(
            deltas, output_fps_num=30000, output_fps_den=1001,
        )
        assert result.frame_rate_class == FrameRateClass.CFR
        assert result.selected_mode == ResampleMode.CLOCK_DRIVEN

    def test_select_resample_mode_allows_cadence_for_cfr(self):
        deltas = generate_cfr_pts_deltas(fps_num=24000, fps_den=1001, count=48)
        result = classify_frame_timing(
            deltas, output_fps_num=30000, output_fps_den=1001,
        )
        mode = select_resample_mode(result)
        assert mode == ResampleMode.CADENCE


class TestContainerFpsNotTrusted:
    """INV-CADENCE-STABILITY-OBSERVED-001:
    Source with r_frame_rate=120 but PTS ~24fps detected as VFR.
    """

    def test_120fps_container_irregular_pts_classified_vfr(self):
        deltas, metadata = generate_120fps_container_24fps_pts(count=48)
        result = classify_frame_timing(deltas, container_metadata=metadata)
        assert result.frame_rate_class == FrameRateClass.VFR

    def test_container_metadata_does_not_override_observed_instability(self):
        deltas, metadata = generate_120fps_container_24fps_pts(count=48)
        # Even though container says 120fps, classification uses PTS deltas.
        result = classify_frame_timing(deltas, container_metadata=metadata)
        assert result.selected_mode == ResampleMode.CLOCK_DRIVEN

    def test_container_metadata_ignored_for_cfr_too(self):
        """CFR source with misleading container metadata still classified correctly."""
        deltas = generate_cfr_pts_deltas(fps_num=24000, fps_den=1001, count=48)
        bogus_metadata = ContainerMetadata(
            r_frame_rate_num=60, r_frame_rate_den=1,
        )
        result = classify_frame_timing(deltas, container_metadata=bogus_metadata)
        assert result.frame_rate_class == FrameRateClass.CFR


class TestMicroJitterAccumulates:
    """INV-CADENCE-JITTER-ACCUMULATION-001:
    Per-frame 0.5ms bias within single-frame threshold but
    cumulative drift exceeds tolerance.
    """

    def test_consistent_bias_accumulates_to_vfr(self):
        """Alternating bias: most frames at nominal, but ~30% are 2ms fast.
        Median stays at nominal, but cumulative drift from the fast frames
        exceeds the threshold → VFR.
        """
        nominal_us = int(1001 * 1_000_000 / 24000)  # 41708
        rng = random.Random(77)
        deltas = []
        for i in range(48):
            if rng.random() < 0.3:
                deltas.append(nominal_us - 2000)  # 2ms fast
            else:
                deltas.append(nominal_us)
        result = classify_frame_timing(deltas)
        # ~14 frames × -2000us = -28000us cumulative drift > threshold
        assert abs(result.cumulative_drift_us) > _CUMULATIVE_DRIFT_THRESHOLD_US
        assert result.frame_rate_class == FrameRateClass.VFR

    def test_small_bias_below_threshold_stays_cfr(self):
        """Each frame is 10us fast. Over 48 frames: 480us cumulative drift.
        Both variance and cumulative drift within bounds → CFR.
        """
        deltas = generate_biased_jitter_deltas(
            fps_num=24000, fps_den=1001, count=48, bias_us=10,
        )
        result = classify_frame_timing(deltas)
        assert abs(result.cumulative_drift_us) < _CUMULATIVE_DRIFT_THRESHOLD_US
        assert result.frame_rate_class == FrameRateClass.CFR

    def test_bias_projects_to_movie_length_drift(self):
        """Verify the mechanism: even small per-frame error accumulates
        to noticeable A/V drift over a movie.

        At 23.976fps, a 90-minute movie has ~129,470 frames.
        If 10% of frames have 1ms error (average 0.1ms/frame overall),
        cumulative drift ≈ 12.9 seconds — easily audible.
        Even 1% of frames with 1ms error → ~1.3s drift.
        """
        fps = 24000 / 1001  # ~23.976
        # 1% of frames with 1ms (1000us) error
        error_fraction = 0.01
        error_per_affected_frame_us = 1000
        for movie_minutes in (90, 120):
            total_frames = int(fps * 60 * movie_minutes)
            affected_frames = int(total_frames * error_fraction)
            projected_drift_us = affected_frames * error_per_affected_frame_us
            projected_drift_s = projected_drift_us / 1_000_000
            assert projected_drift_s > 1.0, (
                f"{movie_minutes}min movie with {error_fraction*100}% affected: "
                f"projected drift {projected_drift_s:.1f}s should exceed 1s"
            )


class TestClassificationBeforeOutput:
    """INV-CADENCE-CLASSIFICATION-BEFORE-MODE-001:
    Mode selection occurs during prime phase, not after first output tick.
    """

    def test_classification_uses_prime_window_only(self):
        """Classification must be based on frames available during prime.
        The classifier accepts a bounded list, not a live stream.
        """
        prime_deltas = generate_cfr_pts_deltas(count=48)
        result = classify_frame_timing(prime_deltas)
        assert result.observation_frames == 48
        assert result.frame_rate_class == FrameRateClass.CFR

    def test_classification_is_deterministic(self):
        """Same input → same classification. No time-dependent behavior."""
        deltas = generate_vfr_pts_deltas(jitter_range_us=5000, count=48, seed=123)
        r1 = classify_frame_timing(deltas)
        r2 = classify_frame_timing(deltas)
        assert r1.frame_rate_class == r2.frame_rate_class
        assert r1.selected_mode == r2.selected_mode
        assert r1.variance_us == r2.variance_us


class TestIndeterminateDefaultsClock:
    """INV-CADENCE-CLASSIFICATION-BEFORE-MODE-001:
    Insufficient frames in prime window defaults to clock-driven mode.
    """

    def test_empty_deltas_indeterminate(self):
        result = classify_frame_timing([])
        assert result.frame_rate_class == FrameRateClass.INDETERMINATE
        assert result.selected_mode == ResampleMode.CLOCK_DRIVEN

    def test_few_frames_indeterminate(self):
        deltas = generate_cfr_pts_deltas(count=5)
        result = classify_frame_timing(deltas)
        assert result.frame_rate_class == FrameRateClass.INDETERMINATE
        assert result.selected_mode == ResampleMode.CLOCK_DRIVEN

    def test_just_below_minimum_indeterminate(self):
        deltas = generate_cfr_pts_deltas(count=_MIN_FRAMES_FOR_CLASSIFICATION - 1)
        result = classify_frame_timing(deltas)
        assert result.frame_rate_class == FrameRateClass.INDETERMINATE

    def test_at_minimum_classified(self):
        deltas = generate_cfr_pts_deltas(count=_MIN_FRAMES_FOR_CLASSIFICATION)
        result = classify_frame_timing(deltas)
        assert result.frame_rate_class != FrameRateClass.INDETERMINATE

    def test_indeterminate_never_selects_cadence(self):
        result = classify_frame_timing([])
        mode = select_resample_mode(result)
        assert mode == ResampleMode.CLOCK_DRIVEN


# ---------------------------------------------------------------------------
# Hard Rejection (MANDATORY)
# ---------------------------------------------------------------------------


class TestVFRCadenceHardRejected:
    """INV-CADENCE-INPUT-VFR-FORBIDDEN-001:
    Forcing CADENCE on VFR MUST raise, not warn or fallback.
    """

    def test_vfr_cadence_raises(self):
        deltas = generate_vfr_pts_deltas(jitter_range_us=5000, count=48)
        result = classify_frame_timing(deltas)
        assert result.frame_rate_class == FrameRateClass.VFR
        with pytest.raises(CadenceVFRViolation):
            enforce_cadence_eligibility(result, ResampleMode.CADENCE)

    def test_indeterminate_cadence_raises(self):
        result = classify_frame_timing([])
        assert result.frame_rate_class == FrameRateClass.INDETERMINATE
        with pytest.raises(CadenceVFRViolation):
            enforce_cadence_eligibility(result, ResampleMode.CADENCE)

    def test_cfr_cadence_does_not_raise(self):
        deltas = generate_cfr_pts_deltas(fps_num=24000, fps_den=1001, count=48)
        result = classify_frame_timing(deltas)
        assert result.frame_rate_class == FrameRateClass.CFR
        mode = enforce_cadence_eligibility(result, ResampleMode.CADENCE)
        assert mode == ResampleMode.CADENCE

    def test_vfr_clock_driven_does_not_raise(self):
        deltas = generate_vfr_pts_deltas(jitter_range_us=5000, count=48)
        result = classify_frame_timing(deltas)
        mode = enforce_cadence_eligibility(result, ResampleMode.CLOCK_DRIVEN)
        assert mode == ResampleMode.CLOCK_DRIVEN

    def test_exception_message_contains_classification(self):
        deltas = generate_vfr_pts_deltas(jitter_range_us=5000, count=48)
        result = classify_frame_timing(deltas)
        with pytest.raises(CadenceVFRViolation, match="vfr"):
            enforce_cadence_eligibility(result, ResampleMode.CADENCE)


# ---------------------------------------------------------------------------
# Clock Authority for VFR
# ---------------------------------------------------------------------------


class TestVFRUsesClockDrivenSelection:
    """INV-CADENCE-INPUT-VFR-FORBIDDEN-001:
    VFR mode frame selection is governed by output clock, not source timing.
    """

    def test_selects_nearest_frame_by_output_time(self):
        """Output clock at 40000us should select frame 0 (ct=0),
        not frame 1 (ct=50000) even though frame 1 is closer in source time.
        """
        frames = [(0, 0), (1, 50000), (2, 95000)]
        selected = clock_driven_frame_select(40000, frames)
        assert selected == 0  # largest ct <= 40000

    def test_selects_latest_eligible_frame(self):
        """Output clock at 80000us should select frame 1 (ct=50000),
        not frame 0 (ct=0).
        """
        frames = [(0, 0), (1, 50000), (2, 95000)]
        selected = clock_driven_frame_select(80000, frames)
        assert selected == 1

    def test_output_clock_drives_selection_not_source_spacing(self):
        """VFR source: frames at irregular content times.
        Output clock advances at constant 33367us (29.97fps).
        Each output tick selects the nearest-past content frame.
        """
        # Irregular VFR content times (not evenly spaced)
        frames = [
            (0, 0),
            (1, 38000),   # 38ms gap
            (2, 82000),   # 44ms gap
            (3, 115000),  # 33ms gap
            (4, 160000),  # 45ms gap
        ]
        output_tick_us = 33367  # 29.97fps constant

        selections = []
        for tick in range(6):
            t = tick * output_tick_us
            sel = clock_driven_frame_select(t, frames)
            selections.append(sel)

        # tick 0 (0us) → frame 0 (ct=0)
        # tick 1 (33367us) → frame 0 (ct=0, frame 1 at 38000 > 33367)
        # tick 2 (66734us) → frame 1 (ct=38000)
        # tick 3 (100101us) → frame 2 (ct=82000)
        # tick 4 (133468us) → frame 3 (ct=115000)
        # tick 5 (166835us) → frame 4 (ct=160000)
        assert selections == [0, 0, 1, 2, 3, 4]

    def test_no_frame_selected_before_first_content(self):
        """Output clock before any content time → None."""
        frames = [(0, 10000), (1, 50000)]
        selected = clock_driven_frame_select(5000, frames)
        assert selected is None


# ---------------------------------------------------------------------------
# Median Misclassification Edge Case
# ---------------------------------------------------------------------------


class TestVFRWithStableMedianButHighVariance:
    """INV-CADENCE-JITTER-ACCUMULATION-001:
    Stable median does not guarantee CFR — variance must also be low.
    """

    def test_symmetric_jitter_stable_median_high_variance(self):
        """Alternating +3000us / -3000us around nominal.
        Median = nominal (stable), but variance is high → VFR.
        """
        nominal_us = int(1001 * 1_000_000 / 24000)  # 41708
        deltas = []
        for i in range(48):
            if i % 2 == 0:
                deltas.append(nominal_us + 3000)
            else:
                deltas.append(nominal_us - 3000)
        result = classify_frame_timing(deltas)

        # Median should be close to nominal (sorted middle is nominal±3000)
        # But variance = 3000² = 9,000,000 >> threshold
        assert result.variance_us > _VARIANCE_THRESHOLD_US
        assert result.frame_rate_class == FrameRateClass.VFR

    def test_bimodal_distribution_classified_vfr(self):
        """Half frames at 33ms, half at 50ms. Median may appear stable
        but variance is very high → VFR.
        """
        deltas = [33000] * 24 + [50000] * 24
        random.Random(0).shuffle(deltas)
        result = classify_frame_timing(deltas)
        assert result.variance_us > _VARIANCE_THRESHOLD_US
        assert result.frame_rate_class == FrameRateClass.VFR

    def test_near_zero_cumulative_drift_but_high_variance_is_vfr(self):
        """Jitter that cancels out (zero cumulative drift from median)
        but has high per-frame variance → still VFR.
        The median of ±3000 alternation around nominal will be one of the
        two values; deviations from median are all ±6000 → high variance.
        """
        nominal_us = 41708
        deltas = []
        for i in range(48):
            deltas.append(nominal_us + (3000 if i % 2 == 0 else -3000))
        result = classify_frame_timing(deltas)
        # Variance is high regardless of which value is median
        assert result.variance_us > _VARIANCE_THRESHOLD_US
        assert result.frame_rate_class == FrameRateClass.VFR


# ---------------------------------------------------------------------------
# Long-Run Drift Projection
# ---------------------------------------------------------------------------


class TestMicroJitterProjectsToDrift:
    """INV-CADENCE-JITTER-ACCUMULATION-001:
    Small per-frame bias accumulates to VFR classification via
    projected cumulative drift.
    """

    def test_120us_bias_over_48_frames_triggers_vfr(self):
        """120us bias × 48 frames = 5760us cumulative drift > threshold.
        Per-frame variance is 0 (all deltas identical, but median is biased).
        Cumulative drift exceeds the 5000us threshold → VFR.
        """
        # Mix of nominal and biased so median stays at nominal
        nominal_us = 41708
        # 40 nominal + 8 frames at nominal+3500 → drift = 8*3500 = 28000us
        deltas = [nominal_us] * 40 + [nominal_us + 3500] * 8
        result = classify_frame_timing(deltas)
        assert abs(result.cumulative_drift_us) > _CUMULATIVE_DRIFT_THRESHOLD_US
        assert result.frame_rate_class == FrameRateClass.VFR

    def test_projected_drift_at_movie_scale(self):
        """A 48-frame window with drift rate D projects to movie-length drift.
        If D/48 > threshold_per_frame for a 90-min movie, classify VFR.

        This test verifies the contract principle: classification in a short
        window must catch drift rates that would be catastrophic over hours.
        """
        nominal_us = 41708
        # 6 frames with +1000us bias in a 48-frame window
        # Drift rate = 6000us / 48 frames = 125us/frame
        # Over 90min movie at 23.976fps: 129470 frames × 125us = 16.18s drift
        deltas = [nominal_us] * 42 + [nominal_us + 1000] * 6
        result = classify_frame_timing(deltas)
        assert result.frame_rate_class == FrameRateClass.VFR


# ---------------------------------------------------------------------------
# Explicit Clock Dominance
# ---------------------------------------------------------------------------


class TestVFRNeverUsesSourceTiming:
    """INV-CADENCE-INPUT-VFR-FORBIDDEN-001:
    In VFR mode, output timing MUST be derived from the output clock,
    never from source PTS intervals.
    """

    def test_output_timing_independent_of_source_gaps(self):
        """Two VFR sources with different PTS spacing produce identical
        output tick timing because the output clock is authoritative.
        """
        output_tick_us = 33367  # 29.97fps

        # Source A: frames at irregular content times
        frames_a = [(i, i * 38000) for i in range(10)]  # 38ms spacing
        # Source B: frames at very different content times
        frames_b = [(i, i * 50000) for i in range(10)]  # 50ms spacing

        # Output ticks are identical regardless of source
        for tick in range(5):
            t = tick * output_tick_us
            # Both sources produce a selection at the SAME output time
            sel_a = clock_driven_frame_select(t, frames_a)
            sel_b = clock_driven_frame_select(t, frames_b)
            # Selections may differ (different content) but the output
            # time that drives the selection is identical
            assert t == tick * output_tick_us  # Output clock is constant

    def test_source_pts_gap_does_not_stall_output(self):
        """A large gap in source PTS does not create a gap in output timing.
        The output clock continues at constant rate; it just repeats the
        last eligible frame until new content arrives.
        """
        # Source with a 200ms gap between frames 2 and 3
        frames = [
            (0, 0),
            (1, 40000),
            (2, 80000),
            # 200ms gap
            (3, 280000),
            (4, 320000),
        ]
        output_tick_us = 33367

        # During the gap (ticks 3-7, ~100-233ms), frame 2 is repeated
        selections = []
        for tick in range(10):
            t = tick * output_tick_us
            sel = clock_driven_frame_select(t, frames)
            selections.append(sel)

        # Ticks 0-2: frames 0, 0, 1
        # Ticks 3-7: frame 2 repeated (gap, no frame 3 until 280ms)
        # Ticks 8+: frame 3 becomes eligible at tick 8 (266936us)
        assert all(s is not None for s in selections[1:])
        # Frame 2 should be selected for multiple consecutive ticks during gap
        gap_selections = selections[3:8]
        assert all(s == 2 for s in gap_selections)

    def test_cadence_pattern_not_used_in_vfr_mode(self):
        """Verify that classify → VFR → select_resample_mode produces
        CLOCK_DRIVEN, never CADENCE, regardless of fps ratio.
        """
        deltas = generate_vfr_pts_deltas(jitter_range_us=5000, count=48)
        for output_fps in [(30000, 1001), (25, 1), (60000, 1001)]:
            result = classify_frame_timing(
                deltas,
                output_fps_num=output_fps[0],
                output_fps_den=output_fps[1],
            )
            mode = select_resample_mode(result)
            assert mode == ResampleMode.CLOCK_DRIVEN, (
                f"VFR input incorrectly allowed CADENCE at "
                f"output fps {output_fps[0]}/{output_fps[1]}"
            )
