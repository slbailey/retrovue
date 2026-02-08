// Repository: Retrovue-playout
// Component: Output Clock
// Purpose: Frame-indexed session clock for PipelineManager
// Contract Reference: PlayoutAuthorityContract.md
// Copyright (c) 2025 RetroVue
//
// OutputClock provides absolute-deadline pacing and PTS generation keyed
// to a monotonically increasing session frame index.  It is intentionally
// decoupled from block boundaries — the same clock runs for the entire
// playout session, producing drift-free timing by sleeping to absolute
// wall-clock deadlines rather than accumulating relative sleeps.

#ifndef RETROVUE_BLOCKPLAN_OUTPUT_CLOCK_HPP_
#define RETROVUE_BLOCKPLAN_OUTPUT_CLOCK_HPP_

#include <chrono>
#include <cstdint>

namespace retrovue::blockplan {

class OutputClock {
 public:
  // Construct with rational FPS (fps_num/fps_den).
  // Pacing deadlines use nanosecond-resolution integer arithmetic.
  OutputClock(int64_t fps_num, int64_t fps_den);

  // Record session start time.  Must be called exactly once before
  // WaitForFrame() or SessionStartTime().
  void Start();

  // Convert a session-global frame index to a 90 kHz PTS value.
  // Monotonic by construction: PTS(N) = N * frame_duration_90k_.
  int64_t FrameIndexToPts90k(int64_t session_frame_index) const;

  // Frame duration in milliseconds (rounded, e.g. 33 for 30 fps).
  // Non-authoritative — used only for diagnostics/logging.
  int64_t FrameDurationMs() const;

  // Frame duration in 90 kHz ticks (e.g. 3000 for 30 fps).
  int64_t FrameDuration90k() const;

  // Sleep until the absolute wall-clock deadline for frame N.
  // Returns the actual wake-up time (for inter-frame gap measurement).
  //
  // Deadline uses nanosecond-resolution rational arithmetic:
  //   deadline_ns(N) = N * ns_per_frame_whole_ + (N * ns_per_frame_rem_) / fps_num_
  // This is exact for all standard broadcast frame rates and eliminates
  // the cumulative drift from ms-quantized pacing.
  std::chrono::steady_clock::time_point WaitForFrame(int64_t session_frame_index);

  // Compute the absolute monotonic deadline time_point for frame N.
  // Pure arithmetic — no side effects, no sleeping.
  // INV-TICK-MONOTONIC-UTC-ANCHOR-001: Deadline anchored to session
  // monotonic epoch, immune to UTC clock steps.
  std::chrono::steady_clock::time_point DeadlineFor(int64_t session_frame_index) const;

  // Return the UTC epoch (ms since Unix epoch) captured at Start().
  // INV-TICK-MONOTONIC-UTC-ANCHOR-001: UTC remains the schedule authority
  // for fence math; monotonic is the enforcement anchor.
  int64_t SessionEpochUtcMs() const;

  // Compute the exact nanosecond offset for frame N from session start.
  // Pure arithmetic — no side effects, no sleeping.  Exposed for testing.
  std::chrono::nanoseconds DeadlineOffsetNs(int64_t session_frame_index) const;

  // Retrieve the time_point recorded by Start().
  std::chrono::steady_clock::time_point SessionStartTime() const;

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
