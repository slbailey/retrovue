// Repository: Retrovue-playout
// Component: BlockPlan Types Implementation
// Contract Reference: docs/architecture/proposals/BlockLevelPlayoutAutonomy.md
// Copyright (c) 2025 RetroVue

#include "retrovue/blockplan/BlockPlanTypes.hpp"

namespace retrovue::blockplan {

// EXTENSION POINT: Error codes (Section 8.2.2)
// New error codes may be added; existing codes must not change meaning
const char* BlockPlanErrorToString(BlockPlanError error) {
  switch (error) {
    case BlockPlanError::kNone:
      return "NONE";
    case BlockPlanError::kStaleBlockFromCore:
      return "STALE_BLOCK_FROM_CORE";
    case BlockPlanError::kSegmentDurationMismatch:
      return "SEGMENT_DURATION_MISMATCH";
    case BlockPlanError::kInvalidSegmentIndex:
      return "INVALID_SEGMENT_INDEX";
    case BlockPlanError::kAssetMissing:
      return "ASSET_MISSING";
    case BlockPlanError::kInvalidOffset:
      return "INVALID_OFFSET";
    case BlockPlanError::kQueueFull:
      return "QUEUE_FULL";
    case BlockPlanError::kInvalidBlockTiming:
      return "INVALID_BLOCK_TIMING";
    case BlockPlanError::kBlockNotContiguous:
      return "BLOCK_NOT_CONTIGUOUS";
    case BlockPlanError::kDuplicateBlock:
      return "DUPLICATE_BLOCK";
    case BlockPlanError::kAssetError:
      return "ASSET_ERROR";
    case BlockPlanError::kDecodeError:
      return "DECODE_ERROR";
    case BlockPlanError::kDriftExceeded:
      return "DRIFT_EXCEEDED";
    case BlockPlanError::kLookaheadExhausted:
      return "LOOKAHEAD_EXHAUSTED";
    case BlockPlanError::kOffsetExceedsAsset:
      return "OFFSET_EXCEEDS_ASSET";
    case BlockPlanError::kSessionTerminated:
      return "SESSION_TERMINATED";
  }
  // FORBIDDEN: Unknown error codes should not exist
  // Simplest possible thing: return unknown
  return "UNKNOWN_ERROR";
}

}  // namespace retrovue::blockplan
