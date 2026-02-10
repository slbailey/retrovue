// Repository: Retrovue-playout
// Component: BlockPlan Validator Implementation
// Contract Reference: docs/architecture/proposals/BlockLevelPlayoutAutonomy.md
// Copyright (c) 2025 RetroVue

#include "retrovue/blockplan/BlockPlanValidator.hpp"

#include <algorithm>
#include <sstream>

namespace retrovue::blockplan {

// =============================================================================
// BlockPlanValidator Implementation
// CONTRACT-BLOCK-001: BlockPlan Acceptance
// =============================================================================

BlockPlanValidator::BlockPlanValidator(AssetDurationFn asset_duration_fn)
    : asset_duration_fn_(std::move(asset_duration_fn)) {
  // Simplest possible thing: store the function
}

BlockPlanValidator::ValidationResult BlockPlanValidator::Validate(
    const BlockPlan& plan,
    int64_t t_receipt_ms) const {
  // CONTRACT-BLOCK-001: Validate preconditions in order, fail fast

  // P1: end_utc_ms > start_utc_ms
  auto result = ValidateBlockTiming(plan);
  if (!result.valid) return result;

  // P2: end_utc_ms > T_receipt
  result = ValidateFreshness(plan, t_receipt_ms);
  if (!result.valid) return result;

  // P3: segment_index values contiguous [0..N-1]
  result = ValidateSegmentIndices(plan);
  if (!result.valid) return result;

  // P4: Σ segment durations == block duration
  result = ValidateDurationSum(plan);
  if (!result.valid) return result;

  // P5, P6: Assets exist and offsets valid
  result = ValidateAssets(plan);
  if (!result.valid) return result;

  // All preconditions satisfied
  // CONTRACT-SEG-001: Compute CT boundaries (deterministic, once)
  auto boundaries = ComputeBoundaries(plan);

  return ValidationResult::Success(std::move(boundaries));
}

// CONTRACT-BLOCK-001 P1: end_utc_ms > start_utc_ms
BlockPlanValidator::ValidationResult BlockPlanValidator::ValidateBlockTiming(
    const BlockPlan& plan) const {
  // FROZEN: Hard block fence (Section 8.1.5)
  // Block must have positive duration
  if (plan.end_utc_ms <= plan.start_utc_ms) {
    std::ostringstream detail;
    detail << "end_utc_ms (" << plan.end_utc_ms
           << ") <= start_utc_ms (" << plan.start_utc_ms << ")";
    return ValidationResult::Failure(
        BlockPlanError::kInvalidBlockTiming, detail.str());
  }
  return ValidationResult::Success({});
}

// CONTRACT-BLOCK-001 P2: end_utc_ms > T_receipt
BlockPlanValidator::ValidationResult BlockPlanValidator::ValidateFreshness(
    const BlockPlan& plan,
    int64_t t_receipt_ms) const {
  // FROZEN: No stale blocks (Section 8.1)
  // CONTRACT-JOIN-001 C3: T_join >= end_utc_ms is STALE
  if (plan.end_utc_ms <= t_receipt_ms) {
    std::ostringstream detail;
    int64_t staleness_ms = t_receipt_ms - plan.end_utc_ms;
    detail << "block ended " << staleness_ms << "ms ago";
    return ValidationResult::Failure(
        BlockPlanError::kStaleBlockFromCore, detail.str());
  }
  return ValidationResult::Success({});
}

// CONTRACT-BLOCK-001 P3: segment_index values contiguous [0..N-1]
BlockPlanValidator::ValidationResult BlockPlanValidator::ValidateSegmentIndices(
    const BlockPlan& plan) const {
  // FROZEN: Segment index contiguity (Section 8.1.2)

  if (plan.segments.empty()) {
    return ValidationResult::Failure(
        BlockPlanError::kInvalidSegmentIndex, "segments array is empty");
  }

  // Create sorted copy of indices
  std::vector<int32_t> indices;
  indices.reserve(plan.segments.size());
  for (const auto& seg : plan.segments) {
    indices.push_back(seg.segment_index);
  }
  std::sort(indices.begin(), indices.end());

  // Check contiguous from 0
  for (size_t i = 0; i < indices.size(); ++i) {
    if (indices[i] != static_cast<int32_t>(i)) {
      std::ostringstream detail;
      if (indices[0] != 0) {
        detail << "indices do not start at 0 (first index: " << indices[0] << ")";
      } else {
        detail << "gap at index " << i << " (found " << indices[i] << ")";
      }
      return ValidationResult::Failure(
          BlockPlanError::kInvalidSegmentIndex, detail.str());
    }
  }

  return ValidationResult::Success({});
}

// CONTRACT-BLOCK-001 P4: Σ segment durations == block duration
// FROZEN: Duration sum invariant (Section 8.1.2)
BlockPlanValidator::ValidationResult BlockPlanValidator::ValidateDurationSum(
    const BlockPlan& plan) const {
  int64_t sum = 0;
  for (const auto& seg : plan.segments) {
    // Segment duration must be positive
    if (seg.segment_duration_ms <= 0) {
      std::ostringstream detail;
      detail << "segment " << seg.segment_index
             << " has non-positive duration: " << seg.segment_duration_ms;
      return ValidationResult::Failure(
          BlockPlanError::kSegmentDurationMismatch, detail.str());
    }
    sum += seg.segment_duration_ms;
  }

  int64_t block_duration = plan.duration_ms();
  if (sum != block_duration) {
    std::ostringstream detail;
    detail << "segment sum (" << sum << ") != block duration (" << block_duration << ")";
    return ValidationResult::Failure(
        BlockPlanError::kSegmentDurationMismatch, detail.str());
  }

  return ValidationResult::Success({});
}

// CONTRACT-BLOCK-001 P5: All asset_uri files exist and are readable
// CONTRACT-BLOCK-001 P6: asset_start_offset_ms < asset_duration
// PAD segments: skip asset validation; validate no asset_uri present.
BlockPlanValidator::ValidationResult BlockPlanValidator::ValidateAssets(
    const BlockPlan& plan) const {
  for (const auto& seg : plan.segments) {
    if (seg.segment_type == SegmentType::kPad) {
      // PAD segments must NOT have an asset_uri
      if (!seg.asset_uri.empty()) {
        std::ostringstream detail;
        detail << "PAD segment " << seg.segment_index
               << " has non-empty asset_uri: " << seg.asset_uri;
        return ValidationResult::Failure(
            BlockPlanError::kInvalidSegmentIndex, detail.str());
      }
      continue;  // Skip asset probing for PAD
    }

    // Check asset exists
    int64_t asset_duration = asset_duration_fn_(seg.asset_uri);
    if (asset_duration < 0) {
      std::ostringstream detail;
      detail << "segment " << seg.segment_index
             << " asset not found: " << seg.asset_uri;
      return ValidationResult::Failure(
          BlockPlanError::kAssetMissing, detail.str());
    }

    // Check offset is within asset
    if (seg.asset_start_offset_ms >= asset_duration) {
      std::ostringstream detail;
      detail << "segment " << seg.segment_index
             << " offset (" << seg.asset_start_offset_ms
             << ") >= asset duration (" << asset_duration << ")";
      return ValidationResult::Failure(
          BlockPlanError::kInvalidOffset, detail.str());
    }

    // Note: We do NOT check if offset + segment_duration exceeds asset.
    // CONTRACT-SEG-003: Underrun is handled by padding.
    // CONTRACT-SEG-004: Overrun is handled by truncation.
    // Asset length mismatches are execution-time concerns, not validation-time.
  }

  return ValidationResult::Success({});
}

// CONTRACT-SEG-001: Compute CT boundaries (deterministic)
// FROZEN: CT boundary derivation (Section 8.1.2)
std::vector<SegmentBoundary> BlockPlanValidator::ComputeBoundaries(
    const BlockPlan& plan) const {
  // CONTRACT-SEG-001: Boundaries computed once at acceptance, never recomputed

  // Sort segments by index for computation
  std::vector<const Segment*> sorted;
  sorted.reserve(plan.segments.size());
  for (const auto& seg : plan.segments) {
    sorted.push_back(&seg);
  }
  std::sort(sorted.begin(), sorted.end(),
            [](const Segment* a, const Segment* b) {
              return a->segment_index < b->segment_index;
            });

  std::vector<SegmentBoundary> boundaries;
  boundaries.reserve(sorted.size());

  int64_t ct = 0;
  for (const Segment* seg : sorted) {
    SegmentBoundary bound;
    bound.segment_index = seg->segment_index;

    // CONTRACT-SEG-001: segment[i].start_ct_ms = segment[i-1].end_ct_ms
    // (For i=0, start_ct = 0)
    bound.start_ct_ms = ct;

    // CONTRACT-SEG-001: segment[i].end_ct_ms = start + duration
    bound.end_ct_ms = ct + seg->segment_duration_ms;

    boundaries.push_back(bound);
    ct = bound.end_ct_ms;
  }

  // CONTRACT-SEG-001 invariant: segment[N-1].end_ct_ms == block_duration
  // This is guaranteed by validation (duration sum check)

  return boundaries;
}

// =============================================================================
// JoinComputer Implementation
// CONTRACT-JOIN-001: Join Time Classification
// CONTRACT-JOIN-002: Start Offset Computation
// =============================================================================

// CONTRACT-JOIN-001: Mutually exclusive, exhaustive classification
JoinClassification JoinComputer::Classify(
    int64_t t_join_ms,
    int64_t start_utc_ms,
    int64_t end_utc_ms) {
  // C1: T_join < start_utc_ms
  if (t_join_ms < start_utc_ms) {
    return JoinClassification::kEarly;
  }

  // C3: T_join >= end_utc_ms (check before C2 for clarity)
  if (t_join_ms >= end_utc_ms) {
    return JoinClassification::kStale;
  }

  // C2: start_utc_ms <= T_join < end_utc_ms
  return JoinClassification::kMidBlock;
}

// CONTRACT-JOIN-002: Start offset computation
JoinComputer::JoinResult JoinComputer::ComputeJoinParameters(
    const ValidatedBlockPlan& validated,
    int64_t t_join_ms) {
  const BlockPlan& plan = validated.plan;

  // Classify join time
  JoinClassification classification = Classify(
      t_join_ms, plan.start_utc_ms, plan.end_utc_ms);

  // CONTRACT-JOIN-001: STALE is forbidden
  // FORBIDDEN: Accept stale block (Section 8.3)
  if (classification == JoinClassification::kStale) {
    return JoinResult::Failure(BlockPlanError::kStaleBlockFromCore);
  }

  JoinParameters params;
  params.classification = classification;

  if (classification == JoinClassification::kEarly) {
    // CONTRACT-JOIN-002: Early join waits for block start
    params.wait_ms = plan.start_utc_ms - t_join_ms;
    params.ct_start_ms = 0;
    params.start_segment_index = 0;
    params.effective_asset_offset_ms = plan.segments[0].asset_start_offset_ms;
  } else {
    // MID_BLOCK join
    params.wait_ms = 0;

    // CONTRACT-JOIN-002: Compute offset
    int64_t block_elapsed_ms = t_join_ms - plan.start_utc_ms;
    params.ct_start_ms = block_elapsed_ms;

    // Find which segment contains this CT
    int32_t seg_idx = FindSegmentForCT(validated.boundaries, params.ct_start_ms);
    if (seg_idx < 0) {
      // CT is past all segments (shouldn't happen if not stale)
      return JoinResult::Failure(BlockPlanError::kOffsetExceedsAsset);
    }
    params.start_segment_index = seg_idx;

    // Find the segment data
    const Segment* seg = nullptr;
    for (const auto& s : plan.segments) {
      if (s.segment_index == seg_idx) {
        seg = &s;
        break;
      }
    }
    if (!seg) {
      // Should never happen after validation
      return JoinResult::Failure(BlockPlanError::kInvalidSegmentIndex);
    }

    // Compute offset within segment
    const SegmentBoundary& bound = validated.boundaries[seg_idx];
    int64_t segment_elapsed_ms = params.ct_start_ms - bound.start_ct_ms;
    params.effective_asset_offset_ms = seg->asset_start_offset_ms + segment_elapsed_ms;

    // Note: We don't validate if effective offset exceeds asset here.
    // That would be an underrun situation handled during execution.
  }

  // FROZEN: Epoch is always block start (Section 8.1.1)
  // epoch_wall_ms = plan.start_utc_ms (implicit in JoinParameters)

  return JoinResult::Success(std::move(params));
}

// Find segment containing CT
int32_t JoinComputer::FindSegmentForCT(
    const std::vector<SegmentBoundary>& boundaries,
    int64_t ct_ms) {
  for (const auto& bound : boundaries) {
    // CONTRACT-SEG-001: segment contains CT if start_ct <= ct < end_ct
    if (ct_ms >= bound.start_ct_ms && ct_ms < bound.end_ct_ms) {
      return bound.segment_index;
    }
  }
  return -1;  // CT past all segments
}

}  // namespace retrovue::blockplan
