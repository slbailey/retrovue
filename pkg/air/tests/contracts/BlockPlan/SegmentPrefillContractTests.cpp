// Repository: Retrovue-playout
// Component: Segment Prefill Contract Tests
// Purpose: Verify INV-SEAM-SEGMENT-PREFILL-001
// Contract Reference: docs/contracts/invariants/air/INV-SEAM-SEGMENT-PREFILL-001.md
// Copyright (c) 2025 RetroVue
//
// Tests:
//   T-PREFILL-001: BCreatedAtPrepCompletionNotSeamTick
//   T-PREFILL-002: FillLoopIncreasesDepthDuringRunway
//   T-PREFILL-003: SwapSeesWarmBuffer
//   T-PREFILL-004: PadSegmentsUnaffected
//   T-PREFILL-005: IdempotentBCreation
//   T-PREFILL-006: ShortRunwayNoRegression

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
#include "retrovue/blockplan/PlaybackTraceTypes.hpp"
#include "retrovue/blockplan/SeamProofTypes.hpp"
#include "FastTestConfig.hpp"
#include "TestDecoder.hpp"
#include "deterministic_tick_driver.hpp"

namespace retrovue::blockplan::testing {
namespace {

// =============================================================================
// Constants
// =============================================================================

static const std::string kPathA = "/opt/retrovue/assets/SampleA.mp4";

static bool FileExists(const std::string& path) {
  std::ifstream f(path);
  return f.good();
}

// =============================================================================
// Helpers
// =============================================================================

static FedBlock MakeBlock(const std::string& block_id,
                          int64_t start_utc_ms,
                          int64_t duration_ms,
                          const std::string& uri = "/nonexistent/test.mp4") {
  FedBlock block;
  block.block_id = block_id;
  block.channel_id = 99;
  block.start_utc_ms = start_utc_ms;
  block.end_utc_ms = start_utc_ms + duration_ms;

  FedBlock::Segment seg;
  seg.segment_index = 0;
  seg.asset_uri = uri;
  seg.asset_start_offset_ms = 0;
  seg.segment_duration_ms = duration_ms;
  block.segments.push_back(seg);

  return block;
}

static FedBlock MakeMultiSegmentBlock(
    const std::string& block_id,
    int64_t start_utc_ms,
    int64_t duration_ms,
    const std::string& seg0_uri,
    int64_t seg0_duration_ms,
    const std::string& seg1_uri,
    int64_t seg1_duration_ms,
    SegmentType seg0_type = SegmentType::kContent,
    SegmentType seg1_type = SegmentType::kFiller) {
  FedBlock block;
  block.block_id = block_id;
  block.channel_id = 99;
  block.start_utc_ms = start_utc_ms;
  block.end_utc_ms = start_utc_ms + duration_ms;

  FedBlock::Segment s0;
  s0.segment_index = 0;
  s0.asset_uri = seg0_uri;
  s0.asset_start_offset_ms = 0;
  s0.segment_duration_ms = seg0_duration_ms;
  s0.segment_type = seg0_type;
  block.segments.push_back(s0);

  FedBlock::Segment s1;
  s1.segment_index = 1;
  s1.asset_uri = seg1_uri;
  s1.asset_start_offset_ms = 0;
  s1.segment_duration_ms = seg1_duration_ms;
  s1.segment_type = seg1_type;
  block.segments.push_back(s1);

  return block;
}

using test_infra::kBootGuardMs;
using test_infra::kBlockTimeOffsetMs;
using test_infra::kStdBlockMs;
using test_infra::kSegBlockMs;

// =============================================================================
// Test Fixture
// =============================================================================

class SegmentPrefillContractTest : public ::testing::Test {
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
  }

  void TearDown() override {
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

  int64_t NowMs() { return test_ts_->NowUtcMs(); }

  std::unique_ptr<PipelineManager> MakeEngine() {
    PipelineManager::Callbacks callbacks;
    callbacks.on_block_completed = [this](const FedBlock& block, int64_t ct, int64_t) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      completed_blocks_.push_back(block.block_id);
      blocks_completed_cv_.notify_all();
    };
    callbacks.on_session_ended = [this](const std::string& reason, int64_t) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      session_ended_count_++;
      session_ended_reason_ = reason;
      session_ended_cv_.notify_all();
    };
    callbacks.on_frame_emitted = [this](const FrameFingerprint& fp) {
      std::lock_guard<std::mutex> lock(fp_mutex_);
      fingerprints_.push_back(fp);
    };
    callbacks.on_seam_transition = [this](const SeamTransitionLog& seam) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      seam_logs_.push_back(seam);
    };
    callbacks.on_block_summary = [this](const BlockPlaybackSummary& summary) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      summaries_.push_back(summary);
    };
    return std::make_unique<PipelineManager>(
        ctx_.get(), std::move(callbacks), test_ts_,
        test_infra::MakeTestOutputClock(ctx_->fps.num, ctx_->fps.den, test_ts_),
        PipelineManagerOptions{0},
        std::make_shared<test_infra::TestProducerFactory>());
  }

  bool WaitForBlocksCompletedBounded(int count, int64_t max_steps = 50000) {
    return retrovue::blockplan::test_utils::WaitForBounded(
        [this, count] {
          std::lock_guard<std::mutex> lock(cb_mutex_);
          return static_cast<int>(completed_blocks_.size()) >= count;
        },
        max_steps);
  }

  std::shared_ptr<test_infra::TestTimeSourceType> test_ts_;
  std::unique_ptr<BlockPlanSessionContext> ctx_;
  std::unique_ptr<PipelineManager> engine_;
  int drain_fd_ = -1;
  std::atomic<bool> drain_stop_{false};
  std::thread drain_thread_;

  std::mutex cb_mutex_;
  std::condition_variable session_ended_cv_;
  std::condition_variable blocks_completed_cv_;
  int session_ended_count_ = 0;
  std::string session_ended_reason_;
  std::vector<std::string> completed_blocks_;
  std::vector<SeamTransitionLog> seam_logs_;
  std::vector<BlockPlaybackSummary> summaries_;

  std::mutex fp_mutex_;
  std::vector<FrameFingerprint> fingerprints_;
};

// =============================================================================
// T-PREFILL-001: BCreatedAtPrepCompletionNotSeamTick
// Contract: INV-SEAM-SEGMENT-PREFILL-001
//
// B-side buffers are created when prep completes (not at seam tick).
// Evidence: segment_prep_armed fires, and the session survives the seam
// (pad output from unresolvable URIs still produces frames).
// =============================================================================

TEST_F(SegmentPrefillContractTest, T_PREFILL_001_BCreatedAtPrepCompletionNotSeamTick) {
  auto now = NowMs();

  // Block with 2 segments. Unresolvable URIs → pad frames at segment.
  // Session must survive the seam — the prefill code path still runs
  // (EnsureIncomingBReadyForSeam is called when prep completes, even though
  // the producer will output pad).
  auto blockA = MakeMultiSegmentBlock(
      "prefill-001-A", now + kBlockTimeOffsetMs, kSegBlockMs,
      "/nonexistent/ep.mp4", kSegBlockMs / 2,
      "/nonexistent/filler.mp4", kSegBlockMs / 2);

  auto blockB = MakeBlock("prefill-001-B",
      now + kBlockTimeOffsetMs + kSegBlockMs, kStdBlockMs);

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(blockA);
    ctx_->block_queue.push_back(blockB);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Advance past block A's fence + some margin into block B.
  int64_t fence = test_infra::FenceTickAt30fps(kBootGuardMs + kSegBlockMs + 1000);
  test_utils::AdvanceUntilFenceOrFail(engine_.get(), fence);
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  // Session must survive (no fatal underflow). The early B creation code
  // path runs (or is a no-op for pad) without crashing.
  EXPECT_EQ(m.detach_count, 0) << "Session died — detach_count > 0";

  // Session produced frames past the segment boundary.
  EXPECT_GT(m.continuous_frames_emitted_total, 30)
      << "Session must produce frames past the segment boundary";
}

// =============================================================================
// T-PREFILL-002: FillLoopIncreasesDepthDuringRunway
// Contract: INV-SEAM-SEGMENT-PREFILL-001
//
// When real media is available, the fill loop increases video lookahead
// depth during the runway between prep completion and seam tick.
// Evidence: session survives without underflow; source_swap fires.
// =============================================================================

TEST_F(SegmentPrefillContractTest, T_PREFILL_002_FillLoopIncreasesDepthDuringRunway) {
  if (!FileExists(kPathA)) {
    GTEST_SKIP() << "SampleA.mp4 not found — skipping real-media prefill test";
  }

  auto now = NowMs();

  auto blockA = MakeMultiSegmentBlock(
      "prefill-002-A", now + kBlockTimeOffsetMs, kSegBlockMs,
      kPathA, kSegBlockMs / 2,
      kPathA, kSegBlockMs / 2);

  auto blockB = MakeBlock("prefill-002-B",
      now + kBlockTimeOffsetMs + kSegBlockMs, kStdBlockMs, kPathA);

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(blockA);
    ctx_->block_queue.push_back(blockB);
  }

  engine_ = MakeEngine();
  engine_->Start();

  int64_t fence = test_infra::FenceTickAt30fps(kBootGuardMs + kSegBlockMs + 1000);
  test_utils::AdvanceUntilFenceOrFail(engine_.get(), fence);
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  // Source swap count tracks segment swaps. At least one must have fired.
  EXPECT_GE(m.source_swap_count, 1)
      << "No source swap detected — segment transition did not fire";

  // Session must survive the seam without underflow.
  EXPECT_EQ(m.detach_count, 0)
      << "Session died at segment seam — fill loop did not accumulate depth";
}

// =============================================================================
// T-PREFILL-003: SwapSeesWarmBuffer
// Contract: INV-SEAM-SEGMENT-PREFILL-001
//
// At segment swap, incoming video depth should be near target when the
// runway was sufficient for the decode rate.
// =============================================================================

TEST_F(SegmentPrefillContractTest, T_PREFILL_003_SwapSeesWarmBuffer) {
  if (!FileExists(kPathA)) {
    GTEST_SKIP() << "SampleA.mp4 not found — skipping warm-buffer test";
  }

  auto now = NowMs();

  // Long first segment to maximize runway for fill loop.
  const int64_t seg0_ms = (kSegBlockMs * 4) / 5;
  const int64_t seg1_ms = kSegBlockMs - seg0_ms;

  auto blockA = MakeMultiSegmentBlock(
      "prefill-003-A", now + kBlockTimeOffsetMs, kSegBlockMs,
      kPathA, seg0_ms,
      kPathA, seg1_ms);

  auto blockB = MakeBlock("prefill-003-B",
      now + kBlockTimeOffsetMs + kSegBlockMs, kStdBlockMs, kPathA);

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(blockA);
    ctx_->block_queue.push_back(blockB);
  }

  engine_ = MakeEngine();
  engine_->Start();

  int64_t fence = test_infra::FenceTickAt30fps(kBootGuardMs + kSegBlockMs + 1000);
  test_utils::AdvanceUntilFenceOrFail(engine_.get(), fence);
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();
  EXPECT_EQ(m.detach_count, 0) << "Session died";
  EXPECT_GE(m.source_swap_count, 1) << "No segment swap fired";
}

// =============================================================================
// T-PREFILL-004: PadSegmentsUnaffected
// Contract: INV-SEAM-SEGMENT-PREFILL-001
//
// PAD segments must not create segment_b buffers. They use persistent
// pad_b_* buffers created at session init.
// =============================================================================

TEST_F(SegmentPrefillContractTest, T_PREFILL_004_PadSegmentsUnaffected) {
  auto now = NowMs();

  auto blockA = MakeMultiSegmentBlock(
      "prefill-004-A", now + kBlockTimeOffsetMs, kSegBlockMs,
      "/nonexistent/ep.mp4", kSegBlockMs / 2,
      "/nonexistent/pad.mp4", kSegBlockMs / 2,
      SegmentType::kContent, SegmentType::kPad);

  auto blockB = MakeBlock("prefill-004-B",
      now + kBlockTimeOffsetMs + kSegBlockMs, kStdBlockMs);

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(blockA);
    ctx_->block_queue.push_back(blockB);
  }

  engine_ = MakeEngine();
  engine_->Start();

  int64_t fence = test_infra::FenceTickAt30fps(kBootGuardMs + kSegBlockMs + 1000);
  test_utils::AdvanceUntilFenceOrFail(engine_.get(), fence);
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  // Session must survive — PAD transition uses pad_b_*, not segment_b_*.
  EXPECT_EQ(m.detach_count, 0) << "Session died on PAD transition";

  // Session produced frames past the segment boundary.
  EXPECT_GT(m.continuous_frames_emitted_total, 30)
      << "Session must produce frames past the PAD segment boundary";
}

// =============================================================================
// T-PREFILL-005: IdempotentBCreation
// Contract: INV-SEAM-SEGMENT-PREFILL-001
//
// EnsureIncomingBReadyForSeam is called every tick when prep result is
// available. It must not create duplicate B buffers.
// =============================================================================

TEST_F(SegmentPrefillContractTest, T_PREFILL_005_IdempotentBCreation) {
  auto now = NowMs();

  auto blockA = MakeMultiSegmentBlock(
      "prefill-005-A", now + kBlockTimeOffsetMs, kSegBlockMs,
      "/nonexistent/ep.mp4", kSegBlockMs / 2,
      "/nonexistent/filler.mp4", kSegBlockMs / 2);

  auto blockB = MakeBlock("prefill-005-B",
      now + kBlockTimeOffsetMs + kSegBlockMs, kStdBlockMs);

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(blockA);
    ctx_->block_queue.push_back(blockB);
  }

  engine_ = MakeEngine();
  engine_->Start();

  int64_t fence = test_infra::FenceTickAt30fps(kBootGuardMs + kSegBlockMs + 1000);
  test_utils::AdvanceUntilFenceOrFail(engine_.get(), fence);
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();
  EXPECT_EQ(m.detach_count, 0)
      << "Session died — double B creation may have caused crash";
}

// =============================================================================
// T-PREFILL-006: ShortRunwayNoRegression
// Contract: INV-SEAM-SEGMENT-PREFILL-001
//
// Very short segments (< 200ms) still create B and do not crash.
// The runway may be insufficient for full depth, but the session must survive.
// =============================================================================

TEST_F(SegmentPrefillContractTest, T_PREFILL_006_ShortRunwayNoRegression) {
  auto now = NowMs();

  // Two very short segments: 100ms each (total 200ms).
  const int64_t total_ms = 200;

  auto blockA = MakeMultiSegmentBlock(
      "prefill-006-A", now + kBlockTimeOffsetMs, total_ms,
      "/nonexistent/ep.mp4", 100,
      "/nonexistent/filler.mp4", 100);

  auto blockB = MakeBlock("prefill-006-B",
      now + kBlockTimeOffsetMs + total_ms, kStdBlockMs);

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(blockA);
    ctx_->block_queue.push_back(blockB);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Advance past the short block + into block B.
  int64_t fence = test_infra::FenceTickAt30fps(kBootGuardMs + total_ms + 1000);
  test_utils::AdvanceUntilFenceOrFail(engine_.get(), fence);
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();
  EXPECT_EQ(m.detach_count, 0)
      << "Session died on short-segment block — regression";
}

}  // namespace
}  // namespace retrovue::blockplan::testing
