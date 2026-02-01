// Repository: Retrovue-playout
// Component: Phase 10 Frame-Indexed Execution Tests
// Purpose: Verify INV-FRAME-001, INV-FRAME-002, INV-FRAME-003 invariants
// Contract: docs/contracts/laws/PlayoutInvariants-BroadcastGradeGuarantees.md Section 6
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>
#include <chrono>
#include <thread>
#include <atomic>
#include <cmath>

#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/producers/file/FileProducer.h"
#include "retrovue/producers/black/BlackFrameProducer.h"
#include "retrovue/timing/MasterClock.h"
#include "retrovue/timing/TimelineController.h"
#include "retrovue/runtime/ProgramFormat.h"
#include "timing/TestMasterClock.h"

using namespace retrovue;
using namespace retrovue::producers::file;
using namespace retrovue::producers::black;
using namespace retrovue::timing;
using namespace std::chrono_literals;

namespace {

// Test asset path
std::string GetTestVideoPath() {
  const char* env_path = std::getenv("RETROVUE_TEST_VIDEO_PATH");
  if (env_path) return env_path;
  return "/opt/retrovue/assets/SampleA.mp4";
}

// =============================================================================
// Frame-Indexed Execution Test Fixture
// =============================================================================

class FrameIndexedExecutionTest : public ::testing::Test {
 protected:
  void SetUp() override {
    auto now = std::chrono::system_clock::now();
    auto now_us = std::chrono::duration_cast<std::chrono::microseconds>(
        now.time_since_epoch()).count();

    clock_ = std::make_shared<TestMasterClock>(now_us, TestMasterClock::Mode::Deterministic);
    clock_->SetMaxWaitUs(100'000);

    config_ = TimelineConfig::FromFps(30.0);
    config_.early_threshold_us = 10'000'000;
    config_.late_threshold_us = 10'000'000;
    timeline_ = std::make_shared<TimelineController>(clock_, config_);

    ASSERT_TRUE(timeline_->StartSession());
    timeline_->BeginSegmentAbsolute(0, 0);

    // Time advancement thread
    stop_time_thread_ = false;
    time_thread_ = std::thread([this]() {
      while (!stop_time_thread_.load(std::memory_order_acquire)) {
        clock_->AdvanceMicroseconds(1'000);
        std::this_thread::sleep_for(std::chrono::microseconds(100));
      }
    });
  }

  void TearDown() override {
    stop_time_thread_.store(true, std::memory_order_release);
    if (time_thread_.joinable()) {
      time_thread_.join();
    }
    timeline_->EndSession();
  }

  std::shared_ptr<TestMasterClock> clock_;
  std::shared_ptr<TimelineController> timeline_;
  TimelineConfig config_;
  std::thread time_thread_;
  std::atomic<bool> stop_time_thread_{false};
};

// =============================================================================
// INV-FRAME-001: Segment Boundaries Are Frame-Indexed
// =============================================================================
// Given: ProducerConfig with frame_count = N
// When: Producer runs until completion
// Then: Exactly N frames are produced (±0)
// =============================================================================

TEST_F(FrameIndexedExecutionTest, INV_FRAME_001_FrameCountExact_10Frames) {
  // Given: frame_count = 10
  // When: Producer runs
  // Then: Exactly 10 frames produced

  buffer::FrameRingBuffer ring_buffer(60);

  ProducerConfig producer_config;
  producer_config.asset_uri = GetTestVideoPath();
  producer_config.target_width = 640;
  producer_config.target_height = 360;
  producer_config.target_fps = 30.0;
  producer_config.frame_count = 10;  // INV-FRAME-001: frame-indexed boundary

  FileProducer producer(producer_config, ring_buffer, clock_, nullptr, timeline_.get());
  ASSERT_TRUE(producer.start());

  // Wait for producer to complete or timeout
  auto deadline = std::chrono::steady_clock::now() + 5s;
  while (producer.isRunning() && std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(10ms);
  }

  // Producer should have stopped (segment complete)
  // Give a bit more time for the stop to propagate
  std::this_thread::sleep_for(100ms);

  // Count frames in buffer
  int frame_count = 0;
  buffer::Frame frame;
  while (ring_buffer.Pop(frame)) {
    frame_count++;
  }

  producer.stop();

  // INV-FRAME-001: Exactly frame_count frames, no more, no less
  EXPECT_EQ(frame_count, 10)
      << "INV-FRAME-001 violated: Expected exactly 10 frames, got " << frame_count;
}

TEST_F(FrameIndexedExecutionTest, INV_FRAME_001_FrameCountExact_30Frames) {
  // Given: frame_count = 30 (1 second at 30fps)
  buffer::FrameRingBuffer ring_buffer(60);

  ProducerConfig producer_config;
  producer_config.asset_uri = GetTestVideoPath();
  producer_config.target_width = 640;
  producer_config.target_height = 360;
  producer_config.target_fps = 30.0;
  producer_config.frame_count = 30;

  FileProducer producer(producer_config, ring_buffer, clock_, nullptr, timeline_.get());
  ASSERT_TRUE(producer.start());

  auto deadline = std::chrono::steady_clock::now() + 10s;
  while (producer.isRunning() && std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(10ms);
  }
  std::this_thread::sleep_for(100ms);

  int frame_count = 0;
  buffer::Frame frame;
  while (ring_buffer.Pop(frame)) {
    frame_count++;
  }

  producer.stop();

  EXPECT_EQ(frame_count, 30)
      << "INV-FRAME-001 violated: Expected exactly 30 frames, got " << frame_count;
}

TEST_F(FrameIndexedExecutionTest, INV_FRAME_001_FrameCountExact_100Frames) {
  // Given: frame_count = 100 (~3.3 seconds at 30fps)
  buffer::FrameRingBuffer ring_buffer(150);

  ProducerConfig producer_config;
  producer_config.asset_uri = GetTestVideoPath();
  producer_config.target_width = 640;
  producer_config.target_height = 360;
  producer_config.target_fps = 30.0;
  producer_config.frame_count = 100;

  FileProducer producer(producer_config, ring_buffer, clock_, nullptr, timeline_.get());
  ASSERT_TRUE(producer.start());

  auto deadline = std::chrono::steady_clock::now() + 15s;
  while (producer.isRunning() && std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(10ms);
  }
  std::this_thread::sleep_for(100ms);

  int frame_count = 0;
  buffer::Frame frame;
  while (ring_buffer.Pop(frame)) {
    frame_count++;
  }

  producer.stop();

  EXPECT_EQ(frame_count, 100)
      << "INV-FRAME-001 violated: Expected exactly 100 frames, got " << frame_count;
}

TEST_F(FrameIndexedExecutionTest, INV_FRAME_001_NegativeOneFrameCountMeansEOF) {
  // Given: frame_count = -1 (legacy EOF mode)
  // When: Producer runs until stopped
  // Then: Producer does NOT stop at any specific frame count (runs until EOF or stop)

  buffer::FrameRingBuffer ring_buffer(60);

  ProducerConfig producer_config;
  producer_config.asset_uri = GetTestVideoPath();
  producer_config.target_width = 640;
  producer_config.target_height = 360;
  producer_config.target_fps = 30.0;
  producer_config.frame_count = -1;  // Legacy: run until EOF

  FileProducer producer(producer_config, ring_buffer, clock_, nullptr, timeline_.get());
  ASSERT_TRUE(producer.start());

  // Wait a bit and verify producer is still running
  auto deadline = std::chrono::steady_clock::now() + 2s;
  while (ring_buffer.Size() < 30 && std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(10ms);
  }

  EXPECT_TRUE(producer.isRunning())
      << "Producer with frame_count=-1 should continue running (not stop at frame count)";

  producer.stop();
}

// =============================================================================
// INV-FRAME-002: Padding Is Expressed in Frames (BlackFrameProducer)
// =============================================================================
// Given: BlackFrameProducer with target_frame_count = N
// When: Producer runs until completion
// Then: Exactly N black frames produced
// =============================================================================

TEST_F(FrameIndexedExecutionTest, INV_FRAME_002_StructuralPadding_ExactCount_5Frames) {
  // Given: target_frame_count = 5
  // When: BlackFrameProducer runs
  // Then: Exactly 5 black frames produced

  buffer::FrameRingBuffer ring_buffer(30);

  runtime::ProgramFormat format;
  format.video.width = 640;
  format.video.height = 360;
  format.video.frame_rate = "30/1";

  BlackFrameProducer producer(ring_buffer, format, clock_, 0);
  producer.SetTargetFrameCount(5);  // INV-FRAME-002: structural padding

  ASSERT_TRUE(producer.start());

  // Wait for producer to complete
  auto deadline = std::chrono::steady_clock::now() + 5s;
  while (producer.isRunning() && std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(10ms);
  }

  // Verify padding complete flag
  EXPECT_TRUE(producer.IsPaddingComplete())
      << "IsPaddingComplete() should return true after emitting target frames";

  // Count frames
  int frame_count = 0;
  buffer::Frame frame;
  while (ring_buffer.Pop(frame)) {
    frame_count++;
    // Verify this is a black frame (internal://black sentinel)
    EXPECT_EQ(frame.metadata.asset_uri, BlackFrameProducer::kAssetUri);
  }

  EXPECT_EQ(frame_count, 5)
      << "INV-FRAME-002 violated: Expected exactly 5 padding frames, got " << frame_count;
}

TEST_F(FrameIndexedExecutionTest, INV_FRAME_002_StructuralPadding_ExactCount_30Frames) {
  // Given: target_frame_count = 30 (1 second padding)
  buffer::FrameRingBuffer ring_buffer(60);

  runtime::ProgramFormat format;
  format.video.width = 640;
  format.video.height = 360;
  format.video.frame_rate = "30/1";

  BlackFrameProducer producer(ring_buffer, format, clock_, 0);
  producer.SetTargetFrameCount(30);

  ASSERT_TRUE(producer.start());

  auto deadline = std::chrono::steady_clock::now() + 5s;
  while (producer.isRunning() && std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(10ms);
  }

  EXPECT_TRUE(producer.IsPaddingComplete());

  int frame_count = 0;
  buffer::Frame frame;
  while (ring_buffer.Pop(frame)) {
    frame_count++;
    EXPECT_EQ(frame.metadata.asset_uri, BlackFrameProducer::kAssetUri);
  }

  EXPECT_EQ(frame_count, 30)
      << "INV-FRAME-002 violated: Expected exactly 30 padding frames, got " << frame_count;
}

TEST_F(FrameIndexedExecutionTest, INV_FRAME_002_StructuralPadding_ExactCount_100Frames) {
  // Given: target_frame_count = 100 (~3.3 seconds padding)
  buffer::FrameRingBuffer ring_buffer(150);

  runtime::ProgramFormat format;
  format.video.width = 640;
  format.video.height = 360;
  format.video.frame_rate = "30/1";

  BlackFrameProducer producer(ring_buffer, format, clock_, 0);
  producer.SetTargetFrameCount(100);

  ASSERT_TRUE(producer.start());

  auto deadline = std::chrono::steady_clock::now() + 10s;
  while (producer.isRunning() && std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(10ms);
  }

  EXPECT_TRUE(producer.IsPaddingComplete());

  int frame_count = 0;
  buffer::Frame frame;
  while (ring_buffer.Pop(frame)) {
    frame_count++;
    EXPECT_EQ(frame.metadata.asset_uri, BlackFrameProducer::kAssetUri);
  }

  EXPECT_EQ(frame_count, 100)
      << "INV-FRAME-002 violated: Expected exactly 100 padding frames, got " << frame_count;
}

TEST_F(FrameIndexedExecutionTest, INV_FRAME_002_FailsafeMode_DoesNotComplete) {
  // Given: target_frame_count = -1 (failsafe mode)
  // When: Producer runs
  // Then: IsPaddingComplete() returns false (never completes)

  buffer::FrameRingBuffer ring_buffer(30);

  runtime::ProgramFormat format;
  format.video.width = 640;
  format.video.height = 360;
  format.video.frame_rate = "30/1";

  BlackFrameProducer producer(ring_buffer, format, clock_, 0);
  producer.SetTargetFrameCount(-1);  // Failsafe mode: unbounded

  ASSERT_TRUE(producer.start());

  // Wait for some frames to be produced
  auto deadline = std::chrono::steady_clock::now() + 2s;
  while (ring_buffer.Size() < 10 && std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(10ms);
  }

  // In failsafe mode, IsPaddingComplete should always return false
  EXPECT_FALSE(producer.IsPaddingComplete())
      << "Failsafe mode (frame_count=-1) should never report padding complete";

  // Producer should still be running
  EXPECT_TRUE(producer.isRunning())
      << "Failsafe mode producer should keep running indefinitely";

  producer.stop();
}

TEST_F(FrameIndexedExecutionTest, INV_FRAME_002_PaddingPTSMonotonic) {
  // Given: structural padding frames
  // When: Frames are produced
  // Then: PTS values are monotonically increasing

  buffer::FrameRingBuffer ring_buffer(60);

  runtime::ProgramFormat format;
  format.video.width = 640;
  format.video.height = 360;
  format.video.frame_rate = "30/1";

  BlackFrameProducer producer(ring_buffer, format, clock_, 0);
  producer.SetTargetFrameCount(20);

  ASSERT_TRUE(producer.start());

  auto deadline = std::chrono::steady_clock::now() + 5s;
  while (producer.isRunning() && std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(10ms);
  }

  std::vector<int64_t> pts_values;
  buffer::Frame frame;
  while (ring_buffer.Pop(frame)) {
    pts_values.push_back(frame.metadata.pts);
  }

  ASSERT_EQ(pts_values.size(), 20u);

  // Verify monotonicity
  for (size_t i = 1; i < pts_values.size(); i++) {
    EXPECT_GT(pts_values[i], pts_values[i - 1])
        << "PTS not monotonic at index " << i << ": "
        << pts_values[i - 1] << " -> " << pts_values[i];
  }
}

// =============================================================================
// INV-FRAME-003: CT Derives From Frame Index (tested primarily in TimelineController)
// These tests verify the integration with TimelineController
// =============================================================================

TEST_F(FrameIndexedExecutionTest, INV_FRAME_003_PTSSpacingMatchesFrameRate) {
  // Given: Frames produced at 30fps
  // When: PTS deltas are examined
  // Then: Deltas are approximately 33333us (1/30s)

  buffer::FrameRingBuffer ring_buffer(60);

  ProducerConfig producer_config;
  producer_config.asset_uri = GetTestVideoPath();
  producer_config.target_width = 640;
  producer_config.target_height = 360;
  producer_config.target_fps = 30.0;
  producer_config.frame_count = 30;

  FileProducer producer(producer_config, ring_buffer, clock_, nullptr, timeline_.get());
  ASSERT_TRUE(producer.start());

  auto deadline = std::chrono::steady_clock::now() + 10s;
  while (ring_buffer.Size() < 30 && std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(10ms);
  }

  std::vector<int64_t> pts_values;
  buffer::Frame frame;
  while (ring_buffer.Pop(frame) && pts_values.size() < 30) {
    pts_values.push_back(frame.metadata.pts);
  }

  producer.stop();

  ASSERT_GE(pts_values.size(), 10u) << "Need at least 10 frames for PTS spacing test";

  const int64_t expected_period_us = 33'333;  // 30fps
  const int64_t tolerance_us = 1'000;  // 1ms tolerance

  for (size_t i = 1; i < pts_values.size(); i++) {
    int64_t delta = pts_values[i] - pts_values[i - 1];
    EXPECT_NEAR(delta, expected_period_us, tolerance_us)
        << "PTS delta at frame " << i << " is " << delta
        << "us, expected ~" << expected_period_us << "us";
  }
}

// =============================================================================
// Long-Duration Asset Stability Tests
// =============================================================================
// Verify that frame-indexed execution remains stable over many frames
// without drift, drops, or timing errors
// =============================================================================

TEST_F(FrameIndexedExecutionTest, LongDuration_300Frames_NoDrops) {
  // Given: frame_count = 300 (10 seconds at 30fps)
  // When: Producer runs
  // Then: Exactly 300 frames with no drops

  buffer::FrameRingBuffer ring_buffer(350);

  ProducerConfig producer_config;
  producer_config.asset_uri = GetTestVideoPath();
  producer_config.target_width = 640;
  producer_config.target_height = 360;
  producer_config.target_fps = 30.0;
  producer_config.frame_count = 300;

  FileProducer producer(producer_config, ring_buffer, clock_, nullptr, timeline_.get());
  ASSERT_TRUE(producer.start());

  auto deadline = std::chrono::steady_clock::now() + 30s;
  while (producer.isRunning() && std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(10ms);
  }
  std::this_thread::sleep_for(200ms);

  int frame_count = 0;
  buffer::Frame frame;
  while (ring_buffer.Pop(frame)) {
    frame_count++;
  }

  producer.stop();

  EXPECT_EQ(frame_count, 300)
      << "Long-duration test: Expected 300 frames, got " << frame_count;
}

TEST_F(FrameIndexedExecutionTest, LongDuration_PTSMonotonicity) {
  // Given: 200 frames
  // When: All PTS values are examined
  // Then: PTS is strictly monotonically increasing

  buffer::FrameRingBuffer ring_buffer(250);

  ProducerConfig producer_config;
  producer_config.asset_uri = GetTestVideoPath();
  producer_config.target_width = 640;
  producer_config.target_height = 360;
  producer_config.target_fps = 30.0;
  producer_config.frame_count = 200;

  FileProducer producer(producer_config, ring_buffer, clock_, nullptr, timeline_.get());
  ASSERT_TRUE(producer.start());

  auto deadline = std::chrono::steady_clock::now() + 20s;
  while (producer.isRunning() && std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(10ms);
  }
  std::this_thread::sleep_for(200ms);

  std::vector<int64_t> pts_values;
  buffer::Frame frame;
  while (ring_buffer.Pop(frame)) {
    pts_values.push_back(frame.metadata.pts);
  }

  producer.stop();

  ASSERT_GE(pts_values.size(), 100u) << "Need significant frames for long-duration test";

  bool monotonic = true;
  int violations = 0;
  for (size_t i = 1; i < pts_values.size(); i++) {
    if (pts_values[i] <= pts_values[i - 1]) {
      monotonic = false;
      violations++;
    }
  }

  EXPECT_TRUE(monotonic)
      << "Long-duration PTS monotonicity failed: " << violations << " violations";
}

TEST_F(FrameIndexedExecutionTest, LongDuration_NoPTSDrift) {
  // Given: 150 frames at 30fps
  // When: Total PTS span is measured
  // Then: Span matches expected duration (no cumulative drift)

  buffer::FrameRingBuffer ring_buffer(200);

  ProducerConfig producer_config;
  producer_config.asset_uri = GetTestVideoPath();
  producer_config.target_width = 640;
  producer_config.target_height = 360;
  producer_config.target_fps = 30.0;
  producer_config.frame_count = 150;

  FileProducer producer(producer_config, ring_buffer, clock_, nullptr, timeline_.get());
  ASSERT_TRUE(producer.start());

  auto deadline = std::chrono::steady_clock::now() + 15s;
  while (producer.isRunning() && std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(10ms);
  }
  std::this_thread::sleep_for(200ms);

  std::vector<int64_t> pts_values;
  buffer::Frame frame;
  while (ring_buffer.Pop(frame)) {
    pts_values.push_back(frame.metadata.pts);
  }

  producer.stop();

  ASSERT_GE(pts_values.size(), 100u);

  // Calculate expected span: (N-1) * frame_period
  int64_t expected_span = (pts_values.size() - 1) * 33'333;
  int64_t actual_span = pts_values.back() - pts_values.front();

  // Allow 1% drift tolerance
  double drift_ratio = std::abs(static_cast<double>(actual_span - expected_span) / expected_span);

  EXPECT_LT(drift_ratio, 0.01)
      << "PTS drift detected: actual_span=" << actual_span
      << ", expected_span=" << expected_span
      << ", drift=" << (drift_ratio * 100) << "%";
}

}  // namespace
