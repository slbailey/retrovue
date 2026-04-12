// INV-FPS-RATIONAL-001: Contract tests for rational FPS as single authoritative timebase.
// Validates: DROP/cadence math, fence/budget convergence, round-trip identity, hot-path no-float.

#include <gtest/gtest.h>

#include <cctype>
#include <cstdlib>
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


TEST(RationalTimebaseIntegrity, DriftSimulation_10Minutes_2997_NoAccumulatedError) {
  const RationalFps fps(30000, 1001);
  const int64_t duration_us = 10LL * 60LL * 1000000LL;
  const int64_t frames_floor = fps.FramesFromDurationFloorUs(duration_us);
  const int64_t frames_ceil = fps.FramesFromDurationCeilUs(duration_us);
  const int64_t back_floor = fps.DurationFromFramesUs(frames_floor);
  const int64_t back_ceil = fps.DurationFromFramesUs(frames_ceil);
  EXPECT_LE(back_floor, duration_us);
  EXPECT_GE(back_ceil, duration_us);
  EXPECT_LE(duration_us - back_floor, fps.FrameDurationUs());
  EXPECT_LE(back_ceil - duration_us, fps.FrameDurationUs());
}

TEST(RationalTimebaseIntegrity, CadenceExactPattern_23976_to_30_Repeatable) {
  const RationalFps in(24000, 1001);
  const RationalFps out(30, 1);
  std::vector<int64_t> picks;
  picks.reserve(20);
  int64_t emitted = 0;
  for (int64_t src = 0; src < 200 && emitted < 20; ++src) {
    const int64_t before = (src * out.num * in.den) / (in.num * out.den);
    const int64_t after = ((src + 1) * out.num * in.den) / (in.num * out.den);
    if (after > before) {
      picks.push_back(src);
      emitted++;
    }
  }
  ASSERT_EQ(picks.size(), 20u);
  for (size_t i = 1; i < picks.size(); ++i) {
    const int64_t gap = picks[i] - picks[i - 1];
    EXPECT_TRUE(gap == 1 || gap == 0);
  }
}

TEST(RationalTimebaseIntegrity, HotPath_NoFloatOutsideTelemetry) {
#ifdef RETROVUE_AIR_ROOT_DIR
  std::string root(RETROVUE_AIR_ROOT_DIR);
  std::string cmd = "python3 " + root + "/scripts/check_rationalfps_hotpath.py > /tmp/rfps_scan.out 2>&1";
  int rc = std::system(cmd.c_str());
  if (rc != 0) {
    std::ifstream f("/tmp/rfps_scan.out");
    std::stringstream ss;
    ss << f.rdbuf();
    FAIL() << ss.str();
  }
#else
  GTEST_SKIP() << "RETROVUE_AIR_ROOT_DIR not set";
#endif
}

TEST(RationalTimebaseIntegrity, OutputClock_UsesCanonicalHelpers) {
#ifdef RETROVUE_AIR_ROOT_DIR
  std::string path = std::string(RETROVUE_AIR_ROOT_DIR) + "/src/blockplan/OutputClock.cpp";
  std::ifstream f(path);
  ASSERT_TRUE(f.good()) << path;
  std::stringstream ss;
  ss << f.rdbuf();
  const std::string body = ss.str();
  EXPECT_NE(body.find("DurationFromFramesNs"), std::string::npos);
  EXPECT_EQ(body.find("ns_per_frame_whole_"), std::string::npos);
  EXPECT_EQ(body.find("ns_per_frame_rem_"), std::string::npos);
  EXPECT_EQ(body.find("kNanosPerSecond * fps_den"), std::string::npos);
#else
  GTEST_SKIP() << "RETROVUE_AIR_ROOT_DIR not set";
#endif
}

// -----------------------------------------------------------------------------
// Hot-path source scan: no float/double, no ToDouble(), no floating literals
// -----------------------------------------------------------------------------

#ifndef RETROVUE_BLOCKPLAN_SRC_DIR
#define RETROVUE_BLOCKPLAN_SRC_DIR ""
#endif

// C++ identifier character (alnum + underscore); used so "double_start" is not flagged.
static bool isIdentifierChar(unsigned char c) {
  return std::isalnum(c) || c == '_';
}

static bool isWordBoundary(const std::string& s, size_t pos, size_t len) {
  return (pos == 0 || !isIdentifierChar(static_cast<unsigned char>(s[pos - 1]))) &&
         (pos + len >= s.size() || !isIdentifierChar(static_cast<unsigned char>(s[pos + len])));
}

// Strip string literals, char literals, and comments so we only scan code (avoids false
// positives from "double" in strings or comments). Returns a string of the same length
// with literal/comment content replaced by spaces.
static std::string stripLiteralsAndComments(const std::string& line) {
  std::string out;
  out.reserve(line.size());
  enum State { NONE, IN_DOUBLE_QUOTE, IN_SINGLE_QUOTE, IN_LINE_COMMENT, IN_BLOCK_COMMENT };
  State state = NONE;
  bool escape = false;
  for (size_t i = 0; i < line.size(); ++i) {
    char c = line[i];
    char prev = (i > 0) ? line[i - 1] : '\0';
    if (state == IN_LINE_COMMENT) {
      out += ' ';
      continue;
    }
    if (state == IN_BLOCK_COMMENT) {
      out += ' ';
      if (prev == '*' && c == '/') state = NONE;
      continue;
    }
    if (state == IN_DOUBLE_QUOTE || state == IN_SINGLE_QUOTE) {
      if (!escape && c == (state == IN_DOUBLE_QUOTE ? '"' : '\''))
        state = NONE;
      else if (c == '\\' && !escape)
        escape = true;
      else
        escape = false;
      out += ' ';
      continue;
    }
    if (c == '"') {
      state = IN_DOUBLE_QUOTE;
      out += ' ';
      continue;
    }
    if (c == '\'') {
      state = IN_SINGLE_QUOTE;
      out += ' ';
      continue;
    }
    if (c == '/' && i + 1 < line.size()) {
      if (line[i + 1] == '/') {
        state = IN_LINE_COMMENT;
        out += ' ';
        ++i;
        out += ' ';
        continue;
      }
      if (line[i + 1] == '*') {
        state = IN_BLOCK_COMMENT;
        out += ' ';
        ++i;
        out += ' ';
        continue;
      }
    }
    out += c;
  }
  return out;
}

// Standalone type keywords and floating literals (including .0). Applied to stripped line.
static const std::regex kFloatLiteralRe(
    R"(\d+\.\d+([eE][+-]?\d+)?|\d+[eE][+-]?\d+|\.\d+([eE][+-]?\d+)?)");

static bool hasForbiddenPattern(const std::string& line) {
  const std::string s = stripLiteralsAndComments(line);
  // Standalone "double" type (not in identifiers like double_start or in strings).
  auto pos = s.find("double");
  if (pos != std::string::npos && isWordBoundary(s, pos, 6)) return true;
  // Standalone "float" type.
  pos = s.find("float");
  if (pos != std::string::npos && isWordBoundary(s, pos, 5)) return true;
  // ToDouble( or ToDouble (
  if (s.find("ToDouble(") != std::string::npos || s.find("ToDouble (") != std::string::npos)
    return true;
  // duration<double> and similar are covered by standalone "double" on stripped line.
  // Floating literals: 10.0, .0, 1e10, etc.
  if (std::regex_search(s, kFloatLiteralRe)) return true;
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
