// Repository: Retrovue-playout
// Component: BlockPlan Contract Tests
// Purpose: Test Section 7 contracts from BlockLevelPlayoutAutonomy.md
// Contract Reference: docs/architecture/proposals/BlockLevelPlayoutAutonomy.md Section 7
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <map>
#include <string>

#include "retrovue/blockplan/BlockPlanQueue.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/BlockPlanValidator.hpp"

namespace retrovue::blockplan {
namespace {

// =============================================================================
// Test Fixtures
// =============================================================================

// Fake asset store for testing
// Returns predefined durations; -1 for missing assets
class FakeAssetStore {
 public:
  void SetAssetDuration(const std::string& uri, int64_t duration_ms) {
    assets_[uri] = duration_ms;
  }

  int64_t GetDuration(const std::string& uri) const {
    auto it = assets_.find(uri);
    if (it == assets_.end()) {
      return -1;  // Asset not found
    }
    return it->second;
  }

  AssetDurationFn AsDurationFn() const {
    return [this](const std::string& uri) { return GetDuration(uri); };
  }

 private:
  std::map<std::string, int64_t> assets_;
};

// Helper to create a valid single-segment BlockPlan
BlockPlan MakeValidSingleSegmentPlan(
    const std::string& block_id = "B001",
    int64_t start = 1000000,
    int64_t end = 1060000,
    const std::string& asset = "valid.mp4",
    int64_t offset = 0) {
  BlockPlan plan;
  plan.block_id = block_id;
  plan.channel_id = 1;
  plan.start_utc_ms = start;
  plan.end_utc_ms = end;

  Segment seg;
  seg.segment_index = 0;
  seg.asset_uri = asset;
  seg.asset_start_offset_ms = offset;
  seg.segment_duration_ms = end - start;
  plan.segments.push_back(seg);

  return plan;
}

// =============================================================================
// TEST-BLOCK-ACCEPT-001: Valid single-segment block accepted
// CONTRACT-BLOCK-001
// =============================================================================
TEST(BlockPlanAcceptance, ValidSingleSegmentBlockAccepted) {
  FakeAssetStore store;
  store.SetAssetDuration("valid.mp4", 120000);  // 2 minutes

  BlockPlanValidator validator(store.AsDurationFn());
  BlockPlan plan = MakeValidSingleSegmentPlan("B001", 1000000, 1060000, "valid.mp4", 0);

  // T_receipt before block ends
  int64_t t_receipt = 999000;

  auto result = validator.Validate(plan, t_receipt);

  // ASSERTIONS:
  // - Response is synchronous (implicit - function returns)
  // - Block accessible (valid result)
  // - No error returned
  ASSERT_TRUE(result.valid) << "Expected valid, got: " << result.detail;
  EXPECT_EQ(result.error, BlockPlanError::kNone);
  EXPECT_FALSE(result.boundaries.empty());
}

// =============================================================================
// TEST-BLOCK-ACCEPT-002: Stale block rejected
// CONTRACT-BLOCK-001 E1: STALE_BLOCK_FROM_CORE
// =============================================================================
TEST(BlockPlanAcceptance, StaleBlockRejected) {
  FakeAssetStore store;
  store.SetAssetDuration("valid.mp4", 120000);

  BlockPlanValidator validator(store.AsDurationFn());
  BlockPlan plan = MakeValidSingleSegmentPlan("B002", 1000000, 1060000, "valid.mp4", 0);

  // T_receipt AFTER block ends (stale)
  int64_t t_receipt = 1060001;

  auto result = validator.Validate(plan, t_receipt);

  // ASSERTIONS:
  // - Block not valid
  // - Error code is STALE_BLOCK_FROM_CORE
  // - Staleness included in error detail
  EXPECT_FALSE(result.valid);
  EXPECT_EQ(result.error, BlockPlanError::kStaleBlockFromCore);
  EXPECT_TRUE(result.detail.find("1ms") != std::string::npos ||
              result.detail.find("ago") != std::string::npos);
}

// =============================================================================
// TEST-BLOCK-ACCEPT-003: Duration mismatch rejected
// CONTRACT-BLOCK-001 E2: SEGMENT_DURATION_MISMATCH
// =============================================================================
TEST(BlockPlanAcceptance, DurationMismatchRejected) {
  FakeAssetStore store;
  store.SetAssetDuration("a.mp4", 100000);
  store.SetAssetDuration("b.mp4", 100000);

  BlockPlanValidator validator(store.AsDurationFn());

  BlockPlan plan;
  plan.block_id = "B003";
  plan.channel_id = 1;
  plan.start_utc_ms = 1000000;
  plan.end_utc_ms = 1060000;  // 60 seconds

  // Segments sum to 50 seconds, not 60
  Segment seg0;
  seg0.segment_index = 0;
  seg0.asset_uri = "a.mp4";
  seg0.asset_start_offset_ms = 0;
  seg0.segment_duration_ms = 30000;
  plan.segments.push_back(seg0);

  Segment seg1;
  seg1.segment_index = 1;
  seg1.asset_uri = "b.mp4";
  seg1.asset_start_offset_ms = 0;
  seg1.segment_duration_ms = 20000;
  plan.segments.push_back(seg1);

  int64_t t_receipt = 999000;
  auto result = validator.Validate(plan, t_receipt);

  // ASSERTIONS:
  // - Block not valid
  // - Error indicates expected vs actual
  EXPECT_FALSE(result.valid);
  EXPECT_EQ(result.error, BlockPlanError::kSegmentDurationMismatch);
  EXPECT_TRUE(result.detail.find("50000") != std::string::npos);
  EXPECT_TRUE(result.detail.find("60000") != std::string::npos);
}

// =============================================================================
// TEST-BLOCK-ACCEPT-004: Non-contiguous segment indices rejected
// CONTRACT-BLOCK-001 E3: INVALID_SEGMENT_INDEX
// =============================================================================
TEST(BlockPlanAcceptance, NonContiguousSegmentIndicesRejected) {
  FakeAssetStore store;
  store.SetAssetDuration("a.mp4", 100000);
  store.SetAssetDuration("b.mp4", 100000);

  BlockPlanValidator validator(store.AsDurationFn());

  BlockPlan plan;
  plan.block_id = "B004";
  plan.channel_id = 1;
  plan.start_utc_ms = 1000000;
  plan.end_utc_ms = 1060000;

  // Gap: indices 0 and 2 (missing 1)
  Segment seg0;
  seg0.segment_index = 0;
  seg0.asset_uri = "a.mp4";
  seg0.asset_start_offset_ms = 0;
  seg0.segment_duration_ms = 30000;
  plan.segments.push_back(seg0);

  Segment seg2;
  seg2.segment_index = 2;  // Gap!
  seg2.asset_uri = "b.mp4";
  seg2.asset_start_offset_ms = 0;
  seg2.segment_duration_ms = 30000;
  plan.segments.push_back(seg2);

  int64_t t_receipt = 999000;
  auto result = validator.Validate(plan, t_receipt);

  // ASSERTIONS:
  // - Error indicates gap at index 1
  EXPECT_FALSE(result.valid);
  EXPECT_EQ(result.error, BlockPlanError::kInvalidSegmentIndex);
  EXPECT_TRUE(result.detail.find("gap") != std::string::npos ||
              result.detail.find("1") != std::string::npos);
}

// =============================================================================
// TEST-BLOCK-ACCEPT-005: Missing asset rejected
// CONTRACT-BLOCK-001 E4: ASSET_MISSING
// =============================================================================
TEST(BlockPlanAcceptance, MissingAssetRejected) {
  FakeAssetStore store;
  // "nonexistent.mp4" not added to store

  BlockPlanValidator validator(store.AsDurationFn());
  BlockPlan plan = MakeValidSingleSegmentPlan("B005", 1000000, 1060000, "nonexistent.mp4", 0);

  int64_t t_receipt = 999000;
  auto result = validator.Validate(plan, t_receipt);

  // ASSERTIONS:
  // - Error indicates which asset is missing
  EXPECT_FALSE(result.valid);
  EXPECT_EQ(result.error, BlockPlanError::kAssetMissing);
  EXPECT_TRUE(result.detail.find("nonexistent.mp4") != std::string::npos);
}

// =============================================================================
// TEST-BLOCK-ACCEPT-006: Queue full rejected
// CONTRACT-LOOK-001 R3: QUEUE_FULL
// =============================================================================
TEST(BlockPlanAcceptance, QueueFullRejected) {
  FakeAssetStore store;
  store.SetAssetDuration("valid.mp4", 120000);

  BlockPlanValidator validator(store.AsDurationFn());
  BlockPlanQueue queue;

  // Fill both slots
  auto plan1 = MakeValidSingleSegmentPlan("B001", 1000000, 1060000, "valid.mp4", 0);
  auto result1 = validator.Validate(plan1, 999000);
  ASSERT_TRUE(result1.valid);
  ValidatedBlockPlan vp1{plan1, result1.boundaries, 999000};
  auto enq1 = queue.Enqueue(std::move(vp1));
  ASSERT_TRUE(enq1.success);

  auto plan2 = MakeValidSingleSegmentPlan("B002", 1060000, 1120000, "valid.mp4", 0);
  auto result2 = validator.Validate(plan2, 999000);
  ASSERT_TRUE(result2.valid);
  ValidatedBlockPlan vp2{plan2, result2.boundaries, 999000};
  auto enq2 = queue.Enqueue(std::move(vp2));
  ASSERT_TRUE(enq2.success);

  // Third block should be rejected
  auto plan3 = MakeValidSingleSegmentPlan("B003", 1120000, 1180000, "valid.mp4", 0);
  auto result3 = validator.Validate(plan3, 999000);
  ASSERT_TRUE(result3.valid);
  ValidatedBlockPlan vp3{plan3, result3.boundaries, 999000};
  auto enq3 = queue.Enqueue(std::move(vp3));

  // ASSERTIONS:
  // - Existing blocks unchanged
  // - New block not queued
  EXPECT_FALSE(enq3.success);
  EXPECT_EQ(enq3.error, BlockPlanError::kQueueFull);
  EXPECT_EQ(queue.Size(), 2u);
}

// =============================================================================
// TEST-CT-001: CT boundaries computed correctly for multi-segment block
// CONTRACT-SEG-001
// =============================================================================
TEST(CTBoundary, ComputedCorrectlyForMultiSegment) {
  FakeAssetStore store;
  store.SetAssetDuration("a.mp4", 100000);
  store.SetAssetDuration("b.mp4", 100000);
  store.SetAssetDuration("c.mp4", 100000);

  BlockPlanValidator validator(store.AsDurationFn());

  BlockPlan plan;
  plan.block_id = "B001";
  plan.channel_id = 1;
  plan.start_utc_ms = 0;
  plan.end_utc_ms = 60000;

  Segment seg0{0, "a.mp4", 0, 10000};
  Segment seg1{1, "b.mp4", 0, 20000};
  Segment seg2{2, "c.mp4", 0, 30000};
  plan.segments = {seg0, seg1, seg2};

  auto result = validator.Validate(plan, 0);
  ASSERT_TRUE(result.valid);

  // ASSERTIONS:
  // segment[0]: start_ct=0, end_ct=10000
  // segment[1]: start_ct=10000, end_ct=30000
  // segment[2]: start_ct=30000, end_ct=60000
  ASSERT_EQ(result.boundaries.size(), 3u);

  EXPECT_EQ(result.boundaries[0].segment_index, 0);
  EXPECT_EQ(result.boundaries[0].start_ct_ms, 0);
  EXPECT_EQ(result.boundaries[0].end_ct_ms, 10000);

  EXPECT_EQ(result.boundaries[1].segment_index, 1);
  EXPECT_EQ(result.boundaries[1].start_ct_ms, 10000);
  EXPECT_EQ(result.boundaries[1].end_ct_ms, 30000);

  EXPECT_EQ(result.boundaries[2].segment_index, 2);
  EXPECT_EQ(result.boundaries[2].start_ct_ms, 30000);
  EXPECT_EQ(result.boundaries[2].end_ct_ms, 60000);

  // Invariant: segment[i].end_ct == segment[i+1].start_ct
  for (size_t i = 0; i < result.boundaries.size() - 1; ++i) {
    EXPECT_EQ(result.boundaries[i].end_ct_ms,
              result.boundaries[i + 1].start_ct_ms);
  }

  // Invariant: segment[N-1].end_ct == block_duration
  EXPECT_EQ(result.boundaries.back().end_ct_ms, plan.duration_ms());
}

// =============================================================================
// TEST-JOIN-001: Early join waits for block start
// CONTRACT-JOIN-001, CONTRACT-JOIN-002
// =============================================================================
TEST(JoinParameters, EarlyJoinWaitsForBlockStart) {
  FakeAssetStore store;
  store.SetAssetDuration("valid.mp4", 120000);

  BlockPlanValidator validator(store.AsDurationFn());
  BlockPlan plan = MakeValidSingleSegmentPlan("B001", 1000000, 1060000, "valid.mp4", 5000);

  auto result = validator.Validate(plan, 999000);
  ASSERT_TRUE(result.valid);

  ValidatedBlockPlan validated{plan, result.boundaries, 999000};

  // Join 1 second early
  int64_t t_join = 999000;
  auto join_result = JoinComputer::ComputeJoinParameters(validated, t_join);

  // ASSERTIONS:
  // - Wait 1000ms
  // - Begin at CT=0, asset_offset=5000 (from plan)
  // - epoch_wall_ms = 1000000 (block start)
  ASSERT_TRUE(join_result.valid);
  EXPECT_EQ(join_result.params.classification, JoinClassification::kEarly);
  EXPECT_EQ(join_result.params.wait_ms, 1000);
  EXPECT_EQ(join_result.params.ct_start_ms, 0);
  EXPECT_EQ(join_result.params.start_segment_index, 0);
  EXPECT_EQ(join_result.params.effective_asset_offset_ms, 5000);
}

// =============================================================================
// TEST-JOIN-002: Mid-block join computes correct offset
// CONTRACT-JOIN-002
// =============================================================================
TEST(JoinParameters, MidBlockJoinComputesCorrectOffset) {
  FakeAssetStore store;
  store.SetAssetDuration("a.mp4", 100000);
  store.SetAssetDuration("b.mp4", 100000);

  BlockPlanValidator validator(store.AsDurationFn());

  BlockPlan plan;
  plan.block_id = "B001";
  plan.channel_id = 1;
  plan.start_utc_ms = 1000000;
  plan.end_utc_ms = 1060000;

  // Two segments: 30s each
  Segment seg0{0, "a.mp4", 0, 30000};
  Segment seg1{1, "b.mp4", 0, 30000};
  plan.segments = {seg0, seg1};

  auto result = validator.Validate(plan, 999000);
  ASSERT_TRUE(result.valid);

  ValidatedBlockPlan validated{plan, result.boundaries, 999000};

  // Join 45 seconds into block (15 seconds into segment 1)
  int64_t t_join = 1045000;
  auto join_result = JoinComputer::ComputeJoinParameters(validated, t_join);

  // ASSERTIONS:
  // - CT at first frame = 45000ms
  // - Playing from segment[1]
  // - effective offset = 15000 (segment 1 asset offset 0 + 15s elapsed)
  // - epoch_wall_ms = 1000000 (block start, not join time)
  ASSERT_TRUE(join_result.valid);
  EXPECT_EQ(join_result.params.classification, JoinClassification::kMidBlock);
  EXPECT_EQ(join_result.params.wait_ms, 0);
  EXPECT_EQ(join_result.params.ct_start_ms, 45000);
  EXPECT_EQ(join_result.params.start_segment_index, 1);
  EXPECT_EQ(join_result.params.effective_asset_offset_ms, 15000);
}

// =============================================================================
// TEST-JOIN-003: Stale block rejected
// CONTRACT-JOIN-001 C3
// =============================================================================
TEST(JoinParameters, StaleBlockRejected) {
  FakeAssetStore store;
  store.SetAssetDuration("valid.mp4", 120000);

  BlockPlanValidator validator(store.AsDurationFn());
  BlockPlan plan = MakeValidSingleSegmentPlan("B001", 1000000, 1060000, "valid.mp4", 0);

  // Validate when fresh
  auto result = validator.Validate(plan, 999000);
  ASSERT_TRUE(result.valid);

  ValidatedBlockPlan validated{plan, result.boundaries, 999000};

  // But try to join after block ended
  int64_t t_join = 1060001;
  auto join_result = JoinComputer::ComputeJoinParameters(validated, t_join);

  // ASSERTIONS:
  // - No execution attempted
  // - Error is STALE_BLOCK_FROM_CORE
  EXPECT_FALSE(join_result.valid);
  EXPECT_EQ(join_result.error, BlockPlanError::kStaleBlockFromCore);
}

// =============================================================================
// TEST-LOOK-001: Fence transition with pending block
// CONTRACT-BLOCK-003, CONTRACT-LOOK-001
// =============================================================================
TEST(Lookahead, FenceTransitionWithPendingBlock) {
  FakeAssetStore store;
  store.SetAssetDuration("valid.mp4", 120000);

  BlockPlanValidator validator(store.AsDurationFn());
  BlockPlanQueue queue;

  // Block A in slot 0
  auto planA = MakeValidSingleSegmentPlan("A", 1000000, 1060000, "valid.mp4", 0);
  auto resultA = validator.Validate(planA, 999000);
  ASSERT_TRUE(resultA.valid);
  ValidatedBlockPlan vpA{planA, resultA.boundaries, 999000};
  queue.Enqueue(std::move(vpA));

  // Block B in slot 1
  auto planB = MakeValidSingleSegmentPlan("B", 1060000, 1120000, "valid.mp4", 0);
  auto resultB = validator.Validate(planB, 999000);
  ASSERT_TRUE(resultB.valid);
  ValidatedBlockPlan vpB{planB, resultB.boundaries, 999000};
  queue.Enqueue(std::move(vpB));

  ASSERT_EQ(queue.Size(), 2u);
  EXPECT_EQ(queue.ExecutingBlock()->plan.block_id, "A");
  EXPECT_EQ(queue.PendingBlock()->plan.block_id, "B");

  // Transition at fence
  auto trans_result = queue.TransitionAtFence();

  // ASSERTIONS:
  // - Block A completes
  // - Block B promoted to slot 0
  // - Slot 1 now empty
  EXPECT_EQ(trans_result, BlockPlanQueue::TransitionResult::kTransitioned);
  EXPECT_EQ(queue.Size(), 1u);
  EXPECT_EQ(queue.ExecutingBlock()->plan.block_id, "B");
  EXPECT_EQ(queue.PendingBlock(), nullptr);
}

// =============================================================================
// TEST-LOOK-002: Fence with empty pending slot terminates
// CONTRACT-LOOK-003
// =============================================================================
TEST(Lookahead, FenceWithEmptyPendingTerminates) {
  FakeAssetStore store;
  store.SetAssetDuration("valid.mp4", 120000);

  BlockPlanValidator validator(store.AsDurationFn());
  BlockPlanQueue queue;

  // Only Block A in slot 0, slot 1 empty
  auto planA = MakeValidSingleSegmentPlan("A", 1000000, 1060000, "valid.mp4", 0);
  auto resultA = validator.Validate(planA, 999000);
  ASSERT_TRUE(resultA.valid);
  ValidatedBlockPlan vpA{planA, resultA.boundaries, 999000};
  queue.Enqueue(std::move(vpA));

  EXPECT_EQ(queue.Size(), 1u);
  EXPECT_EQ(queue.PendingBlock(), nullptr);

  // Transition at fence with no pending
  auto trans_result = queue.TransitionAtFence();

  // ASSERTIONS:
  // - Session terminates
  // - Error: LOOKAHEAD_EXHAUSTED
  // - No output after fence (queue empty)
  EXPECT_EQ(trans_result, BlockPlanQueue::TransitionResult::kLookaheadExhausted);
  EXPECT_EQ(queue.Size(), 0u);
}

// =============================================================================
// TEST-LOOK-003: Block contiguity enforced
// CONTRACT-LOOK-002
// =============================================================================
TEST(Lookahead, BlockContiguityEnforced) {
  FakeAssetStore store;
  store.SetAssetDuration("valid.mp4", 120000);

  BlockPlanValidator validator(store.AsDurationFn());
  BlockPlanQueue queue;

  // Block A: ends at 1060000
  auto planA = MakeValidSingleSegmentPlan("A", 1000000, 1060000, "valid.mp4", 0);
  auto resultA = validator.Validate(planA, 999000);
  ASSERT_TRUE(resultA.valid);
  ValidatedBlockPlan vpA{planA, resultA.boundaries, 999000};
  queue.Enqueue(std::move(vpA));

  // Block B: starts at 1060001 (1ms gap!)
  auto planB = MakeValidSingleSegmentPlan("B", 1060001, 1120001, "valid.mp4", 0);
  auto resultB = validator.Validate(planB, 999000);
  ASSERT_TRUE(resultB.valid);
  ValidatedBlockPlan vpB{planB, resultB.boundaries, 999000};
  auto enq_result = queue.Enqueue(std::move(vpB));

  // ASSERTIONS:
  // - Gap detected
  // - Block B not queued
  EXPECT_FALSE(enq_result.success);
  EXPECT_EQ(enq_result.error, BlockPlanError::kBlockNotContiguous);
  EXPECT_EQ(queue.Size(), 1u);
}

// =============================================================================
// TEST-LOOK-004: Late block after fence rejected
// CONTRACT-LOOK-003
// =============================================================================
TEST(Lookahead, LateBlockAfterFenceRejected) {
  FakeAssetStore store;
  store.SetAssetDuration("valid.mp4", 120000);

  BlockPlanValidator validator(store.AsDurationFn());
  BlockPlanQueue queue;

  // Block A, no pending
  auto planA = MakeValidSingleSegmentPlan("A", 1000000, 1060000, "valid.mp4", 0);
  auto resultA = validator.Validate(planA, 999000);
  ASSERT_TRUE(resultA.valid);
  ValidatedBlockPlan vpA{planA, resultA.boundaries, 999000};
  queue.Enqueue(std::move(vpA));

  // Fence reached, LOOKAHEAD_EXHAUSTED
  auto trans_result = queue.TransitionAtFence();
  EXPECT_EQ(trans_result, BlockPlanQueue::TransitionResult::kLookaheadExhausted);

  // Mark terminated
  queue.MarkTerminated();
  EXPECT_TRUE(queue.IsTerminated());

  // Late block B arrives
  auto planB = MakeValidSingleSegmentPlan("B", 1060000, 1120000, "valid.mp4", 0);
  auto resultB = validator.Validate(planB, 1060500);
  ASSERT_TRUE(resultB.valid);
  ValidatedBlockPlan vpB{planB, resultB.boundaries, 1060500};
  auto enq_result = queue.Enqueue(std::move(vpB));

  // ASSERTIONS:
  // - No resurrection of terminated session
  // - Block not queued
  EXPECT_FALSE(enq_result.success);
  EXPECT_EQ(enq_result.error, BlockPlanError::kSessionTerminated);
}

// =============================================================================
// TEST-DET-001: Same inputs produce identical CT sequence
// Determinism test (boundaries computed identically)
// =============================================================================
TEST(Determinism, SameInputsProduceIdenticalBoundaries) {
  FakeAssetStore store;
  store.SetAssetDuration("a.mp4", 100000);
  store.SetAssetDuration("b.mp4", 100000);
  store.SetAssetDuration("c.mp4", 100000);

  BlockPlanValidator validator(store.AsDurationFn());

  BlockPlan plan;
  plan.block_id = "B001";
  plan.channel_id = 1;
  plan.start_utc_ms = 0;
  plan.end_utc_ms = 60000;
  plan.segments = {
      {0, "a.mp4", 0, 10000},
      {1, "b.mp4", 0, 20000},
      {2, "c.mp4", 0, 30000},
  };

  // Run 1
  auto result1 = validator.Validate(plan, 0);
  ASSERT_TRUE(result1.valid);

  // Run 2
  auto result2 = validator.Validate(plan, 0);
  ASSERT_TRUE(result2.valid);

  // ASSERTIONS:
  // - CT[i] from run 1 == CT[i] from run 2 for all samples
  // - Transition points identical
  ASSERT_EQ(result1.boundaries.size(), result2.boundaries.size());
  for (size_t i = 0; i < result1.boundaries.size(); ++i) {
    EXPECT_EQ(result1.boundaries[i].segment_index,
              result2.boundaries[i].segment_index);
    EXPECT_EQ(result1.boundaries[i].start_ct_ms,
              result2.boundaries[i].start_ct_ms);
    EXPECT_EQ(result1.boundaries[i].end_ct_ms,
              result2.boundaries[i].end_ct_ms);
  }
}

// =============================================================================
// Additional validation edge cases
// =============================================================================

TEST(BlockPlanAcceptance, EmptySegmentsRejected) {
  FakeAssetStore store;
  BlockPlanValidator validator(store.AsDurationFn());

  BlockPlan plan;
  plan.block_id = "B001";
  plan.channel_id = 1;
  plan.start_utc_ms = 1000000;
  plan.end_utc_ms = 1060000;
  // Empty segments array

  auto result = validator.Validate(plan, 999000);

  EXPECT_FALSE(result.valid);
  EXPECT_EQ(result.error, BlockPlanError::kInvalidSegmentIndex);
}

TEST(BlockPlanAcceptance, InvalidBlockTimingRejected) {
  FakeAssetStore store;
  store.SetAssetDuration("valid.mp4", 120000);

  BlockPlanValidator validator(store.AsDurationFn());

  // end <= start
  BlockPlan plan = MakeValidSingleSegmentPlan("B001", 1060000, 1000000, "valid.mp4", 0);

  auto result = validator.Validate(plan, 999000);

  EXPECT_FALSE(result.valid);
  EXPECT_EQ(result.error, BlockPlanError::kInvalidBlockTiming);
}

TEST(BlockPlanAcceptance, InvalidOffsetRejected) {
  FakeAssetStore store;
  store.SetAssetDuration("short.mp4", 30000);  // Only 30 seconds

  BlockPlanValidator validator(store.AsDurationFn());

  // Offset 50000 exceeds asset duration 30000
  BlockPlan plan = MakeValidSingleSegmentPlan("B001", 1000000, 1060000, "short.mp4", 50000);

  auto result = validator.Validate(plan, 999000);

  EXPECT_FALSE(result.valid);
  EXPECT_EQ(result.error, BlockPlanError::kInvalidOffset);
}

TEST(BlockPlanAcceptance, DuplicateBlockIdRejected) {
  FakeAssetStore store;
  store.SetAssetDuration("valid.mp4", 120000);

  BlockPlanValidator validator(store.AsDurationFn());
  BlockPlanQueue queue;

  auto plan1 = MakeValidSingleSegmentPlan("SAME_ID", 1000000, 1060000, "valid.mp4", 0);
  auto result1 = validator.Validate(plan1, 999000);
  ASSERT_TRUE(result1.valid);
  ValidatedBlockPlan vp1{plan1, result1.boundaries, 999000};
  queue.Enqueue(std::move(vp1));

  // Same block_id
  auto plan2 = MakeValidSingleSegmentPlan("SAME_ID", 1060000, 1120000, "valid.mp4", 0);
  auto result2 = validator.Validate(plan2, 999000);
  ASSERT_TRUE(result2.valid);
  ValidatedBlockPlan vp2{plan2, result2.boundaries, 999000};
  auto enq_result = queue.Enqueue(std::move(vp2));

  EXPECT_FALSE(enq_result.success);
  EXPECT_EQ(enq_result.error, BlockPlanError::kDuplicateBlock);
}

TEST(BlockPlanAcceptance, NonPositiveSegmentDurationRejected) {
  FakeAssetStore store;
  store.SetAssetDuration("valid.mp4", 120000);

  BlockPlanValidator validator(store.AsDurationFn());

  BlockPlan plan;
  plan.block_id = "B001";
  plan.channel_id = 1;
  plan.start_utc_ms = 1000000;
  plan.end_utc_ms = 1060000;

  Segment seg;
  seg.segment_index = 0;
  seg.asset_uri = "valid.mp4";
  seg.asset_start_offset_ms = 0;
  seg.segment_duration_ms = 0;  // Invalid!
  plan.segments.push_back(seg);

  auto result = validator.Validate(plan, 999000);

  EXPECT_FALSE(result.valid);
  EXPECT_EQ(result.error, BlockPlanError::kSegmentDurationMismatch);
}

}  // namespace
}  // namespace retrovue::blockplan
