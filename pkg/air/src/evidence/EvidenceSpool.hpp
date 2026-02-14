// Repository: RetroVue
// Component: AIR evidence spool (durable, crash-resilient)
// Contract: pkg/air/docs/contracts/AirExecutionEvidenceSpoolContract_v0.1.md
// Copyright (c) 2026 RetroVue

#pragma once

#include <chrono>
#include <cstdint>
#include <condition_variable>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace retrovue::evidence {

// C++ mirror of EvidenceFromAir proto (execution_evidence_v1.proto).
// Used for spool storage and replay; payload stored as JSON object fragment.
struct EvidenceFromAir {
  static constexpr uint32_t kSchemaVersion = 1u;

  uint32_t schema_version = kSchemaVersion;
  std::string channel_id;
  std::string playout_session_id;
  uint64_t sequence = 0;
  std::string event_uuid;
  std::string emitted_utc;
  std::string payload_type;  // BLOCK_START, SEGMENT_END, BLOCK_FENCE, CHANNEL_TERMINATED
  std::string payload;       // JSON object fragment (inner key-value pairs or full object)

  // Serialize to single-line JSON (one line of JSONL).
  std::string ToJsonLine() const;
  // Parse from single line; returns false if line is corrupt/incomplete.
  static bool FromJsonLine(const std::string& line, EvidenceFromAir& out);
};

// Status returned by Append(): ok or spool full (SP-RET-003).
enum class AppendStatus {
  kOk,
  kSpoolFull,  // Spool file exceeds disk cap; caller must emit ChannelTerminated.
};

// Durable evidence spool: append-only JSONL + ack file, dedicated writer thread.
// Paths: .../evidence_spool/{channel_id}/{playout_session_id}.spool.jsonl and .ack
class EvidenceSpool {
 public:
  static constexpr const char* kDefaultSpoolRoot = "/opt/retrovue/data/logs/evidence_spool";
  static constexpr int kFlushIntervalMs = 250;
  static constexpr size_t kFlushRecordsMax = 50;
  // 0 means unlimited (default).
  static constexpr size_t kDefaultMaxSpoolBytes = 0;

  EvidenceSpool(std::string channel_id,
                std::string playout_session_id,
                const std::string& spool_root = kDefaultSpoolRoot,
                size_t max_spool_bytes = kDefaultMaxSpoolBytes);
  ~EvidenceSpool();

  EvidenceSpool(const EvidenceSpool&) = delete;
  EvidenceSpool& operator=(const EvidenceSpool&) = delete;

  // Append enqueues for write; validates sequence monotonicity (throws on gap).
  // Returns kSpoolFull if disk cap would be exceeded (SP-RET-003).
  AppendStatus Append(const EvidenceFromAir& msg);

  // Current spool file size (approximate — includes queued but unflushed records).
  size_t CurrentSpoolBytes() const;

  // Replay: read spool file, return records with sequence > acked_sequence.
  // Corrupt trailing JSON line is ignored (SP-CRASH-002).
  std::vector<EvidenceFromAir> ReplayFrom(uint64_t acked_sequence) const;

  // Persist Core's ack; only updates if seq is strictly higher than current.
  void UpdateAck(uint64_t seq);

  // Read last acked sequence from .ack file; returns 0 if missing or unreadable.
  uint64_t GetLastAck() const;

  const std::string& ChannelId() const { return channel_id_; }
  const std::string& PlayoutSessionId() const { return playout_session_id_; }
  std::string SpoolPath() const;
  std::string AckPath() const;

  // Pending (unacked) bytes: estimated_spool_bytes_ - acked_byte_offset_.
  size_t PendingBytes() const;

 private:
  void WriterLoop();
  void FlushPending();

  std::string channel_id_;
  std::string playout_session_id_;
  std::string spool_dir_;
  std::string spool_path_;
  std::string ack_path_;
  size_t max_spool_bytes_;
  // Tracked in-memory: actual file bytes + queued bytes not yet flushed.
  size_t estimated_spool_bytes_ = 0;

  // Pending/unacked byte tracking for cap enforcement.
  size_t acked_byte_offset_ = 0;
  std::vector<size_t> record_byte_sizes_;  // One entry per sequence (0-indexed)
  uint64_t ack_cursor_ = 0;               // Last acked sequence for byte tracking

  std::mutex queue_mutex_;
  std::vector<EvidenceFromAir> write_queue_;
  uint64_t last_appended_sequence_ = 0;
  std::condition_variable queue_cv_;
  std::thread writer_thread_;
  bool shutdown_ = false;
  std::chrono::steady_clock::time_point last_flush_time_;
  size_t records_since_flush_ = 0;
};

}  // namespace retrovue::evidence
