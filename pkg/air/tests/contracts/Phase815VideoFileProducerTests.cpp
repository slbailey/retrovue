// Phase 8.1.5 — VideoFileProducer libav-only contract tests.
// No ffmpeg executable; Producer uses libavformat/libavcodec only.
// Decode test, Stop test, Restart test per Phase8-1-5-VideoFileProducerInternalRefactor.md
// Phase 8.2 — Segment control tests (frame-admission start_offset, hard_stop) per Phase8-2-SegmentControl.md

#include <chrono>
#include <cstdlib>
#include <fstream>
#include <string>
#include <thread>
#include <vector>

#include <gtest/gtest.h>
#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/producers/video_file/VideoFileProducer.h"
#include "retrovue/timing/MasterClock.h"
#include "timing/TestMasterClock.h"

namespace {

using retrovue::buffer::Frame;
using retrovue::buffer::FrameRingBuffer;
using retrovue::producers::video_file::ProducerConfig;
using retrovue::producers::video_file::VideoFileProducer;

std::string GetPhase815TestAssetPath() {
  const char* env = std::getenv("RETROVUE_TEST_VIDEO_PATH");
  if (env && env[0] != '\0') return env;
  return "/opt/retrovue/assets/samplecontent.mp4";
}

bool FileExists(const std::string& path) {
  std::ifstream f(path);
  return f.good();
}

class Phase815VideoFileProducerTest : public ::testing::Test {
 protected:
  void SetUp() override {
    test_asset_path_ = GetPhase815TestAssetPath();
  }

  std::string test_asset_path_;
};

// Decode test: open known MP4, decode N frames, assert count, PTS monotonic, no dropped
// Phase 8.1.5: libav is REQUIRED at build time; skip only when test asset is missing.
TEST_F(Phase815VideoFileProducerTest, DecodeNFramesPTSMonotonic) {
  if (!FileExists(test_asset_path_)) {
    GTEST_SKIP() << "Test asset not found: " << test_asset_path_;
  }

  FrameRingBuffer buffer(60);
  auto clock = std::make_shared<retrovue::timing::TestMasterClock>();
  clock->SetEpochUtcUs(1700000000000000);
  clock->SetRatePpm(0.0);
  clock->SetNow(1700000000000000, 0.0);

  ProducerConfig config;
  config.asset_uri = test_asset_path_;
  config.stub_mode = false;
  config.start_offset_ms = 0;
  config.hard_stop_time_ms = 0;

  VideoFileProducer producer(config, buffer, clock, nullptr);
  ASSERT_TRUE(producer.start());

  constexpr size_t kN = 30;
  std::vector<Frame> frames;
  frames.reserve(kN);
  const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(10);
  while (frames.size() < kN && std::chrono::steady_clock::now() < deadline) {
    Frame f;
    if (buffer.Pop(f)) {
      frames.push_back(std::move(f));
    } else {
      std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
  }

  producer.stop();

  ASSERT_EQ(frames.size(), kN) << "Expected " << kN << " frames";
  int64_t prev_pts = frames[0].metadata.pts;
  for (size_t i = 1; i < frames.size(); ++i) {
    ASSERT_GE(frames[i].metadata.pts, prev_pts) << "PTS not monotonic at frame " << i;
    prev_pts = frames[i].metadata.pts;
  }
}

// Stop test: start decoding, issue stop() after K frames, assert exactly K (or at most K+1) emitted
TEST_F(Phase815VideoFileProducerTest, StopAfterKFrames) {
  if (!FileExists(test_asset_path_)) {
    GTEST_SKIP() << "Test asset not found: " << test_asset_path_;
  }

  FrameRingBuffer buffer(60);
  auto clock = std::make_shared<retrovue::timing::TestMasterClock>();
  clock->SetEpochUtcUs(1700000000000000);
  clock->SetRatePpm(0.0);
  clock->SetNow(1700000000000000, 0.0);

  ProducerConfig config;
  config.asset_uri = test_asset_path_;
  config.stub_mode = false;

  VideoFileProducer producer(config, buffer, clock, nullptr);
  ASSERT_TRUE(producer.start());

  constexpr size_t kK = 15;
  size_t popped = 0;
  const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(10);
  while (popped < kK && std::chrono::steady_clock::now() < deadline) {
    Frame f;
    if (buffer.Pop(f)) {
      ++popped;
      if (popped == kK) break;
    } else {
      std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
  }
  producer.stop();

  uint64_t total = producer.GetFramesProduced();
  ASSERT_GE(total, kK);
  ASSERT_LE(total, kK + 5u) << "Expected at most ~K frames after stop (no more than a few extra)";
}

// Restart test: start → stop → destroy → create again → start; no crashes, no leaks
TEST_F(Phase815VideoFileProducerTest, RestartNoCrashOrLeak) {
  if (!FileExists(test_asset_path_)) {
    GTEST_SKIP() << "Test asset not found: " << test_asset_path_;
  }

  auto clock = std::make_shared<retrovue::timing::TestMasterClock>();
  clock->SetEpochUtcUs(1700000000000000);
  clock->SetRatePpm(0.0);
  clock->SetNow(1700000000000000, 0.0);

  ProducerConfig config;
  config.asset_uri = test_asset_path_;
  config.stub_mode = false;

  {
    FrameRingBuffer buffer1(60);
    VideoFileProducer producer1(config, buffer1, clock, nullptr);
    ASSERT_TRUE(producer1.start());
    Frame f;
    (void)buffer1.Pop(f);
    producer1.stop();
  }

  {
    FrameRingBuffer buffer2(60);
    VideoFileProducer producer2(config, buffer2, clock, nullptr);
    ASSERT_TRUE(producer2.start());
    Frame f;
    (void)buffer2.Pop(f);
    producer2.stop();
  }
}

// ---------------------------------------------------------------------------
// Phase 8.2 — Segment Control: frame-accurate start & stop (no container seek)
// First emitted frame PTS >= start_offset_ms; hard_stop respected.
// ---------------------------------------------------------------------------

TEST_F(Phase815VideoFileProducerTest, Phase82_FirstEmittedFramePTSAtOrAfterStartOffset) {
  if (!FileExists(test_asset_path_)) {
    GTEST_SKIP() << "Test asset not found: " << test_asset_path_;
  }

  const int64_t start_offset_ms = 500;  // 0.5 s into asset
  const int64_t start_offset_us = start_offset_ms * 1000;

  FrameRingBuffer buffer(60);
  auto clock = std::make_shared<retrovue::timing::TestMasterClock>();
  clock->SetEpochUtcUs(1700000000000000);
  clock->SetRatePpm(0.0);
  clock->SetNow(1700000000000000, 0.0);

  ProducerConfig config;
  config.asset_uri = test_asset_path_;
  config.stub_mode = false;
  config.start_offset_ms = start_offset_ms;
  config.hard_stop_time_ms = 0;

  VideoFileProducer producer(config, buffer, clock, nullptr);
  ASSERT_TRUE(producer.start());

  std::vector<Frame> frames;
  const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(10);
  while (frames.size() < 20 && std::chrono::steady_clock::now() < deadline) {
    Frame f;
    if (buffer.Pop(f)) {
      frames.push_back(std::move(f));
    } else {
      std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
  }
  producer.stop();

  ASSERT_GE(frames.size(), 1u) << "At least one frame must be emitted";
  // Phase 8.2: first emitted video frame pts_ms >= start_offset_ms (frame.pts in us here)
  ASSERT_GE(frames[0].metadata.pts, start_offset_us)
      << "First emitted frame PTS must be >= start_offset_ms (frame admission, no seek)";
  for (size_t i = 0; i < frames.size(); ++i) {
    ASSERT_GE(frames[i].metadata.pts, start_offset_us)
        << "No frame PTS < start_offset_ms at frame " << i;
  }
  // Phase 8.2: monotonicity — frame.pts strictly increasing (display order)
  for (size_t i = 1; i < frames.size(); ++i) {
    ASSERT_GT(frames[i].metadata.pts, frames[i - 1].metadata.pts)
        << "frame.pts_ms must be strictly increasing at frame " << i;
  }
}

TEST_F(Phase815VideoFileProducerTest, Phase82_HardStopNoFramesAfter) {
  if (!FileExists(test_asset_path_)) {
    GTEST_SKIP() << "Test asset not found: " << test_asset_path_;
  }

  const int64_t clock_start_us = 1'000'000'000'000'000LL;
  const int64_t clock_start_ms = clock_start_us / 1000;
  const int64_t segment_duration_ms = 2000;
  const int64_t hard_stop_time_ms = clock_start_ms + segment_duration_ms;
  // Derived segment end: segment_end_pts_ms = start_offset_ms + segment_duration_ms = 0 + 2000
  const int64_t segment_end_pts_us = segment_duration_ms * 1000;

  FrameRingBuffer buffer(60);
  auto clock = std::make_shared<retrovue::timing::TestMasterClock>(
      clock_start_us, retrovue::timing::TestMasterClock::Mode::Deterministic);
  clock->SetRatePpm(0.0);

  ProducerConfig config;
  config.asset_uri = test_asset_path_;
  config.stub_mode = false;
  config.start_offset_ms = 0;
  config.hard_stop_time_ms = hard_stop_time_ms;

  VideoFileProducer producer(config, buffer, clock, nullptr);
  ASSERT_TRUE(producer.start());

  // Let producer run briefly so it can emit frames and set derived segment_end_pts_us_
  std::this_thread::sleep_for(std::chrono::milliseconds(300));

  // Advance clock past hard_stop_time_ms — producer must stop; no frames after this
  auto test_clock = std::static_pointer_cast<retrovue::timing::TestMasterClock>(clock);
  test_clock->AdvanceMicroseconds(3'000'000);  // +3 s

  std::this_thread::sleep_for(std::chrono::milliseconds(500));
  std::vector<Frame> frames;
  Frame f;
  while (buffer.Pop(f)) {
    frames.push_back(std::move(f));
  }

  EXPECT_FALSE(producer.isRunning())
      << "Producer must stop at or before hard_stop_time_ms (MasterClock.now_utc_ms() >= hard_stop_time_ms)";
  // Phase 8.2: every emitted frame must have frame.pts_ms < segment_end_pts_ms (derived boundary)
  for (size_t i = 0; i < frames.size(); ++i) {
    ASSERT_LT(frames[i].metadata.pts, segment_end_pts_us)
        << "Emitted frame " << i << " must have frame.pts_ms < segment_end_pts_ms";
  }
  if (!frames.empty()) {
    ASSERT_LT(frames.back().metadata.pts, segment_end_pts_us)
        << "Last emitted frame must have frame.pts_ms < segment_end_pts_ms (derived boundary)";
  }
  producer.stop();
}

}  // namespace
