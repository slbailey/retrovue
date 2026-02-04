// Repository: Retrovue-playout
// Component: SocketSink Implementation
// Purpose: Non-blocking byte consumer for socket transport.
// Contract: docs/contracts/components/SOCKETSINK_CONTRACT.md
// Copyright (c) 2025 RetroVue

#include "retrovue/output/SocketSink.h"

#include <cerrno>
#include <chrono>
#include <cstring>
#include <iostream>
#include <thread>

#if defined(__linux__) || defined(__APPLE__)
#include <sys/socket.h>
#include <unistd.h>
#endif

namespace retrovue::output {

SocketSink::SocketSink(int fd, const std::string& name)
    : fd_(fd), name_(name) {}

SocketSink::~SocketSink() {
  Close();
}

bool SocketSink::TryConsumeBytes(const uint8_t* data, size_t len) {
  // SS-001: Non-blocking check
  if (closed_.load(std::memory_order_acquire) || fd_ < 0) {
    bytes_dropped_.fetch_add(len, std::memory_order_relaxed);
    return false;
  }

  if (!data || len == 0) {
    return true;  // Nothing to write
  }

#if defined(__linux__)
  // SS-001: Non-blocking send with MSG_DONTWAIT + MSG_NOSIGNAL
  // SS-004: Single attempt, no retries
  ssize_t n = send(fd_, data, len, MSG_DONTWAIT | MSG_NOSIGNAL);
#elif defined(__APPLE__)
  // macOS: MSG_DONTWAIT not available, use SO_NOSIGPIPE on socket instead
  // For now, use send without DONTWAIT (caller should set O_NONBLOCK on fd)
  ssize_t n = send(fd_, data, len, 0);
#else
  ssize_t n = -1;
  errno = ENOSYS;
#endif

  if (n < 0) {
    if (errno == EAGAIN || errno == EWOULDBLOCK) {
      // SS-002: Backpressure absorbed locally by dropping
      bytes_dropped_.fetch_add(len, std::memory_order_relaxed);
      return false;
    }

    if (errno == EINTR) {
      // SS-004: No retries. Treat interrupt as drop.
      bytes_dropped_.fetch_add(len, std::memory_order_relaxed);
      return false;
    }

    // SS-005: Failure is local. Log (rate-limited) and continue.
    // Real errors: EPIPE, ECONNRESET, ENOTCONN, etc.
    uint64_t error_count = write_errors_.fetch_add(1, std::memory_order_relaxed);
    if ((error_count & 0xFF) == 0) {  // Log every 256 errors
      std::cerr << "[SocketSink:" << name_ << "] Write error: "
                << strerror(errno) << " (count=" << error_count + 1 << ")" << std::endl;
    }
    bytes_dropped_.fetch_add(len, std::memory_order_relaxed);
    return false;
  }

  if (static_cast<size_t>(n) < len) {
    // Partial write: accept what was written, drop the rest
    // SS-004: No retries for remainder
    bytes_written_.fetch_add(static_cast<uint64_t>(n), std::memory_order_relaxed);
    bytes_dropped_.fetch_add(len - static_cast<size_t>(n), std::memory_order_relaxed);
    return false;  // Partial = dropped
  }

  // Full write succeeded
  bytes_written_.fetch_add(len, std::memory_order_relaxed);
  return true;
}

void SocketSink::Close() {
  // Idempotent close
  bool expected = false;
  if (!closed_.compare_exchange_strong(expected, true, std::memory_order_acq_rel)) {
    return;  // Already closed
  }

  // Note: We do NOT close fd_ here. Caller owns it.
  // We just mark ourselves as closed so TryConsumeBytes returns false.
  fd_ = -1;
}

}  // namespace retrovue::output
