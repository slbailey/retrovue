// Repository: Retrovue-playout
// Component: Log Capture Harness (test-only)
// Purpose: Per-test structured log capture and assertion macros for contract
//          tests. Installs a test sink in SetUp and removes it in TearDown.
//          All captured entries are cleared between tests — isolation is
//          automatic via LogHarnessTest base class.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_TESTS_LOG_HARNESS_H_
#define RETROVUE_TESTS_LOG_HARNESS_H_

#include <algorithm>
#include <mutex>
#include <string>
#include <vector>

#include <gtest/gtest.h>

#include "retrovue/util/Logger.hpp"

namespace retrovue::tests {

// ---------------------------------------------------------------------------
// LogCapture — thread-safe log entry store used by the harness.
// ---------------------------------------------------------------------------
class LogCapture {
 public:
  void Install() {
    Clear();
    retrovue::util::Logger::SetTestSink(
        [this](const retrovue::util::LogEntry& entry) {
          std::lock_guard<std::mutex> lock(mutex_);
          entries_.push_back(entry);
        });
  }

  void Uninstall() {
    retrovue::util::Logger::SetTestSink(nullptr);
  }

  void Clear() {
    std::lock_guard<std::mutex> lock(mutex_);
    entries_.clear();
  }

  // Returns all captured entries (snapshot under lock).
  std::vector<retrovue::util::LogEntry> Entries() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return entries_;
  }

  // Count entries matching invariant_id exactly.
  int CountViolations(const std::string& invariant_id) const {
    std::lock_guard<std::mutex> lock(mutex_);
    int count = 0;
    for (const auto& e : entries_) {
      if (e.invariant_id == invariant_id) {
        ++count;
      }
    }
    return count;
  }

  // True iff at least one entry has invariant_id == id.
  bool HasViolation(const std::string& invariant_id) const {
    return CountViolations(invariant_id) > 0;
  }

  // True iff no entries with a non-empty invariant_id were captured.
  bool NoViolations() const {
    std::lock_guard<std::mutex> lock(mutex_);
    for (const auto& e : entries_) {
      if (!e.invariant_id.empty()) {
        return false;
      }
    }
    return true;
  }

 private:
  mutable std::mutex mutex_;
  std::vector<retrovue::util::LogEntry> entries_;
};

// ---------------------------------------------------------------------------
// LogHarnessTest — mix-in base for GTest fixtures that need log capture.
//
// Usage:
//   class MyTest : public LogHarnessTest { ... };
//
// The harness installs itself in SetUp() and removes itself in TearDown().
// Captured violations are available via log_capture_ or the EXPECT_LOG_*
// macros defined below.
// ---------------------------------------------------------------------------
class LogHarnessTest : public ::testing::Test {
 protected:
  void SetUp() override {
    log_capture_.Install();
  }

  void TearDown() override {
    log_capture_.Uninstall();
    retrovue::util::Logger::ClearCorrelationId();
  }

  LogCapture log_capture_;
};

}  // namespace retrovue::tests

// ---------------------------------------------------------------------------
// Assertion macros — use inside LogHarnessTest fixtures.
// ---------------------------------------------------------------------------

// Assert that at least one structured violation was captured for invariant_id.
#define EXPECT_LOG_VIOLATION(invariant_id) \
  EXPECT_TRUE(log_capture_.HasViolation(invariant_id)) \
      << "Expected violation for " << (invariant_id) << " but none was captured"

// Assert that zero structured violations were captured (any invariant_id).
#define EXPECT_NO_LOG_VIOLATIONS() \
  EXPECT_TRUE(log_capture_.NoViolations()) \
      << "Expected no violations but captured " \
      << log_capture_.Entries().size() << " log entr(ies)"

// Assert exactly N violations were captured for invariant_id.
#define EXPECT_LOG_VIOLATION_COUNT(invariant_id, N) \
  EXPECT_EQ(log_capture_.CountViolations(invariant_id), (N)) \
      << "Expected " << (N) << " violation(s) for " << (invariant_id)

#endif  // RETROVUE_TESTS_LOG_HARNESS_H_
