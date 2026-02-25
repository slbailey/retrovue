// Repository: Retrovue-playout
// Component: PipelineManager 60fps PAD fence audio repro contract tests
// Purpose: Prove or disprove hypothesis: a_src == nullptr at PAD fence (FENCE_AUDIO_PAD)
//          occurs only with 60fps input due to video lookahead/fence-tick desync.
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
static const std::string kPath60fps = "/opt/retrovue/assets/Sample60fps.mp4";

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

// Per-tick record for assertion and failure reporting
struct TickRecord {
  int64_t tick_index = 0;
  std::string decision;
  bool a_src_is_null = false;
  int fence_audio_pad_warning_delta = 0;
  int pad_frames_emitted_delta = 0;
};

// Fixture: parameterized by FPS and asset path; records per-tick observability.
class PipelineManagerPadFenceAudio60fpsReproTest
    : public ::testing::TestWithParam<std::tuple<RationalFps, std::string>> {
 protected:
  void SetUp() override {
    std::tie(fps_, asset_path_) = GetParam();
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
    ctx_->fps = fps_;
    test_ts_ = test_infra::MakeTestTimeSource();
    tick_records_.clear();
    first_padded_gap_tick_ = -1;
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
      session_ended_count_++;
      session_ended_reason_ = reason;
    };
    callbacks.on_tick_pad_fence_observability =
        [this](int64_t session_frame_index, const char* decision,
               bool a_src_is_null, bool fence_audio_pad_warning_this_tick,
               bool pad_frame_emitted_this_tick) {
          std::lock_guard<std::mutex> lock(rec_mutex_);
          TickRecord rec;
          rec.tick_index = session_frame_index;
          rec.decision = decision ? decision : "";
          rec.a_src_is_null = a_src_is_null;
          rec.fence_audio_pad_warning_delta = fence_audio_pad_warning_this_tick ? 1 : 0;
          rec.pad_frames_emitted_delta = pad_frame_emitted_this_tick ? 1 : 0;
          tick_records_.push_back(rec);
          if (first_padded_gap_tick_ < 0 && rec.decision == "pad" && rec.tick_index > 0) {
            first_padded_gap_tick_ = rec.tick_index;
          }
        };
    return std::make_unique<PipelineManager>(
        ctx_.get(), std::move(callbacks), test_ts_,
        std::make_shared<DeterministicOutputClock>(ctx_->fps.num, ctx_->fps.den),
        PipelineManagerOptions{0});
  }

  bool WaitForBlocksCompleted(int count, int timeout_ms = 15000) {
    std::unique_lock<std::mutex> lock(cb_mutex_);
    return blocks_completed_cv_.wait_for(
        lock, std::chrono::milliseconds(timeout_ms),
        [this, count] {
          return static_cast<int>(completed_blocks_.size()) >= count;
        });
  }

  int64_t NowMs() { return test_ts_->NowUtcMs(); }

  std::vector<TickRecord> SnapshotTickRecords() {
    std::lock_guard<std::mutex> lock(rec_mutex_);
    return tick_records_;
  }

  RationalFps fps_;
  std::string asset_path_;
  std::shared_ptr<ITimeSource> test_ts_;
  std::unique_ptr<BlockPlanSessionContext> ctx_;
  std::unique_ptr<PipelineManager> engine_;
  int drain_fd_ = -1;
  std::atomic<bool> drain_stop_{false};
  std::thread drain_thread_;

  std::mutex cb_mutex_;
  std::condition_variable blocks_completed_cv_;
  std::vector<std::string> completed_blocks_;
  int session_ended_count_ = 0;
  std::string session_ended_reason_;

  std::mutex rec_mutex_;
  std::vector<TickRecord> tick_records_;
  int64_t first_padded_gap_tick_ = -1;
};

// Run Block A → wait completion → enter PADDED_GAP → advance N=120 ticks;
// collect per-tick metrics; assert PAD occurs and (30fps: no a_src null, 60fps: at least one a_src null or warning).
static const int kTicksAfterPaddedGap = 120;

INSTANTIATE_TEST_SUITE_P(
    PadFenceAudioRepro,
    PipelineManagerPadFenceAudio60fpsReproTest,
    ::testing::Values(
        std::make_tuple(FPS_30, kPathA),
        std::make_tuple(FPS_60, kPath60fps)));

TEST_P(PipelineManagerPadFenceAudio60fpsReproTest, PadFenceAudio_AuxNull_Repro_30fps) {
  if (fps_.num != 30000 || fps_.den != 1001) {
    GTEST_SKIP() << "This test runs only for 30fps parameterization";
  }
  if (!FileExists(asset_path_)) {
    GTEST_SKIP() << "Asset not found: " << asset_path_;
  }
  int64_t now = NowMs();
  FedBlock block_a = MakeBlock("repro-30-a", now, 2000, asset_path_);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
  }
  engine_ = MakeEngineWithObservability();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(1, 15000))
      << "Block A must complete so we enter PADDED_GAP (no next block)";

  int64_t frame_at_completion = engine_->SnapshotMetrics().continuous_frames_emitted_total;
  int64_t target_frame = frame_at_completion + 1 + kTicksAfterPaddedGap;
  retrovue::blockplan::test_utils::AdvanceUntilFenceOrFail(engine_.get(), target_frame);
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();
  std::vector<TickRecord> records = SnapshotTickRecords();

  EXPECT_GE(m.padded_gap_count, 1)
      << "Must have entered PADDED_GAP (fence with no next block)";
  EXPECT_GE(m.pad_frames_emitted_total, kTicksAfterPaddedGap / 2)
      << "PAD actually occurred (pad_frames_emitted_total >= N/2)";

  // Filter to PADDED_GAP ticks: tick_index > frame_at_completion, first kTicksAfterPaddedGap
  std::vector<TickRecord> pad_ticks;
  for (const auto& r : records) {
    if (r.tick_index > frame_at_completion && static_cast<int>(pad_ticks.size()) < kTicksAfterPaddedGap) {
      pad_ticks.push_back(r);
    }
  }

  // 30fps: no a_src_is_null during PAD (or at least fence_audio_pad_warning_count == 0)
  int warning_count = 0;
  int a_src_null_count = 0;
  for (const auto& r : pad_ticks) {
    if (r.fence_audio_pad_warning_delta) warning_count++;
    if (r.a_src_is_null) a_src_null_count++;
  }
  if (m.fence_audio_pad_warning_count != 0 || warning_count != 0) {
    size_t start = 0;
    for (size_t i = 0; i < pad_ticks.size(); i++) {
      if (pad_ticks[i].fence_audio_pad_warning_delta || pad_ticks[i].a_src_is_null) {
        start = (i >= 5) ? i - 5 : 0;
        int show = 10;
        for (size_t j = start; j < pad_ticks.size() && show > 0; j++, show--) {
          const auto& t = pad_ticks[j];
          printf("  tick=%" PRId64 " decision=%s a_src_is_null=%d warning_delta=%d\n",
                 t.tick_index, t.decision.c_str(), t.a_src_is_null ? 1 : 0,
                 t.fence_audio_pad_warning_delta);
        }
        break;
      }
    }
  }
  EXPECT_EQ(m.fence_audio_pad_warning_count, 0)
      << "30fps: no FENCE_AUDIO_PAD warning during PADDED_GAP";
  EXPECT_EQ(a_src_null_count, 0)
      << "30fps: no a_src_is_null ticks during PAD";
}

TEST_P(PipelineManagerPadFenceAudio60fpsReproTest, PadFenceAudio_AuxNull_Repro_60fps) {
  if (fps_.num != 60 || fps_.den != 1) {
    GTEST_SKIP() << "This test runs only for 60fps parameterization";
  }
  if (!FileExists(asset_path_)) {
    GTEST_SKIP() << "Asset not found: " << asset_path_;
  }
  int64_t now = NowMs();
  FedBlock block_a = MakeBlock("repro-60-a", now, 2000, asset_path_);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
  }
  engine_ = MakeEngineWithObservability();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(1, 15000))
      << "Block A must complete so we enter PADDED_GAP (no next block)";

  int64_t frame_at_completion = engine_->SnapshotMetrics().continuous_frames_emitted_total;
  int64_t target_frame = frame_at_completion + 1 + kTicksAfterPaddedGap;
  retrovue::blockplan::test_utils::AdvanceUntilFenceOrFail(engine_.get(), target_frame);
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();
  std::vector<TickRecord> records = SnapshotTickRecords();

  EXPECT_GE(m.padded_gap_count, 1)
      << "Must have entered PADDED_GAP (fence with no next block)";
  EXPECT_GE(m.pad_frames_emitted_total, kTicksAfterPaddedGap / 2)
      << "PAD actually occurred (pad_frames_emitted_total >= N/2)";

  std::vector<TickRecord> pad_ticks;
  for (const auto& r : records) {
    if (r.tick_index > frame_at_completion && static_cast<int>(pad_ticks.size()) < kTicksAfterPaddedGap) {
      pad_ticks.push_back(r);
    }
  }

  // 60fps: Document observed behavior. Original hypothesis was "only 60fps hits a_src==null at
  // PAD fence"; this test disproved it — with Sample60fps.mp4 we see no a_src_is_null and no
  // FENCE_AUDIO_PAD. Assert no regression (same as 30fps: PAD must route silence, no warning).
  int warning_count = 0;
  int a_src_null_count = 0;
  for (const auto& r : pad_ticks) {
    if (r.fence_audio_pad_warning_delta) warning_count++;
    if (r.a_src_is_null) a_src_null_count++;
  }
  if (m.fence_audio_pad_warning_count != 0 || a_src_null_count != 0) {
    size_t start = 0;
    for (size_t i = 0; i < pad_ticks.size(); i++) {
      if (pad_ticks[i].fence_audio_pad_warning_delta || pad_ticks[i].a_src_is_null) {
        start = (i >= 5) ? i - 5 : 0;
        int show = 10;
        for (size_t j = start; j < pad_ticks.size() && show > 0; j++, show--) {
          const auto& t = pad_ticks[j];
          printf("  tick=%" PRId64 " decision=%s a_src_is_null=%d warning_delta=%d\n",
                 t.tick_index, t.decision.c_str(), t.a_src_is_null ? 1 : 0,
                 t.fence_audio_pad_warning_delta);
        }
        break;
      }
    }
  }
  EXPECT_EQ(m.fence_audio_pad_warning_count, 0)
      << "60fps: no FENCE_AUDIO_PAD during PADDED_GAP (hypothesis disproven: 60fps does not "
         "reproduce a_src==null in this harness)";
  EXPECT_EQ(a_src_null_count, 0)
      << "60fps: no a_src_is_null ticks during PAD (hypothesis disproven)";
}

}  // namespace
}  // namespace retrovue::blockplan::testing
