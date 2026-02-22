// Repository: Retrovue-playout
// Component: TAKE-at-Commit Contract Tests
// Purpose: Verify that the frame-accurate TAKE at the commitment point
//          guarantees: tick < fence → source A, tick >= fence → source B,
//          with no A-source frames at or after the fence.
// Contract Reference: INV-TAKE-AT-COMMIT-001
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <fcntl.h>
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
#include "DeterministicOutputClock.hpp"
#include "retrovue/blockplan/SeamProofTypes.hpp"
#include "retrovue/blockplan/TickProducer.hpp"
#include "FastTestConfig.hpp"
#include "deterministic_tick_driver.hpp"

namespace retrovue::blockplan::testing {
namespace {

using test_infra::kStdBlockMs;
using test_infra::kShortBlockMs;
using test_infra::kLongBlockMs;

// =============================================================================
// Helpers
// =============================================================================

static const std::string kPathA = "/opt/retrovue/assets/SampleA.mp4";
static const std::string kPathB = "/opt/retrovue/assets/SampleB.mp4";

static bool FileExists(const std::string& path) {
  std::ifstream f(path);
  return f.good();
}

static FedBlock MakeBlock(const std::string& block_id,
                          int64_t start_utc_ms,
                          int64_t duration_ms,
                          const std::string& uri,
                          int64_t asset_offset_ms = 0) {
  FedBlock block;
  block.block_id = block_id;
  block.channel_id = 99;
  block.start_utc_ms = start_utc_ms;
  block.end_utc_ms = start_utc_ms + duration_ms;

  FedBlock::Segment seg;
  seg.segment_index = 0;
  seg.asset_uri = uri;
  seg.asset_start_offset_ms = asset_offset_ms;
  seg.segment_duration_ms = duration_ms;
  block.segments.push_back(seg);

  return block;
}

// =============================================================================
// Test Fixture
// =============================================================================

class TakeAtCommitContractTest : public ::testing::Test {
 protected:
  void SetUp() override {
    ctx_ = std::make_unique<BlockPlanSessionContext>();
    ctx_->channel_id = 99;
    // PipelineManager::Run() calls dup(fd) then send() — must be a real socket.
    // socketpair + drain thread absorbs encoded TS output without backpressure.
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
    ctx_->fps = DeriveRationalFPS(30.0);
    test_ts_ = test_infra::MakeTestTimeSource();
  }

  void TearDown() override {
    if (engine_) {
      engine_->Stop();
      engine_.reset();
    }
    // Shut down drain: close write end first so read() returns 0.
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
      fence_frame_indices_.push_back(ct);
      blocks_completed_cv_.notify_all();
    };
    callbacks.on_session_ended = [this](const std::string& reason, int64_t) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      session_ended_count_++;
      session_ended_cv_.notify_all();
    };
    callbacks.on_frame_emitted = [this](const FrameFingerprint& fp) {
      std::lock_guard<std::mutex> lock(fp_mutex_);
      fingerprints_.push_back(fp);
    };
    return std::make_unique<PipelineManager>(
        ctx_.get(), std::move(callbacks), test_ts_,
        std::make_shared<DeterministicOutputClock>(ctx_->fps.num, ctx_->fps.den),
        PipelineManagerOptions{0});
  }

  bool WaitForBlocksCompletedBounded(int count, int64_t max_steps = 50000) {
    return retrovue::blockplan::test_utils::WaitForBounded(
        [this, count] {
          std::lock_guard<std::mutex> lock(cb_mutex_);
          return static_cast<int>(completed_blocks_.size()) >= count;
        },
        max_steps);
  }

  bool WaitForFenceBounded(int64_t max_steps = 50000) {
    return retrovue::blockplan::test_utils::WaitForBounded(
        [this] {
          std::lock_guard<std::mutex> lock(cb_mutex_);
          return !fence_frame_indices_.empty();
        },
        max_steps);
  }

  std::shared_ptr<ITimeSource> test_ts_;
  std::unique_ptr<BlockPlanSessionContext> ctx_;
  std::unique_ptr<PipelineManager> engine_;
  int drain_fd_ = -1;
  std::atomic<bool> drain_stop_{false};
  std::thread drain_thread_;

  std::mutex cb_mutex_;
  std::condition_variable blocks_completed_cv_;
  std::condition_variable session_ended_cv_;
  std::vector<std::string> completed_blocks_;
  std::vector<int64_t> fence_frame_indices_;
  int session_ended_count_ = 0;

  std::mutex fp_mutex_;
  std::vector<FrameFingerprint> fingerprints_;
};

// =============================================================================
// INV-TAKE-AT-COMMIT-001: Frame-Accurate Source Selection
//
// Two real-media blocks A (1s) and B (1s).  Known fence_tick derived from
// block A's duration.  After both blocks complete, inspect the commit_slot
// field on every fingerprint.
// Block durations kept short to avoid audio lookahead underflow at
// block B's tail (fill thread throughput < 100% real-time).
//
// Assert:
//   - tick == fence_tick - 1 has commit_slot == 'A'
//   - tick == fence_tick     has commit_slot == 'B'
//   - ALL ticks >= fence_tick have commit_slot != 'A'
//   - ALL non-pad ticks < fence_tick have commit_slot == 'A'
// =============================================================================
TEST_F(TakeAtCommitContractTest, FrameAccurateSourceSelection) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Real media assets not found: " << kPathA << ", " << kPathB;
  }

  // Block A: standard duration, block B: long (not waited on).
  // Use time source for wall-clock-anchored UTC times.
  auto now_ms = NowMs();

  // Block B has a long duration — we do NOT wait for it to complete.
  // We only need a few B frames past the fence to verify the TAKE invariant.
  // Waiting for B to finish would hit audio underflow (fill thread < real-time).
  FedBlock block_a = MakeBlock("take-A", now_ms, kStdBlockMs, kPathA);
  FedBlock block_b = MakeBlock("take-B", now_ms + kStdBlockMs, kLongBlockMs, kPathB);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  engine_ = MakeEngine();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompletedBounded(1))
      << "Block A must complete within bounded steps";

  int64_t current = retrovue::blockplan::test_utils::GetCurrentSessionFrameIndex(engine_.get());
  retrovue::blockplan::test_utils::AdvanceUntilFenceOrFail(engine_.get(), current + 15);
  engine_->Stop();

  // Collect fingerprints
  std::vector<FrameFingerprint> fps;
  {
    std::lock_guard<std::mutex> lock(fp_mutex_);
    fps = fingerprints_;
  }

  // Derive fence_tick from fingerprints: first frame where active_block_id
  // changes from block A.  The ct value from on_block_completed is
  // ct_at_fence_ms (content time in milliseconds), not a frame index.
  int64_t fence_tick = -1;
  for (size_t i = 1; i < fps.size(); ++i) {
    if (fps[i].active_block_id != "take-A") {
      fence_tick = static_cast<int64_t>(i);
      break;
    }
  }
  ASSERT_GE(fence_tick, 0) << "Must find block transition in fingerprints";

  std::cout << "=== TAKE-AT-COMMIT TEST ===" << std::endl;
  std::cout << "fence_tick=" << fence_tick
            << " total_fingerprints=" << fps.size() << std::endl;

  // Verify we have enough frames to test the boundary.
  ASSERT_GT(fence_tick, 5)
      << "Block A must produce enough frames to test the boundary";
  ASSERT_GT(static_cast<int64_t>(fps.size()), fence_tick + 5)
      << "Must have frames past the fence to verify B";

  // ── Core assertions ──
  // Use active_block_id (block identity) for invariant checks.
  // commit_slot tracks buffer slot ('A'=live, 'B'=preview) which rotates
  // at the fence; active_block_id tracks the actual block that produced
  // the frame regardless of buffer slot assignment.

  const std::string block_a_id = "take-A";
  const std::string block_b_id = "take-B";

  // 1. tick == fence_tick - 1 must be from block A (last A frame)
  {
    const auto& fp = fps[static_cast<size_t>(fence_tick - 1)];
    EXPECT_EQ(fp.active_block_id, block_a_id)
        << "tick " << (fence_tick - 1) << " (fence-1) must be from block A"
        << " but got block=" << fp.active_block_id;
  }

  // 2. tick == fence_tick must be from block B (first B frame)
  {
    const auto& fp = fps[static_cast<size_t>(fence_tick)];
    EXPECT_EQ(fp.active_block_id, block_b_id)
        << "tick " << fence_tick << " (fence) must be from block B"
        << " but got block=" << fp.active_block_id;
  }

  // 3. No block-A frames at or after fence_tick
  int a_after_fence = 0;
  for (size_t i = static_cast<size_t>(fence_tick); i < fps.size(); i++) {
    if (fps[i].active_block_id == block_a_id) {
      a_after_fence++;
      if (a_after_fence <= 3) {
        std::cerr << "  VIOLATION: tick " << fps[i].session_frame_index
                  << " block=" << fps[i].active_block_id
                  << " after fence_tick=" << fence_tick << std::endl;
      }
    }
  }
  EXPECT_EQ(a_after_fence, 0)
      << a_after_fence << " block-A frame(s) at or after fence_tick="
      << fence_tick;

  // 4. All non-pad frames before fence_tick must be from block A
  int non_a_before_fence = 0;
  for (size_t i = 0; i < static_cast<size_t>(fence_tick); i++) {
    if (fps[i].active_block_id != block_a_id && !fps[i].is_pad) {
      non_a_before_fence++;
      if (non_a_before_fence <= 3) {
        std::cerr << "  VIOLATION: tick " << fps[i].session_frame_index
                  << " block=" << fps[i].active_block_id
                  << " before fence_tick=" << fence_tick << std::endl;
      }
    }
  }
  EXPECT_EQ(non_a_before_fence, 0)
      << non_a_before_fence << " non-A-block frame(s) before fence_tick="
      << fence_tick;

  // Print boundary region for diagnostic visibility
  std::cout << "Boundary region (fence-3 to fence+3):" << std::endl;
  for (int64_t t = std::max(int64_t{0}, fence_tick - 3);
       t <= std::min(static_cast<int64_t>(fps.size()) - 1, fence_tick + 3);
       t++) {
    const auto& fp = fps[static_cast<size_t>(t)];
    std::cout << "  tick=" << fp.session_frame_index
              << " source=" << fp.commit_slot
              << " pad=" << fp.is_pad
              << " block=" << fp.active_block_id
              << " asset=" << fp.asset_uri
              << std::endl;
  }
}

// =============================================================================
// INV-TAKE-AT-COMMIT-002: No A Frames After Fence (Sweep)
//
// Same setup as 001, but focuses purely on the sweep invariant:
// for ALL ticks T in the session, if T >= fence_tick then
// commit_slot != 'A'.  This is the single-predicate version.
// =============================================================================
TEST_F(TakeAtCommitContractTest, NoAFramesAfterFenceSweep) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Real media assets not found: " << kPathA << ", " << kPathB;
  }

  auto now_ms = NowMs();

  // Use different asset offsets so CRC32 fingerprints differ.
  // Block B has long duration — we only need a few B frames past fence.
  FedBlock block_a = MakeBlock("sweep-A", now_ms, kShortBlockMs, kPathA, 0);
  FedBlock block_b = MakeBlock("sweep-B", now_ms + kShortBlockMs, kLongBlockMs, kPathB, 5000);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Wait for block A's fence (not completion count) — under the
  // fence-authoritative model, block completion fires only after the
  // commit sweep at the fence, not when media frames are exhausted.
  ASSERT_TRUE(WaitForFenceBounded())
      << "Fence must fire for block A";

  int64_t cur = retrovue::blockplan::test_utils::GetCurrentSessionFrameIndex(engine_.get());
  retrovue::blockplan::test_utils::AdvanceUntilFenceOrFail(engine_.get(), cur + 15);
  engine_->Stop();

  std::vector<FrameFingerprint> fps;
  {
    std::lock_guard<std::mutex> lock(fp_mutex_);
    fps = fingerprints_;
  }

  int64_t fence_tick;
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    ASSERT_GE(fence_frame_indices_.size(), 1u);
    fence_tick = fence_frame_indices_[0];
  }

  // Single-predicate sweep: no frames from the pre-fence block after fence.
  const std::string block_a_id = "sweep-A";
  for (size_t i = static_cast<size_t>(fence_tick); i < fps.size(); i++) {
    EXPECT_NE(fps[i].active_block_id, block_a_id)
        << "INV-TAKE-AT-COMMIT: tick " << fps[i].session_frame_index
        << " >= fence_tick " << fence_tick
        << " must not be from block A"
        << " (got block=" << fps[i].active_block_id << ")";
  }
}

// =============================================================================
// INV-TAKE-AT-COMMIT-003: Commit Source Field Populated
//
// Run a single short block.  Verify that commit_slot is set on every
// fingerprint — it must be 'A' or 'P', never the default 'P' for all
// when real frames exist.  This catches accidental non-population.
// =============================================================================
TEST_F(TakeAtCommitContractTest, CommitSourceFieldPopulated) {
  if (!FileExists(kPathA)) {
    GTEST_SKIP() << "Real media asset not found: " << kPathA;
  }

  auto now_ms = NowMs();

  FedBlock block_a = MakeBlock("pop-A", now_ms, 2000, kPathA);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
  }

  engine_ = MakeEngine();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompletedBounded(1))
      << "Block must complete within bounded steps";

  engine_->Stop();

  std::vector<FrameFingerprint> fps;
  {
    std::lock_guard<std::mutex> lock(fp_mutex_);
    fps = fingerprints_;
  }

  ASSERT_GT(fps.size(), 10u) << "Must have enough frames to verify";

  int a_count = 0;
  int p_count = 0;
  for (const auto& fp : fps) {
    EXPECT_TRUE(fp.commit_slot == 'A' || fp.commit_slot == 'P')
        << "Single-block session: commit_slot must be 'A' or 'P', got '"
        << fp.commit_slot << "' at tick " << fp.session_frame_index;
    if (fp.commit_slot == 'A') a_count++;
    if (fp.commit_slot == 'P') p_count++;
  }

  // With real media, we expect mostly 'A' frames (after initial pad startup).
  EXPECT_GT(a_count, 0)
      << "Real media block must produce at least one A-sourced frame";
  std::cout << "commit_slot distribution: A=" << a_count
            << " P=" << p_count << " total=" << fps.size() << std::endl;
}

}  // namespace
}  // namespace retrovue::blockplan::testing
