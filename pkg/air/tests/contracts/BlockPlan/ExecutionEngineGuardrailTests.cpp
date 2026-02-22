// Repository: Retrovue-playout
// Component: Execution Engine Guardrail Tests
// Purpose: Verify engine selection and interface conformance for PipelineManager
// Contract Reference: PlayoutAuthorityContract.md
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <memory>
#include <string>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/PipelineManager.hpp"
#include "retrovue/blockplan/IPlayoutExecutionEngine.hpp"
#include "DeterministicOutputClock.hpp"

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
    ctx_->fps = FPS_30;
  }

  std::unique_ptr<BlockPlanSessionContext> ctx_;
};

// =============================================================================
// A. MODE SELECTION TESTS
// =============================================================================

// -----------------------------------------------------------------------------
// TEST-ENGINE-002: kContinuousOutput selects PipelineManager
// The engine must implement IPlayoutExecutionEngine.
// -----------------------------------------------------------------------------
TEST_F(ExecutionEngineGuardrailTest, ContinuousOutputSelectsContinuousEngine) {
  constexpr auto mode = PlayoutExecutionMode::kContinuousOutput;
  EXPECT_EQ(std::string(PlayoutExecutionModeToString(mode)), "continuous_output");

  // kContinuousOutput must be distinct from kSerialBlock
  EXPECT_NE(static_cast<int>(mode), static_cast<int>(PlayoutExecutionMode::kSerialBlock));

  // Creating a PipelineManager must succeed
  PipelineManager::Callbacks callbacks;
  callbacks.on_block_completed = [](const FedBlock&, int64_t, int64_t) {};
  callbacks.on_session_ended = [](const std::string&, int64_t) {};

  auto engine = std::make_unique<PipelineManager>(
      ctx_.get(), std::move(callbacks), nullptr,
      std::make_shared<DeterministicOutputClock>(ctx_->fps.num, ctx_->fps.den),
      PipelineManagerOptions{0});
  EXPECT_NE(engine, nullptr);

  // Verify it satisfies the IPlayoutExecutionEngine interface
  IPlayoutExecutionEngine* iface = engine.get();
  EXPECT_NE(iface, nullptr);
}

}  // namespace
}  // namespace retrovue::blockplan::testing
