// Repository: Retrovue-playout
// Component: DEGRADED_TAKE_MODE / INV-FENCE-TAKE-READY-001 Contract Tests
// Purpose: When B is content-first and not primed at fence, must not crash and
//          must output held frame then cut to B when primed; violation logged once.
// Contract Reference: pkg/air/docs/contracts/INV-FENCE-TAKE-READY-001.md
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
#include "DeterministicOutputClock.hpp"
#include "retrovue/blockplan/SeamProofTypes.hpp"
#include "retrovue/util/Logger.hpp"
#include "FastTestConfig.hpp"
#include "deterministic_tick_driver.hpp"

namespace retrovue::blockplan::testing {
namespace {

using test_infra::kBlockTimeOffsetMs;
using test_infra::kStdBlockMs;

static const std::string kPathA = "/opt/retrovue/assets/SampleA.mp4";
static const std::string kPathB = "/opt/retrovue/assets/SampleB.mp4";

static bool FileExists(const std::string& path) {
  std::ifstream f(path);
  return f.good();
}

static FedBlock MakeBlock(const std::string& block_id,
                          int64_t start_utc_ms,
                          int64_t duration_ms,
                          const std::string& uri) {
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
  seg.segment_type = SegmentType::kContent;
  block.segments.push_back(seg);
  return block;
}

class DegradedTakeModeContractTest : public ::testing::Test {
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
    callbacks.on_block_completed = [this](const FedBlock& block, int64_t, int64_t) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      completed_blocks_.push_back(block.block_id);
      blocks_completed_cv_.notify_all();
    };
    callbacks.on_session_ended = [this](const std::string&, int64_t) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      session_ended_count_++;
      session_ended_cv_.notify_all();
    };
    callbacks.on_frame_emitted = [this](const FrameFingerprint& fp) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      fingerprints_.push_back(fp);
    };
    callbacks.on_seam_transition = [](const SeamTransitionLog&) {};
    callbacks.on_block_summary = [](const BlockPlaybackSummary&) {};
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

  std::shared_ptr<ITimeSource> test_ts_;
  std::unique_ptr<BlockPlanSessionContext> ctx_;
  std::unique_ptr<PipelineManager> engine_;
  int drain_fd_ = -1;
  std::atomic<bool> drain_stop_{false};
  std::thread drain_thread_;

  std::mutex cb_mutex_;
  std::condition_variable session_ended_cv_;
  std::condition_variable blocks_completed_cv_;
  std::vector<std::string> completed_blocks_;
  std::vector<FrameFingerprint> fingerprints_;
  int session_ended_count_ = 0;

  // Capture Error() lines for violation-once assertion (INV-FENCE-TAKE-READY-001).
  std::vector<std::string> error_log_lines_;
  void InstallViolationSink() {
    error_log_lines_.clear();
    retrovue::util::Logger::SetErrorSink(
        [this](const std::string& line) { error_log_lines_.push_back(line); });
  }
  void ClearViolationSink() {
    retrovue::util::Logger::SetErrorSink(nullptr);
  }
  int CountViolationLines() const {
    const std::string marker = "INV-FENCE-TAKE-READY-001 VIOLATION DEGRADED_TAKE_MODE";
    int n = 0;
    for (const auto& s : error_log_lines_) {
      if (s.find(marker) != std::string::npos) n++;
    }
    return n;
  }
};

// =============================================================================
// INV-FENCE-TAKE-READY-001 / DEGRADED_TAKE_MODE: Simulated fence where B is
// unprimed must not output black and must not crash. Output must be held
// frame then cut to B when primed.
// =============================================================================
TEST_F(DegradedTakeModeContractTest, UnprimedBAtFence_NoBlackNoCrash_HeldThenB) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Real media assets not found: " << kPathA << ", " << kPathB;
  }

  auto now = NowMs();
  int64_t offset = kBlockTimeOffsetMs;

  // A (1.5s) -> B (3s). B's preroll is delayed so at fence we enter
  // DEGRADED_TAKE_MODE (hold last A frame); when B becomes ready we take B.
  // We only require A to complete; B may not complete (no block after B).
  FedBlock block_a = MakeBlock("deg-a", now + offset, 1500, kPathA);
  FedBlock block_b = MakeBlock("deg-b", block_a.end_utc_ms, 3000, kPathB);

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  engine_ = MakeEngine();

  // Delay block prep for B so at fence B is not primed -> DEGRADED_TAKE_MODE.
  auto delay_fired = std::make_shared<std::atomic<bool>>(false);
  engine_->SetPreloaderDelayHook([delay_fired](const std::atomic<bool>& cancel) {
    if (!delay_fired->exchange(true, std::memory_order_acq_rel)) {
      // Cancellable 2.5s delay — check cancel every 10ms
      for (int i = 0; i < 250 && !cancel.load(std::memory_order_acquire); ++i) {
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
      }
    }
  });

  InstallViolationSink();
  engine_->Start();

  // At least block A must complete (take at fence or after degraded recovery).
  ASSERT_TRUE(WaitForBlocksCompletedBounded(1))
      << "Block A must complete — DEGRADED_TAKE_MODE must not crash or stall A→B";

  engine_->Stop();
  ClearViolationSink();

  auto m = engine_->SnapshotMetrics();

  // No crash / no detach.
  EXPECT_EQ(m.detach_count, 0)
      << "INV-FENCE-TAKE-READY-001: must not crash when B unprimed at fence";

  // Must have emitted frames through the fence (continuous output).
  EXPECT_GT(m.continuous_frames_emitted_total, 60u)
      << "Output must continue through degraded take";

  // Fingerprints: must see at least one held slot ('H') then later B slot.
  std::lock_guard<std::mutex> lock(cb_mutex_);
  int first_h = -1;
  int first_b_after_h = -1;
  for (size_t i = 0; i < fingerprints_.size(); i++) {
    if (fingerprints_[i].commit_slot == 'H') {
      if (first_h < 0) first_h = static_cast<int>(i);
    } else if (fingerprints_[i].commit_slot == 'B' && first_h >= 0 &&
               first_b_after_h < 0) {
      first_b_after_h = static_cast<int>(i);
      break;
    }
  }
  EXPECT_GE(first_h, 0)
      << "DEGRADED_TAKE_MODE: must output held frame (slot H) when B unprimed at fence";
  EXPECT_GE(first_b_after_h, first_h)
      << "Must cut to B (slot B) after held frame when B becomes primed";

  // Violation exactly once per fence event.
  EXPECT_EQ(CountViolationLines(), 1)
      << "INV-FENCE-TAKE-READY-001 must be logged exactly once when entering DEGRADED_TAKE_MODE";

  // No-unintentional-black: last A frame before fence must be real content; held must match it.
  int last_a_index = -1;
  for (size_t i = 0; i < fingerprints_.size(); i++) {
    if (fingerprints_[i].commit_slot == 'A') last_a_index = static_cast<int>(i);
    if (fingerprints_[i].commit_slot == 'H') break;  // stop at first H
  }
  ASSERT_GE(last_a_index, 0) << "Must have at least one A frame before held";
  const FrameFingerprint& last_a = fingerprints_[static_cast<size_t>(last_a_index)];
  EXPECT_FALSE(last_a.is_pad)
      << "Block A must produce real content (non-pad) just before fence";
  EXPECT_NE(last_a.y_crc32, 0u)
      << "Last A frame must have non-zero Y CRC (not black)";
  for (size_t i = 0; i < fingerprints_.size(); i++) {
    if (fingerprints_[i].commit_slot != 'H') continue;
    EXPECT_FALSE(fingerprints_[i].is_pad)
        << "Held frames must not be marked pad";
    EXPECT_EQ(fingerprints_[i].y_crc32, last_a.y_crc32)
        << "Held frame fingerprint must match last good A (no unintentional black) at index " << i;
  }
}

// =============================================================================
// Bounded degraded escalation: B never primes -> hold for HOLD_MAX_MS then
// switch to standby (slot 'S'); no crash; continuous output.
// =============================================================================
TEST_F(DegradedTakeModeContractTest, UnprimedBAtFence_BNeverPrimes_EscalatesToStandby) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Real media assets not found: " << kPathA << ", " << kPathB;
  }

  auto now = NowMs();
  int64_t offset = kBlockTimeOffsetMs;
  FedBlock block_a = MakeBlock("esc-a", now + offset, 1500, kPathA);
  FedBlock block_b = MakeBlock("esc-b", block_a.end_utc_ms, 3000, kPathB);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }
  engine_ = MakeEngine();
  engine_->SetPreloaderDelayHook([](const std::atomic<bool>& cancel) {
    // Cancellable 15s delay — check cancel every 10ms
    for (int i = 0; i < 1500 && !cancel.load(std::memory_order_acquire); ++i) {
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
  });

  engine_->Start();
  // Run long enough to pass HOLD_MAX_MS (5s) and see standby. Fence at ~1.5s, escalate at 6.5s.
  std::this_thread::sleep_for(std::chrono::milliseconds(8000));
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();
  EXPECT_EQ(m.detach_count, 0) << "Must not crash when B never primes";
  EXPECT_GT(m.continuous_frames_emitted_total, 200u)
      << "Output must continue through hold then standby";

  std::lock_guard<std::mutex> lock(cb_mutex_);
  int first_h = -1;
  int first_s = -1;
  for (size_t i = 0; i < fingerprints_.size(); i++) {
    if (fingerprints_[i].commit_slot == 'H' && first_h < 0)
      first_h = static_cast<int>(i);
    if (fingerprints_[i].commit_slot == 'S' && first_s < 0)
      first_s = static_cast<int>(i);
  }
  EXPECT_GE(first_h, 0)
      << "Must emit held frames (H) before escalating";
  EXPECT_GE(first_s, first_h)
      << "Must escalate to standby (S) after bounded hold";
}

}  // namespace
}  // namespace retrovue::blockplan::testing
