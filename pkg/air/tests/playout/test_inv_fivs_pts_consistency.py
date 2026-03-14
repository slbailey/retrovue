"""
Contract test for INV-FIVS-PTS-CONSISTENCY (slope-based formulation).

Contract: pkg/air/docs/contracts/playout/INV-FIVS-PTS-CONSISTENCY.md

Invariant:
    For consecutive decoded frames within a segment, after the slope
    window has been established:

        established_delta = average(pts[i] − pts[i−1]) for i in 1..window
        |actual_delta − established_delta| ≤ 0.5 × established_delta

    If violated, PTS_DRIFT_DETECTED is logged. Frame is always emitted.
    Playback is never interrupted.

These tests validate the PTSSlopeValidator reference implementation.
The authoritative enforcement is in C++ (PipelineManager.cpp).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add pkg/air to sys.path so we can import the playout module.
_AIR_ROOT = Path(__file__).resolve().parents[2]
if str(_AIR_ROOT) not in sys.path:
    sys.path.insert(0, str(_AIR_ROOT))

from playout.pts_validator import PTSSlopeValidator, PTSSlopeDriftEvent


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# 24fps: ~41,667 µs per frame
DELTA_24FPS_US = 1_000_000 // 24  # 41666 µs

# 30fps: ~33,333 µs per frame
DELTA_30FPS_US = 1_000_000 // 30  # 33333 µs

# Small slope window for tests (avoid needing 25+ frames in every test).
TEST_WINDOW = 4


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _feed_consistent_frames(
    validator: PTSSlopeValidator,
    count: int,
    delta_us: int,
    start_pts_us: int = 0,
) -> int:
    """Feed `count` consistent frames and return the next expected PTS.

    The returned value is the PTS that the NEXT frame should have if
    the sequence continues at the same delta. i.e., to feed one more
    consistent frame, call validator.validate(returned_value).
    """
    pts = start_pts_us
    for _ in range(count):
        validator.validate(pts)
        pts += delta_us
    return pts


# ===========================================================================
# Test 1: Consistent slope produces no diagnostic
# ===========================================================================

class TestSlopeConsistentNoDiagnostic:
    """After slope establishment, consistent deltas produce no event."""

    def test_consistent_deltas_no_drift(self):
        """Frames with constant PTS delta produce no drift event."""
        v = PTSSlopeValidator(slope_window=TEST_WINDOW)
        # Establish slope: TEST_WINDOW + 1 frames (TEST_WINDOW deltas).
        pts = _feed_consistent_frames(v, TEST_WINDOW + 1, DELTA_24FPS_US)

        # 10 more consistent frames — all should pass.
        for _ in range(10):
            event = v.validate(pts)
            assert event is None, (
                f"Expected no drift for consistent delta, got {event}"
            )
            pts += DELTA_24FPS_US

    def test_small_jitter_within_tolerance(self):
        """Deltas within ±50% of established slope produce no event."""
        v = PTSSlopeValidator(slope_window=TEST_WINDOW)
        next_pts = _feed_consistent_frames(v, TEST_WINDOW + 1, DELTA_24FPS_US)

        # Feed a frame where the delta from last is 1.4× established (within ±50%).
        # next_pts is already 1× delta ahead. Adding 40% of delta makes the
        # actual delta from last frame = 1.4× delta.
        jitter = DELTA_24FPS_US * 40 // 100
        event = v.validate(next_pts + jitter)
        assert event is None, (
            f"Expected no drift for jitter within tolerance, got {event}"
        )


# ===========================================================================
# Test 2: Slope deviation triggers diagnostic
# ===========================================================================

class TestSlopeDeviationTriggersDiagnostic:
    """PTS delta outside ±50% of established slope triggers drift event."""

    def test_large_jump_triggers_drift(self):
        """PTS jump of 2× established delta triggers PTS_DRIFT_DETECTED."""
        v = PTSSlopeValidator(slope_window=TEST_WINDOW)
        next_pts = _feed_consistent_frames(v, TEST_WINDOW + 1, DELTA_24FPS_US)

        # Feed frame at next_pts + DELTA, making actual delta = 2× established.
        bad_pts = next_pts + DELTA_24FPS_US
        event = v.validate(bad_pts)

        assert event is not None, (
            "Expected PTS_DRIFT_DETECTED for 2× delta jump"
        )
        assert isinstance(event, PTSSlopeDriftEvent)
        assert event.actual_delta_us == 2 * DELTA_24FPS_US
        assert event.established_delta_us == DELTA_24FPS_US
        assert event.deviation_us == DELTA_24FPS_US  # 2× - 1× = 1×

    def test_near_zero_delta_triggers_drift(self):
        """PTS delta near zero (stall) triggers PTS_DRIFT_DETECTED."""
        v = PTSSlopeValidator(slope_window=TEST_WINDOW)
        next_pts = _feed_consistent_frames(v, TEST_WINDOW + 1, DELTA_24FPS_US)

        # The last validated PTS was next_pts - DELTA. Feeding next_pts - DELTA
        # again would give delta=0, but that frame was already validated.
        # Feed a frame with delta=0 by repeating the same PTS as the last one:
        # last validated PTS = next_pts - DELTA_24FPS_US.
        stall_pts = next_pts - DELTA_24FPS_US
        event = v.validate(stall_pts)
        assert event is not None, (
            "Expected PTS_DRIFT_DETECTED for zero delta (stall)"
        )
        assert event.actual_delta_us == 0

    def test_negative_delta_triggers_drift(self):
        """PTS going backwards triggers PTS_DRIFT_DETECTED."""
        v = PTSSlopeValidator(slope_window=TEST_WINDOW)
        next_pts = _feed_consistent_frames(v, TEST_WINDOW + 1, DELTA_24FPS_US)

        # Last validated PTS = next_pts - DELTA. Feeding a frame 2× DELTA
        # before that gives delta = -DELTA.
        backwards_pts = next_pts - 2 * DELTA_24FPS_US
        event = v.validate(backwards_pts)
        assert event is not None, (
            "Expected PTS_DRIFT_DETECTED for negative delta"
        )
        assert event.actual_delta_us == -DELTA_24FPS_US


# ===========================================================================
# Test 3: Accumulation phase never triggers
# ===========================================================================

class TestAccumulationPhaseNeverTriggers:
    """During slope accumulation, no diagnostics are emitted even for large jumps."""

    def test_no_drift_during_accumulation(self):
        """Wild PTS deltas during accumulation produce no event."""
        v = PTSSlopeValidator(slope_window=TEST_WINDOW)

        # Feed TEST_WINDOW + 1 frames with wildly varying deltas.
        pts_values = [0, 100000, 50000, 200000, 80000]  # 5 frames = 4 deltas = TEST_WINDOW
        for pts in pts_values:
            event = v.validate(pts)
            assert event is None, (
                f"Expected no drift during accumulation phase, got {event}"
            )


# ===========================================================================
# Test 4: Reset clears slope state
# ===========================================================================

class TestResetClearsSlopeState:
    """Reset allows re-establishment of slope for a new segment."""

    def test_reset_allows_new_slope(self):
        """After reset, a new slope is established from scratch."""
        v = PTSSlopeValidator(slope_window=TEST_WINDOW)

        # Establish 24fps slope.
        pts = _feed_consistent_frames(v, TEST_WINDOW + 1, DELTA_24FPS_US)

        # Reset (simulates segment boundary).
        v.reset()

        # Establish 30fps slope — completely different cadence.
        pts2 = _feed_consistent_frames(v, TEST_WINDOW + 1, DELTA_30FPS_US, start_pts_us=5_000_000)

        # Verify 30fps frames pass without drift.
        for _ in range(5):
            event = v.validate(pts2)
            assert event is None, (
                f"Expected no drift after reset and new slope, got {event}"
            )
            pts2 += DELTA_30FPS_US

    def test_reset_mid_accumulation(self):
        """Reset during accumulation phase starts fresh."""
        v = PTSSlopeValidator(slope_window=TEST_WINDOW)

        # Feed 2 frames (incomplete accumulation).
        v.validate(0)
        v.validate(DELTA_24FPS_US)

        # Reset.
        v.reset()

        # New slope establishment should start from zero count.
        pts = _feed_consistent_frames(v, TEST_WINDOW + 1, DELTA_30FPS_US)

        # Verify new slope works.
        event = v.validate(pts)
        assert event is None


# ===========================================================================
# Test 5: Telecine source produces no false positive
# ===========================================================================

class TestTelecineNoFalsePositive:
    """Telecine: declared 23.976fps but actual PTS spacing at 29.97fps."""

    def test_telecine_consistent_slope(self):
        """Telecine file with consistent PTS spacing at 29.97fps.

        The slope validator doesn't care about declared frame rate —
        it learns the actual PTS spacing from the stream. A telecine
        source with consistent 33,367µs deltas should never trigger drift.
        """
        # 29.97fps PTS spacing (actual telecine cadence).
        telecine_delta_us = 1_001_000 // 30  # 33366 µs

        v = PTSSlopeValidator(slope_window=TEST_WINDOW)
        pts = _feed_consistent_frames(v, TEST_WINDOW + 1, telecine_delta_us)

        # 50 more frames at telecine cadence — no drift.
        for _ in range(50):
            event = v.validate(pts)
            assert event is None, (
                f"Telecine false positive: {event}"
            )
            pts += telecine_delta_us


# ===========================================================================
# Test 6: Frame is always returned (emission never blocked)
# ===========================================================================

class TestFrameAlwaysEmitted:
    """Drift detection must never block emission — validator is diagnostic only."""

    def test_drift_event_is_informational(self):
        """The validator returns an event but does not raise or block.

        The caller (PipelineManager) always emits the frame regardless
        of the return value. This test verifies the API contract: validate()
        returns a value, never raises, never blocks.
        """
        v = PTSSlopeValidator(slope_window=TEST_WINDOW)
        next_pts = _feed_consistent_frames(v, TEST_WINDOW + 1, DELTA_24FPS_US)

        # Trigger drift (10× delta jump) — but the call must succeed.
        event = v.validate(next_pts + 9 * DELTA_24FPS_US)

        # Event is present but is just data — no exception, no side effect.
        assert event is not None
        assert isinstance(event, PTSSlopeDriftEvent)
        # The caller would emit the frame regardless. The validator
        # doesn't even see the frame — it only sees PTS values.
