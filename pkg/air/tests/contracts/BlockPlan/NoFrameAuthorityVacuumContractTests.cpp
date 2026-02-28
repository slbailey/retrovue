// Repository: Retrovue-playout
// Component: INV-NO-FRAME-AUTHORITY-VACUUM-001 Contract Tests
// Classification: Enforcement evidence for INV-CONTINUOUS-FRAME-AUTHORITY-001
// Purpose: Verify swap eligibility gate enforces video depth for content segments
//          and audio depth for all segment types.  PAD is exempt from the video
//          depth gate because it provides video on-demand.
// Contract: docs/contracts/invariants/air/INV-NO-FRAME-AUTHORITY-VACUUM-001.md
// Parent: docs/contracts/invariants/air/INV-CONTINUOUS-FRAME-AUTHORITY-001.md
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include "retrovue/blockplan/PipelineManager.hpp"

using retrovue::blockplan::IncomingState;
using retrovue::blockplan::PipelineManager;
using retrovue::blockplan::SegmentType;

namespace {

// =============================================================================
// INV-NO-FRAME-AUTHORITY-VACUUM-001: Swap-commit video precondition
// =============================================================================
// The swap eligibility gate MUST prevent authority transfer to a segment that
// cannot provide video.  Content segments prove capability via buffer depth.
// PAD segments provide video on-demand via pad_producer_->VideoFrame() and
// are therefore exempt from the buffer-based video depth gate.  All segment
// types require audio depth for continuity.

// PAD with audio but zero video frames IS swap-eligible (video is on-demand).
TEST(SwapCommitVideoPreCondition, PadEligibleWithZeroVideoFramesBecauseOnDemand) {
  IncomingState pad;
  pad.incoming_audio_ms = 500;
  pad.incoming_video_frames = 0;
  pad.is_pad = true;
  pad.segment_type = SegmentType::kPad;

  EXPECT_TRUE(PipelineManager::IsIncomingSegmentEligibleForSwap(pad))
      << "PAD provides video on-demand; no frame authority vacuum possible";
}

// PAD with sufficient audio AND video frames MUST be swap-eligible.
TEST(SwapCommitVideoPreCondition, PadWithSufficientVideoFramesEligible) {
  IncomingState pad;
  pad.incoming_audio_ms = 500;
  pad.incoming_video_frames = 2;
  pad.is_pad = true;
  pad.segment_type = SegmentType::kPad;

  EXPECT_TRUE(PipelineManager::IsIncomingSegmentEligibleForSwap(pad));
}

// Content with sufficient audio AND video is eligible; PAD with same depths
// is also eligible.  Both can provide video — content via buffer, PAD via
// on-demand producer.
TEST(SwapCommitVideoPreCondition, ContentAndPadBothEligibleWhenDepthsSufficient) {
  IncomingState content;
  content.incoming_audio_ms = 500;
  content.incoming_video_frames = 2;
  content.is_pad = false;
  content.segment_type = SegmentType::kContent;

  IncomingState pad;
  pad.incoming_audio_ms = 500;
  pad.incoming_video_frames = 2;
  pad.is_pad = true;
  pad.segment_type = SegmentType::kPad;

  EXPECT_TRUE(PipelineManager::IsIncomingSegmentEligibleForSwap(content));
  EXPECT_TRUE(PipelineManager::IsIncomingSegmentEligibleForSwap(pad));
}

// Content with zero video frames is NOT eligible (baseline — content has buffers).
TEST(SwapCommitVideoPreCondition, ContentWithZeroVideoFramesNotEligible) {
  IncomingState content;
  content.incoming_audio_ms = 500;
  content.incoming_video_frames = 0;
  content.is_pad = false;
  content.segment_type = SegmentType::kContent;

  EXPECT_FALSE(PipelineManager::IsIncomingSegmentEligibleForSwap(content))
      << "Content segments must prove video capability via buffer depth";
}

// PAD with video frames but insufficient audio is NOT eligible.
TEST(SwapCommitVideoPreCondition, PadWithVideoButInsufficientAudioNotEligible) {
  IncomingState pad;
  pad.incoming_audio_ms = 100;
  pad.incoming_video_frames = 2;
  pad.is_pad = true;
  pad.segment_type = SegmentType::kPad;

  EXPECT_FALSE(PipelineManager::IsIncomingSegmentEligibleForSwap(pad))
      << "Audio depth is still required for PAD for continuity at seam";
}

}  // namespace
