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

// CONTRACT_VIOLATION_PENDING: SS-001, SS-004
// This method blocks on EAGAIN and retries. It exists for migration from
// MpegTSOutputSink::WriteToFdCallback. Once callers migrate to TryConsumeBytes,
// this method should be deleted.
ssize_t SocketSink::BlockingWrite(const uint8_t* data, size_t len) {
  // Moved from MpegTSOutputSink.cpp WriteToFdCallback (lines 766-790)
  // Line-for-line preservation of blocking behavior.

  if (closed_.load(std::memory_order_acquire) || fd_ < 0) {
    return -1;
  }

  if (!data || len == 0) {
    return 0;
  }

#if defined(__linux__) || defined(__APPLE__)
  const uint8_t* p = data;
  size_t remaining = len;

  while (remaining > 0) {
    // CONTRACT_VIOLATION_PENDING: Using blocking send (no MSG_DONTWAIT)
    // Original code used SafeWrite which is send() with MSG_NOSIGNAL on Linux
#if defined(__linux__)
    ssize_t n = send(fd_, p, remaining, MSG_NOSIGNAL);
#else
    ssize_t n = write(fd_, p, remaining);
#endif

    if (n < 0) {
      if (errno == EINTR) {
        continue;  // Interrupted, retry (acceptable)
      }
      if (errno == EAGAIN || errno == EWOULDBLOCK) {
        // CONTRACT_VIOLATION_PENDING: SS-001, SS-004
        // Blocking with sleep-retry loop. This MUST be removed to comply
        // with SS-001 (non-blocking) and SS-004 (no retries).
        std::this_thread::sleep_for(std::chrono::microseconds(100));
        continue;
      }
      // Real error (EPIPE, ECONNRESET, etc.)
      uint64_t error_count = write_errors_.fetch_add(1, std::memory_order_relaxed);
      if ((error_count & 0xFF) == 0) {
        std::cerr << "[SocketSink:" << name_ << "] BlockingWrite error: "
                  << strerror(errno) << " (count=" << error_count + 1 << ")" << std::endl;
      }
      return -1;
    }

    if (n == 0) {
      // Connection closed
      return -1;
    }

    remaining -= static_cast<size_t>(n);
    p += n;
    bytes_written_.fetch_add(static_cast<uint64_t>(n), std::memory_order_relaxed);
  }

  return static_cast<ssize_t>(len);
#else
  (void)data;
  (void)len;
  errno = ENOSYS;
  return -1;
#endif
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
