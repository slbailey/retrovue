// Repository: Retrovue-playout
// Component: BlockPlan Executor Contract Tests
// Purpose: Tests that define and verify executor behavior
// Contract Reference: docs/architecture/proposals/BlockLevelPlayoutAutonomy.md Section 7
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include "retrovue/blockplan/BlockPlanExecutor.hpp"
#include "retrovue/blockplan/BlockPlanQueue.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/BlockPlanValidator.hpp"
#include "ExecutorTestInfrastructure.hpp"

namespace retrovue::blockplan::testing {
namespace {

// =============================================================================
// Test Fixture
// =============================================================================

class BlockPlanExecutorTest : public ::testing::Test {
 protected:
  void SetUp() override {
    clock_ = std::make_unique<FakeClock>();
    assets_ = std::make_unique<FakeAssetSource>();
    sink_ = std::make_unique<RecordingSink>();
    executor_ = std::make_unique<BlockPlanExecutor>();
  }

  // Helper: Create a validated single-segment plan
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
// A. BLOCK START & FENCE TESTS
// =============================================================================

// -----------------------------------------------------------------------------
// TEST-EXEC-START-001: Early join emits nothing before start_utc_ms
// FROZEN: Hard block fence (Section 8.1.5)
// CONTRACT-JOIN-001: Early join waits for block start
// -----------------------------------------------------------------------------
TEST_F(BlockPlanExecutorTest, EarlyJoinEmitsNothingBeforeStartUtc) {
  constexpr int64_t kBlockStart = 1000;
  constexpr int64_t kBlockEnd = 2000;
  constexpr int64_t kJoinTime = 500;

  assets_->RegisterSimpleAsset("asset.mp4", 5000, 33);
  auto plan = MakeValidatedPlan("B001", kBlockStart, kBlockEnd, "asset.mp4");
  auto join = ComputeJoin(plan, kJoinTime);

  ASSERT_EQ(join.classification, JoinClassification::kEarly);
  ASSERT_EQ(join.wait_ms, 500);

  clock_->SetMs(kJoinTime);
  auto result = executor_->Execute(plan, join, clock_.get(), assets_.get(), sink_.get());

  // First emitted frame must be at or after block start
  ASSERT_FALSE(sink_->Empty());
  EXPECT_GE(sink_->FirstWallMs().value(), kBlockStart);
  EXPECT_EQ(result.exit_code, ExecutorExitCode::kSuccess);
}

// -----------------------------------------------------------------------------
// TEST-EXEC-START-002: First emitted frame has ct_ms == ct_start_ms
// CONTRACT-JOIN-002: Start offset computation
// FROZEN: Epoch is always block start (Section 8.1.1)
// -----------------------------------------------------------------------------
TEST_F(BlockPlanExecutorTest, FirstEmittedFrameHasCorrectCt) {
  constexpr int64_t kBlockStart = 1000;
  constexpr int64_t kBlockEnd = 2000;

  assets_->RegisterSimpleAsset("asset.mp4", 5000, 33);
  auto plan = MakeValidatedPlan("B001", kBlockStart, kBlockEnd, "asset.mp4");
  auto join = ComputeJoin(plan, kBlockStart);

  ASSERT_EQ(join.classification, JoinClassification::kMidBlock);
  ASSERT_EQ(join.ct_start_ms, 0);

  clock_->SetMs(kBlockStart);
  auto result = executor_->Execute(plan, join, clock_.get(), assets_.get(), sink_.get());

  ASSERT_FALSE(sink_->Empty());
  EXPECT_EQ(sink_->FirstCtMs().value(), 0);
  EXPECT_FALSE(sink_->Frames().front().is_pad);
  EXPECT_EQ(result.exit_code, ExecutorExitCode::kSuccess);
}

// -----------------------------------------------------------------------------
// TEST-EXEC-START-003: Mid-join first frame has ct_ms == ct_start_ms
// CONTRACT-JOIN-002: Start offset computation for mid-block
// -----------------------------------------------------------------------------
TEST_F(BlockPlanExecutorTest, MidJoinFirstFrameHasCorrectCt) {
  constexpr int64_t kBlockStart = 1000;
  constexpr int64_t kBlockEnd = 2000;
  constexpr int64_t kJoinTime = 1500;

  assets_->RegisterSimpleAsset("asset.mp4", 5000, 33);
  auto plan = MakeValidatedPlan("B001", kBlockStart, kBlockEnd, "asset.mp4");
  auto join = ComputeJoin(plan, kJoinTime);

  ASSERT_EQ(join.classification, JoinClassification::kMidBlock);
  ASSERT_EQ(join.ct_start_ms, 500);

  clock_->SetMs(kJoinTime);
  auto result = executor_->Execute(plan, join, clock_.get(), assets_.get(), sink_.get());

  ASSERT_FALSE(sink_->Empty());
  EXPECT_EQ(sink_->FirstCtMs().value(), 500);
  EXPECT_EQ(result.exit_code, ExecutorExitCode::kSuccess);
}

// -----------------------------------------------------------------------------
// TEST-EXEC-FENCE-001: Execution stops exactly at end_utc_ms
// CONTRACT-BLOCK-003: Block fence enforcement
// FROZEN: Hard block fence (Section 8.1.5)
// -----------------------------------------------------------------------------
TEST_F(BlockPlanExecutorTest, ExecutionStopsAtFence) {
  constexpr int64_t kBlockStart = 1000;
  constexpr int64_t kBlockEnd = 2000;
  constexpr int64_t kBlockDuration = kBlockEnd - kBlockStart;

  assets_->RegisterSimpleAsset("asset.mp4", 5000, 33);
  auto plan = MakeValidatedPlan("B001", kBlockStart, kBlockEnd, "asset.mp4");
  auto join = ComputeJoin(plan, kBlockStart);

  clock_->SetMs(kBlockStart);
  auto result = executor_->Execute(plan, join, clock_.get(), assets_.get(), sink_.get());

  // No frame should have CT >= block duration
  EXPECT_TRUE(sink_->NoCtBeyond(kBlockDuration));
  EXPECT_LT(sink_->LastCtMs().value(), kBlockDuration);
  EXPECT_EQ(result.exit_code, ExecutorExitCode::kSuccess);
  EXPECT_EQ(result.final_wall_ms, kBlockEnd);
}

// -----------------------------------------------------------------------------
// TEST-EXEC-CT-001: CT is strictly monotonic
// FROZEN: Monotonic CT advancement (Section 8.1.1)
// CONTRACT-BLOCK-002: CT advances monotonically
// -----------------------------------------------------------------------------
TEST_F(BlockPlanExecutorTest, CtIsStrictlyMonotonic) {
  constexpr int64_t kBlockStart = 1000;
  constexpr int64_t kBlockEnd = 2000;

  assets_->RegisterSimpleAsset("asset.mp4", 5000, 33);
  auto plan = MakeValidatedPlan("B001", kBlockStart, kBlockEnd, "asset.mp4");
  auto join = ComputeJoin(plan, kBlockStart);

  clock_->SetMs(kBlockStart);
  auto result = executor_->Execute(plan, join, clock_.get(), assets_.get(), sink_.get());

  EXPECT_TRUE(sink_->AllCtMonotonic());
  EXPECT_EQ(result.exit_code, ExecutorExitCode::kSuccess);
}

// =============================================================================
// B. SEGMENT EXECUTION TESTS
// =============================================================================

// -----------------------------------------------------------------------------
// TEST-EXEC-SEG-001: Segment transitions occur at CT boundaries
// CONTRACT-SEG-002: Segment transition at CT boundary
// FROZEN: Hard segment CT boundaries (Section 8.1.5)
// -----------------------------------------------------------------------------
TEST_F(BlockPlanExecutorTest, SegmentTransitionsAtCtBoundary) {
  constexpr int64_t kBlockStart = 1000;

  assets_->RegisterSimpleAsset("seg0.mp4", 1000, 33);
  assets_->RegisterSimpleAsset("seg1.mp4", 1000, 33);

  auto plan = MakeMultiSegmentPlan("B001", kBlockStart, {
    {"seg0.mp4", 0, 500},
    {"seg1.mp4", 0, 500}
  });
  auto join = ComputeJoin(plan, kBlockStart);

  clock_->SetMs(kBlockStart);
  auto result = executor_->Execute(plan, join, clock_.get(), assets_.get(), sink_.get());

  // All frames with CT < 500 should be from seg0
  // All frames with CT >= 500 should be from seg1
  for (const auto& frame : sink_->Frames()) {
    if (frame.ct_ms < 500) {
      EXPECT_EQ(frame.segment_index, 0) << "CT=" << frame.ct_ms;
    } else {
      EXPECT_EQ(frame.segment_index, 1) << "CT=" << frame.ct_ms;
    }
  }
  EXPECT_EQ(result.exit_code, ExecutorExitCode::kSuccess);
}

// -----------------------------------------------------------------------------
// TEST-EXEC-SEG-002: Correct segment selected on mid-block join
// CONTRACT-JOIN-002: Find segment containing CT
// -----------------------------------------------------------------------------
TEST_F(BlockPlanExecutorTest, CorrectSegmentSelectedOnMidJoin) {
  constexpr int64_t kBlockStart = 1000;
  constexpr int64_t kJoinTime = 1500;  // 500ms into block

  assets_->RegisterSimpleAsset("seg0.mp4", 1000, 33);
  assets_->RegisterSimpleAsset("seg1.mp4", 1000, 33);
  assets_->RegisterSimpleAsset("seg2.mp4", 1000, 33);

  auto plan = MakeMultiSegmentPlan("B001", kBlockStart, {
    {"seg0.mp4", 0, 300},   // CT 0-300
    {"seg1.mp4", 0, 400},   // CT 300-700
    {"seg2.mp4", 0, 300}    // CT 700-1000
  });
  auto join = ComputeJoin(plan, kJoinTime);

  ASSERT_EQ(join.ct_start_ms, 500);
  ASSERT_EQ(join.start_segment_index, 1);

  clock_->SetMs(kJoinTime);
  auto result = executor_->Execute(plan, join, clock_.get(), assets_.get(), sink_.get());

  // First emitted frame should be from seg1
  ASSERT_FALSE(sink_->Empty());
  EXPECT_EQ(sink_->Frames().front().segment_index, 1);

  // No frames from seg0
  EXPECT_EQ(sink_->FramesFromSegment(0), 0u);
  EXPECT_EQ(result.exit_code, ExecutorExitCode::kSuccess);
}

// -----------------------------------------------------------------------------
// TEST-EXEC-SEG-003: Correct asset offset applied on mid-join
// CONTRACT-JOIN-002: Effective asset offset computation
// -----------------------------------------------------------------------------
TEST_F(BlockPlanExecutorTest, CorrectAssetOffsetOnMidJoin) {
  constexpr int64_t kBlockStart = 1000;
  constexpr int64_t kJoinTime = 1200;
  constexpr int64_t kAssetOffset = 1000;

  assets_->RegisterSimpleAsset("asset.mp4", 5000, 33);

  BlockPlan plan;
  plan.block_id = "B001";
  plan.channel_id = 1;
  plan.start_utc_ms = kBlockStart;
  plan.end_utc_ms = kBlockStart + 500;

  Segment seg;
  seg.segment_index = 0;
  seg.asset_uri = "asset.mp4";
  seg.asset_start_offset_ms = kAssetOffset;
  seg.segment_duration_ms = 500;
  plan.segments.push_back(seg);

  BlockPlanValidator validator(assets_->AsDurationFn());
  auto vresult = validator.Validate(plan, kBlockStart - 1000);
  ASSERT_TRUE(vresult.valid);

  ValidatedBlockPlan vp{plan, vresult.boundaries, kBlockStart - 1000};
  auto join = ComputeJoin(vp, kJoinTime);

  ASSERT_EQ(join.effective_asset_offset_ms, 1200);  // 1000 + 200

  clock_->SetMs(kJoinTime);
  auto result = executor_->Execute(vp, join, clock_.get(), assets_.get(), sink_.get());

  // First frame should have asset offset ~1200
  ASSERT_FALSE(sink_->Empty());
  EXPECT_EQ(sink_->Frames().front().asset_offset_ms, 1200);
  EXPECT_EQ(result.exit_code, ExecutorExitCode::kSuccess);
}

// =============================================================================
// C. UNDERRUN BEHAVIOR TESTS
// =============================================================================

// -----------------------------------------------------------------------------
// TEST-EXEC-UNDER-001: Asset EOF pads to CT boundary
// CONTRACT-SEG-003: Segment underrun (pad-to-CT)
// INV-BLOCKPLAN-SEGMENT-PAD-TO-CT
// -----------------------------------------------------------------------------
TEST_F(BlockPlanExecutorTest, UnderrunPadsToCTBoundary) {
  constexpr int64_t kBlockStart = 1000;

  // seg0 asset: 400ms (underrun by 100ms in 500ms slot)
  assets_->RegisterSimpleAsset("seg0_short.mp4", 400, 33);
  // seg1 asset: normal
  assets_->RegisterSimpleAsset("seg1.mp4", 1000, 33);

  auto plan = MakeMultiSegmentPlan("B001", kBlockStart, {
    {"seg0_short.mp4", 0, 500},   // 500ms allocated, 400ms asset
    {"seg1.mp4", 0, 500}
  });
  auto join = ComputeJoin(plan, kBlockStart);

  clock_->SetMs(kBlockStart);
  auto result = executor_->Execute(plan, join, clock_.get(), assets_.get(), sink_.get());

  // Check for pad frames in CT range [~400, 500)
  EXPECT_TRUE(sink_->AllPadInCtRange(400, 500));
  EXPECT_GT(sink_->PadFrameCount(), 0u);

  // seg1 frames should exist
  EXPECT_GT(sink_->FramesFromSegment(1), 0u);
  EXPECT_EQ(result.exit_code, ExecutorExitCode::kSuccess);
}

// -----------------------------------------------------------------------------
// TEST-EXEC-UNDER-002: Last segment underrun pads until block fence
// CONTRACT-SEG-003: Last segment underrun
// FROZEN: Hard block fence (Section 8.1.5)
// -----------------------------------------------------------------------------
TEST_F(BlockPlanExecutorTest, LastSegmentUnderrunPadsToFence) {
  constexpr int64_t kBlockStart = 1000;
  constexpr int64_t kBlockEnd = 2000;

  assets_->RegisterSimpleAsset("short.mp4", 800, 33);

  auto plan = MakeValidatedPlan("B001", kBlockStart, kBlockEnd, "short.mp4");
  auto join = ComputeJoin(plan, kBlockStart);

  clock_->SetMs(kBlockStart);
  auto result = executor_->Execute(plan, join, clock_.get(), assets_.get(), sink_.get());

  // Frames in CT range [~800, 1000) should be pad frames
  EXPECT_TRUE(sink_->AllPadInCtRange(800, 1000));

  // Block should complete successfully
  EXPECT_EQ(result.exit_code, ExecutorExitCode::kSuccess);
  EXPECT_EQ(result.final_wall_ms, kBlockEnd);
}

// -----------------------------------------------------------------------------
// TEST-EXEC-UNDER-003: Padding is deterministic (same input = same pad count)
// Section 7.5.9 TEST-DET-002
// -----------------------------------------------------------------------------
TEST_F(BlockPlanExecutorTest, UnderrunPaddingIsDeterministic) {
  constexpr int64_t kBlockStart = 1000;
  constexpr int64_t kBlockEnd = 2000;

  assets_->RegisterSimpleAsset("short.mp4", 800, 33);

  auto plan = MakeValidatedPlan("B001", kBlockStart, kBlockEnd, "short.mp4");
  auto join = ComputeJoin(plan, kBlockStart);

  // Run 1
  clock_->SetMs(kBlockStart);
  executor_->Execute(plan, join, clock_.get(), assets_.get(), sink_.get());
  size_t pad_count_1 = sink_->PadFrameCount();
  int64_t last_ct_1 = sink_->LastCtMs().value();

  // Run 2
  sink_->Clear();
  clock_->SetMs(kBlockStart);
  auto executor2 = std::make_unique<BlockPlanExecutor>();
  executor2->Execute(plan, join, clock_.get(), assets_.get(), sink_.get());
  size_t pad_count_2 = sink_->PadFrameCount();
  int64_t last_ct_2 = sink_->LastCtMs().value();

  EXPECT_EQ(pad_count_1, pad_count_2);
  EXPECT_EQ(last_ct_1, last_ct_2);
}

// =============================================================================
// D. OVERRUN BEHAVIOR TESTS
// =============================================================================

// -----------------------------------------------------------------------------
// TEST-EXEC-OVER-001: Asset content beyond segment duration is truncated
// CONTRACT-SEG-004: Segment overrun (truncate)
// INV-BLOCKPLAN-SEGMENT-TRUNCATE
// -----------------------------------------------------------------------------
TEST_F(BlockPlanExecutorTest, OverrunTruncatesAtCTBoundary) {
  constexpr int64_t kBlockStart = 1000;

  // seg0 asset: 800ms (overrun by 300ms in 500ms slot)
  assets_->RegisterSimpleAsset("seg0_long.mp4", 800, 33);
  // seg1 asset: normal
  assets_->RegisterSimpleAsset("seg1.mp4", 1000, 33);

  auto plan = MakeMultiSegmentPlan("B001", kBlockStart, {
    {"seg0_long.mp4", 0, 500},   // 500ms allocated, 800ms asset
    {"seg1.mp4", 0, 500}
  });
  auto join = ComputeJoin(plan, kBlockStart);

  clock_->SetMs(kBlockStart);
  auto result = executor_->Execute(plan, join, clock_.get(), assets_.get(), sink_.get());

  // No real (non-pad) frame from seg0 should have CT >= 500
  EXPECT_TRUE(sink_->NoRealFrameBeyondCt(0, 500));

  // seg1 frames should exist starting at CT >= 500
  auto first_seg1 = sink_->FirstFrameFromSegment(1);
  ASSERT_TRUE(first_seg1.has_value());
  EXPECT_GE(first_seg1->ct_ms, 500);

  EXPECT_EQ(result.exit_code, ExecutorExitCode::kSuccess);
}

// -----------------------------------------------------------------------------
// TEST-EXEC-OVER-002: No frame emitted past segment CT boundary
// CONTRACT-SEG-004: Hard truncation
// FROZEN: Hard segment CT boundaries (Section 8.1.5)
// -----------------------------------------------------------------------------
TEST_F(BlockPlanExecutorTest, NoFramePastSegmentBoundary) {
  constexpr int64_t kBlockStart = 1000;

  assets_->RegisterSimpleAsset("long.mp4", 1000, 33);

  BlockPlan plan;
  plan.block_id = "B001";
  plan.channel_id = 1;
  plan.start_utc_ms = kBlockStart;
  plan.end_utc_ms = kBlockStart + 500;

  Segment seg;
  seg.segment_index = 0;
  seg.asset_uri = "long.mp4";
  seg.asset_start_offset_ms = 0;
  seg.segment_duration_ms = 500;
  plan.segments.push_back(seg);

  BlockPlanValidator validator(assets_->AsDurationFn());
  auto vresult = validator.Validate(plan, kBlockStart - 1000);
  ASSERT_TRUE(vresult.valid);

  ValidatedBlockPlan vp{plan, vresult.boundaries, kBlockStart - 1000};
  auto join = ComputeJoin(vp, kBlockStart);

  clock_->SetMs(kBlockStart);
  auto result = executor_->Execute(vp, join, clock_.get(), assets_.get(), sink_.get());

  // No frame should have CT >= 500
  EXPECT_TRUE(sink_->NoCtBeyond(500));
  EXPECT_EQ(result.exit_code, ExecutorExitCode::kSuccess);
}

// =============================================================================
// E. FAILURE SEMANTICS TESTS
// =============================================================================

// -----------------------------------------------------------------------------
// TEST-EXEC-FAIL-001: Asset failure terminates immediately
// CONTRACT-SEG-005: Segment failure propagation
// FROZEN: No segment-level recovery (Section 8.1.3)
// -----------------------------------------------------------------------------
TEST_F(BlockPlanExecutorTest, AssetFailureTerminatesImmediately) {
  constexpr int64_t kBlockStart = 1000;
  constexpr int64_t kBlockEnd = 2000;

  // Asset fails when reading at 300ms offset
  assets_->RegisterFailingAsset("failing.mp4", 1000, 300);

  auto plan = MakeValidatedPlan("B001", kBlockStart, kBlockEnd, "failing.mp4");
  auto join = ComputeJoin(plan, kBlockStart);

  clock_->SetMs(kBlockStart);
  auto result = executor_->Execute(plan, join, clock_.get(), assets_.get(), sink_.get());

  EXPECT_EQ(result.exit_code, ExecutorExitCode::kAssetError);
  // Execution stopped mid-block
  EXPECT_LT(result.final_ct_ms, 1000);
}

// -----------------------------------------------------------------------------
// TEST-EXEC-FAIL-002: No retry on asset failure
// FORBIDDEN: Asset retry (Section 8.3.3)
// CONTRACT-SEG-005: No retry
// -----------------------------------------------------------------------------
TEST_F(BlockPlanExecutorTest, NoRetryOnFailure) {
  constexpr int64_t kBlockStart = 1000;
  constexpr int64_t kBlockEnd = 2000;

  assets_->RegisterFailingAsset("failing.mp4", 1000, 300);

  auto plan = MakeValidatedPlan("B001", kBlockStart, kBlockEnd, "failing.mp4");
  auto join = ComputeJoin(plan, kBlockStart);

  clock_->SetMs(kBlockStart);
  auto result = executor_->Execute(plan, join, clock_.get(), assets_.get(), sink_.get());

  // Verify immediate termination (no frames after failure point)
  EXPECT_EQ(result.exit_code, ExecutorExitCode::kAssetError);

  // All frames should be before the failure offset (~300ms CT)
  for (const auto& frame : sink_->Frames()) {
    EXPECT_LT(frame.ct_ms, 300 + 33);  // Allow one frame margin
  }
}

// -----------------------------------------------------------------------------
// TEST-EXEC-FAIL-003: No skip to next segment on failure
// FORBIDDEN: Segment skipping (Section 8.3.1)
// CONTRACT-SEG-005: No skip
// -----------------------------------------------------------------------------
TEST_F(BlockPlanExecutorTest, NoSkipOnFailure) {
  constexpr int64_t kBlockStart = 1000;

  assets_->RegisterFailingAsset("seg0_fail.mp4", 1000, 200);
  assets_->RegisterSimpleAsset("seg1.mp4", 1000, 33);

  auto plan = MakeMultiSegmentPlan("B001", kBlockStart, {
    {"seg0_fail.mp4", 0, 500},
    {"seg1.mp4", 0, 500}
  });
  auto join = ComputeJoin(plan, kBlockStart);

  clock_->SetMs(kBlockStart);
  auto result = executor_->Execute(plan, join, clock_.get(), assets_.get(), sink_.get());

  // No frames from seg1
  EXPECT_EQ(sink_->FramesFromSegment(1), 0u);
  EXPECT_EQ(result.exit_code, ExecutorExitCode::kAssetError);
}

// -----------------------------------------------------------------------------
// TEST-EXEC-FAIL-004: No filler substitution on failure
// FORBIDDEN: Filler substitution (Section 8.3.3)
// -----------------------------------------------------------------------------
TEST_F(BlockPlanExecutorTest, NoFillerSubstitutionOnFailure) {
  constexpr int64_t kBlockStart = 1000;
  constexpr int64_t kBlockEnd = 2000;

  assets_->RegisterFailingAsset("failing.mp4", 1000, 300);

  auto plan = MakeValidatedPlan("B001", kBlockStart, kBlockEnd, "failing.mp4");
  auto join = ComputeJoin(plan, kBlockStart);

  clock_->SetMs(kBlockStart);
  auto result = executor_->Execute(plan, join, clock_.get(), assets_.get(), sink_.get());

  EXPECT_EQ(result.exit_code, ExecutorExitCode::kAssetError);

  // No pad frames after the failure CT
  // All pad frames (if any) must be before failure
  for (const auto& frame : sink_->Frames()) {
    if (frame.is_pad) {
      // Should not happen in this test - asset has content up to failure
      // If it does, it must be before failure point
      EXPECT_LT(frame.ct_ms, 300);
    }
  }

  // Last frame should NOT be a pad frame
  ASSERT_FALSE(sink_->Empty());
  EXPECT_FALSE(sink_->Frames().back().is_pad);
}

// =============================================================================
// ADDITIONAL INVARIANT TESTS
// =============================================================================

// -----------------------------------------------------------------------------
// TEST-EXEC-EPOCH-001: Epoch is always block start (not join time)
// FROZEN: Epoch immutability (Section 8.1.1)
// -----------------------------------------------------------------------------
TEST_F(BlockPlanExecutorTest, EpochIsBlockStartNotJoinTime) {
  constexpr int64_t kBlockStart = 1000;
  constexpr int64_t kBlockEnd = 2000;
  constexpr int64_t kJoinTime = 1500;

  assets_->RegisterSimpleAsset("asset.mp4", 5000, 33);

  auto plan = MakeValidatedPlan("B001", kBlockStart, kBlockEnd, "asset.mp4");
  auto join = ComputeJoin(plan, kJoinTime);

  ASSERT_EQ(join.ct_start_ms, 500);

  clock_->SetMs(kJoinTime);
  auto result = executor_->Execute(plan, join, clock_.get(), assets_.get(), sink_.get());

  // First frame CT should be ~500 (relative to block start), not 0
  ASSERT_FALSE(sink_->Empty());
  EXPECT_EQ(sink_->FirstCtMs().value(), 500);
  EXPECT_EQ(result.exit_code, ExecutorExitCode::kSuccess);
}

// -----------------------------------------------------------------------------
// TEST-EXEC-WALL-001: No wall clock dependency in segment transitions
// Section 7.5.9 TEST-DET-003
// CONTRACT-SEG-001: CT boundaries derived from durations, not wall clock
// -----------------------------------------------------------------------------
TEST_F(BlockPlanExecutorTest, NoWallClockDependencyInTransitions) {
  constexpr int64_t kBlockStart = 1000;

  assets_->RegisterSimpleAsset("seg0.mp4", 1000, 33);
  assets_->RegisterSimpleAsset("seg1.mp4", 1000, 33);

  auto plan = MakeMultiSegmentPlan("B001", kBlockStart, {
    {"seg0.mp4", 0, 500},
    {"seg1.mp4", 0, 500}
  });
  auto join = ComputeJoin(plan, kBlockStart);

  clock_->SetMs(kBlockStart);
  auto result = executor_->Execute(plan, join, clock_.get(), assets_.get(), sink_.get());

  // Find the transition point
  int64_t transition_ct = -1;
  for (size_t i = 1; i < sink_->Frames().size(); ++i) {
    if (sink_->Frames()[i-1].segment_index == 0 &&
        sink_->Frames()[i].segment_index == 1) {
      transition_ct = sink_->Frames()[i].ct_ms;
      break;
    }
  }

  // Transition should happen at CT=500 (or closest frame boundary >= 500)
  EXPECT_GE(transition_ct, 500);
  EXPECT_LT(transition_ct, 500 + 33);  // Within one frame
  EXPECT_EQ(result.exit_code, ExecutorExitCode::kSuccess);
}

}  // namespace
}  // namespace retrovue::blockplan::testing
