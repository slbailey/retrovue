// Repository: Retrovue-playout
// Component: INV-SEAM-VSRC-COMMIT-001 Contract Tests
// Purpose: When SEAM_VSRC_GATE selects the incoming buffer and a frame is
//          emitted from it, POST-TAKE MUST execute the swap.
// Contract: docs/contracts/invariants/air/INV-SEAM-VSRC-COMMIT-001.md
// Copyright (c) 2026 RetroVue

#include <gtest/gtest.h>
#include <string>
#include <vector>

#include "retrovue/blockplan/PipelineManager.hpp"
#include "retrovue/util/Logger.hpp"

using retrovue::blockplan::IncomingState;
using retrovue::blockplan::PipelineManager;
using retrovue::blockplan::SegmentType;
using retrovue::util::Logger;

namespace {

class SeamVsrcCommitTest : public ::testing::Test {
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
      if (line.find("INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001-VIOLATED") !=
          std::string::npos) {
        return true;
      }
    }
    return false;
  }

  std::vector<std::string> captured_errors_;
};

// =============================================================================
// INV-SEAM-VSRC-COMMIT-001: When v_src selected incoming segment B and a
// frame was emitted from it (origin = incoming segment), the authority check
// MUST NOT report a violation.
//
// Before the fix: SEAM_VSRC_GATE says eligible, frame popped from B
// (origin=1), but POST-TAKE re-evaluates and defers → authority violation
// (active=0, origin=1).
//
// After the fix: force_swap_for_vsrc_commit forces the swap, advancing
// active to 1 → authority check passes.
// =============================================================================

TEST_F(SeamVsrcCommitTest, EmittingFromIncomingBufferRequiresMatchingAuthority) {
  // Simulate: frame emitted from segment B (origin=1), but active is still 0
  // because the swap was deferred. This MUST be a violation.
  bool ok = PipelineManager::EmittedFrameMatchesAuthority(
      /*tick=*/1077,
      /*active_segment_id=*/0,
      /*frame_origin_segment_id=*/1);

  EXPECT_FALSE(ok);
  EXPECT_TRUE(HasViolationTag());
}

TEST_F(SeamVsrcCommitTest, EmittingFromIncomingBufferAfterSwapIsClean) {
  // Simulate: frame emitted from segment B (origin=1), and swap executed
  // so active is now 1. This MUST NOT be a violation.
  bool ok = PipelineManager::EmittedFrameMatchesAuthority(
      /*tick=*/1077,
      /*active_segment_id=*/1,
      /*frame_origin_segment_id=*/1);

  EXPECT_TRUE(ok);
  EXPECT_FALSE(HasViolationTag());
}

// =============================================================================
// Eligibility gate: a CONTENT segment with insufficient video depth but
// sufficient audio SHOULD still be swappable when the VSRC gate already
// committed to it. This test documents the pre-fix behavior where
// IsIncomingSegmentEligibleForSwap would reject the swap.
// =============================================================================

TEST_F(SeamVsrcCommitTest, IncomingContentWithLowVideoDepthIsNotEligible) {
  IncomingState incoming;
  incoming.incoming_audio_ms = 12000;     // Plenty of audio
  incoming.incoming_video_frames = 1;     // Only 1 frame (after FIVS drain)
  incoming.is_pad = false;
  incoming.segment_type = SegmentType::kContent;
  incoming.segment_total_frames = 136;

  const int required_video_depth = 15;
  // With only 1 video frame and 136 total (not a short segment), this is
  // NOT eligible under the normal gate. The fix adds force_swap_for_vsrc_commit
  // to bypass this gate when the frame was already emitted from B.
  EXPECT_FALSE(PipelineManager::IsIncomingSegmentEligibleForSwap(
      incoming, required_video_depth));
}

}  // namespace
