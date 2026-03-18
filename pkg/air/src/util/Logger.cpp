// Repository: Retrovue-playout
// Component: Thread-Safe Logger
// Purpose: Mutex-protected log emission — prevents multi-thread interleave.
// Copyright (c) 2025 RetroVue

#include "retrovue/util/Logger.hpp"

#include <cstdlib>
#include <iostream>
#include <thread>
#include <unordered_map>

namespace retrovue::util {

std::mutex Logger::mutex_;
std::function<void(const std::string&)> Logger::error_sink_;
std::function<void(const std::string&)> Logger::info_sink_;
std::function<void(const LogEntry&)> Logger::test_sink_;

// ---------------------------------------------------------------------------
// Per-thread correlation ID storage (no mutex needed — thread_local).
// ---------------------------------------------------------------------------
namespace {

thread_local std::string tl_correlation_id;

}  // namespace

void Logger::SetErrorSink(std::function<void(const std::string&)> sink) {
  std::lock_guard<std::mutex> lock(mutex_);
  error_sink_ = std::move(sink);
}

void Logger::SetInfoSink(std::function<void(const std::string&)> sink) {
  std::lock_guard<std::mutex> lock(mutex_);
  info_sink_ = std::move(sink);
}

void Logger::SetTestSink(std::function<void(const LogEntry&)> sink) {
  std::lock_guard<std::mutex> lock(mutex_);
  test_sink_ = std::move(sink);
}

void Logger::SetCorrelationId(std::string id) {
  tl_correlation_id = std::move(id);
}

void Logger::ClearCorrelationId() {
  tl_correlation_id.clear();
}

std::string Logger::CurrentCorrelationId() {
  return tl_correlation_id;
}

void Logger::Info(const std::string& line) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (info_sink_) {
    info_sink_(line);
  }
  std::cout << line << '\n';
  std::cout.flush();
}

void Logger::Debug(const std::string& line) {
  if (std::getenv("RETROVUE_DEBUG") == nullptr) return;
  std::lock_guard<std::mutex> lock(mutex_);
  std::cout << line << '\n';
  std::cout.flush();
}

void Logger::Warn(const std::string& line) {
  std::lock_guard<std::mutex> lock(mutex_);
  std::cerr << line << '\n';
  std::cerr.flush();
}

void Logger::Error(const std::string& line) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (error_sink_) {
    error_sink_(line);
  }
  std::cerr << line << '\n';
  std::cerr.flush();
}

void Logger::ErrorStructured(
    const std::string& message,
    const std::string& invariant_id,
    std::vector<std::pair<std::string, std::string>> fields) {
  // Capture correlation ID before acquiring mutex (thread_local — safe).
  std::string corr_id = CurrentCorrelationId();

  std::lock_guard<std::mutex> lock(mutex_);

  // Always emit the free-text line to stderr and the legacy error sink.
  if (error_sink_) {
    error_sink_(message);
  }
  std::cerr << message << '\n';
  std::cerr.flush();

  // Forward structured entry to the test sink if installed.
  if (test_sink_) {
    LogEntry entry;
    entry.level         = LogEntry::Level::kError;
    entry.message       = message;
    entry.invariant_id  = invariant_id;
    entry.correlation_id = std::move(corr_id);
    entry.fields        = std::move(fields);
    test_sink_(entry);
  }
}

}  // namespace retrovue::util
