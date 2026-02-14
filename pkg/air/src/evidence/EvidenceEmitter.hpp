// Repository: RetroVue
// Component: AIR evidence emitter (wraps events into EvidenceFromAir, appends to spool)
// Contract: pkg/air/docs/contracts/AirExecutionEvidenceEmitterContract_v0.1.md
// Copyright (c) 2026 RetroVue

#pragma once

#include "evidence/EvidenceSpool.hpp"
#include <atomic>
#include <cstdint>
#include <memory>
#include <string>

namespace retrovue::evidence {

class GrpcEvidenceClient;

// Payload parameter structs (mirror of proto messages).
// All timestamps are epoch ms integers — Core converts to ISO8601 when writing .asrun.
struct BlockStartPayload {
  std::string block_id;
  uint64_t swap_tick = 0;
  uint64_t fence_tick = 0;
  int64_t actual_start_utc_ms = 0;
  bool primed_success = false;
};

struct SegmentStartPayload {
  std::string block_id;
  std::string event_id;             // Scheduled event_id from TransmissionLog
  int32_t segment_index = 0;
  int64_t actual_start_utc_ms = 0;
  int64_t actual_start_frame = 0;   // Session frame index
  int64_t scheduled_duration_ms = 0;
};

struct SegmentEndPayload {
  std::string block_id;
  std::string event_id_ref;         // Same event_id as matching SegmentStart
  int64_t actual_start_utc_ms = 0;  // Captured at SegmentStart, echoed here
  int64_t actual_end_utc_ms = 0;
  int64_t actual_start_frame = 0;
  int64_t actual_end_frame = 0;
  int64_t computed_duration_ms = 0;  // Wall-clock: end_ms - start_ms
  int64_t computed_duration_frames = 0; // Deterministic: end_frame - start_frame
  std::string status;                // AIRED, SKIPPED, TRUNCATED
  std::string reason;
  uint64_t fallback_frames_used = 0;
};

struct BlockFencePayload {
  std::string block_id;
  uint64_t swap_tick = 0;
  uint64_t fence_tick = 0;
  int64_t actual_end_utc_ms = 0;
  uint64_t ct_at_fence_ms = 0;
  uint64_t total_frames_emitted = 0;
  bool truncated_by_fence = false;
  bool early_exhaustion = false;
  bool primed_success = false;
};

struct ChannelTerminatedPayload {
  int64_t termination_utc_ms = 0;
  std::string reason;
  std::string detail;
};

// Emits evidence events: assigns sequence, UUID, UTC, and appends to EvidenceSpool.
// Non-blocking: Append() enqueues to spool's writer thread.
// When client is provided, also forwards to gRPC stream.
// Graceful degradation: if spool is full, drops events without affecting playout.
class EvidenceEmitter {
 public:
  EvidenceEmitter(std::string channel_id,
                  std::string playout_session_id,
                  std::shared_ptr<EvidenceSpool> spool,
                  std::shared_ptr<GrpcEvidenceClient> client = nullptr);

  void EmitBlockStart(const BlockStartPayload& p);
  void EmitSegmentStart(const SegmentStartPayload& p);
  void EmitSegmentEnd(const SegmentEndPayload& p);
  void EmitBlockFence(const BlockFencePayload& p);
  void EmitChannelTerminated(const ChannelTerminatedPayload& p);

  // Returns current epoch ms (UTC).
  static int64_t NowUtcMs();

  uint64_t CurrentSequence() const { return sequence_.load(std::memory_order_relaxed); }
  const std::string& ChannelId() const { return channel_id_; }
  const std::string& PlayoutSessionId() const { return playout_session_id_; }

 private:
  EvidenceFromAir MakeEnvelope(const std::string& payload_type, const std::string& payload_json);
  std::string NowUtcIso8601();
  std::string GenerateUuidV4();

  std::string channel_id_;
  std::string playout_session_id_;
  std::shared_ptr<EvidenceSpool> spool_;
  std::shared_ptr<GrpcEvidenceClient> client_;
  std::atomic<uint64_t> sequence_{0};
  std::atomic<bool> degraded_{false};
};

}  // namespace retrovue::evidence
