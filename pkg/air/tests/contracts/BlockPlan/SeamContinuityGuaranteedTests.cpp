// Repository: Retrovue-playout
// Component: Seam Continuity Guaranteed Contract Tests
// Purpose: Verify INV-SEAM-CONTINUITY-GUARANTEED-001
// Contract: For every scheduled segment boundary, playout MUST transition
//           seamlessly into the next segment with valid A/V output.
// Copyright (c) 2026 RetroVue

#include <gtest/gtest.h>

#include <atomic>
#include <mutex>
#include <string>
#include <sys/socket.h>
#include <thread>
#include <unistd.h>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/PipelineManager.hpp"
#include "retrovue/blockplan/PipelineMetrics.hpp"
#include "retrovue/blockplan/OutputClock.hpp"
#include "FastTestConfig.hpp"
#include "TestDecoder.hpp"
#include "deterministic_tick_driver.hpp"

namespace retrovue::blockplan::testing {
namespace {

using test_infra::TestProducerFactory;

// =============================================================================
// Fixture
// =============================================================================

class SeamContinuityGuaranteedTest : public ::testing::Test {
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
    };
    callbacks.on_session_ended = [this](const std::string& reason, int64_t) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      session_ended_count_++;
      session_ended_reason_ = reason;
    };
    return std::make_unique<PipelineManager>(
        ctx_.get(), std::move(callbacks), test_ts_,
        test_infra::MakeTestOutputClock(ctx_->fps.num, ctx_->fps.den, test_ts_),
        PipelineManagerOptions{0},
        std::make_shared<TestProducerFactory>());
  }

  // Build a multi-segment block with N content segments + optional filler.
  // Mimics the HBO pattern: intro + ratings card + movie + filler
  static FedBlock MakeMultiSegmentBlock(const std::string& id,
                                         std::vector<int64_t> seg_durations_ms,
                                         int64_t start_utc_ms = 1'000'000'000LL) {
    FedBlock block;
    block.block_id = id;
    block.channel_id = 99;
    int64_t total = 0;
    for (auto d : seg_durations_ms) total += d;
    block.start_utc_ms = start_utc_ms;
    block.end_utc_ms = start_utc_ms + total;

    for (size_t i = 0; i < seg_durations_ms.size(); ++i) {
      FedBlock::Segment s;
      s.segment_index = static_cast<int32_t>(i);
      s.asset_uri = "/nonexistent/seg" + std::to_string(i) + ".mp4";
      s.asset_start_offset_ms = 0;
      s.segment_duration_ms = seg_durations_ms[i];
      s.segment_type = (i == seg_durations_ms.size() - 1)
          ? SegmentType::kFiller : SegmentType::kContent;
      block.segments.push_back(s);
    }
    return block;
  }

  std::shared_ptr<test_infra::TestTimeSourceType> test_ts_;
  std::unique_ptr<BlockPlanSessionContext> ctx_;
  std::unique_ptr<PipelineManager> engine_;
  int drain_fd_ = -1;
  std::atomic<bool> drain_stop_{false};
  std::thread drain_thread_;
  std::mutex cb_mutex_;
  std::vector<std::string> completed_blocks_;
  int session_ended_count_ = 0;
  std::string session_ended_reason_;
};

// =============================================================================
// INV-SEAM-CONTINUITY-GUARANTEED-001: Multi-segment block completes
//
// A block with 4 segments (intro + ratings + movie + filler) must
// transition through all segments. If any transition fails, the block
// never completes — AdvanceUntilFence will stall and the test times out.
// =============================================================================

TEST_F(SeamContinuityGuaranteedTest, FourSegmentBlockCompletesAllTransitions) {
  // intro(2s/60f) + ratings(1s/30f) + movie(5s/150f) + filler(2s/60f) = 10s/300f
  FedBlock block = MakeMultiSegmentBlock("seam-4seg", {2000, 1000, 5000, 2000});
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Advance past the entire block. AdvanceUntilFenceOrFail will GTEST_FAIL
  // if the engine stalls (seam transitions not firing).
  retrovue::blockplan::test_utils::AdvanceUntilFenceOrFail(engine_.get(), 350);

  engine_->Stop();

  // If we reach here, all 3 segment transitions (0→1, 1→2, 2→3) succeeded.
  SUCCEED() << "INV-SEAM-CONTINUITY-GUARANTEED-001: 4-segment block completed";
}

// =============================================================================
// INV-SEAM-CONTINUITY-GUARANTEED-001: Two-segment block transitions
//
// Content→filler is the simplest multi-segment case. This is the JIP
// pattern after presentation segments are skipped.
// =============================================================================

TEST_F(SeamContinuityGuaranteedTest, TwoSegmentBlockTransitionsCleanly) {
  // content(5s/150f) + filler(5s/150f) = 10s/300f
  FedBlock block = MakeMultiSegmentBlock("seam-2seg", {5000, 5000});
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  retrovue::blockplan::test_utils::AdvanceUntilFenceOrFail(engine_.get(), 350);

  engine_->Stop();
  SUCCEED() << "INV-SEAM-CONTINUITY-GUARANTEED-001: 2-segment block completed";
}

// =============================================================================
// INV-SEAM-CONTINUITY-GUARANTEED-001: Short presentation segments
//
// Short segments (< 1 second) have minimal seam-prep headroom. The seam
// preparer must handle tight windows.
// =============================================================================

TEST_F(SeamContinuityGuaranteedTest, ShortPresentationSegmentsTransition) {
  // intro(500ms/15f) + ratings(200ms/6f) + content(8300ms/249f) + filler(1000ms/30f) = 10s
  FedBlock block = MakeMultiSegmentBlock("seam-short", {500, 200, 8300, 1000});
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  retrovue::blockplan::test_utils::AdvanceUntilFenceOrFail(engine_.get(), 350);

  engine_->Stop();
  SUCCEED() << "INV-SEAM-CONTINUITY-GUARANTEED-001: short segments completed";
}

}  // namespace
}  // namespace retrovue::blockplan::testing
