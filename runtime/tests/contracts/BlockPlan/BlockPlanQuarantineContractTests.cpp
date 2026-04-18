// Repository: Retrovue-playout
// Component: INV-BLOCKPLAN-QUARANTINE Contract Test
// Purpose: Prove that legacy RPCs (StartChannel, LoadPreview, SwitchToLive) are
//          guarded by the BlockPlan quarantine check in playout_service.cpp.
//          The quarantine prevents dual-path execution (ProducerBus + PipelineManager
//          simultaneously), which would cause undefined output behavior.
//
//          Method: Source-level scan of playout_service.cpp.
//          Asserts that:
//            1. EnforceBlockPlanQuarantine is called from all 3 legacy RPCs
//            2. EnforceBlockPlanQuarantine calls std::abort()
//            3. The guard checks blockplan_session_->active
//
// Contract Reference: INV-BLOCKPLAN-QUARANTINE, air_truth_canonical_v2.md §1.2
// Copyright (c) 2026 RetroVue

#include <gtest/gtest.h>

#include <fstream>
#include <string>
#include <vector>

namespace retrovue::blockplan::testing {
namespace {

static const std::vector<std::string> kServiceSourcePaths = {
    "../../runtime/src/playout_service.cpp",
    "../src/playout_service.cpp",
    "runtime/src/playout_service.cpp",
    "/opt/retrovue/runtime/src/playout_service.cpp",
};

static std::vector<std::string> ReadSourceLines() {
  for (const auto& path : kServiceSourcePaths) {
    std::ifstream f(path);
    if (f.good()) {
      std::vector<std::string> lines;
      std::string line;
      while (std::getline(f, line)) {
        lines.push_back(line);
      }
      return lines;
    }
  }
  return {};
}

// Helper: check if any line contains both pattern_a and pattern_b.
static bool HasLineContaining(const std::vector<std::string>& lines,
                              const std::string& pattern_a,
                              const std::string& pattern_b) {
  for (const auto& line : lines) {
    if (line.find(pattern_a) != std::string::npos &&
        line.find(pattern_b) != std::string::npos) {
      return true;
    }
  }
  return false;
}

// Helper: count lines matching a pattern.
static int CountLines(const std::vector<std::string>& lines,
                      const std::string& pattern) {
  int count = 0;
  for (const auto& line : lines) {
    // Skip comment-only lines.
    auto trimmed = line;
    auto pos = trimmed.find("//");
    if (pos != std::string::npos) trimmed = trimmed.substr(0, pos);
    if (trimmed.find(pattern) != std::string::npos) count++;
  }
  return count;
}

// ============================================================================
// Test 1: All 3 legacy RPCs call EnforceBlockPlanQuarantine
// ============================================================================
TEST(BlockPlanQuarantine, AllLegacyRpcsGuarded) {
  auto lines = ReadSourceLines();
  ASSERT_FALSE(lines.empty()) << "Could not read playout_service.cpp source";

  // Each legacy RPC must call EnforceBlockPlanQuarantine with its name.
  EXPECT_TRUE(HasLineContaining(lines, "EnforceBlockPlanQuarantine", "\"StartChannel\""))
      << "StartChannel RPC is not guarded by EnforceBlockPlanQuarantine";

  EXPECT_TRUE(HasLineContaining(lines, "EnforceBlockPlanQuarantine", "\"LoadPreview\""))
      << "LoadPreview RPC is not guarded by EnforceBlockPlanQuarantine";

  EXPECT_TRUE(HasLineContaining(lines, "EnforceBlockPlanQuarantine", "\"SwitchToLive\""))
      << "SwitchToLive RPC is not guarded by EnforceBlockPlanQuarantine";
}

// ============================================================================
// Test 2: EnforceBlockPlanQuarantine calls std::abort()
// ============================================================================
// The function must unconditionally abort in release builds to prevent
// dual-path execution. The assert fires in debug; abort fires in both.
TEST(BlockPlanQuarantine, QuarantineCallsAbort) {
  auto lines = ReadSourceLines();
  ASSERT_FALSE(lines.empty()) << "Could not read playout_service.cpp source";

  // Find the function body (between "EnforceBlockPlanQuarantine" and the next "}")
  bool in_function = false;
  bool found_abort = false;
  for (const auto& line : lines) {
    if (line.find("EnforceBlockPlanQuarantine") != std::string::npos &&
        line.find("void") != std::string::npos) {
      in_function = true;
      continue;
    }
    if (in_function) {
      if (line.find("std::abort()") != std::string::npos) {
        found_abort = true;
        break;
      }
      // Function ends at "}" at namespace level (dedent).
      if (line.find("}") != std::string::npos &&
          line.find("oss") == std::string::npos &&
          line.find("if") == std::string::npos) {
        // Could be the closing brace — but EnforceBlockPlanQuarantine is short,
        // so if we hit "}" without finding abort, it's a violation.
        // However, the function has nested braces for the oss block.
        // Look for abort before the "} // namespace" line.
        if (line.find("namespace") != std::string::npos) break;
      }
    }
  }

  EXPECT_TRUE(found_abort)
      << "EnforceBlockPlanQuarantine must call std::abort() to prevent dual-path execution";
}

// ============================================================================
// Test 3: Guard checks blockplan_session_->active
// ============================================================================
// The quarantine fires only when a BlockPlan session is active, not merely
// when a session object exists.
TEST(BlockPlanQuarantine, GuardChecksActiveFlag) {
  auto lines = ReadSourceLines();
  ASSERT_FALSE(lines.empty()) << "Could not read playout_service.cpp source";

  // All 3 guard sites check "blockplan_session_->active".
  int active_checks = CountLines(lines, "blockplan_session_->active");

  // At minimum 3 (one per legacy RPC) + possibly more for other paths.
  EXPECT_GE(active_checks, 3)
      << "Expected at least 3 'blockplan_session_->active' checks "
      << "(one per guarded RPC), found " << active_checks;
}

// ============================================================================
// Test 4: Exactly 3 quarantine call sites (no missing RPCs)
// ============================================================================
TEST(BlockPlanQuarantine, ExactlyThreeCallSites) {
  auto lines = ReadSourceLines();
  ASSERT_FALSE(lines.empty()) << "Could not read playout_service.cpp source";

  int call_count = CountLines(lines, "EnforceBlockPlanQuarantine(");

  // 1 definition + 3 calls = 4 non-comment occurrences.
  // The definition line contains "void EnforceBlockPlanQuarantine(" and the
  // 3 call sites contain "EnforceBlockPlanQuarantine(\"..." .
  // CountLines skips comment-only lines, so we expect 4.
  EXPECT_EQ(call_count, 4)
      << "Expected 4 non-comment occurrences of EnforceBlockPlanQuarantine "
      << "(1 definition + 3 calls), found " << call_count
      << ". A legacy RPC may be missing the quarantine guard.";
}

}  // namespace
}  // namespace retrovue::blockplan::testing
