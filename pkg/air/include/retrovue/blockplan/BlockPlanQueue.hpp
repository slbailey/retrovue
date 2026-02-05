// Repository: Retrovue-playout
// Component: BlockPlan Queue
// Purpose: Two-slot lookahead queue management
// Contract Reference: docs/architecture/proposals/BlockLevelPlayoutAutonomy.md
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_BLOCKPLAN_QUEUE_HPP_
#define RETROVUE_BLOCKPLAN_QUEUE_HPP_

#include <array>
#include <optional>

#include "retrovue/blockplan/BlockPlanTypes.hpp"

namespace retrovue::blockplan {

// =============================================================================
// Block Queue
// CONTRACT-LOOK-001: Queue Management
// =============================================================================

class BlockPlanQueue {
 public:
  // CONTRACT-LOOK-001: Maximum capacity is 2
  // FROZEN: Two-block queue max (Section 8.1)
  static constexpr size_t kMaxCapacity = 2;

  BlockPlanQueue() = default;

  // Disable copy (queue owns blocks)
  BlockPlanQueue(const BlockPlanQueue&) = delete;
  BlockPlanQueue& operator=(const BlockPlanQueue&) = delete;

  // ==========================================================================
  // Query Methods
  // ==========================================================================

  // Current queue depth
  size_t Size() const;

  // Is queue empty?
  bool Empty() const { return Size() == 0; }

  // Is queue full?
  // CONTRACT-LOOK-001 R3: Both slots occupied
  bool Full() const { return Size() >= kMaxCapacity; }

  // Get executing block (slot 0), or nullptr if empty
  const ValidatedBlockPlan* ExecutingBlock() const;

  // Get pending block (slot 1), or nullptr if not present
  const ValidatedBlockPlan* PendingBlock() const;

  // Check if block_id is already queued
  // CONTRACT-LOOK-001: No duplicates
  bool ContainsBlockId(const std::string& block_id) const;

  // ==========================================================================
  // Acceptance
  // CONTRACT-LOOK-001: Acceptance Rules
  // CONTRACT-LOOK-002: Block Contiguity
  // ==========================================================================

  struct EnqueueResult {
    bool success;
    BlockPlanError error;
    int32_t slot;  // 0 or 1 if success, -1 if failure

    static EnqueueResult Success(int32_t s) {
      return {true, BlockPlanError::kNone, s};
    }
    static EnqueueResult Failure(BlockPlanError e) {
      return {false, e, -1};
    }
  };

  // Attempt to enqueue a validated block
  // CONTRACT-LOOK-001 R1: Queue empty → slot 0
  // CONTRACT-LOOK-001 R2: Slot 0 occupied, slot 1 empty → slot 1
  // CONTRACT-LOOK-001 R3: Both occupied → reject QUEUE_FULL
  // CONTRACT-LOOK-002: start_utc_ms must equal previous block's end_utc_ms
  EnqueueResult Enqueue(ValidatedBlockPlan validated);

  // ==========================================================================
  // Fence Transition
  // CONTRACT-BLOCK-003: Block Fence Enforcement
  // CONTRACT-LOOK-003: Lookahead Exhaustion
  // ==========================================================================

  enum class TransitionResult {
    // Pending block promoted to executing
    kTransitioned,

    // No pending block - LOOKAHEAD_EXHAUSTED
    // FROZEN: Lookahead exhaustion = termination (Section 8.1.3)
    kLookaheadExhausted,

    // Queue was already empty (invalid state)
    kNoExecutingBlock,
  };

  // Promote pending block to executing position
  // Called when fence is reached
  // CONTRACT-BLOCK-003 G2: If pending exists, promote to slot 0
  // CONTRACT-BLOCK-003 G3: If no pending, return LOOKAHEAD_EXHAUSTED
  TransitionResult TransitionAtFence();

  // ==========================================================================
  // Termination
  // CONTRACT-SEG-005: Failure = clear all
  // ==========================================================================

  // Clear all queued blocks (on session termination)
  void Clear();

  // Mark session as terminated (reject all future blocks)
  void MarkTerminated();

  // Is session terminated?
  bool IsTerminated() const { return terminated_; }

 private:
  // FROZEN: Two-slot structure (Section 8.1)
  // Slot 0: Executing, Slot 1: Pending
  std::array<std::optional<ValidatedBlockPlan>, kMaxCapacity> slots_;

  // Session terminated flag
  bool terminated_ = false;

  // Get end_utc_ms of the last block in queue (for contiguity check)
  std::optional<int64_t> LastBlockEndUtcMs() const;
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_QUEUE_HPP_
