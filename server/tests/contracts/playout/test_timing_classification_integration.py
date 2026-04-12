"""
Contract tests for playout_timing_classification_integration.md

Validates that timing classification is correctly integrated into the
playout lifecycle: invoked during prime, complete before output,
immutable within a segment, segment-scoped, and accessible to all
timing consumers.

Each test maps to a specific invariant or failure scenario from the contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

import pytest


# ---------------------------------------------------------------------------
# Shared types (same definitions as test_cadence_input_stability.py)
# ---------------------------------------------------------------------------


class ResampleMode(Enum):
    CADENCE = "cadence"
    CLOCK_DRIVEN = "clock"


class FrameRateClass(Enum):
    CFR = "cfr"
    VFR = "vfr"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class ClassificationResult:
    frame_rate_class: FrameRateClass
    nominal_interval_us: int
    variance_us: float
    cumulative_drift_us: float
    observation_frames: int
    selected_mode: ResampleMode


class CadenceVFRViolation(Exception):
    pass


class OutputBeforeClassificationError(Exception):
    """Raised when output is attempted before classification completes."""
    pass


class ClassificationImmutableError(Exception):
    """Raised when classification is overwritten after output has begun."""
    pass


# ---------------------------------------------------------------------------
# Lifecycle stub — minimal model of the playout segment lifecycle.
# Models the data flow defined in the contract:
#   decoder open → prime → collect PTS → classify → select mode →
#   enforce → store → activate output → emit frames
# ---------------------------------------------------------------------------


def _classify_pts_deltas(deltas: List[int]) -> ClassificationResult:
    """Stub classifier matching the contract's algorithm."""
    n = len(deltas)
    if n < 12:
        return ClassificationResult(
            frame_rate_class=FrameRateClass.INDETERMINATE,
            nominal_interval_us=0,
            variance_us=0.0,
            cumulative_drift_us=0.0,
            observation_frames=n,
            selected_mode=ResampleMode.CLOCK_DRIVEN,
        )
    sorted_d = sorted(deltas)
    nominal = sorted_d[n // 2]
    devs = [d - nominal for d in deltas]
    var = sum(d * d for d in devs) / n
    drift = sum(devs)
    stable = var <= 500.0 and abs(drift) <= 5000
    frc = FrameRateClass.CFR if stable else FrameRateClass.VFR
    mode = ResampleMode.CLOCK_DRIVEN
    if frc == FrameRateClass.CFR and nominal > 0:
        src_fps = 1_000_000 / nominal
        out_fps = 30000 / 1001
        if abs(src_fps - out_fps) > 0.5:
            mode = ResampleMode.CADENCE
    return ClassificationResult(
        frame_rate_class=frc,
        nominal_interval_us=nominal,
        variance_us=var,
        cumulative_drift_us=drift,
        observation_frames=n,
        selected_mode=mode,
    )


def _raising_classifier(deltas: List[int]) -> ClassificationResult:
    """Classifier that always raises — simulates internal failure."""
    raise RuntimeError("classifier internal error")


class SegmentPlayoutLifecycle:
    """Minimal model of a single segment's playout lifecycle.

    Enforces the contract's data flow and invariants:
    - Classification during prime only
    - Output gated on classification
    - Classification immutable after output begins
    """

    def __init__(
        self,
        classifier=_classify_pts_deltas,
    ):
        self._classifier = classifier
        self._classification: Optional[ClassificationResult] = None
        self._output_started = False
        self._prime_complete = False
        self._frames_emitted: int = 0
        self._prime_pts_deltas: List[int] = []

    # --- Prime phase ---

    def decode_prime_frame(self, pts_delta_us: int) -> None:
        """Simulate decoding a frame during prime. Collects PTS delta."""
        if self._output_started:
            raise RuntimeError("Cannot prime after output has started")
        self._prime_pts_deltas.append(pts_delta_us)

    def complete_prime(self) -> None:
        """Run classification on collected PTS deltas and store result.

        INV-TIMING-CLASSIFICATION-LIFECYCLE-001: Classification during prime.
        INV-TIMING-CLASSIFICATION-LIFECYCLE-002: Completes before output.
        """
        if self._prime_complete:
            return  # Idempotent
        try:
            self._classification = self._classifier(self._prime_pts_deltas)
        except Exception:
            # Contract: classifier exception → INDETERMINATE → CLOCK_DRIVEN
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

    def activate_output(self, requested_mode: Optional[ResampleMode] = None) -> ResampleMode:
        """Activate output clock with the classified mode.

        INV-TIMING-CLASSIFICATION-GATE-001: No output without classification.
        INV-TIMING-CLASSIFICATION-GATE-002: No CADENCE bypass.
        """
        if self._classification is None:
            raise OutputBeforeClassificationError(
                "Output activation rejected: classification not complete"
            )
        mode = requested_mode or self._classification.selected_mode
        # INV-CADENCE-INPUT-VFR-FORBIDDEN-001: hard reject
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

    def overwrite_classification(self, new_result: ClassificationResult) -> None:
        """Attempt to overwrite classification.

        INV-TIMING-CLASSIFICATION-IMMUTABLE-001: Rejected after output starts.
        INV-TIMING-CLASSIFICATION-LIFECYCLE-003: No mid-playback reclassification.
        """
        if self._output_started:
            raise ClassificationImmutableError(
                "Classification cannot be changed after output has started"
            )
        self._classification = new_result


# ---------------------------------------------------------------------------
# Timing consumer stubs — verify all consumers read the same result
# ---------------------------------------------------------------------------


class OutputClockStub:
    """Simulates the output clock reading classification."""
    def __init__(self, lifecycle: SegmentPlayoutLifecycle):
        self._lifecycle = lifecycle

    @property
    def mode(self) -> Optional[ResampleMode]:
        return self._lifecycle.selected_mode

    @property
    def classification(self) -> Optional[ClassificationResult]:
        return self._lifecycle.classification


class CadenceEngineStub:
    """Simulates the cadence engine reading classification."""
    def __init__(self, lifecycle: SegmentPlayoutLifecycle):
        self._lifecycle = lifecycle

    @property
    def classification(self) -> Optional[ClassificationResult]:
        return self._lifecycle.classification

    @property
    def is_active(self) -> bool:
        c = self._lifecycle.classification
        return c is not None and c.selected_mode == ResampleMode.CADENCE


class DiagnosticsStub:
    """Simulates diagnostics reading classification."""
    def __init__(self, lifecycle: SegmentPlayoutLifecycle):
        self._lifecycle = lifecycle

    @property
    def classification(self) -> Optional[ClassificationResult]:
        return self._lifecycle.classification


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cfr_deltas(count: int = 48) -> List[int]:
    return [int(1001 * 1_000_000 / 24000)] * count  # 41708us


def _vfr_deltas(count: int = 48) -> List[int]:
    import random
    rng = random.Random(42)
    nom = int(1001 * 1_000_000 / 24000)
    return [nom + rng.randint(-5000, 5000) for _ in range(count)]


# ---------------------------------------------------------------------------
# Contract Tests
# ---------------------------------------------------------------------------


class TestClassificationDuringPrime:
    """INV-TIMING-CLASSIFICATION-LIFECYCLE-001:
    Classification occurs during the segment prime phase.
    """

    def test_classification_available_after_prime(self):
        seg = SegmentPlayoutLifecycle()
        for d in _cfr_deltas():
            seg.decode_prime_frame(d)
        assert seg.classification is None  # Not classified yet
        seg.complete_prime()
        assert seg.classification is not None
        assert seg.classification.frame_rate_class == FrameRateClass.CFR

    def test_classification_not_available_before_prime(self):
        seg = SegmentPlayoutLifecycle()
        assert seg.is_classified is False
        assert seg.classification is None

    def test_prime_collects_pts_deltas(self):
        seg = SegmentPlayoutLifecycle()
        for d in _cfr_deltas(24):
            seg.decode_prime_frame(d)
        seg.complete_prime()
        assert seg.classification.observation_frames == 24


class TestNoOutputBeforeClassification:
    """INV-TIMING-CLASSIFICATION-LIFECYCLE-002:
    Classification completes before first output frame.
    """

    def test_emit_before_classification_raises(self):
        seg = SegmentPlayoutLifecycle()
        with pytest.raises(OutputBeforeClassificationError):
            seg.emit_frame()

    def test_activate_before_classification_raises(self):
        seg = SegmentPlayoutLifecycle()
        with pytest.raises(OutputBeforeClassificationError):
            seg.activate_output()

    def test_emit_after_classification_and_activation_succeeds(self):
        seg = SegmentPlayoutLifecycle()
        for d in _cfr_deltas():
            seg.decode_prime_frame(d)
        seg.complete_prime()
        seg.activate_output()
        seg.emit_frame()
        assert seg.frames_emitted == 1


class TestNoReclassificationMidSegment:
    """INV-TIMING-CLASSIFICATION-LIFECYCLE-003:
    Classification does not occur mid-playback.
    """

    def test_overwrite_after_output_raises(self):
        seg = SegmentPlayoutLifecycle()
        for d in _cfr_deltas():
            seg.decode_prime_frame(d)
        seg.complete_prime()
        seg.activate_output()
        seg.emit_frame()

        new_result = ClassificationResult(
            frame_rate_class=FrameRateClass.VFR,
            nominal_interval_us=41708,
            variance_us=9999.0,
            cumulative_drift_us=50000.0,
            observation_frames=48,
            selected_mode=ResampleMode.CLOCK_DRIVEN,
        )
        with pytest.raises(ClassificationImmutableError):
            seg.overwrite_classification(new_result)

    def test_prime_after_output_raises(self):
        seg = SegmentPlayoutLifecycle()
        for d in _cfr_deltas():
            seg.decode_prime_frame(d)
        seg.complete_prime()
        seg.activate_output()
        with pytest.raises(RuntimeError, match="Cannot prime after output"):
            seg.decode_prime_frame(41708)


class TestClassificationImmutableDuringPlayback:
    """INV-TIMING-CLASSIFICATION-IMMUTABLE-001:
    Stored classification cannot be overwritten while segment is active.
    """

    def test_classification_unchanged_after_many_frames(self):
        seg = SegmentPlayoutLifecycle()
        for d in _cfr_deltas():
            seg.decode_prime_frame(d)
        seg.complete_prime()
        original = seg.classification
        seg.activate_output()
        for _ in range(100):
            seg.emit_frame()
        assert seg.classification is original

    def test_overwrite_before_output_allowed(self):
        seg = SegmentPlayoutLifecycle()
        for d in _cfr_deltas():
            seg.decode_prime_frame(d)
        seg.complete_prime()
        # Before output, overwrite is permitted (re-classification during prime)
        new_result = ClassificationResult(
            frame_rate_class=FrameRateClass.VFR,
            nominal_interval_us=41708,
            variance_us=9999.0,
            cumulative_drift_us=50000.0,
            observation_frames=48,
            selected_mode=ResampleMode.CLOCK_DRIVEN,
        )
        seg.overwrite_classification(new_result)
        assert seg.classification.frame_rate_class == FrameRateClass.VFR

    def test_overwrite_after_activation_raises(self):
        seg = SegmentPlayoutLifecycle()
        for d in _cfr_deltas():
            seg.decode_prime_frame(d)
        seg.complete_prime()
        seg.activate_output()
        with pytest.raises(ClassificationImmutableError):
            seg.overwrite_classification(seg.classification)


class TestClassificationPerSegment:
    """INV-TIMING-CLASSIFICATION-SCOPED-001:
    Each segment gets independent classification. No state leaks.
    """

    def test_two_segments_independent(self):
        seg_a = SegmentPlayoutLifecycle()
        for d in _cfr_deltas():
            seg_a.decode_prime_frame(d)
        seg_a.complete_prime()

        seg_b = SegmentPlayoutLifecycle()
        for d in _vfr_deltas():
            seg_b.decode_prime_frame(d)
        seg_b.complete_prime()

        assert seg_a.classification.frame_rate_class == FrameRateClass.CFR
        assert seg_b.classification.frame_rate_class == FrameRateClass.VFR

    def test_segment_b_not_inherited_from_a(self):
        seg_a = SegmentPlayoutLifecycle()
        for d in _cfr_deltas():
            seg_a.decode_prime_frame(d)
        seg_a.complete_prime()
        seg_a.activate_output()

        seg_b = SegmentPlayoutLifecycle()
        assert seg_b.classification is None  # Fresh, not inherited
        assert seg_b.is_classified is False

    def test_same_asset_different_seek_reclassified(self):
        """Same source file at different seek positions gets fresh classification."""
        seg_a = SegmentPlayoutLifecycle()
        for d in _cfr_deltas():
            seg_a.decode_prime_frame(d)
        seg_a.complete_prime()

        seg_b = SegmentPlayoutLifecycle()
        # Same nominal FPS but slightly different deltas (e.g., after seek)
        for d in _cfr_deltas():
            seg_b.decode_prime_frame(d)
        seg_b.complete_prime()

        # Both classified independently — same result but distinct objects
        assert seg_a.classification is not seg_b.classification
        assert seg_a.classification.frame_rate_class == seg_b.classification.frame_rate_class


class TestAllTimingConsumersAccessResult:
    """INV-TIMING-CLASSIFICATION-AVAILABLE-001:
    Output clock, cadence engine, and diagnostics all read same result.
    """

    def test_all_consumers_see_same_result(self):
        seg = SegmentPlayoutLifecycle()
        for d in _cfr_deltas():
            seg.decode_prime_frame(d)
        seg.complete_prime()

        clock = OutputClockStub(seg)
        cadence = CadenceEngineStub(seg)
        diag = DiagnosticsStub(seg)

        assert clock.classification is seg.classification
        assert cadence.classification is seg.classification
        assert diag.classification is seg.classification

    def test_consumers_see_mode_consistent_with_classification(self):
        seg = SegmentPlayoutLifecycle()
        for d in _cfr_deltas():
            seg.decode_prime_frame(d)
        seg.complete_prime()

        clock = OutputClockStub(seg)
        cadence = CadenceEngineStub(seg)

        assert clock.mode == seg.classification.selected_mode
        assert cadence.is_active == (seg.classification.selected_mode == ResampleMode.CADENCE)

    def test_vfr_consumers_see_clock_driven(self):
        seg = SegmentPlayoutLifecycle()
        for d in _vfr_deltas():
            seg.decode_prime_frame(d)
        seg.complete_prime()

        clock = OutputClockStub(seg)
        cadence = CadenceEngineStub(seg)

        assert clock.mode == ResampleMode.CLOCK_DRIVEN
        assert cadence.is_active is False


class TestOutputGateBlocksWithoutClassification:
    """INV-TIMING-CLASSIFICATION-GATE-001:
    Segment with no classification cannot emit frames.
    """

    def test_unclassified_segment_blocks_output(self):
        seg = SegmentPlayoutLifecycle()
        # No prime, no classification
        with pytest.raises(OutputBeforeClassificationError):
            seg.activate_output()

    def test_partial_prime_no_complete_blocks_output(self):
        seg = SegmentPlayoutLifecycle()
        seg.decode_prime_frame(41708)
        # Primed but not completed → no classification
        with pytest.raises(OutputBeforeClassificationError):
            seg.activate_output()

    def test_completed_prime_allows_output(self):
        seg = SegmentPlayoutLifecycle()
        for d in _cfr_deltas():
            seg.decode_prime_frame(d)
        seg.complete_prime()
        mode = seg.activate_output()
        assert mode in (ResampleMode.CADENCE, ResampleMode.CLOCK_DRIVEN)


class TestNoCadenceWithoutClassification:
    """INV-TIMING-CLASSIFICATION-GATE-002:
    CADENCE activation without classification raises or rejects.
    """

    def test_cadence_without_classification_raises(self):
        seg = SegmentPlayoutLifecycle()
        with pytest.raises(OutputBeforeClassificationError):
            seg.activate_output(requested_mode=ResampleMode.CADENCE)

    def test_cadence_on_vfr_classification_raises(self):
        seg = SegmentPlayoutLifecycle()
        for d in _vfr_deltas():
            seg.decode_prime_frame(d)
        seg.complete_prime()
        with pytest.raises(CadenceVFRViolation):
            seg.activate_output(requested_mode=ResampleMode.CADENCE)

    def test_cadence_on_cfr_classification_allowed(self):
        seg = SegmentPlayoutLifecycle()
        for d in _cfr_deltas():
            seg.decode_prime_frame(d)
        seg.complete_prime()
        mode = seg.activate_output(requested_mode=ResampleMode.CADENCE)
        assert mode == ResampleMode.CADENCE

    def test_cadence_on_indeterminate_raises(self):
        seg = SegmentPlayoutLifecycle()
        # Only 5 frames → INDETERMINATE
        for d in _cfr_deltas(5):
            seg.decode_prime_frame(d)
        seg.complete_prime()
        assert seg.classification.frame_rate_class == FrameRateClass.INDETERMINATE
        with pytest.raises(CadenceVFRViolation):
            seg.activate_output(requested_mode=ResampleMode.CADENCE)


class TestInsufficientFramesDefaultsClock:
    """Failure handling: too few prime frames → INDETERMINATE → CLOCK_DRIVEN."""

    def test_few_frames_indeterminate_clock_driven(self):
        seg = SegmentPlayoutLifecycle()
        for d in _cfr_deltas(5):
            seg.decode_prime_frame(d)
        seg.complete_prime()
        assert seg.classification.frame_rate_class == FrameRateClass.INDETERMINATE
        mode = seg.activate_output()
        assert mode == ResampleMode.CLOCK_DRIVEN

    def test_zero_frames_indeterminate_clock_driven(self):
        seg = SegmentPlayoutLifecycle()
        seg.complete_prime()
        assert seg.classification.frame_rate_class == FrameRateClass.INDETERMINATE
        mode = seg.activate_output()
        assert mode == ResampleMode.CLOCK_DRIVEN


class TestDecoderFailureDefaultsClock:
    """Failure handling: decoder produces zero frames → INDETERMINATE → CLOCK_DRIVEN."""

    def test_decoder_failure_no_frames(self):
        seg = SegmentPlayoutLifecycle()
        # Decoder "fails" — produces nothing
        seg.complete_prime()
        assert seg.classification.frame_rate_class == FrameRateClass.INDETERMINATE
        assert seg.classification.observation_frames == 0
        mode = seg.activate_output()
        assert mode == ResampleMode.CLOCK_DRIVEN


class TestClassificationExceptionDefaultsClock:
    """Failure handling: classifier raises → INDETERMINATE → CLOCK_DRIVEN."""

    def test_classifier_exception_caught_indeterminate(self):
        seg = SegmentPlayoutLifecycle(classifier=_raising_classifier)
        for d in _cfr_deltas():
            seg.decode_prime_frame(d)
        seg.complete_prime()
        # Exception caught, result is INDETERMINATE
        assert seg.classification.frame_rate_class == FrameRateClass.INDETERMINATE
        mode = seg.activate_output()
        assert mode == ResampleMode.CLOCK_DRIVEN

    def test_classifier_exception_does_not_crash(self):
        seg = SegmentPlayoutLifecycle(classifier=_raising_classifier)
        for d in _cfr_deltas():
            seg.decode_prime_frame(d)
        # Must not raise
        seg.complete_prime()
        seg.activate_output()
        seg.emit_frame()
        assert seg.frames_emitted == 1
