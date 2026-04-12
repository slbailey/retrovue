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
#include <vector>

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
      // Last segment is filler, rest are content
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
// INV-SEAM-CONTINUITY-GUARANTEED-001: Four-segment block
//
// A block with 4 segments (intro + ratings + movie + filler) MUST:
// 1. Complete (reach block fence)
// 2. Fire all 3 segment transitions (segment_seam_count >= 3)
// 3. Arm segment prep for each transition (segment_prep_armed_count >= 1)
// 4. Have zero seam misses (segment_seam_miss_count == 0)
// =============================================================================

TEST_F(SeamContinuityGuaranteedTest, FourSegmentBlockAllTransitionsFire) {
  // intro(2s/60f) + ratings(1s/30f) + movie(5s/150f) + filler(2s/60f) = 10s/300f
  FedBlock block = MakeMultiSegmentBlock("seam-4seg", {2000, 1000, 5000, 2000});
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Advance past entire block
  retrovue::blockplan::test_utils::AdvanceUntilFenceOrFail(engine_.get(), 350);

  auto m = engine_->SnapshotMetrics();

  // INV-SEAM-CONTINUITY-GUARANTEED-001: All segment transitions must fire.
  // 4 segments = 3 transitions (0→1, 1→2, 2→3).
  EXPECT_GE(m.segment_seam_count, 3)
      << "INV-SEAM-CONTINUITY-GUARANTEED-001 VIOLATED: expected >= 3 segment "
      << "transitions for a 4-segment block, got " << m.segment_seam_count;

  // Segment prep must have been armed at least once (for non-PAD transitions).
  EXPECT_GE(m.segment_prep_armed_count, 1)
      << "INV-SEAM-CONTINUITY-GUARANTEED-001 VIOLATED: segment prep was never "
      << "armed — ArmSegmentPrep likely returned early";

  // Zero seam misses — every transition must have been ready.
  EXPECT_EQ(m.segment_seam_miss_count, 0)
      << "INV-SEAM-CONTINUITY-GUARANTEED-001 VIOLATED: " << m.segment_seam_miss_count
      << " segment transition(s) were not ready at seam frame";

  engine_->Stop();
}

// =============================================================================
// INV-SEAM-CONTINUITY-GUARANTEED-001: Two-segment block (JIP pattern)
// =============================================================================

TEST_F(SeamContinuityGuaranteedTest, TwoSegmentBlockTransitionFires) {
  // content(5s/150f) + filler(5s/150f) = 10s/300f
  FedBlock block = MakeMultiSegmentBlock("seam-2seg", {5000, 5000});
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  retrovue::blockplan::test_utils::AdvanceUntilFenceOrFail(engine_.get(), 350);

  auto m = engine_->SnapshotMetrics();

  // 2 segments = 1 transition
  EXPECT_GE(m.segment_seam_count, 1)
      << "INV-SEAM-CONTINUITY-GUARANTEED-001 VIOLATED: expected >= 1 segment "
      << "transition for a 2-segment block, got " << m.segment_seam_count;

  EXPECT_EQ(m.segment_seam_miss_count, 0)
      << "INV-SEAM-CONTINUITY-GUARANTEED-001 VIOLATED: seam miss on 2-segment block";

  engine_->Stop();
}

// =============================================================================
// INV-SEAM-CONTINUITY-GUARANTEED-001: Short presentation segments
//
// Segments < 1 second have minimal headroom for seam prep. The engine
// must still arm and complete prep before the seam frame.
// =============================================================================

TEST_F(SeamContinuityGuaranteedTest, ShortSegmentsAllTransitionsFire) {
  // intro(500ms/15f) + ratings(200ms/6f) + content(8300ms/249f) + filler(1000ms/30f) = 10s
  FedBlock block = MakeMultiSegmentBlock("seam-short", {500, 200, 8300, 1000});
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  retrovue::blockplan::test_utils::AdvanceUntilFenceOrFail(engine_.get(), 350);

  auto m = engine_->SnapshotMetrics();

  // 4 segments = 3 transitions
  EXPECT_GE(m.segment_seam_count, 3)
      << "INV-SEAM-CONTINUITY-GUARANTEED-001 VIOLATED: short-segment block "
      << "expected >= 3 transitions, got " << m.segment_seam_count;

  EXPECT_EQ(m.segment_seam_miss_count, 0)
      << "INV-SEAM-CONTINUITY-GUARANTEED-001 VIOLATED: seam miss with short segments";

  engine_->Stop();
}

}  // namespace
}  // namespace retrovue::blockplan::testing
