// Repository: Retrovue-playout
// Component: INV-PREROLL-UNDECODABLE-RELEASE Contract Tests
// Purpose: When preview_ (block B) has a permanently dead decoder, the system
//          must release it so PADDED_GAP can fire and Core can feed the next block.
//          Without the release, may_rotate is permanently false (b_primed=0,
//          !preview_=false) and the pipeline emits pad frames indefinitely.
// Copyright (c) 2026 RetroVue

#include <gtest/gtest.h>

#include <atomic>
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
#include "retrovue/blockplan/SeamProofTypes.hpp"
#include "retrovue/util/Logger.hpp"
#include "FastTestConfig.hpp"
#include "TestDecoder.hpp"
#include "deterministic_tick_driver.hpp"

namespace retrovue::blockplan::testing {
namespace {

using test_infra::kBlockTimeOffsetMs;
using test_infra::kStdBlockMs;
using test_infra::kLongBlockMs;

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

class UndecodablePreviewReleaseTest : public ::testing::Test {
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

  std::unique_ptr<PipelineManager> MakeEngine(
      std::shared_ptr<IProducerFactory> factory) {
    PipelineManager::Callbacks callbacks;
    callbacks.on_block_completed = [this](const FedBlock& block, int64_t, int64_t) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      completed_blocks_.push_back(block.block_id);
      blocks_completed_cv_.notify_all();
    };
    callbacks.on_session_ended = [this](const std::string&, int64_t) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      session_ended_count_++;
    };
    callbacks.on_frame_emitted = [](const FrameFingerprint&) {};
    callbacks.on_seam_transition = [](const SeamTransitionLog&) {};
    callbacks.on_block_summary = [](const BlockPlaybackSummary&) {};
    return std::make_unique<PipelineManager>(
        ctx_.get(), std::move(callbacks), test_ts_,
        test_infra::MakeTestOutputClock(ctx_->fps.num, ctx_->fps.den, test_ts_),
        PipelineManagerOptions{0},
        factory);
  }

  std::shared_ptr<test_infra::TestTimeSourceType> test_ts_;
  std::unique_ptr<BlockPlanSessionContext> ctx_;
  std::unique_ptr<PipelineManager> engine_;
  int drain_fd_ = -1;
  std::atomic<bool> drain_stop_{false};
  std::thread drain_thread_;

  std::mutex cb_mutex_;
  std::condition_variable blocks_completed_cv_;
  std::vector<std::string> completed_blocks_;
  int session_ended_count_ = 0;

  std::vector<std::string> error_log_lines_;
  void InstallErrorSink() {
    error_log_lines_.clear();
    retrovue::util::Logger::SetErrorSink(
        [this](const std::string& line) { error_log_lines_.push_back(line); });
  }
  void ClearErrorSink() {
    retrovue::util::Logger::SetErrorSink(nullptr);
  }
};

// =============================================================================
// INV-PREROLL-UNDECODABLE-RELEASE: When B's decoder permanently fails, the
// system must release preview_ so the PADDED_GAP path can fire, on_block_completed
// emits, and the pipeline does not stall indefinitely.
// =============================================================================
TEST_F(UndecodablePreviewReleaseTest, DeadPreviewReleasedAtFence_BlockCompletes) {
  auto now = NowMs();
  int64_t offset = kBlockTimeOffsetMs;

  // Block A (healthy) → Block B (dead decoder).
  // After A's fence, B is loaded but HasDecoder()=false and never primes.
  // The fix must release B so on_block_completed fires for A.
  FedBlock block_a = MakeBlock("undec-a", now + offset, kStdBlockMs, "test://a.mp4");
  FedBlock block_b = MakeBlock("undec-b", block_a.end_utc_ms, kStdBlockMs, "test://b.mp4");

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  // ProbeFailProducerFactory: producer #3 (the preview/preroll producer for B)
  // uses DeadDecoderTestDecoder which simulates permanent probe failure.
  auto factory = std::make_shared<test_infra::ProbeFailProducerFactory>(3);
  engine_ = MakeEngine(factory);
  engine_->Start();

  // Block A must complete — the dead preview must be released so
  // on_block_completed fires and the pipeline enters PADDED_GAP.
  bool completed = retrovue::blockplan::test_utils::WaitForBounded(
      [this] {
        std::lock_guard<std::mutex> lock(cb_mutex_);
        return !completed_blocks_.empty();
      },
      200000, 20000);

  engine_->Stop();

  ASSERT_TRUE(completed)
      << "INV-PREROLL-UNDECODABLE-RELEASE: Block A must complete even when B "
         "has a permanently dead decoder. Without the fix, may_rotate is "
         "permanently false and on_block_completed never fires.";

  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_EQ(completed_blocks_.front(), "undec-a")
        << "First completed block must be A";
  }

  // Pipeline must have entered PADDED_GAP (proves dead preview was released).
  auto m = engine_->SnapshotMetrics();
  EXPECT_GE(m.padded_gap_count, 1u)
      << "Must enter PADDED_GAP after releasing dead preview";
}

// =============================================================================
// Regression: Healthy preview must NOT be released by the guard.
// =============================================================================
TEST_F(UndecodablePreviewReleaseTest, HealthyPreview_NotReleased_NormalTransition) {
  auto now = NowMs();
  int64_t offset = kBlockTimeOffsetMs;

  // Both blocks healthy — normal A→B seamless transition.
  FedBlock block_a = MakeBlock("healthy-a", now + offset, kStdBlockMs, "test://a.mp4");
  FedBlock block_b = MakeBlock("healthy-b", block_a.end_utc_ms, kLongBlockMs, "test://b.mp4");

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  // Normal factory — all producers healthy.
  auto factory = std::make_shared<test_infra::TestProducerFactory>();
  engine_ = MakeEngine(factory);
  engine_->Start();

  // Block A must complete via normal seamless transition.
  bool completed = retrovue::blockplan::test_utils::WaitForBounded(
      [this] {
        std::lock_guard<std::mutex> lock(cb_mutex_);
        return !completed_blocks_.empty();
      },
      200000, 20000);

  engine_->Stop();

  ASSERT_TRUE(completed)
      << "Block A must complete normally with healthy preview";

  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_EQ(completed_blocks_.front(), "healthy-a");
  }

  // Normal transition — no PADDED_GAP needed (proves guard did not fire).
  auto m = engine_->SnapshotMetrics();
  EXPECT_EQ(m.padded_gap_count, 0u)
      << "Healthy A→B must not enter PADDED_GAP";
}

}  // namespace
}  // namespace retrovue::blockplan::testing
