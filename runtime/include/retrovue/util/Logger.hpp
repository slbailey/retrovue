// Repository: Retrovue-playout
// Component: Thread-Safe Logger
// Purpose: Mutex-protected log emission — prevents multi-thread interleave.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_UTIL_LOGGER_HPP_
#define RETROVUE_UTIL_LOGGER_HPP_

#include <functional>
#include <mutex>
#include <string>
#include <utility>
#include <vector>

namespace retrovue::util {

// LogEntry carries structured data for a single log emission.
// Populated by ErrorStructured() and forwarded to the test sink.
// Production log lines are always emitted as raw strings to stderr/stdout
// (unchanged). Structured fields are additive — they do not replace or
// alter the free-text message.
struct LogEntry {
  enum class Level { kInfo, kDebug, kWarn, kError };

  Level level = Level::kError;

  // Free-text message (same string passed to Error/Info/etc.).
  std::string message;

  // INV-* identifier extracted at call site (empty for non-invariant logs).
  std::string invariant_id;

  // Per-thread correlation ID set by SetCorrelationId(); empty if not set.
  std::string correlation_id;

  // Additional structured context key=value pairs (e.g. tick, channel_id).
  std::vector<std::pair<std::string, std::string>> fields;
};

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

  // Structured invariant violation emission.
  // Emits the free-text message via Error() AND forwards a populated LogEntry
  // to the test sink (if set). invariant_id should be the canonical tag
  // (e.g. "INV-CONTINUOUS-FRAME-AUTHORITY-001-VIOLATED").
  static void ErrorStructured(
      const std::string& message,
      const std::string& invariant_id,
      std::vector<std::pair<std::string, std::string>> fields = {});

  // Test-only: set to capture Error() lines (e.g. INV-FENCE-TAKE-READY-001).
  // Call with nullptr to clear.
  static void SetErrorSink(std::function<void(const std::string&)> sink);

  // Test-only: set to capture Info() lines for instrumentation analysis.
  // Call with nullptr to clear.
  static void SetInfoSink(std::function<void(const std::string&)> sink);

  // Test-only: structured sink — receives a LogEntry for every
  // ErrorStructured() call. Set with nullptr to clear.
  static void SetTestSink(std::function<void(const LogEntry&)> sink);

  // Test-only: set a per-thread correlation ID carried on every subsequent
  // structured log entry emitted from this thread. Pass empty string to clear.
  static void SetCorrelationId(std::string id);
  static void ClearCorrelationId();

 private:
  static std::mutex mutex_;
  static std::function<void(const std::string&)> error_sink_;
  static std::function<void(const std::string&)> info_sink_;
  static std::function<void(const LogEntry&)> test_sink_;

  // Returns the current thread's correlation ID (empty string if none set).
  static std::string CurrentCorrelationId();
};

}  // namespace retrovue::util

#endif  // RETROVUE_UTIL_LOGGER_HPP_
