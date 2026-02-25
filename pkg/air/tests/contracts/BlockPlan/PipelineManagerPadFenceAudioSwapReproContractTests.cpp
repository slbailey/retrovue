// Repository: Retrovue-playout
// Component: PipelineManager PAD fence audio swap repro contract tests
// Purpose: Reproduce real-world log pattern: A → B → short C → PAD with multiple
//          segment swaps, fence crossings, and preview activation/deactivation.
//          Hunt the race window that causes FENCE_AUDIO_PAD / a_src_is_null.
// Contract Reference: INV-PAD-PRODUCER, FENCE_AUDIO_PAD semantics
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <cinttypes>
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

// Per-tick record from on_tick_pad_fence_observability. Segment slot (A/B) and
// preview buffer existence are not available without additional production hooks.
struct SwapTickRecord {
  int64_t tick_index = 0;
  std::string decision;
  bool a_src_is_null = false;
  int fence_audio_pad_warning_delta = 0;
  int pad_frames_emitted_delta = 0;
};

class PipelineManagerPadFenceAudioSwapReproTest : public ::testing::Test {
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
    tick_records_.clear();
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

  std::unique_ptr<PipelineManager> MakeEngineWithObservability() {
    PipelineManager::Callbacks callbacks;
    callbacks.on_block_completed = [this](const FedBlock& block, int64_t, int64_t) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      completed_blocks_.push_back(block.block_id);
      blocks_completed_cv_.notify_all();
    };
    callbacks.on_session_ended = [this](const std::string& reason, int64_t) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      session_ended_reason_ = reason;
    };
    callbacks.on_tick_pad_fence_observability =
        [this](int64_t session_frame_index, const char* decision,
               bool a_src_is_null, bool fence_audio_pad_warning_this_tick,
               bool pad_frame_emitted_this_tick) {
          std::lock_guard<std::mutex> lock(rec_mutex_);
          SwapTickRecord rec;
          rec.tick_index = session_frame_index;
          rec.decision = decision ? decision : "";
          rec.a_src_is_null = a_src_is_null;
          rec.fence_audio_pad_warning_delta = fence_audio_pad_warning_this_tick ? 1 : 0;
          rec.pad_frames_emitted_delta = pad_frame_emitted_this_tick ? 1 : 0;
          tick_records_.push_back(rec);
        };
    return std::make_unique<PipelineManager>(
        ctx_.get(), std::move(callbacks), test_ts_,
        std::make_shared<DeterministicOutputClock>(ctx_->fps.num, ctx_->fps.den),
        PipelineManagerOptions{0});
  }

  bool WaitForBlocksCompleted(int count, int timeout_ms = 30000) {
    std::unique_lock<std::mutex> lock(cb_mutex_);
    return blocks_completed_cv_.wait_for(
        lock, std::chrono::milliseconds(timeout_ms),
        [this, count] {
          return static_cast<int>(completed_blocks_.size()) >= count;
        });
  }

  int64_t NowMs() { return test_ts_->NowUtcMs(); }

  std::vector<SwapTickRecord> SnapshotTickRecords() {
    std::lock_guard<std::mutex> lock(rec_mutex_);
    return tick_records_;
  }

  std::shared_ptr<ITimeSource> test_ts_;
  std::unique_ptr<BlockPlanSessionContext> ctx_;
  std::unique_ptr<PipelineManager> engine_;
  int drain_fd_ = -1;
  std::atomic<bool> drain_stop_{false};
  std::thread drain_thread_;

  std::mutex cb_mutex_;
  std::condition_variable blocks_completed_cv_;
  std::vector<std::string> completed_blocks_;
  std::string session_ended_reason_;

  std::mutex rec_mutex_;
  std::vector<SwapTickRecord> tick_records_;
};

// Scenario: Block A (content) → Block B (content) → short Block C → PAD.
// Covers: A→B swap, B→C swap, C→PAD swap. Asserts no FENCE_AUDIO_PAD and no
// a_src_is_null during PAD ticks. If failure reproduces, prints first 10 ticks
// around the first warning.
TEST_F(PipelineManagerPadFenceAudioSwapReproTest, PadFenceAudio_MultiBlockSwap_NoFenceAudioPad) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Assets not found: " << kPathA << ", " << kPathB;
  }

  const std::string block_a_id = "swap-a";
  const std::string block_b_id = "swap-b";
  const std::string block_c_id = "swap-c";
  int64_t now = NowMs();

  FedBlock block_a = MakeBlock(block_a_id, now, 2000, kPathA);
  FedBlock block_b = MakeBlock(block_b_id, now + 3000, 2000, kPathB);
  FedBlock block_c = MakeBlock(block_c_id, now + 6000, 500, kPathA);  // short C: 500ms

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
    ctx_->block_queue.push_back(block_c);
  }

  engine_ = MakeEngineWithObservability();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(3, 45000))
      << "Blocks A, B, C must complete so we see A→B, B→C, C→PAD swaps";

  int64_t frame_at_c_completion = engine_->SnapshotMetrics().continuous_frames_emitted_total;
  int64_t pad_ticks = 60;
  int64_t target_frame = frame_at_c_completion + 1 + pad_ticks;
  retrovue::blockplan::test_utils::AdvanceUntilFenceOrFail(engine_.get(), target_frame);
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();
  std::vector<SwapTickRecord> records = SnapshotTickRecords();

  EXPECT_GE(m.padded_gap_count, 1)
      << "Must have entered PADDED_GAP after C (no next block)";
  EXPECT_GE(m.total_blocks_executed, 3)
      << "Must have run A, B, and C";

  // PAD ticks: after C completed (tick_index > frame_at_c_completion), first pad_ticks
  std::vector<SwapTickRecord> pad_window;
  for (const auto& r : records) {
    if (r.tick_index > frame_at_c_completion &&
        static_cast<int>(pad_window.size()) < pad_ticks) {
      pad_window.push_back(r);
    }
  }

  int warning_count = 0;
  int a_src_null_during_pad = 0;
  size_t first_warning_idx = pad_window.size();
  for (size_t i = 0; i < pad_window.size(); i++) {
    if (pad_window[i].fence_audio_pad_warning_delta) {
      warning_count++;
      if (first_warning_idx > i) first_warning_idx = i;
    }
    if (pad_window[i].a_src_is_null && pad_window[i].decision == "pad") {
      a_src_null_during_pad++;
      if (first_warning_idx > i) first_warning_idx = i;
    }
  }

  if (m.fence_audio_pad_warning_count != 0 || a_src_null_during_pad != 0) {
    printf("\nMulti-segment swap REPRODUCED failure: fence_audio_pad_warning_count=%" PRId64
           " a_src_null_during_pad=%d\n",
           m.fence_audio_pad_warning_count, a_src_null_during_pad);
    size_t start = (first_warning_idx >= 5) ? first_warning_idx - 5 : 0;
    int show = 10;
    for (size_t j = start; j < pad_window.size() && show > 0; j++, show--) {
      const auto& t = pad_window[j];
      printf("  tick=%" PRId64 " decision=%s a_src_is_null=%d warning_delta=%d\n",
             t.tick_index, t.decision.c_str(), t.a_src_is_null ? 1 : 0,
             t.fence_audio_pad_warning_delta);
    }
  }

  EXPECT_EQ(m.fence_audio_pad_warning_count, 0)
      << "No FENCE_AUDIO_PAD during multi-block swap (A→B→C→PAD)";
  EXPECT_EQ(a_src_null_during_pad, 0)
      << "No a_src_is_null during PAD ticks after C→PAD swap";
}

}  // namespace
}  // namespace retrovue::blockplan::testing
