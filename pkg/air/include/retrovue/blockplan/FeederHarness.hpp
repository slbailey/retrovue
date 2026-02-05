// Repository: Retrovue-playout
// Component: Feeder Harness (Fake Core)
// Purpose: Simulates Core feeding blocks to AIR just-in-time
// Contract Reference: docs/architecture/proposals/BlockLevelPlayoutAutonomy.md
// Copyright (c) 2025 RetroVue
//
// This component models how professional broadcast automation feeds blocks
// to a playout engine. It is NOT part of AIR - it acts as a fake Core.
//
// ARCHITECTURAL INTENT:
// - AIR executes blocks; it does not decide schedules
// - Feeder (acting like Core) supplies blocks ahead of time
// - AIR maintains exactly two blocks of lookahead
// - If lookahead is exhausted, AIR terminates immediately at the fence
// - No waiting, no filler, no retries, no mutation

#ifndef RETROVUE_BLOCKPLAN_FEEDER_HARNESS_HPP_
#define RETROVUE_BLOCKPLAN_FEEDER_HARNESS_HPP_

#include <functional>
#include <optional>
#include <queue>
#include <string>
#include <vector>

#include "retrovue/blockplan/BlockPlanQueue.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/BlockPlanValidator.hpp"

namespace retrovue::blockplan {

// Forward declarations for test infrastructure
namespace testing {
class FakeClock;
class FakeAssetSource;
class RecordingSink;
}  // namespace testing

// =============================================================================
// Feeder Harness
// Simulates Core feeding blocks to AIR
// =============================================================================

class FeederHarness {
 public:
  // Diagnostic callback for observing feeder events
  using DiagnosticCallback = std::function<void(const std::string&)>;

  explicit FeederHarness(DiagnosticCallback diagnostic = nullptr);

  // ==========================================================================
  // Block Supply (Core-side operations)
  // ==========================================================================

  // Add a block to the feeder's supply
  // These blocks will be fed to AIR just-in-time
  void AddBlockToSupply(const BlockPlan& plan);

  // Get count of blocks remaining in supply
  size_t SupplySize() const { return supply_.size(); }

  // Check if supply is exhausted
  bool SupplyExhausted() const { return supply_.empty(); }

  // ==========================================================================
  // Feeding Control
  // ==========================================================================

  // Set maximum number of feed events (0 = unlimited)
  // After this many feeds, the feeder will stop supplying blocks
  void SetDropAfter(size_t max_feeds) { drop_after_ = max_feeds; }

  // Get number of feed events that have occurred
  size_t FeedCount() const { return feed_count_; }

  // Is feeding stopped (either supply exhausted or drop limit reached)?
  bool FeedingStopped() const;

  // ==========================================================================
  // Queue Operations (AIR-side interface)
  // ==========================================================================

  // Seed the queue with initial blocks (must be exactly 2)
  // CONTRACT-FEED-001: Two-block window must be maintained
  // Returns false if seeding fails (not enough blocks, validation error, etc.)
  bool SeedQueue(BlockPlanQueue& queue,
                 testing::FakeAssetSource* assets,
                 int64_t current_time_ms);

  // Attempt to feed the next block from supply
  // Called just before a block fence is reached
  // Returns true if a block was successfully enqueued
  // CONTRACT-FEED-001: Maintains two-block window when active
  // CONTRACT-FEED-002: Returns false when supply exhausted
  bool MaybeFeed(BlockPlanQueue& queue,
                 testing::FakeAssetSource* assets,
                 int64_t current_time_ms);

  // ==========================================================================
  // Validation
  // ==========================================================================

  // Validate a block plan before feeding
  // Uses the asset source to check segment durations
  std::optional<ValidatedBlockPlan> ValidateBlock(
      const BlockPlan& plan,
      testing::FakeAssetSource* assets,
      int64_t validation_time_ms);

 private:
  // Emit diagnostic message
  void Diag(const std::string& msg);

  // Blocks waiting to be fed
  std::queue<BlockPlan> supply_;

  // Feed event counter
  size_t feed_count_ = 0;

  // Maximum feed events (0 = unlimited)
  size_t drop_after_ = 0;

  // Diagnostic callback
  DiagnosticCallback diagnostic_;
};

// =============================================================================
// Multi-Block Runner
// Coordinates execution across multiple blocks with feeder
// =============================================================================

class MultiBlockRunner {
 public:
  // Diagnostic callback
  using DiagnosticCallback = std::function<void(const std::string&)>;

  MultiBlockRunner(FeederHarness* feeder,
                   BlockPlanQueue* queue,
                   testing::FakeClock* clock,
                   testing::FakeAssetSource* assets,
                   DiagnosticCallback diagnostic = nullptr);

  // ==========================================================================
  // Execution
  // ==========================================================================

  // Run result
  enum class RunResult {
    // All blocks executed successfully
    kCompleted,

    // Lookahead exhausted at fence (expected when feeder stops)
    kLookaheadExhausted,

    // Asset error during execution
    kAssetError,

    // External termination requested
    kTerminated,

    // Seeding failed (not enough initial blocks)
    kSeedFailed,
  };

  struct RunSummary {
    RunResult result;
    size_t blocks_executed;
    size_t blocks_fed;
    int64_t final_ct_ms;
    std::string error_detail;
  };

  // Run all blocks until completion or lookahead exhaustion
  // CONTRACT-FEED-002: Missing feed causes termination at fence
  // CONTRACT-FEED-004: No waiting or filler when feed stops
  RunSummary Run(testing::RecordingSink* sink);

 private:
  // Emit diagnostic message
  void Diag(const std::string& msg);

  FeederHarness* feeder_;
  BlockPlanQueue* queue_;
  testing::FakeClock* clock_;
  testing::FakeAssetSource* assets_;
  DiagnosticCallback diagnostic_;
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_FEEDER_HARNESS_HPP_
