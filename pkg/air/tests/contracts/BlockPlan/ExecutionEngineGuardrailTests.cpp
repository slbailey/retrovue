// Repository: Retrovue-playout
// Component: Execution Engine Guardrail Tests
// Purpose: Verify engine selection, lifecycle alignment, and mode guardrails
// Contract Reference: INV-SERIAL-BLOCK-EXECUTION, PlayoutAuthorityContract.md
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/IPlayoutExecutionEngine.hpp"
#include "retrovue/blockplan/SerialBlockExecutionEngine.hpp"

namespace retrovue::blockplan::testing {
namespace {

// =============================================================================
// Test Fixture
// =============================================================================

class ExecutionEngineGuardrailTest : public ::testing::Test {
 protected:
  void SetUp() override {
    ctx_ = std::make_unique<BlockPlanSessionContext>();
    ctx_->channel_id = 42;
    ctx_->fd = -1;  // No real FD needed for structural tests
    ctx_->width = 640;
    ctx_->height = 480;
    ctx_->fps = 30.0;
  }

  void TearDown() override {
    // Ensure engine is stopped before context is destroyed
    if (engine_) {
      engine_->Stop();
      engine_.reset();
    }
  }

  // Create a SerialBlockExecutionEngine with test callbacks
  std::unique_ptr<SerialBlockExecutionEngine> MakeSerialEngine() {
    SerialBlockExecutionEngine::Callbacks callbacks;
    callbacks.on_block_completed = [this](const FedBlock& block, int64_t final_ct_ms) {
      std::lock_guard<std::mutex> lock(callback_mutex_);
      completed_blocks_.push_back(block.block_id);
    };
    callbacks.on_session_ended = [this](const std::string& reason) {
      std::lock_guard<std::mutex> lock(callback_mutex_);
      session_ended_reason_ = reason;
      session_ended_ = true;
    };
    return std::make_unique<SerialBlockExecutionEngine>(ctx_.get(), std::move(callbacks));
  }

  std::unique_ptr<BlockPlanSessionContext> ctx_;
  std::unique_ptr<IPlayoutExecutionEngine> engine_;

  // Callback tracking
  std::mutex callback_mutex_;
  std::vector<std::string> completed_blocks_;
  std::string session_ended_reason_;
  bool session_ended_ = false;
};

// =============================================================================
// A. MODE SELECTION TESTS
// =============================================================================

// -----------------------------------------------------------------------------
// TEST-ENGINE-001: kSerialBlock selects SerialBlockExecutionEngine
// The only valid engine for the current execution mode
// -----------------------------------------------------------------------------
TEST_F(ExecutionEngineGuardrailTest, SerialBlockSelectsSerialEngine) {
  constexpr auto mode = PlayoutExecutionMode::kSerialBlock;
  EXPECT_EQ(std::string(PlayoutExecutionModeToString(mode)), "serial_block");

  // Creating a SerialBlockExecutionEngine must succeed
  auto engine = MakeSerialEngine();
  EXPECT_NE(engine, nullptr);

  // Verify it satisfies the IPlayoutExecutionEngine interface
  IPlayoutExecutionEngine* iface = engine.get();
  EXPECT_NE(iface, nullptr);
}

// -----------------------------------------------------------------------------
// TEST-ENGINE-002: kContinuousOutput is declared but NOT implemented
// Any attempt to create an engine for this mode must be rejected at the
// selection point (in playout_service.cpp). The enum value exists only as
// a placeholder.
// -----------------------------------------------------------------------------
TEST_F(ExecutionEngineGuardrailTest, ContinuousOutputNotImplemented) {
  constexpr auto mode = PlayoutExecutionMode::kContinuousOutput;
  EXPECT_EQ(std::string(PlayoutExecutionModeToString(mode)), "continuous_output");

  // There is no ContinuousOutputEngine class — this test documents
  // that kContinuousOutput has no engine implementation.
  // The selection logic in playout_service.cpp rejects this mode at startup.
  EXPECT_NE(static_cast<int>(mode), static_cast<int>(PlayoutExecutionMode::kSerialBlock))
      << "kContinuousOutput must be a distinct mode from kSerialBlock";
}

// =============================================================================
// B. ENGINE LIFECYCLE TESTS
// =============================================================================

// -----------------------------------------------------------------------------
// TEST-ENGINE-003: Engine Start/Stop is idempotent
// Stop() must be safe to call multiple times
// -----------------------------------------------------------------------------
TEST_F(ExecutionEngineGuardrailTest, EngineStopIsIdempotent) {
  engine_ = MakeSerialEngine();

  // Start the engine (it will loop waiting for blocks with no FD)
  engine_->Start();

  // Stop multiple times — must not crash or hang
  engine_->Stop();
  engine_->Stop();
  engine_->Stop();
}

// -----------------------------------------------------------------------------
// TEST-ENGINE-004: Engine Stop without Start is safe
// Must not crash if Stop() is called before Start()
// -----------------------------------------------------------------------------
TEST_F(ExecutionEngineGuardrailTest, StopWithoutStartIsSafe) {
  engine_ = MakeSerialEngine();

  // Stop without ever starting — must be a no-op
  engine_->Stop();
}

// -----------------------------------------------------------------------------
// TEST-ENGINE-005: Engine destructor calls Stop
// If the engine is destroyed without explicit Stop(), it must clean up
// -----------------------------------------------------------------------------
TEST_F(ExecutionEngineGuardrailTest, DestructorCallsStop) {
  {
    auto engine = MakeSerialEngine();
    engine->Start();
    // Destructor should call Stop() and join the thread
  }
  // If we get here without hanging, the destructor worked
  SUCCEED();
}

// =============================================================================
// C. NO EXECUTION WITHOUT ENGINE TESTS
// =============================================================================

// -----------------------------------------------------------------------------
// TEST-ENGINE-006: Session context without engine produces no execution
// The context alone does not spawn threads or process blocks
// -----------------------------------------------------------------------------
TEST_F(ExecutionEngineGuardrailTest, ContextAloneProducesNoExecution) {
  // Add blocks to the queue
  FedBlock block;
  block.block_id = "BLOCK-ORPHAN";
  block.channel_id = 42;
  block.start_utc_ms = 1000;
  block.end_utc_ms = 6000;
  FedBlock::Segment seg;
  seg.segment_index = 0;
  seg.asset_uri = "test://orphan.mp4";
  seg.segment_duration_ms = 5000;
  block.segments.push_back(seg);

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  // Wait briefly — no engine means no execution
  std::this_thread::sleep_for(std::chrono::milliseconds(50));

  // blocks_executed must remain 0
  EXPECT_EQ(ctx_->blocks_executed, 0)
      << "Without an engine, blocks must not execute";

  // Queue must still contain the block
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    EXPECT_EQ(ctx_->block_queue.size(), 1u)
        << "Without an engine, queue must remain unchanged";
  }
}

// =============================================================================
// D. ENGINE-SESSION ALIGNMENT TESTS
// =============================================================================

// -----------------------------------------------------------------------------
// TEST-ENGINE-007: Engine reads stop_requested from session context
// The engine must respect the shared stop flag
// -----------------------------------------------------------------------------
TEST_F(ExecutionEngineGuardrailTest, EngineRespectsStopRequested) {
  engine_ = MakeSerialEngine();
  engine_->Start();

  // Engine is running (waiting for blocks)
  std::this_thread::sleep_for(std::chrono::milliseconds(20));

  // Stop via engine (which sets stop_requested internally)
  engine_->Stop();

  // Verify the session context's stop flag was set
  EXPECT_TRUE(ctx_->stop_requested.load(std::memory_order_acquire))
      << "Engine Stop() must set the session context's stop_requested flag";
}

// -----------------------------------------------------------------------------
// TEST-ENGINE-008: Engine emits session_ended callback on exit
// The callback must fire regardless of exit reason
// -----------------------------------------------------------------------------
TEST_F(ExecutionEngineGuardrailTest, EngineEmitsSessionEndedOnStop) {
  engine_ = MakeSerialEngine();
  engine_->Start();

  // Let it run briefly (no blocks, will loop waiting)
  std::this_thread::sleep_for(std::chrono::milliseconds(20));

  engine_->Stop();

  // Session ended callback should have fired
  {
    std::lock_guard<std::mutex> lock(callback_mutex_);
    EXPECT_TRUE(session_ended_)
        << "Engine must emit session_ended callback when stopping";
    EXPECT_EQ(session_ended_reason_, "stopped")
        << "Stop() should produce 'stopped' reason";
  }
}

// =============================================================================
// E. TYPE CONVERSION TESTS
// =============================================================================

// -----------------------------------------------------------------------------
// TEST-ENGINE-009: FedBlockToBlockPlan preserves all fields
// Mechanical verification of the type conversion
// -----------------------------------------------------------------------------
TEST_F(ExecutionEngineGuardrailTest, FedBlockToBlockPlanPreservesFields) {
  FedBlock fed;
  fed.block_id = "BLOCK-CONV-1";
  fed.channel_id = 7;
  fed.start_utc_ms = 1000;
  fed.end_utc_ms = 6000;

  FedBlock::Segment seg;
  seg.segment_index = 0;
  seg.asset_uri = "test://sample.mp4";
  seg.asset_start_offset_ms = 500;
  seg.segment_duration_ms = 5000;
  fed.segments.push_back(seg);

  BlockPlan plan = FedBlockToBlockPlan(fed);

  EXPECT_EQ(plan.block_id, "BLOCK-CONV-1");
  EXPECT_EQ(plan.channel_id, 7);
  EXPECT_EQ(plan.start_utc_ms, 1000);
  EXPECT_EQ(plan.end_utc_ms, 6000);
  ASSERT_EQ(plan.segments.size(), 1u);
  EXPECT_EQ(plan.segments[0].segment_index, 0);
  EXPECT_EQ(plan.segments[0].asset_uri, "test://sample.mp4");
  EXPECT_EQ(plan.segments[0].asset_start_offset_ms, 500);
  EXPECT_EQ(plan.segments[0].segment_duration_ms, 5000);
}

}  // namespace
}  // namespace retrovue::blockplan::testing
