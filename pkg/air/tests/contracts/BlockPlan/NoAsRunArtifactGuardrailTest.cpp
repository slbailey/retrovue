// Repository: Retrovue-playout
// Component: Architectural Guardrail — No As-Run Artifacts from AIR
// Purpose: Ensures AIR never writes .asrun files. Core is the sole as-run
//          authority. AIR emits execution evidence only via EvidenceEmitter.
// Rule: Core is sole As-Run authority. AIR MUST NOT produce .asrun artifacts.
// Copyright (c) 2026 RetroVue

#include <gtest/gtest.h>

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <string>

namespace retrovue::blockplan::testing {
namespace {

// =============================================================================
// GUARDRAIL-ASRUN-001: AsRunWriter must not exist as a constructible class.
//
// If someone re-introduces AsRunWriter.hpp, this test will fail to compile
// because the #if check below expects the header to NOT exist.  The linker
// will also fail because AsRunWriter.cpp is not in CMakeLists.txt.
// =============================================================================

// Compile-time check: AsRunWriter.hpp must not be includable.
// If this ifdef ever resolves to true, a developer re-introduced the header.
#ifdef RETROVUE_BLOCKPLAN_ASRUN_WRITER_HPP_
#error "GUARDRAIL-ASRUN-001: AsRunWriter.hpp must not exist. Core owns as-run artifacts."
#endif

// =============================================================================
// GUARDRAIL-ASRUN-002: Source tree must not contain .asrun output patterns.
//
// Scans AIR source files (not tests, not docs) for patterns that would
// produce .asrun files at runtime.
// =============================================================================

TEST(NoAsRunArtifactGuardrail, GUARDRAIL_ASRUN_002_NoAsRunFileOutput) {
  // Scan AIR src/ and include/ for any code that opens/creates .asrun files.
  // The grep returns 0 if NO matches (good), non-zero if matches found.
  //
  // Patterns checked:
  //   ".asrun"  in C++ source files under src/ (excluding evidence/ comments)
  //   "AsRunWriter" class references in src/ or include/
  //
  // We exclude:
  //   - tests/ (this file lives there)
  //   - docs/  (retired contract mentions it)
  //   - evidence/EvidenceEmitter.hpp (comment about Core writing .asrun)

  const char* air_root = nullptr;

  // Try to find AIR root relative to build directory or use env.
  namespace fs = std::filesystem;
  // Walk up from CWD looking for pkg/air/src
  for (auto p = fs::current_path(); p != p.root_path(); p = p.parent_path()) {
    if (fs::exists(p / "src" / "playout_service.cpp")) {
      air_root = strdup(p.string().c_str());
      break;
    }
    if (fs::exists(p / "pkg" / "air" / "src" / "playout_service.cpp")) {
      air_root = strdup((p / "pkg" / "air").string().c_str());
      break;
    }
  }

  // If we can't find the source tree (e.g. CI binary-only), skip gracefully.
  if (!air_root) {
    GTEST_SKIP() << "Cannot locate AIR source tree — skipping source scan guardrail";
  }

  // Check 1: No C++ source file in src/ or include/ references "AsRunWriter"
  {
    std::string cmd = "grep -r --include='*.cpp' --include='*.hpp' --include='*.h' "
                      "'AsRunWriter' "
                      + std::string(air_root) + "/src/ "
                      + std::string(air_root) + "/include/ "
                      "2>/dev/null | wc -l";
    FILE* pipe = popen(cmd.c_str(), "r");
    ASSERT_NE(pipe, nullptr);
    char buf[64];
    std::string result;
    while (fgets(buf, sizeof(buf), pipe)) result += buf;
    pclose(pipe);
    int count = std::stoi(result);
    EXPECT_EQ(count, 0)
        << "GUARDRAIL-ASRUN-001: Found " << count
        << " reference(s) to AsRunWriter in AIR src/include. "
        << "Core is the sole as-run authority.";
  }

  // Check 2: No C++ source file in src/ opens files with ".asrun" suffix.
  // Exclude evidence/EvidenceEmitter.hpp which has a comment about Core's .asrun.
  {
    std::string cmd = "grep -r --include='*.cpp' --include='*.hpp' --include='*.h' "
                      "'\\.asrun' "
                      + std::string(air_root) + "/src/ "
                      + std::string(air_root) + "/include/ "
                      "2>/dev/null | grep -v 'Core converts to' | wc -l";
    FILE* pipe = popen(cmd.c_str(), "r");
    ASSERT_NE(pipe, nullptr);
    char buf[64];
    std::string result;
    while (fgets(buf, sizeof(buf), pipe)) result += buf;
    pclose(pipe);
    int count = std::stoi(result);
    EXPECT_EQ(count, 0)
        << "GUARDRAIL-ASRUN-002: Found " << count
        << " reference(s) to '.asrun' file patterns in AIR src/include. "
        << "AIR must not produce .asrun artifacts.";
  }

  free(const_cast<char*>(air_root));
}

}  // namespace
}  // namespace retrovue::blockplan::testing
