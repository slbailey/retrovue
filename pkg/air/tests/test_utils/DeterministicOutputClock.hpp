// Repository: Retrovue-playout
// Component: Deterministic Output Clock (test only — test_utils)
// Purpose: Same rational FPS and PTS as OutputClock; WaitForFrame is a no-op
//          so the tick loop advances instantly. No sleep, no wait.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_TESTS_TEST_UTILS_DETERMINISTIC_OUTPUT_CLOCK_HPP_
#define RETROVUE_TESTS_TEST_UTILS_DETERMINISTIC_OUTPUT_CLOCK_HPP_

#include <chrono>
#include <cstdint>

#include "retrovue/blockplan/IOutputClock.hpp"

namespace retrovue::blockplan {

// Test clock: identical PTS/fence/deadline math, zero pacing.
// Use in tests so the BlockPlan suite runs with no real-time sleeps in the tick loop.
class DeterministicOutputClock : public IOutputClock {
 public:
  DeterministicOutputClock(int64_t fps_num, int64_t fps_den);

  void Start() override;
  int64_t FrameIndexToPts90k(int64_t session_frame_index) const override;
  int64_t FrameDurationMs() const override;
  int64_t FrameDuration90k() const override;
  std::chrono::steady_clock::time_point DeadlineFor(
      int64_t session_frame_index) const override;
  std::chrono::steady_clock::time_point WaitForFrame(
      int64_t session_frame_index) override;
  int64_t SessionEpochUtcMs() const override;
  std::chrono::steady_clock::time_point SessionStartTime() const override;
  std::chrono::nanoseconds DeadlineOffsetNs(
      int64_t session_frame_index) const override;

 private:
  int64_t fps_num_;
  int64_t fps_den_;
  int64_t ns_per_frame_whole_;
  int64_t ns_per_frame_rem_;
  int64_t frame_duration_ms_;
  int64_t frame_duration_90k_;
  std::chrono::steady_clock::time_point session_start_;
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_TESTS_TEST_UTILS_DETERMINISTIC_OUTPUT_CLOCK_HPP_
