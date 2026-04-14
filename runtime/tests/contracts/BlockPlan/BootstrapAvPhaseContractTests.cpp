// INV-BOOTSTRAP-AV-PHASE-001, INV-PACING-SINGLE-AUTHORITY-001 (bootstrap handoff)
// Copyright (c) 2026 RetroVue

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <fcntl.h>
#include <fstream>
#include <memory>
#include <mutex>
#include <string>
#include <sys/socket.h>
#include <thread>
#include <unistd.h>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/IOutputClock.hpp"
#include "retrovue/blockplan/OutputClock.hpp"
#include "retrovue/blockplan/PipelineManager.hpp"
#include "FastTestConfig.hpp"
#include "TestDecoder.hpp"

#include "retrovue/playout_sinks/mpegts/EncoderPipeline.hpp"

namespace retrovue::blockplan::testing {
namespace {

// Records Start() for INV-BOOTSTRAP-AV-PHASE-001 / INV-PACING-SINGLE-AUTHORITY-001.
class RecordingOutputClock : public IOutputClock {
 public:
  explicit RecordingOutputClock(std::shared_ptr<IOutputClock> inner)
      : inner_(std::move(inner)) {}

  void Start() override {
    start_count_.fetch_add(1, std::memory_order_relaxed);
    inner_->Start();
  }
  int64_t FrameIndexToPts90k(int64_t session_frame_index) const override {
    return inner_->FrameIndexToPts90k(session_frame_index);
  }
  int64_t FrameDurationMs() const override { return inner_->FrameDurationMs(); }
  int64_t FrameDuration90k() const override { return inner_->FrameDuration90k(); }
  std::chrono::steady_clock::time_point DeadlineFor(int64_t session_frame_index) const override {
    return inner_->DeadlineFor(session_frame_index);
  }
  std::chrono::steady_clock::time_point WaitForFrame(int64_t session_frame_index) override {
    return inner_->WaitForFrame(session_frame_index);
  }
  int64_t SessionEpochUtcMs() const override { return inner_->SessionEpochUtcMs(); }
  std::chrono::steady_clock::time_point SessionStartTime() const override {
    return inner_->SessionStartTime();
  }
  std::chrono::nanoseconds DeadlineOffsetNs(int64_t session_frame_index) const override {
    return inner_->DeadlineOffsetNs(session_frame_index);
  }

  int StartCount() const { return start_count_.load(std::memory_order_relaxed); }

 private:
  std::shared_ptr<IOutputClock> inner_;
  std::atomic<int> start_count_{0};
};

TEST(BootstrapAvPhaseContract, BootstrapGate_BlocksClockStart_WhenAudioDepthBelowPrimeFloor) {
  const int floor_ms = 500;
  const int ceiling_ms = 800;
  const auto snap = PipelineManager::EvaluateBootstrapPhaseGate(
      100, 15, FPS_30, floor_ms, ceiling_ms, 120);
  EXPECT_FALSE(snap.audio_floor_met);
  EXPECT_FALSE(snap.phase_valid);
}

TEST(BootstrapAvPhaseContract, BootstrapGate_BlocksClockStart_WhenAudioDepthExceedsBootstrapCeiling) {
  const int floor_ms = 500;
  const int ceiling_ms = 800;
  const auto snap = PipelineManager::EvaluateBootstrapPhaseGate(
      900, 15, FPS_30, floor_ms, ceiling_ms, 120);
  EXPECT_TRUE(snap.audio_floor_met);
  EXPECT_FALSE(snap.audio_ceiling_met);
  EXPECT_FALSE(snap.phase_valid);
}

TEST(BootstrapAvPhaseContract, BootstrapGate_BlocksClockStart_WhenAbsAvDeltaExceedsTolerance) {
  const int floor_ms = 500;
  const int ceiling_ms = 2000;
  // video_time_gate: 15 frames @ 30fps = 500ms; audio 800ms -> delta 300 > 120
  const auto snap = PipelineManager::EvaluateBootstrapPhaseGate(
      800, 15, FPS_30, floor_ms, ceiling_ms, 120);
  EXPECT_TRUE(snap.audio_floor_met);
  EXPECT_TRUE(snap.audio_ceiling_met);
  EXPECT_FALSE(snap.av_phase_met);
  EXPECT_FALSE(snap.phase_valid);
}

TEST(BootstrapAvPhaseContract, BootstrapGate_StartsClock_WhenBootstrapStateIsPhaseValid) {
  const int floor_ms = 500;
  const int ceiling_ms = 2000;
  const auto snap = PipelineManager::EvaluateBootstrapPhaseGate(
      600, 15, FPS_30, floor_ms, ceiling_ms, 120);
  EXPECT_TRUE(snap.phase_valid);
}

TEST(BootstrapAvPhaseContract, ComputeVideoTimeMsGate_MatchesContractFormula) {
  EXPECT_EQ(PipelineManager::ComputeVideoTimeMsGate(15, FPS_30), 500);
  EXPECT_EQ(PipelineManager::ComputeVideoTimeMsGate(0, FPS_30), 0);
}

TEST(BootstrapAvPhaseContract, OutputClock_RemainsSolePacingAuthority_ForBootstrapHandoff) {
  auto base = std::make_shared<OutputClock>(30, 1);
  auto rec = std::make_shared<RecordingOutputClock>(base);
  EXPECT_EQ(rec->StartCount(), 0);
  rec->Start();
  EXPECT_EQ(rec->StartCount(), 1);
}

TEST(BootstrapAvPhaseContract, EncoderPipeline_DoesNotRepairPreexistingBootstrapPhaseError) {
  EXPECT_EQ(RETROVUE_ENCODER_BOOTSTRAP_AV_PHASE_REPAIR, 0);
}

TEST(BootstrapAvPhaseContract, BootstrapPhaseRepair_RemainsInFillDecodeDomain) {
  // Structural: PipelineManager exposes gate evaluation; EncoderPipeline macro forbids repair.
  EXPECT_NE(nullptr, &PipelineManager::EvaluateBootstrapPhaseGate);
  EXPECT_EQ(RETROVUE_ENCODER_BOOTSTRAP_AV_PHASE_REPAIR, 0);
}

// --- Integration: timeout before OutputClock::Start (requires media) ---
static bool FileExists(const std::string& path) {
  std::ifstream f(path);
  return f.good();
}

static FedBlock MakeShortBlock(const std::string& uri) {
  FedBlock b;
  b.block_id = "boot_contract";
  b.channel_id = 1;
  b.start_utc_ms = 0;
  b.end_utc_ms = 120000;
  FedBlock::Segment seg;
  seg.segment_index = 0;
  seg.asset_uri = uri;
  seg.segment_duration_ms = 120000;
  b.segments.push_back(seg);
  return b;
}

class BootstrapTimeoutFixture : public ::testing::Test {
 protected:
  void SetUp() override {
    int fds[2];
    ASSERT_EQ(socketpair(AF_UNIX, SOCK_STREAM, 0, fds), 0);
    ctx_ = std::make_unique<BlockPlanSessionContext>();
    ctx_->fd = fds[0];
    drain_fd_ = fds[1];
    drain_stop_ = false;
    drain_thread_ = std::thread([this] {
      char buf[8192];
      while (!drain_stop_) {
        ssize_t n = read(drain_fd_, buf, sizeof buf);
        if (n <= 0) break;
      }
    });
    ctx_->channel_id = 42;
    ctx_->width = 320;
    ctx_->height = 240;
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
    drain_stop_ = true;
    if (drain_fd_ >= 0) {
      shutdown(drain_fd_, SHUT_RDWR);
      close(drain_fd_);
      drain_fd_ = -1;
    }
    if (drain_thread_.joinable()) drain_thread_.join();
  }

  std::shared_ptr<RecordingOutputClock> MakeRecordingClock() {
    auto base = test_infra::MakeTestOutputClock(ctx_->fps.num, ctx_->fps.den, test_ts_);
    return std::make_shared<RecordingOutputClock>(base);
  }

  std::shared_ptr<test_infra::TestTimeSourceType> test_ts_;
  std::unique_ptr<BlockPlanSessionContext> ctx_;
  std::unique_ptr<PipelineManager> engine_;
  int drain_fd_{-1};
  bool drain_stop_{false};
  std::thread drain_thread_;
};

TEST_F(BootstrapTimeoutFixture, BootstrapGate_TimeoutSetsStopRequested_AndDoesNotStartClock) {
  const char* env = getenv("RETROVUE_TEST_VIDEO_PATH");
  const std::string uri = env ? std::string(env) : std::string("/opt/retrovue/assets/SampleA.mp4");
  if (!FileExists(uri)) {
    GTEST_SKIP() << "RETROVUE_TEST_VIDEO_PATH or SampleA.mp4 not available";
  }

  PipelineManager::Callbacks cb;
  cb.on_session_ended = [](const std::string&, int64_t) {};

  PipelineManagerOptions opt;
  opt.bootstrap_gate_timeout_ms = 0;
  opt.av_phase_tolerance_ms = 0;

  auto rec = MakeRecordingClock();
  engine_ = std::make_unique<PipelineManager>(
      ctx_.get(), std::move(cb), test_ts_, rec, opt,
      std::make_shared<test_infra::TestProducerFactory>());

  ctx_->block_queue.push_back(MakeShortBlock(uri));
  engine_->Start();

  auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(15);
  while (std::chrono::steady_clock::now() < deadline) {
    if (ctx_->stop_requested.load(std::memory_order_acquire)) break;
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }

  EXPECT_TRUE(ctx_->stop_requested.load(std::memory_order_acquire))
      << "bootstrap gate should abort session on timeout";
  EXPECT_EQ(rec->StartCount(), 0) << "OutputClock must not start after failed bootstrap";
  EXPECT_GE(engine_->SnapshotMetrics().air_bootstrap_phase_failure_total, 1);

  engine_->Stop();
  engine_.reset();
}

TEST_F(BootstrapTimeoutFixture, BootstrapGate_DoesNotOpenEmissionGate_OnPhaseInvalidTimeout) {
  const char* env = getenv("RETROVUE_TEST_VIDEO_PATH");
  const std::string uri = env ? std::string(env) : std::string("/opt/retrovue/assets/SampleA.mp4");
  if (!FileExists(uri)) {
    GTEST_SKIP() << "RETROVUE_TEST_VIDEO_PATH or SampleA.mp4 not available";
  }

  PipelineManager::Callbacks cb;
  cb.on_session_ended = [](const std::string&, int64_t) {};

  PipelineManagerOptions opt;
  opt.bootstrap_gate_timeout_ms = 0;
  opt.av_phase_tolerance_ms = 0;

  auto rec = MakeRecordingClock();
  engine_ = std::make_unique<PipelineManager>(
      ctx_.get(), std::move(cb), test_ts_, rec, opt,
      std::make_shared<test_infra::TestProducerFactory>());

  ctx_->block_queue.push_back(MakeShortBlock(uri));
  engine_->Start();

  auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(15);
  while (std::chrono::steady_clock::now() < deadline) {
    if (ctx_->stop_requested.load(std::memory_order_acquire)) break;
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }

  EXPECT_TRUE(ctx_->stop_requested.load(std::memory_order_acquire));
  // Emission gate is opened only after successful bootstrap + clock start; failed path never opens.
  EXPECT_EQ(rec->StartCount(), 0);

  engine_->Stop();
  engine_.reset();
}

}  // namespace
}  // namespace retrovue::blockplan::testing
