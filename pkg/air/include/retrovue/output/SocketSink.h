// Repository: Retrovue-playout
// Component: SocketSink
// Purpose: Non-blocking byte consumer with bounded buffer + writer thread.
// Contract: docs/contracts/components/SOCKETSINK_CONTRACT.md
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_OUTPUT_SOCKET_SINK_H_
#define RETROVUE_OUTPUT_SOCKET_SINK_H_

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <functional>
#include <mutex>
#include <queue>
#include <string>
#include <thread>
#include <vector>

namespace retrovue::output {

// Callback invoked when sink is detached due to slow consumer (buffer overflow)
using DetachCallback = std::function<void(const std::string& reason)>;

// Callback invoked when buffer crosses high-water or low-water marks
// state: true = crossed above high-water (throttle), false = dropped below low-water (resume)
using ThrottleCallback = std::function<void(bool throttle_active)>;

// SocketSink is a non-blocking byte consumer that writes to a socket.
//
// Contract: docs/contracts/components/SOCKETSINK_CONTRACT.md
//
// Core Invariants:
//   SS-001: Non-blocking ingress (TryConsumeBytes MUST NOT block)
//   SS-002: Bounded buffer + writer thread for backpressure absorption
//   SS-003: Bounded memory (configurable buffer limit)
//   SS-004: NO PACKET DROPS - overflow triggers slow-consumer detach
//   SS-005: Failure is local (errors don't affect upstream)
//   SS-006: No timing authority (no pacing, just delivery)
//   SS-007: Honest liveness (last_accepted_time_ set only when kernel accepts)
//
// CRITICAL PRECONDITION (INV-SOCKET-NONBLOCK):
//   The fd passed to SocketSink MUST have O_NONBLOCK set.
//   This is NOT optional. Blocking fds violate LAW-OUTPUT-LIVENESS.
//
//   Why: The writer thread uses poll() + send() in a loop. If the fd is
//   blocking, send() will block when the kernel buffer fills, causing the
//   internal buffer to overflow and triggering false slow-consumer detach.
//
//   Enforcement: The CALLER (MpegTSOutputSink) is responsible for setting
//   O_NONBLOCK before constructing SocketSink. A debug assertion in the
//   constructor verifies compliance.
//
// AUTHORITATIVE SINK: This is viewer-facing. Packets are never dropped.
// If buffer overflows, the slow consumer is detached (connection closed).
//
class SocketSink {
 public:
  // Constructs a SocketSink with a connected file descriptor.
  // fd: Connected socket (UDS or TCP). SocketSink TAKES OWNERSHIP and will close it.
  // name: Human-readable name for diagnostics.
  // buffer_capacity: Max bytes to buffer before slow-consumer detach.
  explicit SocketSink(int fd, const std::string& name = "SocketSink",
                      size_t buffer_capacity = 2 * 1024 * 1024);

  ~SocketSink();

  SocketSink(const SocketSink&) = delete;
  SocketSink& operator=(const SocketSink&) = delete;

  // Set callback invoked when sink is detached due to buffer overflow
  void SetDetachCallback(DetachCallback cb) { detach_callback_ = std::move(cb); }

  // Set callback invoked when buffer crosses high/low water marks (for throttling)
  void SetThrottleCallback(ThrottleCallback cb) { throttle_callback_ = std::move(cb); }

  // Configure whether to detach immediately on overflow (default: true)
  // When false, overflow triggers throttle instead of detach
  void SetDetachOnOverflow(bool detach) { detach_on_overflow_ = detach; }

  // Enqueues bytes for delivery. NEVER blocks (SS-001).
  //
  // Returns:
  //   true  = bytes enqueued successfully
  //   false = sink closed OR slow-consumer detach triggered
  //
  // SS-004: If buffer would overflow, triggers detach (closes connection).
  // After detach, all subsequent calls return false.
  bool TryConsumeBytes(const uint8_t* data, size_t len);

  // Blocking variant: waits up to `timeout` for buffer space, then enqueues.
  // Returns false on timeout, close, or detach — never drops data.
  //
  // Safe to call from the AVIO write callback (tick thread).  The writer
  // thread drains the queue independently; no circular dependency exists.
  // On close/detach, drain_cv_ is signalled so this unblocks promptly.
  bool WaitAndConsumeBytes(const uint8_t* data, size_t len,
                           std::chrono::milliseconds timeout);

  // Closes the socket sink. Idempotent.
  // Shuts down and closes the file descriptor.
  void Close();

  // Returns true if sink was detached due to slow consumer (buffer overflow)
  bool IsDetached() const { return detached_.load(std::memory_order_acquire); }

  // =========================================================================
  // DIAGNOSTICS & LIVENESS (INV-HONEST-LIVENESS-METRICS)
  // =========================================================================
  uint64_t GetBytesDelivered() const { return bytes_delivered_.load(std::memory_order_relaxed); }
  uint64_t GetBytesEnqueued() const { return bytes_enqueued_.load(std::memory_order_relaxed); }
  uint64_t GetWriteErrors() const { return write_errors_.load(std::memory_order_relaxed); }
  uint64_t GetOverflowDetachCount() const { return overflow_detach_count_.load(std::memory_order_relaxed); }
  const std::string& GetName() const { return name_; }
  bool IsClosed() const { return closed_.load(std::memory_order_acquire); }

  // LAW-OUTPUT-LIVENESS: Returns time of last successful send() to kernel buffer.
  // This is the ONLY source of truth for DOWNSTREAM liveness detection.
  // NOTE: This does NOT indicate upstream frame availability!
  std::chrono::steady_clock::time_point GetLastAcceptedTime() const {
    std::lock_guard<std::mutex> lock(time_mutex_);
    return last_accepted_time_;
  }

  // =========================================================================
  // BUFFER STATE (for throttling and diagnostics)
  // =========================================================================
  size_t GetCurrentBufferSize() const {
    std::lock_guard<std::mutex> lock(queue_mutex_);
    return current_buffer_size_;
  }
  size_t GetBufferCapacity() const { return buffer_capacity_; }
  bool IsThrottling() const { return throttling_.load(std::memory_order_acquire); }

 private:
  void WriterThreadLoop();
  void DetachSlowConsumer(const std::string& reason);

  int fd_;
  std::string name_;
  size_t buffer_capacity_;
  std::atomic<bool> closed_{false};
  std::atomic<bool> detached_{false};

  // Bounded buffer queue (SS-002, SS-003)
  mutable std::mutex queue_mutex_;
  std::condition_variable queue_cv_;     // writer waits here for data
  std::condition_variable drain_cv_;     // producer waits here for space
  std::queue<std::vector<uint8_t>> packet_queue_;
  size_t current_buffer_size_{0};

  // Writer thread (SS-002)
  std::thread writer_thread_;
  std::atomic<bool> writer_stop_{false};

  // Telemetry counters
  std::atomic<uint64_t> bytes_enqueued_{0};        // Bytes accepted into buffer
  std::atomic<uint64_t> bytes_delivered_{0};       // Bytes accepted by kernel
  std::atomic<uint64_t> write_errors_{0};
  std::atomic<uint64_t> overflow_detach_count_{0}; // Detaches due to slow consumer

  // LAW-OUTPUT-LIVENESS: Honest liveness tracking (SS-007)
  mutable std::mutex time_mutex_;
  std::chrono::steady_clock::time_point last_accepted_time_;

  // Detach callback
  DetachCallback detach_callback_;

  // =========================================================================
  // HIGH-WATER / LOW-WATER THROTTLING
  // =========================================================================
  // Instead of immediately detaching on overflow, throttle writes:
  // - Above high-water (80%): set throttling_, invoke callback
  // - Below low-water (50%): clear throttling_, invoke callback
  // - Detach only if detach_on_overflow_ is true AND buffer is full
  // =========================================================================
  ThrottleCallback throttle_callback_;
  std::atomic<bool> throttling_{false};
  bool detach_on_overflow_{true};  // Legacy behavior by default
  static constexpr double kHighWaterRatio = 0.80;  // 80% of capacity
  static constexpr double kLowWaterRatio = 0.50;   // 50% of capacity
};

}  // namespace retrovue::output

#endif  // RETROVUE_OUTPUT_SOCKET_SINK_H_
