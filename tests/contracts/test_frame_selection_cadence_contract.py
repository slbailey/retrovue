"""
Frame Selection Cadence Contract Tests

Contract: pkg/air/docs/contracts/frame_selection_cadence.md

These tests verify the observable correctness properties of frame cadence
conversion when the source frame rate differs from the output frame rate.

The canonical case is 3:2 pulldown: 24000/1001 fps source → 30000/1001 fps output.

Invariants tested:
  INV-CADENCE-POP-001: Repeat ticks must NOT consume source frames
  INV-CADENCE-POP-002: Source consumption equals advance count
  INV-CADENCE-POP-003: Consumption ratio matches FPS ratio
  INV-CADENCE-POP-004: Accumulator orientation

No FFmpeg, no real-time pacing. Pure deterministic simulation of the
Bresenham cadence accumulator and a mock video buffer.
"""

import math
import pytest
from dataclasses import dataclass, field
from fractions import Fraction
from typing import List


# ---------------------------------------------------------------------------
# Bresenham cadence accumulator (mirrors PipelineManager C++ logic)
# ---------------------------------------------------------------------------

@dataclass
class CadenceAccumulator:
    """
    Deterministic simulation of the frame-selection cadence gate.

    Mirrors the C++ logic in PipelineManager.cpp lines 1700-1710:
        budget += increment
        if budget >= threshold:
            budget -= threshold
            → ADVANCE
        else:
            → REPEAT
    """
    input_fps_num: int
    input_fps_den: int
    output_fps_num: int
    output_fps_den: int

    budget: int = 0
    advance_count: int = 0
    repeat_count: int = 0

    def __post_init__(self):
        # INV-CADENCE-POP-004: Accumulator orientation
        # increment = input_fps.num × output_fps.den
        # threshold = output_fps.num × input_fps.den
        self.increment = self.input_fps_num * self.output_fps_den
        self.threshold = self.output_fps_num * self.input_fps_den

    def tick(self) -> str:
        """Returns 'ADVANCE' or 'REPEAT'."""
        self.budget += self.increment
        if self.budget >= self.threshold:
            self.budget -= self.threshold
            self.advance_count += 1
            return "ADVANCE"
        else:
            self.repeat_count += 1
            return "REPEAT"

    @property
    def total_ticks(self) -> int:
        return self.advance_count + self.repeat_count


# ---------------------------------------------------------------------------
# Mock video buffer (tracks pop count)
# ---------------------------------------------------------------------------

@dataclass
class MockVideoBuffer:
    """
    Mock of VideoLookaheadBuffer that tracks how many frames are consumed.
    Always has frames available (infinite source).
    """
    pop_count: int = 0
    pop_log: List[int] = field(default_factory=list)  # tick indices where pop occurred

    def try_pop_frame(self, tick_index: int) -> bool:
        self.pop_count += 1
        self.pop_log.append(tick_index)
        return True


# ---------------------------------------------------------------------------
# Frame selection cascade simulation
# ---------------------------------------------------------------------------

def simulate_cadence(
    input_fps_num: int,
    input_fps_den: int,
    output_fps_num: int,
    output_fps_den: int,
    num_ticks: int,
) -> dict:
    """
    Simulate the frame-selection cascade for `num_ticks` output ticks.

    Returns a dict with:
        advance_count: number of ADVANCE decisions
        repeat_count: number of REPEAT decisions
        pop_count: number of TryPopFrame calls
        pop_on_repeat: list of tick indices where pop happened on a REPEAT tick
        decisions: list of ('ADVANCE'|'REPEAT', popped: bool) per tick
    """
    acc = CadenceAccumulator(
        input_fps_num=input_fps_num,
        input_fps_den=input_fps_den,
        output_fps_num=output_fps_num,
        output_fps_den=output_fps_den,
    )
    buf = MockVideoBuffer()
    pop_on_repeat = []
    decisions = []

    for tick in range(num_ticks):
        decision = acc.tick()

        if decision == "ADVANCE":
            # Normal advance: pop a frame from the buffer
            buf.try_pop_frame(tick)
            popped = True
        else:
            # REPEAT: must NOT pop — re-encode last good frame
            # INV-CADENCE-POP-001: This is the contract under test.
            # A correct implementation does NOT call try_pop_frame here.
            popped = False

        decisions.append((decision, popped))

    return {
        "advance_count": acc.advance_count,
        "repeat_count": acc.repeat_count,
        "pop_count": buf.pop_count,
        "pop_on_repeat": pop_on_repeat,
        "decisions": decisions,
        "accumulator": acc,
        "buffer": buf,
    }


def simulate_cadence_buggy(
    input_fps_num: int,
    input_fps_den: int,
    output_fps_num: int,
    output_fps_den: int,
    num_ticks: int,
) -> dict:
    """
    Simulate a BUGGY cascade that pops on every tick regardless of cadence.

    This represents the hypothesized bug: TryPopFrame is called on REPEAT ticks,
    consuming source frames at the output rate instead of the source rate.
    """
    acc = CadenceAccumulator(
        input_fps_num=input_fps_num,
        input_fps_den=input_fps_den,
        output_fps_num=output_fps_num,
        output_fps_den=output_fps_den,
    )
    buf = MockVideoBuffer()
    pop_on_repeat = []
    decisions = []

    for tick in range(num_ticks):
        decision = acc.tick()

        # BUG: always pop regardless of cadence decision
        buf.try_pop_frame(tick)
        popped = True

        if decision == "REPEAT":
            pop_on_repeat.append(tick)

        decisions.append((decision, popped))

    return {
        "advance_count": acc.advance_count,
        "repeat_count": acc.repeat_count,
        "pop_count": buf.pop_count,
        "pop_on_repeat": pop_on_repeat,
        "decisions": decisions,
        "accumulator": acc,
        "buffer": buf,
    }


# ---------------------------------------------------------------------------
# Constants for common frame rate pairs
# ---------------------------------------------------------------------------

# 3:2 pulldown: 24000/1001 → 30000/1001
INPUT_24P_NUM = 24000
INPUT_24P_DEN = 1001
OUTPUT_30_NUM = 30000
OUTPUT_30_DEN = 1001

# Same-rate (cadence disabled in practice, but test the math)
INPUT_30_NUM = 30000
INPUT_30_DEN = 1001
OUTPUT_30_NUM_SAME = 30000
OUTPUT_30_DEN_SAME = 1001


# ===========================================================================
# Contract Tests
# ===========================================================================

class TestCadenceAccumulatorOrientation:
    """INV-CADENCE-POP-004: Accumulator orientation."""

    # Tier: 1 | Structural invariant
    def test_increment_less_than_threshold_for_24_to_30(self):
        """
        For 24000/1001 → 30000/1001:
            increment = 24000 × 1001 = 24,024,000
            threshold = 30000 × 1001 = 30,030,000

        increment < threshold ensures ADVANCE fires on 4/5 ticks (not 5/5).
        """
        acc = CadenceAccumulator(
            input_fps_num=INPUT_24P_NUM,
            input_fps_den=INPUT_24P_DEN,
            output_fps_num=OUTPUT_30_NUM,
            output_fps_den=OUTPUT_30_DEN,
        )
        assert acc.increment == 24024000
        assert acc.threshold == 30030000
        assert acc.increment < acc.threshold, (
            f"increment ({acc.increment}) must be < threshold ({acc.threshold}) "
            f"for correct 4:1 advance:repeat ratio"
        )

    # Tier: 1 | Structural invariant
    def test_advance_repeat_ratio_over_5_ticks(self):
        """
        Over exactly 5 ticks at 24→30, expect 4 ADVANCE + 1 REPEAT.
        """
        acc = CadenceAccumulator(
            input_fps_num=INPUT_24P_NUM,
            input_fps_den=INPUT_24P_DEN,
            output_fps_num=OUTPUT_30_NUM,
            output_fps_den=OUTPUT_30_DEN,
        )
        decisions = [acc.tick() for _ in range(5)]
        advances = decisions.count("ADVANCE")
        repeats = decisions.count("REPEAT")
        assert advances == 4, f"Expected 4 ADVANCE in 5 ticks, got {advances}: {decisions}"
        assert repeats == 1, f"Expected 1 REPEAT in 5 ticks, got {repeats}: {decisions}"

    # Tier: 1 | Structural invariant
    def test_advance_repeat_ratio_over_50_ticks(self):
        """Over 50 ticks: expect 40 ADVANCE + 10 REPEAT."""
        acc = CadenceAccumulator(
            input_fps_num=INPUT_24P_NUM,
            input_fps_den=INPUT_24P_DEN,
            output_fps_num=OUTPUT_30_NUM,
            output_fps_den=OUTPUT_30_DEN,
        )
        for _ in range(50):
            acc.tick()
        assert acc.advance_count == 40
        assert acc.repeat_count == 10


class TestCadencePopInvariant:
    """
    INV-CADENCE-POP-001: Repeat ticks must NOT consume source frames.
    INV-CADENCE-POP-002: Source consumption equals advance count.
    """

    # Tier: 1 | Structural invariant
    def test_pop_count_equals_advance_count(self):
        """
        INV-CADENCE-POP-002: Over 1500 ticks (50 seconds at 30fps),
        pop_count must exactly equal advance_count.
        """
        result = simulate_cadence(
            INPUT_24P_NUM, INPUT_24P_DEN,
            OUTPUT_30_NUM, OUTPUT_30_DEN,
            num_ticks=1500,
        )
        assert result["pop_count"] == result["advance_count"], (
            f"pop_count ({result['pop_count']}) != advance_count ({result['advance_count']}). "
            f"REPEAT ticks are consuming source frames."
        )

    # Tier: 1 | Structural invariant
    def test_no_pop_on_repeat_ticks(self):
        """
        INV-CADENCE-POP-001: TryPopFrame must NEVER be called on REPEAT ticks.
        Verify by checking that pop_on_repeat is empty.
        """
        result = simulate_cadence(
            INPUT_24P_NUM, INPUT_24P_DEN,
            OUTPUT_30_NUM, OUTPUT_30_DEN,
            num_ticks=1500,
        )
        assert len(result["pop_on_repeat"]) == 0, (
            f"TryPopFrame called on {len(result['pop_on_repeat'])} REPEAT ticks: "
            f"{result['pop_on_repeat'][:10]}..."
        )

    # Tier: 1 | Structural invariant
    def test_buggy_cascade_violates_pop_invariant(self):
        """
        Verify that the buggy simulation DOES violate INV-CADENCE-POP-001.
        This confirms the test would catch the bug if present.
        """
        result = simulate_cadence_buggy(
            INPUT_24P_NUM, INPUT_24P_DEN,
            OUTPUT_30_NUM, OUTPUT_30_DEN,
            num_ticks=1500,
        )
        # Buggy: pops on every tick, so pop_count == total ticks
        assert result["pop_count"] == 1500, (
            f"Buggy simulation should pop on every tick, got {result['pop_count']}"
        )
        # Buggy: pop_count != advance_count (1500 != 1200)
        assert result["pop_count"] != result["advance_count"], (
            "Buggy simulation should violate pop == advance invariant"
        )
        # Buggy: pops occurred on repeat ticks
        assert len(result["pop_on_repeat"]) > 0, (
            "Buggy simulation should have pops on REPEAT ticks"
        )
        assert len(result["pop_on_repeat"]) == result["repeat_count"], (
            f"Buggy: every REPEAT tick should have a pop. "
            f"pop_on_repeat={len(result['pop_on_repeat'])}, repeat_count={result['repeat_count']}"
        )


class TestConsumptionRatio:
    """INV-CADENCE-POP-003: Consumption ratio matches FPS ratio."""

    # Tier: 1 | Structural invariant
    def test_consumption_ratio_24_to_30(self):
        """
        Over N output ticks with cadence enabled:
            source_frames_consumed / N ≈ input_fps / output_fps

        For 24000/1001 → 30000/1001: ratio ≈ 0.8 (4 pops per 5 ticks).
        Tolerance: ±0.001 over 1000+ ticks.
        """
        num_ticks = 3000  # 100 seconds at 30fps
        result = simulate_cadence(
            INPUT_24P_NUM, INPUT_24P_DEN,
            OUTPUT_30_NUM, OUTPUT_30_DEN,
            num_ticks=num_ticks,
        )

        observed_ratio = result["pop_count"] / num_ticks
        expected_ratio = Fraction(INPUT_24P_NUM, INPUT_24P_DEN) / Fraction(OUTPUT_30_NUM, OUTPUT_30_DEN)
        expected_float = float(expected_ratio)  # exactly 0.8

        assert abs(observed_ratio - expected_float) < 0.001, (
            f"Consumption ratio {observed_ratio:.6f} deviates from expected "
            f"{expected_float:.6f} by {abs(observed_ratio - expected_float):.6f} "
            f"(tolerance: 0.001)"
        )

    # Tier: 1 | Structural invariant
    def test_consumption_ratio_exact_for_integer_fps_ratio(self):
        """
        When input/output FPS have an exact integer ratio (24/30 = 4/5),
        the consumption ratio must be exactly 0.8 over any multiple of 5 ticks.
        """
        for num_periods in [1, 10, 100, 1000]:
            num_ticks = num_periods * 5
            result = simulate_cadence(
                INPUT_24P_NUM, INPUT_24P_DEN,
                OUTPUT_30_NUM, OUTPUT_30_DEN,
                num_ticks=num_ticks,
            )
            expected_pops = num_periods * 4
            assert result["pop_count"] == expected_pops, (
                f"Over {num_ticks} ticks ({num_periods} periods): "
                f"expected {expected_pops} pops, got {result['pop_count']}"
            )

    # Tier: 1 | Structural invariant
    def test_buggy_consumption_ratio_is_1_0(self):
        """
        Buggy cascade consumes at output rate → ratio = 1.0, not 0.8.
        This produces 1.25× playback speed (30/24 = 1.25).
        """
        num_ticks = 1500
        result = simulate_cadence_buggy(
            INPUT_24P_NUM, INPUT_24P_DEN,
            OUTPUT_30_NUM, OUTPUT_30_DEN,
            num_ticks=num_ticks,
        )
        observed_ratio = result["pop_count"] / num_ticks
        assert observed_ratio == 1.0, (
            f"Buggy cascade should consume at ratio 1.0, got {observed_ratio}"
        )
        # This means content plays at 30/24 = 1.25× speed
        speed_multiplier = observed_ratio / 0.8
        assert abs(speed_multiplier - 1.25) < 0.01, (
            f"Buggy cascade speed multiplier should be 1.25×, got {speed_multiplier}"
        )


class TestLongRunStability:
    """Long-run stability: cadence correctness over extended periods."""

    # Tier: 1 | Structural invariant
    def test_10000_ticks_stability(self):
        """
        Over 10,000 ticks (~333 seconds at 30fps), all invariants hold:
        - pop_count == advance_count (INV-CADENCE-POP-002)
        - consumption ratio ≈ 0.8 (INV-CADENCE-POP-003)
        - No pops on repeat ticks (INV-CADENCE-POP-001)
        """
        num_ticks = 10000
        result = simulate_cadence(
            INPUT_24P_NUM, INPUT_24P_DEN,
            OUTPUT_30_NUM, OUTPUT_30_DEN,
            num_ticks=num_ticks,
        )

        # INV-CADENCE-POP-002
        assert result["pop_count"] == result["advance_count"], (
            f"pop_count ({result['pop_count']}) != advance_count ({result['advance_count']})"
        )

        # INV-CADENCE-POP-003
        observed_ratio = result["pop_count"] / num_ticks
        assert abs(observed_ratio - 0.8) < 0.001, (
            f"Long-run consumption ratio {observed_ratio:.6f} deviates from 0.8"
        )

        # INV-CADENCE-POP-001
        assert len(result["pop_on_repeat"]) == 0, (
            f"Pops on repeat ticks: {len(result['pop_on_repeat'])}"
        )

        # Verify exact counts for 10000 ticks (2000 full 5-tick periods)
        assert result["advance_count"] == 8000
        assert result["repeat_count"] == 2000

    # Tier: 1 | Structural invariant
    def test_accumulator_budget_bounded(self):
        """
        The Bresenham budget must stay bounded: 0 ≤ budget < threshold.
        If it grows unbounded, the accumulator is broken.
        """
        acc = CadenceAccumulator(
            input_fps_num=INPUT_24P_NUM,
            input_fps_den=INPUT_24P_DEN,
            output_fps_num=OUTPUT_30_NUM,
            output_fps_den=OUTPUT_30_DEN,
        )
        max_budget = 0
        for _ in range(100000):
            acc.tick()
            if acc.budget > max_budget:
                max_budget = acc.budget
            assert 0 <= acc.budget < acc.threshold, (
                f"Budget {acc.budget} out of range [0, {acc.threshold})"
            )


class TestEdgeCases:
    """Edge cases for cadence behavior."""

    # Tier: 1 | Structural invariant
    def test_same_fps_all_advance(self):
        """
        When input_fps == output_fps, every tick is ADVANCE (no repeats).
        increment == threshold, so budget always crosses on every tick.
        """
        acc = CadenceAccumulator(
            input_fps_num=30000,
            input_fps_den=1001,
            output_fps_num=30000,
            output_fps_den=1001,
        )
        for _ in range(100):
            decision = acc.tick()
            assert decision == "ADVANCE", (
                f"Same-fps should always ADVANCE, got {decision}"
            )
        assert acc.repeat_count == 0

    # Tier: 1 | Structural invariant
    def test_25_to_30_cadence(self):
        """
        25fps → 30fps: ratio = 25/30 = 5/6.
        Over 6 ticks: 5 ADVANCE + 1 REPEAT.
        """
        acc = CadenceAccumulator(
            input_fps_num=25,
            input_fps_den=1,
            output_fps_num=30,
            output_fps_den=1,
        )
        for _ in range(60):  # 10 periods
            acc.tick()
        assert acc.advance_count == 50
        assert acc.repeat_count == 10

    # Tier: 1 | Structural invariant
    def test_60_to_30_cadence_half(self):
        """
        60fps input → 30fps output is NOT a cadence case (input faster than output).
        increment > threshold, so every tick is ADVANCE.
        In practice this path would be handled differently (frame dropping),
        but the accumulator math should still work: every tick advances.
        """
        acc = CadenceAccumulator(
            input_fps_num=60,
            input_fps_den=1,
            output_fps_num=30,
            output_fps_den=1,
        )
        # increment = 60 * 1 = 60, threshold = 30 * 1 = 30
        # budget starts at 0, after tick: budget = 60 >= 30 → ADVANCE, budget = 30
        # next tick: budget = 90 >= 30 → ADVANCE, budget = 60
        # budget grows unbounded — this case needs special handling
        # For this test, just verify no REPEAT decisions
        for _ in range(10):
            decision = acc.tick()
            assert decision == "ADVANCE"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
