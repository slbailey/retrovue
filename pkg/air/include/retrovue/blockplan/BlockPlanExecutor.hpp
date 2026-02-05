// Repository: Retrovue-playout
// Component: BlockPlan Executor
// Purpose: Minimal executor loop for BlockPlan execution
// Contract Reference: docs/architecture/proposals/BlockLevelPlayoutAutonomy.md Section 7
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_BLOCKPLAN_EXECUTOR_HPP_
#define RETROVUE_BLOCKPLAN_EXECUTOR_HPP_

#include <atomic>
#include <cstdint>

#include "retrovue/blockplan/BlockPlanTypes.hpp"

namespace retrovue::blockplan {

// Forward declarations for test infrastructure
namespace testing {
class FakeClock;
class FakeAssetSource;
class RecordingSink;
struct ExecutorResult;
enum class ExecutorExitCode;
}  // namespace testing

// =============================================================================
// BlockPlan Executor
// Minimal implementation that satisfies Section 7 contracts
// =============================================================================

class BlockPlanExecutor {
 public:
  BlockPlanExecutor();
  ~BlockPlanExecutor();

  // Disable copy
  BlockPlanExecutor(const BlockPlanExecutor&) = delete;
  BlockPlanExecutor& operator=(const BlockPlanExecutor&) = delete;

  // Execute a validated block plan
  // FROZEN: No Core communication during execution (Section 8.1.4)
  // Returns when: fence reached, failure occurs, or termination requested
  testing::ExecutorResult Execute(
      const ValidatedBlockPlan& plan,
      const JoinParameters& join_params,
      testing::FakeClock* clock,
      testing::FakeAssetSource* assets,
      testing::RecordingSink* sink);

  // Request graceful termination
  void RequestTermination();

 private:
  std::atomic<bool> termination_requested_{false};

  // Find segment index for given CT
  // CONTRACT-SEG-001: Segment contains CT if start_ct <= ct < end_ct
  int32_t FindSegmentForCt(
      const std::vector<SegmentBoundary>& boundaries,
      int64_t ct_ms) const;

  // Get segment by index
  const Segment* GetSegmentByIndex(
      const BlockPlan& plan,
      int32_t segment_index) const;
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_EXECUTOR_HPP_
