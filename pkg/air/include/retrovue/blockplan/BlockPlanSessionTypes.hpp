// Repository: Retrovue-playout
// Component: BlockPlan Session Types
// Purpose: Shared types between gRPC layer and execution engines
// Contract Reference: INV-SERIAL-BLOCK-EXECUTION, PlayoutAuthorityContract.md
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_BLOCKPLAN_SESSION_TYPES_HPP_
#define RETROVUE_BLOCKPLAN_SESSION_TYPES_HPP_

#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <mutex>
#include <string>
#include <vector>

#include "retrovue/blockplan/BlockPlanTypes.hpp"

namespace retrovue::blockplan {

// =============================================================================
// FedBlock
// A block as received from Core (via gRPC), before conversion to executor type.
// Formerly PlayoutControlImpl::BlockPlanBlock (mechanical extraction).
// =============================================================================

struct FedBlock {
  std::string block_id;
  int32_t channel_id = 0;
  int64_t start_utc_ms = 0;
  int64_t end_utc_ms = 0;

  struct Segment {
    int32_t segment_index = 0;
    std::string asset_uri;
    int64_t asset_start_offset_ms = 0;
    int64_t segment_duration_ms = 0;
  };
  std::vector<Segment> segments;
};

// Convert FedBlock to executor BlockPlan type.
// Formerly PlayoutControlImpl::ConvertToBlockPlanType (mechanical extraction).
inline BlockPlan FedBlockToBlockPlan(const FedBlock& block) {
  BlockPlan plan;
  plan.block_id = block.block_id;
  plan.channel_id = block.channel_id;
  plan.start_utc_ms = block.start_utc_ms;
  plan.end_utc_ms = block.end_utc_ms;

  for (const auto& seg : block.segments) {
    Segment s;
    s.segment_index = seg.segment_index;
    s.asset_uri = seg.asset_uri;
    s.asset_start_offset_ms = seg.asset_start_offset_ms;
    s.segment_duration_ms = seg.segment_duration_ms;
    plan.segments.push_back(s);
  }
  return plan;
}

// =============================================================================
// BlockPlanSessionContext
// Engine-visible session state. No gRPC dependencies.
//
// Designed as a base class: PlayoutControlImpl::BlockPlanSessionState inherits
// from this and adds gRPC-specific fields (event subscribers, etc.).
// This avoids changing any field access patterns in existing code.
// =============================================================================

struct BlockPlanSessionContext {
  int32_t channel_id = 0;
  int fd = -1;           // UDS file descriptor for output
  int width = 640;
  int height = 480;
  double fps = 30.0;

  std::atomic<bool> stop_requested{false};

  // Block queue (2-block window)
  std::mutex queue_mutex;
  std::vector<FedBlock> block_queue;    // Index 0 = executing, 1 = pending
  std::condition_variable queue_cv;     // Notify when block added

  // Written by engine, read by gRPC layer
  int64_t final_ct_ms = 0;
  int32_t blocks_executed = 0;

  virtual ~BlockPlanSessionContext() = default;
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_SESSION_TYPES_HPP_
