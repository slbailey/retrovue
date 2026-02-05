// Repository: Retrovue-playout
// Component: Standalone BlockPlan Executor Harness
// Purpose: Test harness that acts as fake Core for diagnostics
// Contract Reference: docs/architecture/proposals/BlockLevelPlayoutAutonomy.md
// Copyright (c) 2025 RetroVue
//
// This binary is for testing and diagnostics only.
// It is NOT the production retrovue_air executable.
// AIR remains unaware it is being run standalone.
//
// MODES OF OPERATION:
// 1. Single-block mode: --block blockplan.json
// 2. Multi-block feeder mode: --seed blockA.json blockB.json --feed blockC.json ...

#include <chrono>
#include <csignal>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <set>
#include <sstream>
#include <string>
#include <vector>

#include "retrovue/blockplan/BlockPlanExecutor.hpp"
#include "retrovue/blockplan/BlockPlanQueue.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/BlockPlanValidator.hpp"
#include "retrovue/blockplan/FeederHarness.hpp"

// Include test infrastructure for FakeClock, FakeAssetSource, RecordingSink
#include "ExecutorTestInfrastructure.hpp"

// Include MpegTsSink for real MPEG-TS output
#include "MpegTsSink.hpp"

namespace {

// =============================================================================
// Global state for signal handling
// =============================================================================
std::atomic<bool> g_termination_requested{false};

void SignalHandler(int signal) {
  if (signal == SIGINT || signal == SIGTERM) {
    std::cerr << "\n[HARNESS] Received signal " << signal << ", requesting termination...\n";
    g_termination_requested.store(true, std::memory_order_release);
  }
}

// =============================================================================
// CLI Arguments
// =============================================================================
struct CliArgs {
  // Single-block mode
  std::string block_json_path;
  int64_t join_utc_ms = -1;  // -1 means use block start

  // Multi-block feeder mode
  std::vector<std::string> seed_paths;  // Exactly 2 for seeding
  std::vector<std::string> feed_paths;  // Additional blocks to feed
  size_t drop_after = 0;  // 0 = unlimited, >0 = stop feeding after N feeds

  // Output options
  std::string output_ts_path;   // Real MPEG-TS file output
  std::string output_csv_path;  // Diagnostic CSV output
  bool diagnostic = false;
  bool help = false;
  bool valid = false;
  std::string error;

  // Mode detection
  bool IsMultiBlockMode() const { return !seed_paths.empty(); }
  bool IsSingleBlockMode() const { return !block_json_path.empty() && seed_paths.empty(); }
};

void PrintUsage(const char* program_name) {
  std::cerr << "Usage: " << program_name << " [OPTIONS]\n"
            << "\n"
            << "Standalone BlockPlan executor harness for testing and diagnostics.\n"
            << "Acts as a fake Core - AIR remains unaware it is being run standalone.\n"
            << "\n"
            << "SINGLE-BLOCK MODE:\n"
            << "  --block PATH         Execute a single BlockPlan JSON file\n"
            << "  --join-utc MS        Join time in milliseconds (default: block start)\n"
            << "\n"
            << "MULTI-BLOCK FEEDER MODE:\n"
            << "  --seed A.json B.json Seed queue with exactly 2 initial blocks\n"
            << "  --feed C.json ...    Additional blocks to feed just-in-time\n"
            << "  --drop-after N       Stop feeding after N feed events (default: unlimited)\n"
            << "\n"
            << "OUTPUT OPTIONS:\n"
            << "  --output-ts PATH     Write REAL MPEG-TS file (playable in ffplay/VLC)\n"
            << "  --output-csv PATH    Write diagnostic CSV (CT, segment, pad, asset, offset)\n"
            << "  --diagnostic         Print human-readable execution timeline to stdout\n"
            << "  --help               Show this help message\n"
            << "\n"
            << "EXAMPLES:\n"
            << "  Single block with diagnostic output:\n"
            << "    " << program_name << " --block blockplan.json --diagnostic\n"
            << "\n"
            << "  Single block with real MPEG-TS output:\n"
            << "    " << program_name << " --block blockplan.json --output-ts /tmp/test.ts\n"
            << "    ffplay /tmp/test.ts\n"
            << "\n"
            << "  Multi-block with continuous feeding:\n"
            << "    " << program_name << " --seed block1.json block2.json \\\n"
            << "                      --feed block3.json block4.json --output-ts /tmp/multi.ts\n"
            << "\n"
            << "  Multi-block with feed limit (simulates feed failure):\n"
            << "    " << program_name << " --seed block1.json block2.json \\\n"
            << "                      --feed block3.json --drop-after 0 --diagnostic\n"
            << "\n";
}

CliArgs ParseArgs(int argc, char* argv[]) {
  CliArgs args;

  for (int i = 1; i < argc; ++i) {
    std::string arg = argv[i];

    if (arg == "--help" || arg == "-h") {
      args.help = true;
      args.valid = true;
      return args;
    } else if (arg == "--block" && i + 1 < argc) {
      args.block_json_path = argv[++i];
    } else if (arg == "--join-utc" && i + 1 < argc) {
      args.join_utc_ms = std::stoll(argv[++i]);
    } else if (arg == "--seed" && i + 2 < argc) {
      // Collect exactly 2 seed blocks
      args.seed_paths.push_back(argv[++i]);
      args.seed_paths.push_back(argv[++i]);
    } else if (arg == "--feed") {
      // Collect all remaining paths until next flag
      while (i + 1 < argc && argv[i + 1][0] != '-') {
        args.feed_paths.push_back(argv[++i]);
      }
    } else if (arg == "--drop-after" && i + 1 < argc) {
      args.drop_after = static_cast<size_t>(std::stoll(argv[++i]));
    } else if (arg == "--output-ts" && i + 1 < argc) {
      args.output_ts_path = argv[++i];
    } else if (arg == "--output-csv" && i + 1 < argc) {
      args.output_csv_path = argv[++i];
    } else if (arg == "--diagnostic") {
      args.diagnostic = true;
    } else {
      args.error = "Unknown argument: " + arg;
      return args;
    }
  }

  // Validate arguments
  if (!args.seed_paths.empty() && args.seed_paths.size() != 2) {
    args.error = "--seed requires exactly 2 block paths";
    return args;
  }

  if (args.block_json_path.empty() && args.seed_paths.empty()) {
    args.error = "Must specify either --block or --seed";
    return args;
  }

  if (!args.block_json_path.empty() && !args.seed_paths.empty()) {
    args.error = "Cannot use both --block and --seed";
    return args;
  }

  args.valid = true;
  return args;
}

// =============================================================================
// Simple JSON Parser for BlockPlan
// Minimal parser - only handles the exact structure we need
// =============================================================================

std::string ReadFile(const std::string& path) {
  std::ifstream file(path);
  if (!file.is_open()) {
    return "";
  }
  std::stringstream buffer;
  buffer << file.rdbuf();
  return buffer.str();
}

// Extract string value from JSON
std::string JsonGetString(const std::string& json, const std::string& key) {
  std::string search = "\"" + key + "\"";
  size_t pos = json.find(search);
  if (pos == std::string::npos) return "";

  pos = json.find(':', pos);
  if (pos == std::string::npos) return "";

  pos = json.find('"', pos);
  if (pos == std::string::npos) return "";

  size_t end = json.find('"', pos + 1);
  if (end == std::string::npos) return "";

  return json.substr(pos + 1, end - pos - 1);
}

// Extract integer value from JSON
int64_t JsonGetInt(const std::string& json, const std::string& key) {
  std::string search = "\"" + key + "\"";
  size_t pos = json.find(search);
  if (pos == std::string::npos) return 0;

  pos = json.find(':', pos);
  if (pos == std::string::npos) return 0;

  // Skip whitespace
  while (pos < json.size() && (json[pos] == ':' || json[pos] == ' ' || json[pos] == '\t')) {
    ++pos;
  }

  // Read number
  std::string num;
  while (pos < json.size() && (isdigit(json[pos]) || json[pos] == '-')) {
    num += json[pos++];
  }

  return num.empty() ? 0 : std::stoll(num);
}

// Segment with optional actual asset duration for underrun testing
struct ParsedSegment {
  retrovue::blockplan::Segment segment;
  int64_t asset_actual_duration_ms;  // 0 = use calculated, >0 = use this value
};

// Parse segments array
std::vector<ParsedSegment> JsonGetSegments(const std::string& json) {
  std::vector<ParsedSegment> segments;

  size_t pos = json.find("\"segments\"");
  if (pos == std::string::npos) return segments;

  pos = json.find('[', pos);
  if (pos == std::string::npos) return segments;

  size_t end = json.find(']', pos);
  if (end == std::string::npos) return segments;

  std::string arr = json.substr(pos, end - pos + 1);

  // Find each segment object
  size_t seg_start = 0;
  while ((seg_start = arr.find('{', seg_start)) != std::string::npos) {
    size_t seg_end = arr.find('}', seg_start);
    if (seg_end == std::string::npos) break;

    std::string seg_json = arr.substr(seg_start, seg_end - seg_start + 1);

    ParsedSegment parsed;
    parsed.segment.segment_index = static_cast<int32_t>(JsonGetInt(seg_json, "segment_index"));
    parsed.segment.asset_uri = JsonGetString(seg_json, "asset_uri");
    parsed.segment.asset_start_offset_ms = JsonGetInt(seg_json, "asset_start_offset_ms");
    parsed.segment.segment_duration_ms = JsonGetInt(seg_json, "segment_duration_ms");
    // Optional: actual asset duration for testing underrun
    parsed.asset_actual_duration_ms = JsonGetInt(seg_json, "asset_actual_duration_ms");

    segments.push_back(parsed);
    seg_start = seg_end + 1;
  }

  return segments;
}

// Parse BlockPlan from JSON (returns parsed segments with optional actual durations)
bool ParseBlockPlan(const std::string& json,
                    retrovue::blockplan::BlockPlan& plan,
                    std::vector<ParsedSegment>& parsed_segments) {
  if (json.empty()) return false;

  plan.block_id = JsonGetString(json, "block_id");
  plan.channel_id = static_cast<int32_t>(JsonGetInt(json, "channel_id"));
  plan.start_utc_ms = JsonGetInt(json, "start_utc_ms");
  plan.end_utc_ms = JsonGetInt(json, "end_utc_ms");

  parsed_segments = JsonGetSegments(json);
  for (const auto& ps : parsed_segments) {
    plan.segments.push_back(ps.segment);
  }

  return !plan.block_id.empty() && !plan.segments.empty();
}

// Load and register assets for a block plan
bool LoadBlockPlan(const std::string& path,
                   retrovue::blockplan::BlockPlan& plan,
                   retrovue::blockplan::testing::FakeAssetSource& assets,
                   bool diagnostic) {
  std::string json = ReadFile(path);
  if (json.empty()) {
    std::cerr << "[HARNESS] Failed to read: " << path << "\n";
    return false;
  }

  std::vector<ParsedSegment> parsed_segments;
  if (!ParseBlockPlan(json, plan, parsed_segments)) {
    std::cerr << "[HARNESS] Failed to parse: " << path << "\n";
    return false;
  }

  // Register fake assets
  for (const auto& ps : parsed_segments) {
    const auto& seg = ps.segment;
    int64_t asset_duration;
    if (ps.asset_actual_duration_ms > 0) {
      asset_duration = ps.asset_actual_duration_ms;
    } else {
      asset_duration = seg.asset_start_offset_ms + seg.segment_duration_ms;
    }

    // Only register if not already registered
    if (!assets.HasAsset(seg.asset_uri)) {
      assets.RegisterSimpleAsset(seg.asset_uri, asset_duration, 33);
      if (diagnostic) {
        std::string note = (ps.asset_actual_duration_ms > 0) ? " [UNDERRUN]" : "";
        std::cerr << "[HARNESS] Registered asset: " << seg.asset_uri
                  << " (duration=" << asset_duration << "ms)" << note << "\n";
      }
    }
  }

  return true;
}

// =============================================================================
// Diagnostic Output
// =============================================================================

void PrintDiagnosticHeader(const retrovue::blockplan::BlockPlan& plan, int64_t join_utc_ms) {
  int64_t duration_ms = plan.end_utc_ms - plan.start_utc_ms;

  std::cout << "\n";
  std::cout << "╔══════════════════════════════════════════════════════════════════════════╗\n";
  std::cout << "║             RETROVUE AIR STANDALONE EXECUTOR HARNESS                     ║\n";
  std::cout << "╠══════════════════════════════════════════════════════════════════════════╣\n";
  std::cout << "║  Block ID:      " << std::setw(57) << std::left << plan.block_id << "║\n";
  std::cout << "║  Channel:       " << std::setw(57) << plan.channel_id << "║\n";
  std::cout << "║  Start UTC:     " << std::setw(57) << plan.start_utc_ms << "║\n";
  std::cout << "║  End UTC:       " << std::setw(57) << plan.end_utc_ms << "║\n";
  std::cout << "║  Duration:      " << std::setw(52) << (duration_ms / 1000) << " sec ║\n";
  std::cout << "║  Segments:      " << std::setw(57) << plan.segments.size() << "║\n";
  std::cout << "║  Join Time:     " << std::setw(57) << join_utc_ms << "║\n";
  std::cout << "╠══════════════════════════════════════════════════════════════════════════╣\n";
  std::cout << "║  SEGMENTS:                                                               ║\n";

  for (const auto& seg : plan.segments) {
    std::cout << "║    [" << seg.segment_index << "] "
              << std::setw(40) << std::left << seg.asset_uri
              << " dur=" << std::setw(6) << seg.segment_duration_ms << "ms"
              << " off=" << std::setw(6) << seg.asset_start_offset_ms << "ms ║\n";
  }

  std::cout << "╚══════════════════════════════════════════════════════════════════════════╝\n";
  std::cout << "\n";
}

void PrintMultiBlockHeader(size_t seed_count, size_t feed_count, size_t drop_after) {
  std::cout << "\n";
  std::cout << "╔══════════════════════════════════════════════════════════════════════════╗\n";
  std::cout << "║         RETROVUE AIR MULTI-BLOCK FEEDER HARNESS                          ║\n";
  std::cout << "╠══════════════════════════════════════════════════════════════════════════╣\n";
  std::cout << "║  Mode:          MULTI-BLOCK FEEDER                                       ║\n";
  std::cout << "║  Seed Blocks:   " << std::setw(57) << std::left << seed_count << "║\n";
  std::cout << "║  Feed Blocks:   " << std::setw(57) << feed_count << "║\n";
  std::cout << "║  Drop After:    " << std::setw(57)
            << (drop_after == 0 ? "unlimited" : std::to_string(drop_after)) << "║\n";
  std::cout << "╚══════════════════════════════════════════════════════════════════════════╝\n";
  std::cout << "\n";
}

void PrintDiagnosticTimeline(
    const std::vector<retrovue::blockplan::testing::EmittedFrame>& frames,
    int64_t total_duration_ms) {

  std::cout << "╔══════════════════════════════════════════════════════════════════════════╗\n";
  std::cout << "║                         EXECUTION TIMELINE                               ║\n";
  std::cout << "╠══════════════════════════════════════════════════════════════════════════╣\n";

  if (frames.empty()) {
    std::cout << "║  (no frames emitted)                                                     ║\n";
    std::cout << "╚══════════════════════════════════════════════════════════════════════════╝\n";
    return;
  }

  // Group by second
  int64_t current_second = -1;
  int32_t last_segment = -1;
  int real_count = 0;
  int pad_count = 0;

  auto print_line = [&](int64_t sec, int32_t seg, int real, int pad, bool transition) {
    std::cout << std::setfill(' ');

    std::ostringstream time_str;
    time_str << std::setw(3) << std::setfill('0') << sec;

    std::ostringstream ct_str;
    ct_str << std::setw(6) << std::setfill('0') << (sec * 1000);

    std::cout << "║  t=" << time_str.str() << "s"
              << " │ CT=" << ct_str.str()
              << " │ SEG=" << seg << " │ ";

    if (pad > 0 && real == 0) {
      std::cout << "░░░ PAD  ";
    } else if (pad > 0) {
      std::cout << "█░░ MIX  ";
    } else {
      std::cout << "███ REAL ";
    }

    std::cout << " │ " << std::setw(3) << (real + pad) << " frames";

    if (transition) {
      std::cout << " ◄── SEGMENT TRANSITION";
    } else if (pad > 0 && real > 0) {
      std::cout << " ◄── UNDERRUN START";
    }

    std::cout << std::setw(8) << "" << "║\n";
  };

  for (const auto& frame : frames) {
    int64_t frame_second = frame.ct_ms / 1000;

    if (frame_second != current_second) {
      if (current_second >= 0) {
        print_line(current_second, last_segment, real_count, pad_count, false);
      }
      current_second = frame_second;
      real_count = 0;
      pad_count = 0;
    }

    if (frame.is_pad) {
      ++pad_count;
    } else {
      ++real_count;
    }

    last_segment = frame.segment_index;
  }

  // Print final second
  if (current_second >= 0) {
    print_line(current_second, last_segment, real_count, pad_count, false);
  }

  std::cout << "╠══════════════════════════════════════════════════════════════════════════╣\n";
  std::cout << "║                        ▓▓▓ EXECUTION COMPLETE ▓▓▓                        ║\n";
  std::cout << "╚══════════════════════════════════════════════════════════════════════════╝\n";
}

void PrintSingleBlockSummary(
    const std::vector<retrovue::blockplan::testing::EmittedFrame>& frames,
    const retrovue::blockplan::testing::ExecutorResult& result,
    int64_t block_duration_ms) {

  std::cout << "\n";
  std::cout << "╔══════════════════════════════════════════════════════════════════════════╗\n";
  std::cout << "║                         EXECUTION SUMMARY                                ║\n";
  std::cout << "╠══════════════════════════════════════════════════════════════════════════╣\n";

  size_t total_frames = frames.size();
  size_t pad_frames = 0;
  size_t real_frames = 0;
  std::set<int32_t> segments_seen;

  for (const auto& f : frames) {
    if (f.is_pad) ++pad_frames;
    else ++real_frames;
    segments_seen.insert(f.segment_index);
  }

  std::cout << "║  Exit Code:     " << std::setw(57) << std::left;
  switch (result.exit_code) {
    case retrovue::blockplan::testing::ExecutorExitCode::kSuccess:
      std::cout << "SUCCESS"; break;
    case retrovue::blockplan::testing::ExecutorExitCode::kAssetError:
      std::cout << "ASSET_ERROR"; break;
    case retrovue::blockplan::testing::ExecutorExitCode::kLookaheadExhausted:
      std::cout << "LOOKAHEAD_EXHAUSTED"; break;
    case retrovue::blockplan::testing::ExecutorExitCode::kTerminated:
      std::cout << "TERMINATED"; break;
  }
  std::cout << "║\n";

  std::cout << "║  Total Frames:  " << std::setw(57) << total_frames << "║\n";
  std::cout << "║  Real Frames:   " << std::setw(57) << real_frames << "║\n";
  std::cout << "║  Pad Frames:    " << std::setw(57) << pad_frames << "║\n";
  std::cout << "║  Segments Used: " << std::setw(57) << segments_seen.size() << "║\n";
  std::cout << "║  Final CT:      " << std::setw(52) << result.final_ct_ms << " ms ║\n";
  std::cout << "║  Block Fence:   " << std::setw(52) << block_duration_ms << " ms ║\n";

  std::cout << "╠══════════════════════════════════════════════════════════════════════════╣\n";
  std::cout << "║  VERIFICATION:                                                           ║\n";

  bool ct_start_ok = !frames.empty();
  std::cout << "║    CT Start:              " << (ct_start_ok ? "✓ PASS" : "✗ FAIL")
            << std::setw(47) << "" << "║\n";

  bool ct_mono_ok = true;
  for (size_t i = 1; i < frames.size(); ++i) {
    if (frames[i].ct_ms <= frames[i-1].ct_ms) {
      ct_mono_ok = false;
      break;
    }
  }
  std::cout << "║    CT Monotonic:          " << (ct_mono_ok ? "✓ PASS" : "✗ FAIL")
            << std::setw(47) << "" << "║\n";

  bool fence_ok = frames.empty() || frames.back().ct_ms < block_duration_ms;
  std::cout << "║    Fence Respected:       " << (fence_ok ? "✓ PASS" : "✗ FAIL")
            << std::setw(47) << "" << "║\n";

  std::cout << "║    Underrun Padding:      " << (pad_frames > 0 ? "✓ PASS (pad frames present)" : "N/A (no underrun)")
            << std::setw(pad_frames > 0 ? 20 : 30) << "" << "║\n";

  std::cout << "╚══════════════════════════════════════════════════════════════════════════╝\n";
}

void PrintMultiBlockSummary(
    const retrovue::blockplan::MultiBlockRunner::RunSummary& summary,
    const std::vector<retrovue::blockplan::testing::EmittedFrame>& frames) {

  std::cout << "\n";
  std::cout << "╔══════════════════════════════════════════════════════════════════════════╗\n";
  std::cout << "║                      MULTI-BLOCK EXECUTION SUMMARY                       ║\n";
  std::cout << "╠══════════════════════════════════════════════════════════════════════════╣\n";

  std::cout << "║  Result:        " << std::setw(57) << std::left;
  switch (summary.result) {
    case retrovue::blockplan::MultiBlockRunner::RunResult::kCompleted:
      std::cout << "COMPLETED"; break;
    case retrovue::blockplan::MultiBlockRunner::RunResult::kLookaheadExhausted:
      std::cout << "LOOKAHEAD_EXHAUSTED"; break;
    case retrovue::blockplan::MultiBlockRunner::RunResult::kAssetError:
      std::cout << "ASSET_ERROR"; break;
    case retrovue::blockplan::MultiBlockRunner::RunResult::kTerminated:
      std::cout << "TERMINATED"; break;
    case retrovue::blockplan::MultiBlockRunner::RunResult::kSeedFailed:
      std::cout << "SEED_FAILED"; break;
  }
  std::cout << "║\n";

  std::cout << "║  Blocks Executed: " << std::setw(55) << summary.blocks_executed << "║\n";
  std::cout << "║  Blocks Fed:      " << std::setw(55) << summary.blocks_fed << "║\n";
  std::cout << "║  Total Frames:    " << std::setw(55) << frames.size() << "║\n";
  std::cout << "║  Final CT:        " << std::setw(50) << summary.final_ct_ms << " ms ║\n";

  if (!summary.error_detail.empty()) {
    std::cout << "║  Error:           " << std::setw(55) << summary.error_detail << "║\n";
  }

  // Verification
  std::cout << "╠══════════════════════════════════════════════════════════════════════════╣\n";
  std::cout << "║  VERIFICATION:                                                           ║\n";

  bool ct_mono_ok = true;
  for (size_t i = 1; i < frames.size(); ++i) {
    if (frames[i].ct_ms <= frames[i-1].ct_ms) {
      ct_mono_ok = false;
      break;
    }
  }
  std::cout << "║    CT Monotonic:          " << (ct_mono_ok ? "✓ PASS" : "✗ FAIL")
            << std::setw(47) << "" << "║\n";

  size_t pad_frames = 0;
  for (const auto& f : frames) {
    if (f.is_pad) ++pad_frames;
  }
  std::cout << "║    No Filler:             " << (pad_frames == 0 ? "✓ PASS (no pad frames)" : "N/A (pad frames present)")
            << std::setw(pad_frames == 0 ? 25 : 22) << "" << "║\n";

  bool exhausted_expected = (summary.result == retrovue::blockplan::MultiBlockRunner::RunResult::kLookaheadExhausted);
  std::cout << "║    Clean Termination:     " << (exhausted_expected ? "✓ PASS (exhausted at fence)" : "N/A")
            << std::setw(exhausted_expected ? 20 : 44) << "" << "║\n";

  std::cout << "╚══════════════════════════════════════════════════════════════════════════╝\n";
}

// =============================================================================
// File Output
// =============================================================================

void WriteOutputFile(
    const std::string& path,
    const std::vector<retrovue::blockplan::testing::EmittedFrame>& frames) {

  std::ofstream file(path);
  if (!file.is_open()) {
    std::cerr << "[HARNESS] Failed to open output file: " << path << "\n";
    return;
  }

  file << "# BlockPlan Executor Diagnostic Output\n";
  file << "# Format: CT_MS,SEGMENT,IS_PAD,ASSET_URI,ASSET_OFFSET\n";
  file << "#\n";

  for (const auto& f : frames) {
    file << f.ct_ms << ","
         << f.segment_index << ","
         << (f.is_pad ? "PAD" : "REAL") << ","
         << f.asset_uri << ","
         << f.asset_offset_ms << "\n";
  }

  file.close();
  std::cerr << "[HARNESS] Wrote " << frames.size() << " frames to " << path << "\n";
}

// =============================================================================
// Single-Block Mode
// =============================================================================

int RunSingleBlockMode(const CliArgs& args) {
  using namespace retrovue::blockplan;
  using namespace retrovue::blockplan::testing;

  std::cerr << "[HARNESS] Loading block plan from: " << args.block_json_path << "\n";

  FakeAssetSource assets;
  BlockPlan plan;

  if (!LoadBlockPlan(args.block_json_path, plan, assets, args.diagnostic)) {
    std::cerr << "Error: Failed to load block plan\n";
    return 1;
  }

  int64_t join_utc_ms = (args.join_utc_ms >= 0) ? args.join_utc_ms : plan.start_utc_ms;

  if (args.diagnostic) {
    PrintDiagnosticHeader(plan, join_utc_ms);
  }

  BlockPlanValidator validator(assets.AsDurationFn());
  auto validation = validator.Validate(plan, join_utc_ms);

  if (!validation.valid) {
    std::cerr << "Error: Block plan validation failed: " << validation.detail << "\n";
    return 1;
  }

  std::cerr << "[HARNESS] Block plan validated successfully\n";

  ValidatedBlockPlan validated{plan, validation.boundaries, join_utc_ms};
  auto join_result = JoinComputer::ComputeJoinParameters(validated, join_utc_ms);

  if (!join_result.valid) {
    std::cerr << "Error: Join computation failed: "
              << BlockPlanErrorToString(join_result.error) << "\n";
    return 1;
  }

  std::cerr << "[HARNESS] Join parameters computed:\n";
  std::cerr << "  Classification: "
            << (join_result.params.classification == JoinClassification::kEarly ? "EARLY" :
                join_result.params.classification == JoinClassification::kMidBlock ? "MID_BLOCK" : "STALE")
            << "\n";
  std::cerr << "  CT Start: " << join_result.params.ct_start_ms << "ms\n";
  std::cerr << "  Start Segment: " << join_result.params.start_segment_index << "\n";

  FakeClock clock;
  clock.SetMs(join_utc_ms);

  RecordingSink sink;
  BlockPlanExecutor executor;

  std::cerr << "[HARNESS] Starting execution...\n";
  auto start_time = std::chrono::steady_clock::now();

  ExecutorResult result = executor.Execute(validated, join_result.params,
                                            &clock, &assets, &sink);

  auto end_time = std::chrono::steady_clock::now();
  auto elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(end_time - start_time).count();

  std::cerr << "[HARNESS] Execution complete in " << elapsed_ms << "ms (simulated time)\n";

  int64_t block_duration_ms = plan.end_utc_ms - plan.start_utc_ms;
  if (args.diagnostic) {
    PrintDiagnosticTimeline(sink.Frames(), block_duration_ms);
    PrintSingleBlockSummary(sink.Frames(), result, block_duration_ms);
  }

  // Write diagnostic CSV if requested
  if (!args.output_csv_path.empty()) {
    WriteOutputFile(args.output_csv_path, sink.Frames());
  }

  // Write real MPEG-TS if requested
  if (!args.output_ts_path.empty()) {
    std::cerr << "[HARNESS] Encoding " << sink.Frames().size() << " frames to MPEG-TS...\n";

    // Determine output resolution (use 640x480 as default, could be made configurable)
    constexpr int kOutputWidth = 640;
    constexpr int kOutputHeight = 480;
    constexpr double kOutputFps = 30.0;

    retrovue::standalone::MpegTsSink ts_sink(args.output_ts_path,
                                              kOutputWidth, kOutputHeight, kOutputFps);
    if (ts_sink.Open()) {
      for (const auto& frame : sink.Frames()) {
        ts_sink.EmitFrame(frame);
      }
      ts_sink.Close();
      std::cerr << "[HARNESS] MPEG-TS output: " << args.output_ts_path << "\n";
      std::cerr << "[HARNESS] Play with: ffplay " << args.output_ts_path << "\n";
    } else {
      std::cerr << "[HARNESS] Failed to create MPEG-TS output\n";
    }
  }

  switch (result.exit_code) {
    case ExecutorExitCode::kSuccess: return 0;
    case ExecutorExitCode::kAssetError: return 2;
    case ExecutorExitCode::kLookaheadExhausted: return 3;
    case ExecutorExitCode::kTerminated: return 4;
  }

  return 0;
}

// =============================================================================
// Multi-Block Feeder Mode
// =============================================================================

int RunMultiBlockMode(const CliArgs& args) {
  using namespace retrovue::blockplan;
  using namespace retrovue::blockplan::testing;

  if (args.diagnostic) {
    PrintMultiBlockHeader(args.seed_paths.size(), args.feed_paths.size(), args.drop_after);
  }

  FakeAssetSource assets;
  BlockPlanQueue queue;

  // Create feeder with diagnostic output
  FeederHarness feeder([&](const std::string& msg) {
    if (args.diagnostic) {
      std::cout << msg << "\n";
    }
  });

  // Set drop limit if specified
  if (args.drop_after > 0) {
    feeder.SetDropAfter(args.drop_after);
    std::cerr << "[HARNESS] Feed limit set to " << args.drop_after << " blocks\n";
  }

  // Load seed blocks
  std::cerr << "[HARNESS] Loading seed blocks...\n";
  for (const auto& path : args.seed_paths) {
    BlockPlan plan;
    if (!LoadBlockPlan(path, plan, assets, args.diagnostic)) {
      std::cerr << "Error: Failed to load seed block: " << path << "\n";
      return 1;
    }
    feeder.AddBlockToSupply(plan);
    std::cerr << "[HARNESS] Added to supply: " << plan.block_id
              << " (" << plan.start_utc_ms << " - " << plan.end_utc_ms << ")\n";
  }

  // Load feed blocks
  if (!args.feed_paths.empty()) {
    std::cerr << "[HARNESS] Loading feed blocks...\n";
    for (const auto& path : args.feed_paths) {
      BlockPlan plan;
      if (!LoadBlockPlan(path, plan, assets, args.diagnostic)) {
        std::cerr << "Error: Failed to load feed block: " << path << "\n";
        return 1;
      }
      feeder.AddBlockToSupply(plan);
      std::cerr << "[HARNESS] Added to supply: " << plan.block_id
                << " (" << plan.start_utc_ms << " - " << plan.end_utc_ms << ")\n";
    }
  }

  std::cerr << "[HARNESS] Total blocks in supply: " << feeder.SupplySize() << "\n";

  FakeClock clock;
  clock.SetMs(0);

  RecordingSink sink;

  // Create runner with diagnostic output
  MultiBlockRunner runner(&feeder, &queue, &clock, &assets,
      [&](const std::string& msg) {
        if (args.diagnostic) {
          std::cout << msg << "\n";
        }
      });

  std::cerr << "[HARNESS] Starting multi-block execution...\n";
  auto start_time = std::chrono::steady_clock::now();

  auto summary = runner.Run(&sink);

  auto end_time = std::chrono::steady_clock::now();
  auto elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(end_time - start_time).count();

  std::cerr << "[HARNESS] Execution complete in " << elapsed_ms << "ms (simulated time)\n";

  if (args.diagnostic) {
    PrintDiagnosticTimeline(sink.Frames(), summary.final_ct_ms);
    PrintMultiBlockSummary(summary, sink.Frames());
  }

  // Write diagnostic CSV if requested
  if (!args.output_csv_path.empty()) {
    WriteOutputFile(args.output_csv_path, sink.Frames());
  }

  // Write real MPEG-TS if requested
  if (!args.output_ts_path.empty()) {
    std::cerr << "[HARNESS] Encoding " << sink.Frames().size() << " frames to MPEG-TS...\n";

    constexpr int kOutputWidth = 640;
    constexpr int kOutputHeight = 480;
    constexpr double kOutputFps = 30.0;

    retrovue::standalone::MpegTsSink ts_sink(args.output_ts_path,
                                              kOutputWidth, kOutputHeight, kOutputFps);
    if (ts_sink.Open()) {
      for (const auto& frame : sink.Frames()) {
        ts_sink.EmitFrame(frame);
      }
      ts_sink.Close();
      std::cerr << "[HARNESS] MPEG-TS output: " << args.output_ts_path << "\n";
      std::cerr << "[HARNESS] Play with: ffplay " << args.output_ts_path << "\n";
    } else {
      std::cerr << "[HARNESS] Failed to create MPEG-TS output\n";
    }
  }

  switch (summary.result) {
    case MultiBlockRunner::RunResult::kCompleted: return 0;
    case MultiBlockRunner::RunResult::kLookaheadExhausted: return 3;
    case MultiBlockRunner::RunResult::kAssetError: return 2;
    case MultiBlockRunner::RunResult::kTerminated: return 4;
    case MultiBlockRunner::RunResult::kSeedFailed: return 5;
  }

  return 0;
}

}  // namespace

// =============================================================================
// Main Entry Point
// =============================================================================

int main(int argc, char* argv[]) {
  // Parse CLI arguments
  CliArgs args = ParseArgs(argc, argv);

  if (args.help) {
    PrintUsage(argv[0]);
    return 0;
  }

  if (!args.valid) {
    std::cerr << "Error: " << args.error << "\n\n";
    PrintUsage(argv[0]);
    return 1;
  }

  // Install signal handlers
  std::signal(SIGINT, SignalHandler);
  std::signal(SIGTERM, SignalHandler);

  // Run appropriate mode
  if (args.IsMultiBlockMode()) {
    return RunMultiBlockMode(args);
  } else {
    return RunSingleBlockMode(args);
  }
}
