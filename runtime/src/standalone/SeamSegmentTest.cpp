// Step 5a — Synthetic segment-seam reproduction harness.
//
// Constructs a single FedBlock with N segments of chosen content
// alternating every N seconds, feeds it to PipelineManager, and writes
// the encoder output to a TS file the user can play back.
//
// Purpose:
//   Reproduce the skip-at-seam behavior on demand (every 30 s by
//   default) so SEAM_JUMP / SKIP_DETECT instrumentation can be
//   correlated with perceived playback skip.
//
// Usage:
//   retrovue_seam_segment_test \
//     --segment <path:offset_ms:duration_ms> \
//     --segment <path:offset_ms:duration_ms> \
//     [--segment ...] \
//     --output <ts-file>
//
// Example:
//   retrovue_seam_segment_test \
//     --segment /mnt/data/Interstitials/commercials/1950s/0001.mp4:0:30000 \
//     --segment /mnt/data/Interstitials/commercials/1950s/0002.mp4:0:30000 \
//     --segment /mnt/data/Interstitials/commercials/1950s/0001.mp4:0:30000 \
//     --segment /mnt/data/Interstitials/commercials/1950s/0002.mp4:0:30000 \
//     --output /tmp/seam_loop.ts

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#if defined(__linux__) || defined(__APPLE__)
#include <fcntl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#endif

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/PipelineManager.hpp"

using namespace retrovue::blockplan;

namespace {

struct SegSpec {
  std::string path;
  int64_t offset_ms = 0;
  int64_t duration_ms = 0;
};

bool ParseSegSpec(const std::string& s, SegSpec& out) {
  // Format: path:offset_ms:duration_ms
  // Path may itself contain colons (absolute paths). Split on LAST two
  // colons so offset/duration come from the rightmost fields.
  auto pos2 = s.rfind(':');
  if (pos2 == std::string::npos) return false;
  auto pos1 = s.rfind(':', pos2 - 1);
  if (pos1 == std::string::npos) return false;
  out.path = s.substr(0, pos1);
  try {
    out.offset_ms = std::stoll(s.substr(pos1 + 1, pos2 - pos1 - 1));
    out.duration_ms = std::stoll(s.substr(pos2 + 1));
  } catch (...) {
    return false;
  }
  return out.duration_ms > 0;
}

}  // namespace

int main(int argc, char** argv) {
  std::vector<SegSpec> segs;
  std::string output_path;

  for (int i = 1; i < argc; ++i) {
    std::string arg = argv[i];
    if (arg == "--segment" && i + 1 < argc) {
      SegSpec s;
      if (!ParseSegSpec(argv[++i], s)) {
        std::cerr << "Bad --segment spec: " << argv[i] << "\n";
        return 1;
      }
      segs.push_back(std::move(s));
    } else if (arg == "--output" && i + 1 < argc) {
      output_path = argv[++i];
    } else {
      std::cerr << "Unknown arg: " << arg << "\n";
      return 1;
    }
  }

  if (segs.size() < 2) {
    std::cerr << "Need at least 2 --segment entries to produce a seam\n";
    return 1;
  }
  if (output_path.empty()) {
    std::cerr << "Need --output <ts-file>\n";
    return 1;
  }

  // Verify all asset files exist.
  for (const auto& s : segs) {
    std::ifstream f(s.path);
    if (!f.good()) {
      std::cerr << "Missing asset: " << s.path << "\n";
      return 1;
    }
  }

  // Compute total duration from sum of segment durations.
  int64_t total_duration_ms = 0;
  for (const auto& s : segs) total_duration_ms += s.duration_ms;

  // Output TS bytes are irrelevant for AIR-internal seam investigation —
  // the log is what we analyze. SocketSink's send() errors on a regular
  // fd are harmless; bytes are simply discarded. Route to /dev/null.
  int fd = open("/dev/null", O_WRONLY);
  if (fd < 0) {
    std::perror("/dev/null");
    return 1;
  }
  (void)output_path;  // retained for caller convenience; unused.

  std::cout << "[SeamSegmentTest] segments=" << segs.size()
            << " total_duration_ms=" << total_duration_ms
            << " output=" << output_path << "\n";
  for (size_t i = 0; i < segs.size(); ++i) {
    std::cout << "  seg[" << i << "] " << segs[i].path
              << " offset_ms=" << segs[i].offset_ms
              << " duration_ms=" << segs[i].duration_ms << "\n";
  }

  // Build session context.
  BlockPlanSessionContext ctx;
  ctx.channel_id = 999;
  ctx.fd = fd;
  ctx.width = 640;
  ctx.height = 480;
  ctx.fps = DeriveRationalFPS(29.97);

  // Build FedBlock with all segments.
  // NOTE: start/end_utc_ms must be in REAL wall-clock time — the engine
  // re-anchors fence_epoch_utc_ms_ to NowUtcMs() at clock->Start(), and
  // block_fence_frame_ is computed as (block.end_utc_ms - fence_epoch).
  // Small placeholder values make that delta hugely negative, which
  // clamps the fence to 0 and the block exits after one segment.
  const auto now_ms =
      std::chrono::duration_cast<std::chrono::milliseconds>(
          std::chrono::system_clock::now().time_since_epoch()).count();
  FedBlock block;
  block.block_id = "seam-segment-test";
  block.channel_id = 999;
  block.start_utc_ms = now_ms;
  block.end_utc_ms = now_ms + total_duration_ms;
  for (size_t i = 0; i < segs.size(); ++i) {
    FedBlock::Segment seg;
    seg.segment_index = static_cast<int32_t>(i);
    seg.asset_uri = segs[i].path;
    seg.asset_start_offset_ms = segs[i].offset_ms;
    seg.segment_duration_ms = segs[i].duration_ms;
    block.segments.push_back(seg);
  }

  std::mutex mu;
  std::condition_variable cv;
  bool done = false;

  PipelineManager::Callbacks callbacks;
  callbacks.on_block_completed = [&](const FedBlock&, int64_t, int64_t) {
    std::lock_guard<std::mutex> lock(mu);
    done = true;
    cv.notify_all();
  };
  callbacks.on_session_ended = [&](const std::string&, int64_t) {
    std::lock_guard<std::mutex> lock(mu);
    done = true;
    cv.notify_all();
  };

  {
    std::lock_guard<std::mutex> lock(ctx.queue_mutex);
    ctx.block_queue.push_back(block);
  }

  auto engine = std::make_unique<PipelineManager>(
      &ctx, std::move(callbacks));
  engine->Start();

  // Wait long enough for all segments to play out, with a generous timeout.
  const auto timeout = std::chrono::milliseconds(total_duration_ms + 15000);
  {
    std::unique_lock<std::mutex> lock(mu);
    cv.wait_for(lock, timeout, [&] { return done; });
  }

  engine->Stop();
  close(fd);

  auto metrics = engine->SnapshotMetrics();
  std::cout << "\n[SeamSegmentTest] done."
            << " frames_emitted=" << metrics.continuous_frames_emitted_total
            << " pad_frames=" << metrics.pad_frames_emitted_total
            << " segment_swaps=" << metrics.source_swap_count << "\n";

  return 0;
}
