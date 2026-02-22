// Repository: Retrovue-playout
// Component: Deterministic Output Clock (test only)
// Purpose: Instant advancement for tests; same PTS/fence math as OutputClock.
// Copyright (c) 2025 RetroVue

#include "DeterministicOutputClock.hpp"

#include <chrono>
#include <cmath>

namespace retrovue::blockplan {

static constexpr int64_t kNanosPerSecond = 1'000'000'000;

DeterministicOutputClock::DeterministicOutputClock(int64_t fps_num, int64_t fps_den)
    : fps_num_(fps_num),
      fps_den_(fps_den),
      ns_per_frame_whole_((kNanosPerSecond * fps_den) / fps_num),
      ns_per_frame_rem_((kNanosPerSecond * fps_den) % fps_num),
      frame_duration_ms_(static_cast<int64_t>(
          std::round(1000.0 * static_cast<double>(fps_den) /
                     static_cast<double>(fps_num)))),
      frame_duration_90k_(static_cast<int64_t>(
          std::round(90000.0 * static_cast<double>(fps_den) /
                     static_cast<double>(fps_num)))),
      session_start_(std::chrono::steady_clock::time_point{}) {}

void DeterministicOutputClock::Start() {
  session_start_ = std::chrono::steady_clock::now();
}

int64_t DeterministicOutputClock::FrameIndexToPts90k(int64_t session_frame_index) const {
  return session_frame_index * frame_duration_90k_;
}

int64_t DeterministicOutputClock::FrameDurationMs() const {
  return frame_duration_ms_;
}

int64_t DeterministicOutputClock::FrameDuration90k() const {
  return frame_duration_90k_;
}

std::chrono::steady_clock::time_point DeterministicOutputClock::DeadlineFor(
    int64_t session_frame_index) const {
  int64_t whole_ns = session_frame_index * ns_per_frame_whole_;
  int64_t rem_ns = (session_frame_index * ns_per_frame_rem_) / fps_num_;
  return session_start_ + std::chrono::nanoseconds(whole_ns + rem_ns);
}

std::chrono::steady_clock::time_point DeterministicOutputClock::WaitForFrame(
    int64_t /* session_frame_index */) {
  return std::chrono::steady_clock::now();
}

int64_t DeterministicOutputClock::SessionEpochUtcMs() const {
  return 0;
}

std::chrono::steady_clock::time_point DeterministicOutputClock::SessionStartTime() const {
  return session_start_;
}

std::chrono::nanoseconds DeterministicOutputClock::DeadlineOffsetNs(
    int64_t session_frame_index) const {
  int64_t whole_ns = session_frame_index * ns_per_frame_whole_;
  int64_t rem_ns = (session_frame_index * ns_per_frame_rem_) / fps_num_;
  return std::chrono::nanoseconds(whole_ns + rem_ns);
}

}  // namespace retrovue::blockplan
