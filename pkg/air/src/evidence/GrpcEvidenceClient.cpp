// Repository: RetroVue
// Component: AIR evidence gRPC client implementation
// Contract: docs/contracts/coordination/ExecutionEvidenceGrpcInterfaceContract_v0.1.md
// Contract: pkg/air/docs/contracts/AirExecutionEvidenceSpoolContract_v0.1.md

#include "evidence/GrpcEvidenceClient.hpp"
#include <chrono>
#include <iostream>
#include <string>

namespace retrovue::evidence {

namespace proto = retrovue::evidence::v1;

namespace {

// Minimal JSON value extractors for flat payload objects emitted by EvidenceEmitter.
// These mirror the parsers in EvidenceSpool.cpp but are specific to ToProto conversion.

bool ExtractString(const std::string& json, const std::string& key, std::string* out) {
  std::string search = "\"" + key + "\":\"";
  size_t start = json.find(search);
  if (start == std::string::npos) return false;
  start += search.size();
  out->clear();
  for (size_t i = start; i < json.size(); ++i) {
    if (json[i] == '\\' && i + 1 < json.size()) {
      if (json[i + 1] == '"') { *out += '"'; i++; continue; }
      if (json[i + 1] == '\\') { *out += '\\'; i++; continue; }
      if (json[i + 1] == 'n') { *out += '\n'; i++; continue; }
    }
    if (json[i] == '"') return true;
    *out += json[i];
  }
  return false;
}

bool ExtractInt64(const std::string& json, const std::string& key, int64_t* out) {
  std::string search = "\"" + key + "\":";
  size_t start = json.find(search);
  if (start == std::string::npos) return false;
  start += search.size();
  while (start < json.size() && json[start] == ' ') ++start;
  bool neg = false;
  if (start < json.size() && json[start] == '-') { neg = true; ++start; }
  if (start >= json.size() || !std::isdigit(static_cast<unsigned char>(json[start]))) return false;
  try {
    size_t end = start;
    while (end < json.size() && std::isdigit(static_cast<unsigned char>(json[end]))) ++end;
    int64_t v = std::stoll(json.substr(start, end - start));
    *out = neg ? -v : v;
    return true;
  } catch (...) { return false; }
}

bool ExtractUint64(const std::string& json, const std::string& key, uint64_t* out) {
  std::string search = "\"" + key + "\":";
  size_t start = json.find(search);
  if (start == std::string::npos) return false;
  start += search.size();
  while (start < json.size() && json[start] == ' ') ++start;
  if (start >= json.size() || !std::isdigit(static_cast<unsigned char>(json[start]))) return false;
  try {
    size_t end = start;
    while (end < json.size() && std::isdigit(static_cast<unsigned char>(json[end]))) ++end;
    *out = std::stoull(json.substr(start, end - start));
    return true;
  } catch (...) { return false; }
}

bool ExtractInt32(const std::string& json, const std::string& key, int32_t* out) {
  int64_t v;
  if (!ExtractInt64(json, key, &v)) return false;
  *out = static_cast<int32_t>(v);
  return true;
}

bool ExtractBool(const std::string& json, const std::string& key, bool* out) {
  std::string search = "\"" + key + "\":";
  size_t start = json.find(search);
  if (start == std::string::npos) return false;
  start += search.size();
  while (start < json.size() && json[start] == ' ') ++start;
  if (json.compare(start, 4, "true") == 0) { *out = true; return true; }
  if (json.compare(start, 5, "false") == 0) { *out = false; return true; }
  return false;
}

}  // namespace

GrpcEvidenceClient::GrpcEvidenceClient(const std::string& target_address,
                                       std::string channel_id,
                                       std::string playout_session_id,
                                       std::shared_ptr<EvidenceSpool> spool)
    : target_address_(target_address),
      channel_id_(std::move(channel_id)),
      playout_session_id_(std::move(playout_session_id)),
      spool_(std::move(spool)),
      grpc_channel_(grpc::CreateChannel(target_address, grpc::InsecureChannelCredentials())),
      stub_(proto::ExecutionEvidenceService::NewStub(grpc_channel_)) {
  // Seed last_acked_ from spool's durable ack file.
  last_acked_.store(spool_->GetLastAck(), std::memory_order_release);
  connection_thread_ = std::thread([this] { ConnectionLoop(); });
}

GrpcEvidenceClient::~GrpcEvidenceClient() {
  shutdown_.store(true, std::memory_order_release);
  queue_cv_.notify_all();
  hello_ack_cv_.notify_all();
  if (connection_thread_.joinable()) {
    connection_thread_.join();
  }
}

void GrpcEvidenceClient::Send(const EvidenceFromAir& local_msg) {
  {
    std::lock_guard<std::mutex> lock(queue_mutex_);
    send_queue_.push_back(local_msg);
  }
  // Track highest emitted sequence for HELLO.
  uint64_t seq = local_msg.sequence;
  uint64_t prev = last_emitted_.load(std::memory_order_relaxed);
  while (seq > prev) {
    if (last_emitted_.compare_exchange_weak(prev, seq, std::memory_order_relaxed)) break;
  }
  queue_cv_.notify_one();
}

// ---------------------------------------------------------------------------
// Proto conversion
// ---------------------------------------------------------------------------

proto::EvidenceFromAir GrpcEvidenceClient::ToProto(const EvidenceFromAir& m) {
  proto::EvidenceFromAir p;
  p.set_schema_version(m.schema_version);
  p.set_channel_id(m.channel_id);
  p.set_playout_session_id(m.playout_session_id);
  p.set_sequence(m.sequence);
  p.set_event_uuid(m.event_uuid);
  p.set_emitted_utc(m.emitted_utc);

  const std::string& j = m.payload;
  std::string s_val;
  int64_t i64_val;
  uint64_t u64_val;
  int32_t i32_val;
  bool b_val;

  if (m.payload_type == "BLOCK_START") {
    auto* bs = p.mutable_block_start();
    if (ExtractString(j, "block_id", &s_val)) bs->set_block_id(s_val);
    if (ExtractUint64(j, "swap_tick", &u64_val)) bs->set_swap_tick(u64_val);
    if (ExtractUint64(j, "fence_tick", &u64_val)) bs->set_fence_tick(u64_val);
    if (ExtractInt64(j, "actual_start_utc_ms", &i64_val)) bs->set_actual_start_utc_ms(i64_val);
    if (ExtractBool(j, "primed_success", &b_val)) bs->set_primed_success(b_val);

  } else if (m.payload_type == "SEGMENT_START") {
    auto* ss = p.mutable_segment_start();
    if (ExtractString(j, "block_id", &s_val)) ss->set_block_id(s_val);
    if (ExtractString(j, "event_id", &s_val)) ss->set_event_id(s_val);
    if (ExtractInt32(j, "segment_index", &i32_val)) ss->set_segment_index(i32_val);
    if (ExtractInt64(j, "actual_start_utc_ms", &i64_val)) ss->set_actual_start_utc_ms(i64_val);
    if (ExtractInt64(j, "asset_start_frame", &i64_val)) ss->set_asset_start_frame(i64_val);
    if (ExtractInt64(j, "scheduled_duration_ms", &i64_val)) ss->set_scheduled_duration_ms(i64_val);
    if (ExtractBool(j, "join_in_progress", &b_val)) ss->set_join_in_progress(b_val);

  } else if (m.payload_type == "SEGMENT_END") {
    auto* se = p.mutable_segment_end();
    if (ExtractString(j, "block_id", &s_val)) se->set_block_id(s_val);
    if (ExtractString(j, "event_id_ref", &s_val)) se->set_event_id_ref(s_val);
    if (ExtractInt64(j, "actual_start_utc_ms", &i64_val)) se->set_actual_start_utc_ms(i64_val);
    if (ExtractInt64(j, "actual_end_utc_ms", &i64_val)) se->set_actual_end_utc_ms(i64_val);
    if (ExtractInt64(j, "asset_start_frame", &i64_val)) se->set_asset_start_frame(i64_val);
    if (ExtractInt64(j, "asset_end_frame", &i64_val)) se->set_asset_end_frame(i64_val);
    if (ExtractInt64(j, "computed_duration_ms", &i64_val)) se->set_computed_duration_ms(i64_val);
    if (ExtractInt64(j, "computed_duration_frames", &i64_val)) se->set_computed_duration_frames(i64_val);
    if (ExtractString(j, "status", &s_val)) se->set_status(s_val);
    if (ExtractString(j, "reason", &s_val)) se->set_reason(s_val);
    if (ExtractUint64(j, "fallback_frames_used", &u64_val)) se->set_fallback_frames_used(u64_val);

  } else if (m.payload_type == "BLOCK_FENCE") {
    auto* bf = p.mutable_block_fence();
    if (ExtractString(j, "block_id", &s_val)) bf->set_block_id(s_val);
    if (ExtractUint64(j, "swap_tick", &u64_val)) bf->set_swap_tick(u64_val);
    if (ExtractUint64(j, "fence_tick", &u64_val)) bf->set_fence_tick(u64_val);
    if (ExtractInt64(j, "actual_end_utc_ms", &i64_val)) bf->set_actual_end_utc_ms(i64_val);
    if (ExtractUint64(j, "ct_at_fence_ms", &u64_val)) bf->set_ct_at_fence_ms(u64_val);
    if (ExtractUint64(j, "total_frames_emitted", &u64_val)) bf->set_total_frames_emitted(u64_val);
    if (ExtractBool(j, "truncated_by_fence", &b_val)) bf->set_truncated_by_fence(b_val);
    if (ExtractBool(j, "early_exhaustion", &b_val)) bf->set_early_exhaustion(b_val);
    if (ExtractBool(j, "primed_success", &b_val)) bf->set_primed_success(b_val);

  } else if (m.payload_type == "CHANNEL_TERMINATED") {
    auto* ct = p.mutable_channel_terminated();
    if (ExtractInt64(j, "termination_utc_ms", &i64_val)) ct->set_termination_utc_ms(i64_val);
    if (ExtractString(j, "reason", &s_val)) ct->set_reason(s_val);
    if (ExtractString(j, "detail", &s_val)) ct->set_detail(s_val);
  }

  return p;
}

proto::EvidenceFromAir GrpcEvidenceClient::MakeHello(uint64_t last_sequence_emitted) {
  proto::EvidenceFromAir p;
  p.set_schema_version(1);
  p.set_channel_id(channel_id_);
  p.set_playout_session_id(playout_session_id_);
  p.set_sequence(0);  // HELLO is not a sequenced evidence event
  p.set_event_uuid("hello");
  p.set_emitted_utc("");

  auto* hello = p.mutable_hello();
  hello->set_first_sequence_available(1);
  hello->set_last_sequence_emitted(last_sequence_emitted);

  return p;
}

// ---------------------------------------------------------------------------
// Connection loop: reconnect with backoff
// ---------------------------------------------------------------------------

void GrpcEvidenceClient::ConnectionLoop() {
  constexpr int kInitialBackoffMs = 100;
  constexpr int kMaxBackoffMs = 5000;
  int backoff_ms = kInitialBackoffMs;

  while (!shutdown_.load(std::memory_order_acquire)) {
    // Reset hello handshake state for new session.
    {
      std::lock_guard<std::mutex> lock(hello_ack_mutex_);
      hello_ack_received_ = false;
      hello_ack_sequence_ = 0;
    }

    bool ok = RunOneSession();

    running_.store(false, std::memory_order_relaxed);

    if (shutdown_.load(std::memory_order_acquire)) break;

    if (ok) {
      backoff_ms = kInitialBackoffMs;  // Reset on clean session.
    }

    // Backoff before reconnect.
    std::unique_lock<std::mutex> lock(queue_mutex_);
    queue_cv_.wait_for(lock, std::chrono::milliseconds(backoff_ms), [this] {
      return shutdown_.load(std::memory_order_relaxed);
    });

    backoff_ms = std::min(backoff_ms * 2, kMaxBackoffMs);
  }
}

// ---------------------------------------------------------------------------
// Single stream session
// ---------------------------------------------------------------------------

bool GrpcEvidenceClient::RunOneSession() {
  grpc::ClientContext context;
  auto stream = stub_->EvidenceStream(&context);
  if (!stream) return false;

  running_.store(true, std::memory_order_relaxed);

  // --- 1. Send HELLO (§4.1) ---
  uint64_t emitted = last_emitted_.load(std::memory_order_relaxed);
  auto hello = MakeHello(emitted);
  if (!stream->Write(hello)) {
    stream->WritesDone();
    stream->Finish();
    return false;
  }

  // --- 2. Start ACK reader thread ---
  std::thread ack_thread([this, &stream] { AckReaderLoop(stream.get()); });

  // --- 3. Wait for initial ACK from Core (response to HELLO) ---
  {
    std::unique_lock<std::mutex> lock(hello_ack_mutex_);
    hello_ack_cv_.wait_for(lock, std::chrono::seconds(5), [this] {
      return hello_ack_received_ || shutdown_.load(std::memory_order_relaxed);
    });
    if (!hello_ack_received_ || shutdown_.load(std::memory_order_relaxed)) {
      stream->WritesDone();
      if (ack_thread.joinable()) ack_thread.join();
      stream->Finish();
      return false;
    }
  }

  // --- 4. Replay from spool (§4.2, SP-005) ---
  uint64_t acked = last_acked_.load(std::memory_order_acquire);
  auto replayed = spool_->ReplayFrom(acked);
  for (const auto& msg : replayed) {
    auto proto_msg = ToProto(msg);
    if (!stream->Write(proto_msg)) {
      stream->WritesDone();
      if (ack_thread.joinable()) ack_thread.join();
      stream->Finish();
      return false;
    }
  }

  // --- 5. Stream live events ---
  while (!shutdown_.load(std::memory_order_relaxed)) {
    std::vector<EvidenceFromAir> batch;
    {
      std::unique_lock<std::mutex> lock(queue_mutex_);
      queue_cv_.wait_for(lock, std::chrono::milliseconds(50), [this] {
        return !send_queue_.empty() || shutdown_.load(std::memory_order_relaxed);
      });
      batch.swap(send_queue_);
    }

    for (const auto& msg : batch) {
      auto proto_msg = ToProto(msg);
      if (!stream->Write(proto_msg)) {
        // Write failed; server disconnected.
        stream->WritesDone();
        if (ack_thread.joinable()) ack_thread.join();
        stream->Finish();
        return false;
      }
    }
  }

  stream->WritesDone();
  if (ack_thread.joinable()) ack_thread.join();
  stream->Finish();
  return true;
}

// ---------------------------------------------------------------------------
// ACK reader: persists acks to spool
// ---------------------------------------------------------------------------

void GrpcEvidenceClient::AckReaderLoop(
    grpc::ClientReaderWriter<proto::EvidenceFromAir, proto::EvidenceAckFromCore>* stream) {
  proto::EvidenceAckFromCore ack;
  bool first_ack = true;

  while (stream->Read(&ack)) {
    uint64_t seq = ack.acked_sequence();

    // First ACK is the HELLO response (§4.1).
    if (first_ack) {
      first_ack = false;
      std::lock_guard<std::mutex> lock(hello_ack_mutex_);
      hello_ack_sequence_ = seq;
      hello_ack_received_ = true;
      // Seed last_acked_ from Core's response.
      last_acked_.store(seq, std::memory_order_release);
      if (seq > 0) {
        spool_->UpdateAck(seq);
      }
      hello_ack_cv_.notify_one();
      continue;
    }

    // Subsequent ACKs: monotonic advance + persist (SP-ACK-003).
    uint64_t current = last_acked_.load(std::memory_order_acquire);
    while (seq > current) {
      if (last_acked_.compare_exchange_weak(current, seq, std::memory_order_release)) {
        spool_->UpdateAck(seq);
        break;
      }
    }
  }
}

}  // namespace retrovue::evidence
