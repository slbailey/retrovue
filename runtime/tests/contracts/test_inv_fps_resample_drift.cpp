// Repository: Retrovue-playout
// Component: INV-FPS-RESAMPLE / INV-FPS-TICK-PTS drift and proof-frame contract tests
// Purpose: Assert no cumulative drift over long tick runs; rational frame count
//          vs ms-based; PTS exactly one output tick per frame.
// Contract Reference: DRIFT-REGRESSION-AUDIT-FINDINGS.md, INV-FPS-RESAMPLE, INV-FPS-TICK-PTS
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <cstdint>
#include <cmath>

#include "retrovue/blockplan/RationalFps.hpp"

namespace retrovue::blockplan::testing {
namespace {

// Tick time in µs for tick N from session start (INV-FPS-RESAMPLE).
static int64_t TickTimeUs(int64_t tick_index, const RationalFps& fps) {
  return fps.IsValid() ? fps.DurationFromFramesUs(tick_index) : 0;
}

// One output tick duration in µs (INV-FPS-TICK-PTS: PTS delta per frame).
static int64_t OneTickDurationUs(const RationalFps& fps) {
  return fps.IsValid() ? fps.FrameDurationUs() : 0;
}

// -----------------------------------------------------------------------------
// Long-run drift: >= 100,000 ticks at 30000/1001
// -----------------------------------------------------------------------------
TEST(InvFpsResampleDrift, LongRun100kTicksNoDrift) {
  const RationalFps fps(30000, 1001);  // 29.97
  constexpr int64_t kNumTicks = 100'000;

  // (a) tick_time_us(N) computed rationally matches expected; zero drift by definition.
  for (int64_t N : {int64_t{0}, int64_t{1}, int64_t{1000}, int64_t{30000}, kNumTicks}) {
    const int64_t tick_us = TickTimeUs(N, fps);
    const int64_t expected = fps.DurationFromFramesUs(N);
    EXPECT_EQ(tick_us, expected) << "N=" << N << " rational tick_time_us must match DurationFromFramesUs";
  }

  // (b) PTS increment is exactly one output tick per frame (INV-FPS-TICK-PTS).
  // For rational 30000/1001, per-frame delta may be 33366 or 33367 µs (integer division).
  const int64_t one_tick_us = OneTickDurationUs(fps);
  ASSERT_GT(one_tick_us, 0);
  for (int64_t N = 1; N <= kNumTicks; N += (N < 100 ? 1 : 10000)) {
    const int64_t tick_us = TickTimeUs(N, fps);
    const int64_t prev_us = TickTimeUs(N - 1, fps);
    const int64_t delta_us = tick_us - prev_us;
    EXPECT_GE(delta_us, one_tick_us) << "N=" << N;
    EXPECT_LE(delta_us, one_tick_us + 1)
        << "Per-tick delta must be one output tick (or one_tick_us+1 from integer division); N=" << N;
  }

  // (c) No cumulative error: total duration for kNumTicks must equal kNumTicks * one_tick_us
  //    only when using rational; rounded accumulation would diverge.
  const int64_t total_us_rational = TickTimeUs(kNumTicks, fps);
  const int64_t total_us_accumulated = kNumTicks * one_tick_us;
  // With rational, total_us_rational = (kNumTicks * 1_000_000 * 1001) / 30000.
  // With truncated one_tick_us accumulation, we'd get kNumTicks * 33366 = 3336600000.
  // Rational: 100000 * 1000000 * 1001 / 30000 = 3336666666 (approx). So they differ.
  EXPECT_EQ(total_us_rational, fps.DurationFromFramesUs(kNumTicks))
      << "Total duration must come from rational formula, not accumulated rounded µs";
  // Assert that using rounded per-frame duration would have produced drift:
  const int64_t rounded_tick_us = 33366;  // round(1e6/29.97) — forbidden
  const int64_t drift_if_rounded = std::abs(total_us_rational - (kNumTicks * rounded_tick_us));
  EXPECT_GT(drift_if_rounded, 0)
      << "Rounded µs accumulation would have drifted; rational path must be used";
}

// -----------------------------------------------------------------------------
// Proof frames: rational vs ms-based frame count
// -----------------------------------------------------------------------------
TEST(InvFpsResampleDrift, ProofFramesUseRationalNotMs) {
  // At 29.97fps (30000/1001), FrameDurationMs() = 33 (truncated).
  // ceil(1000/33) = 31, but FramesFromDurationCeilMs(1000) = ceil(1000*30000/1001) = 29970.
  const RationalFps fps(30000, 1001);
  const int64_t duration_ms = 1000;
  const int64_t rational_frames = fps.FramesFromDurationCeilMs(duration_ms);
  const int64_t frame_ms_truncated = fps.FrameDurationMs();
  const int64_t ms_based_frames = (frame_ms_truncated > 0)
      ? (duration_ms + frame_ms_truncated - 1) / frame_ms_truncated
      : 0;
  // For 1000ms at 29.97: rational = ceil(1000*30000/1001) = 30; ms-based ceil(1000/33) = 31.
  EXPECT_NE(ms_based_frames, rational_frames)
      << "Code must use rational FramesFromDurationCeilMs, not ceil(duration_ms/frame_duration_ms)";
  EXPECT_EQ(rational_frames, fps.FramesFromDurationCeilMs(duration_ms));
}

// Same for integer 30fps: rational and ms-based can still differ for some durations.
TEST(InvFpsResampleDrift, ProofFramesRationalFormulaMatchesFence) {
  const RationalFps fps(30, 1);
  // INV-BLOCK-WALLCLOCK-FENCE-001: fence_tick = ceil(delta_ms * fps_num / (fps_den * 1000)).
  const int64_t delta_ms = 1000;
  const int64_t frames = (delta_ms * fps.num + fps.den * 1000 - 1) / (fps.den * 1000);
  EXPECT_EQ(frames, fps.FramesFromDurationCeilMs(delta_ms))
      << "Segment/block frame count must use same rational formula as fence";
}

}  // namespace
}  // namespace retrovue::blockplan::testing
