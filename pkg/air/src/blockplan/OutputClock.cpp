// Repository: Retrovue-playout
// Component: Output Clock
// Purpose: Frame-indexed session clock for PipelineManager
// Contract Reference: PlayoutAuthorityContract.md
// Copyright (c) 2025 RetroVue

#include "retrovue/blockplan/OutputClock.hpp"

namespace retrovue::blockplan {

static constexpr int64_t kNanosPerSecond = 1'000'000'000;

OutputClock::OutputClock(int64_t fps_num, int64_t fps_den,
                         std::unique_ptr<IWaitStrategy> wait_strategy)
    : fps_{fps_num, fps_den},
      frame_duration_ms_(fps_.FrameDurationMs()),
      frame_duration_90k_(((90000LL * fps_.den) + (fps_.num / 2)) / fps_.num),
      wait_strategy_(wait_strategy ? std::move(wait_strategy)
                                   : std::make_unique<RealtimeWaitStrategy>()) {}

void OutputClock::Start() {
  // INV-TICK-MONOTONIC-UTC-ANCHOR-001 R1: Monotonic epoch capture.
  // Anchors all tick deadlines to steady_clock.  Called once per session,
  // AFTER blocking I/O completes, so tick 0 is not born late.
  //
  // UTC schedule epoch is NOT captured here — it is owned by
  // PipelineManager (captured before blocking I/O) to preserve
  // fence math accuracy.  See PipelineManager::Run() §3.
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
  return std::chrono::nanoseconds(fps_.DurationFromFramesNs(session_frame_index));
}

std::chrono::steady_clock::time_point OutputClock::WaitForFrame(
    int64_t session_frame_index) {
  auto deadline = session_start_ + DeadlineOffsetNs(session_frame_index);
  wait_strategy_->WaitUntil(deadline);
  return std::chrono::steady_clock::now();
}

std::chrono::steady_clock::time_point OutputClock::SessionStartTime() const {
  return session_start_;
}

std::chrono::steady_clock::time_point OutputClock::DeadlineFor(
    int64_t session_frame_index) const {
  return session_start_ + DeadlineOffsetNs(session_frame_index);
}

int64_t OutputClock::SessionEpochUtcMs() const {
  return session_epoch_utc_ms_;
}

}  // namespace retrovue::blockplan
