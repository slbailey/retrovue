// Repository: Retrovue-playout
// Component: INV-RESAMPLE-DETERMINISM-001 Contract Test
// Purpose: Prove that the time-based SourceFrameForTick() mapping produces
//          identical advance/repeat decisions to the former Bresenham
//          accumulator for all standard FPS pairs, and satisfies the
//          determinism, monotonicity, and ratio properties.
//
// Contract: docs/contracts/frame_selection_cadence.md
//           Rule INV-RESAMPLE-DETERMINISM-001
// Copyright (c) 2026 RetroVue

#include <gtest/gtest.h>

#include <cstdint>
#include <vector>

#include "retrovue/blockplan/PipelineManager.hpp"
#include "retrovue/blockplan/RationalFps.hpp"

namespace retrovue::blockplan::testing {
namespace {

using SFT = PipelineManager;

// =========================================================================
// Bresenham reference implementation (former production code, kept as oracle)
// =========================================================================
struct BresenhamState {
  int64_t budget_num = 0;
  int64_t budget_den;   // = out_num * in_den
  int64_t increment;    // = in_num * out_den

  BresenhamState(int64_t in_num, int64_t in_den,
                 int64_t out_num, int64_t out_den)
      : budget_den(out_num * in_den),
        increment(in_num * out_den) {}

  // Returns true = ADVANCE, false = REPEAT.
  bool Step() {
    budget_num += increment;
    if (budget_num >= budget_den) {
      budget_num -= budget_den;
      return true;  // ADVANCE
    }
    return false;  // REPEAT
  }
};

// =========================================================================
// Helper: run SourceFrameForTick over N ticks starting at tick_offset and
// return advance/repeat decisions as a vector of bools (true=advance).
//
// Production starts resample_tick_ at 1 (not 0) because the first frame
// is consumed via priming.  To match Bresenham phase, callers should pass
// tick_offset=1 for equivalence tests.
// =========================================================================
static std::vector<bool> RunTimeMapping(int64_t n_ticks,
                                         int64_t in_num, int64_t in_den,
                                         int64_t out_num, int64_t out_den,
                                         int64_t tick_offset = 0) {
  std::vector<bool> decisions;
  decisions.reserve(n_ticks);
  for (int64_t i = 0; i < n_ticks; ++i) {
    int64_t tick = tick_offset + i;
    int64_t curr = SFT::SourceFrameForTick(tick, in_num, in_den, out_num, out_den);
    int64_t prev = SFT::SourceFrameForTick(tick - 1, in_num, in_den, out_num, out_den);
    decisions.push_back(curr > prev);
  }
  return decisions;
}

// =========================================================================
// Helper: run Bresenham over N ticks and return advance/repeat decisions.
// =========================================================================
static std::vector<bool> RunBresenham(int64_t n_ticks,
                                       int64_t in_num, int64_t in_den,
                                       int64_t out_num, int64_t out_den) {
  BresenhamState state(in_num, in_den, out_num, out_den);
  std::vector<bool> decisions;
  decisions.reserve(n_ticks);
  for (int64_t tick = 0; tick < n_ticks; ++tick) {
    decisions.push_back(state.Step());
  }
  return decisions;
}

struct FpsPair {
  const char* label;
  int64_t in_num, in_den;
  int64_t out_num, out_den;
};

// Upsample pairs: input_fps < output_fps.  These are the cases where
// PipelineManager's frame-selection resampling is active in production.
// (Downconversion is handled by TickProducer's DROP mode, not by the
// PipelineManager cadence — both Bresenham and time-mapping say "always
// advance" for those, which is correct.)
static const FpsPair kUpsamplePairs[] = {
    {"23.976->29.97", 24000, 1001, 30000, 1001},
    {"24->30",        24,    1,    30,    1},
    {"25->29.97",     25000, 1000, 30000, 1001},
    {"25->30",        25,    1,    30,    1},
    {"30->59.94",     30000, 1001, 60000, 1001},
    {"24->59.94",     24000, 1001, 60000, 1001},
};

// All pairs including down-conversion (for monotonicity/determinism tests).
static const FpsPair kAllPairs[] = {
    {"23.976->29.97", 24000, 1001, 30000, 1001},
    {"24->30",        24,    1,    30,    1},
    {"25->29.97",     25000, 1000, 30000, 1001},
    {"25->30",        25,    1,    30,    1},
    {"50->29.97",     50000, 1000, 30000, 1001},
    {"60->30",        60,    1,    30,    1},
    {"59.94->29.97",  60000, 1001, 30000, 1001},
    {"30->59.94",     30000, 1001, 60000, 1001},
    {"24->59.94",     24000, 1001, 60000, 1001},
};

// =========================================================================
// INV-RESAMPLE-DETERMINISM-001: Equivalence to Bresenham
//
// For every upsample FPS pair, SourceFrameForTick (starting at tick 1)
// must produce the identical advance/repeat sequence as the Bresenham
// accumulator over 100,000 ticks.
//
// Production starts resample_tick_ at 1 (not 0) because the primed frame
// is consumed before cadence runs.  Bresenham starts with budget=0.
// SourceFrameForTick(1) vs SourceFrameForTick(0) matches Bresenham step 1.
// =========================================================================

TEST(TimeBasedResampling, EquivalenceToBresenham_UpsamplePairs) {
  constexpr int64_t kTicks = 100000;
  for (const auto& pair : kUpsamplePairs) {
    SCOPED_TRACE(pair.label);
    // tick_offset=1 to match production's resample_tick_ initial value.
    auto time_decisions = RunTimeMapping(kTicks, pair.in_num, pair.in_den,
                                          pair.out_num, pair.out_den, /*tick_offset=*/1);
    auto bres_decisions = RunBresenham(kTicks, pair.in_num, pair.in_den,
                                        pair.out_num, pair.out_den);
    ASSERT_EQ(time_decisions.size(), bres_decisions.size());
    for (int64_t i = 0; i < kTicks; ++i) {
      ASSERT_EQ(time_decisions[i], bres_decisions[i])
          << "Divergence at tick " << i << " for " << pair.label
          << ": time=" << time_decisions[i] << " bres=" << bres_decisions[i];
    }
  }
}

// =========================================================================
// INV-RESAMPLE-DETERMINISM-001: Pure function (deterministic)
// =========================================================================

TEST(TimeBasedResampling, PureFunction_SameInputSameOutput) {
  for (int64_t tick = 0; tick < 1000; tick += 7) {
    int64_t a = SFT::SourceFrameForTick(tick, 24000, 1001, 30000, 1001);
    int64_t b = SFT::SourceFrameForTick(tick, 24000, 1001, 30000, 1001);
    ASSERT_EQ(a, b) << "Non-deterministic at tick " << tick;
  }
}

// =========================================================================
// INV-RESAMPLE-DETERMINISM-001: Monotonically non-decreasing
// =========================================================================

TEST(TimeBasedResampling, Monotonic_AllPairs) {
  constexpr int64_t kTicks = 50000;
  for (const auto& pair : kAllPairs) {
    SCOPED_TRACE(pair.label);
    int64_t prev = -1;
    for (int64_t tick = 0; tick < kTicks; ++tick) {
      int64_t curr = SFT::SourceFrameForTick(tick, pair.in_num, pair.in_den,
                                               pair.out_num, pair.out_den);
      ASSERT_GE(curr, prev) << "Non-monotonic at tick " << tick;
      prev = curr;
    }
  }
}

// =========================================================================
// INV-CADENCE-POP-003: Consumption ratio matches FPS ratio
//
// For upsample pairs (the production use case), the fraction of ticks
// that advance must approximate input_fps / output_fps (±0.001).
// =========================================================================

TEST(TimeBasedResampling, ConsumptionRatio_UpsamplePairs) {
  constexpr int64_t kTicks = 100000;
  for (const auto& pair : kUpsamplePairs) {
    SCOPED_TRACE(pair.label);
    auto decisions = RunTimeMapping(kTicks, pair.in_num, pair.in_den,
                                     pair.out_num, pair.out_den, /*tick_offset=*/1);
    int64_t advance_count = 0;
    for (bool d : decisions) {
      if (d) advance_count++;
    }
    double actual_ratio = static_cast<double>(advance_count) / kTicks;
    double expected_ratio = (static_cast<double>(pair.in_num) / pair.in_den) /
                            (static_cast<double>(pair.out_num) / pair.out_den);
    EXPECT_NEAR(actual_ratio, expected_ratio, 0.001)
        << "Ratio mismatch for " << pair.label
        << ": actual=" << actual_ratio << " expected=" << expected_ratio;
  }
}

// =========================================================================
// Downconversion pairs: always advance (TickProducer DROP handles ratio)
//
// When input_fps >= output_fps, every tick should be ADVANCE because
// TickProducer's DROP mode already rate-matches at the decode level.
// The PipelineManager resampling gate says "always advance" and the
// time-mapping agrees: source_frame(N) > source_frame(N-1) for all N.
// =========================================================================

TEST(TimeBasedResampling, Downconversion_AlwaysAdvance) {
  static const FpsPair kDownPairs[] = {
      {"50->29.97",    50000, 1000, 30000, 1001},
      {"60->30",       60,    1,    30,    1},
      {"59.94->29.97", 60000, 1001, 30000, 1001},
  };
  constexpr int64_t kTicks = 10000;
  for (const auto& pair : kDownPairs) {
    SCOPED_TRACE(pair.label);
    auto decisions = RunTimeMapping(kTicks, pair.in_num, pair.in_den,
                                     pair.out_num, pair.out_den, /*tick_offset=*/1);
    for (int64_t i = 0; i < kTicks; ++i) {
      ASSERT_TRUE(decisions[i])
          << "Downconversion should always advance at tick " << i;
    }
  }
}

// =========================================================================
// INV-RESAMPLE-DETERMINISM-001: Tick 0 always maps to source frame 0
// =========================================================================

TEST(TimeBasedResampling, Tick0MapsToSourceFrame0) {
  for (const auto& pair : kAllPairs) {
    SCOPED_TRACE(pair.label);
    int64_t src = SFT::SourceFrameForTick(0, pair.in_num, pair.in_den,
                                            pair.out_num, pair.out_den);
    EXPECT_EQ(src, 0) << "Tick 0 should map to source frame 0";
  }
}

// =========================================================================
// INV-RESAMPLE-DETERMINISM-001: No overflow at large tick values
// =========================================================================

TEST(TimeBasedResampling, NoOverflow_LargeTick) {
  constexpr int64_t kLargeTick = (1LL << 36);  // ~25 hours at 30fps
  // 23.976->29.97: source_frame = floor(tick * 24000 * 1001 / (30000 * 1001))
  //              = floor(tick * 4/5)
  int64_t result = SFT::SourceFrameForTick(kLargeTick, 24000, 1001, 30000, 1001);
  int64_t expected = kLargeTick * 4 / 5;
  EXPECT_EQ(result, expected)
      << "Overflow at tick " << kLargeTick
      << ": got " << result << " expected " << expected;
}

// =========================================================================
// 23.976 → 29.97: Verify exact 4 advances per 5 ticks at every cycle
// =========================================================================

TEST(TimeBasedResampling, 23_976_to_29_97_ExactCyclePattern) {
  constexpr int kCycles = 200;
  for (int cycle = 0; cycle < kCycles; ++cycle) {
    // tick_offset=1 to match production phase; cycles start at 1+cycle*5.
    int64_t base = 1 + cycle * 5;
    int advance_count = 0;
    for (int64_t t = base; t < base + 5; ++t) {
      int64_t curr = SFT::SourceFrameForTick(t, 24000, 1001, 30000, 1001);
      int64_t prev = SFT::SourceFrameForTick(t - 1, 24000, 1001, 30000, 1001);
      if (curr > prev) advance_count++;
    }
    EXPECT_EQ(advance_count, 4) << "Cycle " << cycle << " (tick " << base
                                 << "): expected 4 advances per 5 ticks, got "
                                 << advance_count;
  }
}

// =========================================================================
// Identity: same FPS in == out should yield source_frame == tick
// =========================================================================

TEST(TimeBasedResampling, Identity_SameFps) {
  for (int64_t tick = 0; tick < 1000; ++tick) {
    int64_t src = SFT::SourceFrameForTick(tick, 30000, 1001, 30000, 1001);
    ASSERT_EQ(src, tick) << "Identity failed at tick " << tick;
  }
}

// =========================================================================
// Edge: negative/zero tick returns 0
// =========================================================================

TEST(TimeBasedResampling, EdgeCases_ZeroAndNegativeTick) {
  EXPECT_EQ(SFT::SourceFrameForTick(0, 24000, 1001, 30000, 1001), 0);
  EXPECT_EQ(SFT::SourceFrameForTick(-1, 24000, 1001, 30000, 1001), 0);
  EXPECT_EQ(SFT::SourceFrameForTick(-100, 24000, 1001, 30000, 1001), 0);
}

}  // namespace
}  // namespace retrovue::blockplan::testing
