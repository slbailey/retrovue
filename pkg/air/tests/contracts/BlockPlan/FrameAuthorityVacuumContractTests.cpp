// Repository: Retrovue-playout
// Component: INV-CONTINUOUS-FRAME-AUTHORITY-001 Contract Tests
// Purpose: Verify frame-authority vacuum detection and enforcement at segment swap.
// Contract: docs/contracts/invariants/air/INV-CONTINUOUS-FRAME-AUTHORITY-001.md
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>
#include <string>
#include <vector>

#include "retrovue/blockplan/PipelineManager.hpp"
#include "retrovue/util/Logger.hpp"

using retrovue::blockplan::FrameAuthorityAction;
using retrovue::blockplan::PipelineManager;
using retrovue::util::Logger;

namespace {

class FrameAuthorityVacuumTest : public ::testing::Test {
 protected:
  void SetUp() override {
    captured_errors_.clear();
    Logger::SetErrorSink([this](const std::string& line) {
      captured_errors_.push_back(line);
    });
  }

  void TearDown() override {
    Logger::SetErrorSink(nullptr);
  }

  bool HasViolationTag() const {
    for (const auto& line : captured_errors_) {
      if (line.find("INV-CONTINUOUS-FRAME-AUTHORITY-001-VIOLATED") != std::string::npos) {
        return true;
      }
    }
    return false;
  }

  std::vector<std::string> captured_errors_;
};

// Active segment has video frames — no vacuum, no violation.
TEST_F(FrameAuthorityVacuumTest, NoViolationWhenActiveHasFrames) {
  bool violated = PipelineManager::CheckFrameAuthorityVacuum(
      /*tick=*/100,
      /*active_segment_index=*/0,
      /*active_video_depth_frames=*/3,
      /*successor_segment_index=*/1,
      /*successor_video_depth_frames=*/0,
      /*successor_seam_ready=*/false);

  EXPECT_FALSE(violated);
  EXPECT_FALSE(HasViolationTag());
}

// Active segment empty, no incoming source at all — violation.
TEST_F(FrameAuthorityVacuumTest, ViolationWhenActiveEmptyNoIncoming) {
  bool violated = PipelineManager::CheckFrameAuthorityVacuum(
      /*tick=*/200,
      /*active_segment_index=*/0,
      /*active_video_depth_frames=*/0,
      /*successor_segment_index=*/1,
      /*successor_video_depth_frames=*/-1,
      /*successor_seam_ready=*/false);

  EXPECT_TRUE(violated);
  EXPECT_TRUE(HasViolationTag());

  // Verify structured fields in violation log.
  ASSERT_EQ(captured_errors_.size(), 1u);
  const std::string& log = captured_errors_[0];
  EXPECT_NE(log.find("tick=200"), std::string::npos);
  EXPECT_NE(log.find("active_segment_id=0"), std::string::npos);
  EXPECT_NE(log.find("successor_segment_id=1"), std::string::npos);
  EXPECT_NE(log.find("active_video_depth=0"), std::string::npos);
  EXPECT_NE(log.find("successor_video_depth=-1"), std::string::npos);
  EXPECT_NE(log.find("successor_seam_ready=false"), std::string::npos);
}

// Active segment empty, incoming exists but not seam-ready (0 video frames) — violation.
TEST_F(FrameAuthorityVacuumTest, ViolationWhenActiveEmptySuccessorNotSeamReady) {
  bool violated = PipelineManager::CheckFrameAuthorityVacuum(
      /*tick=*/300,
      /*active_segment_index=*/1,
      /*active_video_depth_frames=*/0,
      /*successor_segment_index=*/2,
      /*successor_video_depth_frames=*/0,
      /*successor_seam_ready=*/false);

  EXPECT_TRUE(violated);
  EXPECT_TRUE(HasViolationTag());

  ASSERT_EQ(captured_errors_.size(), 1u);
  const std::string& log = captured_errors_[0];
  EXPECT_NE(log.find("successor_video_depth=0"), std::string::npos);
  EXPECT_NE(log.find("successor_seam_ready=false"), std::string::npos);
}

// Active segment empty, swap deferred despite successor being seam-ready — violation.
// Per INV-CONTINUOUS-FRAME-AUTHORITY-001 Violation Condition:
// "A swap is deferred while the active segment cannot provide a video frame."
// The swap deferral itself is the violation, regardless of successor state.
TEST_F(FrameAuthorityVacuumTest, ViolationWhenActiveEmptySwapDeferredDespiteSeamReady) {
  bool violated = PipelineManager::CheckFrameAuthorityVacuum(
      /*tick=*/400,
      /*active_segment_index=*/2,
      /*active_video_depth_frames=*/0,
      /*successor_segment_index=*/3,
      /*successor_video_depth_frames=*/5,
      /*successor_seam_ready=*/true);

  EXPECT_TRUE(violated);
  EXPECT_TRUE(HasViolationTag());

  ASSERT_EQ(captured_errors_.size(), 1u);
  const std::string& log = captured_errors_[0];
  EXPECT_NE(log.find("successor_seam_ready=true"), std::string::npos);
}

// =============================================================================
// INV-CONTINUOUS-FRAME-AUTHORITY-001: Enforcement decision tests
// =============================================================================

// Active has frames — deferral is safe.
TEST_F(FrameAuthorityVacuumTest, EnforcementAllowsDeferWhenActiveHasFrames) {
  auto action = PipelineManager::EvaluateFrameAuthorityEnforcement(
      /*active_video_depth_frames=*/3,
      /*has_incoming=*/true,
      /*successor_video_depth_frames=*/0);

  EXPECT_EQ(action, FrameAuthorityAction::kDefer);
}

// Active empty, successor seam-ready (has video) — force execute swap.
TEST_F(FrameAuthorityVacuumTest, EnforcementForceExecuteWhenSuccessorSeamReady) {
  auto action = PipelineManager::EvaluateFrameAuthorityEnforcement(
      /*active_video_depth_frames=*/0,
      /*has_incoming=*/true,
      /*successor_video_depth_frames=*/2);

  EXPECT_EQ(action, FrameAuthorityAction::kForceExecute);
}

// Active empty, no incoming at all — extend active.
TEST_F(FrameAuthorityVacuumTest, EnforcementExtendActiveWhenNoIncoming) {
  auto action = PipelineManager::EvaluateFrameAuthorityEnforcement(
      /*active_video_depth_frames=*/0,
      /*has_incoming=*/false,
      /*successor_video_depth_frames=*/-1);

  EXPECT_EQ(action, FrameAuthorityAction::kExtendActive);
}

// Active empty, incoming exists but not seam-ready (0 video) — extend active.
TEST_F(FrameAuthorityVacuumTest, EnforcementExtendActiveWhenSuccessorNotSeamReady) {
  auto action = PipelineManager::EvaluateFrameAuthorityEnforcement(
      /*active_video_depth_frames=*/0,
      /*has_incoming=*/true,
      /*successor_video_depth_frames=*/0);

  EXPECT_EQ(action, FrameAuthorityAction::kExtendActive);
}

}  // namespace
