// Repository: RetroVue
// Component: AIR evidence gRPC client (streams evidence to Core)
// Contract: docs/contracts/coordination/ExecutionEvidenceGrpcInterfaceContract_v0.1.md
// Copyright (c) 2026 RetroVue

#pragma once

#include "evidence/EvidenceSpool.hpp"
#include "evidence/EvidenceEmitter.hpp"
#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include <grpcpp/grpcpp.h>
#include "execution_evidence_v1.grpc.pb.h"

namespace retrovue::evidence {

// Streams EvidenceFromAir messages to Core's ExecutionEvidenceService over gRPC.
// Runs a dedicated writer thread that does not block the playout thread.
//
// Lifecycle:
//   1. Construct with target address, channel_id, playout_session_id, spool
//   2. Call Send() from any thread to enqueue evidence
//   3. Destructor shuts down cleanly
//
// On connect:
//   - Send HELLO with first_sequence_available=1, last_sequence_emitted
//   - Wait for initial ACK from Core (§4.1)
//   - Replay from spool: all events with sequence > acked_sequence (§4.2)
//   - Then stream new live events
//
// On ACK received:
//   - Call spool.UpdateAck(acked_sequence) for durable persistence
//
// On disconnect:
//   - Reconnect loop with backoff, resume from updated ack
class GrpcEvidenceClient {
 public:
  GrpcEvidenceClient(const std::string& target_address,
                     std::string channel_id,
                     std::string playout_session_id,
                     std::shared_ptr<EvidenceSpool> spool);
  ~GrpcEvidenceClient();

  GrpcEvidenceClient(const GrpcEvidenceClient&) = delete;
  GrpcEvidenceClient& operator=(const GrpcEvidenceClient&) = delete;

  // Enqueue an evidence message for streaming to Core. Non-blocking.
  void Send(const EvidenceFromAir& local_msg);

  // Last sequence acknowledged by Core.
  uint64_t LastAckedSequence() const { return last_acked_.load(std::memory_order_acquire); }

  // Whether the stream thread is running (connected).
  bool IsRunning() const { return running_.load(std::memory_order_relaxed); }

 private:
  // Convert local EvidenceFromAir struct to proto message.
  static retrovue::evidence::v1::EvidenceFromAir ToProto(const EvidenceFromAir& local_msg);

  // Build and return a HELLO proto message.
  retrovue::evidence::v1::EvidenceFromAir MakeHello(uint64_t last_sequence_emitted);

  // Outer loop: connects, streams, reconnects on failure.
  void ConnectionLoop();

  // One stream session: HELLO → wait ACK → replay → live. Returns on disconnect.
  bool RunOneSession();

  // ACK reader thread: reads ACKs, updates spool.
  void AckReaderLoop(
      grpc::ClientReaderWriter<retrovue::evidence::v1::EvidenceFromAir,
                               retrovue::evidence::v1::EvidenceAckFromCore>* stream);

  std::string target_address_;
  std::string channel_id_;
  std::string playout_session_id_;
  std::shared_ptr<EvidenceSpool> spool_;
  std::shared_ptr<grpc::Channel> grpc_channel_;
  std::unique_ptr<retrovue::evidence::v1::ExecutionEvidenceService::Stub> stub_;

  std::mutex queue_mutex_;
  std::condition_variable queue_cv_;
  std::vector<EvidenceFromAir> send_queue_;

  // Highest sequence emitted (queued) so far.
  std::atomic<uint64_t> last_emitted_{0};
  std::atomic<uint64_t> last_acked_{0};
  std::atomic<bool> shutdown_{false};
  std::atomic<bool> running_{false};

  // Initial ACK from Core after HELLO handshake.
  std::mutex hello_ack_mutex_;
  std::condition_variable hello_ack_cv_;
  bool hello_ack_received_ = false;
  uint64_t hello_ack_sequence_ = 0;

  std::thread connection_thread_;
};

}  // namespace retrovue::evidence
