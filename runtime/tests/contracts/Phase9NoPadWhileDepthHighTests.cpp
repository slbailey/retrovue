// Repository: Retrovue-playout
// Component: Phase 9 No Pad While Depth High Tests
// Purpose: Verify INV-P9-STEADY-004: No Pad While Depth High
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>
#include <chrono>
#include <thread>
#include <atomic>
#include <memory>

#include "retrovue/renderer/ProgramOutput.h"
#include "retrovue/buffer/FrameRingBuffer.h"
#include "timing/TestMasterClock.h"

using namespace retrovue;
using namespace std::chrono_literals;

namespace {

// =============================================================================
// INV-P9-STEADY-004: No Pad While Depth High
// =============================================================================
// Contract: Pad frame emission while buffer depth >= 10 is a CONTRACT VIOLATION.
// If frames exist in the buffer but are not being consumed, this indicates
// a flow control or CT tracking bug, not content starvation.
//
// MUST: Log `INV-P9-STEADY-004 VIOLATION` if pad emitted with depth >= 10.
// MUST NOT: Emit pad frames when buffer has content.
// =============================================================================

// -----------------------------------------------------------------------------
// Test Buffer: Wraps FrameRingBuffer to inject inconsistent state for testing
// -----------------------------------------------------------------------------
// This wrapper allows us to test the violation detection by making Size()
// report high depth while Pop() returns empty, simulating the race condition
// or bug that INV-P9-STEADY-004 is designed to detect.
// -----------------------------------------------------------------------------
class TestFrameRingBuffer : public buffer::FrameRingBuffer {
 public:
  TestFrameRingBuffer(size_t capacity) : buffer::FrameRingBuffer(capacity) {}

  // Override Size() to report fake depth when testing
  size_t Size() const override {
    if (fake_depth_enabled_) {
      return fake_depth_;
    }
    return buffer::FrameRingBuffer::Size();
  }

  // Enable fake depth reporting for testing INV-P9-STEADY-004
  void SetFakeDepth(size_t depth) {
    fake_depth_ = depth;
    fake_depth_enabled_ = true;
  }

  void ClearFakeDepth() {
    fake_depth_enabled_ = false;
  }

 private:
  bool fake_depth_enabled_ = false;
  size_t fake_depth_ = 0;
};

class Phase9NoPadWhileDepthHighTest : public ::testing::Test {
 protected:
  void SetUp() override {
    // Create a test buffer
    buffer_ = std::make_unique<TestFrameRingBuffer>(64);

    // Create TestMasterClock in RealTime mode
    clock_ = std::make_shared<timing::TestMasterClock>(timing::TestMasterClock::Mode::RealTime);

    // Create ProgramOutput (headless mode)
    renderer::RenderConfig config;
    config.mode = renderer::RenderMode::HEADLESS;
    program_output_ = renderer::ProgramOutput::Create(
        config, *buffer_, clock_, nullptr, /*channel_id=*/1);
  }

  void TearDown() override {
    if (program_output_ && program_output_->IsRunning()) {
      program_output_->Stop();
    }
  }

  std::unique_ptr<TestFrameRingBuffer> buffer_;
  std::shared_ptr<timing::MasterClock> clock_;
  std::unique_ptr<renderer::ProgramOutput> program_output_;
};

// =============================================================================
// P9-TEST-STEADY-004-A: Violation Detection When Pad Emitted With Depth >= 10
// =============================================================================
// Given: Buffer depth appears to be >= 10 (simulated)
// When: ProgramOutput emits pad frame
// Then: Log contains `INV-P9-STEADY-004 VIOLATION`
// And: `pad_while_depth_high_` counter incremented
// Contract: INV-P9-STEADY-004

TEST_F(Phase9NoPadWhileDepthHighTest, P9_TEST_STEADY_004_A_ViolationDetection) {
  // Verify initial state
  EXPECT_EQ(program_output_->GetPadWhileDepthHighViolations(), 0)
      << "Violation counter should start at 0";

  // Set up a side sink so output loop doesn't block on sink gate
  std::atomic<int> frames_received{0};
  program_output_->SetSideSink([&frames_received](const buffer::Frame& frame) {
    (void)frame;
    frames_received++;
  });

  // Mark as no-content segment so pad frames are allowed immediately
  // (bypasses INV-AIR-CONTENT-BEFORE-PAD gate)
  program_output_->SetNoContentSegment(true);

  // Start the output loop
  ASSERT_TRUE(program_output_->Start()) << "ProgramOutput Start failed";

  // Wait for output loop to start
  std::this_thread::sleep_for(50ms);

  // Now set fake depth to simulate the bug condition:
  // Size() reports 15 frames, but buffer is actually empty
  // This simulates a race condition or bug that INV-P9-STEADY-004 detects
  buffer_->SetFakeDepth(15);

  // Wait for output loop to attempt emission
  // With buffer empty but reporting depth=15, pad frame will be emitted
  // and the violation should be detected
  std::this_thread::sleep_for(200ms);

  // The violation should have been detected at least once
  // (multiple pad frames may be emitted during the 200ms window)
  const uint64_t violations = program_output_->GetPadWhileDepthHighViolations();
  EXPECT_GT(violations, 0)
      << "INV-P9-STEADY-004: Violation should be detected when pad emitted "
      << "while buffer depth appears >= 10";

  std::cout << "[P9-TEST-STEADY-004-A] Violation detection: "
            << "violations=" << violations
            << ", frames_received=" << frames_received.load()
            << std::endl;

  // Clean up
  buffer_->ClearFakeDepth();
  program_output_->Stop();
}

// =============================================================================
// P9-TEST-STEADY-004-B: No Violation When Buffer Actually Empty
// =============================================================================
// Given: Buffer is truly empty (depth = 0)
// When: ProgramOutput emits pad frame
// Then: No INV-P9-STEADY-004 violation logged
// And: Violation counter remains 0
// Contract: INV-P9-STEADY-004 (negative test - confirms violation is specific)

TEST_F(Phase9NoPadWhileDepthHighTest, P9_TEST_STEADY_004_B_NoViolationWhenBufferEmpty) {
  EXPECT_EQ(program_output_->GetPadWhileDepthHighViolations(), 0);

  // Set up side sink
  std::atomic<int> pad_frames{0};
  program_output_->SetSideSink([&pad_frames](const buffer::Frame& frame) {
    if (frame.metadata.asset_uri == "pad://black") {
      pad_frames++;
    }
  });

  // Mark as no-content segment so pad frames are allowed immediately
  program_output_->SetNoContentSegment(true);

  ASSERT_TRUE(program_output_->Start());
  std::this_thread::sleep_for(50ms);

  // Buffer is empty and Size() reports 0 (no fake depth)
  // Pad frames should be emitted without triggering violation
  std::this_thread::sleep_for(200ms);

  const uint64_t violations = program_output_->GetPadWhileDepthHighViolations();
  EXPECT_EQ(violations, 0)
      << "INV-P9-STEADY-004: No violation should occur when buffer is truly empty";

  // Verify pad frames were actually emitted
  EXPECT_GT(pad_frames.load(), 0)
      << "Pad frames should have been emitted during empty buffer condition";

  std::cout << "[P9-TEST-STEADY-004-B] No violation when empty: "
            << "violations=" << violations
            << ", pad_frames=" << pad_frames.load()
            << std::endl;

  program_output_->Stop();
}

// =============================================================================
// P9-TEST-STEADY-004-C: Threshold Boundary Test (depth = 9 vs 10)
// =============================================================================
// Given: Buffer depth at boundary (9 vs 10)
// When: ProgramOutput emits pad frame
// Then: Violation only when depth >= 10
// Contract: INV-P9-STEADY-004 (boundary condition)

TEST_F(Phase9NoPadWhileDepthHighTest, P9_TEST_STEADY_004_C_ThresholdBoundary) {
  // Set up side sink
  program_output_->SetSideSink([](const buffer::Frame& frame) { (void)frame; });
  program_output_->SetNoContentSegment(true);

  ASSERT_TRUE(program_output_->Start());
  std::this_thread::sleep_for(50ms);

  // Test with depth = 9 (below threshold)
  buffer_->SetFakeDepth(9);
  std::this_thread::sleep_for(100ms);
  uint64_t violations_at_9 = program_output_->GetPadWhileDepthHighViolations();

  EXPECT_EQ(violations_at_9, 0)
      << "INV-P9-STEADY-004: No violation at depth=9 (below threshold of 10)";

  // Test with depth = 10 (at threshold)
  buffer_->SetFakeDepth(10);
  std::this_thread::sleep_for(100ms);
  uint64_t violations_at_10 = program_output_->GetPadWhileDepthHighViolations();

  EXPECT_GT(violations_at_10, violations_at_9)
      << "INV-P9-STEADY-004: Violation should occur at depth=10 (at threshold)";

  std::cout << "[P9-TEST-STEADY-004-C] Threshold boundary: "
            << "violations_at_9=" << violations_at_9
            << ", violations_at_10=" << violations_at_10
            << std::endl;

  buffer_->ClearFakeDepth();
  program_output_->Stop();
}

// =============================================================================
// P9-TEST-STEADY-004-D: Steady-State Flag Included in Log
// =============================================================================
// This is a documentation test - the log message MUST include steady_state flag.
// The actual log verification is done via log inspection during test runs.
// Contract: INV-P9-STEADY-004

TEST_F(Phase9NoPadWhileDepthHighTest, P9_TEST_STEADY_004_D_SteadyStateFlagInLog) {
  // This test verifies that when a violation occurs, the log includes:
  // - depth
  // - steady_state flag
  // - wall_us timestamp
  // - violation count
  //
  // Log format: "[ProgramOutput] INV-P9-STEADY-004 VIOLATION: Pad emitted while depth=X >= 10,
  //              steady_state=true/false, wall_us=NNNN, violations=N"

  // Set up for violation
  program_output_->SetSideSink([](const buffer::Frame& frame) { (void)frame; });
  program_output_->SetNoContentSegment(true);

  ASSERT_TRUE(program_output_->Start());
  std::this_thread::sleep_for(50ms);

  std::cout << "[P9-TEST-STEADY-004-D] Triggering violation - inspect log for format:" << std::endl;
  std::cout << "  Expected: INV-P9-STEADY-004 VIOLATION: Pad emitted while depth=X >= 10, "
            << "steady_state=true/false, wall_us=NNNN, violations=N" << std::endl;

  buffer_->SetFakeDepth(15);
  std::this_thread::sleep_for(100ms);

  const uint64_t violations = program_output_->GetPadWhileDepthHighViolations();
  EXPECT_GT(violations, 0) << "Violation should be triggered for log format verification";

  buffer_->ClearFakeDepth();
  program_output_->Stop();
}

}  // namespace
