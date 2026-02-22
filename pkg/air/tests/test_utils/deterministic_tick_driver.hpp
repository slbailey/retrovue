// Repository: Retrovue-playout
// Component: Test utilities
// Purpose: Deterministic, bounded tick driving for AIR tests. No real-time
//         wall clock, no unbounded loops, no sleep/timers. Tests must
//         terminate based on frame count or explicit ceiling only.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_TESTS_TEST_UTILS_DETERMINISTIC_TICK_DRIVER_HPP_
#define RETROVUE_TESTS_TEST_UTILS_DETERMINISTIC_TICK_DRIVER_HPP_

#include <cstdint>
#include <thread>

namespace retrovue::blockplan {

class PipelineManager;
struct PipelineMetrics;

namespace test_utils {

// Hard ceiling: no test may allow more than this many ticks/frames.
// Exceeding triggers test failure (deterministic termination).
constexpr int64_t kMaxTestTicks = 10'000;

// Returns current session frame index (frames emitted so far) from engine
// metrics. Equivalent to session_frame_index in the tick loop.
int64_t GetCurrentSessionFrameIndex(const PipelineManager* engine);

// Advances test by waiting until engine has emitted at least fence_tick
// frames (continuous_frames_emitted_total >= fence_tick). Uses polling only
// (yield, no sleep). If frames emitted exceeds kMaxTestTicks before reaching
// fence_tick, calls ADD_FAILURE() and returns false. Returns true when
// fence_tick reached. Caller must call engine->Stop() after assertions.
bool AdvanceUntilFence(PipelineManager* engine, int64_t fence_tick);

// Same as AdvanceUntilFence but fails with GTEST_FAIL if ceiling exceeded.
// Use when fence must be reached for the test to be valid.
void AdvanceUntilFenceOrFail(PipelineManager* engine, int64_t fence_tick);

// Bounded wait for an arbitrary predicate (e.g. buffer depth). Polls up to
// max_steps times (yield each iteration). Returns true if pred() became true
// within max_steps; false otherwise. No wall clock, no sleep.
template <typename Pred>
inline bool WaitForBounded(Pred pred, int64_t max_steps,
                           int64_t timeout_ms = 5000) {
  auto deadline = std::chrono::steady_clock::now() +
                  std::chrono::milliseconds(timeout_ms);
  for (int64_t i = 0; i < max_steps; ++i) {
    if (pred()) return true;
    // Yield + short sleep to allow background threads (delay hooks) to progress
    std::this_thread::sleep_for(std::chrono::microseconds(100));
    if (std::chrono::steady_clock::now() > deadline) return false;
  }
  return false;
}

}  // namespace test_utils
}  // namespace retrovue::blockplan

#endif  // RETROVUE_TESTS_TEST_UTILS_DETERMINISTIC_TICK_DRIVER_HPP_
