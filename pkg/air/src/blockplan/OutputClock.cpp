// Repository: Retrovue-playout
// Component: Output Clock
// Purpose: Frame-indexed session clock for ContinuousOutput execution mode
// Contract Reference: PlayoutAuthorityContract.md
// Copyright (c) 2025 RetroVue

#include "retrovue/blockplan/OutputClock.hpp"

#include <cmath>
#include <thread>

namespace retrovue::blockplan {

OutputClock::OutputClock(double fps)
    : fps_(fps),
      frame_duration_ms_(static_cast<int64_t>(std::round(1000.0 / fps))),
      frame_duration_90k_(static_cast<int64_t>(std::round(90000.0 / fps))) {}

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

std::chrono::steady_clock::time_point OutputClock::WaitForFrame(
    int64_t session_frame_index) {
  // Absolute deadline: session_start + N * frame_duration_ms.
  // Using milliseconds for the deadline avoids sub-ms jitter from
  // accumulating relative sleeps.
  auto deadline = session_start_ +
      std::chrono::milliseconds(session_frame_index * frame_duration_ms_);
  std::this_thread::sleep_until(deadline);
  return std::chrono::steady_clock::now();
}

std::chrono::steady_clock::time_point OutputClock::SessionStartTime() const {
  return session_start_;
}

}  // namespace retrovue::blockplan
