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
  explicit OutputClock(double fps);

  // Record session start time.  Must be called exactly once before
  // WaitForFrame() or SessionStartTime().
  void Start();

  // Convert a session-global frame index to a 90 kHz PTS value.
  // Monotonic by construction: PTS(N) = N * frame_duration_90k_.
  int64_t FrameIndexToPts90k(int64_t session_frame_index) const;

  // Frame duration in milliseconds (truncated, e.g. 33 for 30 fps).
  int64_t FrameDurationMs() const;

  // Frame duration in 90 kHz ticks (e.g. 3000 for 30 fps).
  int64_t FrameDuration90k() const;

  // Sleep until the absolute wall-clock deadline for frame N.
  // Returns the actual wake-up time (for inter-frame gap measurement).
  // Prevents drift accumulation: deadline = session_start_ + N * frame_duration.
  std::chrono::steady_clock::time_point WaitForFrame(int64_t session_frame_index);

  // Retrieve the time_point recorded by Start().
  std::chrono::steady_clock::time_point SessionStartTime() const;

 private:
  double fps_;
  int64_t frame_duration_ms_;   // e.g. 33 for 30 fps
  int64_t frame_duration_90k_;  // e.g. 3000 for 30 fps
  std::chrono::steady_clock::time_point session_start_;
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_OUTPUT_CLOCK_HPP_
