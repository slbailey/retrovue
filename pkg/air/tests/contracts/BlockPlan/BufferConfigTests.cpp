// Repository: Retrovue-playout
// Component: BufferConfig Contract Tests
// Purpose: Verify configurable buffer depths, low-water marks, decode latency,
//          refill rate, and Prometheus metrics output.
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <cstring>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

#include "retrovue/blockplan/AudioLookaheadBuffer.hpp"
#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/ITickProducer.hpp"
#include "retrovue/blockplan/PipelineMetrics.hpp"
#include "retrovue/blockplan/TickProducer.hpp"
#include "retrovue/blockplan/VideoLookaheadBuffer.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"

namespace retrovue::blockplan::testing {
namespace {

// Helper: create a video Frame with given dimensions and a fill pattern.
static buffer::Frame MakeVideoFrame(int width, int height,
                                    uint8_t y_fill = 0x10) {
  buffer::Frame frame;
  frame.width = width;
  frame.height = height;
  int y_size = width * height;
  int uv_size = (width / 2) * (height / 2);
  frame.data.resize(static_cast<size_t>(y_size + 2 * uv_size));
  std::memset(frame.data.data(), y_fill, static_cast<size_t>(y_size));
  std::memset(frame.data.data() + y_size, 0x80,
              static_cast<size_t>(2 * uv_size));
  return frame;
}

// Helper: create an AudioFrame with N samples.
static buffer::AudioFrame MakeAudioFrame(int nb_samples, int16_t fill = 0) {
  buffer::AudioFrame frame;
  frame.sample_rate = buffer::kHouseAudioSampleRate;
  frame.channels = buffer::kHouseAudioChannels;
  frame.nb_samples = nb_samples;
  const int bytes_per_sample =
      buffer::kHouseAudioChannels * static_cast<int>(sizeof(int16_t));
  frame.data.resize(static_cast<size_t>(nb_samples * bytes_per_sample));
  auto* samples = reinterpret_cast<int16_t*>(frame.data.data());
  for (int i = 0; i < nb_samples * buffer::kHouseAudioChannels; i++) {
    samples[i] = fill;
  }
  return frame;
}

// =============================================================================
// MockTickProducer — minimal ITickProducer for buffer testing
// =============================================================================
class MockTickProducer : public ITickProducer {
 public:
  MockTickProducer(int width, int height, double input_fps, int total_frames)
      : width_(width),
        height_(height),
        input_fps_(input_fps),
        frames_remaining_(total_frames),
        total_frames_(total_frames) {
    frame_duration_ms_ =
        input_fps > 0.0 ? static_cast<int64_t>(1000.0 / input_fps) : 33;
  }

  void AssignBlock(const FedBlock& block) override { block_ = block; }

  std::optional<FrameData> TryGetFrame() override {
    std::lock_guard<std::mutex> lock(mutex_);
    if (frames_remaining_ <= 0) return std::nullopt;

    // Optional decode delay (for latency simulation).
    if (decode_delay_.count() > 0) {
      mutex_.unlock();
      std::this_thread::sleep_for(decode_delay_);
      mutex_.lock();
      if (frames_remaining_ <= 0) return std::nullopt;
    }

    frames_remaining_--;
    int frame_index = total_frames_ - frames_remaining_ - 1;

    FrameData fd;
    fd.video = MakeVideoFrame(width_, height_,
                               static_cast<uint8_t>(0x10 + (frame_index % 200)));
    fd.asset_uri = "test_asset.mp4";
    fd.block_ct_ms = frame_index * frame_duration_ms_;
    fd.audio.push_back(MakeAudioFrame(1024));

    return fd;
  }

  void Reset() override {
    std::lock_guard<std::mutex> lock(mutex_);
    frames_remaining_ = 0;
  }

  State GetState() const override { return State::kReady; }
  const FedBlock& GetBlock() const override { return block_; }
  int64_t FramesPerBlock() const override { return total_frames_; }
  bool HasDecoder() const override { return true; }
  double GetInputFPS() const override { return input_fps_; }
  bool HasPrimedFrame() const override { return false; }

  void SetDecodeDelay(std::chrono::milliseconds delay) {
    decode_delay_ = delay;
  }

 private:
  int width_;
  int height_;
  double input_fps_;
  int64_t frame_duration_ms_;
  mutable std::mutex mutex_;
  int frames_remaining_;
  int total_frames_;
  FedBlock block_;
  std::chrono::milliseconds decode_delay_{0};
};

// Helper: poll until condition is true (with timeout).
template <typename Pred>
static bool WaitFor(Pred pred, std::chrono::milliseconds timeout) {
  auto deadline = std::chrono::steady_clock::now() + timeout;
  while (!pred()) {
    if (std::chrono::steady_clock::now() > deadline) return false;
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
  return true;
}

// =============================================================================
// BC-001: VideoTargetDepthConfigurable
// Custom target_depth is respected by fill thread.
// =============================================================================
TEST(BufferConfigTest, VideoTargetDepthConfigurable) {
  const int custom_depth = 8;
  VideoLookaheadBuffer buf(custom_depth);
  EXPECT_EQ(buf.TargetDepthFrames(), custom_depth);

  MockTickProducer mock(64, 48, 30.0, 100);
  std::atomic<bool> stop{false};

  buf.StartFilling(&mock, nullptr, 30.0, 30.0, &stop);

  // Wait for buffer to fill to target depth.
  ASSERT_TRUE(WaitFor([&] { return buf.DepthFrames() >= custom_depth; },
                       std::chrono::seconds(2)));

  // Fill thread blocks at target depth — should not exceed by more than 1.
  // (Could be at target exactly, or one extra if fill thread was mid-push.)
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  EXPECT_LE(buf.DepthFrames(), custom_depth + 1);

  buf.StopFilling(true);
}

// =============================================================================
// BC-002: AudioTargetDepthConfigurable
// Custom target_depth_ms is stored and queryable.
// =============================================================================
TEST(BufferConfigTest, AudioTargetDepthConfigurable) {
  const int custom_depth_ms = 500;
  AudioLookaheadBuffer buf(custom_depth_ms);
  EXPECT_EQ(buf.TargetDepthMs(), custom_depth_ms);
}

// =============================================================================
// BC-003: VideoLowWaterDetection
// IsBelowLowWater() true when depth < threshold, false when above.
// =============================================================================
TEST(BufferConfigTest, VideoLowWaterDetection) {
  // target=10, low_water=4
  VideoLookaheadBuffer buf(10, 4);
  EXPECT_EQ(buf.LowWaterFrames(), 4);

  // Not primed → not below low water.
  EXPECT_FALSE(buf.IsBelowLowWater());

  MockTickProducer mock(64, 48, 30.0, 100);
  std::atomic<bool> stop{false};

  buf.StartFilling(&mock, nullptr, 30.0, 30.0, &stop);

  // Wait for buffer to fill above low-water.
  ASSERT_TRUE(WaitFor([&] { return buf.DepthFrames() >= 4; },
                       std::chrono::seconds(2)));
  EXPECT_FALSE(buf.IsBelowLowWater());

  buf.StopFilling(false);

  // Drain to below low-water.
  VideoBufferFrame vbf;
  while (buf.DepthFrames() > 2) {
    ASSERT_TRUE(buf.TryPopFrame(vbf));
  }
  // Now depth=2, low_water=4 → below.
  EXPECT_TRUE(buf.IsBelowLowWater());
}

// =============================================================================
// BC-004: AudioLowWaterDetection
// IsBelowLowWater() true when depth_ms < threshold, false when above.
// =============================================================================
TEST(BufferConfigTest, AudioLowWaterDetection) {
  // target=1000ms, low_water=200ms
  AudioLookaheadBuffer buf(1000, buffer::kHouseAudioSampleRate,
                            buffer::kHouseAudioChannels, 200);
  EXPECT_EQ(buf.LowWaterMs(), 200);

  // Not primed → not below low water.
  EXPECT_FALSE(buf.IsBelowLowWater());

  // Push enough audio to be above low-water.
  // 200ms = 9600 samples at 48kHz. Push 19200 samples (400ms).
  buf.Push(MakeAudioFrame(19200));
  EXPECT_TRUE(buf.IsPrimed());
  EXPECT_FALSE(buf.IsBelowLowWater());

  // Pop down to below 200ms.
  // Remaining after pop: 19200 - 15000 = 4200 samples = ~87ms < 200ms.
  buffer::AudioFrame out;
  ASSERT_TRUE(buf.TryPopSamples(15000, out));
  EXPECT_TRUE(buf.IsBelowLowWater());
}

// =============================================================================
// BC-005: LowWaterIsDiagnosticOnly
// TryPopFrame still works normally when below low-water (no behavioral change).
// =============================================================================
TEST(BufferConfigTest, LowWaterIsDiagnosticOnly) {
  VideoLookaheadBuffer buf(10, 4);
  MockTickProducer mock(64, 48, 30.0, 100);
  std::atomic<bool> stop{false};

  buf.StartFilling(&mock, nullptr, 30.0, 30.0, &stop);
  ASSERT_TRUE(WaitFor([&] { return buf.DepthFrames() >= 6; },
                       std::chrono::seconds(2)));
  buf.StopFilling(false);

  // Drain to below low-water.
  VideoBufferFrame vbf;
  while (buf.DepthFrames() > 2) {
    ASSERT_TRUE(buf.TryPopFrame(vbf));
  }
  EXPECT_TRUE(buf.IsBelowLowWater());

  // Pop still works — low-water is diagnostic only.
  EXPECT_TRUE(buf.TryPopFrame(vbf));
  EXPECT_TRUE(buf.TryPopFrame(vbf));
  // Now buffer is empty. Pop should return false (underflow), not crash.
  EXPECT_FALSE(buf.TryPopFrame(vbf));
}

// =============================================================================
// BC-006: DecodeLatencyP95_NoData
// Returns 0 when no decodes have occurred.
// =============================================================================
TEST(BufferConfigTest, DecodeLatencyP95_NoData) {
  VideoLookaheadBuffer buf(10);
  EXPECT_EQ(buf.DecodeLatencyP95Us(), 0);
  EXPECT_EQ(buf.DecodeLatencyMeanUs(), 0);
}

// =============================================================================
// BC-007: DecodeLatencyP95_ReflectsActualTimes
// With 10ms decode delay mock, p95 ≈ 10000us (±tolerance).
// =============================================================================
TEST(BufferConfigTest, DecodeLatencyP95_ReflectsActualTimes) {
  VideoLookaheadBuffer buf(5);
  MockTickProducer mock(64, 48, 30.0, 100);
  mock.SetDecodeDelay(std::chrono::milliseconds(10));
  std::atomic<bool> stop{false};

  buf.StartFilling(&mock, nullptr, 30.0, 30.0, &stop);

  // Wait for enough frames to have meaningful latency data.
  ASSERT_TRUE(WaitFor([&] { return buf.TotalFramesPushed() >= 5; },
                       std::chrono::seconds(5)));

  buf.StopFilling(false);

  int64_t p95 = buf.DecodeLatencyP95Us();
  int64_t mean = buf.DecodeLatencyMeanUs();

  // 10ms sleep → expect p95/mean around 10000us.
  // Tolerance: 5000-50000us (sleep is imprecise, OS scheduling, CI).
  EXPECT_GE(p95, 5000) << "p95=" << p95;
  EXPECT_LE(p95, 50000) << "p95=" << p95;
  EXPECT_GE(mean, 5000) << "mean=" << mean;
  EXPECT_LE(mean, 50000) << "mean=" << mean;
}

// =============================================================================
// BC-008: RefillRateFps_Positive
// After fill thread runs, RefillRateFps() > 0.
// =============================================================================
TEST(BufferConfigTest, RefillRateFps_Positive) {
  VideoLookaheadBuffer buf(5);
  MockTickProducer mock(64, 48, 30.0, 100);
  std::atomic<bool> stop{false};

  EXPECT_DOUBLE_EQ(buf.RefillRateFps(), 0.0);

  buf.StartFilling(&mock, nullptr, 30.0, 30.0, &stop);

  // Wait for some frames to be pushed.
  ASSERT_TRUE(WaitFor([&] { return buf.TotalFramesPushed() >= 3; },
                       std::chrono::seconds(2)));

  double rate = buf.RefillRateFps();
  EXPECT_GT(rate, 0.0) << "rate=" << rate;

  buf.StopFilling(true);
}

// =============================================================================
// BC-009: BufferConfigDefaults
// Default BufferConfig matches legacy: video=0(auto), audio=1000.
// =============================================================================
TEST(BufferConfigTest, BufferConfigDefaults) {
  BufferConfig cfg;
  EXPECT_EQ(cfg.video_target_depth_frames, 0);
  EXPECT_EQ(cfg.video_low_water_frames, 0);
  EXPECT_EQ(cfg.audio_target_depth_ms, 1000);
  EXPECT_EQ(cfg.audio_low_water_ms, 0);
}

// =============================================================================
// BC-010: PrometheusOutputIncludesNewMetrics
// GeneratePrometheusText() contains all 6 new metric names.
// =============================================================================
TEST(BufferConfigTest, PrometheusOutputIncludesNewMetrics) {
  PipelineMetrics m;
  m.channel_id = 42;
  m.decode_latency_p95_us = 12345;
  m.decode_latency_mean_us = 6789;
  m.video_refill_rate_fps = 29.97;
  m.video_low_water_events = 3;
  m.audio_low_water_events = 1;
  m.detach_count = 2;

  std::string text = m.GeneratePrometheusText();

  EXPECT_NE(text.find("air_continuous_decode_latency_p95_us"), std::string::npos)
      << "Missing decode_latency_p95_us";
  EXPECT_NE(text.find("air_continuous_decode_latency_mean_us"), std::string::npos)
      << "Missing decode_latency_mean_us";
  EXPECT_NE(text.find("air_continuous_video_refill_rate_fps"), std::string::npos)
      << "Missing video_refill_rate_fps";
  EXPECT_NE(text.find("air_continuous_video_low_water_events"), std::string::npos)
      << "Missing video_low_water_events";
  EXPECT_NE(text.find("air_continuous_audio_low_water_events"), std::string::npos)
      << "Missing audio_low_water_events";
  EXPECT_NE(text.find("air_continuous_detach_count"), std::string::npos)
      << "Missing detach_count";

  // Verify values appear.
  EXPECT_NE(text.find("12345"), std::string::npos)
      << "Value 12345 for p95 not found";
  EXPECT_NE(text.find("6789"), std::string::npos)
      << "Value 6789 for mean not found";
}

}  // namespace
}  // namespace retrovue::blockplan::testing
