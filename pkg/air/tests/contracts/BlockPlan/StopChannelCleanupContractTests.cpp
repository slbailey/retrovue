// Repository: Retrovue-playout
// Component: StopChannel Cleanup Contract Tests
// Purpose: Verify AIR-007 — After PipelineManager::Stop() (the Phase 8+
//          equivalent of StopChannel), all producer decoders are stopped
//          and no orphan decode threads remain active.
//
//          "All producers MUST stop; MUST NOT leave orphan ffmpeg processes.
//          Resources MUST be released."  — CANONICAL_RULE_LEDGER.md §AIR-007
//
//          In Phase 8 architecture, FFmpeg runs as a library (not subprocess).
//          "Orphan ffmpeg process" maps to: TickProducer / TestDecoder still
//          reporting isRunning()==true after PipelineManager::Stop() returns.
//
// Contract Reference: PlayoutEngineContract.md §StopChannel; AIR-007
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <string>
#include <sys/socket.h>
#include <thread>
#include <unistd.h>
#include <vector>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/IProducerFactory.hpp"
#include "retrovue/blockplan/ITickProducer.hpp"
#include "retrovue/blockplan/PipelineManager.hpp"
#include "retrovue/blockplan/PipelineMetrics.hpp"
#include "retrovue/producers/IProducer.h"
#include "FastTestConfig.hpp"
#include "TestDecoder.hpp"
#include "deterministic_tick_driver.hpp"

namespace retrovue::blockplan::testing {
namespace {

// =============================================================================
// TrackingProducerFactory
// =============================================================================

class TrackingTestDecoder : public producers::IProducer,
                             public ITickProducer {
 public:
  TrackingTestDecoder(int width, int height, RationalFps fps,
                      std::shared_ptr<std::atomic<int>> running_count)
      : inner_(width, height, fps),
        running_count_(std::move(running_count)) {}

  // --- IProducer ---
  bool start() override {
    bool ok = inner_.start();
    if (ok) running_count_->fetch_add(1, std::memory_order_relaxed);
    return ok;
  }
  void stop() override {
    if (inner_.isRunning()) {
      inner_.stop();
      running_count_->fetch_sub(1, std::memory_order_relaxed);
    } else {
       inner_.stop();
    }
  }
  bool isRunning() const override { return inner_.isRunning(); }
  void RequestStop() override { inner_.RequestStop(); }
  bool IsStopped() const override { return inner_.IsStopped(); }

  // --- ITickProducer ---
  void AssignBlock(const FedBlock& b) override { inner_.AssignBlock(b); }
  std::optional<FrameData> TryGetFrame() override { return inner_.TryGetFrame(); }
  void Reset() override { inner_.Reset(); }
  State GetState() const override { return inner_.GetState(); }
  const FedBlock& GetBlock() const override { return inner_.GetBlock(); }
  int64_t FramesPerBlock() const override { return inner_.FramesPerBlock(); }
  bool HasDecoder() const override { return inner_.HasDecoder(); }
  RationalFps GetInputRationalFps() const override { return inner_.GetInputRationalFps(); }
  bool HasPrimedFrame() const override { return inner_.HasPrimedFrame(); }
  bool HasAudioStream() const override { return inner_.HasAudioStream(); }
  const std::vector<SegmentBoundary>& GetBoundaries() const override { return inner_.GetBoundaries(); }
  int64_t GetFrameIndex() const override { return inner_.GetFrameIndex(); }
  void SetInterruptFlags(const InterruptFlags& f) override { inner_.SetInterruptFlags(f); }
  
  ResampleMode GetResampleMode() const override { return inner_.GetResampleMode(); }
  int64_t GetDropStep() const override { return inner_.GetDropStep(); }

 private:
  test_infra::TestDecoder inner_;
  std::shared_ptr<std::atomic<int>> running_count_;
};

class TrackingProducerFactory : public IProducerFactory {
 public:
  explicit TrackingProducerFactory()
      : running_count_(std::make_shared<std::atomic<int>>(0)) {}

  std::unique_ptr<producers::IProducer> Create(
      int width, int height, RationalFps output_fps) override {
    create_count_.fetch_add(1, std::memory_order_relaxed);
    return std::make_unique<TrackingTestDecoder>(width, height, output_fps,
                                                 running_count_);
  }

  int RunningCount() const {
    return running_count_->load(std::memory_order_acquire);
  }
  int CreateCount() const {
    return create_count_.load(std::memory_order_relaxed);
  }

 private:
  std::shared_ptr<std::atomic<int>> running_count_;
  std::atomic<int> create_count_{0};
};

// =============================================================================
// Test Fixture
// =============================================================================

class StopChannelCleanupContractTest : public ::testing::Test {
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
    factory_ = std::make_shared<TrackingProducerFactory>();
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
    callbacks.on_session_ended = [this](const std::string& reason, int64_t) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      session_ended_ = true;
      session_ended_reason_ = reason;
      session_ended_cv_.notify_all();
    };
    callbacks.on_block_completed = [this](const FedBlock&, int64_t, int64_t) {};
    callbacks.on_block_started = [this](const FedBlock&, const BlockActivationContext&) {};
    return std::make_unique<PipelineManager>(
        ctx_.get(), std::move(callbacks), test_ts_,
        test_infra::MakeTestOutputClock(ctx_->fps.num, ctx_->fps.den, test_ts_),
        PipelineManagerOptions{0},
        factory_);
  }

  bool WaitForSessionEndedBounded(int64_t max_ms = 5000) {
    std::unique_lock<std::mutex> lock(cb_mutex_);
    return session_ended_cv_.wait_for(
        lock, std::chrono::milliseconds(max_ms),
        [this] { return session_ended_; });
  }

  // Use dynamic time to ensure block is current
  FedBlock MakeSyntheticBlock(const std::string& id, int64_t duration_ms) {
    FedBlock block;
    block.block_id = id;
    block.channel_id = 99;
    
    // Use test_ts_ to get current time, plus offset for fence guard
    int64_t now_ms = test_infra::NowMs(test_ts_) + test_infra::kBlockTimeOffsetMs;
    
    block.start_utc_ms = now_ms;
    block.end_utc_ms = now_ms + duration_ms;
    FedBlock::Segment seg;
    seg.segment_index = 0;
    seg.asset_uri = "test://synthetic";
    seg.asset_start_offset_ms = 0;
    seg.segment_duration_ms = duration_ms;
    block.segments.push_back(seg);
    return block;
  }

  std::unique_ptr<BlockPlanSessionContext> ctx_;
  std::shared_ptr<test_infra::TestTimeSourceType> test_ts_;
  std::shared_ptr<TrackingProducerFactory> factory_;
  std::unique_ptr<PipelineManager> engine_;
  int drain_fd_ = -1;
  std::thread drain_thread_;
  std::atomic<bool> drain_stop_{false};

  std::mutex cb_mutex_;
  std::condition_variable session_ended_cv_;
  bool session_ended_ = false;
  std::string session_ended_reason_;
};

// =============================================================================
// AIR-007 — Compliant scenario: Stop() releases all producers.
// =============================================================================
TEST_F(StopChannelCleanupContractTest,
       AIR007_StopReleasesAllProducers_NoOrphans) {
  // Arrange: push a 30s block.
  FedBlock block = MakeSyntheticBlock("air007-live", 30000);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Advance until the engine has emitted a few frames (producer is live).
  const int64_t kFewFrames = 5;
  retrovue::blockplan::test_utils::AdvanceUntilFenceOrFail(engine_.get(), kFewFrames);

  ASSERT_GE(factory_->CreateCount(), 1)
      << "PipelineManager must have created at least one producer via factory";

  // Act: Stop the engine (AIR-007: StopChannel equivalent).
  engine_->Stop();

  // Assert (1): on_session_ended fires.
  ASSERT_TRUE(WaitForSessionEndedBounded())
      << "on_session_ended must fire after Stop()";

  // Assert (2): No orphan producers.
  EXPECT_EQ(factory_->RunningCount(), 0)
      << "AIR-007: All producers must be stopped after PipelineManager::Stop().";
}

// =============================================================================
// AIR-007 — Compliant scenario: Stop() with preview loaded (two producers).
// =============================================================================
TEST_F(StopChannelCleanupContractTest,
       AIR007_StopWithPreviewLoaded_BothProducersStopped) {
  // Arrange: push two blocks (use current time).
  // Note: MakeSyntheticBlock updates start_utc_ms based on Now().
  // We need sequential blocks.
  
  int64_t now_ms = test_infra::NowMs(test_ts_) + test_infra::kBlockTimeOffsetMs;
  int64_t duration = 30000;
  
  FedBlock block_a;
  block_a.block_id = "air007-a";
  block_a.channel_id = 99;
  block_a.start_utc_ms = now_ms;
  block_a.end_utc_ms = now_ms + duration;
  FedBlock::Segment seg_a;
  seg_a.asset_uri = "test://a";
  seg_a.segment_duration_ms = duration;
  block_a.segments.push_back(seg_a);

  FedBlock block_b;
  block_b.block_id = "air007-b";
  block_b.channel_id = 99;
  block_b.start_utc_ms = now_ms + duration;
  block_b.end_utc_ms = now_ms + duration * 2;
  FedBlock::Segment seg_b;
  seg_b.asset_uri = "test://b";
  seg_b.segment_duration_ms = duration;
  block_b.segments.push_back(seg_b);

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Advance enough that preview_ is likely being preloaded.
  const int64_t kFrames = 10;
  retrovue::blockplan::test_utils::AdvanceUntilFenceOrFail(engine_.get(), kFrames);

  // Act.
  engine_->Stop();

  ASSERT_TRUE(WaitForSessionEndedBounded())
      << "on_session_ended must fire after Stop()";

  // Assert: all started producers are stopped.
  EXPECT_EQ(factory_->RunningCount(), 0)
      << "AIR-007: All producers (live_ and preview_) must be stopped.";
}

// =============================================================================
// AIR-007 — Violation scenario: verify the tracking mechanism detects leaks.
// =============================================================================
TEST_F(StopChannelCleanupContractTest,
       AIR007_TrackingDetectsOrphan_MetaTest) {
  auto inner_count = std::make_shared<std::atomic<int>>(0);
  auto orphan = std::make_unique<TrackingTestDecoder>(
      640, 480, FPS_30, inner_count);

  orphan->start();
  EXPECT_EQ(inner_count->load(), 1)
      << "Tracking must report 1 running producer after start()";

  orphan.reset();  // destructor but no stop() was called!

  // Verify the count remains at 1
  EXPECT_EQ(inner_count->load(), 1)
      << "Meta-test: count should still be 1 because stop() was not called.";
}

}  // namespace
}  // namespace retrovue::blockplan::testing
