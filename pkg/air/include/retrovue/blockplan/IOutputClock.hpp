// Repository: Retrovue-playout
// Component: Output Clock Interface
// Purpose: Dependency inversion for frame pacing — RealClock (production) vs
//          DeterministicClock (tests). Fence computation, budget, PTS unchanged.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_BLOCKPLAN_IOUTPUT_CLOCK_HPP_
#define RETROVUE_BLOCKPLAN_IOUTPUT_CLOCK_HPP_

#include <chrono>
#include <cstdint>

namespace retrovue::blockplan {

// Abstract output clock: rational FPS, PTS, and optional pacing.
// Production: RealOutputClock sleeps until deadline (real-time).
// Tests: DeterministicOutputClock advances instantly (no sleep, no wait).
class IOutputClock {
 public:
  virtual ~IOutputClock() = default;

  // Record session start. Must be called exactly once before WaitForFrame/DeadlineFor.
  virtual void Start() = 0;

  // PTS and frame duration (rational fps, unchanged across implementations).
  virtual int64_t FrameIndexToPts90k(int64_t session_frame_index) const = 0;
  virtual int64_t FrameDurationMs() const = 0;
  virtual int64_t FrameDuration90k() const = 0;

  // Absolute deadline for frame N (pure arithmetic, no side effects).
  virtual std::chrono::steady_clock::time_point DeadlineFor(
      int64_t session_frame_index) const = 0;

  // Wait until it is time for frame N.
  // Real: sleep_until(DeadlineFor(N)); return now().
  // Deterministic: no-op, return now() immediately (instant advance).
  virtual std::chrono::steady_clock::time_point WaitForFrame(
      int64_t session_frame_index) = 0;

  virtual int64_t SessionEpochUtcMs() const = 0;
  virtual std::chrono::steady_clock::time_point SessionStartTime() const = 0;
  virtual std::chrono::nanoseconds DeadlineOffsetNs(
      int64_t session_frame_index) const = 0;
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_IOUTPUT_CLOCK_HPP_
