// Repository: Retrovue-playout
// Component: Seam Verify Standalone Harness
// Purpose: P3.2 standalone binary for real-media boundary verification.
//          Queues two blocks through PipelineManager and
//          verifies seamless block transitions via FrameFingerprint and
//          BoundaryReport.
// Contract Reference: PlayoutAuthorityContract.md (P3.2)
// Copyright (c) 2025 RetroVue
//
// Usage:
//   retrovue_air_seam_verify \
//     --block-a <path> --offset-a <ms> --duration-a <ms> \
//     --block-b <path> --offset-b <ms> --duration-b <ms> \
//     [--verbose]

#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <mutex>
#include <string>
#include <vector>

#if defined(__linux__) || defined(__APPLE__)
#include <fcntl.h>
#include <unistd.h>
#endif

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/PipelineManager.hpp"
#include "retrovue/blockplan/SeamProofTypes.hpp"

using namespace retrovue::blockplan;

struct Args {
  std::string block_a_path;
  int64_t offset_a_ms = 0;
  int64_t duration_a_ms = 5000;
  std::string block_b_path;
  int64_t offset_b_ms = 0;
  int64_t duration_b_ms = 5000;
  bool verbose = false;
};

static void PrintUsage(const char* prog) {
  std::cerr << "Usage: " << prog << " \\\n"
            << "  --block-a <path> --offset-a <ms> --duration-a <ms> \\\n"
            << "  --block-b <path> --offset-b <ms> --duration-b <ms> \\\n"
            << "  [--verbose]\n";
}

static bool ParseArgs(int argc, char** argv, Args& args) {
  for (int i = 1; i < argc; i++) {
    std::string arg = argv[i];
    if (arg == "--block-a" && i + 1 < argc) {
      args.block_a_path = argv[++i];
    } else if (arg == "--offset-a" && i + 1 < argc) {
      args.offset_a_ms = std::stoll(argv[++i]);
    } else if (arg == "--duration-a" && i + 1 < argc) {
      args.duration_a_ms = std::stoll(argv[++i]);
    } else if (arg == "--block-b" && i + 1 < argc) {
      args.block_b_path = argv[++i];
    } else if (arg == "--offset-b" && i + 1 < argc) {
      args.offset_b_ms = std::stoll(argv[++i]);
    } else if (arg == "--duration-b" && i + 1 < argc) {
      args.duration_b_ms = std::stoll(argv[++i]);
    } else if (arg == "--verbose") {
      args.verbose = true;
    } else {
      std::cerr << "Unknown argument: " << arg << "\n";
      return false;
    }
  }

  if (args.block_a_path.empty() || args.block_b_path.empty()) {
    std::cerr << "Error: --block-a and --block-b are required\n";
    return false;
  }

  return true;
}

static bool FileExists(const std::string& path) {
  std::ifstream f(path);
  return f.good();
}

static FedBlock MakeBlock(const std::string& block_id,
                           const std::string& uri,
                           int64_t offset_ms,
                           int64_t duration_ms) {
  FedBlock block;
  block.block_id = block_id;
  block.channel_id = 99;
  block.start_utc_ms = 1000000;
  block.end_utc_ms = 1000000 + duration_ms;

  FedBlock::Segment seg;
  seg.segment_index = 0;
  seg.asset_uri = uri;
  seg.asset_start_offset_ms = offset_ms;
  seg.segment_duration_ms = duration_ms;
  block.segments.push_back(seg);

  return block;
}

int main(int argc, char** argv) {
  Args args;
  if (!ParseArgs(argc, argv, args)) {
    PrintUsage(argv[0]);
    return 1;
  }

  // Verify files exist
  if (!FileExists(args.block_a_path)) {
    std::cerr << "Error: Block A file not found: " << args.block_a_path << "\n";
    return 1;
  }
  if (!FileExists(args.block_b_path)) {
    std::cerr << "Error: Block B file not found: " << args.block_b_path << "\n";
    return 1;
  }

  std::cout << "[SeamVerify] Block A: " << args.block_a_path
            << " offset=" << args.offset_a_ms
            << "ms duration=" << args.duration_a_ms << "ms\n";
  std::cout << "[SeamVerify] Block B: " << args.block_b_path
            << " offset=" << args.offset_b_ms
            << "ms duration=" << args.duration_b_ms << "ms\n";

  // Open /dev/null for encoder output
  int fd = -1;
#if defined(__linux__) || defined(__APPLE__)
  fd = open("/dev/null", O_WRONLY);
  if (fd < 0) {
    std::cerr << "Error: Cannot open /dev/null\n";
    return 1;
  }
#endif

  // Create session context
  BlockPlanSessionContext ctx;
  ctx.channel_id = 99;
  ctx.fd = fd;
  ctx.width = 640;
  ctx.height = 480;
  ctx.fps = DeriveRationalFPS(29.97);

  // Tracking state
  std::mutex mu;
  std::condition_variable cv;
  std::vector<std::string> completed_blocks;
  std::vector<int64_t> fence_indices;
  std::vector<FrameFingerprint> fingerprints;
  std::mutex fp_mu;

  PipelineManager::Callbacks callbacks;
  callbacks.on_block_completed = [&](const FedBlock& block, int64_t final_ct_ms, int64_t) {
    std::lock_guard<std::mutex> lock(mu);
    completed_blocks.push_back(block.block_id);
    fence_indices.push_back(final_ct_ms);  // actual content time at fence
    cv.notify_all();
  };
  callbacks.on_session_ended = [&](const std::string& reason, int64_t) {
    std::lock_guard<std::mutex> lock(mu);
    cv.notify_all();
  };
  callbacks.on_frame_emitted = [&](const FrameFingerprint& fp) {
    std::lock_guard<std::mutex> lock(fp_mu);
    fingerprints.push_back(fp);
  };

  // Queue blocks
  FedBlock block_a = MakeBlock("verify-a", args.block_a_path,
                                args.offset_a_ms, args.duration_a_ms);
  FedBlock block_b = MakeBlock("verify-b", args.block_b_path,
                                args.offset_b_ms, args.duration_b_ms);
  {
    std::lock_guard<std::mutex> lock(ctx.queue_mutex);
    ctx.block_queue.push_back(block_a);
    ctx.block_queue.push_back(block_b);
  }

  // Create and start engine
  auto engine = std::make_unique<PipelineManager>(
      &ctx, std::move(callbacks));
  engine->Start();

  // Wait for both blocks to complete (with timeout)
  {
    std::unique_lock<std::mutex> lock(mu);
    bool ok = cv.wait_for(lock, std::chrono::seconds(60),
                           [&] { return completed_blocks.size() >= 2; });
    if (!ok) {
      std::cerr << "[SeamVerify] TIMEOUT waiting for blocks to complete\n";
      engine->Stop();
#if defined(__linux__) || defined(__APPLE__)
      if (fd >= 0) close(fd);
#endif
      return 1;
    }
  }

  engine->Stop();

  // Build boundary report
  std::vector<FrameFingerprint> fps;
  {
    std::lock_guard<std::mutex> lock(fp_mu);
    fps = fingerprints;
  }

  int64_t fence_idx;
  {
    std::lock_guard<std::mutex> lock(mu);
    fence_idx = fence_indices[0] + 1;
  }

  auto report = BuildBoundaryReport(fps, fence_idx, "verify-a", "verify-b");

  std::cout << "\n";
  PrintBoundaryReport(std::cout, report);

  // Print metrics
  auto metrics = engine->SnapshotMetrics();
  std::cout << "\n[SeamVerify] Metrics:\n"
            << "  total_frames=" << metrics.continuous_frames_emitted_total << "\n"
            << "  pad_frames=" << metrics.pad_frames_emitted_total << "\n"
            << "  fence_pad_frames=" << metrics.fence_pad_frames_total << "\n"
            << "  source_swaps=" << metrics.source_swap_count << "\n"
            << "  blocks_executed=" << metrics.total_blocks_executed << "\n";

  // Assertions
  bool pass = true;

  if (report.pad_frames_in_window != 0) {
    std::cerr << "[SeamVerify] FAIL: pad_frames_in_window="
              << report.pad_frames_in_window << " (expected 0)\n";
    pass = false;
  }

  if (!report.head_b.empty()) {
    const auto& first_b = report.head_b[0];
    if (first_b.asset_uri != args.block_b_path) {
      std::cerr << "[SeamVerify] FAIL: first frame of B has asset_uri="
                << first_b.asset_uri << " (expected " << args.block_b_path
                << ")\n";
      pass = false;
    }
  } else {
    std::cerr << "[SeamVerify] FAIL: head_b is empty\n";
    pass = false;
  }

  if (pass) {
    std::cout << "\n[SeamVerify] PASS: Seamless boundary verified\n";
  } else {
    std::cout << "\n[SeamVerify] FAIL: Boundary verification failed\n";
  }

#if defined(__linux__) || defined(__APPLE__)
  if (fd >= 0) close(fd);
#endif

  return pass ? 0 : 1;
}
