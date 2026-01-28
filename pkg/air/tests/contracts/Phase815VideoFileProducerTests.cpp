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

// Decode test: open known MP4, collect frames for up to 10s, assert PTS monotonic for all (≥1).
// Contract: PTS correctness, not asset duration. Works with any length asset (Phase 8.8).
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

  std::vector<Frame> frames;
  const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(10);
  while (std::chrono::steady_clock::now() < deadline) {
    Frame f;
    if (buffer.Pop(f)) {
      frames.push_back(std::move(f));
    } else {
      std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
  }

  producer.stop();

  ASSERT_GE(frames.size(), 1u) << "Expected at least one frame from decode";
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

// Phase 8.6: Fixed segment cutoff removed. Segment end = natural EOF only; hard_stop_time_ms
// and asset duration are not used to forcibly stop the process. This test is skipped.
TEST_F(Phase815VideoFileProducerTest, Phase82_HardStopNoFramesAfter) {
  GTEST_SKIP() << "Phase 8.6: segment end is natural EOF only; hard_stop not enforced";
}

}  // namespace
