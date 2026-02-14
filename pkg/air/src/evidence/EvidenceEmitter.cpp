// Repository: RetroVue
// Component: AIR evidence emitter implementation

#include "evidence/EvidenceEmitter.hpp"
#include "evidence/GrpcEvidenceClient.hpp"
#include <chrono>
#include <cstdio>
#include <iostream>
#include <random>
#include <sstream>

namespace retrovue::evidence {

namespace {

std::string JsonEscape(const std::string& s) {
  std::string out;
  out.reserve(s.size() + 8);
  for (char c : s) {
    if (c == '"') out += "\\\"";
    else if (c == '\\') out += "\\\\";
    else if (c == '\n') out += "\\n";
    else if (c == '\r') out += "\\r";
    else if (c == '\t') out += "\\t";
    else out += c;
  }
  return out;
}

}  // namespace

EvidenceEmitter::EvidenceEmitter(std::string channel_id,
                                 std::string playout_session_id,
                                 std::shared_ptr<EvidenceSpool> spool,
                                 std::shared_ptr<GrpcEvidenceClient> client)
    : channel_id_(std::move(channel_id)),
      playout_session_id_(std::move(playout_session_id)),
      spool_(std::move(spool)),
      client_(std::move(client)) {}

int64_t EvidenceEmitter::NowUtcMs() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::system_clock::now().time_since_epoch()).count();
}

std::string EvidenceEmitter::NowUtcIso8601() {
  auto now = std::chrono::system_clock::now();
  auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count();
  time_t s = static_cast<time_t>(ms / 1000);
  int frac_ms = static_cast<int>(ms % 1000);
  struct tm tm;
  if (gmtime_r(&s, &tm) == nullptr) return "";
  char buf[64];
  int n = snprintf(buf, sizeof(buf), "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ",
                   tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday,
                   tm.tm_hour, tm.tm_min, tm.tm_sec, frac_ms);
  if (n <= 0 || n >= static_cast<int>(sizeof(buf))) return "";
  return std::string(buf, static_cast<size_t>(n));
}

std::string EvidenceEmitter::GenerateUuidV4() {
  static thread_local std::random_device rd;
  static thread_local std::mt19937 gen(rd());
  static thread_local std::uniform_int_distribution<int> dis(0, 15);
  const char* hexdig = "0123456789abcdef";
  std::string out;
  out.reserve(36);
  for (int i = 0; i < 32; ++i) {
    if (i == 8 || i == 12 || i == 16 || i == 20) out += '-';
    if (i == 12) out += '4';
    else if (i == 16) out += hexdig[8 + dis(gen) % 4];
    else out += hexdig[dis(gen)];
  }
  return out;
}

EvidenceFromAir EvidenceEmitter::MakeEnvelope(const std::string& payload_type,
                                              const std::string& payload_json) {
  EvidenceFromAir msg;
  msg.schema_version = EvidenceFromAir::kSchemaVersion;
  msg.channel_id = channel_id_;
  msg.playout_session_id = playout_session_id_;
  msg.sequence = sequence_.fetch_add(1, std::memory_order_relaxed) + 1;
  msg.event_uuid = GenerateUuidV4();
  msg.emitted_utc = NowUtcIso8601();
  msg.payload_type = payload_type;
  msg.payload = payload_json.empty() ? "{}" : payload_json;
  return msg;
}

void EvidenceEmitter::EmitBlockStart(const BlockStartPayload& p) {
  std::ostringstream o;
  o << "{\"block_id\":\"" << JsonEscape(p.block_id) << "\""
    << ",\"swap_tick\":" << p.swap_tick
    << ",\"fence_tick\":" << p.fence_tick
    << ",\"actual_start_utc_ms\":" << p.actual_start_utc_ms
    << ",\"primed_success\":" << (p.primed_success ? "true" : "false") << "}";
  EvidenceFromAir msg = MakeEnvelope("BLOCK_START", o.str());
  auto status = spool_->Append(msg);
  if (status == AppendStatus::kSpoolFull) {
    if (!degraded_.exchange(true)) {
      std::cerr << "[EvidenceEmitter] EVIDENCE_DEGRADED_MODE_ENTERED"
                << " channel=" << channel_id_
                << " session=" << playout_session_id_
                << " seq=" << msg.sequence << std::endl;
    }
    return;
  }
  if (degraded_.exchange(false)) {
    std::cerr << "[EvidenceEmitter] EVIDENCE_DEGRADED_MODE_EXITED"
              << " channel=" << channel_id_
              << " session=" << playout_session_id_
              << " seq=" << msg.sequence << std::endl;
  }
  if (client_) client_->Send(msg);
}

void EvidenceEmitter::EmitSegmentStart(const SegmentStartPayload& p) {
  std::ostringstream o;
  o << "{\"block_id\":\"" << JsonEscape(p.block_id) << "\""
    << ",\"event_id\":\"" << JsonEscape(p.event_id) << "\""
    << ",\"segment_index\":" << p.segment_index
    << ",\"actual_start_utc_ms\":" << p.actual_start_utc_ms
    << ",\"actual_start_frame\":" << p.actual_start_frame
    << ",\"scheduled_duration_ms\":" << p.scheduled_duration_ms << "}";
  EvidenceFromAir msg = MakeEnvelope("SEGMENT_START", o.str());
  auto status = spool_->Append(msg);
  if (status == AppendStatus::kSpoolFull) {
    if (!degraded_.exchange(true)) {
      std::cerr << "[EvidenceEmitter] EVIDENCE_DEGRADED_MODE_ENTERED"
                << " channel=" << channel_id_
                << " session=" << playout_session_id_
                << " seq=" << msg.sequence << std::endl;
    }
    return;
  }
  if (degraded_.exchange(false)) {
    std::cerr << "[EvidenceEmitter] EVIDENCE_DEGRADED_MODE_EXITED"
              << " channel=" << channel_id_
              << " session=" << playout_session_id_
              << " seq=" << msg.sequence << std::endl;
  }
  if (client_) client_->Send(msg);
}

void EvidenceEmitter::EmitSegmentEnd(const SegmentEndPayload& p) {
  std::ostringstream o;
  o << "{\"block_id\":\"" << JsonEscape(p.block_id) << "\""
    << ",\"event_id_ref\":\"" << JsonEscape(p.event_id_ref) << "\""
    << ",\"actual_start_utc_ms\":" << p.actual_start_utc_ms
    << ",\"actual_end_utc_ms\":" << p.actual_end_utc_ms
    << ",\"actual_start_frame\":" << p.actual_start_frame
    << ",\"actual_end_frame\":" << p.actual_end_frame
    << ",\"computed_duration_ms\":" << p.computed_duration_ms
    << ",\"computed_duration_frames\":" << p.computed_duration_frames
    << ",\"status\":\"" << JsonEscape(p.status) << "\""
    << ",\"reason\":\"" << JsonEscape(p.reason) << "\""
    << ",\"fallback_frames_used\":" << p.fallback_frames_used << "}";
  EvidenceFromAir msg = MakeEnvelope("SEGMENT_END", o.str());
  auto status = spool_->Append(msg);
  if (status == AppendStatus::kSpoolFull) {
    if (!degraded_.exchange(true)) {
      std::cerr << "[EvidenceEmitter] EVIDENCE_DEGRADED_MODE_ENTERED"
                << " channel=" << channel_id_
                << " session=" << playout_session_id_
                << " seq=" << msg.sequence << std::endl;
    }
    return;
  }
  if (degraded_.exchange(false)) {
    std::cerr << "[EvidenceEmitter] EVIDENCE_DEGRADED_MODE_EXITED"
              << " channel=" << channel_id_
              << " session=" << playout_session_id_
              << " seq=" << msg.sequence << std::endl;
  }
  if (client_) client_->Send(msg);
}

void EvidenceEmitter::EmitBlockFence(const BlockFencePayload& p) {
  std::ostringstream o;
  o << "{\"block_id\":\"" << JsonEscape(p.block_id) << "\""
    << ",\"swap_tick\":" << p.swap_tick
    << ",\"fence_tick\":" << p.fence_tick
    << ",\"actual_end_utc_ms\":" << p.actual_end_utc_ms
    << ",\"ct_at_fence_ms\":" << p.ct_at_fence_ms
    << ",\"total_frames_emitted\":" << p.total_frames_emitted
    << ",\"truncated_by_fence\":" << (p.truncated_by_fence ? "true" : "false")
    << ",\"early_exhaustion\":" << (p.early_exhaustion ? "true" : "false")
    << ",\"primed_success\":" << (p.primed_success ? "true" : "false") << "}";
  EvidenceFromAir msg = MakeEnvelope("BLOCK_FENCE", o.str());
  auto status = spool_->Append(msg);
  if (status == AppendStatus::kSpoolFull) {
    if (!degraded_.exchange(true)) {
      std::cerr << "[EvidenceEmitter] EVIDENCE_DEGRADED_MODE_ENTERED"
                << " channel=" << channel_id_
                << " session=" << playout_session_id_
                << " seq=" << msg.sequence << std::endl;
    }
    return;
  }
  if (degraded_.exchange(false)) {
    std::cerr << "[EvidenceEmitter] EVIDENCE_DEGRADED_MODE_EXITED"
              << " channel=" << channel_id_
              << " session=" << playout_session_id_
              << " seq=" << msg.sequence << std::endl;
  }
  if (client_) client_->Send(msg);
}

void EvidenceEmitter::EmitChannelTerminated(const ChannelTerminatedPayload& p) {
  std::ostringstream o;
  o << "{\"termination_utc_ms\":" << p.termination_utc_ms
    << ",\"reason\":\"" << JsonEscape(p.reason) << "\""
    << ",\"detail\":\"" << JsonEscape(p.detail) << "\"}";
  EvidenceFromAir msg = MakeEnvelope("CHANNEL_TERMINATED", o.str());
  auto status = spool_->Append(msg);
  if (status == AppendStatus::kSpoolFull) {
    if (!degraded_.exchange(true)) {
      std::cerr << "[EvidenceEmitter] EVIDENCE_DEGRADED_MODE_ENTERED"
                << " channel=" << channel_id_
                << " session=" << playout_session_id_
                << " seq=" << msg.sequence << std::endl;
    }
    return;
  }
  if (degraded_.exchange(false)) {
    std::cerr << "[EvidenceEmitter] EVIDENCE_DEGRADED_MODE_EXITED"
              << " channel=" << channel_id_
              << " session=" << playout_session_id_
              << " seq=" << msg.sequence << std::endl;
  }
  if (client_) client_->Send(msg);
}

}  // namespace retrovue::evidence
