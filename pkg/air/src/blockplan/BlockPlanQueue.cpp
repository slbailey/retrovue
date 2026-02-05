// Repository: Retrovue-playout
// Component: BlockPlan Queue Implementation
// Contract Reference: docs/architecture/proposals/BlockLevelPlayoutAutonomy.md
// Copyright (c) 2025 RetroVue

#include "retrovue/blockplan/BlockPlanQueue.hpp"

namespace retrovue::blockplan {

// =============================================================================
// BlockPlanQueue Implementation
// CONTRACT-LOOK-001: Queue Management
// =============================================================================

size_t BlockPlanQueue::Size() const {
  size_t count = 0;
  for (const auto& slot : slots_) {
    if (slot.has_value()) {
      ++count;
    }
  }
  return count;
}

const ValidatedBlockPlan* BlockPlanQueue::ExecutingBlock() const {
  // Slot 0 is executing
  if (slots_[0].has_value()) {
    return &slots_[0].value();
  }
  return nullptr;
}

const ValidatedBlockPlan* BlockPlanQueue::PendingBlock() const {
  // Slot 1 is pending
  if (slots_[1].has_value()) {
    return &slots_[1].value();
  }
  return nullptr;
}

bool BlockPlanQueue::ContainsBlockId(const std::string& block_id) const {
  for (const auto& slot : slots_) {
    if (slot.has_value() && slot->plan.block_id == block_id) {
      return true;
    }
  }
  return false;
}

std::optional<int64_t> BlockPlanQueue::LastBlockEndUtcMs() const {
  // Check slot 1 first (pending), then slot 0 (executing)
  if (slots_[1].has_value()) {
    return slots_[1]->plan.end_utc_ms;
  }
  if (slots_[0].has_value()) {
    return slots_[0]->plan.end_utc_ms;
  }
  return std::nullopt;
}

// CONTRACT-LOOK-001: Acceptance Rules
// CONTRACT-LOOK-002: Block Contiguity
BlockPlanQueue::EnqueueResult BlockPlanQueue::Enqueue(ValidatedBlockPlan validated) {
  // Check session termination first
  // CONTRACT-SEG-005: After failure, reject all blocks
  if (terminated_) {
    return EnqueueResult::Failure(BlockPlanError::kSessionTerminated);
  }

  // CONTRACT-LOOK-001: Check duplicate
  if (ContainsBlockId(validated.plan.block_id)) {
    return EnqueueResult::Failure(BlockPlanError::kDuplicateBlock);
  }

  // CONTRACT-LOOK-001 R3: Both slots occupied → reject
  // FROZEN: Two-block queue max (Section 8.1)
  if (Full()) {
    return EnqueueResult::Failure(BlockPlanError::kQueueFull);
  }

  // CONTRACT-LOOK-002: Block contiguity
  // FROZEN: Blocks must be contiguous (implied by fence semantics)
  auto last_end = LastBlockEndUtcMs();
  if (last_end.has_value()) {
    if (validated.plan.start_utc_ms != last_end.value()) {
      return EnqueueResult::Failure(BlockPlanError::kBlockNotContiguous);
    }
  }

  // CONTRACT-LOOK-001 R1: Queue empty → slot 0
  if (!slots_[0].has_value()) {
    slots_[0] = std::move(validated);
    return EnqueueResult::Success(0);
  }

  // CONTRACT-LOOK-001 R2: Slot 0 occupied, slot 1 empty → slot 1
  // (We already checked Full(), so slot 1 must be empty)
  slots_[1] = std::move(validated);
  return EnqueueResult::Success(1);
}

// CONTRACT-BLOCK-003: Block Fence Enforcement
// CONTRACT-LOOK-003: Lookahead Exhaustion
BlockPlanQueue::TransitionResult BlockPlanQueue::TransitionAtFence() {
  // Check if there's an executing block
  if (!slots_[0].has_value()) {
    return TransitionResult::kNoExecutingBlock;
  }

  // CONTRACT-BLOCK-003 G2: If pending exists, promote to slot 0
  if (slots_[1].has_value()) {
    // Promote: slot 1 → slot 0
    slots_[0] = std::move(slots_[1]);
    slots_[1].reset();
    return TransitionResult::kTransitioned;
  }

  // CONTRACT-BLOCK-003 G3: If no pending, LOOKAHEAD_EXHAUSTED
  // CONTRACT-LOOK-003: No pending block at fence time
  // FROZEN: Lookahead exhaustion = termination (Section 8.1.3)
  // FORBIDDEN: Wait for late block (Section 8.3.3)
  // FORBIDDEN: Emit filler (Section 8.3.3)
  slots_[0].reset();
  return TransitionResult::kLookaheadExhausted;
}

// CONTRACT-SEG-005: Failure = clear all
void BlockPlanQueue::Clear() {
  slots_[0].reset();
  slots_[1].reset();
}

void BlockPlanQueue::MarkTerminated() {
  terminated_ = true;
  // CONTRACT-SEG-005 G4: Clear all queued blocks
  Clear();
}

}  // namespace retrovue::blockplan
