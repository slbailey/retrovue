// Repository: Retrovue-playout
// Component: INV-NO-FLOAT-FPS-TIMEBASE-001 contract test
// Purpose: Fail if runtime code (pkg/air/src, pkg/air/include) uses float FPS timebase
//          math (1e6/fps, round(1e6/...)) for frame/tick duration. No behavior change.
// Contract Reference: INV-NO-FLOAT-FPS-TIMEBASE-001.md
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <algorithm>
#include <cstdlib>
#include <fstream>
#include <regex>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

#if __cplusplus >= 201703L
#include <filesystem>
namespace fs = std::filesystem;
#else
#include <experimental/filesystem>
namespace fs = std::experimental::filesystem;
#endif

namespace {

// Strip C++ line comment (// ...) from the end of the line. Does not handle block comments.
std::string StripLineComment(std::string line) {
  auto pos = line.find("//");
  if (pos != std::string::npos) {
    line = line.substr(0, pos);
  }
  return line;
}

// Trim trailing/leading whitespace.
std::string Trim(const std::string& s) {
  auto start = s.find_first_not_of(" \t\r\n");
  if (start == std::string::npos) return "";
  auto end = s.find_last_not_of(" \t\r\n");
  return s.substr(start, end == std::string::npos ? std::string::npos : end - start + 1);
}

// Resolve pkg/air root: prefer RETROVUE_AIR_SOURCE_DIR; else assume cwd is build dir and parent is air root.
fs::path GetAirRoot() {
  const char* env = std::getenv("RETROVUE_AIR_SOURCE_DIR");
  if (env && env[0] != '\0') {
    return fs::path(env);
  }
  fs::path cwd = fs::current_path();
  // When run via ctest from pkg/air/build, cwd is build; parent is pkg/air.
  if (cwd.filename() == "build" || cwd.filename().string() == "build") {
    return cwd.parent_path();
  }
  // Fallback: go up until we find a directory containing both "src" and "include".
  for (fs::path p = cwd; !p.empty() && p != p.root_path(); p = p.parent_path()) {
    if (fs::is_directory(p / "src") && fs::is_directory(p / "include")) {
      return p;
    }
  }
  return cwd;  // last resort
}

// Collect all .cpp, .h, .hpp under dir (recursive).
std::vector<fs::path> CollectSourceFiles(const fs::path& dir) {
  std::vector<fs::path> out;
  if (!fs::is_directory(dir)) return out;
  for (const auto& entry : fs::recursive_directory_iterator(dir, fs::directory_options::skip_permission_denied)) {
    if (!entry.is_regular_file()) continue;
    std::string ext = entry.path().extension().string();
    if (ext == ".cpp" || ext == ".h" || ext == ".hpp") {
      out.push_back(entry.path());
    }
  }
  std::sort(out.begin(), out.end());
  return out;
}

struct Violation {
  fs::path path;
  int line_no;
  std::string line;
  std::string pattern;
};

// Allowlist: (path_string, line_no). Path in forward-slash form relative to air root for portability.
using Allowlist = std::vector<std::pair<std::string, int>>;

bool IsAllowlisted(const Violation& v, const fs::path& air_root, const Allowlist& allowlist) {
  fs::path rel = fs::relative(v.path, air_root);
  std::string key = rel.generic_string();
  for (const auto& a : allowlist) {
    if (a.first == key && a.second == v.line_no) return true;
  }
  return false;
}

}  // namespace

TEST(InvNoFloatFpsTimebase001, NoFloatFpsTimebaseInRuntimeCode) {
  const fs::path air_root = GetAirRoot();
  const fs::path src_dir = air_root / "src";
  const fs::path include_dir = air_root / "include";

  if (!fs::is_directory(src_dir)) {
    GTEST_SKIP() << "Source dir not found: " << src_dir
                 << " (set RETROVUE_AIR_SOURCE_DIR if not running from build dir)";
  }

  std::vector<fs::path> files = CollectSourceFiles(src_dir);
  auto inc_files = CollectSourceFiles(include_dir);
  files.insert(files.end(), inc_files.begin(), inc_files.end());

  // Forbidden: compute frame/tick duration as 1e6/fps or 1'000'000/fps (with fps-related divisor).
  const std::regex re_duration_from_fps(
      "(1'?000'?000|1e6)(\\.0)?\\s*\\/\\s*.*\\b(config_\\.)?(target_)?fps\\b",
      std::regex_constants::icase);
  // Forbidden: round(1e6 or round(1'000'000 ...
  const std::regex re_round_1e6(
      "round\\s*\\(\\s*1('?000'?000|e6)");

  Allowlist allowlist = {
      // Display-only: fps = 1e6/duration for logging (not computing duration from fps).
      {"src/renderer/ProgramOutput.cpp", 497},
      {"src/renderer/ProgramOutput.cpp", 668},
  };

  std::vector<Violation> violations;
  for (const fs::path& file : files) {
    std::ifstream f(file);
    if (!f) continue;
    std::string line;
    int line_no = 0;
    while (std::getline(f, line)) {
      line_no++;
      std::string code = Trim(StripLineComment(line));
      if (code.empty()) continue;
      std::smatch m;
      if (std::regex_search(code, m, re_duration_from_fps)) {
        violations.push_back(
            {file, line_no, line, "1e6/1'000'000 divided by fps (duration-from-float-fps)"});
      } else if (std::regex_search(code, m, re_round_1e6)) {
        violations.push_back(
            {file, line_no, line, "round(1e6/1'000'000 (forbidden tick duration)"});
      }
    }
  }

  std::vector<Violation> not_allowed;
  for (const auto& v : violations) {
    if (!IsAllowlisted(v, air_root, allowlist)) {
      not_allowed.push_back(v);
    }
  }

  if (not_allowed.empty()) {
    return;
  }

  std::ostringstream msg;
  msg << "INV-NO-FLOAT-FPS-TIMEBASE-001: runtime code must not use float FPS timebase (1e6/fps, round(1e6/...)). "
      << "Use RationalFps. Violations:\n";
  for (const auto& v : not_allowed) {
    msg << "  " << fs::relative(v.path, air_root).generic_string() << ":" << v.line_no
        << " [" << v.pattern << "]\n    " << Trim(v.line) << "\n";
  }
  FAIL() << msg.str();
}
