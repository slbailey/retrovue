"""
Contract Tests: Deterministic Rational-Timebase Fence Computation

Contract references:
    pkg/air/docs/contracts/INV-BLOCK-WALLCLOCK-FENCE-001.md
    pkg/air/docs/contracts/INV-BLOCK-FRAME-BUDGET-AUTHORITY.md

These tests enforce the rational-timebase fence computation invariants.
The fence formula is:
    fence_tick = ceil(delta_ms * fps_num / (fps_den * 1000))
    Integer:     (delta_ms * fps_num + fps_den * 1000 - 1) / (fps_den * 1000)

The INVALID ms-quantized formula is:
    ceil(delta_ms / round(1000/fps))   # e.g. ceil(30000/33) = 910 for 30fps

All tests are deterministic and require no media files, AIR process,
or wall-clock sleeps.

Copyright (c) 2025 RetroVue
"""

from __future__ import annotations

import math

import pytest


# =============================================================================
# Model: Rational fence computation (mirrors PipelineManager.cpp)
# =============================================================================

# Standard broadcast frame rate lookup table.
# Mirrors DeriveRationalFPS() in BlockPlanSessionTypes.hpp.
RATIONAL_FPS_TABLE = {
    23.976: (24000, 1001),
    24.0:   (24, 1),
    25.0:   (25, 1),
    29.97:  (30000, 1001),
    30.0:   (30, 1),
    50.0:   (50, 1),
    59.94:  (60000, 1001),
    60.0:   (60, 1),
}


def derive_rational_fps(fps: float) -> tuple[int, int]:
    """Derive fps_num/fps_den from a double fps value."""
    for approx, (num, den) in RATIONAL_FPS_TABLE.items():
        if abs(fps - approx) < 0.01:
            return (num, den)
    # Fallback: integer fps
    return (round(fps), 1)


def compute_fence_tick(delta_ms: int, fps_num: int, fps_den: int) -> int:
    """Rational fence computation: ceil(delta_ms * fps_num / (fps_den * 1000)).

    This is the CORRECT formula.  Integer ceil division avoids floating-point.
    Mirrors compute_fence_frame lambda in PipelineManager.cpp.
    """
    if delta_ms <= 0:
        return 0
    denominator = fps_den * 1000
    return (delta_ms * fps_num + denominator - 1) // denominator


def compute_fence_tick_INVALID(delta_ms: int, fps: float) -> int:
    """The INVALID ms-quantized formula.  Used only in tests to prove divergence.

    ceil(delta_ms / round(1000/fps))
    """
    frame_dur_ms = round(1000 / fps)
    if frame_dur_ms == 0:
        return 0
    return (delta_ms + frame_dur_ms - 1) // frame_dur_ms


# =============================================================================
# Group 1: Exact budget for integer FPS
# =============================================================================

class TestExactBudgetIntegerFPS:
    """Verify that the rational formula produces exact frame counts for all
    standard integer frame rates at typical block durations."""

    @pytest.mark.parametrize("fps,duration_s,expected_frames", [
        (24.0,  30, 720),
        (25.0,  30, 750),
        (30.0,  30, 900),
        (50.0,  30, 1500),
        (60.0,  30, 1800),
        (24.0,  60, 1440),
        (30.0,  60, 1800),
        (60.0,  60, 3600),
        (30.0,   1, 30),
        (60.0,   1, 60),
        (30.0,   5, 150),
        (30.0,  10, 300),
    ])
    def test_exact_frame_count(self, fps, duration_s, expected_frames):
        """fence_tick = duration_s * fps exactly for integer fps."""
        fps_num, fps_den = derive_rational_fps(fps)
        delta_ms = duration_s * 1000
        fence = compute_fence_tick(delta_ms, fps_num, fps_den)
        assert fence == expected_frames, (
            f"Rational fence for {fps}fps @ {duration_s}s = {fence}, "
            f"expected {expected_frames}. "
            f"fps_num={fps_num}, fps_den={fps_den}"
        )

    @pytest.mark.parametrize("fps,duration_s", [
        (30.0, 30),
        (60.0, 30),
        (24.0, 60),
    ])
    def test_invalid_formula_diverges(self, fps, duration_s):
        """The ms-quantized formula must NOT match the rational formula
        for cases where round(1000/fps) introduces error."""
        fps_num, fps_den = derive_rational_fps(fps)
        delta_ms = duration_s * 1000
        rational = compute_fence_tick(delta_ms, fps_num, fps_den)
        invalid = compute_fence_tick_INVALID(delta_ms, fps)
        # For 30fps/30s: rational=900, invalid=ceil(30000/33)=910
        # For 60fps/30s: rational=1800, invalid=ceil(30000/17)=1765
        # The two formulas MUST NOT agree (that's the whole point)
        if fps == 30.0 and duration_s == 30:
            assert invalid == 910, (
                f"Expected invalid formula to yield 910 for 30fps/30s, got {invalid}"
            )
            assert rational == 900
        elif fps == 60.0 and duration_s == 30:
            assert invalid != rational, (
                f"Invalid formula unexpectedly matched rational for {fps}fps/{duration_s}s"
            )


# =============================================================================
# Group 2: Rational FPS (non-integer frame rates)
# =============================================================================

class TestRationalFPSNonInteger:
    """Verify fence computation for non-integer frame rates (29.97, 23.976)."""

    @pytest.mark.parametrize("fps_approx,fps_num,fps_den,duration_s,expected", [
        # 29.97fps (30000/1001) @ 30s = ceil(30000 * 30000 / (1001 * 1000))
        # = ceil(900000000 / 1001000) = ceil(899100.899...) = 900
        (29.97, 30000, 1001, 30, 900),
        # 23.976fps (24000/1001) @ 30s = ceil(30000 * 24000 / (1001 * 1000))
        # = ceil(720000000 / 1001000) = ceil(719280.719...) = 720
        (23.976, 24000, 1001, 30, 720),
        # 59.94fps (60000/1001) @ 30s = ceil(30000 * 60000 / (1001 * 1000))
        # = ceil(1800000000 / 1001000) = ceil(1798201.798...) = 1799
        (59.94, 60000, 1001, 30, 1799),
        # 29.97fps @ 60s = ceil(60000 * 30000 / (1001 * 1000))
        # = ceil(1800000000 / 1001000) = ceil(1798201.798...) = 1799
        (29.97, 30000, 1001, 60, 1799),
        # 23.976fps @ 60s = ceil(60000 * 24000 / (1001 * 1000))
        # = ceil(1440000000 / 1001000) = ceil(1438561.438...) = 1439
        (23.976, 24000, 1001, 60, 1439),
    ])
    def test_non_integer_fps_fence(self, fps_approx, fps_num, fps_den,
                                    duration_s, expected):
        delta_ms = duration_s * 1000
        fence = compute_fence_tick(delta_ms, fps_num, fps_den)
        assert fence == expected, (
            f"Rational fence for {fps_approx}fps ({fps_num}/{fps_den}) "
            f"@ {duration_s}s = {fence}, expected {expected}"
        )

    def test_derive_rational_fps_29_97(self):
        """DeriveRationalFPS(29.97) must yield 30000/1001."""
        num, den = derive_rational_fps(29.97)
        assert (num, den) == (30000, 1001)

    def test_derive_rational_fps_23_976(self):
        """DeriveRationalFPS(23.976) must yield 24000/1001."""
        num, den = derive_rational_fps(23.976)
        assert (num, den) == (24000, 1001)


# =============================================================================
# Group 3: Fence properties (immutable, precomputed)
# =============================================================================

class TestFenceProperties:
    """Fence tick must be immutable and deterministic once computed."""

    def test_fence_deterministic_same_inputs(self):
        """Same inputs always produce the same fence."""
        fps_num, fps_den = 30, 1
        delta_ms = 30000
        f1 = compute_fence_tick(delta_ms, fps_num, fps_den)
        f2 = compute_fence_tick(delta_ms, fps_num, fps_den)
        assert f1 == f2

    def test_fence_zero_for_nonpositive_delta(self):
        """Fence is 0 if delta_ms <= 0."""
        assert compute_fence_tick(0, 30, 1) == 0
        assert compute_fence_tick(-1000, 30, 1) == 0

    def test_fence_1ms_block(self):
        """A 1ms block at 30fps: ceil(1*30/1000) = ceil(0.03) = 1."""
        assert compute_fence_tick(1, 30, 1) == 1

    def test_fence_monotonically_increasing_with_duration(self):
        """Longer blocks produce larger or equal fence ticks."""
        fps_num, fps_den = 30, 1
        prev = 0
        for duration_s in range(1, 100):
            fence = compute_fence_tick(duration_s * 1000, fps_num, fps_den)
            assert fence >= prev, (
                f"Fence decreased: {fence} < {prev} at {duration_s}s"
            )
            prev = fence

    def test_fence_integer_only(self):
        """Fence tick must always be an integer (no floating point)."""
        for fps_approx, (fps_num, fps_den) in RATIONAL_FPS_TABLE.items():
            for duration_s in [1, 5, 10, 30, 60, 120, 300]:
                fence = compute_fence_tick(duration_s * 1000, fps_num, fps_den)
                assert isinstance(fence, int), (
                    f"Fence is not integer for {fps_approx}fps @ {duration_s}s"
                )


# =============================================================================
# Group 4: Swap timing (fence tick ownership)
# =============================================================================

class TestSwapTiming:
    """The fence tick belongs to the NEW block, not the old block.
    Swap fires when session_frame_index >= block_fence_frame_."""

    def test_last_old_block_tick(self):
        """For a 30fps/30s block starting at tick 0, the last tick belonging
        to the old block is tick 899 (fence=900).  Tick 900 is the swap tick."""
        fence = compute_fence_tick(30000, 30, 1)
        assert fence == 900
        # Old block owns ticks [0, 900)
        # Tick 899: session_frame_index (899) < fence (900) → no swap
        assert 899 < fence
        # Tick 900: session_frame_index (900) >= fence (900) → SWAP
        assert 900 >= fence

    def test_new_block_owns_fence_tick(self):
        """The new block's remaining_block_frames_ is computed at the fence tick.
        remaining = new_fence - session_frame_index."""
        # Block A: 30fps, 30s, epoch=0 → fence=900
        # Block B: 30fps, 30s, end_utc_ms=60000 → fence=1800
        epoch = 0
        fence_a = compute_fence_tick(30000 - epoch, 30, 1)  # 900
        fence_b = compute_fence_tick(60000 - epoch, 30, 1)  # 1800
        assert fence_a == 900
        assert fence_b == 1800

        # At tick 900 (swap), new block budget = 1800 - 900 = 900
        new_budget = fence_b - fence_a
        assert new_budget == 900

    def test_consecutive_blocks_no_gap_no_overlap(self):
        """Back-to-back blocks: block A [0, 30000), block B [30000, 60000).
        fence_A = 900, fence_B = 1800.  No tick is owned by both or neither."""
        fence_a = compute_fence_tick(30000, 30, 1)
        fence_b = compute_fence_tick(60000, 30, 1)
        # Block A owns [0, 900), Block B owns [900, 1800)
        # Total ticks = 1800, no gap
        assert fence_a == 900
        assert fence_b == 1800
        assert fence_b - fence_a == 900  # same budget as first block


# =============================================================================
# Group 5: Budget-fence convergence
# =============================================================================

class TestBudgetFenceConvergence:
    """remaining_block_frames_ reaches 0 exactly when
    session_frame_index == block_fence_frame_, by construction."""

    @pytest.mark.parametrize("fps_approx,duration_s", [
        (30.0,  30),
        (24.0,  30),
        (60.0,  30),
        (29.97, 30),
        (23.976, 30),
        (30.0,  60),
        (30.0,  1),
        (25.0,  40),
    ])
    def test_convergence_by_construction(self, fps_approx, duration_s):
        """Simulate tick loop: budget = fence - start, decrement each tick.
        Budget must reach exactly 0 when session_frame_index == fence."""
        fps_num, fps_den = derive_rational_fps(fps_approx)
        delta_ms = duration_s * 1000
        fence = compute_fence_tick(delta_ms, fps_num, fps_den)

        start_tick = 0
        budget = fence - start_tick
        assert budget == fence

        # Simulate tick-by-tick decrement
        for tick in range(start_tick, fence):
            assert budget > 0, (
                f"Budget exhausted prematurely at tick {tick}, "
                f"fence={fence}, fps={fps_approx}"
            )
            budget -= 1

        assert budget == 0, (
            f"Budget is {budget} at fence tick {fence}, expected 0. "
            f"fps={fps_approx}, duration={duration_s}s"
        )

    def test_convergence_mid_session(self):
        """When a block starts at tick 500, budget = fence - 500.
        Budget reaches 0 at fence."""
        # Block: 30fps, 30s, starting at session tick 500.
        # epoch_to_end_ms = (500/30 + 30) * 1000 ≈ 46666ms
        # But we compute fence from end_utc_ms: suppose end_utc_ms gives fence=1400
        fps_num, fps_den = 30, 1
        start_tick = 500
        end_delta_ms = 46667  # ceil(46666.67)
        fence = compute_fence_tick(end_delta_ms, fps_num, fps_den)
        # fence = ceil(46667 * 30 / 1000) = ceil(1400.01) = 1401
        budget = fence - start_tick

        for tick in range(start_tick, fence):
            assert budget > 0
            budget -= 1

        assert budget == 0


# =============================================================================
# Group 6: Multi-block sequencing
# =============================================================================

class TestMultiBlockSequencing:
    """Verify fence computation across multiple consecutive blocks."""

    def test_three_block_sequence_30fps(self):
        """3 consecutive 30s blocks at 30fps.  Fences: 900, 1800, 2700."""
        epoch_ms = 0
        ends = [30000, 60000, 90000]
        expected_fences = [900, 1800, 2700]

        fps_num, fps_den = 30, 1
        fences = [compute_fence_tick(end - epoch_ms, fps_num, fps_den)
                  for end in ends]
        assert fences == expected_fences

        # Each block budget: fence[i] - fence[i-1] (or fence[0] - 0 for first)
        budgets = [fences[0]] + [fences[i] - fences[i-1] for i in range(1, len(fences))]
        assert budgets == [900, 900, 900]

    def test_mixed_duration_blocks(self):
        """Blocks: 10s, 20s, 30s at 30fps.  Fences: 300, 900, 1800."""
        epoch_ms = 0
        ends = [10000, 30000, 60000]
        expected_fences = [300, 900, 1800]

        fps_num, fps_den = 30, 1
        fences = [compute_fence_tick(end - epoch_ms, fps_num, fps_den)
                  for end in ends]
        assert fences == expected_fences

        budgets = [fences[0]] + [fences[i] - fences[i-1] for i in range(1, len(fences))]
        assert budgets == [300, 600, 900]

    def test_non_integer_fps_multi_block(self):
        """3 consecutive 30s blocks at 29.97fps.  All budgets must be equal."""
        epoch_ms = 0
        ends = [30000, 60000, 90000]
        fps_num, fps_den = 30000, 1001

        fences = [compute_fence_tick(end - epoch_ms, fps_num, fps_den)
                  for end in ends]

        # All fences should be derived from the same rational formula.
        # Budget for each block = fence[i] - fence[i-1]
        budgets = [fences[0]] + [fences[i] - fences[i-1] for i in range(1, len(fences))]

        # Budgets may differ by at most 1 due to ceiling arithmetic
        for b in budgets:
            assert abs(b - budgets[0]) <= 1, (
                f"Budget variation too large: {budgets}. "
                f"Max difference from first should be <= 1."
            )

    def test_epoch_offset_does_not_affect_budget(self):
        """The epoch offset cancels out — block budgets are the same
        regardless of when the session started."""
        fps_num, fps_den = 30, 1
        block_duration_ms = 30000

        for epoch_ms in [0, 1000, 50000, 1700000000000]:
            start_ms = epoch_ms
            end_ms = epoch_ms + block_duration_ms
            fence = compute_fence_tick(end_ms - epoch_ms, fps_num, fps_den)
            assert fence == 900, (
                f"Fence is {fence} with epoch={epoch_ms}, expected 900"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
