// Repository: Retrovue-playout
// Component: Feeder Contract Tests
// Purpose: Verify feeder harness behavior matches broadcast automation
// Contract Reference: docs/architecture/proposals/BlockLevelPlayoutAutonomy.md
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <string>
#include <vector>

#include "retrovue/blockplan/BlockPlanExecutor.hpp"
#include "retrovue/blockplan/BlockPlanQueue.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/BlockPlanValidator.hpp"
#include "retrovue/blockplan/FeederHarness.hpp"
#include "ExecutorTestInfrastructure.hpp"

namespace retrovue::blockplan::testing {
namespace {

// =============================================================================
// Test Fixture
// =============================================================================

class FeederContractTests : public ::testing::Test {
 protected:
  void SetUp() override {
    clock_ = std::make_unique<FakeClock>();
    assets_ = std::make_unique<FakeAssetSource>();
    sink_ = std::make_unique<RecordingSink>();
    queue_ = std::make_unique<BlockPlanQueue>();

    // Capture diagnostics for verification
    diagnostics_.clear();
    feeder_ = std::make_unique<FeederHarness>(
        [this](const std::string& msg) { diagnostics_.push_back(msg); });
  }

  // Create a simple block plan
  BlockPlan CreateBlock(const std::string& id, int64_t start_ms, int64_t duration_ms) {
    BlockPlan plan;
    plan.block_id = id;
    plan.channel_id = 1;
    plan.start_utc_ms = start_ms;
    plan.end_utc_ms = start_ms + duration_ms;

    Segment seg;
    seg.segment_index = 0;
    seg.asset_uri = id + "_asset.mp4";
    seg.asset_start_offset_ms = 0;
    seg.segment_duration_ms = duration_ms;
    plan.segments.push_back(seg);

    // Register fake asset
    assets_->RegisterSimpleAsset(seg.asset_uri, duration_ms, 33);

    return plan;
  }

  // Create a contiguous sequence of blocks
  std::vector<BlockPlan> CreateContiguousBlocks(size_t count, int64_t block_duration_ms) {
    std::vector<BlockPlan> blocks;
    int64_t current_start = 0;
    for (size_t i = 0; i < count; ++i) {
      std::string id = "BLOCK-" + std::to_string(i);
      blocks.push_back(CreateBlock(id, current_start, block_duration_ms));
      current_start += block_duration_ms;
    }
    return blocks;
  }

  // Check if diagnostic contains message
  bool HasDiagnostic(const std::string& substr) const {
    for (const auto& msg : diagnostics_) {
      if (msg.find(substr) != std::string::npos) {
        return true;
      }
    }
    return false;
  }

  std::unique_ptr<FakeClock> clock_;
  std::unique_ptr<FakeAssetSource> assets_;
  std::unique_ptr<RecordingSink> sink_;
  std::unique_ptr<BlockPlanQueue> queue_;
  std::unique_ptr<FeederHarness> feeder_;
  std::vector<std::string> diagnostics_;
};

// =============================================================================
// CONTRACT-FEED-001: Two-block window is always maintained when feeder is active
// =============================================================================

TEST_F(FeederContractTests, CONTRACT_FEED_001_SeedRequiresTwoBlocks) {
  // GIVEN: Feeder with only 1 block
  auto block = CreateBlock("ONLY-ONE", 0, 10000);
  feeder_->AddBlockToSupply(block);

  // WHEN: Attempting to seed queue
  clock_->SetMs(0);
  bool seeded = feeder_->SeedQueue(*queue_, assets_.get(), clock_->NowMs());

  // THEN: Seeding fails (need exactly 2 blocks)
  EXPECT_FALSE(seeded);
  EXPECT_TRUE(queue_->Empty());
  EXPECT_TRUE(HasDiagnostic("need at least 2 blocks"));
}

TEST_F(FeederContractTests, CONTRACT_FEED_001_SeedSucceedsWithTwoBlocks) {
  // GIVEN: Feeder with 2 contiguous blocks
  auto blocks = CreateContiguousBlocks(2, 10000);
  for (const auto& b : blocks) {
    feeder_->AddBlockToSupply(b);
  }

  // WHEN: Seeding queue
  clock_->SetMs(0);
  bool seeded = feeder_->SeedQueue(*queue_, assets_.get(), clock_->NowMs());

  // THEN: Queue has exactly 2 blocks
  EXPECT_TRUE(seeded);
  EXPECT_TRUE(queue_->Full());
  EXPECT_EQ(queue_->Size(), 2u);
  EXPECT_NE(queue_->ExecutingBlock(), nullptr);
  EXPECT_NE(queue_->PendingBlock(), nullptr);
  EXPECT_EQ(queue_->ExecutingBlock()->plan.block_id, "BLOCK-0");
  EXPECT_EQ(queue_->PendingBlock()->plan.block_id, "BLOCK-1");
}

TEST_F(FeederContractTests, CONTRACT_FEED_001_FeedMaintainsTwoBlockWindow) {
  // GIVEN: Feeder with 4 blocks, queue seeded with 2
  auto blocks = CreateContiguousBlocks(4, 10000);
  for (const auto& b : blocks) {
    feeder_->AddBlockToSupply(b);
  }

  clock_->SetMs(0);
  ASSERT_TRUE(feeder_->SeedQueue(*queue_, assets_.get(), clock_->NowMs()));

  // WHEN: Transition at fence and feed
  auto transition = queue_->TransitionAtFence();
  ASSERT_EQ(transition, BlockPlanQueue::TransitionResult::kTransitioned);

  // Queue now has 1 block (BLOCK-1 executing, no pending)
  EXPECT_EQ(queue_->Size(), 1u);

  // Feed next block
  clock_->SetMs(10000);
  bool fed = feeder_->MaybeFeed(*queue_, assets_.get(), clock_->NowMs());

  // THEN: Queue is back to 2 blocks
  EXPECT_TRUE(fed);
  EXPECT_EQ(queue_->Size(), 2u);
  EXPECT_EQ(queue_->ExecutingBlock()->plan.block_id, "BLOCK-1");
  EXPECT_EQ(queue_->PendingBlock()->plan.block_id, "BLOCK-2");
}

// =============================================================================
// CONTRACT-FEED-002: Missing feed causes termination at fence
// =============================================================================

TEST_F(FeederContractTests, CONTRACT_FEED_002_MissingFeedCausesTermination) {
  // GIVEN: Feeder with exactly 2 blocks (no extras to feed)
  auto blocks = CreateContiguousBlocks(2, 10000);
  for (const auto& b : blocks) {
    feeder_->AddBlockToSupply(b);
  }

  clock_->SetMs(0);
  ASSERT_TRUE(feeder_->SeedQueue(*queue_, assets_.get(), clock_->NowMs()));
  EXPECT_TRUE(feeder_->SupplyExhausted());

  // WHEN: Execute first block, transition, and try to feed
  auto transition = queue_->TransitionAtFence();
  ASSERT_EQ(transition, BlockPlanQueue::TransitionResult::kTransitioned);

  // Execute second block
  auto transition2 = queue_->TransitionAtFence();

  // THEN: Lookahead exhausted (no pending block)
  EXPECT_EQ(transition2, BlockPlanQueue::TransitionResult::kLookaheadExhausted);
}

TEST_F(FeederContractTests, CONTRACT_FEED_002_MultiBlockRunnerTerminatesOnExhaustion) {
  // GIVEN: Feeder with exactly 2 blocks
  auto blocks = CreateContiguousBlocks(2, 5000);
  for (const auto& b : blocks) {
    feeder_->AddBlockToSupply(b);
  }

  clock_->SetMs(0);

  // Create runner with diagnostic capture
  std::vector<std::string> runner_diags;
  MultiBlockRunner runner(feeder_.get(), queue_.get(), clock_.get(), assets_.get(),
      [&runner_diags](const std::string& msg) { runner_diags.push_back(msg); });

  // WHEN: Running all blocks
  auto summary = runner.Run(sink_.get());

  // THEN: Terminates with LOOKAHEAD_EXHAUSTED after 2 blocks
  EXPECT_EQ(summary.result, MultiBlockRunner::RunResult::kLookaheadExhausted);
  EXPECT_EQ(summary.blocks_executed, 2u);

  // Check diagnostic output
  bool found_exhausted = false;
  for (const auto& msg : runner_diags) {
    if (msg.find("LOOKAHEAD_EXHAUSTED") != std::string::npos) {
      found_exhausted = true;
      break;
    }
  }
  EXPECT_TRUE(found_exhausted) << "Expected LOOKAHEAD_EXHAUSTED diagnostic";
}

// =============================================================================
// CONTRACT-FEED-003: Late or non-contiguous block is rejected
// =============================================================================

TEST_F(FeederContractTests, CONTRACT_FEED_003_NonContiguousBlockRejected) {
  // GIVEN: Seeded queue with blocks 0-10000, 10000-20000
  auto blocks = CreateContiguousBlocks(2, 10000);
  for (const auto& b : blocks) {
    feeder_->AddBlockToSupply(b);
  }

  clock_->SetMs(0);
  ASSERT_TRUE(feeder_->SeedQueue(*queue_, assets_.get(), clock_->NowMs()));

  // Transition so queue has 1 slot
  queue_->TransitionAtFence();

  // Create a non-contiguous block (gap from 20000 to 25000)
  auto bad_block = CreateBlock("BAD-GAP", 25000, 10000);

  // WHEN: Attempt to enqueue directly
  auto validated = feeder_->ValidateBlock(bad_block, assets_.get(), clock_->NowMs());
  ASSERT_TRUE(validated.has_value());

  auto result = queue_->Enqueue(std::move(*validated));

  // THEN: Rejected with contiguity error
  EXPECT_FALSE(result.success);
  EXPECT_EQ(result.error, BlockPlanError::kBlockNotContiguous);
}

TEST_F(FeederContractTests, CONTRACT_FEED_003_OverlappingBlockRejected) {
  // GIVEN: Seeded queue with blocks 0-10000, 10000-20000
  auto blocks = CreateContiguousBlocks(2, 10000);
  for (const auto& b : blocks) {
    feeder_->AddBlockToSupply(b);
  }

  clock_->SetMs(0);
  ASSERT_TRUE(feeder_->SeedQueue(*queue_, assets_.get(), clock_->NowMs()));

  // Transition so queue has 1 slot
  queue_->TransitionAtFence();

  // Create an overlapping block (starts before previous end)
  auto bad_block = CreateBlock("BAD-OVERLAP", 15000, 10000);

  // WHEN: Attempt to enqueue
  auto validated = feeder_->ValidateBlock(bad_block, assets_.get(), clock_->NowMs());
  ASSERT_TRUE(validated.has_value());

  auto result = queue_->Enqueue(std::move(*validated));

  // THEN: Rejected with contiguity error
  EXPECT_FALSE(result.success);
  EXPECT_EQ(result.error, BlockPlanError::kBlockNotContiguous);
}

// =============================================================================
// CONTRACT-FEED-004: No waiting or filler when feed stops
// =============================================================================

TEST_F(FeederContractTests, CONTRACT_FEED_004_NoFillerOnExhaustion) {
  // GIVEN: Feeder with exactly 2 blocks (nothing to feed after seed)
  auto blocks = CreateContiguousBlocks(2, 5000);
  for (const auto& b : blocks) {
    feeder_->AddBlockToSupply(b);
  }

  clock_->SetMs(0);

  // WHEN: Running (MultiBlockRunner seeds internally)
  MultiBlockRunner runner(feeder_.get(), queue_.get(), clock_.get(), assets_.get());
  auto summary = runner.Run(sink_.get());

  // THEN: Supply exhausted after seed, no feeds possible
  EXPECT_EQ(feeder_->SupplySize(), 0u);
  EXPECT_TRUE(feeder_->FeedingStopped());
  EXPECT_EQ(summary.blocks_fed, 0u);  // No feeds after seed

  // Terminates at fence with LOOKAHEAD_EXHAUSTED
  // No filler frames, no waiting
  EXPECT_EQ(summary.result, MultiBlockRunner::RunResult::kLookaheadExhausted);
  EXPECT_EQ(summary.blocks_executed, 2u);

  // Verify real frames were emitted (no padding = no filler)
  EXPECT_GT(sink_->FrameCount(), 0u);
  EXPECT_EQ(sink_->PadFrameCount(), 0u);
}

TEST_F(FeederContractTests, CONTRACT_FEED_004_DropAfterLimitsFeeding) {
  // GIVEN: Feeder with 5 blocks, drop-after set to 1
  auto blocks = CreateContiguousBlocks(5, 5000);
  for (const auto& b : blocks) {
    feeder_->AddBlockToSupply(b);
  }

  feeder_->SetDropAfter(1);  // Allow only 1 feed after seed

  clock_->SetMs(0);

  // WHEN: Running (MultiBlockRunner seeds internally)
  MultiBlockRunner runner(feeder_.get(), queue_.get(), clock_.get(), assets_.get());
  auto summary = runner.Run(sink_.get());

  // THEN: Executes 3 blocks (2 seeded + 1 fed), then terminates
  EXPECT_EQ(summary.result, MultiBlockRunner::RunResult::kLookaheadExhausted);
  EXPECT_EQ(summary.blocks_executed, 3u);
  EXPECT_EQ(summary.blocks_fed, 1u);
}

// =============================================================================
// Additional Tests: Continuous Feeding
// =============================================================================

TEST_F(FeederContractTests, ContinuousFeedingExecutesAllBlocks) {
  // GIVEN: Feeder with 5 blocks
  auto blocks = CreateContiguousBlocks(5, 5000);
  for (const auto& b : blocks) {
    feeder_->AddBlockToSupply(b);
  }

  clock_->SetMs(0);

  // WHEN: Running with continuous feeding (no drop limit)
  MultiBlockRunner runner(feeder_.get(), queue_.get(), clock_.get(), assets_.get());
  auto summary = runner.Run(sink_.get());

  // THEN: All 5 blocks executed, terminates at end
  EXPECT_EQ(summary.result, MultiBlockRunner::RunResult::kLookaheadExhausted);
  EXPECT_EQ(summary.blocks_executed, 5u);
  EXPECT_EQ(summary.blocks_fed, 3u);  // 2 seeded + 3 fed = 5 total
}

TEST_F(FeederContractTests, DiagnosticOutputShowsAllEvents) {
  // GIVEN: Feeder with 3 blocks
  auto blocks = CreateContiguousBlocks(3, 3000);
  for (const auto& b : blocks) {
    feeder_->AddBlockToSupply(b);
  }

  clock_->SetMs(0);

  std::vector<std::string> runner_diags;
  MultiBlockRunner runner(feeder_.get(), queue_.get(), clock_.get(), assets_.get(),
      [&runner_diags](const std::string& msg) { runner_diags.push_back(msg); });

  // WHEN: Running
  auto summary = runner.Run(sink_.get());

  // THEN: Check runner diagnostics for execution events
  bool saw_seeded = false;
  bool saw_exec = false;
  bool saw_fence = false;
  bool saw_promoted = false;

  for (const auto& msg : runner_diags) {
    if (msg.find("[QUEUE] Queue seeded") != std::string::npos) saw_seeded = true;
    if (msg.find("[EXEC] Executing") != std::string::npos) saw_exec = true;
    if (msg.find("[FENCE]") != std::string::npos) saw_fence = true;
    if (msg.find("Promoted") != std::string::npos) saw_promoted = true;
  }

  EXPECT_TRUE(saw_seeded) << "Missing seeded diagnostic";
  EXPECT_TRUE(saw_exec) << "Missing exec diagnostic";
  EXPECT_TRUE(saw_fence) << "Missing fence diagnostic";
  EXPECT_TRUE(saw_promoted) << "Missing promoted diagnostic";

  // Check feeder diagnostics for feed events
  // (diagnostics_ is the fixture's capture of feeder events)
  bool saw_feed = false;
  for (const auto& msg : diagnostics_) {
    if (msg.find("[FEED] Enqueued") != std::string::npos) saw_feed = true;
  }
  EXPECT_TRUE(saw_feed) << "Missing feed diagnostic (feeder)";
}

TEST_F(FeederContractTests, DeterministicExecution_AllBlocksComplete) {
  // GIVEN: Feeder with blocks
  auto blocks = CreateContiguousBlocks(3, 5000);
  for (const auto& b : blocks) {
    feeder_->AddBlockToSupply(b);
  }

  clock_->SetMs(0);

  // WHEN: Running
  MultiBlockRunner runner(feeder_.get(), queue_.get(), clock_.get(), assets_.get());
  auto summary = runner.Run(sink_.get());

  // THEN: All blocks executed and terminated as expected
  EXPECT_EQ(summary.result, MultiBlockRunner::RunResult::kLookaheadExhausted);
  EXPECT_EQ(summary.blocks_executed, 3u);

  // Final wall clock should be at block 3's fence (15000ms)
  // Note: CT is block-local (resets to 0 per block), so we check final_ct_ms
  // which represents the last CT emitted in the final block
  EXPECT_GE(summary.final_ct_ms, 4000);  // Near end of last block (~5000ms duration)
  EXPECT_LT(summary.final_ct_ms, 5100);  // Within last block's range

  // Frames were emitted from all blocks
  EXPECT_GT(sink_->FrameCount(), 0u);
}

}  // namespace
}  // namespace retrovue::blockplan::testing
