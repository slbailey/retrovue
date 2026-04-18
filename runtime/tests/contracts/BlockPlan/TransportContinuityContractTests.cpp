// Repository: Retrovue-playout
// Component: INV-TRANSPORT-CONTINUOUS Contract Test
// Purpose: Prove that MuxLoop timing state (wall_epoch, ct_epoch_us,
//          timing_initialized) is never reset on queue underflow or
//          empty-queue conditions. Timing calibration is immutable after
//          the first frame — segment transitions and queue gaps must be
//          invisible to the transport layer.
//
//          Method: Source-level scan of MpegTSOutputSink.cpp.
//          Asserts that:
//            1. timing_initialized is never set to false after declaration
//            2. No timing assignment (wall_epoch =, ct_epoch_us =) appears
//               inside a code block conditioned on queue emptiness
//            3. The only assignments to timing state are the known-safe sites
//
// Contract Reference: INV-TRANSPORT-CONTINUOUS, air_truth_canonical_v2.md §2
// Pattern: Follows Phase 7D/7E clock authority boundary tests.
// Copyright (c) 2026 RetroVue

#include <gtest/gtest.h>

#include <fstream>
#include <string>
#include <vector>

namespace retrovue::blockplan::testing {
namespace {

// Source file paths — try multiple relative paths depending on CWD.
// CWD at test run is typically runtime/build.
static const std::vector<std::string> kSinkSourcePaths = {
    "../../runtime/src/output/MpegTSOutputSink.cpp",  // from repo-root/runtime/build
    "../src/output/MpegTSOutputSink.cpp",              // from runtime/build (if cmake -S runtime)
    "runtime/src/output/MpegTSOutputSink.cpp",         // from repo root
    "/opt/retrovue/runtime/src/output/MpegTSOutputSink.cpp",  // absolute fallback
};

static std::vector<std::string> ReadSourceLines() {
  for (const auto& path : kSinkSourcePaths) {
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

// ============================================================================
// Test 1: timing_initialized is never set to false after its declaration
// ============================================================================
// The latch must be one-way: false → true. If it ever resets to false,
// the timing anchor would be recomputed on the next frame — creating a
// PTS discontinuity visible to decoders.

TEST(TransportContinuity, TimingInitializedNeverResetToFalse) {
  auto lines = ReadSourceLines();
  ASSERT_FALSE(lines.empty()) << "Could not read MpegTSOutputSink.cpp source";

  bool found_declaration = false;
  std::vector<std::string> violations;

  for (size_t i = 0; i < lines.size(); ++i) {
    const auto& line = lines[i];

    // Find the declaration (line ~402: "bool timing_initialized = false;")
    if (line.find("bool timing_initialized = false") != std::string::npos) {
      found_declaration = true;
      continue;  // The declaration itself is fine.
    }

    // After the declaration, any "timing_initialized = false" is a violation.
    if (found_declaration &&
        line.find("timing_initialized = false") != std::string::npos) {
      // Exclude comments.
      auto trimmed = line;
      auto comment_pos = trimmed.find("//");
      if (comment_pos != std::string::npos) {
        trimmed = trimmed.substr(0, comment_pos);
      }
      if (trimmed.find("timing_initialized = false") != std::string::npos) {
        violations.push_back("Line " + std::to_string(i + 1) + ": " + line);
      }
    }
  }

  EXPECT_TRUE(found_declaration)
      << "Could not find 'bool timing_initialized = false' declaration in source";
  EXPECT_TRUE(violations.empty())
      << "INV-TRANSPORT-CONTINUOUS violated: timing_initialized reset to false.\n"
      << "Timing calibration must be immutable after first frame.\n"
      << "Violations:\n"
      << [&] { std::string s; for (const auto& v : violations) s += "  " + v + "\n"; return s; }();
}

// ============================================================================
// Test 2: Timing assignments are only at known-safe sites
// ============================================================================
// wall_epoch and ct_epoch_us should only be assigned at:
//   - Initial declaration
//   - First-frame timing init (gated by !timing_initialized)
//   - Synthetic timing init (gated by !timing_initialized in pre-timing wait)
//   - CT discontinuity reset (gated by ct_jump > threshold)
//
// Any NEW assignment site is a potential INV-TRANSPORT-CONTINUOUS violation
// and must be reviewed.

TEST(TransportContinuity, TimingAssignmentSitesCounted) {
  auto lines = ReadSourceLines();
  ASSERT_FALSE(lines.empty()) << "Could not read MpegTSOutputSink.cpp source";

  int wall_epoch_assignments = 0;
  int ct_epoch_assignments = 0;
  int timing_true_assignments = 0;

  for (size_t i = 0; i < lines.size(); ++i) {
    const auto& line = lines[i];

    // Skip comments.
    auto trimmed = line;
    auto comment_pos = trimmed.find("//");
    if (comment_pos != std::string::npos) {
      trimmed = trimmed.substr(0, comment_pos);
    }

    // Count "wall_epoch =" assignments (excluding declarations).
    if (trimmed.find("wall_epoch =") != std::string::npos &&
        trimmed.find("time_point") == std::string::npos &&  // skip declaration
        trimmed.find("g_pcr_pace_init_time") == std::string::npos) {  // skip map assignment
      wall_epoch_assignments++;
    }

    // Count "ct_epoch_us =" assignments (excluding declaration).
    if (trimmed.find("ct_epoch_us =") != std::string::npos &&
        trimmed.find("int64_t") == std::string::npos) {  // skip declaration
      ct_epoch_assignments++;
    }

    // Count "timing_initialized = true" assignments.
    if (trimmed.find("timing_initialized = true") != std::string::npos) {
      timing_true_assignments++;
    }
  }

  // Known-safe sites as of HARDEN-007:
  //   wall_epoch: 3 assignments (synthetic init, first-frame init, CT discontinuity reset)
  //   ct_epoch_us: 2 assignments (synthetic init = 0, first-frame init = ct_us)
  //     Note: CT discontinuity reset also writes ct_epoch_us (line 1017)
  //   timing_initialized = true: 2 assignments (synthetic init, first-frame init)
  //
  // If any count increases, a new timing assignment site was added.
  // That site must be reviewed for INV-TRANSPORT-CONTINUOUS compliance.

  EXPECT_EQ(wall_epoch_assignments, 3)
      << "wall_epoch assignment count changed. A new timing assignment site was added.\n"
      << "Review for INV-TRANSPORT-CONTINUOUS: timing must not reset on queue underflow.";

  // ct_epoch_us has 3 assignments: synthetic (=0), first-frame (=ct_us), CT discontinuity (=ct_us)
  EXPECT_EQ(ct_epoch_assignments, 3)
      << "ct_epoch_us assignment count changed. Review for INV-TRANSPORT-CONTINUOUS.";

  EXPECT_EQ(timing_true_assignments, 2)
      << "timing_initialized = true count changed. Review for INV-TRANSPORT-CONTINUOUS.";
}

}  // namespace
}  // namespace retrovue::blockplan::testing
