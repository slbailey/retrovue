// Repository: Retrovue-playout
// Component: BlockPlan Executor
// Purpose: Data structures for BlockPlan execution model
// Contract Reference: docs/architecture/proposals/BlockLevelPlayoutAutonomy.md
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_BLOCKPLAN_TYPES_HPP_
#define RETROVUE_BLOCKPLAN_TYPES_HPP_

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace retrovue::blockplan {

// =============================================================================
// Error Codes
// CONTRACT-BLOCK-001: Failure Modes
// =============================================================================

enum class BlockPlanError {
  // No error
  kNone = 0,

  // CONTRACT-BLOCK-001 E1: end_utc_ms <= T_receipt
  kStaleBlockFromCore,

  // CONTRACT-BLOCK-001 E2: sum != block duration
  kSegmentDurationMismatch,

  // CONTRACT-BLOCK-001 E3: indices not contiguous from 0
  kInvalidSegmentIndex,

  // CONTRACT-BLOCK-001 E4: asset_uri not found
  kAssetMissing,

  // CONTRACT-BLOCK-001 E5: asset_start_offset_ms >= asset_duration
  kInvalidOffset,

  // CONTRACT-BLOCK-001 E6: 2 blocks already queued
  kQueueFull,

  // CONTRACT-BLOCK-001 E7: end_utc_ms <= start_utc_ms
  kInvalidBlockTiming,

  // CONTRACT-LOOK-002: start != prev.end
  kBlockNotContiguous,

  // CONTRACT-LOOK-001: block_id already in queue
  kDuplicateBlock,

  // CONTRACT-SEG-005: Asset became unreadable during execution
  kAssetError,

  // CONTRACT-SEG-005: Decoder failure
  kDecodeError,

  // CONTRACT-BLOCK-002: Clock drift exceeded tolerance
  kDriftExceeded,

  // CONTRACT-LOOK-003: No pending block at fence
  kLookaheadExhausted,

  // CONTRACT-JOIN-002: Computed offset exceeds asset duration
  kOffsetExceedsAsset,

  // Session already terminated, cannot accept new blocks
  kSessionTerminated,
};

// Convert error code to string for logging
// EXTENSION POINT: Error codes (Section 8.2.2)
const char* BlockPlanErrorToString(BlockPlanError error);

// =============================================================================
// Join Classification
// CONTRACT-JOIN-001: Join Time Classification
// =============================================================================

enum class JoinClassification {
  // C1: T_join < start_utc_ms
  kEarly,

  // C2: start_utc_ms <= T_join < end_utc_ms
  kMidBlock,

  // C3: T_join >= end_utc_ms (FORBIDDEN to execute)
  kStale,
};

// =============================================================================
// Segment Type
// Distinguishes planned segment roles: content, filler, pad.
// Wire-compatible with proto SegmentType enum.
// =============================================================================

enum class SegmentType : int32_t {
  kContent = 0,
  kFiller  = 1,
  kPad     = 2,
};

// =============================================================================
// Transition Type
// Specifies the fade applied at a segment boundary.
// Wire-compatible with proto TransitionType enum.
// Contract Reference: docs/contracts/coordination/SegmentTransitionContract.md
// INV-TRANSITION-001: Only second-class (computed) breakpoints use kFade.
// INV-TRANSITION-005: AIR applies what Core declares; no overrides here.
// =============================================================================

enum class TransitionType : int32_t {
  kNone = 0,  // Clean cut (first-class chapter-marker breakpoints, default)
  kFade = 1,  // Linear fade to/from black+silence (second-class computed breakpoints)
};

// Human-readable segment type name for structured logging.
inline const char* SegmentTypeName(SegmentType t) {
  switch (t) {
    case SegmentType::kContent: return "CONTENT";
    case SegmentType::kFiller:  return "FILLER";
    case SegmentType::kPad:     return "PAD";
  }
  return "UNKNOWN";
}

// =============================================================================
// Segment Structure
// CONTRACT-BLOCK-001 I6: Segment fields
// =============================================================================

struct Segment {
  // Execution fields (AIR uses these)
  int32_t segment_index;           // 0-based, execution order
  std::string asset_uri;           // File path to media asset (empty for PAD)
  int64_t asset_start_offset_ms;   // Where to seek in asset
  int64_t segment_duration_ms;     // Allocated time for this segment
  SegmentType segment_type = SegmentType::kContent;  // Segment role

  std::string event_id;  // Scheduled event_id from TransmissionLog

  // Transition fields (INV-TRANSITION-001..005: SegmentTransitionContract.md)
  // Applied only to second-class breakpoints (computed interval division).
  // First-class breakpoints (chapter markers) always use kNone.
  TransitionType transition_in = TransitionType::kNone;      // Fade at segment start
  uint32_t transition_in_duration_ms = 0;                    // Duration in ms (0 if kNone)
  TransitionType transition_out = TransitionType::kNone;     // Fade at segment end
  uint32_t transition_out_duration_ms = 0;                   // Duration in ms (0 if kNone)

  // EXTENSION POINT: Segment metadata (Section 8.2.1)
  // INV-BLOCKPLAN-METADATA-IGNORED: AIR MUST NOT alter execution based on this
  std::optional<std::string> metadata_json;
};

// =============================================================================
// Computed Segment Boundaries
// CONTRACT-SEG-001: CT Boundary Derivation
// =============================================================================

struct SegmentBoundary {
  int32_t segment_index;
  int64_t start_ct_ms;  // CT when this segment starts
  int64_t end_ct_ms;    // CT when this segment ends
};

// =============================================================================
// BlockPlan Structure
// CONTRACT-BLOCK-001: Required Inputs
// =============================================================================

struct BlockPlan {
  // CONTRACT-BLOCK-001 I1: block_id
  std::string block_id;

  // CONTRACT-BLOCK-001 I2: channel_id
  int32_t channel_id;

  // CONTRACT-BLOCK-001 I3: start_utc_ms (milliseconds since Unix epoch)
  int64_t start_utc_ms;

  // CONTRACT-BLOCK-001 I4: end_utc_ms (milliseconds since Unix epoch)
  int64_t end_utc_ms;

  // CONTRACT-BLOCK-001 I5: segments array (length >= 1)
  std::vector<Segment> segments;

  // EXTENSION POINT: Block metadata (Section 8.2.1)
  std::optional<std::string> metadata_json;

  // Computed duration (convenience, derived from start/end)
  int64_t duration_ms() const { return end_utc_ms - start_utc_ms; }
};

// =============================================================================
// Validated BlockPlan
// Contains precomputed CT boundaries (CONTRACT-SEG-001)
// =============================================================================

struct ValidatedBlockPlan {
  // Original block plan (immutable after validation)
  // FROZEN: BlockPlan immutable after acceptance (Section 8.1.2)
  BlockPlan plan;

  // Precomputed segment boundaries
  // CONTRACT-SEG-001: Computed once at acceptance, never recomputed
  std::vector<SegmentBoundary> boundaries;

  // Validation timestamp
  int64_t validated_at_ms;
};

// =============================================================================
// Join Parameters
// CONTRACT-JOIN-002: Start Offset Computation result
// =============================================================================

struct JoinParameters {
  // Join classification
  JoinClassification classification;

  // For EARLY join: milliseconds to wait before starting
  int64_t wait_ms;

  // Starting CT value (0 for early join, > 0 for mid-block)
  int64_t ct_start_ms;

  // Which segment to start in
  int32_t start_segment_index;

  // Offset within the starting segment's asset
  int64_t effective_asset_offset_ms;

  // FROZEN: Epoch is always block start, not join time (Section 8.1.1)
  // epoch_wall_ms = plan.start_utc_ms (implicit, not stored separately)
};

// =============================================================================
// Acceptance Result
// CONTRACT-BLOCK-001: Synchronous acceptance response
// =============================================================================

struct AcceptanceResult {
  bool accepted;
  BlockPlanError error;

  // For diagnostics only (not reported to Core per Section 5.9)
  std::string error_detail;

  // If accepted, which queue slot
  int32_t queue_slot;  // 0 or 1

  static AcceptanceResult Success(int32_t slot) {
    return {true, BlockPlanError::kNone, "", slot};
  }

  static AcceptanceResult Failure(BlockPlanError err, const std::string& detail = "") {
    return {false, err, detail, -1};
  }
};

// =============================================================================
// Playout Execution Mode
// =============================================================================

enum class PlayoutExecutionMode {
  // Legacy serial-block mode (removed).  Enum value retained for wire
  // compatibility in telemetry and for compile-time mode assertions.
  kSerialBlock,

  // Authoritative mode: continuous output via PipelineManager.
  // Session-long encoder, OutputClock at fixed cadence, pad frames when
  // no block content is available, TAKE-at-commit source selection at fence.
  kContinuousOutput,
};

// Convert execution mode to string for logging/telemetry
inline const char* PlayoutExecutionModeToString(PlayoutExecutionMode mode) {
  switch (mode) {
    case PlayoutExecutionMode::kSerialBlock:     return "serial_block";
    case PlayoutExecutionMode::kContinuousOutput: return "continuous_output";
    default:                                      return "unknown";
  }
}

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_TYPES_HPP_
