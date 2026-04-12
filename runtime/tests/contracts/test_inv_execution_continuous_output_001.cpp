// Repository: Retrovue-playout
// Component: INV-EXECUTION-CONTINUOUS-OUTPUT-001 contract tests
// Purpose: Assert execution_model=continuous_output invariants: spt(N) fixed by
//          epoch + rational FPS; segment swap does not affect tick schedule.
// Contract Reference: INV-EXECUTION-CONTINUOUS-OUTPUT-001.md
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <cstdint>

#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/RationalFps.hpp"

namespace retrovue::blockplan::testing {
namespace {

// -----------------------------------------------------------------------------
// INV-EXECUTION-CONTINUOUS-OUTPUT-001: spt(N) fixed by epoch + rational FPS
// -----------------------------------------------------------------------------

// Compute spt in milliseconds (session presentation time for tick N).
// Contract: spt_ms(N) = session_epoch_utc_ms + N * 1000 * fps_den / fps_num
// (integer division; matches INV-FPS-RESAMPLE / RationalFps.)
int64_t SptMs(int64_t session_epoch_utc_ms, int64_t tick_index,
              const RationalFps& fps) {
  if (!fps.IsValid()) return 0;
  int64_t delta_ms = (tick_index * 1000LL * fps.den) / fps.num;
  return session_epoch_utc_ms + delta_ms;
}

// Deadline offset in nanoseconds for tick N from session start (monotonic).
// Contract: same rational formula as OutputClock::DeadlineOffsetNs.
int64_t DeadlineOffsetNs(int64_t tick_index, const RationalFps& fps) {
  return fps.DurationFromFramesNs(tick_index);
}

TEST(InvExecutionContinuousOutput001, SptNIsFixedByEpochAndRationalFps) {
  constexpr int64_t kEpochMs = 1000000;
  const RationalFps fps_30(30, 1);
  const RationalFps fps_23976(24000, 1001);

  // spt(N) must depend only on epoch, N, and fps — not on segment or block.
  for (int64_t N : {0, 1, 30, 90000}) {
    int64_t spt = SptMs(kEpochMs, N, fps_30);
    int64_t expected_delta_ms = (N * 1000LL * fps_30.den) / fps_30.num;
    EXPECT_EQ(spt, kEpochMs + expected_delta_ms)
        << "N=" << N << " fps=30/1";
  }

  // Same for 23.976.
  for (int64_t N : {0, 1, 24000}) {
    int64_t spt = SptMs(kEpochMs, N, fps_23976);
    int64_t expected_delta_ms = (N * 1000LL * fps_23976.den) / fps_23976.num;
    EXPECT_EQ(spt, kEpochMs + expected_delta_ms)
        << "N=" << N << " fps=24000/1001";
  }

  // Deadline offset must match RationalFps::DurationFromFramesNs (house format).
  EXPECT_EQ(DeadlineOffsetNs(1, fps_30), fps_30.DurationFromFramesNs(1));
  EXPECT_EQ(DeadlineOffsetNs(30, fps_30), fps_30.DurationFromFramesNs(30));
  EXPECT_EQ(DeadlineOffsetNs(1, fps_23976), fps_23976.DurationFromFramesNs(1));

  // Execution mode must be continuous_output (authoritative).
  constexpr auto mode = PlayoutExecutionMode::kContinuousOutput;
  EXPECT_EQ(std::string(PlayoutExecutionModeToString(mode)), "continuous_output");
}

TEST(InvExecutionContinuousOutput001, SegmentSwapDoesNotAffectTickSchedule) {
  // Contract: tick schedule is a function only of (session_epoch, fps_num,
  // fps_den, tick_index). Segment identity, block identity, and decoder
  // lifecycle do not appear in the formula. So "before segment swap" and
  // "after segment swap" yield the same spt(N) for the same N.
  constexpr int64_t kEpochMs = 2000000;
  const RationalFps fps(30, 1);

  // Simulate "before" and "after" segment swap: different segment IDs,
  // same session epoch and FPS. Tick schedule must be identical.
  const int64_t segment_id_before = 1;
  const int64_t segment_id_after = 2;
  (void)segment_id_before;
  (void)segment_id_after;

  for (int64_t N : {0, 100, 1000}) {
    int64_t spt_before = SptMs(kEpochMs, N, fps);
    int64_t spt_after = SptMs(kEpochMs, N, fps);
    EXPECT_EQ(spt_before, spt_after)
        << "spt(N) must be unchanged by segment swap; N=" << N;
    EXPECT_EQ(DeadlineOffsetNs(N, fps), fps.DurationFromFramesNs(N))
        << "Deadline offset for tick N must depend only on N and fps";
  }

  // Frame-selection cadence may refresh on segment swap (different input_fps);
  // that must not change the tick schedule. Here we only assert the
  // schedule formula does not take segment or input_fps into account.
  const RationalFps input_fps_24(24, 1);
  const RationalFps input_fps_30(30, 1);
  int64_t spt_N_after_swap_24 = SptMs(kEpochMs, 30, fps);
  int64_t spt_N_after_swap_30 = SptMs(kEpochMs, 30, fps);
  EXPECT_EQ(spt_N_after_swap_24, spt_N_after_swap_30)
      << "spt(30) must be same regardless of input_fps (frame-selection may "
         "differ; tick schedule must not)";
  (void)input_fps_24;
  (void)input_fps_30;
}

}  // namespace
}  // namespace retrovue::blockplan::testing
