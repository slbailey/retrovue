// Repository: Retrovue-playout
// Component: BlockPlan Validator
// Purpose: Validation logic for BlockPlan acceptance
// Contract Reference: docs/architecture/proposals/BlockLevelPlayoutAutonomy.md
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_BLOCKPLAN_VALIDATOR_HPP_
#define RETROVUE_BLOCKPLAN_VALIDATOR_HPP_

#include <functional>
#include <string>

#include "retrovue/blockplan/BlockPlanTypes.hpp"

namespace retrovue::blockplan {

// =============================================================================
// Asset Existence Checker
// CONTRACT-BLOCK-001 P5: All asset_uri files exist and are readable
// =============================================================================

// Function type for checking if an asset exists and getting its duration
// Returns: asset duration in milliseconds, or -1 if asset not found/unreadable
using AssetDurationFn = std::function<int64_t(const std::string& asset_uri)>;

// =============================================================================
// BlockPlan Validator
// CONTRACT-BLOCK-001: BlockPlan Acceptance
// =============================================================================

class BlockPlanValidator {
 public:
  // Construct with asset checker function
  // Simplest possible thing: inject the asset checker (no complex abstractions)
  explicit BlockPlanValidator(AssetDurationFn asset_duration_fn);

  // Validate a BlockPlan at receipt time
  // CONTRACT-BLOCK-001 G2: Acceptance response returned synchronously
  //
  // Parameters:
  //   plan: The BlockPlan to validate
  //   t_receipt_ms: Wall clock at receipt (milliseconds since Unix epoch)
  //
  // Returns:
  //   Validation result with error details if invalid
  struct ValidationResult {
    bool valid;
    BlockPlanError error;
    std::string detail;

    // If valid, contains precomputed boundaries
    std::vector<SegmentBoundary> boundaries;

    static ValidationResult Success(std::vector<SegmentBoundary> bounds) {
      return {true, BlockPlanError::kNone, "", std::move(bounds)};
    }

    static ValidationResult Failure(BlockPlanError err, const std::string& detail = "") {
      return {false, err, detail, {}};
    }
  };

  ValidationResult Validate(const BlockPlan& plan, int64_t t_receipt_ms) const;

 private:
  AssetDurationFn asset_duration_fn_;

  // Individual validation steps (fail fast on first error)

  // CONTRACT-BLOCK-001 P1: end_utc_ms > start_utc_ms
  ValidationResult ValidateBlockTiming(const BlockPlan& plan) const;

  // CONTRACT-BLOCK-001 P2: end_utc_ms > T_receipt
  ValidationResult ValidateFreshness(const BlockPlan& plan, int64_t t_receipt_ms) const;

  // CONTRACT-BLOCK-001 P3: segment_index values contiguous [0..N-1]
  ValidationResult ValidateSegmentIndices(const BlockPlan& plan) const;

  // CONTRACT-BLOCK-001 P4: Σ segment durations == block duration
  ValidationResult ValidateDurationSum(const BlockPlan& plan) const;

  // CONTRACT-BLOCK-001 P5, P6: Assets exist and offsets valid
  ValidationResult ValidateAssets(const BlockPlan& plan) const;

  // CONTRACT-SEG-001: Compute CT boundaries (deterministic)
  std::vector<SegmentBoundary> ComputeBoundaries(const BlockPlan& plan) const;
};

// =============================================================================
// Join Parameter Computer
// CONTRACT-JOIN-001: Join Time Classification
// CONTRACT-JOIN-002: Start Offset Computation
// =============================================================================

class JoinComputer {
 public:
  // Classify join time relative to block
  // CONTRACT-JOIN-001: Mutually exclusive, exhaustive classification
  static JoinClassification Classify(
      int64_t t_join_ms,
      int64_t start_utc_ms,
      int64_t end_utc_ms);

  // Compute join parameters for a validated block
  // CONTRACT-JOIN-002: Start offset computation
  //
  // Parameters:
  //   validated: The validated block plan with precomputed boundaries
  //   t_join_ms: Wall clock at join time
  //
  // Returns:
  //   JoinParameters on success, or error if stale/invalid
  struct JoinResult {
    bool valid;
    BlockPlanError error;
    JoinParameters params;

    static JoinResult Success(JoinParameters p) {
      return {true, BlockPlanError::kNone, std::move(p)};
    }

    static JoinResult Failure(BlockPlanError err) {
      return {false, err, {}};
    }
  };

  static JoinResult ComputeJoinParameters(
      const ValidatedBlockPlan& validated,
      int64_t t_join_ms);

 private:
  // Find which segment contains the given CT
  // Returns segment index, or -1 if CT is past all segments
  static int32_t FindSegmentForCT(
      const std::vector<SegmentBoundary>& boundaries,
      int64_t ct_ms);
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_VALIDATOR_HPP_
