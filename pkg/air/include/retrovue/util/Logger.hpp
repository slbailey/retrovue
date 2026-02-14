// Repository: Retrovue-playout
// Component: Thread-Safe Logger
// Purpose: Mutex-protected log emission — prevents multi-thread interleave.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_UTIL_LOGGER_HPP_
#define RETROVUE_UTIL_LOGGER_HPP_

#include <mutex>
#include <string>

namespace retrovue::util {

// Logger provides thread-safe log emission with a single static mutex.
// Each call acquires the mutex, writes the full line, appends '\n', and
// flushes — guaranteeing no interleave between concurrent threads
// (tick loop, fill thread, SeamPreparer worker, gRPC handlers).
//
// Info  → stdout (normal operational logs)
// Warn  → stderr (degraded but recoverable conditions)
// Error → stderr (violations, bugs, hard faults)
class Logger {
 public:
  static void Info(const std::string& line);
  static void Warn(const std::string& line);
  static void Error(const std::string& line);

 private:
  static std::mutex mutex_;
};

}  // namespace retrovue::util

#endif  // RETROVUE_UTIL_LOGGER_HPP_
