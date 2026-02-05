// Repository: Retrovue-playout
// Component: Feeder Harness Implementation
// Contract Reference: docs/architecture/proposals/BlockLevelPlayoutAutonomy.md
// Copyright (c) 2025 RetroVue

#include "retrovue/blockplan/FeederHarness.hpp"

#include <sstream>

#include "retrovue/blockplan/BlockPlanExecutor.hpp"
#include "ExecutorTestInfrastructure.hpp"

namespace retrovue::blockplan {

// =============================================================================
// FeederHarness Implementation
// =============================================================================

FeederHarness::FeederHarness(DiagnosticCallback diagnostic)
    : diagnostic_(std::move(diagnostic)) {}

void FeederHarness::Diag(const std::string& msg) {
  if (diagnostic_) {
    diagnostic_(msg);
  }
}

void FeederHarness::AddBlockToSupply(const BlockPlan& plan) {
  supply_.push(plan);
}

bool FeederHarness::FeedingStopped() const {
  // Feeding stops when supply is exhausted
  if (supply_.empty()) {
    return true;
  }
  // Or when drop limit is reached
  if (drop_after_ > 0 && feed_count_ >= drop_after_) {
    return true;
  }
  return false;
}

std::optional<ValidatedBlockPlan> FeederHarness::ValidateBlock(
    const BlockPlan& plan,
    testing::FakeAssetSource* assets,
    int64_t validation_time_ms) {

  // Create validator with asset duration function
  BlockPlanValidator validator(assets->AsDurationFn());

  // Validate the plan
  auto validation = validator.Validate(plan, validation_time_ms);
  if (!validation.valid) {
    Diag("[FEEDER] Validation failed for " + plan.block_id + ": " + validation.detail);
    return std::nullopt;
  }

  // Create validated plan
  return ValidatedBlockPlan{plan, validation.boundaries, validation_time_ms};
}

bool FeederHarness::SeedQueue(BlockPlanQueue& queue,
                              testing::FakeAssetSource* assets,
                              int64_t current_time_ms) {
  // CONTRACT-FEED-001: Two-block window must be maintained
  // Seeding requires exactly 2 blocks in supply

  if (supply_.size() < 2) {
    Diag("[FEEDER] Seed failed: need at least 2 blocks, have " +
         std::to_string(supply_.size()));
    return false;
  }

  // Seed block A (executing)
  BlockPlan blockA = supply_.front();
  supply_.pop();

  auto validatedA = ValidateBlock(blockA, assets, current_time_ms);
  if (!validatedA) {
    Diag("[FEEDER] Seed failed: Block A validation failed");
    return false;
  }

  auto resultA = queue.Enqueue(std::move(*validatedA));
  if (!resultA.success) {
    Diag(std::string("[FEEDER] Seed failed: Block A enqueue failed: ") +
         BlockPlanErrorToString(resultA.error));
    return false;
  }

  Diag("[QUEUE] Seeded slot 0: " + blockA.block_id);

  // Seed block B (pending)
  BlockPlan blockB = supply_.front();
  supply_.pop();

  auto validatedB = ValidateBlock(blockB, assets, current_time_ms);
  if (!validatedB) {
    Diag("[FEEDER] Seed failed: Block B validation failed");
    return false;
  }

  auto resultB = queue.Enqueue(std::move(*validatedB));
  if (!resultB.success) {
    Diag(std::string("[FEEDER] Seed failed: Block B enqueue failed: ") +
         BlockPlanErrorToString(resultB.error));
    return false;
  }

  Diag("[QUEUE] Seeded slot 1: " + blockB.block_id);

  return true;
}

bool FeederHarness::MaybeFeed(BlockPlanQueue& queue,
                              testing::FakeAssetSource* assets,
                              int64_t current_time_ms) {
  // Check if feeding is stopped
  if (FeedingStopped()) {
    if (supply_.empty()) {
      Diag("[FEEDER] Supply exhausted - no more blocks to feed");
    } else {
      Diag("[FEEDER] Feed limit reached (" + std::to_string(drop_after_) +
           ") - stopping feed");
    }
    return false;
  }

  // Check if queue can accept a block
  if (queue.Full()) {
    Diag("[FEEDER] Queue full - cannot feed yet");
    return false;
  }

  // Get next block from supply
  BlockPlan nextBlock = supply_.front();
  supply_.pop();

  // Validate the block
  auto validated = ValidateBlock(nextBlock, assets, current_time_ms);
  if (!validated) {
    Diag("[FEEDER] Feed failed: validation error for " + nextBlock.block_id);
    return false;
  }

  // Attempt to enqueue
  auto result = queue.Enqueue(std::move(*validated));
  if (!result.success) {
    // CONTRACT-FEED-003: Late or non-contiguous block is rejected
    Diag(std::string("[FEEDER] Feed rejected: ") + BlockPlanErrorToString(result.error) +
         " for " + nextBlock.block_id);
    return false;
  }

  ++feed_count_;
  Diag("[FEED] Enqueued " + nextBlock.block_id + " at t=" +
       std::to_string(current_time_ms) + " (feed #" +
       std::to_string(feed_count_) + ")");

  return true;
}

// =============================================================================
// MultiBlockRunner Implementation
// =============================================================================

MultiBlockRunner::MultiBlockRunner(FeederHarness* feeder,
                                   BlockPlanQueue* queue,
                                   testing::FakeClock* clock,
                                   testing::FakeAssetSource* assets,
                                   DiagnosticCallback diagnostic)
    : feeder_(feeder),
      queue_(queue),
      clock_(clock),
      assets_(assets),
      diagnostic_(std::move(diagnostic)) {}

void MultiBlockRunner::Diag(const std::string& msg) {
  if (diagnostic_) {
    diagnostic_(msg);
  }
}

MultiBlockRunner::RunSummary MultiBlockRunner::Run(testing::RecordingSink* sink) {
  RunSummary summary;
  summary.blocks_executed = 0;
  summary.blocks_fed = 0;
  summary.final_ct_ms = 0;

  // Seed the queue with initial two blocks
  if (!feeder_->SeedQueue(*queue_, assets_, clock_->NowMs())) {
    Diag("[ERROR] Seed failed - cannot start execution");
    summary.result = RunResult::kSeedFailed;
    summary.error_detail = "Failed to seed queue with initial blocks";
    return summary;
  }

  Diag("[QUEUE] Queue seeded successfully");

  // Create executor
  BlockPlanExecutor executor;

  // Main execution loop
  while (true) {
    // Get current executing block
    const ValidatedBlockPlan* executing = queue_->ExecutingBlock();
    if (!executing) {
      // No executing block - we're done
      Diag("[EXEC] No executing block - stopping");
      break;
    }

    const auto& plan = executing->plan;
    Diag("[EXEC] Executing " + plan.block_id +
         " (start=" + std::to_string(plan.start_utc_ms) +
         ", end=" + std::to_string(plan.end_utc_ms) + ")");

    // Show pending block status
    const ValidatedBlockPlan* pending = queue_->PendingBlock();
    if (pending) {
      Diag("[QUEUE] Pending: " + pending->plan.block_id);
    } else {
      Diag("[QUEUE] Pending: NONE");
    }

    // Compute join parameters for this block
    int64_t join_time = clock_->NowMs();
    auto join_result = JoinComputer::ComputeJoinParameters(*executing, join_time);
    if (!join_result.valid) {
      Diag(std::string("[ERROR] Join computation failed: ") +
           BlockPlanErrorToString(join_result.error));
      summary.result = RunResult::kAssetError;
      summary.error_detail = "Join computation failed";
      return summary;
    }

    // Execute the block
    auto exec_result = executor.Execute(*executing, join_result.params,
                                         clock_, assets_, sink);

    summary.final_ct_ms = exec_result.final_ct_ms;
    ++summary.blocks_executed;

    // Handle execution result
    if (exec_result.exit_code == testing::ExecutorExitCode::kAssetError) {
      Diag("[ERROR] Asset error during execution");
      summary.result = RunResult::kAssetError;
      summary.error_detail = exec_result.error_detail;
      return summary;
    }

    if (exec_result.exit_code == testing::ExecutorExitCode::kTerminated) {
      Diag("[EXEC] Terminated by request");
      summary.result = RunResult::kTerminated;
      return summary;
    }

    // Block completed at fence
    // Store block end time BEFORE transition (transition invalidates plan reference)
    int64_t completed_block_end_ms = plan.end_utc_ms;
    std::string completed_block_id = plan.block_id;

    Diag("[FENCE] " + completed_block_id + " complete at CT=" +
         std::to_string(exec_result.final_ct_ms));

    // Transition at fence FIRST
    auto transition = queue_->TransitionAtFence();

    if (transition == BlockPlanQueue::TransitionResult::kLookaheadExhausted) {
      // CONTRACT-FEED-002: Missing feed causes termination at fence
      // CONTRACT-FEED-004: No waiting or filler when feed stops
      Diag("[ERROR] LOOKAHEAD_EXHAUSTED -> terminating");
      summary.result = RunResult::kLookaheadExhausted;
      summary.error_detail = "No pending block at fence";
      return summary;
    }

    if (transition == BlockPlanQueue::TransitionResult::kNoExecutingBlock) {
      Diag("[ERROR] No executing block during transition");
      summary.result = RunResult::kAssetError;
      summary.error_detail = "Invalid queue state";
      return summary;
    }

    // Successfully transitioned to next block
    Diag("[QUEUE] Promoted pending to executing");

    // NOW try to feed the next block (after transition freed a slot)
    // This is "just-in-time" feeding - Core sends next block when there's room
    size_t feeds_before = feeder_->FeedCount();
    feeder_->MaybeFeed(*queue_, assets_, clock_->NowMs());
    if (feeder_->FeedCount() > feeds_before) {
      ++summary.blocks_fed;
    }

    // Advance wall clock to completed block's end time for next iteration
    // (The executor already set this, but be explicit for clarity)
    clock_->SetMs(completed_block_end_ms);
  }

  // All blocks executed successfully
  summary.result = RunResult::kCompleted;
  return summary;
}

}  // namespace retrovue::blockplan
