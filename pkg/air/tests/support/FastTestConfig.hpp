// Fast Test Configuration — shared infrastructure for BlockPlan contract tests.
//
// Two modes:
//   Default (no define):  Real-time wall-clock, original durations and sleeps.
//   Fast   (RETROVUE_FAST_TEST defined):  DeterministicTimeSource, shorter
//          block durations, shorter sleeps.  Fence epoch is deterministic so
//          kBootGuardMs can be tiny (no wall-clock drift during bootstrap).
//
// Build fast mode:
//   cmake ... -DRETROVUE_FAST_TEST=1
//   cmake --build pkg/air/build -j$(nproc)
//
// All test files include this header and use the constants/helpers below.
// Production code is unchanged.

#pragma once

#include <chrono>
#include <cstdint>
#include <memory>
#include <thread>

#include "time/ITimeSource.hpp"
#include "time/SystemTimeSource.hpp"
#include "DeterministicTimeSource.hpp"
#include "retrovue/blockplan/OutputClock.hpp"
#include "DeterministicWaitStrategy.hpp"

namespace retrovue::blockplan::test_infra {

// ---- Compile-time fast-test flag ----
#ifdef RETROVUE_FAST_TEST
inline constexpr bool kFastMode = true;
#else
inline constexpr bool kFastMode = false;
#endif

// Concrete time-source type visible to test fixtures.
// Fast mode: DeterministicTimeSource (allows AdvanceNs from DeterministicWaitStrategy).
// Default:   SystemTimeSource (real wall clock).
#ifdef RETROVUE_FAST_TEST
using TestTimeSourceType = DeterministicTimeSource;
#else
using TestTimeSourceType = SystemTimeSource;
#endif

// ---- Duration constants ----
// Fast mode uses shorter values; default mode preserves the real-time behavior
// that was validated when these tests were written.

// Bootstrap gate: the audio-prime gate in PipelineManager uses steady_clock with
// a 2s timeout (kGateTimeoutMs=2000).  Pad-only blocks always hit the full timeout
// because there is no audio to prime.  The deterministic clock helps fence *math*
// (fence_epoch doesn't drift) but the real-time gate still runs.  Guard must exceed
// the 2s gate timeout.
inline constexpr int64_t kBootGuardMs   = kFastMode ? 2500 : 3000;

// Standard block duration (most tests).
inline constexpr int64_t kStdBlockMs    = kFastMode ? 500  : 5000;

// Short block duration (some multi-block tests).
inline constexpr int64_t kShortBlockMs  = kFastMode ? 200  : 1000;

// Long block duration (preroll / multi-block chains).
inline constexpr int64_t kLongBlockMs   = kFastMode ? 1000 : 10000;

// Segment block duration (multi-segment tests).
inline constexpr int64_t kSegBlockMs    = kFastMode ? 600  : 6000;

// Preloader delay (PaddedTransitionStatus test).
// Must exceed the audio-prime gate timeout (kGateTimeoutMs=2000) plus block A's
// wall-clock tick-loop duration (~kStdBlockMs at real-time 30fps) so the preloader
// is still sleeping when block A's fence fires.
inline constexpr int64_t kPreloaderMs   = kFastMode ? 4000 : 12000;

// Block-timestamp offset.  In real-time mode the fence epoch re-anchors to
// wall-clock AFTER bootstrap (~2s), so block windows must be pushed forward by
// kBootGuardMs to keep fence math positive.  In fast mode the DeterministicTimeSource
// doesn't advance, so fence_epoch == initial epoch and no offset is needed.
inline constexpr int64_t kBlockTimeOffsetMs = kFastMode ? 0 : kBootGuardMs;

// ---- Time source factory ----
// Fast mode:  DeterministicTimeSource at a fixed epoch (1 billion ms ≈ Jan 2001).
// Default:    SystemTimeSource (real wall clock).
inline std::shared_ptr<TestTimeSourceType> MakeTestTimeSource() {
#ifdef RETROVUE_FAST_TEST
    return std::make_shared<DeterministicTimeSource>(1'000'000'000LL);
#else
    return std::make_shared<SystemTimeSource>();
#endif
}

// ---- Timestamp helpers ----

// Current ms from the given test time source.
inline int64_t NowMs(const std::shared_ptr<ITimeSource>& ts) {
  return ts->NowUtcMs();
}

// Real wall-clock ms (always real, for timeout guards etc.).
inline int64_t WallNowMs() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::system_clock::now().time_since_epoch()).count();
}

// ---- Sleep helper ----
// Prefer AdvanceUntilFence(engine, FenceTickAt30fps(ms)) over SleepMs when the test
// has access to PipelineManager — then the test advances by frame count, not wall time.
// SleepMs is for tests that cannot use the tick driver (e.g. no engine, or waiting on
// external process). In fast deterministic mode, reduce SleepMs usage; gate long soak
// tests behind RETROVUE_SOAK_TESTS or SOAK label.
inline void SleepMs(int64_t ms) {
  std::this_thread::sleep_for(std::chrono::milliseconds(ms));
}

// ---- Fence tick (for AdvanceUntilFence) ----
// At 30 fps, duration_ms yields this many frames. Use with test_utils::AdvanceUntilFence
// to wait until the pipeline has emitted that many frames (no fixed sleep).
inline int64_t FenceTickAt30fps(int64_t duration_ms) {
  return (duration_ms * 30 + 999) / 1000;
}

// ---- Deterministic OutputClock factory ----
// Returns an OutputClock with DeterministicWaitStrategy (advances virtual time, no sleep).
// Replaces the former DeterministicOutputClock class — same frame math, no code duplication.
// When ts is provided in fast mode, DeterministicWaitStrategy advances ts by exactly one
// frame duration per tick — no wall-clock sleep, no cumulative drift.
inline std::shared_ptr<IOutputClock> MakeTestOutputClock(
    int64_t fps_num, int64_t fps_den,
    [[maybe_unused]] std::shared_ptr<TestTimeSourceType> ts = nullptr) {
#ifdef RETROVUE_FAST_TEST
  if (ts) {
    return std::make_shared<OutputClock>(fps_num, fps_den,
        std::make_unique<DeterministicWaitStrategy>(ts));
  }
#endif
  return std::make_shared<OutputClock>(fps_num, fps_den);
}

}  // namespace retrovue::blockplan::test_infra
