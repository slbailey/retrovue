"""
Contract Tests: Rational-Timebase OutputClock Pacing

Validates that OutputClock's nanosecond-resolution rational pacing
produces exact deadlines for all standard broadcast frame rates over
multi-hour sessions.

The pacing formula is:
    ns_per_frame_whole = (1_000_000_000 * fps_den) // fps_num
    ns_per_frame_rem   = (1_000_000_000 * fps_den) %  fps_num
    deadline_ns(N) = N * ns_per_frame_whole + (N * ns_per_frame_rem) // fps_num

The INVALID ms-quantized formula is:
    deadline_ms(N) = N * round(1000/fps)
    e.g. 900 * 33 = 29700ms instead of 30000ms for 30fps/30s

All tests are pure arithmetic — no sleeping, no wall-clock.

Copyright (c) 2025 RetroVue
"""

from __future__ import annotations

import pytest


NS_PER_SECOND = 1_000_000_000


def deadline_offset_ns(n: int, fps_num: int, fps_den: int) -> int:
    """Mirrors OutputClock::DeadlineOffsetNs — rational nanosecond deadline.

    deadline = N * (1_000_000_000 * fps_den) / fps_num
    Split: whole + remainder to avoid overflow.
    """
    ns_total = NS_PER_SECOND * fps_den
    ns_per_frame_whole = ns_total // fps_num
    ns_per_frame_rem = ns_total % fps_num
    return n * ns_per_frame_whole + (n * ns_per_frame_rem) // fps_num


def deadline_offset_ns_INVALID(n: int, fps: float) -> int:
    """The INVALID ms-quantized pacing formula (pre-fix behavior).

    deadline_ms = N * round(1000/fps)
    Returns nanoseconds for comparison.
    """
    frame_dur_ms = round(1000 / fps)
    return n * frame_dur_ms * 1_000_000


def true_duration_ns(n: int, fps_num: int, fps_den: int) -> float:
    """Mathematically exact duration for N frames as a float (reference).

    duration = N * fps_den / fps_num seconds
    """
    return n * fps_den / fps_num * NS_PER_SECOND


# =============================================================================
# Group 1: Exact deadlines for integer FPS
# =============================================================================

class TestExactDeadlinesIntegerFPS:
    """Rational pacing must be exact for integer frame rates."""

    @pytest.mark.parametrize("fps_num,fps_den,n,expected_ns", [
        # 30fps, 900 frames = exactly 30s
        (30, 1, 900, 30_000_000_000),
        # 30fps, 1 frame = exactly 33.333...ms → floor = 33_333_333 ns
        (30, 1, 1, 33_333_333),
        # 30fps, 30 frames = exactly 1s
        (30, 1, 30, 1_000_000_000),
        # 24fps, 720 frames = exactly 30s
        (24, 1, 720, 30_000_000_000),
        # 60fps, 1800 frames = exactly 30s
        (60, 1, 1800, 30_000_000_000),
        # 25fps, 750 frames = exactly 30s
        (25, 1, 750, 30_000_000_000),
    ])
    def test_exact_deadline(self, fps_num, fps_den, n, expected_ns):
        result = deadline_offset_ns(n, fps_num, fps_den)
        assert result == expected_ns, (
            f"Deadline for {n} frames at {fps_num}/{fps_den}fps = "
            f"{result} ns, expected {expected_ns} ns"
        )

    def test_30fps_900_frames_invalid_drifts(self):
        """The old ms-quantized formula drifts 300ms in 30s at 30fps."""
        rational = deadline_offset_ns(900, 30, 1)
        invalid = deadline_offset_ns_INVALID(900, 30.0)
        assert rational == 30_000_000_000  # Exact 30s
        assert invalid == 29_700_000_000   # 900 * 33ms = 29.7s
        assert rational - invalid == 300_000_000  # 300ms drift


# =============================================================================
# Group 2: Exact deadlines for non-integer FPS (29.97, 23.976)
# =============================================================================

class TestExactDeadlinesNonIntegerFPS:
    """Rational pacing must be accurate for 1001-denominator rates."""

    @pytest.mark.parametrize("fps_num,fps_den,n,expected_ns", [
        # 29.97fps (30000/1001), 900 frames:
        # 900 * 1_000_000_000 * 1001 / 30000 = 30_030_000_000 ns = 30.03s
        (30000, 1001, 900, 30_030_000_000),
        # 23.976fps (24000/1001), 720 frames:
        # 720 * 1_000_000_000 * 1001 / 24000 = 30_030_000_000 ns = 30.03s
        (24000, 1001, 720, 30_030_000_000),
        # 59.94fps (60000/1001), 1800 frames:
        # 1800 * 1_000_000_000 * 1001 / 60000 = 30_030_000_000 ns
        (60000, 1001, 1800, 30_030_000_000),
    ])
    def test_exact_deadline_1001(self, fps_num, fps_den, n, expected_ns):
        result = deadline_offset_ns(n, fps_num, fps_den)
        assert result == expected_ns, (
            f"Deadline for {n} frames at {fps_num}/{fps_den}fps = "
            f"{result} ns, expected {expected_ns} ns"
        )


# =============================================================================
# Group 3: 1-hour session accuracy
# =============================================================================

class TestOneHourAccuracy:
    """Over 1 hour, rational pacing must be within 1ms of true duration."""

    @pytest.mark.parametrize("fps_num,fps_den,label", [
        (30, 1, "30fps"),
        (24, 1, "24fps"),
        (60, 1, "60fps"),
        (25, 1, "25fps"),
        (30000, 1001, "29.97fps"),
        (24000, 1001, "23.976fps"),
        (60000, 1001, "59.94fps"),
    ])
    def test_one_hour_drift_under_1ms(self, fps_num, fps_den, label):
        """Computed deadline for 1 hour of frames must be within 1ms
        of the mathematically exact duration."""
        one_hour_s = 3600
        # Number of frames in 1 hour (floor — we want the last complete frame)
        n_frames = one_hour_s * fps_num // fps_den

        computed_ns = deadline_offset_ns(n_frames, fps_num, fps_den)
        exact_ns = true_duration_ns(n_frames, fps_num, fps_den)
        error_ns = abs(computed_ns - exact_ns)

        # Error must be less than 1ms (1_000_000 ns)
        assert error_ns < 1_000_000, (
            f"{label}: 1-hour drift = {error_ns} ns ({error_ns/1e6:.3f} ms). "
            f"n_frames={n_frames}, computed={computed_ns}, exact={exact_ns}"
        )

    @pytest.mark.parametrize("fps_num,fps_den,label", [
        (30, 1, "30fps"),
        (60, 1, "60fps"),
    ])
    def test_one_hour_invalid_drift_is_large(self, fps_num, fps_den, label):
        """The old ms-quantized formula drifts by SECONDS over 1 hour."""
        one_hour_s = 3600
        n_frames = one_hour_s * fps_num // fps_den
        fps_approx = fps_num / fps_den

        rational_ns = deadline_offset_ns(n_frames, fps_num, fps_den)
        invalid_ns = deadline_offset_ns_INVALID(n_frames, fps_approx)
        drift_abs_ms = abs(rational_ns - invalid_ns) / 1_000_000

        # For 30fps: round(1000/30)=33 < 33.333 → runs fast → large positive drift
        # For 60fps: round(1000/60)=17 > 16.667 → runs slow → large negative drift
        # Either way, drift magnitude exceeds 1s over 1 hour.
        assert drift_abs_ms > 1000, (
            f"{label}: expected >1s absolute drift from ms-quantized formula, "
            f"got {drift_abs_ms:.1f} ms"
        )


# =============================================================================
# Group 4: Remainder handling (Bresenham correctness)
# =============================================================================

class TestRemainderHandling:
    """The Bresenham-style split must handle remainders correctly."""

    def test_30fps_remainder_structure(self):
        """30fps: 1e9/30 = 33_333_333 remainder 10.
        After 30 frames, remainder contributes exactly 300ns → total = 1s exact."""
        ns_total = NS_PER_SECOND * 1  # fps_den=1
        whole = ns_total // 30
        rem = ns_total % 30
        assert whole == 33_333_333
        assert rem == 10

        # 30 frames: 30 * 33_333_333 + (30 * 10) // 30 = 999_999_990 + 10 = 1e9
        deadline = 30 * whole + (30 * rem) // 30
        assert deadline == NS_PER_SECOND

    def test_29_97fps_remainder_structure(self):
        """29.97fps (30000/1001): verify remainder is handled correctly."""
        ns_total = NS_PER_SECOND * 1001  # fps_den=1001
        whole = ns_total // 30000
        rem = ns_total % 30000
        # 1_001_000_000_000 / 30000 = 33_366_666 remainder 20_000
        assert whole == 33_366_666
        assert rem == 20_000

    def test_deadline_monotonically_increasing(self):
        """Deadlines must be strictly monotonically increasing."""
        for fps_num, fps_den in [(30, 1), (30000, 1001), (24000, 1001), (60, 1)]:
            prev = -1
            for n in range(1000):
                d = deadline_offset_ns(n, fps_num, fps_den)
                assert d > prev, (
                    f"Deadline not monotonic at frame {n}: "
                    f"{d} <= {prev} for {fps_num}/{fps_den}"
                )
                prev = d

    def test_no_negative_deadlines(self):
        """All deadlines must be non-negative."""
        for fps_num, fps_den in [(30, 1), (30000, 1001), (24000, 1001)]:
            for n in range(100):
                assert deadline_offset_ns(n, fps_num, fps_den) >= 0

    def test_frame_zero_is_zero(self):
        """Deadline for frame 0 must be exactly 0 (start of session)."""
        for fps_num, fps_den in [(30, 1), (30000, 1001), (24000, 1001), (60, 1)]:
            assert deadline_offset_ns(0, fps_num, fps_den) == 0


# =============================================================================
# Group 5: Overflow safety
# =============================================================================

class TestOverflowSafety:
    """The split formula must not overflow int64 for multi-day sessions."""

    @pytest.mark.parametrize("hours", [1, 12, 24, 48])
    def test_no_overflow_30fps(self, hours):
        """30fps for N hours must produce valid (non-negative) deadline."""
        n = hours * 3600 * 30
        d = deadline_offset_ns(n, 30, 1)
        assert d > 0
        expected_s = hours * 3600
        # Should be exactly expected_s seconds
        assert d == expected_s * NS_PER_SECOND

    @pytest.mark.parametrize("hours", [1, 12, 24, 48])
    def test_no_overflow_29_97fps(self, hours):
        """29.97fps for N hours must produce valid deadline within 1ms."""
        n = hours * 3600 * 30000 // 1001
        d = deadline_offset_ns(n, 30000, 1001)
        assert d > 0
        exact = true_duration_ns(n, 30000, 1001)
        error_ns = abs(d - exact)
        assert error_ns < 1_000_000, (
            f"29.97fps {hours}h: error = {error_ns/1e6:.3f} ms"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
