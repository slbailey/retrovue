// Repository: Retrovue-playout
// Component: Test utilities
// Purpose: Deterministic tick driver implementation.
// Copyright (c) 2025 RetroVue

#include "deterministic_tick_driver.hpp"

#include <gtest/gtest.h>

#include "retrovue/blockplan/PipelineManager.hpp"
#include "retrovue/blockplan/PipelineMetrics.hpp"

namespace retrovue::blockplan::test_utils {

int64_t GetCurrentSessionFrameIndex(const PipelineManager* engine) {
  if (!engine) return 0;
  return engine->SnapshotMetrics().continuous_frames_emitted_total;
}

bool AdvanceUntilFence(PipelineManager* engine, int64_t fence_tick) {
  if (!engine) return fence_tick <= 0;
  // Wall-clock safety: 30s hard deadline prevents infinite hangs when
  // the engine stops early (e.g. audio underflow, fill thread failure).
  // The deterministic tick loop runs at full speed, so 30s is ample for
  // any test that should complete in milliseconds.
  constexpr auto kHardDeadline = std::chrono::seconds(30);
  auto deadline = std::chrono::steady_clock::now() + kHardDeadline;
  int64_t prev_current = -1;
  while (true) {
    auto m = engine->SnapshotMetrics();
    int64_t current = m.continuous_frames_emitted_total;
    if (current >= fence_tick) return true;
    if (current > kMaxTestTicks) {
      ADD_FAILURE() << "Test exceeded deterministic tick ceiling: "
                    << current << " > " << kMaxTestTicks
                    << " (fence_tick=" << fence_tick << ")";
      return false;
    }
    // Detect engine stall: if no progress and wall-clock deadline exceeded,
    // fail instead of spinning forever.
    if (std::chrono::steady_clock::now() > deadline) {
      ADD_FAILURE() << "AdvanceUntilFence wall-clock timeout: "
                    << "current=" << current << " fence_tick=" << fence_tick
                    << " (engine may have stopped early)";
      return false;
    }
    if (current != prev_current) {
      prev_current = current;
      std::this_thread::yield();
    } else {
      // No progress — sleep briefly to avoid burning CPU while engine
      // does real I/O (decoder open, fill thread).
      std::this_thread::sleep_for(std::chrono::microseconds(100));
    }
  }
}

void AdvanceUntilFenceOrFail(PipelineManager* engine, int64_t fence_tick) {
  if (!AdvanceUntilFence(engine, fence_tick)) {
    GTEST_FAIL() << "AdvanceUntilFence failed (ceiling or null engine)";
  }
}

}  // namespace retrovue::blockplan::test_utils
