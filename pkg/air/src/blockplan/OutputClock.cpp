// Repository: Retrovue-playout
// Component: Output Clock
// Purpose: Frame-indexed session clock for PipelineManager
// Contract Reference: PlayoutAuthorityContract.md
// Copyright (c) 2025 RetroVue

#include "retrovue/blockplan/OutputClock.hpp"

#include <cmath>
#include <thread>

namespace retrovue::blockplan {

static constexpr int64_t kNanosPerSecond = 1'000'000'000;

OutputClock::OutputClock(int64_t fps_num, int64_t fps_den)
    : fps_num_(fps_num),
      fps_den_(fps_den),
      // Rational pacing: frame period in nanoseconds split into whole + remainder.
      // ns_total = 1_000_000_000 * fps_den (nanoseconds per frame numerator)
      // ns_per_frame_whole = ns_total / fps_num  (integer floor)
      // ns_per_frame_rem   = ns_total % fps_num  (remainder)
      ns_per_frame_whole_((kNanosPerSecond * fps_den) / fps_num),
      ns_per_frame_rem_((kNanosPerSecond * fps_den) % fps_num),
      // Legacy: ms-rounded (diagnostic only, NOT used for pacing).
      frame_duration_ms_(static_cast<int64_t>(
          std::round(1000.0 * static_cast<double>(fps_den) /
                     static_cast<double>(fps_num)))),
      frame_duration_90k_(static_cast<int64_t>(
          std::round(90000.0 * static_cast<double>(fps_den) /
                     static_cast<double>(fps_num)))) {}

void OutputClock::Start() {
  session_start_ = std::chrono::steady_clock::now();
}

int64_t OutputClock::FrameIndexToPts90k(int64_t session_frame_index) const {
  return session_frame_index * frame_duration_90k_;
}

int64_t OutputClock::FrameDurationMs() const {
  return frame_duration_ms_;
}

int64_t OutputClock::FrameDuration90k() const {
  return frame_duration_90k_;
}

std::chrono::nanoseconds OutputClock::DeadlineOffsetNs(
    int64_t session_frame_index) const {
  // Exact nanosecond offset for frame N:
  //   offset = N * (kNanosPerSecond * fps_den) / fps_num
  // Split to avoid overflow and floating-point:
  //   offset = N * ns_per_frame_whole_ + (N * ns_per_frame_rem_) / fps_num_
  int64_t whole_ns = session_frame_index * ns_per_frame_whole_;
  int64_t rem_ns = (session_frame_index * ns_per_frame_rem_) / fps_num_;
  return std::chrono::nanoseconds(whole_ns + rem_ns);
}

std::chrono::steady_clock::time_point OutputClock::WaitForFrame(
    int64_t session_frame_index) {
  auto deadline = session_start_ + DeadlineOffsetNs(session_frame_index);
  std::this_thread::sleep_until(deadline);
  return std::chrono::steady_clock::now();
}

std::chrono::steady_clock::time_point OutputClock::SessionStartTime() const {
  return session_start_;
}

}  // namespace retrovue::blockplan
