// Repository: Retrovue-playout
// Component: Output Clock (Real-time implementation)
// Purpose: Frame-indexed session clock for PipelineManager
// Contract Reference: PlayoutAuthorityContract.md
// Copyright (c) 2025 RetroVue
//
// OutputClock = RealOutputClock: sleeps to absolute wall-clock deadlines.
// For deterministic tests, inject DeterministicOutputClock instead (no sleep).

#ifndef RETROVUE_BLOCKPLAN_OUTPUT_CLOCK_HPP_
#define RETROVUE_BLOCKPLAN_OUTPUT_CLOCK_HPP_

#include <chrono>
#include <cstdint>

#include "retrovue/blockplan/IOutputClock.hpp"

namespace retrovue::blockplan {

class OutputClock : public IOutputClock {
 public:
  // Construct with rational FPS (fps_num/fps_den).
  OutputClock(int64_t fps_num, int64_t fps_den);

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

  // Rational pacing: frame period = (1_000_000_000 * fps_den) / fps_num nanoseconds.
  // Split into whole + remainder to avoid floating-point drift:
  //   ns_per_frame_whole_ = (1_000_000_000 * fps_den) / fps_num
  //   ns_per_frame_rem_   = (1_000_000_000 * fps_den) % fps_num
  //   deadline_ns(N) = N * ns_per_frame_whole_ + (N * ns_per_frame_rem_) / fps_num_
  int64_t ns_per_frame_whole_;
  int64_t ns_per_frame_rem_;

  // Legacy values for backward-compatible APIs (diagnostics only).
  int64_t frame_duration_ms_;   // round(1000 * fps_den / fps_num)
  int64_t frame_duration_90k_;  // round(90000 * fps_den / fps_num)

  std::chrono::steady_clock::time_point session_start_;

  // INV-TICK-MONOTONIC-UTC-ANCHOR-001: UTC epoch captured alongside
  // monotonic epoch at Start().  Used for fence math (schedule authority).
  int64_t session_epoch_utc_ms_ = 0;
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_OUTPUT_CLOCK_HPP_
