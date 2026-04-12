// Repository: Retrovue-playout
// Component: Demand-Driven Producer Contract Tests
// Purpose: Verify INV-PRODUCER-DEMAND-DRIVEN-001
// Contract: Decode must not advance without tick consumption.
// Copyright (c) 2026 RetroVue

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
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

class DemandDrivenProducerTest : public ::testing::Test {
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
    callbacks.on_session_ended = [this](const std::string&, int64_t) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      session_ended_count_++;
    };
    return std::make_unique<PipelineManager>(
        ctx_.get(), std::move(callbacks), test_ts_,
        test_infra::MakeTestOutputClock(ctx_->fps.num, ctx_->fps.den, test_ts_),
        PipelineManagerOptions{0},
        std::make_shared<TestProducerFactory>());
  }

  static FedBlock MakeBlock(const std::string& id, int64_t dur_ms,
                             int64_t start = 1'000'000'000LL) {
    FedBlock block;
    block.block_id = id;
    block.channel_id = 99;
    block.start_utc_ms = start;
    block.end_utc_ms = start + dur_ms;
    FedBlock::Segment seg;
    seg.segment_index = 0;
    seg.asset_uri = "/nonexistent/test.mp4";
    seg.asset_start_offset_ms = 0;
    seg.segment_duration_ms = dur_ms;
    block.segments.push_back(seg);
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
};

// =============================================================================
// INV-PRODUCER-DEMAND-DRIVEN-001
//
// After advancing N ticks into block 1, the live video buffer should have
// pushed approximately N frames (proportional to tick consumption).
// If pushed >> consumed, decode is running ahead of demand.
//
// We use video_buffer_frames_pushed vs video_buffer_frames_popped.
// A demand-driven system keeps pushed - popped bounded by the buffer
// target depth (typically 32). A push-based system lets the gap grow
// unboundedly.
// =============================================================================

TEST_F(DemandDrivenProducerTest, VideoBufferGrowthProportionalToConsumption) {
  FedBlock block1 = MakeBlock("demand-1", 60000);  // 60s = 1800 frames
  FedBlock block2 = MakeBlock("demand-2", 60000, block1.end_utc_ms);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block1);
    ctx_->block_queue.push_back(block2);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Advance 300 ticks (~10s at 30fps) into block 1
  retrovue::blockplan::test_utils::AdvanceUntilFenceOrFail(engine_.get(), 300);

  auto m = engine_->SnapshotMetrics();
  int64_t buffered = m.video_buffer_frames_pushed - m.video_buffer_frames_popped;

  // INV-PRODUCER-DEMAND-DRIVEN-001: The buffered-but-unconsumed frame count
  // must be bounded. A reasonable target is < 128 frames (~4 seconds).
  // An unbounded push-based fill loop would accumulate thousands.
  constexpr int64_t kMaxAcceptableBuffered = 128;

  EXPECT_LE(buffered, kMaxAcceptableBuffered)
      << "INV-PRODUCER-DEMAND-DRIVEN-001 VIOLATED: video buffer has "
      << buffered << " unconsumed frames (pushed=" << m.video_buffer_frames_pushed
      << " popped=" << m.video_buffer_frames_popped
      << "). Decode is advancing without proportional consumption.";

  engine_->Stop();
}

}  // namespace
}  // namespace retrovue::blockplan::testing
