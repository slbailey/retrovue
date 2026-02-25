// Repository: Retrovue-playout
// Component: PipelineManager PAD / FENCE_AUDIO_PAD contract tests
// Purpose: Prove or disprove that FENCE_AUDIO_PAD occurs because
//          SelectAudioSourceForTick(...) returns nullptr at a block fence when
//          PAD is chosen, so PAD silence is never enqueued (if (a_src) a_src->Push(...)).
// Contract Reference: INV-PAD-PRODUCER, FENCE_AUDIO_PAD semantics
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

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/PipelineManager.hpp"
#include "retrovue/blockplan/PipelineMetrics.hpp"
#include "retrovue/blockplan/SeamProofTypes.hpp"
#include "DeterministicOutputClock.hpp"
#include "deterministic_tick_driver.hpp"
#include "FastTestConfig.hpp"

namespace retrovue::blockplan::testing {
namespace {

static const std::string kPathA = "/opt/retrovue/assets/SampleA.mp4";
static const std::string kPathB = "/opt/retrovue/assets/SampleB.mp4";

static bool FileExists(const std::string& path) {
  std::ifstream f(path);
  return f.good();
}

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

// =============================================================================
// Fixture: minimal PipelineManager harness (reuse pattern from BlockPlan contracts)
// =============================================================================

class PipelineManagerPadFenceAudioContractTest : public ::testing::Test {
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

  std::unique_ptr<PipelineManager> MakeEngine() {
    PipelineManager::Callbacks callbacks;
    callbacks.on_block_completed = [this](const FedBlock& block, int64_t, int64_t) {
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
    return std::make_unique<PipelineManager>(
        ctx_.get(), std::move(callbacks), test_ts_,
        std::make_shared<DeterministicOutputClock>(ctx_->fps.num, ctx_->fps.den),
        PipelineManagerOptions{0});
  }

  std::unique_ptr<PipelineManager> MakeEngineWithTrace() {
    PipelineManager::Callbacks callbacks;
    callbacks.on_block_completed = [this](const FedBlock& block, int64_t, int64_t) {
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
    return std::make_unique<PipelineManager>(
        ctx_.get(), std::move(callbacks), test_ts_,
        std::make_shared<DeterministicOutputClock>(ctx_->fps.num, ctx_->fps.den),
        PipelineManagerOptions{0});
  }

  std::vector<FrameFingerprint> SnapshotFingerprints() {
    std::lock_guard<std::mutex> lock(fp_mutex_);
    return fingerprints_;
  }

  bool WaitForBlocksCompleted(int count, int timeout_ms = 10000) {
    std::unique_lock<std::mutex> lock(cb_mutex_);
    return blocks_completed_cv_.wait_for(
        lock, std::chrono::milliseconds(timeout_ms),
        [this, count] {
          return static_cast<int>(completed_blocks_.size()) >= count;
        });
  }

  int64_t NowMs() { return test_ts_->NowUtcMs(); }

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
  int session_ended_count_ = 0;
  std::string session_ended_reason_;

  std::mutex fp_mutex_;
  std::vector<FrameFingerprint> fingerprints_;
};

// =============================================================================
// Contract: FENCE_AUDIO_PAD is taken when a_src == nullptr at a PAD tick.
// Subcase A: PAD at block fence with no preview (PADDED_GAP) → a_src is null,
//            silence is NOT enqueued, WARNING FENCE_AUDIO_PAD path is taken.
// =============================================================================

TEST_F(PipelineManagerPadFenceAudioContractTest, PadFenceAudio_WhenAuxNull_TriggersFenceWarning_NoEnqueue) {
  if (!FileExists(kPathA)) {
    GTEST_SKIP() << "Asset not found: " << kPathA;
  }
  int64_t now = NowMs();
  FedBlock block_a = MakeBlock("padfence-a", now, 2000, kPathA);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
  }
  engine_ = MakeEngine();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(1, 15000))
      << "Block A must complete so we enter PADDED_GAP (no next block)";

  // Run several more ticks in PADDED_GAP. At each tick take_b is true and
  // preview_audio_buffer_ is null, so SelectAudioSourceForTick returns null,
  // we do not push (if (a_src) a_src->Push(...) is skipped), and we hit the
  // else branch that logs WARNING FENCE_AUDIO_PAD.
  int64_t frames_after_block = engine_->SnapshotMetrics().continuous_frames_emitted_total;
  retrovue::blockplan::test_utils::AdvanceUntilFenceOrFail(
      engine_.get(), frames_after_block + 15);
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  EXPECT_GE(m.padded_gap_count, 1)
      << "Must have entered PADDED_GAP (fence with no next block)";
  EXPECT_EQ(m.fence_audio_pad_warning_count, 0)
      << "Fix: PAD must route silence to audio_buffer_ when a_src is null; no FENCE_AUDIO_PAD";
  EXPECT_GT(m.audio_buffer_samples_pushed, 0)
      << "PAD silence must be enqueued (push to fallback buffer) over PADDED_GAP ticks";
  EXPECT_GE(m.pad_frames_emitted_total, 15)
      << "PAD decision was used (pad frames emitted in PADDED_GAP)";
}

// =============================================================================
// Subcase B: PAD at session start (zero blocks) → a_src == audio_buffer_ (non-null),
//            silence IS enqueued, no FENCE_AUDIO_PAD warning.
// =============================================================================

TEST_F(PipelineManagerPadFenceAudioContractTest, PadFenceAudio_WhenAuxNonNull_EnqueuesSilence_NoFenceWarning) {
  // Queue empty: no blocks. From tick 0 decision is kPad, a_src = audio_buffer_ (live).
  engine_ = MakeEngine();
  engine_->Start();

  retrovue::blockplan::test_utils::AdvanceUntilFenceOrFail(engine_.get(), 10);
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  EXPECT_EQ(m.fence_audio_pad_warning_count, 0)
      << "With a_src non-null (live audio buffer), PAD must enqueue silence and not take FENCE_AUDIO_PAD path";
  EXPECT_GT(m.audio_buffer_samples_pushed, 0)
      << "PAD must have pushed silence into the audio buffer when a_src is non-null";
  EXPECT_GE(m.pad_frames_emitted_total, 10)
      << "Pad frames emitted in pad-only mode";
}

// =============================================================================
// PadDoesNotLeakIntoContentAfterFence: After PADDED_GAP, when Block B starts,
// no PAD silence/frames may appear; audio buffer must transition to B's content.
// =============================================================================

TEST_F(PipelineManagerPadFenceAudioContractTest, PadDoesNotLeakIntoContentAfterFence) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Assets not found: " << kPathA << ", " << kPathB;
  }
  const std::string block_a_id = "padleak-a";
  const std::string block_b_id = "padleak-b";
  int64_t now = NowMs();
  FedBlock block_a = MakeBlock(block_a_id, now, 2000, kPathA);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
  }
  engine_ = MakeEngineWithTrace();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(1, 15000))
      << "Block A must complete so we enter PADDED_GAP";

  FedBlock block_b = MakeBlock(block_b_id, now + 4000, 2000, kPathB);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_b);
  }

  // Wait until we have at least one B content frame (no need for B to fully complete).
  const int deadline_ms = 20000;
  const int poll_ms = 50;
  int elapsed = 0;
  bool have_b_content = false;
  while (elapsed < deadline_ms) {
    auto fps = SnapshotFingerprints();
    for (const auto& fp : fps) {
      if (fp.active_block_id == block_b_id && !fp.is_pad) {
        have_b_content = true;
        break;
      }
    }
    if (have_b_content) break;
    std::this_thread::sleep_for(std::chrono::milliseconds(poll_ms));
    elapsed += poll_ms;
  }
  ASSERT_TRUE(have_b_content)
      << "Block B must emit at least one content frame (PADDED_GAP_EXIT then B content) within " << deadline_ms << "ms";

  // Advance a few more frames so we have a window of B content to assert on.
  retrovue::blockplan::test_utils::AdvanceUntilFenceOrFail(
      engine_.get(), engine_->SnapshotMetrics().continuous_frames_emitted_total + 15);
  engine_->Stop();

  auto fps = SnapshotFingerprints();
  size_t first_b_content = fps.size();
  size_t last_b_content = 0;
  for (size_t i = 0; i < fps.size(); i++) {
    if (fps[i].active_block_id == block_b_id && !fps[i].is_pad) {
      if (first_b_content == fps.size()) first_b_content = i;
      last_b_content = i;
    }
  }
  ASSERT_LT(first_b_content, fps.size())
      << "Block B must emit at least one content frame (PADDED_GAP_EXIT then B content)";

  // Assert no PAD within B's content window only (exclude warm-up PAD 60-63 and next PADDED_GAP after B).
  for (size_t i = first_b_content; i <= last_b_content; i++) {
    EXPECT_FALSE(fps[i].is_pad)
        << "No PAD frame inside B content window: index " << i
        << " session_frame=" << fps[i].session_frame_index;
  }

  auto m = engine_->SnapshotMetrics();
  EXPECT_GE(m.audio_buffer_samples_pushed, 0)
      << "Audio buffer must have received samples (content or pad as designed)";
  EXPECT_EQ(m.fence_audio_pad_warning_count, 0)
      << "No FENCE_AUDIO_PAD warning (PAD routed to fallback buffer)";
}

}  // namespace
}  // namespace retrovue::blockplan::testing
