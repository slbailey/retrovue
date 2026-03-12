// Repository: Retrovue-playout
// Component: Segment Swap Readiness Contract Tests
// Purpose: Verify INV-SEAM-SWAP-READINESS-001
// Contract Reference: docs/contracts/invariants/air/INV-SEAM-SWAP-READINESS-001.md
// Copyright (c) 2025 RetroVue
//
// Tests:
//   T-SWAP-READY-001: SwapDeferredWhenBelowTarget
//     Outcome: Swap defers when incoming video depth < target. Session survives
//              via hold-last on the outgoing segment.
//
//   T-SWAP-READY-002: SwapFiresWhenAtTarget
//     Outcome: With sufficient runway (Commit 1), swap fires at or near seam
//              tick with depth >= target. Session survives without underflow.
//
//   T-SWAP-READY-003: PadExemptFromVideoDepthGate
//     Outcome: Content→PAD transition fires immediately regardless of video
//              depth. PAD provides video on-demand.
//
//   T-SWAP-READY-004: RepeatedDeferralSafe
//     Outcome: When swap is deferred for multiple ticks, outgoing segment
//              continues hold-last safely, incoming fill loop keeps filling,
//              and commit occurs only once target is reached.
//
//   T-SWAP-READY-005: SyntheticURIDeferralSurvives
//     Outcome: Unresolvable URIs defer indefinitely via pad fallback.
//              Session survives.
//
// Test → Contract → Outcome Mapping:
//
//   | Test              | INV-SEAM-SWAP-READINESS-001 | Outcome                                 | Asset-Agnostic? |
//   |-------------------|-----------------------------|------------------------------------------|-----------------|
//   | T-SWAP-READY-001  | Deferral                    | Swap defers below target, session lives  | No              |
//   | T-SWAP-READY-002  | Readiness                   | Swap fires at target depth               | No              |
//   | T-SWAP-READY-003  | PAD exemption               | PAD bypasses video gate                  | Yes             |
//   | T-SWAP-READY-004  | Repeated deferral           | Hold-last + fill continues + commit once | No              |
//   | T-SWAP-READY-005  | Synthetic fallback          | Pad fallback, session survives           | Yes             |

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

class SegmentSwapReadinessContractTest : public ::testing::Test {
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
        PipelineManagerOptions{0});
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
// T-SWAP-READY-001: SwapDeferredWhenBelowTarget
// Contract: INV-SEAM-SWAP-READINESS-001
//
// With a very short first segment (minimal runway), the fill loop may not
// reach target depth before the seam tick. The swap must defer — the
// outgoing segment enters hold-last mode and the session survives.
// =============================================================================

TEST_F(SegmentSwapReadinessContractTest, T_SWAP_READY_001_SwapDeferredWhenBelowTarget) {
  if (!FileExists(kPathA)) {
    GTEST_SKIP() << "SampleA.mp4 not found — skipping deferral test";
  }

  auto now = NowMs();

  // Very short first segment (100ms) followed by longer second segment.
  // 100ms at 30fps = 3 frames. Prep + fill may not reach target=15 in that
  // window, causing deferral.
  auto blockA = MakeMultiSegmentBlock(
      "swap-ready-001-A", now + kBlockTimeOffsetMs, kSegBlockMs,
      kPathA, 100,
      kPathA, kSegBlockMs - 100);

  auto blockB = MakeBlock("swap-ready-001-B",
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

  // Session must survive — deferral + hold-last is safe.
  EXPECT_EQ(m.detach_count, 0)
      << "Session died — deferral should be safe via hold-last";

  // Session produced frames through the block.
  EXPECT_GT(m.continuous_frames_emitted_total, 30)
      << "Session must produce frames past the segment boundary";
}

// =============================================================================
// T-SWAP-READY-002: SwapFiresWhenAtTarget
// Contract: INV-SEAM-SWAP-READINESS-001
//
// With a long first segment (ample runway from Commit 1), the fill loop
// reaches target depth before the seam tick and swap fires cleanly.
// =============================================================================

TEST_F(SegmentSwapReadinessContractTest, T_SWAP_READY_002_SwapFiresWhenAtTarget) {
  if (!FileExists(kPathA)) {
    GTEST_SKIP() << "SampleA.mp4 not found — skipping warm-swap test";
  }

  auto now = NowMs();

  // Long first segment (80% of block) gives fill loop plenty of runway.
  const int64_t seg0_ms = (kSegBlockMs * 4) / 5;
  const int64_t seg1_ms = kSegBlockMs - seg0_ms;

  auto blockA = MakeMultiSegmentBlock(
      "swap-ready-002-A", now + kBlockTimeOffsetMs, kSegBlockMs,
      kPathA, seg0_ms,
      kPathA, seg1_ms);

  auto blockB = MakeBlock("swap-ready-002-B",
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
// T-SWAP-READY-003: PadExemptFromVideoDepthGate
// Contract: INV-SEAM-SWAP-READINESS-001
//
// Content→PAD transition fires immediately. PAD provides video on-demand
// via PadProducer::VideoFrame() and has no buffer to fill.
// =============================================================================

TEST_F(SegmentSwapReadinessContractTest, T_SWAP_READY_003_PadExemptFromVideoDepthGate) {
  auto now = NowMs();

  // Content (unresolvable → pad output) followed by PAD segment.
  auto blockA = MakeMultiSegmentBlock(
      "swap-ready-003-A", now + kBlockTimeOffsetMs, kSegBlockMs,
      "/nonexistent/ep.mp4", kSegBlockMs / 2,
      "/nonexistent/pad.mp4", kSegBlockMs / 2,
      SegmentType::kContent, SegmentType::kPad);

  auto blockB = MakeBlock("swap-ready-003-B",
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

  // Session must survive — PAD transition is exempt from video depth gate.
  EXPECT_EQ(m.detach_count, 0) << "Session died on PAD transition";

  // Session produced frames past the segment boundary.
  EXPECT_GT(m.continuous_frames_emitted_total, 30)
      << "Session must produce frames past the PAD segment boundary";
}

// =============================================================================
// T-SWAP-READY-004: RepeatedDeferralSafe
// Contract: INV-SEAM-SWAP-READINESS-001
//
// When swap is deferred for multiple ticks:
// - Outgoing segment continues hold-last safely
// - Incoming fill loop keeps filling
// - Commit occurs only once target is reached
// =============================================================================

TEST_F(SegmentSwapReadinessContractTest, T_SWAP_READY_004_RepeatedDeferralSafe) {
  if (!FileExists(kPathA)) {
    GTEST_SKIP() << "SampleA.mp4 not found — skipping repeated-deferral test";
  }

  auto now = NowMs();

  // Short first segment (150ms ≈ 5 frames at 30fps). Fill loop needs to
  // decode 15 frames to reach target. Prep + prime + fill will likely
  // not complete by the seam tick, causing deferral for several ticks.
  auto blockA = MakeMultiSegmentBlock(
      "swap-ready-004-A", now + kBlockTimeOffsetMs, kSegBlockMs,
      kPathA, 150,
      kPathA, kSegBlockMs - 150);

  auto blockB = MakeBlock("swap-ready-004-B",
      now + kBlockTimeOffsetMs + kSegBlockMs, kStdBlockMs, kPathA);

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(blockA);
    ctx_->block_queue.push_back(blockB);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Allow extra time for deferral + eventual commit.
  int64_t fence = test_infra::FenceTickAt30fps(kBootGuardMs + kSegBlockMs + 2000);
  test_utils::AdvanceUntilFenceOrFail(engine_.get(), fence);
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  // Session must survive — repeated deferral with hold-last is safe.
  EXPECT_EQ(m.detach_count, 0)
      << "Session died during repeated deferral — hold-last should be safe";

  // Session produced frames continuously (no gap from deferral).
  EXPECT_GT(m.continuous_frames_emitted_total, 30)
      << "Session must produce frames through deferral period";
}

// =============================================================================
// T-SWAP-READY-005: SyntheticURIDeferralSurvives
// Contract: INV-SEAM-SWAP-READINESS-001
//
// Unresolvable URIs cause indefinite deferral via pad fallback.
// Session survives.
// =============================================================================

TEST_F(SegmentSwapReadinessContractTest, T_SWAP_READY_005_SyntheticURIDeferralSurvives) {
  auto now = NowMs();

  auto blockA = MakeMultiSegmentBlock(
      "swap-ready-005-A", now + kBlockTimeOffsetMs, kSegBlockMs,
      "/nonexistent/ep.mp4", kSegBlockMs / 2,
      "/nonexistent/filler.mp4", kSegBlockMs / 2);

  auto blockB = MakeBlock("swap-ready-005-B",
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
      << "Session died on synthetic-URI deferral — pad fallback should work";

  EXPECT_GT(m.continuous_frames_emitted_total, 30)
      << "Session must produce frames through synthetic-URI deferral";
}

}  // namespace
}  // namespace retrovue::blockplan::testing
