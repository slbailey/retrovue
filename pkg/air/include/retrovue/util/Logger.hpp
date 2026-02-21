// Repository: Retrovue-playout
// Component: Thread-Safe Logger
// Purpose: Mutex-protected log emission — prevents multi-thread interleave.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_UTIL_LOGGER_HPP_
#define RETROVUE_UTIL_LOGGER_HPP_

#include <functional>
#include <mutex>
#include <string>

namespace retrovue::util {

// Logger provides thread-safe log emission with a single static mutex.
// Each call acquires the mutex, writes the full line, appends '\n', and
// flushes — guaranteeing no interleave between concurrent threads
// (tick loop, fill thread, SeamPreparer worker, gRPC handlers).
//
// Info  → stdout (normal operational logs)
// Debug → stdout only when RETROVUE_DEBUG env is set (verbose investigation)
// Warn  → stderr (degraded but recoverable conditions)
// Error → stderr (violations, bugs, hard faults)
//
// Test-only: SetErrorSink installs a callback invoked for every Error() line
// (in addition to stderr). Used by contract tests to assert violation counts.
class Logger {
 public:
  static void Info(const std::string& line);
  static void Debug(const std::string& line);
  static void Warn(const std::string& line);
  static void Error(const std::string& line);

  // Test-only: set to capture Error() lines (e.g. INV-FENCE-TAKE-READY-001).
  // Call with nullptr to clear.
  static void SetErrorSink(std::function<void(const std::string&)> sink);

 private:
  static std::mutex mutex_;
  static std::function<void(const std::string&)> error_sink_;
};

}  // namespace retrovue::util

#endif  // RETROVUE_UTIL_LOGGER_HPP_
