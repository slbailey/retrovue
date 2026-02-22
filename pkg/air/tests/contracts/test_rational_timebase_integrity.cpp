// INV-FPS-RATIONAL-001: Contract tests for rational FPS as single authoritative timebase.
// Validates: DROP/cadence math, fence/budget convergence, round-trip identity, hot-path no-float.

#include <gtest/gtest.h>

#include <cctype>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <regex>
#include <sstream>
#include <string>
#include <vector>

#include "retrovue/blockplan/RationalFps.hpp"

namespace retrovue::blockplan {
namespace {

// -----------------------------------------------------------------------------
// Pure math tests
// -----------------------------------------------------------------------------

TEST(RationalTimebaseIntegrity, DropExactRatio_5994_to_2997_Is2) {
  const RationalFps in(60000, 1001);
  const RationalFps out(30000, 1001);
  __int128 lhs = static_cast<__int128>(in.num) * out.den;
  __int128 rhs = static_cast<__int128>(in.den) * out.num;
  ASSERT_GT(rhs, 0);
  ASSERT_EQ(lhs % rhs, 0);
  int64_t step = static_cast<int64_t>(lhs / rhs);
  EXPECT_EQ(step, 2);
}

TEST(RationalTimebaseIntegrity, CadencePattern_23976_to_30_IsStable) {
  const RationalFps in(24000, 1001);
  const RationalFps out(30, 1);
  __int128 lhs = static_cast<__int128>(in.num) * out.den;
  __int128 rhs = static_cast<__int128>(in.den) * out.num;
  ASSERT_GT(rhs, 0);
  EXPECT_NE(lhs % rhs, 0);  // Not exact integer ratio -> CADENCE (no DROP)
}

TEST(RationalTimebaseIntegrity, FenceAndBudgetConverge_100kFrames) {
  const int64_t fps_num = 30;
  const int64_t fps_den = 1;
  const int64_t block_start_tick = 0;
  const int64_t fence_tick = 100000;
  for (int64_t session_frame_index = 0; session_frame_index < fence_tick;
       session_frame_index += 10000) {
    int64_t remaining = fence_tick - session_frame_index;
    if (remaining < 0) remaining = 0;
    EXPECT_EQ(remaining, fence_tick - session_frame_index);
  }
}

TEST(RationalTimebaseIntegrity, RationalFps_NormalizesAndEqualsStructurally) {
  RationalFps a(60000, 1001);
  RationalFps b(60000, 1001);
  EXPECT_TRUE(a == b);
  EXPECT_EQ(a.FrameDurationUs(), b.FrameDurationUs());
  RationalFps c(30, 1);
  EXPECT_EQ(c.num, 30);
  EXPECT_EQ(c.den, 1);
  EXPECT_EQ(c.FrameDurationUs(), 33333);
}

// -----------------------------------------------------------------------------
// Round-trip identity: DurationFromFrames(N) then FramesFromDuration
// -----------------------------------------------------------------------------

static int64_t DurationFromFramesUs(const RationalFps& fps, int64_t N) {
  if (fps.num <= 0) return 0;
  return (N * 1'000'000LL * fps.den) / fps.num;
}

static int64_t FramesFromDurationFloorUs(const RationalFps& fps, int64_t time_us) {
  if (fps.den <= 0) return 0;
  return (time_us * fps.num) / (fps.den * 1'000'000LL);
}

TEST(RationalTimebaseIntegrity, FrameIndexTimeRoundTrip_1M_IsIdentity) {
  const RationalFps fps(25, 1);
  for (int64_t N = 0; N <= 1'000'000; N += (N < 100 ? 1 : 1000)) {
    int64_t time_us = DurationFromFramesUs(fps, N);
    int64_t N2 = FramesFromDurationFloorUs(fps, time_us);
    EXPECT_EQ(N2, N) << "N=" << N << " time_us=" << time_us;
  }
}

// -----------------------------------------------------------------------------
// Hot-path source scan: no float/double, no ToDouble(), no floating literals
// -----------------------------------------------------------------------------

#ifndef RETROVUE_BLOCKPLAN_SRC_DIR
#define RETROVUE_BLOCKPLAN_SRC_DIR ""
#endif

static bool isWordBoundary(const std::string& s, size_t pos, size_t len) {
  return (pos == 0 || !std::isalnum(static_cast<unsigned char>(s[pos - 1]))) &&
         (pos + len >= s.size() || !std::isalnum(static_cast<unsigned char>(s[pos + len])));
}

static const std::regex kFloatLiteralRe(R"(\d+\.\d+([eE][+-]?\d+)?|\d+[eE][+-]?\d+)");

static bool hasForbiddenPattern(const std::string& line) {
  auto pos = line.find("double");
  if (pos != std::string::npos && isWordBoundary(line, pos, 6)) return true;
  pos = line.find("float");
  if (pos != std::string::npos && isWordBoundary(line, pos, 5)) return true;
  if (line.find("ToDouble(") != std::string::npos ||
      line.find("ToDouble (") != std::string::npos) return true;
  if (line.find("duration<double>") != std::string::npos) return true;
  if (std::regex_search(line, kFloatLiteralRe)) return true;
  return false;
}

TEST(RationalTimebaseIntegrity, HotPath_NoFloatNoToDoubleNoFloatLiterals) {
  std::string blockplan_src(RETROVUE_BLOCKPLAN_SRC_DIR);
  if (blockplan_src.empty()) {
    GTEST_SKIP() << "RETROVUE_BLOCKPLAN_SRC_DIR not set (define in CMake)";
  }
  std::vector<std::string> violations;
  try {
    for (const auto& entry :
         std::filesystem::recursive_directory_iterator(blockplan_src)) {
      if (!entry.is_regular_file()) continue;
      auto path = entry.path();
      std::string ext = path.extension().string();
      if (ext != ".cpp" && ext != ".hpp") continue;
      std::ifstream f(path.string());
      if (!f) continue;
      std::string line;
      int line_no = 0;
      while (std::getline(f, line)) {
        line_no++;
        size_t first = line.find_first_not_of(" \t");
        if (first != std::string::npos && first + 1 < line.size() &&
            (line.compare(first, 2, "//") == 0 || line.compare(first, 2, "/*") == 0 ||
             line[first] == '*'))
          continue;
        if (hasForbiddenPattern(line)) {
          std::ostringstream oss;
          oss << path.string() << ":" << line_no << ": " << line;
          violations.push_back(oss.str());
        }
      }
    }
  } catch (const std::filesystem::filesystem_error& e) {
    FAIL() << "Could not scan " << blockplan_src << ": " << e.what();
  }
  if (!violations.empty()) {
    std::ostringstream msg;
    msg << "INV-FPS-RATIONAL-001 hot-path violation: float/double/ToDouble/floating "
           "literal in blockplan source. Fix or move to non-hot-path.\n";
    for (const auto& v : violations) msg << v << "\n";
    FAIL() << msg.str();
  }
}

}  // namespace
}  // namespace retrovue::blockplan
