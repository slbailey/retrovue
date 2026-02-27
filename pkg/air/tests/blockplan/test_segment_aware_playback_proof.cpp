// Repository: Retrovue-playout
// Component: Segment-Aware Playback Proof Tests
// Purpose: Unit tests for segment-level proof types and verdict logic.
//          Tests SegmentProofRecord, DetermineSegmentVerdict,
//          DetermineBlockVerdictFromSegments, BlockAccumulator segment
//          tracking, frame budget integrity, and gap/overlap detection.
// Contract Reference: PlayoutAuthorityContract.md (P3.3)
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <cmath>
#include <string>
#include <vector>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/PlaybackTraceTypes.hpp"
#include "retrovue/blockplan/RationalFps.hpp"

namespace retrovue::blockplan::testing {
namespace {

// =============================================================================
// Helper: build a FedBlock with multiple segments
// =============================================================================
static FedBlock MakeMultiSegmentBlock(
    const std::string& block_id,
    const std::vector<std::tuple<std::string, int64_t, SegmentType>>& segs,
    int64_t start_ms = 1'000'000'000LL) {
  FedBlock block;
  block.block_id = block_id;
  block.channel_id = 99;
  block.start_utc_ms = start_ms;

  int64_t total_ms = 0;
  int32_t idx = 0;
  for (const auto& [uri, dur_ms, type] : segs) {
    FedBlock::Segment seg;
    seg.segment_index = idx++;
    seg.asset_uri = uri;
    seg.asset_start_offset_ms = 0;
    seg.segment_duration_ms = dur_ms;
    seg.segment_type = type;
    seg.event_id = "EVT-" + std::to_string(seg.segment_index);
    block.segments.push_back(seg);
    total_ms += dur_ms;
  }
  block.end_utc_ms = start_ms + total_ms;
  return block;
}

// Rational frame count (INV-FPS-RESAMPLE): session FPS is authority.
static int64_t FramesForDurationMs(int64_t duration_ms, const RationalFps& session_fps) {
  return session_fps.IsValid() ? session_fps.FramesFromDurationCeilMs(duration_ms) : 0;
}

// =============================================================================
// SEGPROOF-001: Single-segment block — segment proof matches block proof
// =============================================================================
TEST(SegmentAwareProofTest, SingleSegmentMatchesBlockProof) {
  // Build a single-segment block
  FedBlock block = MakeMultiSegmentBlock("single-seg", {
      {"/test/movie.mp4", 3000, SegmentType::kContent},
  });

  const RationalFps session_fps(30, 1);
  const int64_t expected_frames = FramesForDurationMs(3000, session_fps);
  const int64_t frame_dur_ms = 33;  // for CT accumulation display only

  // Simulate accumulation
  BlockAccumulator acc;
  acc.Reset("single-seg");
  acc.BeginSegment(0, "/test/movie.mp4", expected_frames,
                   SegmentType::kContent, "EVT-0");

  for (int64_t i = 0; i < expected_frames; ++i) {
    acc.AccumulateFrame(i, false, "/test/movie.mp4", i * frame_dur_ms);
  }

  auto summary = acc.Finalize();
  auto proof = BuildPlaybackProof(block, summary, session_fps,
                                   acc.GetSegmentProofs());

  // Single segment → 1 segment proof
  ASSERT_EQ(proof.segment_proofs.size(), 1u);
  EXPECT_EQ(proof.segment_proofs[0].segment_index, 0);
  EXPECT_EQ(proof.segment_proofs[0].expected_asset_uri, "/test/movie.mp4");
  EXPECT_EQ(proof.segment_proofs[0].actual_asset_uri, "/test/movie.mp4");
  EXPECT_EQ(proof.segment_proofs[0].actual_frame_count, expected_frames);
  EXPECT_EQ(proof.segment_proofs[0].actual_pad_frames, 0);
  EXPECT_EQ(proof.segment_proofs[0].verdict, PlaybackProofVerdict::kFaithful);

  // Block verdict == segment verdict
  EXPECT_EQ(proof.verdict, PlaybackProofVerdict::kFaithful);
  EXPECT_TRUE(proof.frame_budget_match);
  EXPECT_TRUE(proof.no_gaps);
  EXPECT_TRUE(proof.no_overlaps);
}

// =============================================================================
// SEGPROOF-002: Multi-segment block — per-segment verdicts
// =============================================================================
TEST(SegmentAwareProofTest, MultiSegmentPerSegmentVerdicts) {
  FedBlock block = MakeMultiSegmentBlock("multi-seg", {
      {"/test/show.mp4", 2000, SegmentType::kContent},
      {"/test/ad.mp4", 1000, SegmentType::kFiller},
      {"/test/promo.mp4", 500, SegmentType::kContent},
  });

  const RationalFps session_fps(30, 1);
  const int64_t frame_dur_ms = 33;
  const int64_t frames_0 = FramesForDurationMs(2000, session_fps);
  const int64_t frames_1 = FramesForDurationMs(1000, session_fps);
  const int64_t frames_2 = FramesForDurationMs(500, session_fps);

  BlockAccumulator acc;
  acc.Reset("multi-seg");

  // Segment 0: all real frames
  acc.BeginSegment(0, "/test/show.mp4", frames_0,
                   SegmentType::kContent, "EVT-0");
  int64_t frame_idx = 0;
  for (int64_t i = 0; i < frames_0; ++i) {
    acc.AccumulateFrame(frame_idx++, false, "/test/show.mp4", i * frame_dur_ms);
  }

  // Segment 1: correct asset but 2 pad frames at the end
  acc.BeginSegment(1, "/test/ad.mp4", frames_1,
                   SegmentType::kFiller, "EVT-1");
  for (int64_t i = 0; i < frames_1 - 2; ++i) {
    acc.AccumulateFrame(frame_idx++, false, "/test/ad.mp4", i * frame_dur_ms);
  }
  acc.AccumulateFrame(frame_idx++, true, "", -1);
  acc.AccumulateFrame(frame_idx++, true, "", -1);

  // Segment 2: all real frames
  acc.BeginSegment(2, "/test/promo.mp4", frames_2,
                   SegmentType::kContent, "EVT-2");
  for (int64_t i = 0; i < frames_2; ++i) {
    acc.AccumulateFrame(frame_idx++, false, "/test/promo.mp4", i * frame_dur_ms);
  }

  auto summary = acc.Finalize();
  auto proof = BuildPlaybackProof(block, summary, session_fps,
                                   acc.GetSegmentProofs());

  ASSERT_EQ(proof.segment_proofs.size(), 3u);

  // Segment 0: FAITHFUL
  EXPECT_EQ(proof.segment_proofs[0].verdict, PlaybackProofVerdict::kFaithful);
  EXPECT_EQ(proof.segment_proofs[0].actual_frame_count, frames_0);

  // Segment 1: PARTIAL_PAD (2 pad frames)
  EXPECT_EQ(proof.segment_proofs[1].verdict, PlaybackProofVerdict::kPartialPad);
  EXPECT_EQ(proof.segment_proofs[1].actual_pad_frames, 2);

  // Segment 2: FAITHFUL
  EXPECT_EQ(proof.segment_proofs[2].verdict, PlaybackProofVerdict::kFaithful);
  EXPECT_EQ(proof.segment_proofs[2].actual_frame_count, frames_2);

  // Block verdict = worst segment = PARTIAL_PAD
  EXPECT_EQ(proof.verdict, PlaybackProofVerdict::kPartialPad);
  EXPECT_TRUE(proof.frame_budget_match);
  EXPECT_TRUE(proof.no_gaps);
  EXPECT_TRUE(proof.no_overlaps);
}

// =============================================================================
// SEGPROOF-003: All-pad segment → kAllPad verdict
// =============================================================================
TEST(SegmentAwareProofTest, AllPadSegmentVerdict) {
  SegmentProofRecord rec;
  rec.segment_index = 0;
  rec.expected_asset_uri = "/test/missing.mp4";
  rec.expected_frame_count = 30;
  rec.expected_type = SegmentType::kContent;
  rec.event_id = "EVT-0";
  rec.actual_asset_uri = "";
  rec.actual_frame_count = 30;
  rec.actual_pad_frames = 30;
  rec.actual_start_frame = 0;
  rec.actual_end_frame = 29;

  auto verdict = DetermineSegmentVerdict(rec);
  EXPECT_EQ(verdict, PlaybackProofVerdict::kAllPad)
      << "All pad frames must produce ALL_PAD verdict";

  // Verify via accumulator
  BlockAccumulator acc;
  acc.Reset("allpad-block");
  acc.BeginSegment(0, "/test/missing.mp4", 30, SegmentType::kContent, "EVT-0");
  for (int64_t i = 0; i < 30; ++i) {
    acc.AccumulateFrame(i, true, "", -1);
  }
  acc.Finalize();

  ASSERT_EQ(acc.GetSegmentProofs().size(), 1u);
  EXPECT_EQ(acc.GetSegmentProofs()[0].verdict, PlaybackProofVerdict::kAllPad);
  EXPECT_EQ(acc.GetSegmentProofs()[0].actual_pad_frames, 30);
  EXPECT_EQ(acc.GetSegmentProofs()[0].actual_frame_count, 30);
  EXPECT_TRUE(acc.GetSegmentProofs()[0].actual_asset_uri.empty());
}

// =============================================================================
// SEGPROOF-004: Asset mismatch at segment level → kAssetMismatch
// =============================================================================
TEST(SegmentAwareProofTest, AssetMismatchSegmentVerdict) {
  SegmentProofRecord rec;
  rec.segment_index = 0;
  rec.expected_asset_uri = "/test/expected.mp4";
  rec.expected_frame_count = 30;
  rec.expected_type = SegmentType::kContent;
  rec.event_id = "EVT-0";
  rec.actual_asset_uri = "/test/wrong.mp4";
  rec.actual_frame_count = 30;
  rec.actual_pad_frames = 0;

  auto verdict = DetermineSegmentVerdict(rec);
  EXPECT_EQ(verdict, PlaybackProofVerdict::kAssetMismatch)
      << "Wrong asset must produce ASSET_MISMATCH verdict";

  // Verify block-level verdict propagation
  std::vector<SegmentProofRecord> proofs = {rec};
  proofs[0].verdict = verdict;
  BlockPlaybackSummary summary;
  summary.frames_emitted = 30;
  summary.pad_frames = 0;

  auto block_verdict = DetermineBlockVerdictFromSegments(proofs, summary);
  EXPECT_EQ(block_verdict, PlaybackProofVerdict::kAssetMismatch)
      << "Block verdict must propagate worst segment verdict";
}

// =============================================================================
// SEGPROOF-005: Frame budget check (sum of segments == block total)
// =============================================================================
TEST(SegmentAwareProofTest, FrameBudgetIntegrity) {
  FedBlock block = MakeMultiSegmentBlock("budget-check", {
      {"/test/a.mp4", 2000, SegmentType::kContent},
      {"/test/b.mp4", 1000, SegmentType::kContent},
  });

  const RationalFps session_fps(30, 1);
  const int64_t frame_dur_ms = 33;
  const int64_t frames_a = FramesForDurationMs(2000, session_fps);
  const int64_t frames_b = FramesForDurationMs(1000, session_fps);

  BlockAccumulator acc;
  acc.Reset("budget-check");

  // Segment 0
  acc.BeginSegment(0, "/test/a.mp4", frames_a, SegmentType::kContent, "EVT-0");
  int64_t idx = 0;
  for (int64_t i = 0; i < frames_a; ++i) {
    acc.AccumulateFrame(idx++, false, "/test/a.mp4", i * frame_dur_ms);
  }

  // Segment 1
  acc.BeginSegment(1, "/test/b.mp4", frames_b, SegmentType::kContent, "EVT-1");
  for (int64_t i = 0; i < frames_b; ++i) {
    acc.AccumulateFrame(idx++, false, "/test/b.mp4", i * frame_dur_ms);
  }

  auto summary = acc.Finalize();
  auto proof = BuildPlaybackProof(block, summary, session_fps,
                                   acc.GetSegmentProofs());

  // Sum of segment frames == block total
  EXPECT_TRUE(proof.frame_budget_match)
      << "Sum of segment frame counts must equal block frames_emitted";
  EXPECT_EQ(summary.frames_emitted, frames_a + frames_b);

  // Verify actual segment frame counts
  int64_t segment_total = 0;
  for (const auto& sp : proof.segment_proofs) {
    segment_total += sp.actual_frame_count;
  }
  EXPECT_EQ(segment_total, summary.frames_emitted)
      << "Segment frame sum must match block frame total";

  // Now test mismatch: manually create a proof with wrong segment counts
  std::vector<SegmentProofRecord> bad_proofs = proof.segment_proofs;
  bad_proofs[0].actual_frame_count += 5;  // inflate by 5
  auto bad_proof = BuildPlaybackProof(block, summary, session_fps, bad_proofs);
  EXPECT_FALSE(bad_proof.frame_budget_match)
      << "Inflated segment count must trigger budget mismatch";
}

// =============================================================================
// SEGPROOF-006: Gap/overlap detection between segments
// =============================================================================
TEST(SegmentAwareProofTest, GapAndOverlapDetection) {
  // Test gap detection: segment 0 ends at frame 29, segment 1 starts at frame 31
  {
    SegmentProofRecord seg0;
    seg0.segment_index = 0;
    seg0.expected_asset_uri = "/a.mp4";
    seg0.expected_frame_count = 30;
    seg0.expected_type = SegmentType::kContent;
    seg0.actual_asset_uri = "/a.mp4";
    seg0.actual_frame_count = 30;
    seg0.actual_pad_frames = 0;
    seg0.actual_start_frame = 0;
    seg0.actual_end_frame = 29;
    seg0.verdict = PlaybackProofVerdict::kFaithful;

    SegmentProofRecord seg1;
    seg1.segment_index = 1;
    seg1.expected_asset_uri = "/b.mp4";
    seg1.expected_frame_count = 30;
    seg1.expected_type = SegmentType::kContent;
    seg1.actual_asset_uri = "/b.mp4";
    seg1.actual_frame_count = 30;
    seg1.actual_pad_frames = 0;
    seg1.actual_start_frame = 31;  // gap: should be 30
    seg1.actual_end_frame = 60;
    seg1.verdict = PlaybackProofVerdict::kFaithful;

    FedBlock block;
    block.block_id = "gap-test";
    block.start_utc_ms = 1'000'000'000LL;
    block.end_utc_ms = 1'000'002'000LL;
    FedBlock::Segment s0;
    s0.segment_index = 0;
    s0.asset_uri = "/a.mp4";
    s0.segment_duration_ms = 1000;
    block.segments.push_back(s0);
    FedBlock::Segment s1;
    s1.segment_index = 1;
    s1.asset_uri = "/b.mp4";
    s1.segment_duration_ms = 1000;
    block.segments.push_back(s1);

    BlockPlaybackSummary summary;
    summary.block_id = "gap-test";
    summary.frames_emitted = 60;
    summary.pad_frames = 0;

    const RationalFps session_fps(30, 1);
    auto proof = BuildPlaybackProof(block, summary, session_fps, {seg0, seg1});
    EXPECT_FALSE(proof.no_gaps) << "Frame 30 missing between segments → gap detected";
    EXPECT_TRUE(proof.no_overlaps) << "No overlap in this case";
  }

  // Test overlap detection: segment 0 ends at frame 29, segment 1 starts at frame 29
  {
    SegmentProofRecord seg0;
    seg0.segment_index = 0;
    seg0.expected_asset_uri = "/a.mp4";
    seg0.expected_frame_count = 30;
    seg0.expected_type = SegmentType::kContent;
    seg0.actual_asset_uri = "/a.mp4";
    seg0.actual_frame_count = 30;
    seg0.actual_pad_frames = 0;
    seg0.actual_start_frame = 0;
    seg0.actual_end_frame = 29;
    seg0.verdict = PlaybackProofVerdict::kFaithful;

    SegmentProofRecord seg1;
    seg1.segment_index = 1;
    seg1.expected_asset_uri = "/b.mp4";
    seg1.expected_frame_count = 30;
    seg1.expected_type = SegmentType::kContent;
    seg1.actual_asset_uri = "/b.mp4";
    seg1.actual_frame_count = 30;
    seg1.actual_pad_frames = 0;
    seg1.actual_start_frame = 29;  // overlap: starts on same frame as prev end
    seg1.actual_end_frame = 58;
    seg1.verdict = PlaybackProofVerdict::kFaithful;

    FedBlock block;
    block.block_id = "overlap-test";
    block.start_utc_ms = 1'000'000'000LL;
    block.end_utc_ms = 1'000'002'000LL;
    FedBlock::Segment s0;
    s0.segment_index = 0;
    s0.asset_uri = "/a.mp4";
    s0.segment_duration_ms = 1000;
    block.segments.push_back(s0);
    FedBlock::Segment s1;
    s1.segment_index = 1;
    s1.asset_uri = "/b.mp4";
    s1.segment_duration_ms = 1000;
    block.segments.push_back(s1);

    BlockPlaybackSummary summary;
    summary.block_id = "overlap-test";
    summary.frames_emitted = 60;
    summary.pad_frames = 0;

    const RationalFps session_fps(30, 1);
    auto proof = BuildPlaybackProof(block, summary, session_fps, {seg0, seg1});
    EXPECT_TRUE(proof.no_gaps) << "No gap in this case";
    EXPECT_FALSE(proof.no_overlaps) << "Frame 29 shared → overlap detected";
  }

  // Test clean contiguous: segment 0 ends at 29, segment 1 starts at 30
  {
    SegmentProofRecord seg0;
    seg0.segment_index = 0;
    seg0.actual_start_frame = 0;
    seg0.actual_end_frame = 29;
    seg0.actual_frame_count = 30;
    seg0.actual_pad_frames = 0;
    seg0.expected_type = SegmentType::kContent;
    seg0.verdict = PlaybackProofVerdict::kFaithful;

    SegmentProofRecord seg1;
    seg1.segment_index = 1;
    seg1.actual_start_frame = 30;
    seg1.actual_end_frame = 59;
    seg1.actual_frame_count = 30;
    seg1.actual_pad_frames = 0;
    seg1.expected_type = SegmentType::kContent;
    seg1.verdict = PlaybackProofVerdict::kFaithful;

    FedBlock block;
    block.block_id = "clean-test";
    block.start_utc_ms = 1'000'000'000LL;
    block.end_utc_ms = 1'000'002'000LL;
    FedBlock::Segment s0;
    s0.segment_index = 0;
    s0.segment_duration_ms = 1000;
    block.segments.push_back(s0);
    FedBlock::Segment s1;
    s1.segment_index = 1;
    s1.segment_duration_ms = 1000;
    block.segments.push_back(s1);

    BlockPlaybackSummary summary;
    summary.block_id = "clean-test";
    summary.frames_emitted = 60;
    summary.pad_frames = 0;

    const RationalFps session_fps(30, 1);
    auto proof = BuildPlaybackProof(block, summary, session_fps, {seg0, seg1});
    EXPECT_TRUE(proof.no_gaps) << "Contiguous segments must have no gaps";
    EXPECT_TRUE(proof.no_overlaps) << "Contiguous segments must have no overlaps";
  }
}

// =============================================================================
// SEGPROOF-007: FormatSegmentProof output format
// =============================================================================
TEST(SegmentAwareProofTest, FormatSegmentProofOutput) {
  SegmentProofRecord rec;
  rec.segment_index = 2;
  rec.expected_asset_uri = "/test/ad.mp4";
  rec.expected_frame_count = 30;
  rec.expected_type = SegmentType::kFiller;
  rec.event_id = "EVT-002";
  rec.actual_asset_uri = "/test/ad.mp4";
  rec.actual_frame_count = 30;
  rec.actual_pad_frames = 3;
  rec.verdict = PlaybackProofVerdict::kPartialPad;

  std::string output = FormatSegmentProof(rec);

  EXPECT_NE(output.find("[SEGMENT_PROOF]"), std::string::npos)
      << "Must contain [SEGMENT_PROOF] prefix";
  EXPECT_NE(output.find("segment_index=2"), std::string::npos)
      << "Must contain segment index";
  EXPECT_NE(output.find("type=FILLER"), std::string::npos)
      << "Must contain segment type";
  EXPECT_NE(output.find("event_id=EVT-002"), std::string::npos)
      << "Must contain event ID";
  EXPECT_NE(output.find("expected_asset=/test/ad.mp4"), std::string::npos)
      << "Must contain expected asset";
  EXPECT_NE(output.find("actual_asset=/test/ad.mp4"), std::string::npos)
      << "Must contain actual asset";
  EXPECT_NE(output.find("expected_frames=30"), std::string::npos)
      << "Must contain expected frame count";
  EXPECT_NE(output.find("actual_frames=30"), std::string::npos)
      << "Must contain actual frame count";
  EXPECT_NE(output.find("pad=3"), std::string::npos)
      << "Must contain pad frame count";
  EXPECT_NE(output.find("verdict=PARTIAL_PAD"), std::string::npos)
      << "Must contain verdict";
}

// =============================================================================
// SEGPROOF-008: BlockAccumulator segment tracking unit test
// =============================================================================
TEST(SegmentAwareProofTest, AccumulatorSegmentTracking) {
  BlockAccumulator acc;
  acc.Reset("acc-test");

  // Segment 0: 3 real frames
  acc.BeginSegment(0, "/a.mp4", 3, SegmentType::kContent, "EVT-0");
  acc.AccumulateFrame(0, false, "/a.mp4", 0);
  acc.AccumulateFrame(1, false, "/a.mp4", 33);
  acc.AccumulateFrame(2, false, "/a.mp4", 66);

  // Segment 1: 2 frames (1 real + 1 pad)
  acc.BeginSegment(1, "/b.mp4", 2, SegmentType::kFiller, "EVT-1");
  acc.AccumulateFrame(3, false, "/b.mp4", 0);
  acc.AccumulateFrame(4, true, "", -1);

  auto summary = acc.Finalize();

  // Block-level
  EXPECT_EQ(summary.frames_emitted, 5);
  EXPECT_EQ(summary.pad_frames, 1);
  EXPECT_EQ(summary.first_session_frame_index, 0);
  EXPECT_EQ(summary.last_session_frame_index, 4);
  ASSERT_EQ(summary.asset_uris.size(), 2u);
  EXPECT_EQ(summary.asset_uris[0], "/a.mp4");
  EXPECT_EQ(summary.asset_uris[1], "/b.mp4");

  // Segment-level
  const auto& proofs = acc.GetSegmentProofs();
  ASSERT_EQ(proofs.size(), 2u);

  // Segment 0
  EXPECT_EQ(proofs[0].segment_index, 0);
  EXPECT_EQ(proofs[0].expected_asset_uri, "/a.mp4");
  EXPECT_EQ(proofs[0].actual_asset_uri, "/a.mp4");
  EXPECT_EQ(proofs[0].actual_frame_count, 3);
  EXPECT_EQ(proofs[0].actual_pad_frames, 0);
  EXPECT_EQ(proofs[0].actual_start_frame, 0);
  EXPECT_EQ(proofs[0].actual_end_frame, 2);
  EXPECT_EQ(proofs[0].first_ct_ms, 0);
  EXPECT_EQ(proofs[0].last_ct_ms, 66);
  EXPECT_EQ(proofs[0].verdict, PlaybackProofVerdict::kFaithful);
  EXPECT_EQ(proofs[0].event_id, "EVT-0");
  EXPECT_EQ(proofs[0].expected_type, SegmentType::kContent);

  // Segment 1
  EXPECT_EQ(proofs[1].segment_index, 1);
  EXPECT_EQ(proofs[1].expected_asset_uri, "/b.mp4");
  EXPECT_EQ(proofs[1].actual_asset_uri, "/b.mp4");
  EXPECT_EQ(proofs[1].actual_frame_count, 2);
  EXPECT_EQ(proofs[1].actual_pad_frames, 1);
  EXPECT_EQ(proofs[1].actual_start_frame, 3);
  EXPECT_EQ(proofs[1].actual_end_frame, 4);
  EXPECT_EQ(proofs[1].verdict, PlaybackProofVerdict::kPartialPad);
  EXPECT_EQ(proofs[1].event_id, "EVT-1");
  EXPECT_EQ(proofs[1].expected_type, SegmentType::kFiller);
}

}  // namespace
}  // namespace retrovue::blockplan::testing
