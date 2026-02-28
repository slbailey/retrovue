// Repository: Retrovue-playout
// Component: INV-PAD-VIDEO-READINESS-001 Contract Tests
// Classification: Enforcement evidence for INV-CONTINUOUS-FRAME-AUTHORITY-001, INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001
// Purpose: Verify PAD swap eligibility preconditions.
// Contract: docs/contracts/invariants/air/INV-PAD-VIDEO-READINESS-001.md
// Parents: docs/contracts/invariants/air/INV-CONTINUOUS-FRAME-AUTHORITY-001.md,
//          docs/contracts/invariants/air/INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001.md
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include "retrovue/blockplan/PipelineManager.hpp"

using retrovue::blockplan::IncomingState;
using retrovue::blockplan::PipelineManager;
using retrovue::blockplan::SegmentType;

namespace {

// =============================================================================
// INV-PAD-VIDEO-READINESS-001: PAD video readiness
// =============================================================================
// PAD provides video on-demand via pad_producer_->VideoFrame().  It has no
// video buffer to fill, so the video-depth gate does not apply.  PAD swap
// eligibility requires audio depth only.  This prevents swap deferrals at
// CONTENT->PAD seams that would cause INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001
// stale_frame_bleed violations.

// PAD with zero video frames IS swap-eligible (video is on-demand).
TEST(PadVideoReadiness, PadEligibleWithZeroVideoFramesBecauseOnDemand) {
  IncomingState pad;
  pad.incoming_audio_ms = 500;
  pad.incoming_video_frames = 0;
  pad.is_pad = true;
  pad.segment_type = SegmentType::kPad;

  EXPECT_TRUE(PipelineManager::IsIncomingSegmentEligibleForSwap(pad))
      << "PAD provides video on-demand; video depth gate must not apply";
}

// PAD with sufficient audio AND video MUST be swap-eligible.
TEST(PadVideoReadiness, PadEligibleWithSufficientVideoAndAudio) {
  IncomingState pad;
  pad.incoming_audio_ms = 500;
  pad.incoming_video_frames = 2;
  pad.is_pad = true;
  pad.segment_type = SegmentType::kPad;

  EXPECT_TRUE(PipelineManager::IsIncomingSegmentEligibleForSwap(pad));
}

// PAD with audio-only (video=0) IS eligible — PAD video is on-demand.
TEST(PadVideoReadiness, PadAudioOnlySufficientBecauseVideoOnDemand) {
  IncomingState pad;
  pad.incoming_audio_ms = 1000;  // Well above minimum audio threshold.
  pad.incoming_video_frames = 0;
  pad.is_pad = true;
  pad.segment_type = SegmentType::kPad;

  // PAD provides video synchronously via pad_producer_->VideoFrame().
  // Audio depth is the only gate.
  EXPECT_TRUE(PipelineManager::IsIncomingSegmentEligibleForSwap(pad))
      << "PAD video is on-demand; audio depth alone satisfies eligibility";
}

// PAD with insufficient audio is NOT eligible, even with video frames.
TEST(PadVideoReadiness, PadWithInsufficientAudioNotEligible) {
  IncomingState pad;
  pad.incoming_audio_ms = 100;  // Below minimum audio threshold.
  pad.incoming_video_frames = 5;
  pad.is_pad = true;
  pad.segment_type = SegmentType::kPad;

  EXPECT_FALSE(PipelineManager::IsIncomingSegmentEligibleForSwap(pad))
      << "PAD still requires audio depth for continuity at seam";
}

// Content with zero video frames is NOT eligible (unchanged — content has buffers).
TEST(PadVideoReadiness, ContentStillRequiresVideoDepth) {
  IncomingState content;
  content.incoming_audio_ms = 500;
  content.incoming_video_frames = 0;
  content.is_pad = false;
  content.segment_type = SegmentType::kContent;

  EXPECT_FALSE(PipelineManager::IsIncomingSegmentEligibleForSwap(content))
      << "Content segments still require buffered video depth";
}

}  // namespace
