// Repository: Retrovue-playout
// Component: BlockPlan Mid-Asset Seek Contract Tests
// Purpose: Verify mid-asset offset propagation and frame behavior at executor level
// Contract Reference: docs/contracts/PlayoutAuthorityContract.md "Mid-Asset Seek Strategy"
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include "retrovue/blockplan/BlockPlanExecutor.hpp"
#include "retrovue/blockplan/BlockPlanQueue.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/BlockPlanValidator.hpp"
#include "ExecutorTestInfrastructure.hpp"

namespace retrovue::blockplan::testing {
namespace {

// Frame duration for 30fps (matches executor)
static constexpr int64_t kFrameDurationMs = 33;

// =============================================================================
// Test Fixture
// =============================================================================

class MidAssetSeekTest : public ::testing::Test {
 protected:
  void SetUp() override {
    clock_ = std::make_unique<FakeClock>();
    assets_ = std::make_unique<FakeAssetSource>();
    sink_ = std::make_unique<RecordingSink>();
    executor_ = std::make_unique<BlockPlanExecutor>();
  }

  // Helper: Create a validated single-segment plan with offset
  ValidatedBlockPlan MakeValidatedPlan(
      const std::string& block_id,
      int64_t start_utc_ms,
      int64_t end_utc_ms,
      const std::string& asset_uri,
      int64_t asset_offset_ms = 0) {
    BlockPlan plan;
    plan.block_id = block_id;
    plan.channel_id = 1;
    plan.start_utc_ms = start_utc_ms;
    plan.end_utc_ms = end_utc_ms;

    Segment seg;
    seg.segment_index = 0;
    seg.asset_uri = asset_uri;
    seg.asset_start_offset_ms = asset_offset_ms;
    seg.segment_duration_ms = end_utc_ms - start_utc_ms;
    plan.segments.push_back(seg);

    BlockPlanValidator validator(assets_->AsDurationFn());
    auto result = validator.Validate(plan, start_utc_ms - 1000);
    EXPECT_TRUE(result.valid) << result.detail;

    return ValidatedBlockPlan{plan, result.boundaries, start_utc_ms - 1000};
  }

  // Helper: Create a validated multi-segment plan
  ValidatedBlockPlan MakeMultiSegmentPlan(
      const std::string& block_id,
      int64_t start_utc_ms,
      const std::vector<std::tuple<std::string, int64_t, int64_t>>& segments) {
    // segments: [(asset_uri, asset_offset, segment_duration), ...]
    BlockPlan plan;
    plan.block_id = block_id;
    plan.channel_id = 1;
    plan.start_utc_ms = start_utc_ms;

    int64_t total_duration = 0;
    int32_t idx = 0;
    for (const auto& [uri, offset, duration] : segments) {
      Segment seg;
      seg.segment_index = idx++;
      seg.asset_uri = uri;
      seg.asset_start_offset_ms = offset;
      seg.segment_duration_ms = duration;
      plan.segments.push_back(seg);
      total_duration += duration;
    }
    plan.end_utc_ms = start_utc_ms + total_duration;

    BlockPlanValidator validator(assets_->AsDurationFn());
    auto result = validator.Validate(plan, start_utc_ms - 1000);
    EXPECT_TRUE(result.valid) << result.detail;

    return ValidatedBlockPlan{plan, result.boundaries, start_utc_ms - 1000};
  }

  // Helper: Compute join parameters
  JoinParameters ComputeJoin(const ValidatedBlockPlan& vp, int64_t t_join_ms) {
    auto result = JoinComputer::ComputeJoinParameters(vp, t_join_ms);
    EXPECT_TRUE(result.valid) << "Join computation failed";
    return result.params;
  }

  std::unique_ptr<FakeClock> clock_;
  std::unique_ptr<FakeAssetSource> assets_;
  std::unique_ptr<RecordingSink> sink_;
  std::unique_ptr<BlockPlanExecutor> executor_;
};

// =============================================================================
// MID-ASSET SEEK CONTRACT TESTS
// =============================================================================

// -----------------------------------------------------------------------------
// TEST-SEEK-001: Block at offset 0 matches baseline behavior
// Verifies that zero-offset blocks are unaffected by the seek machinery.
// -----------------------------------------------------------------------------
TEST_F(MidAssetSeekTest, OffsetZeroMatchesBaseline) {
  constexpr int64_t kBlockStart = 1000;
  constexpr int64_t kBlockEnd = 2000;
  constexpr int64_t kBlockDuration = kBlockEnd - kBlockStart;

  assets_->RegisterSimpleAsset("asset.mp4", 5000, kFrameDurationMs);
  auto plan = MakeValidatedPlan("B001", kBlockStart, kBlockEnd, "asset.mp4", 0);
  auto join = ComputeJoin(plan, kBlockStart);

  ASSERT_EQ(join.effective_asset_offset_ms, 0);

  clock_->SetMs(kBlockStart);
  auto result = executor_->Execute(plan, join, clock_.get(), assets_.get(), sink_.get());

  EXPECT_EQ(result.exit_code, ExecutorExitCode::kSuccess);
  ASSERT_FALSE(sink_->Empty());

  // First frame at CT=0, offset=0
  EXPECT_EQ(sink_->FirstCtMs().value(), 0);
  EXPECT_EQ(sink_->Frames().front().asset_offset_ms, 0);
  EXPECT_FALSE(sink_->Frames().front().is_pad);

  // CT monotonic, no frame past fence
  EXPECT_TRUE(sink_->AllCtMonotonic());
  EXPECT_TRUE(sink_->NoCtBeyond(kBlockDuration));

  // Deterministic frame count: ceil(duration / frame_duration)
  int64_t expected_frames = (kBlockDuration + kFrameDurationMs - 1) / kFrameDurationMs;
  EXPECT_EQ(static_cast<int64_t>(sink_->FrameCount()), expected_frames);
}

// -----------------------------------------------------------------------------
// TEST-SEEK-002: Block starting mid-asset: first frame has correct offset
// Verifies asset_offset_ms is propagated to the emitted frame metadata.
// -----------------------------------------------------------------------------
TEST_F(MidAssetSeekTest, MidAssetFirstFrameHasCorrectOffset) {
  constexpr int64_t kBlockStart = 1000;
  constexpr int64_t kBlockEnd = 2000;
  constexpr int64_t kAssetOffset = 5000;  // Start 5 seconds into asset

  assets_->RegisterSimpleAsset("movie.mp4", 60000, kFrameDurationMs);
  auto plan = MakeValidatedPlan("B001", kBlockStart, kBlockEnd, "movie.mp4", kAssetOffset);
  auto join = ComputeJoin(plan, kBlockStart);

  ASSERT_EQ(join.effective_asset_offset_ms, kAssetOffset);

  clock_->SetMs(kBlockStart);
  auto result = executor_->Execute(plan, join, clock_.get(), assets_.get(), sink_.get());

  EXPECT_EQ(result.exit_code, ExecutorExitCode::kSuccess);
  ASSERT_FALSE(sink_->Empty());

  // First frame must have the requested asset offset
  const auto& first = sink_->Frames().front();
  EXPECT_EQ(first.ct_ms, 0);
  EXPECT_EQ(first.asset_offset_ms, kAssetOffset);
  EXPECT_FALSE(first.is_pad);
}

// -----------------------------------------------------------------------------
// TEST-SEEK-003: Two blocks with different offsets have different first offsets
// Verifies that asset_start_offset_ms differentiates block behavior.
// -----------------------------------------------------------------------------
TEST_F(MidAssetSeekTest, DifferentOffsetsProduceDifferentFirstFrames) {
  constexpr int64_t kBlockStart = 1000;
  constexpr int64_t kBlockEnd = 2000;

  assets_->RegisterSimpleAsset("movie.mp4", 60000, kFrameDurationMs);

  // Block A: offset=0
  auto planA = MakeValidatedPlan("BA", kBlockStart, kBlockEnd, "movie.mp4", 0);
  auto joinA = ComputeJoin(planA, kBlockStart);
  clock_->SetMs(kBlockStart);
  executor_->Execute(planA, joinA, clock_.get(), assets_.get(), sink_.get());
  int64_t offsetA = sink_->Frames().front().asset_offset_ms;

  // Block B: offset=3000
  sink_->Clear();
  auto executor2 = std::make_unique<BlockPlanExecutor>();
  auto planB = MakeValidatedPlan("BB", kBlockStart, kBlockEnd, "movie.mp4", 3000);
  auto joinB = ComputeJoin(planB, kBlockStart);
  clock_->SetMs(kBlockStart);
  executor2->Execute(planB, joinB, clock_.get(), assets_.get(), sink_.get());
  int64_t offsetB = sink_->Frames().front().asset_offset_ms;

  EXPECT_EQ(offsetA, 0);
  EXPECT_EQ(offsetB, 3000);
  EXPECT_NE(offsetA, offsetB);
}

// -----------------------------------------------------------------------------
// TEST-SEEK-004: Frame count is deterministic regardless of offset
// Same block_duration → same frame count, whether offset is 0 or 5000.
// Frame count is CT-based (floor(duration / frame_duration)).
// -----------------------------------------------------------------------------
TEST_F(MidAssetSeekTest, FrameCountDeterministicRegardlessOfOffset) {
  constexpr int64_t kBlockStart = 1000;
  constexpr int64_t kBlockEnd = 2000;

  assets_->RegisterSimpleAsset("movie.mp4", 60000, kFrameDurationMs);

  // Run with offset=0
  auto plan0 = MakeValidatedPlan("B0", kBlockStart, kBlockEnd, "movie.mp4", 0);
  auto join0 = ComputeJoin(plan0, kBlockStart);
  clock_->SetMs(kBlockStart);
  executor_->Execute(plan0, join0, clock_.get(), assets_.get(), sink_.get());
  size_t count0 = sink_->FrameCount();

  // Run with offset=5000
  sink_->Clear();
  auto executor2 = std::make_unique<BlockPlanExecutor>();
  auto plan5k = MakeValidatedPlan("B5k", kBlockStart, kBlockEnd, "movie.mp4", 5000);
  auto join5k = ComputeJoin(plan5k, kBlockStart);
  clock_->SetMs(kBlockStart);
  executor2->Execute(plan5k, join5k, clock_.get(), assets_.get(), sink_.get());
  size_t count5k = sink_->FrameCount();

  EXPECT_EQ(count0, count5k);

  // Both should match expected count: ceil(duration / frame_duration)
  int64_t expected = ((kBlockEnd - kBlockStart) + kFrameDurationMs - 1) / kFrameDurationMs;
  EXPECT_EQ(static_cast<int64_t>(count0), expected);
}

// -----------------------------------------------------------------------------
// TEST-SEEK-005: Offset near end of asset causes underrun
// When offset + block_duration > asset_duration, the asset runs out of
// content. Remaining frames become pad frames.
// -----------------------------------------------------------------------------
TEST_F(MidAssetSeekTest, OffsetNearEndCausesUnderrun) {
  constexpr int64_t kBlockStart = 1000;
  constexpr int64_t kBlockEnd = 2000;
  constexpr int64_t kBlockDuration = kBlockEnd - kBlockStart;
  constexpr int64_t kAssetDuration = 3000;
  constexpr int64_t kAssetOffset = 2500;  // Only 500ms of content available

  assets_->RegisterSimpleAsset("short_tail.mp4", kAssetDuration, kFrameDurationMs);
  auto plan = MakeValidatedPlan("B001", kBlockStart, kBlockEnd, "short_tail.mp4", kAssetOffset);
  auto join = ComputeJoin(plan, kBlockStart);

  clock_->SetMs(kBlockStart);
  auto result = executor_->Execute(plan, join, clock_.get(), assets_.get(), sink_.get());

  EXPECT_EQ(result.exit_code, ExecutorExitCode::kSuccess);

  // Should have pad frames since asset runs out after ~500ms of content
  EXPECT_GT(sink_->PadFrameCount(), 0u);

  // Total frame count still deterministic: ceil(duration / frame_duration)
  int64_t expected_frames = (kBlockDuration + kFrameDurationMs - 1) / kFrameDurationMs;
  EXPECT_EQ(static_cast<int64_t>(sink_->FrameCount()), expected_frames);

  // Pad frames should be in the tail end of the block
  int64_t content_available_ms = kAssetDuration - kAssetOffset;  // 500ms
  EXPECT_TRUE(sink_->AllPadInCtRange(content_available_ms, kBlockDuration));
}

// -----------------------------------------------------------------------------
// TEST-SEEK-006: Validator rejects offset >= asset_duration
// CONTRACT-BLOCK-001 P6: asset_start_offset_ms must be < asset_duration.
// -----------------------------------------------------------------------------
TEST_F(MidAssetSeekTest, ValidatorRejectsOffsetBeyondDuration) {
  constexpr int64_t kBlockStart = 1000;
  constexpr int64_t kBlockEnd = 2000;
  constexpr int64_t kAssetDuration = 5000;

  assets_->RegisterSimpleAsset("asset.mp4", kAssetDuration, kFrameDurationMs);

  // Offset == asset_duration (invalid)
  BlockPlan plan;
  plan.block_id = "B001";
  plan.channel_id = 1;
  plan.start_utc_ms = kBlockStart;
  plan.end_utc_ms = kBlockEnd;

  Segment seg;
  seg.segment_index = 0;
  seg.asset_uri = "asset.mp4";
  seg.asset_start_offset_ms = kAssetDuration;  // Exactly at boundary
  seg.segment_duration_ms = kBlockEnd - kBlockStart;
  plan.segments.push_back(seg);

  BlockPlanValidator validator(assets_->AsDurationFn());
  auto result = validator.Validate(plan, kBlockStart - 1000);

  EXPECT_FALSE(result.valid);
  EXPECT_EQ(result.error, BlockPlanError::kInvalidOffset);

  // Offset > asset_duration (also invalid)
  plan.segments[0].asset_start_offset_ms = kAssetDuration + 1000;
  auto result2 = validator.Validate(plan, kBlockStart - 1000);

  EXPECT_FALSE(result2.valid);
  EXPECT_EQ(result2.error, BlockPlanError::kInvalidOffset);
}

// -----------------------------------------------------------------------------
// TEST-SEEK-007: Multi-segment block with per-segment offsets
// Each segment starts decoding at its own asset_start_offset_ms.
// The first frame of each segment has the correct offset.
// -----------------------------------------------------------------------------
TEST_F(MidAssetSeekTest, MultiSegmentPerSegmentOffsets) {
  constexpr int64_t kBlockStart = 1000;

  assets_->RegisterSimpleAsset("movie_a.mp4", 60000, kFrameDurationMs);
  assets_->RegisterSimpleAsset("movie_b.mp4", 60000, kFrameDurationMs);

  constexpr int64_t kOffsetA = 1000;
  constexpr int64_t kOffsetB = 5000;

  auto plan = MakeMultiSegmentPlan("B001", kBlockStart, {
    {"movie_a.mp4", kOffsetA, 500},   // CT 0-500, asset starts at 1000ms
    {"movie_b.mp4", kOffsetB, 500}    // CT 500-1000, asset starts at 5000ms
  });
  auto join = ComputeJoin(plan, kBlockStart);

  clock_->SetMs(kBlockStart);
  auto result = executor_->Execute(plan, join, clock_.get(), assets_.get(), sink_.get());

  EXPECT_EQ(result.exit_code, ExecutorExitCode::kSuccess);

  // First frame of segment 0 should have offset kOffsetA
  auto first_seg0 = sink_->FirstFrameFromSegment(0);
  ASSERT_TRUE(first_seg0.has_value());
  EXPECT_EQ(first_seg0->asset_offset_ms, kOffsetA);

  // First frame of segment 1 should have offset kOffsetB
  auto first_seg1 = sink_->FirstFrameFromSegment(1);
  ASSERT_TRUE(first_seg1.has_value());
  EXPECT_EQ(first_seg1->asset_offset_ms, kOffsetB);

  // Offsets are different
  EXPECT_NE(first_seg0->asset_offset_ms, first_seg1->asset_offset_ms);
}

}  // namespace
}  // namespace retrovue::blockplan::testing
