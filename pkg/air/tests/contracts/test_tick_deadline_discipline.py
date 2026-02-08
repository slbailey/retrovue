"""
Contract Tests: INV-TICK-DEADLINE-DISCIPLINE-001

Contract reference:
    pkg/air/docs/contracts/INV-TICK-DEADLINE-DISCIPLINE-001.md

These tests prove that wall-clock authority cannot be moved by execution.
Tick deadlines are epoch-derived, immutable, and anchored to the session's
rational FPS timebase.  Execution overruns are adversarial conditions used
to attempt to violate authority; they must be powerless to shift time.

Tests assert authority outcomes only:
  - tick index
  - wall-clock alignment
  - fence position
  - deadline immutability

Tests do NOT assert:
  - fallback frame types (freeze vs pad vs black)
  - recovery strategies or adaptation logic
  - frame content or producer state

All tests are deterministic and require no media files, AIR process,
or wall-clock sleeps.

Copyright (c) 2025 RetroVue
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

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


def expected_tick_at_time(elapsed_ns: int, fps_num: int, fps_den: int) -> int:
    """Inverse of deadline_offset_ns: given wall-clock offset, return the
    largest tick index N whose deadline <= elapsed_ns.

    tick = floor(elapsed_ns * fps_num / (fps_den * 1e9))
    """
    return (elapsed_ns * fps_num) // (fps_den * NS_PER_SECOND)


# =============================================================================
# Model: Tick loop with wall-clock simulation and execution-cost injection
# =============================================================================

@dataclass
class TickRecord:
    """What happened on one output tick."""
    tick_index: int
    deadline_ns: int        # Epoch-derived scheduled deadline
    wall_clock_ns: int      # Monotonic wall-clock time at emission
    was_late: bool          # True if wall_clock >= deadline at entry
    fence_fired: bool       # True if fence check fired on this tick


@dataclass
class FenceRecord:
    """Record of a fence firing."""
    tick_index: int
    wall_clock_ns: int


class DeadlineDisciplineModel:
    """Model of PipelineManager's tick loop with simulated wall clock.

    Enforces deadline discipline per INV-TICK-DEADLINE-DISCIPLINE-001:

      1. Deadline for tick N = f(epoch, fps, N) — pure function.
      2. If wall_clock < deadline(N): advance wall_clock to deadline (wait).
      3. If wall_clock >= deadline(N): tick is late; proceed immediately.
      4. Fence check BEFORE emission (per INV-BLOCK-WALLFENCE-004).
      5. Execution cost advances wall_clock AFTER emission.
      6. session_frame_index += 1 (exactly one per iteration).

    Execution cost injection simulates adversarial overruns without
    changing the authority model.  Overruns advance the wall clock;
    they do not move deadlines.
    """

    def __init__(
        self,
        fps_num: int,
        fps_den: int,
        session_epoch_mono_ns: int = 0,
    ) -> None:
        self.fps_num = fps_num
        self.fps_den = fps_den
        self.session_epoch_mono_ns = session_epoch_mono_ns

        # State
        self.session_frame_index: int = 0
        self.wall_clock_ns: int = session_epoch_mono_ns

        # Block fence
        self.block_fence_tick: int = 2**63 - 1  # INT64_MAX sentinel
        self.fence_log: list[FenceRecord] = []

        # Tick log
        self.tick_log: list[TickRecord] = []

    def deadline_ns(self, n: int) -> int:
        """Absolute monotonic deadline for tick N — pure function of
        (session_epoch, fps, n).  No runtime state consulted."""
        return self.session_epoch_mono_ns + deadline_offset_ns(
            n, self.fps_num, self.fps_den
        )

    def frame_period_ns(self) -> int:
        """Nominal frame period (deadline(1) - deadline(0))."""
        return deadline_offset_ns(1, self.fps_num, self.fps_den)

    def set_fence(self, fence_tick: int) -> None:
        """Set the block fence tick index."""
        self.block_fence_tick = fence_tick

    def tick(self, execution_cost_ns: int = 0) -> TickRecord:
        """Execute one tick of the output loop.

        Causal order:
          1. Compute epoch-derived deadline.
          2. Wait or detect lateness.
          3. Fence check BEFORE emission.
          4. Record tick (emission).
          5. Apply execution cost (advances wall_clock).
          6. Increment session_frame_index.
        """
        deadline = self.deadline_ns(self.session_frame_index)
        was_late = self.wall_clock_ns > deadline

        if not was_late:
            self.wall_clock_ns = deadline  # sleep_until(deadline)

        # Fence check BEFORE emission (INV-BLOCK-WALLFENCE-004)
        fence_fired = False
        if (self.block_fence_tick != 2**63 - 1
                and self.session_frame_index >= self.block_fence_tick):
            self.fence_log.append(FenceRecord(
                tick_index=self.session_frame_index,
                wall_clock_ns=self.wall_clock_ns,
            ))
            fence_fired = True
            # Reset sentinel — fence fires once per block
            self.block_fence_tick = 2**63 - 1

        # Record tick (this IS the emission point)
        record = TickRecord(
            tick_index=self.session_frame_index,
            deadline_ns=deadline,
            wall_clock_ns=self.wall_clock_ns,
            was_late=was_late,
            fence_fired=fence_fired,
        )
        self.tick_log.append(record)

        # Execution cost advances wall clock AFTER emission
        self.wall_clock_ns += execution_cost_ns

        # Advance tick index — exactly 1 per iteration
        self.session_frame_index += 1

        return record

    def run_ticks(
        self,
        n: int,
        execution_cost_ns: int = 0,
        overrun_map: Optional[dict[int, int]] = None,
    ) -> list[TickRecord]:
        """Run N ticks with optional per-tick overrun injection.

        overrun_map: {tick_index: execution_cost_ns} for specific ticks.
        All other ticks use the default execution_cost_ns.
        """
        if overrun_map is None:
            overrun_map = {}
        records = []
        for _ in range(n):
            cost = overrun_map.get(self.session_frame_index, execution_cost_ns)
            records.append(self.tick(execution_cost_ns=cost))
        return records


# =============================================================================
# a) test_deadline_schedule_is_epoch_derived
#
# INV-TICK-DEADLINE-DISCIPLINE-001 Definition + R5:
#   spt(N) = session_epoch + N * fps_den / fps_num
#   Processing duration MUST NOT affect deadline computation.
# =============================================================================

class TestDeadlineScheduleIsEpochDerived:
    """Scheduled tick deadlines derive solely from (session_epoch,
    rational FPS, tick index).  No execution state — past, present,
    or future — may influence the deadline value."""

    @pytest.mark.parametrize("label,fps_num,fps_den", [
        ("30fps", 30, 1),
        ("29.97fps", 30000, 1001),
        ("23.976fps", 24000, 1001),
        ("25fps", 25, 1),
        ("60fps", 60, 1),
        ("59.94fps", 60000, 1001),
    ])
    def test_deadlines_are_pure_function_of_epoch_fps_index(
        self, label, fps_num, fps_den
    ):
        """Deadline(N) == epoch + offset(N, fps) for every N, regardless
        of execution cost pattern."""
        epoch = 5_000_000_000  # Arbitrary non-zero epoch
        model = DeadlineDisciplineModel(fps_num, fps_den, epoch)

        # Deterministic cost pattern: alternating fast/slow ticks
        frame_ns = deadline_offset_ns(1, fps_num, fps_den)
        costs = [frame_ns // 10, frame_ns * 2] * 250  # 500 ticks

        for i, cost in enumerate(costs):
            record = model.tick(execution_cost_ns=cost)
            expected = epoch + deadline_offset_ns(i, fps_num, fps_den)
            assert record.deadline_ns == expected, (
                f"INV-TICK-DEADLINE-DISCIPLINE-001 VIOLATION at tick {i}: "
                f"deadline={record.deadline_ns}, expected={expected}. "
                f"Processing cost must not affect deadline computation."
            )

    def test_deadlines_unchanged_after_heavy_overruns(self):
        """After sustained overruns on ticks 10-29, deadlines for all
        ticks (before, during, after) remain epoch-derived.
        R5: no drift accumulation."""
        fps_num, fps_den = 30, 1
        frame_ns = deadline_offset_ns(1, fps_num, fps_den)
        model = DeadlineDisciplineModel(fps_num, fps_den)

        overruns = {i: frame_ns * 3 for i in range(10, 30)}  # 20 overruns
        model.run_ticks(100, execution_cost_ns=frame_ns // 10, overrun_map=overruns)

        for record in model.tick_log:
            expected = deadline_offset_ns(record.tick_index, fps_num, fps_den)
            assert record.deadline_ns == expected, (
                f"INV-TICK-DEADLINE-DISCIPLINE-001 R5 VIOLATION: "
                f"Tick {record.tick_index} deadline shifted by overruns. "
                f"Got {record.deadline_ns}, expected {expected}."
            )

    def test_deadline_independent_of_tick_emission_time(self):
        """Two models with identical (epoch, fps) but different execution
        costs must produce identical deadlines for every tick."""
        fps_num, fps_den = 30000, 1001
        epoch = 1_000_000_000

        model_fast = DeadlineDisciplineModel(fps_num, fps_den, epoch)
        model_slow = DeadlineDisciplineModel(fps_num, fps_den, epoch)

        frame_ns = deadline_offset_ns(1, fps_num, fps_den)
        model_fast.run_ticks(200, execution_cost_ns=0)
        model_slow.run_ticks(200, execution_cost_ns=frame_ns * 2)

        for fast_r, slow_r in zip(model_fast.tick_log, model_slow.tick_log):
            assert fast_r.deadline_ns == slow_r.deadline_ns, (
                f"Tick {fast_r.tick_index}: fast deadline "
                f"{fast_r.deadline_ns} != slow deadline {slow_r.deadline_ns}. "
                "Deadlines must be independent of execution speed."
            )


# =============================================================================
# b) test_tick_index_matches_wall_clock_under_overrun
#
# INV-TICK-DEADLINE-DISCIPLINE-001 R1 + R5:
#   At wall-clock time T: session_frame_index == expected_tick_index (± jitter).
#   Execution overruns MUST NOT permanently shift tick index.
# =============================================================================

class TestTickIndexMatchesWallClockUnderOverrun:
    """Execution overruns cause temporary lateness but the tick index
    recovers to wall-clock alignment.  Overruns are powerless to
    permanently shift the tick schedule."""

    def test_single_overrun_recovery(self):
        """A single 3x overrun at tick 50 causes transient lag.  After
        recovery, tick emissions align with their scheduled deadlines."""
        fps_num, fps_den = 30, 1
        frame_ns = deadline_offset_ns(1, fps_num, fps_den)
        normal_cost = frame_ns // 4     # 25% of frame period
        overrun_cost = frame_ns * 3     # 3 frame periods

        model = DeadlineDisciplineModel(fps_num, fps_den)
        overruns = {50: overrun_cost}
        model.run_ticks(200, execution_cost_ns=normal_cost, overrun_map=overruns)

        # After recovery (~tick 53-54), all subsequent ticks must be on-time
        late_after_recovery = [
            r for r in model.tick_log[60:] if r.was_late
        ]
        assert len(late_after_recovery) == 0, (
            f"INV-TICK-DEADLINE-DISCIPLINE-001 VIOLATION: "
            f"{len(late_after_recovery)} ticks late after recovery window. "
            "Overrun permanently shifted the tick schedule."
        )

        # Final wall-clock / tick-index alignment
        final_elapsed = model.wall_clock_ns - model.session_epoch_mono_ns
        expected = expected_tick_at_time(final_elapsed, fps_num, fps_den)
        actual = model.session_frame_index
        assert abs(actual - expected) <= 1, (
            f"Tick index misaligned at end: actual={actual}, "
            f"expected={expected}, wall_clock={model.wall_clock_ns}ns"
        )

    def test_multiple_spaced_overruns_no_cumulative_drift(self):
        """Overruns at ticks 100, 300, and 500 must each be absorbed
        independently.  No cumulative drift."""
        fps_num, fps_den = 30000, 1001  # 29.97fps
        frame_ns = deadline_offset_ns(1, fps_num, fps_den)
        normal_cost = frame_ns // 5     # 20% of frame period
        overrun_cost = frame_ns * 2     # 2x overrun

        model = DeadlineDisciplineModel(fps_num, fps_den)
        overruns = {100: overrun_cost, 300: overrun_cost, 500: overrun_cost}
        model.run_ticks(700, execution_cost_ns=normal_cost, overrun_map=overruns)

        # Alignment at end: overruns should have been absorbed
        final_elapsed = model.wall_clock_ns - model.session_epoch_mono_ns
        expected = expected_tick_at_time(final_elapsed, fps_num, fps_den)
        actual = model.session_frame_index
        assert abs(actual - expected) <= 1, (
            f"Cumulative drift: actual_tick={actual}, expected={expected}. "
            "Spaced overruns caused permanent schedule shift."
        )

    @pytest.mark.parametrize("label,fps_num,fps_den", [
        ("30fps", 30, 1),
        ("29.97fps", 30000, 1001),
        ("60fps", 60, 1),
    ])
    def test_zero_cost_baseline_exact_alignment(self, label, fps_num, fps_den):
        """Under zero execution cost, every tick emits exactly at its
        scheduled deadline.  Baseline for wall-clock alignment."""
        model = DeadlineDisciplineModel(fps_num, fps_den)
        model.run_ticks(1000, execution_cost_ns=0)

        for record in model.tick_log:
            assert record.wall_clock_ns == record.deadline_ns, (
                f"Tick {record.tick_index}: emitted at "
                f"{record.wall_clock_ns}, deadline was "
                f"{record.deadline_ns}. Zero-cost ticks must be exact."
            )
            assert record.was_late is False

    def test_overrun_lag_is_bounded(self):
        """During a burst of consecutive overruns, the maximum lag
        (measured in ticks behind wall clock) is bounded by the number
        of overruns times the overrun magnitude."""
        fps_num, fps_den = 30, 1
        frame_ns = deadline_offset_ns(1, fps_num, fps_den)
        overrun_cost = frame_ns * 2  # Each overrun pushes 1 frame behind

        model = DeadlineDisciplineModel(fps_num, fps_den)
        # 5 consecutive overruns at ticks 20-24
        overruns = {i: overrun_cost for i in range(20, 25)}
        model.run_ticks(50, execution_cost_ns=frame_ns // 10, overrun_map=overruns)

        # Count how many ticks were late
        late_ticks = [r for r in model.tick_log if r.was_late]
        # Late ticks should be bounded: approximately overrun_count * overrun_magnitude / frame_period
        # 5 overruns * 2x = 10 extra frame periods → ~10 late ticks
        assert len(late_ticks) <= 15, (
            f"Excessive lateness: {len(late_ticks)} late ticks from "
            "5 overruns. Lag should be bounded."
        )
        # After the late region, ticks recover
        last_late_idx = max(r.tick_index for r in late_ticks) if late_ticks else 0
        assert last_late_idx < 40, (
            f"Late ticks persisted until tick {last_late_idx}. "
            "Recovery must occur within bounded time."
        )


# =============================================================================
# c) test_no_catchup_burst_when_execution_overruns
#
# INV-TICK-DEADLINE-DISCIPLINE-001 R3:
#   AIR MUST NOT emit multiple ticks back-to-back in a tight loop.
#   Each tick advances session_frame_index by exactly 1.
# =============================================================================

class TestNoCatchupBurstWhenExecutionOverruns:
    """Under all overrun conditions, the engine emits exactly one tick
    per loop iteration.  No catch-up bursts, no fast-forward, no
    tick-skipping."""

    def test_consecutive_overruns_one_tick_per_iteration(self):
        """Force 5 consecutive 2x overruns.  Tick indices must be
        strictly sequential [0, 1, 2, ...] — no gaps, no repeats."""
        fps_num, fps_den = 30, 1
        frame_ns = deadline_offset_ns(1, fps_num, fps_den)

        model = DeadlineDisciplineModel(fps_num, fps_den)
        overruns = {i: frame_ns * 2 for i in range(10, 15)}
        model.run_ticks(30, execution_cost_ns=frame_ns // 4, overrun_map=overruns)

        indices = [r.tick_index for r in model.tick_log]
        assert indices == list(range(30)), (
            f"INV-TICK-DEADLINE-DISCIPLINE-001 R3 VIOLATION: "
            f"Tick indices not sequential: {indices[:15]}..."
        )

    def test_massive_overrun_still_one_per_iteration(self):
        """A single 10x overrun puts us 10 frame periods behind.
        Still exactly one tick per iteration — no burst recovery."""
        fps_num, fps_den = 30, 1
        frame_ns = deadline_offset_ns(1, fps_num, fps_den)

        model = DeadlineDisciplineModel(fps_num, fps_den)
        overruns = {5: frame_ns * 10}
        model.run_ticks(30, execution_cost_ns=1_000_000, overrun_map=overruns)

        indices = [r.tick_index for r in model.tick_log]
        assert indices == list(range(30)), (
            f"INV-TICK-DEADLINE-DISCIPLINE-001 R3 VIOLATION: "
            f"Tick indices not sequential after massive overrun: "
            f"{indices[:15]}..."
        )

    def test_tick_index_increments_by_one(self):
        """Under adversarial overruns on every other tick, step between
        consecutive tick indices is always exactly 1."""
        fps_num, fps_den = 60, 1
        frame_ns = deadline_offset_ns(1, fps_num, fps_den)

        model = DeadlineDisciplineModel(fps_num, fps_den)
        # Every other tick is a 3x overrun
        overruns = {i: frame_ns * 3 for i in range(0, 200, 2)}
        model.run_ticks(200, execution_cost_ns=frame_ns // 10, overrun_map=overruns)

        for i in range(1, len(model.tick_log)):
            prev = model.tick_log[i - 1].tick_index
            curr = model.tick_log[i].tick_index
            assert curr - prev == 1, (
                f"INV-TICK-DEADLINE-DISCIPLINE-001 R3 VIOLATION: "
                f"Step from tick {prev} to {curr} is {curr - prev}, "
                "expected exactly 1."
            )

    def test_no_fast_forward_after_sustained_overrun(self):
        """After 20 consecutive 2x overruns, recovery must not fast-forward.
        The number of ticks emitted must equal the number of iterations."""
        fps_num, fps_den = 30, 1
        frame_ns = deadline_offset_ns(1, fps_num, fps_den)
        total_ticks = 100

        model = DeadlineDisciplineModel(fps_num, fps_den)
        overruns = {i: frame_ns * 2 for i in range(30, 50)}  # 20 overruns
        model.run_ticks(total_ticks, execution_cost_ns=frame_ns // 10,
                        overrun_map=overruns)

        assert len(model.tick_log) == total_ticks, (
            f"Expected {total_ticks} tick records, got {len(model.tick_log)}. "
            "Fast-forward or catch-up detected."
        )
        assert model.session_frame_index == total_ticks, (
            f"session_frame_index={model.session_frame_index}, "
            f"expected {total_ticks}."
        )


# =============================================================================
# d) test_fence_swap_occurs_on_scheduled_tick_index
#
# INV-TICK-DEADLINE-DISCIPLINE-001 R4 + INV-BLOCK-WALLCLOCK-FENCE-001:
#   Fence fires at session_frame_index == fence_tick, even under overruns.
#   Swap happens before frame emission on that tick.
#   Wall-clock time of swap aligns with fence_utc_ms (± jitter).
# =============================================================================

class TestFenceSwapOccursOnScheduledTickIndex:
    """Block swap occurs at the precomputed fence tick index.
    Execution overruns are powerless to shift fence position.
    Fence check precedes emission (structural guarantee)."""

    def test_fence_at_correct_tick_under_overruns_near_boundary(self):
        """Overruns on ticks [295, 300) must not shift the fence.
        Swap must fire at tick 300."""
        fps_num, fps_den = 30, 1
        session_epoch_ms = 1_000_000
        block_end_ms = session_epoch_ms + 10_000  # 10s block

        fence_tick = compute_fence_tick(
            block_end_ms, session_epoch_ms, fps_num, fps_den
        )
        assert fence_tick == 300  # 10s * 30fps

        frame_ns = deadline_offset_ns(1, fps_num, fps_den)
        model = DeadlineDisciplineModel(fps_num, fps_den)
        model.set_fence(fence_tick)

        # Overruns right before fence (ticks 295-299)
        overruns = {i: frame_ns * 2 for i in range(295, 300)}
        model.run_ticks(310, execution_cost_ns=frame_ns // 4, overrun_map=overruns)

        assert len(model.fence_log) == 1, (
            f"Expected 1 fence event, got {len(model.fence_log)}"
        )
        assert model.fence_log[0].tick_index == fence_tick, (
            f"INV-TICK-DEADLINE-DISCIPLINE-001 R4 VIOLATION: "
            f"Fence fired at tick {model.fence_log[0].tick_index}, "
            f"expected {fence_tick}. Overruns shifted fence position."
        )

    def test_fence_precedes_emission_on_fence_tick(self):
        """The fence check fires on the fence tick AND that same tick
        is recorded in tick_log with fence_fired=True, proving the
        fence check occurred during (before emission of) that tick."""
        fps_num, fps_den = 30, 1
        fence_tick = 100

        model = DeadlineDisciplineModel(fps_num, fps_den)
        model.set_fence(fence_tick)
        model.run_ticks(110, execution_cost_ns=0)

        # Fence must have fired on tick 100
        fence_record = model.tick_log[fence_tick]
        assert fence_record.tick_index == fence_tick
        assert fence_record.fence_fired is True, (
            f"INV-BLOCK-WALLFENCE-004 VIOLATION: Fence did not fire on "
            f"tick {fence_tick}. fence_fired={fence_record.fence_fired}"
        )

        # No fence on adjacent ticks
        assert model.tick_log[fence_tick - 1].fence_fired is False
        assert model.tick_log[fence_tick + 1].fence_fired is False

    def test_fence_wall_clock_alignment_no_overrun(self):
        """Under zero overrun, the wall-clock time of the fence swap
        must equal the epoch-derived deadline for fence_tick exactly."""
        fps_num, fps_den = 30, 1
        session_epoch_ms = 1_000_000
        block_end_ms = session_epoch_ms + 30_000  # 30s block

        fence_tick = compute_fence_tick(
            block_end_ms, session_epoch_ms, fps_num, fps_den
        )
        expected_fence_ns = deadline_offset_ns(fence_tick, fps_num, fps_den)

        model = DeadlineDisciplineModel(fps_num, fps_den)
        model.set_fence(fence_tick)
        model.run_ticks(fence_tick + 5, execution_cost_ns=0)

        assert len(model.fence_log) == 1
        assert model.fence_log[0].wall_clock_ns == expected_fence_ns, (
            f"Fence wall-clock: {model.fence_log[0].wall_clock_ns}ns, "
            f"expected {expected_fence_ns}ns"
        )

    def test_fence_wall_clock_late_but_tick_index_correct(self):
        """Under heavy overruns spanning the fence, the tick INDEX is
        still exactly fence_tick.  Wall-clock time of swap may exceed
        the deadline (because the tick is late), but the tick index —
        the timing authority — is unchanged."""
        fps_num, fps_den = 30000, 1001  # 29.97fps
        session_epoch_ms = 0
        block_end_ms = 30_000  # 30s

        fence_tick = compute_fence_tick(
            block_end_ms, session_epoch_ms, fps_num, fps_den
        )
        frame_ns = deadline_offset_ns(1, fps_num, fps_den)

        model = DeadlineDisciplineModel(fps_num, fps_den)
        model.set_fence(fence_tick)

        # Heavy overruns 2 ticks before fence
        overruns = {
            fence_tick - 2: frame_ns * 5,
            fence_tick - 1: frame_ns * 5,
        }
        model.run_ticks(fence_tick + 10, execution_cost_ns=0, overrun_map=overruns)

        assert len(model.fence_log) == 1
        assert model.fence_log[0].tick_index == fence_tick, (
            f"Fence tick shifted by overruns: "
            f"got {model.fence_log[0].tick_index}, expected {fence_tick}"
        )

        # The tick WAS late (overruns pushed wall clock past deadline)
        fence_tick_record = model.tick_log[fence_tick]
        assert fence_tick_record.was_late is True, (
            "Expected fence tick to be late under overrun conditions"
        )

    @pytest.mark.parametrize("label,fps_num,fps_den,block_dur_ms", [
        ("30fps/10s", 30, 1, 10_000),
        ("30fps/30s", 30, 1, 30_000),
        ("29.97fps/30s", 30000, 1001, 30_000),
        ("24fps/60s", 24, 1, 60_000),
        ("60fps/10s", 60, 1, 10_000),
    ])
    def test_fence_tick_matches_contract_formula(
        self, label, fps_num, fps_den, block_dur_ms
    ):
        """Verify fence_tick == ceil(delta_ms * fps_num / (fps_den * 1000))
        for all standard broadcast rates."""
        epoch_ms = 1_000_000
        end_ms = epoch_ms + block_dur_ms

        fence = compute_fence_tick(end_ms, epoch_ms, fps_num, fps_den)

        denominator = fps_den * 1000
        expected = (block_dur_ms * fps_num + denominator - 1) // denominator
        assert fence == expected, (
            f"{label}: fence={fence}, expected={expected}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
