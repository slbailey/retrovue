// Repository: Retrovue-playout
// Component: INV-LAST-SEGMENT-BLOCK-BOUNDARY-001 Contract Test
// Purpose: Prove that when the last segment in a block ends before block_fence_frame_,
//          the seam type is classified as kBlock (not kSegment), allowing the block
//          fence / PADDED_GAP path to fire and transition to the next block.
//
//          TRIGGER: When block.start_utc_ms > fence_epoch_utc_ms_ (common in JIP
//          and multi-block sessions), block_fence_frame_ includes extra frames
//          for the epoch→block-start gap.  planned_segment_seam_frames_ does NOT.
//          After PerformSegmentSwap rebases the last segment's end, computed equals
//          the planned seam (not the fence), so computed < block_fence_frame_.
//
//          BUG (before fix): PerformSegmentSwap sets kSegment because
//          computed < block_fence_frame_. The segment swap handler finds no segment
//          to swap to (to_seg out of bounds), defers forever, and the system never
//          transitions to block B.
//
//          FIX: PerformSegmentSwap checks is_last_segment and forces kBlock.
//
// Contract: docs/contracts/invariants/air/INV-LAST-SEGMENT-BLOCK-BOUNDARY-001.md
// Related:  ADR-013 (Seam Resolution Model)
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <fstream>
#include <memory>
#include <mutex>
#include <string>
#include <sys/socket.h>
#include <thread>
#include <unistd.h>
#include <vector>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/PipelineManager.hpp"
#include "retrovue/blockplan/PipelineMetrics.hpp"
#include "retrovue/blockplan/RationalFps.hpp"
#include "retrovue/util/Logger.hpp"
#include "deterministic_tick_driver.hpp"
#include "FastTestConfig.hpp"

using retrovue::util::Logger;

namespace retrovue::blockplan::testing {
namespace {

static const std::string kPathA = "/opt/retrovue/assets/SampleA.mp4";
static const std::string kPathB = "/opt/retrovue/assets/SampleB.mp4";

static bool FileExists(const std::string& path) {
  std::ifstream f(path);
  return f.good();
}

// Epoch delta: the ms offset between fence_epoch_utc_ms_ and block.start_utc_ms.
//
// In production this offset arises naturally: fence_epoch is anchored to
// wall-clock at session start, while block timestamps come from Core.
// JIP, bootstrap delay, and multi-block sessions all produce positive deltas.
//
// At 30fps, kEpochDeltaMs=5000 creates a 150-frame gap:
//   fence = ceil((5000 + 10000) * 30 / 1000) = 450
//   planned_seam[last] = ceil(10000 * 30 / 1000)     = 300
//   PerformSegmentSwap rebase: ~150 + 150 = ~300 < 450 → kSegment (BUG)
//
// The large delta ensures that even if the swap is deferred by a few ticks
// (decoder I/O latency), the rebase still produces computed < fence.
static constexpr int64_t kEpochDeltaMs = 5000;

// Build a two-CONTENT-segment block.  Segments sum to block duration
// (passes BlockPlanValidator).  The block's start_utc_ms is offset from
// the test time source's epoch by kEpochDeltaMs, creating the fence gap
// that triggers the bug.
static FedBlock MakeTwoSegmentBlock(const std::string& block_id,
                                    int64_t epoch_ms,
                                    int64_t seg0_ms,
                                    int64_t seg1_ms) {
  FedBlock block;
  block.block_id = block_id;
  block.channel_id = 99;
  // Offset block start from epoch — this is the trigger.
  block.start_utc_ms = epoch_ms + kEpochDeltaMs;
  block.end_utc_ms = block.start_utc_ms + seg0_ms + seg1_ms;

  FedBlock::Segment s0;
  s0.segment_index = 0;
  s0.asset_uri = kPathA;
  s0.asset_start_offset_ms = 0;
  s0.segment_duration_ms = seg0_ms;
  s0.segment_type = SegmentType::kContent;
  block.segments.push_back(s0);

  FedBlock::Segment s1;
  s1.segment_index = 1;
  s1.asset_uri = kPathB;
  s1.asset_start_offset_ms = 0;
  s1.segment_duration_ms = seg1_ms;
  s1.segment_type = SegmentType::kContent;
  block.segments.push_back(s1);

  return block;
}

// Build a simple single-segment block for block B.
static FedBlock MakeSingleSegmentBlock(const std::string& block_id,
                                       int64_t start_utc_ms,
                                       int64_t duration_ms) {
  FedBlock block;
  block.block_id = block_id;
  block.channel_id = 99;
  block.start_utc_ms = start_utc_ms;
  block.end_utc_ms = start_utc_ms + duration_ms;

  FedBlock::Segment s0;
  s0.segment_index = 0;
  s0.asset_uri = kPathA;
  s0.asset_start_offset_ms = 0;
  s0.segment_duration_ms = duration_ms;
  s0.segment_type = SegmentType::kContent;
  block.segments.push_back(s0);

  return block;
}

class LastSegmentBlockBoundaryTest : public ::testing::Test {
 protected:
  void SetUp() override {
    ctx_ = std::make_unique<BlockPlanSessionContext>();
    ctx_->channel_id = 99;
    int fds[2];
    ASSERT_EQ(socketpair(AF_UNIX, SOCK_STREAM, 0, fds), 0);
    ctx_->fd = fds[0];
    drain_fd_ = fds[1];
    drain_stop_.store(false);
    drain_thread_ = std::thread([this] {
      char buf[8192];
      while (!drain_stop_.load(std::memory_order_relaxed)) {
        ssize_t n = read(drain_fd_, buf, sizeof(buf));
        if (n <= 0) break;
      }
    });
    ctx_->width = 640;
    ctx_->height = 480;
    ctx_->fps = FPS_30;
    test_ts_ = test_infra::MakeTestTimeSource();

    // Capture log lines for diagnostic analysis.
    captured_logs_.clear();
    Logger::SetInfoSink([this](const std::string& line) {
      std::lock_guard<std::mutex> lock(log_mutex_);
      captured_logs_.push_back(line);
    });
  }

  void TearDown() override {
    Logger::SetInfoSink(nullptr);
    if (engine_) {
      engine_->Stop();
      engine_.reset();
    }
    if (ctx_ && ctx_->fd >= 0) {
      close(ctx_->fd);
      ctx_->fd = -1;
    }
    drain_stop_.store(true);
    if (drain_fd_ >= 0) {
      shutdown(drain_fd_, SHUT_RDWR);
      close(drain_fd_);
      drain_fd_ = -1;
    }
    if (drain_thread_.joinable()) drain_thread_.join();
  }

  std::unique_ptr<PipelineManager> MakeEngine() {
    PipelineManager::Callbacks callbacks;
    callbacks.on_block_completed = [this](const FedBlock& block, int64_t, int64_t) {
      std::lock_guard<std::mutex> lock(block_mutex_);
      completed_blocks_.push_back(block.block_id);
      block_cv_.notify_all();
    };
    callbacks.on_block_started = [this](const FedBlock& block,
                                        const BlockActivationContext&) {
      std::lock_guard<std::mutex> lock(block_mutex_);
      started_blocks_.push_back(block.block_id);
      block_cv_.notify_all();
    };
    callbacks.on_session_ended = [](const std::string&, int64_t) {};
    callbacks.on_segment_start = [this](int32_t from_seg, int32_t to_seg,
                                        const FedBlock& block, int64_t tick) {
      std::lock_guard<std::mutex> lock(seg_mutex_);
      segment_starts_.push_back({to_seg, block.block_id, tick});
    };
    return std::make_unique<PipelineManager>(
        ctx_.get(), std::move(callbacks), test_ts_,
        test_infra::MakeTestOutputClock(ctx_->fps.num, ctx_->fps.den, test_ts_),
        PipelineManagerOptions{0});
  }

  int64_t NowMs() { return test_ts_->NowUtcMs(); }

  // Wait for block B to start (on_block_started fires with block B's ID).
  bool WaitForBlockBStarted(const std::string& block_b_id, int timeout_ms) {
    auto deadline = std::chrono::steady_clock::now() +
                    std::chrono::milliseconds(timeout_ms);
    std::unique_lock<std::mutex> lock(block_mutex_);
    return block_cv_.wait_until(lock, deadline, [&] {
      for (const auto& id : started_blocks_) {
        if (id == block_b_id) return true;
      }
      return false;
    });
  }

  // Check if SEGMENT_SWAP_DEFERRED reason=no_incoming appeared in logs.
  bool HasPermanentDeferral() const {
    std::lock_guard<std::mutex> lock(log_mutex_);
    for (const auto& line : captured_logs_) {
      if (line.find("SEGMENT_SWAP_DEFERRED") != std::string::npos &&
          line.find("reason=no_incoming") != std::string::npos) {
        return true;
      }
    }
    return false;
  }

  std::shared_ptr<test_infra::TestTimeSourceType> test_ts_;
  std::unique_ptr<BlockPlanSessionContext> ctx_;
  std::unique_ptr<PipelineManager> engine_;
  int drain_fd_ = -1;
  std::atomic<bool> drain_stop_{false};
  std::thread drain_thread_;

  mutable std::mutex log_mutex_;
  std::vector<std::string> captured_logs_;

  mutable std::mutex block_mutex_;
  std::condition_variable block_cv_;
  std::vector<std::string> completed_blocks_;
  std::vector<std::string> started_blocks_;

  struct SegmentStart {
    int32_t to_seg;
    std::string block_id;
    int64_t tick;
  };
  mutable std::mutex seg_mutex_;
  std::vector<SegmentStart> segment_starts_;
};

// ===========================================================================
// INV-LAST-SEGMENT-BLOCK-BOUNDARY-001
//
// Block A: [CONTENT(5000ms), CONTENT(5000ms)]
//   segment_sum = 10000ms = block_duration (validator passes).
//   block.start_utc_ms = epoch + 5000ms (kEpochDeltaMs).
//   block_fence_frame_ = ceil((5000 + 10000) * 30 / 1000) = 450.
//   planned_seam[1]   = 0 + ceil(10000 * 30 / 1000)      = 300.
//   450 > 300 → gap of 150 frames between planned last seam and fence.
//
// Swap from seg0→seg1 at tick ~150 (may defer a few ticks for decoder I/O):
//   PerformSegmentSwap rebase: computed = ~155 + 150 = ~305.
//   305 < 450 → kSegment (BUG).
//
// At tick ~305: to_seg = 2 >= segments.size() → nullopt → no_incoming.
//   SEGMENT_SWAP_DEFERRED reason=no_incoming fires forever.
//   Block fence path never fires because next_seam_type_ == kSegment.
//
// Block B: [CONTENT(5000ms)] — fed before block A completes.
//
// BUG: After last segment ends, SEGMENT_SWAP_DEFERRED fires forever,
//      block B never starts.
// FIX: PerformSegmentSwap detects is_last_segment, sets kBlock.
//      Block fence / PADDED_GAP fires, loads block B.
// ===========================================================================

TEST_F(LastSegmentBlockBoundaryTest, LastSegmentEndBeforeFenceMustTransitionToNextBlock) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Assets not found: " << kPathA << ", " << kPathB;
  }

  const int64_t seg0_ms = 5000;  // CONTENT (SampleA)
  const int64_t seg1_ms = 5000;  // CONTENT (SampleB) — last segment
  int64_t epoch = NowMs();

  FedBlock block_a = MakeTwoSegmentBlock(
      "block-a-last-seg", epoch, seg0_ms, seg1_ms);

  // Block B starts where block A ends.
  FedBlock block_b = MakeSingleSegmentBlock(
      "block-b-successor", block_a.end_utc_ms, 5000);

  // Feed both blocks into the queue.
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Block A's 2 segments = 300 frames at 30fps.  Block fence at 450 (due to
  // 5000ms epoch delta).  After the last segment ends (~300 frames), the system
  // must transition to block B via the block fence / PADDED_GAP path.
  //
  // If the bug is present, the system is stuck at kSegment with no_incoming
  // and block B never starts.  We give a generous wall-time deadline.
  const int timeout_ms = 15000;
  bool block_b_started = WaitForBlockBStarted("block-b-successor", timeout_ms);

  // Diagnostic output if bug is present.
  if (!block_b_started) {
    int64_t total = engine_->SnapshotMetrics().continuous_frames_emitted_total;
    ADD_FAILURE() << "INV-LAST-SEGMENT-BLOCK-BOUNDARY-001 VIOLATED.\n"
                  << "Block B (block-b-successor) did not start within "
                  << timeout_ms << "ms.\n"
                  << "Frames emitted: " << total << "\n"
                  << "SEGMENT_SWAP_DEFERRED seen: "
                  << (HasPermanentDeferral() ? "yes" : "no") << "\n"
                  << "The last segment in block A ended before block_fence_frame_\n"
                  << "but the seam type was kSegment instead of kBlock.\n"
                  << "The block fence / PADDED_GAP path never fired.";
  }

  engine_->Stop();

  // Primary assertion: block B must have started.
  EXPECT_TRUE(block_b_started)
      << "Block B must start after block A's last segment ends.";
}

}  // namespace
}  // namespace retrovue::blockplan::testing
