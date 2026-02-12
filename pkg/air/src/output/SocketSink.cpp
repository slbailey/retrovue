// Repository: Retrovue-playout
// Component: SocketSink Implementation
// Purpose: Non-blocking byte consumer with bounded buffer + writer thread.
// Contract: docs/contracts/components/SOCKETSINK_CONTRACT.md
// Copyright (c) 2025 RetroVue

#include "retrovue/output/SocketSink.h"

#include <cerrno>
#include <cstring>
#include <iostream>

#if defined(__linux__) || defined(__APPLE__)
#include <fcntl.h>
#include <sys/socket.h>
#include <unistd.h>
#include <poll.h>
#endif

#include <cassert>

namespace retrovue::output {

SocketSink::SocketSink(int fd, const std::string& name, size_t buffer_capacity)
    : fd_(fd), name_(name), buffer_capacity_(buffer_capacity) {
  // =========================================================================
  // INV-SOCKET-NONBLOCK: Debug assertion to verify fd is non-blocking.
  // The caller (MpegTSOutputSink) MUST set O_NONBLOCK before constructing.
  // Blocking fds cause send() to block, filling internal buffer, triggering
  // false slow-consumer detach — violating LAW-OUTPUT-LIVENESS.
  // =========================================================================
#ifndef NDEBUG
  {
    int flags = fcntl(fd_, F_GETFL, 0);
    if (flags >= 0 && !(flags & O_NONBLOCK)) {
      std::cerr << "[SocketSink:" << name_ << "] INV-SOCKET-NONBLOCK VIOLATION: "
                << "fd=" << fd_ << " is NOT set to O_NONBLOCK. "
                << "This will cause false slow-consumer detach." << std::endl;
      assert(false && "INV-SOCKET-NONBLOCK: fd must have O_NONBLOCK set");
    }
  }
#endif

  last_accepted_time_ = std::chrono::steady_clock::now();
  writer_thread_ = std::thread(&SocketSink::WriterThreadLoop, this);
}

SocketSink::~SocketSink() {
  Close();
}

void SocketSink::DetachSlowConsumer(const std::string& reason) {
  // Idempotent detach
  bool expected = false;
  if (!detached_.compare_exchange_strong(expected, true, std::memory_order_acq_rel)) {
    return;  // Already detached
  }

  overflow_detach_count_.fetch_add(1, std::memory_order_relaxed);
  std::cerr << "[SocketSink:" << name_ << "] SLOW CONSUMER DETACH: " << reason
            << " (bytes_enqueued=" << bytes_enqueued_.load(std::memory_order_relaxed)
            << ", bytes_delivered=" << bytes_delivered_.load(std::memory_order_relaxed)
            << ", buffer_size=" << current_buffer_size_
            << ", capacity=" << buffer_capacity_
            << ")" << std::endl;

  // Mark closed and stop writer
  closed_.store(true, std::memory_order_release);
  writer_stop_.store(true, std::memory_order_release);
  queue_cv_.notify_all();
  drain_cv_.notify_all();  // Unblock WaitAndConsumeBytes

  // Close FD immediately to unblock writer thread if in poll()
  if (fd_ >= 0) {
    ::shutdown(fd_, SHUT_RDWR);
    ::close(fd_);
    fd_ = -1;
  }

  // Notify callback (if set)
  if (detach_callback_) {
    detach_callback_(reason);
  }
}

bool SocketSink::TryConsumeBytes(const uint8_t* data, size_t len) {
  // SS-001: Non-blocking check
  if (closed_.load(std::memory_order_acquire) ||
      detached_.load(std::memory_order_acquire)) {
    return false;
  }

  if (!data || len == 0) {
    return true;
  }

  std::lock_guard<std::mutex> lock(queue_mutex_);

  // Calculate water marks
  const size_t high_water = static_cast<size_t>(buffer_capacity_ * kHighWaterRatio);
  const size_t low_water = static_cast<size_t>(buffer_capacity_ * kLowWaterRatio);

  // SS-004: Handle buffer overflow
  if (current_buffer_size_ + len > buffer_capacity_) {
    if (detach_on_overflow_) {
      // Legacy behavior: immediate detach
      DetachSlowConsumer("buffer overflow (incoming=" + std::to_string(len) + " bytes)");
      return false;
    } else {
      // New behavior: reject write but don't detach (upstream will throttle)
      // Log at most once per second to avoid spam
      static thread_local int64_t last_overflow_log_ms = 0;
      auto now = std::chrono::steady_clock::now();
      int64_t now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
          now.time_since_epoch()).count();
      if (now_ms - last_overflow_log_ms > 1000) {
        std::cerr << "[SocketSink:" << name_ << "] BUFFER FULL: "
                  << "size=" << current_buffer_size_
                  << " capacity=" << buffer_capacity_
                  << " incoming=" << len
                  << " (write rejected, not detaching)" << std::endl;
        last_overflow_log_ms = now_ms;
      }
      return false;
    }
  }

  // Check for high-water mark crossing (entering throttle)
  bool was_throttling = throttling_.load(std::memory_order_acquire);
  if (!was_throttling && current_buffer_size_ + len >= high_water) {
    throttling_.store(true, std::memory_order_release);
    std::cout << "[SocketSink:" << name_ << "] HIGH-WATER MARK: "
              << "size=" << (current_buffer_size_ + len)
              << " threshold=" << high_water
              << " capacity=" << buffer_capacity_
              << " (throttling ON)" << std::endl;
    if (throttle_callback_) {
      throttle_callback_(true);  // Notify: start throttling
    }
  }

  // Enqueue the packet
  packet_queue_.emplace(data, data + len);
  current_buffer_size_ += len;
  bytes_enqueued_.fetch_add(len, std::memory_order_relaxed);

  // Wake writer thread
  queue_cv_.notify_one();
  return true;
}

bool SocketSink::WaitAndConsumeBytes(const uint8_t* data, size_t len,
                                     std::chrono::milliseconds timeout) {
  if (closed_.load(std::memory_order_acquire) ||
      detached_.load(std::memory_order_acquire)) {
    return false;
  }
  if (!data || len == 0) return true;

  std::unique_lock<std::mutex> lock(queue_mutex_);
  auto deadline = std::chrono::steady_clock::now() + timeout;

  // Block until space is available, or timeout / shutdown.
  while (current_buffer_size_ + len > buffer_capacity_) {
    if (closed_.load(std::memory_order_acquire) ||
        detached_.load(std::memory_order_acquire)) {
      return false;
    }
    if (drain_cv_.wait_until(lock, deadline) == std::cv_status::timeout) {
      return false;
    }
  }

  // Space confirmed — enqueue (same as TryConsumeBytes happy path).
  packet_queue_.emplace(data, data + len);
  current_buffer_size_ += len;
  bytes_enqueued_.fetch_add(len, std::memory_order_relaxed);
  queue_cv_.notify_one();
  return true;
}

void SocketSink::HoldEmission() {
  emission_gate_open_.store(false, std::memory_order_release);
}

void SocketSink::OpenEmissionGate() {
  emission_gate_open_.store(true, std::memory_order_release);
  queue_cv_.notify_all();  // wake writer if parked
}

void SocketSink::WriterThreadLoop() {
  constexpr int kPollTimeoutMs = 100;  // Check for stop every 100ms

  while (!writer_stop_.load(std::memory_order_acquire)) {
    std::vector<uint8_t> packet;

    // Wait for data
    {
      std::unique_lock<std::mutex> lock(queue_mutex_);
      queue_cv_.wait_for(lock, std::chrono::milliseconds(kPollTimeoutMs), [this] {
        return (!packet_queue_.empty() && emission_gate_open_.load(std::memory_order_acquire))
            || writer_stop_.load(std::memory_order_acquire);
      });

      if (writer_stop_.load(std::memory_order_acquire)) break;
      if (packet_queue_.empty()) continue;

      packet = std::move(packet_queue_.front());
      packet_queue_.pop();
      current_buffer_size_ -= packet.size();
    }
    // Space freed — wake any producer blocked in WaitAndConsumeBytes.
    drain_cv_.notify_one();

    // Write to socket
    const uint8_t* ptr = packet.data();
    size_t remaining = packet.size();

    while (remaining > 0 && !writer_stop_.load(std::memory_order_acquire)) {
      // Check if FD is still valid
      if (fd_ < 0) break;

      // Poll for writability with timeout
      struct pollfd pfd;
      pfd.fd = fd_;
      pfd.events = POLLOUT;
      pfd.revents = 0;

      int poll_ret = poll(&pfd, 1, kPollTimeoutMs);
      if (poll_ret < 0) {
        if (errno == EINTR) continue;
        // Poll error
        uint64_t err_count = write_errors_.fetch_add(1, std::memory_order_relaxed);
        if ((err_count & 0xFF) == 0) {
          std::cerr << "[SocketSink:" << name_ << "] poll() error: "
                    << strerror(errno) << std::endl;
        }
        break;
      }

      if (poll_ret == 0) {
        // Timeout - check stop flag and retry
        continue;
      }

      if (pfd.revents & (POLLERR | POLLHUP | POLLNVAL)) {
        // Socket error/hangup - stop
        break;
      }

#if defined(__linux__)
      ssize_t n = send(fd_, ptr, remaining, MSG_NOSIGNAL);
#elif defined(__APPLE__)
      ssize_t n = send(fd_, ptr, remaining, 0);
#else
      ssize_t n = -1;
      errno = ENOSYS;
#endif

      if (n < 0) {
        if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) {
          continue;  // Retry
        }
        // Real error
        uint64_t err_count = write_errors_.fetch_add(1, std::memory_order_relaxed);
        if ((err_count & 0xFF) == 0) {
          std::cerr << "[SocketSink:" << name_ << "] send() error: "
                    << strerror(errno) << std::endl;
        }
        break;
      }

      ptr += n;
      remaining -= static_cast<size_t>(n);

      // INV-HONEST-LIVENESS-METRICS: Update ONLY when kernel accepts bytes
      bytes_delivered_.fetch_add(static_cast<uint64_t>(n), std::memory_order_relaxed);
      {
        std::lock_guard<std::mutex> tlock(time_mutex_);
        last_accepted_time_ = std::chrono::steady_clock::now();
      }
    }

    // Check for low-water mark crossing (exiting throttle)
    {
      std::lock_guard<std::mutex> lock(queue_mutex_);
      const size_t low_water = static_cast<size_t>(buffer_capacity_ * kLowWaterRatio);
      bool was_throttling = throttling_.load(std::memory_order_acquire);
      if (was_throttling && current_buffer_size_ < low_water) {
        throttling_.store(false, std::memory_order_release);
        std::cout << "[SocketSink:" << name_ << "] LOW-WATER MARK: "
                  << "size=" << current_buffer_size_
                  << " threshold=" << low_water
                  << " (throttling OFF)" << std::endl;
        if (throttle_callback_) {
          throttle_callback_(false);  // Notify: stop throttling
        }
      }
    }
  }
}

void SocketSink::Close() {
  // Idempotent close
  bool expected = false;
  if (!closed_.compare_exchange_strong(expected, true, std::memory_order_acq_rel)) {
    return;  // Already closed
  }

  // Signal writer thread to stop
  writer_stop_.store(true, std::memory_order_release);
  queue_cv_.notify_all();
  drain_cv_.notify_all();  // Unblock WaitAndConsumeBytes

  // Wait for writer thread to finish
  if (writer_thread_.joinable()) {
    writer_thread_.join();
  }

  // Actually close the socket FD
  if (fd_ >= 0) {
    ::shutdown(fd_, SHUT_WR);  // Signal EOF to peer
    ::close(fd_);              // Release the FD
    fd_ = -1;
  }
}

}  // namespace retrovue::output
