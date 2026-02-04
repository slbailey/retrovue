// Repository: Retrovue-playout
// Component: SocketSink
// Purpose: Non-blocking byte consumer for socket transport.
// Contract: docs/contracts/components/SOCKETSINK_CONTRACT.md
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_OUTPUT_SOCKET_SINK_H_
#define RETROVUE_OUTPUT_SOCKET_SINK_H_

#include <atomic>
#include <cstdint>
#include <string>

namespace retrovue::output {

// SocketSink is a non-blocking byte consumer that writes to a socket.
//
// Contract: docs/contracts/components/SOCKETSINK_CONTRACT.md
//
// Core Invariants:
//   SS-001: Non-blocking ingress (TryConsumeBytes MUST NOT block)
//   SS-002: Local backpressure absorption (never propagate upstream)
//   SS-003: Bounded memory (no internal buffering)
//   SS-004: Best-effort delivery (no retries)
//   SS-005: Failure is local (errors don't affect upstream)
//   SS-006: No timing authority (no sleep, no pacing)
//
// SocketSink explicitly does NOT:
//   - Retry failed writes
//   - Sleep or wait on socket readiness
//   - Buffer data internally (zero-copy model)
//   - Interpret CT/PTS or frame semantics
//   - Signal lifecycle changes upstream
//   - Own or manage the file descriptor
//
class SocketSink {
 public:
  // Constructs a SocketSink with a connected file descriptor.
  // fd: Connected socket (UDS or TCP). Caller owns the fd and must keep it valid.
  // name: Human-readable name for diagnostics (optional).
  explicit SocketSink(int fd, const std::string& name = "SocketSink");

  ~SocketSink();

  // Disable copy and move
  SocketSink(const SocketSink&) = delete;
  SocketSink& operator=(const SocketSink&) = delete;

  // Attempts to write bytes to the socket.
  //
  // SS-001: MUST NOT block. Uses MSG_DONTWAIT.
  // SS-002: On EAGAIN/EWOULDBLOCK, increments drop counter and returns false.
  // SS-004: No retries. Single send() attempt.
  // SS-005: On error, logs (rate-limited) and returns false. Does not close.
  //
  // Returns:
  //   true  = bytes accepted (may or may not reach client)
  //   false = bytes dropped (backpressure or error)
  //
  // Note: false is not an error. It indicates the sink absorbed backpressure
  // by dropping. Callers MUST NOT retry or treat this as a failure.
  bool TryConsumeBytes(const uint8_t* data, size_t len);

  // Closes the socket sink. Idempotent.
  // After Close(), TryConsumeBytes() returns false immediately.
  void Close();

  // =========================================================================
  // DIAGNOSTICS ONLY
  // =========================================================================

  uint64_t GetBytesWritten() const { return bytes_written_.load(std::memory_order_relaxed); }
  uint64_t GetBytesDropped() const { return bytes_dropped_.load(std::memory_order_relaxed); }
  uint64_t GetWriteErrors() const { return write_errors_.load(std::memory_order_relaxed); }
  const std::string& GetName() const { return name_; }

 private:
  int fd_;                // Not owned. Caller must keep valid until Close().
  std::string name_;
  std::atomic<bool> closed_{false};

  // Telemetry counters (SS-002, SS-005)
  std::atomic<uint64_t> bytes_written_{0};
  std::atomic<uint64_t> bytes_dropped_{0};
  std::atomic<uint64_t> write_errors_{0};
};

}  // namespace retrovue::output

#endif  // RETROVUE_OUTPUT_SOCKET_SINK_H_
