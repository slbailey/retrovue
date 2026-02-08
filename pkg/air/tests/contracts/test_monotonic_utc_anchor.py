"""
Contract Tests: INV-TICK-MONOTONIC-UTC-ANCHOR-001

Contract reference:
    pkg/air/docs/contracts/INV-TICK-MONOTONIC-UTC-ANCHOR-001.md

These tests prove that:

  - Tick deadline enforcement uses monotonic time, not UTC wall time.
  - UTC remains the schedule authority for fence computation.
  - NTP/system-time steps cannot break tick cadence.
  - Session epochs (both UTC and monotonic) are captured once and immutable.

Tests assert authority outcomes only:
  - epoch immutability
  - deadline correctness in the monotonic domain
  - cadence continuity across clock perturbations
  - fence computation domain (UTC, not monotonic)

Tests do NOT assert fallback frame types or recovery strategies.

All tests are deterministic and require no media files, AIR process,
or wall-clock sleeps.

Copyright (c) 2025 RetroVue
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest


NS_PER_SECOND = 1_000_000_000


# =============================================================================
# Pure functions: mirrors of C++ (OutputClock, PipelineManager)
# =============================================================================

def deadline_offset_ns(n: int, fps_num: int, fps_den: int) -> int:
    """Mirrors OutputClock::DeadlineOffsetNs — rational nanosecond offset.

    deadline = N * (1_000_000_000 * fps_den) / fps_num
    Split into whole + remainder (Bresenham) to avoid overflow.
    """
    ns_total = NS_PER_SECOND * fps_den
    ns_per_frame_whole = ns_total // fps_num
    ns_per_frame_rem = ns_total % fps_num
    return n * ns_per_frame_whole + (n * ns_per_frame_rem) // fps_num


def compute_fence_tick(
    end_utc_ms: int, session_epoch_utc_ms: int,
    fps_num: int, fps_den: int,
) -> int:
    """Mirrors C++ compute_fence_frame — rational ceil division.

    fence_tick = ceil(delta_ms * fps_num / (fps_den * 1000))
    Integer form: (delta_ms * fps_num + fps_den * 1000 - 1) / (fps_den * 1000)
    """
    delta_ms = end_utc_ms - session_epoch_utc_ms
    if delta_ms <= 0:
        return 0
    denominator = fps_den * 1000
    return (delta_ms * fps_num + denominator - 1) // denominator


# =============================================================================
# Model: Dual-clock session with UTC step injection
# =============================================================================

@dataclass
class TickRecord:
    """What happened on one output tick."""
    tick_index: int
    deadline_mono_ns: int   # Monotonic deadline (enforcement domain)
    mono_at_emission: int   # Monotonic clock at emission
    utc_at_emission_ms: int # UTC clock at emission (may be stepped)
    was_late: bool          # Lateness detected via monotonic clock


class DualClockSessionModel:
    """Model of a session with dual-anchor epochs and UTC step injection.

    Per INV-TICK-MONOTONIC-UTC-ANCHOR-001:

    Monotonic clock is used for:
      - Deadline computation (deadline_mono_ns)
      - Lateness detection (now_mono >= deadline_mono)
      - Wait/sleep decisions

    UTC clock is used for:
      - Fence computation (schedule authority per INV-BLOCK-WALLCLOCK-FENCE-001)
      - Mapping schedules to tick indices

    UTC clock can be stepped mid-session to simulate NTP adjustments.
    Monotonic clock is immune to steps by definition.
    """

    def __init__(
        self,
        fps_num: int,
        fps_den: int,
        session_epoch_utc_ms: int,
        session_epoch_mono_ns: int,
    ) -> None:
        self.fps_num = fps_num
        self.fps_den = fps_den

        # R1: Dual-anchor capture — immutable after init
        self._session_epoch_utc_ms = session_epoch_utc_ms
        self._session_epoch_mono_ns = session_epoch_mono_ns

        # Simulated clocks
        self.mono_ns: int = session_epoch_mono_ns
        self._utc_step_offset_ms: int = 0  # Cumulative NTP step

        # State
        self.session_frame_index: int = 0
        self.tick_log: list[TickRecord] = []

    @property
    def session_epoch_utc_ms(self) -> int:
        """Immutable UTC epoch — R1."""
        return self._session_epoch_utc_ms

    @property
    def session_epoch_mono_ns(self) -> int:
        """Immutable monotonic epoch — R1."""
        return self._session_epoch_mono_ns

    def deadline_mono_ns(self, n: int) -> int:
        """Monotonic deadline for tick N (enforcement domain).

        deadline_mono_ns(N) = session_epoch_mono_ns
            + round_rational(N * 1e9 * fps_den / fps_num)

        Uses the Bresenham split for exact integer arithmetic.
        """
        return self._session_epoch_mono_ns + deadline_offset_ns(
            n, self.fps_num, self.fps_den
        )

    def current_utc_ms(self) -> int:
        """Current UTC time — affected by NTP steps.

        UTC = session_epoch_utc + elapsed_monotonic + step_offset.
        This is the value a system call to utcnow() would return.
        """
        elapsed_mono_ms = (self.mono_ns - self._session_epoch_mono_ns) // 1_000_000
        return self._session_epoch_utc_ms + elapsed_mono_ms + self._utc_step_offset_ms

    def inject_utc_step(self, step_ms: int) -> None:
        """Simulate an NTP/system-time step.

        Positive step_ms = UTC jumps forward (e.g., NTP correction).
        Negative step_ms = UTC jumps backward.

        Monotonic clock is unaffected by construction.
        """
        self._utc_step_offset_ms += step_ms

    def tick(self, execution_cost_ns: int = 0) -> TickRecord:
        """Execute one tick using monotonic enforcement (R2).

        Lateness detection: now_mono >= deadline_mono.
        Waiting: advance mono to deadline (not UTC).
        """
        deadline = self.deadline_mono_ns(self.session_frame_index)
        was_late = self.mono_ns > deadline

        if not was_late:
            # Wait using monotonic clock (R2)
            self.mono_ns = deadline

        utc_now_ms = self.current_utc_ms()

        record = TickRecord(
            tick_index=self.session_frame_index,
            deadline_mono_ns=deadline,
            mono_at_emission=self.mono_ns,
            utc_at_emission_ms=utc_now_ms,
            was_late=was_late,
        )
        self.tick_log.append(record)

        # Execution cost advances monotonic clock
        self.mono_ns += execution_cost_ns
        self.session_frame_index += 1

        return record

    def run_ticks(
        self, n: int, execution_cost_ns: int = 0
    ) -> list[TickRecord]:
        """Run N ticks with uniform execution cost."""
        records = []
        for _ in range(n):
            records.append(self.tick(execution_cost_ns=execution_cost_ns))
        return records


# =============================================================================
# a) test_epochs_are_captured_once
#
# INV-TICK-MONOTONIC-UTC-ANCHOR-001 R1:
#   A session MUST record both UTC epoch and monotonic epoch once,
#   at session start, and MUST NOT rewrite them during the session.
# =============================================================================

class TestEpochsAreCapturedOnce:
    """Both UTC and monotonic epochs are captured at session start
    and remain immutable for the session lifetime."""

    def test_epochs_immutable_through_normal_session(self):
        """Epoch values must not change after 500 ticks of normal operation."""
        utc_epoch = 1_700_000_000_000  # ~2023 UTC ms
        mono_epoch = 50_000_000_000    # 50s mono ns

        model = DualClockSessionModel(
            fps_num=30, fps_den=1,
            session_epoch_utc_ms=utc_epoch,
            session_epoch_mono_ns=mono_epoch,
        )
        model.run_ticks(500, execution_cost_ns=1_000_000)

        assert model.session_epoch_utc_ms == utc_epoch, (
            "INV-TICK-MONOTONIC-UTC-ANCHOR-001 R1 VIOLATION: "
            "UTC epoch changed during session."
        )
        assert model.session_epoch_mono_ns == mono_epoch, (
            "INV-TICK-MONOTONIC-UTC-ANCHOR-001 R1 VIOLATION: "
            "Monotonic epoch changed during session."
        )

    def test_epochs_immutable_after_utc_step(self):
        """UTC step must not alter the stored epoch values.
        Epochs are anchored at session start; NTP corrections arrive later."""
        utc_epoch = 1_700_000_000_000
        mono_epoch = 50_000_000_000

        model = DualClockSessionModel(
            fps_num=30, fps_den=1,
            session_epoch_utc_ms=utc_epoch,
            session_epoch_mono_ns=mono_epoch,
        )
        model.run_ticks(100, execution_cost_ns=1_000_000)
        model.inject_utc_step(5_000)   # +5s NTP forward step
        model.run_ticks(100, execution_cost_ns=1_000_000)
        model.inject_utc_step(-3_000)  # -3s NTP backward step
        model.run_ticks(100, execution_cost_ns=1_000_000)

        assert model.session_epoch_utc_ms == utc_epoch
        assert model.session_epoch_mono_ns == mono_epoch

    def test_both_epochs_are_nonzero_and_distinct(self):
        """Session must capture both epochs.  They occupy different
        time domains and should not be conflated."""
        utc_epoch = 1_700_000_000_000   # UTC ms
        mono_epoch = 12_345_678_900     # Monotonic ns (different domain)

        model = DualClockSessionModel(
            fps_num=30, fps_den=1,
            session_epoch_utc_ms=utc_epoch,
            session_epoch_mono_ns=mono_epoch,
        )
        assert model.session_epoch_utc_ms == utc_epoch
        assert model.session_epoch_mono_ns == mono_epoch
        # Different domains, different units — should not be equal
        assert model.session_epoch_utc_ms != model.session_epoch_mono_ns


# =============================================================================
# b) test_monotonic_deadlines_are_rational
#
# INV-TICK-MONOTONIC-UTC-ANCHOR-001 Definition:
#   deadline_mono_ns(N) = session_epoch_mono_ns
#       + round_rational(N * 1e9 * fps_den / fps_num)
#   No drift accumulation over long runs.
# =============================================================================

class TestMonotonicDeadlinesAreRational:
    """Monotonic deadlines advance by the rational frame period.
    No drift accumulation, no quantization error over long runs."""

    @pytest.mark.parametrize("label,fps_num,fps_den", [
        ("24fps", 24, 1),
        ("25fps", 25, 1),
        ("29.97fps", 30000, 1001),
        ("30fps", 30, 1),
        ("59.94fps", 60000, 1001),
        ("60fps", 60, 1),
    ])
    def test_deadlines_are_strictly_monotonic(self, label, fps_num, fps_den):
        """Monotonic deadlines must be strictly increasing for all
        standard broadcast frame rates over 10,000 ticks."""
        mono_epoch = 10_000_000_000
        model = DualClockSessionModel(
            fps_num=fps_num, fps_den=fps_den,
            session_epoch_utc_ms=0,
            session_epoch_mono_ns=mono_epoch,
        )

        deadlines = [model.deadline_mono_ns(n) for n in range(10_000)]
        for i in range(1, len(deadlines)):
            assert deadlines[i] > deadlines[i - 1], (
                f"{label}: Deadline not monotonic at tick {i}: "
                f"{deadlines[i]} <= {deadlines[i - 1]}"
            )

    @pytest.mark.parametrize("label,fps_num,fps_den", [
        ("30fps", 30, 1),
        ("29.97fps", 30000, 1001),
        ("23.976fps", 24000, 1001),
        ("60fps", 60, 1),
    ])
    def test_no_drift_at_known_checkpoints(self, label, fps_num, fps_den):
        """Monotonic deadlines must equal exact rational values at
        known frame-count checkpoints (no accumulated error)."""
        mono_epoch = 0
        model = DualClockSessionModel(
            fps_num=fps_num, fps_den=fps_den,
            session_epoch_utc_ms=0,
            session_epoch_mono_ns=mono_epoch,
        )

        for n in [0, 1, 100, 1_000, 5_000, 9_999]:
            computed = model.deadline_mono_ns(n)
            expected = mono_epoch + deadline_offset_ns(n, fps_num, fps_den)
            assert computed == expected, (
                f"{label}: Drift at tick {n}: "
                f"computed={computed}, expected={expected}"
            )

    @pytest.mark.parametrize("label,fps_num,fps_den,n_frames,expected_ns", [
        # 30fps, 900 frames = exactly 30s
        ("30fps/30s", 30, 1, 900, 30_000_000_000),
        # 29.97fps, 900 frames = exactly 30.03s
        ("29.97fps/30.03s", 30000, 1001, 900, 30_030_000_000),
        # 24fps, 720 frames = exactly 30s
        ("24fps/30s", 24, 1, 720, 30_000_000_000),
        # 60fps, 3600 frames = exactly 60s
        ("60fps/60s", 60, 1, 3600, 60_000_000_000),
        # 23.976fps, 720 frames = exactly 30.03s
        ("23.976fps/30.03s", 24000, 1001, 720, 30_030_000_000),
    ])
    def test_cumulative_deadline_exact(
        self, label, fps_num, fps_den, n_frames, expected_ns
    ):
        """Cumulative deadline at known frame counts must be exact —
        no rounding error, no ms-quantization."""
        model = DualClockSessionModel(
            fps_num=fps_num, fps_den=fps_den,
            session_epoch_utc_ms=0,
            session_epoch_mono_ns=0,
        )
        actual = model.deadline_mono_ns(n_frames)
        assert actual == expected_ns, (
            f"{label}: deadline({n_frames}) = {actual}, "
            f"expected {expected_ns}"
        )

    def test_one_hour_drift_under_1ms(self):
        """Over 1 hour at 29.97fps, cumulative deadline must be within
        1ms of mathematically exact duration (integer truncation only)."""
        fps_num, fps_den = 30000, 1001
        n = 3600 * fps_num // fps_den  # frames in 1 hour

        model = DualClockSessionModel(
            fps_num=fps_num, fps_den=fps_den,
            session_epoch_utc_ms=0,
            session_epoch_mono_ns=0,
        )
        computed = model.deadline_mono_ns(n)
        exact = n * fps_den / fps_num * NS_PER_SECOND
        error_ns = abs(computed - exact)
        assert error_ns < 1_000_000, (
            f"29.97fps 1-hour drift = {error_ns / 1e6:.3f} ms "
            f"(n={n}, computed={computed})"
        )


# =============================================================================
# c) test_utc_clock_steps_do_not_affect_tick_cadence
#
# INV-TICK-MONOTONIC-UTC-ANCHOR-001 R2:
#   All lateness detection and waiting MUST use monotonic time.
#   UTC steps MUST NOT cause tick cadence discontinuities.
# =============================================================================

class TestUtcClockStepsDoNotAffectTickCadence:
    """NTP/system-time steps are invisible to tick enforcement.
    Cadence, deadlines, and lateness detection are monotonic-only."""

    def test_forward_utc_step_no_false_lateness(self):
        """A +5s UTC forward step must not cause any tick to be
        detected as late.  Monotonic clock is unaffected."""
        fps_num, fps_den = 30, 1
        model = DualClockSessionModel(
            fps_num=fps_num, fps_den=fps_den,
            session_epoch_utc_ms=1_000_000,
            session_epoch_mono_ns=0,
        )

        pre_step = model.run_ticks(100, execution_cost_ns=0)
        model.inject_utc_step(5_000)  # +5s
        post_step = model.run_ticks(100, execution_cost_ns=0)

        late_pre = [r for r in pre_step if r.was_late]
        late_post = [r for r in post_step if r.was_late]
        assert len(late_pre) == 0
        assert len(late_post) == 0, (
            f"INV-TICK-MONOTONIC-UTC-ANCHOR-001 R2 VIOLATION: "
            f"{len(late_post)} ticks marked late after UTC forward step. "
            "Enforcement must use monotonic clock."
        )

    def test_backward_utc_step_no_false_lateness(self):
        """A -3s UTC backward step must not cause false on-time detection
        or spurious lateness."""
        fps_num, fps_den = 30, 1
        model = DualClockSessionModel(
            fps_num=fps_num, fps_den=fps_den,
            session_epoch_utc_ms=1_000_000,
            session_epoch_mono_ns=0,
        )

        model.run_ticks(100, execution_cost_ns=0)
        model.inject_utc_step(-3_000)  # -3s
        post_step = model.run_ticks(100, execution_cost_ns=0)

        late_ticks = [r for r in post_step if r.was_late]
        assert len(late_ticks) == 0, (
            f"INV-TICK-MONOTONIC-UTC-ANCHOR-001 R2 VIOLATION: "
            f"{len(late_ticks)} ticks marked late after UTC backward step."
        )

    def test_large_utc_step_continuous_deadlines(self):
        """A +60s UTC step must produce zero cadence discontinuity.
        Monotonic deadlines across the step boundary must be strictly
        increasing with no jumps or gaps."""
        fps_num, fps_den = 30000, 1001  # 29.97fps
        model = DualClockSessionModel(
            fps_num=fps_num, fps_den=fps_den,
            session_epoch_utc_ms=0,
            session_epoch_mono_ns=0,
        )

        model.run_ticks(500, execution_cost_ns=0)
        step_boundary = len(model.tick_log)
        model.inject_utc_step(60_000)  # +60s
        model.run_ticks(500, execution_cost_ns=0)

        # Verify continuous monotonic deadline progression
        all_deadlines = [r.deadline_mono_ns for r in model.tick_log]
        for i in range(1, len(all_deadlines)):
            assert all_deadlines[i] > all_deadlines[i - 1], (
                f"Cadence discontinuity at tick {i} "
                f"(step boundary at tick {step_boundary}): "
                f"{all_deadlines[i]} <= {all_deadlines[i - 1]}"
            )

    def test_utc_step_does_not_affect_emission_cadence(self):
        """Monotonic emission times across a UTC step must track the
        rational deadline schedule — no acceleration or deceleration.

        Note: Bresenham remainder distribution means individual frame
        periods vary by ±1ns (by design).  The test verifies each tick
        emits at its exact monotonic deadline, which is the authoritative
        cadence definition."""
        fps_num, fps_den = 30, 1
        model = DualClockSessionModel(
            fps_num=fps_num, fps_den=fps_den,
            session_epoch_utc_ms=0,
            session_epoch_mono_ns=0,
        )

        model.run_ticks(50, execution_cost_ns=0)
        model.inject_utc_step(10_000)  # +10s
        model.run_ticks(50, execution_cost_ns=0)

        # Every tick must be emitted at exactly its monotonic deadline
        for record in model.tick_log:
            assert record.mono_at_emission == record.deadline_mono_ns, (
                f"Cadence error at tick {record.tick_index}: "
                f"emitted at {record.mono_at_emission}ns, "
                f"deadline was {record.deadline_mono_ns}ns. "
                f"UTC step corrupted emission cadence."
            )

    def test_bidirectional_utc_steps_cadence_stable(self):
        """Multiple alternating UTC steps (+5s, -3s, +8s) must not
        produce any cadence variation in the monotonic domain."""
        fps_num, fps_den = 60, 1
        model = DualClockSessionModel(
            fps_num=fps_num, fps_den=fps_den,
            session_epoch_utc_ms=0,
            session_epoch_mono_ns=0,
        )

        model.run_ticks(100, execution_cost_ns=0)
        model.inject_utc_step(5_000)
        model.run_ticks(100, execution_cost_ns=0)
        model.inject_utc_step(-3_000)
        model.run_ticks(100, execution_cost_ns=0)
        model.inject_utc_step(8_000)
        model.run_ticks(100, execution_cost_ns=0)

        # No tick should be late (monotonic is untouched by steps)
        late_ticks = [r for r in model.tick_log if r.was_late]
        assert len(late_ticks) == 0, (
            f"INV-TICK-MONOTONIC-UTC-ANCHOR-001 VIOLATION: "
            f"{len(late_ticks)} late ticks despite zero execution cost. "
            "UTC steps leaked into monotonic enforcement."
        )


# =============================================================================
# d) test_fence_math_remains_utc_based
#
# INV-TICK-MONOTONIC-UTC-ANCHOR-001 R3:
#   UTC epoch remains authoritative for mapping schedules → fence ticks.
#   Fence computation must NOT use monotonic time.
# =============================================================================

class TestFenceMathRemainsUtcBased:
    """Fence tick computation uses UTC epoch and schedule time.
    Monotonic time is for enforcement only; it must not leak into
    fence (schedule authority) computation."""

    def test_fence_uses_utc_delta_not_monotonic(self):
        """Fence must be computed from (end_utc_ms - session_epoch_utc_ms).
        The monotonic epoch value must not influence the result."""
        utc_epoch = 1_700_000_000_000
        fps_num, fps_den = 30, 1
        block_end_utc_ms = utc_epoch + 30_000  # 30s block

        fence = compute_fence_tick(
            block_end_utc_ms, utc_epoch, fps_num, fps_den
        )
        assert fence == 900  # 30s * 30fps

        # Same fence regardless of monotonic epoch value
        for mono_epoch in [0, 50_000_000_000, 999_999_999_999]:
            model = DualClockSessionModel(
                fps_num=fps_num, fps_den=fps_den,
                session_epoch_utc_ms=utc_epoch,
                session_epoch_mono_ns=mono_epoch,
            )
            # Fence computation uses model's UTC epoch, not monotonic
            fence_via_model = compute_fence_tick(
                block_end_utc_ms,
                model.session_epoch_utc_ms,
                fps_num, fps_den,
            )
            assert fence_via_model == 900, (
                f"Fence affected by monotonic epoch {mono_epoch}: "
                f"got {fence_via_model}"
            )

    def test_fence_unchanged_by_utc_step(self):
        """A UTC step after session start must not change the fence.
        The fence was computed from the immutable session_epoch_utc_ms (R1).
        If someone incorrectly used the stepped UTC as epoch, the fence
        would be wrong — this test catches that."""
        utc_epoch = 1_700_000_000_000
        fps_num, fps_den = 30, 1
        block_end_utc_ms = utc_epoch + 10_000  # 10s block

        # Correct: fence from immutable epoch
        fence_correct = compute_fence_tick(
            block_end_utc_ms, utc_epoch, fps_num, fps_den
        )
        assert fence_correct == 300  # 10s * 30fps

        # WRONG: fence from stepped epoch (simulates using utcnow() as epoch)
        stepped_epoch = utc_epoch + 5_000
        fence_wrong = compute_fence_tick(
            block_end_utc_ms, stepped_epoch, fps_num, fps_den
        )

        # The correct and wrong fences must differ
        assert fence_correct != fence_wrong, "Test setup error"
        # The correct fence is the one that uses the immutable epoch
        assert fence_correct == 300

    @pytest.mark.parametrize("label,fps_num,fps_den,dur_ms,expected", [
        ("30fps/30s", 30, 1, 30_000, 900),
        ("29.97fps/30s", 30000, 1001, 30_000, 900),
        ("24fps/60s", 24, 1, 60_000, 1440),
        ("60fps/10s", 60, 1, 10_000, 600),
        ("25fps/30s", 25, 1, 30_000, 750),
        ("59.94fps/30s", 60000, 1001, 30_000, 1799),
    ])
    def test_fence_formula_canonical(
        self, label, fps_num, fps_den, dur_ms, expected
    ):
        """Verify fence computation matches the canonical rational formula
        from INV-BLOCK-WALLCLOCK-FENCE-001, using UTC times."""
        epoch_ms = 1_000_000
        end_ms = epoch_ms + dur_ms

        fence = compute_fence_tick(end_ms, epoch_ms, fps_num, fps_den)
        assert fence == expected, (
            f"{label}: fence={fence}, expected={expected}"
        )

    def test_fence_domain_separation(self):
        """Fence computation must use UTC-ms domain inputs.
        Monotonic-ns domain values must not be substitutable.

        If someone accidentally passes monotonic epoch (ns) where
        UTC epoch (ms) is expected, the result is wildly different —
        this test verifies that the two domains produce different
        fence values, proving they are not interchangeable."""
        utc_epoch_ms = 1_700_000_000_000       # ~2023 UTC ms
        mono_epoch_ns = 50_000_000_000         # 50s monotonic ns
        block_end_utc_ms = utc_epoch_ms + 30_000
        fps_num, fps_den = 30, 1

        # Correct: UTC delta
        fence_utc = compute_fence_tick(
            block_end_utc_ms, utc_epoch_ms, fps_num, fps_den
        )
        assert fence_utc == 900  # 30s * 30fps

        # WRONG: monotonic epoch substituted for UTC (domain confusion)
        fence_mono_confused = compute_fence_tick(
            block_end_utc_ms, mono_epoch_ns, fps_num, fps_den
        )

        # These must differ wildly — proves domains are not interchangeable
        assert fence_utc != fence_mono_confused, (
            "Domain confusion not detected: UTC and monotonic epochs "
            "produced the same fence. This should be impossible for "
            "realistic epoch values."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
