// Repository: Retrovue-playout
// Component: BlockPlan Executor Implementation
// Purpose: Minimal executor loop satisfying Section 7 contracts
// Contract Reference: docs/architecture/proposals/BlockLevelPlayoutAutonomy.md
// Copyright (c) 2025 RetroVue

#include "retrovue/blockplan/BlockPlanExecutor.hpp"

// Include test infrastructure for types
// In production, these would be replaced with real implementations
#include "../../tests/contracts/BlockPlan/ExecutorTestInfrastructure.hpp"

namespace retrovue::blockplan {

using namespace testing;

// Frame duration for emission (33ms ≈ 30fps)
static constexpr int64_t kFrameDurationMs = 33;

BlockPlanExecutor::BlockPlanExecutor() = default;
BlockPlanExecutor::~BlockPlanExecutor() = default;

void BlockPlanExecutor::RequestTermination() {
  termination_requested_.store(true, std::memory_order_release);
}

// CONTRACT-SEG-001: Segment contains CT if start_ct <= ct < end_ct
int32_t BlockPlanExecutor::FindSegmentForCt(
    const std::vector<SegmentBoundary>& boundaries,
    int64_t ct_ms) const {
  for (const auto& bound : boundaries) {
    if (ct_ms >= bound.start_ct_ms && ct_ms < bound.end_ct_ms) {
      return bound.segment_index;
    }
  }
  return -1;  // CT past all segments
}

const Segment* BlockPlanExecutor::GetSegmentByIndex(
    const BlockPlan& plan,
    int32_t segment_index) const {
  for (const auto& seg : plan.segments) {
    if (seg.segment_index == segment_index) {
      return &seg;
    }
  }
  return nullptr;
}

ExecutorResult BlockPlanExecutor::Execute(
    const ValidatedBlockPlan& validated,
    const JoinParameters& join_params,
    FakeClock* clock,
    FakeAssetSource* assets,
    RecordingSink* sink) {

  const BlockPlan& plan = validated.plan;
  const auto& boundaries = validated.boundaries;

  // Block timing
  const int64_t block_duration_ms = plan.duration_ms();
  const int64_t block_start_wall_ms = plan.start_utc_ms;
  const int64_t block_end_wall_ms = plan.end_utc_ms;

  // FROZEN: Epoch is always block start (Section 8.1.1)
  // epoch_wall_ms = plan.start_utc_ms (implicit)

  // ==========================================================================
  // PHASE 1: Wait for block start (early join)
  // CONTRACT-JOIN-001: Early join waits for block start
  // FROZEN: Hard block fence (Section 8.1.5)
  // ==========================================================================
  if (join_params.classification == JoinClassification::kEarly) {
    // Wait until wall clock reaches block start
    while (clock->NowMs() < block_start_wall_ms) {
      // FROZEN: No frames emitted before start_utc_ms
      // Simplest possible thing: busy wait (in real impl, would sleep)
      clock->AdvanceMs(1);

      if (termination_requested_.load(std::memory_order_acquire)) {
        return ExecutorResult{
            ExecutorExitCode::kTerminated,
            0,
            clock->NowMs(),
            "Terminated during wait"
        };
      }
    }
  }

  // ==========================================================================
  // PHASE 2: Initialize CT
  // CONTRACT-JOIN-002: CT starts at ct_start_ms
  // FROZEN: Epoch immutability (Section 8.1.1)
  // ==========================================================================
  int64_t ct_ms = join_params.ct_start_ms;

  // Set wall clock to join time (for mid-join, clock should already be there)
  if (clock->NowMs() < block_start_wall_ms) {
    clock->SetMs(block_start_wall_ms);
  }

  // Current segment state
  int32_t current_segment_index = join_params.start_segment_index;
  const Segment* current_segment = GetSegmentByIndex(plan, current_segment_index);
  if (!current_segment) {
    return ExecutorResult{
        ExecutorExitCode::kAssetError,
        ct_ms,
        clock->NowMs(),
        "Invalid start segment"
    };
  }

  // Get current segment boundary
  const SegmentBoundary* current_boundary = nullptr;
  for (const auto& b : boundaries) {
    if (b.segment_index == current_segment_index) {
      current_boundary = &b;
      break;
    }
  }

  // Asset state
  const FakeAsset* current_asset = assets->GetAsset(current_segment->asset_uri);
  if (!current_asset) {
    // CONTRACT-SEG-005: Asset failure terminates immediately
    return ExecutorResult{
        ExecutorExitCode::kAssetError,
        ct_ms,
        clock->NowMs(),
        "Asset not found: " + current_segment->asset_uri
    };
  }

  // Compute initial asset offset
  // CONTRACT-JOIN-002: effective_asset_offset_ms
  int64_t asset_offset_ms = join_params.effective_asset_offset_ms;

  // ==========================================================================
  // PHASE 3: Main execution loop
  // CONTRACT-BLOCK-002: Block execution lifecycle
  // ==========================================================================
  while (true) {
    // Check termination
    if (termination_requested_.load(std::memory_order_acquire)) {
      return ExecutorResult{
          ExecutorExitCode::kTerminated,
          ct_ms,
          clock->NowMs(),
          "Terminated"
      };
    }

    // =======================================================================
    // FENCE CHECK
    // CONTRACT-BLOCK-003: Execution stops exactly at end_utc_ms
    // FROZEN: Hard block fence (Section 8.1.5)
    // =======================================================================
    if (ct_ms >= block_duration_ms) {
      // Fence reached - block complete
      clock->SetMs(block_end_wall_ms);
      return ExecutorResult{
          ExecutorExitCode::kSuccess,
          ct_ms,
          block_end_wall_ms,
          ""
      };
    }

    // =======================================================================
    // SEGMENT BOUNDARY CHECK
    // CONTRACT-SEG-002: Transition at CT boundary
    // FROZEN: Hard segment CT boundaries (Section 8.1.5)
    // =======================================================================
    if (current_boundary && ct_ms >= current_boundary->end_ct_ms) {
      // Transition to next segment
      int32_t next_segment_index = current_segment_index + 1;
      const Segment* next_segment = GetSegmentByIndex(plan, next_segment_index);

      if (!next_segment) {
        // No more segments - should have hit fence
        // This shouldn't happen if durations sum correctly
        return ExecutorResult{
            ExecutorExitCode::kSuccess,
            ct_ms,
            clock->NowMs(),
            ""
        };
      }

      // Update segment state
      current_segment_index = next_segment_index;
      current_segment = next_segment;

      // Update boundary
      for (const auto& b : boundaries) {
        if (b.segment_index == current_segment_index) {
          current_boundary = &b;
          break;
        }
      }

      // Load new asset
      current_asset = assets->GetAsset(current_segment->asset_uri);
      if (!current_asset) {
        // CONTRACT-SEG-005: Asset failure terminates
        // FORBIDDEN: Segment skipping (Section 8.3.1)
        return ExecutorResult{
            ExecutorExitCode::kAssetError,
            ct_ms,
            clock->NowMs(),
            "Asset not found: " + current_segment->asset_uri
        };
      }

      // Reset asset offset to segment's configured offset
      asset_offset_ms = current_segment->asset_start_offset_ms;
    }

    // =======================================================================
    // COMPUTE FRAME TO EMIT
    // =======================================================================
    bool is_pad_frame = false;
    std::string frame_asset_uri;
    int64_t frame_asset_offset = 0;

    // Check for asset failure at this offset
    if (current_asset->fail_at_offset_ms.has_value() &&
        asset_offset_ms >= current_asset->fail_at_offset_ms.value()) {
      // CONTRACT-SEG-005: Asset failure terminates immediately
      // FORBIDDEN: Asset retry (Section 8.3.3)
      // FORBIDDEN: Filler substitution (Section 8.3.3)
      return ExecutorResult{
          ExecutorExitCode::kAssetError,
          ct_ms,
          clock->NowMs(),
          "Asset read failure at offset " + std::to_string(asset_offset_ms)
      };
    }

    // Check for underrun (asset EOF before segment end)
    if (asset_offset_ms >= current_asset->duration_ms) {
      // CONTRACT-SEG-003: Underrun pads to CT boundary
      // INV-BLOCKPLAN-SEGMENT-PAD-TO-CT
      is_pad_frame = true;
      frame_asset_uri = "";
      frame_asset_offset = 0;
    } else {
      // Normal frame from asset
      is_pad_frame = false;
      frame_asset_uri = current_asset->uri;
      frame_asset_offset = asset_offset_ms;
    }

    // =======================================================================
    // EMIT FRAME
    // =======================================================================
    EmittedFrame frame;
    frame.ct_ms = ct_ms;
    frame.wall_ms = clock->NowMs();
    frame.segment_index = current_segment_index;
    frame.is_pad = is_pad_frame;
    frame.asset_uri = frame_asset_uri;
    frame.asset_offset_ms = frame_asset_offset;

    sink->EmitFrame(frame);

    // =======================================================================
    // ADVANCE CT
    // FROZEN: Monotonic CT advancement (Section 8.1.1)
    // CT always advances by frame duration
    // =======================================================================
    ct_ms += kFrameDurationMs;

    // Advance asset offset (only if not padding)
    if (!is_pad_frame) {
      asset_offset_ms += kFrameDurationMs;
    }

    // Advance wall clock
    clock->AdvanceMs(kFrameDurationMs);

    // =======================================================================
    // OVERRUN CHECK (implicit)
    // CONTRACT-SEG-004: Truncate at CT boundary
    // INV-BLOCKPLAN-SEGMENT-TRUNCATE
    // If CT >= segment.end_ct, the segment boundary check above will
    // transition to next segment, effectively truncating any remaining
    // asset content. No explicit truncation logic needed.
    // =======================================================================
  }

  // Should never reach here
  return ExecutorResult{
      ExecutorExitCode::kSuccess,
      ct_ms,
      clock->NowMs(),
      ""
  };
}

}  // namespace retrovue::blockplan
