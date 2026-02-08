// Repository: Retrovue-playout
// Component: VideoLookaheadBuffer Contract Tests
// Purpose: Verify INV-VIDEO-LOOKAHEAD-001 — non-blocking video frame buffering
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <cstring>
#include <mutex>
#include <optional>
#include <thread>
#include <vector>

#include "retrovue/blockplan/AudioLookaheadBuffer.hpp"
#include "retrovue/blockplan/ITickProducer.hpp"
#include "retrovue/blockplan/TickProducer.hpp"
#include "retrovue/blockplan/VideoLookaheadBuffer.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"

namespace retrovue::blockplan::testing {
namespace {

// Helper: create a video Frame with given dimensions and a fill pattern.
static buffer::Frame MakeVideoFrame(int width, int height, uint8_t y_fill = 0x10) {
  buffer::Frame frame;
  frame.width = width;
  frame.height = height;
  int y_size = width * height;
  int uv_size = (width / 2) * (height / 2);
  frame.data.resize(static_cast<size_t>(y_size + 2 * uv_size));
  std::memset(frame.data.data(), y_fill, static_cast<size_t>(y_size));
  std::memset(frame.data.data() + y_size, 0x80, static_cast<size_t>(2 * uv_size));
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
// MockTickProducer — minimal ITickProducer for testing VideoLookaheadBuffer
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
    // Return primed frame if available.
    if (has_primed_ && primed_frame_) {
      has_primed_ = false;
      return std::move(*primed_frame_);
    }

    std::lock_guard<std::mutex> lock(mutex_);
    if (frames_remaining_ <= 0) return std::nullopt;

    // Optional decode delay (for stall simulation).
    if (decode_delay_.count() > 0) {
      // Release lock during sleep to avoid blocking test thread.
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

    // Produce one audio frame per video decode.
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

  bool HasPrimedFrame() const override { return has_primed_; }

  void SetPrimedFrame(FrameData fd) {
    primed_frame_ = std::move(fd);
    has_primed_ = true;
  }

  void SetDecodeDelay(std::chrono::milliseconds delay) {
    decode_delay_ = delay;
  }

  int FramesRemaining() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return frames_remaining_;
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
  bool has_primed_ = false;
  std::optional<FrameData> primed_frame_;
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
// VLB-001: Basic push via fill thread and pop
// =============================================================================
TEST(VideoLookaheadBufferTest, BasicFillAndPop) {
  VideoLookaheadBuffer buf(5);
  MockTickProducer mock(64, 48, 30.0, 100);
  std::atomic<bool> stop{false};

  EXPECT_FALSE(buf.IsPrimed());
  EXPECT_EQ(buf.DepthFrames(), 0);

  buf.StartFilling(&mock, nullptr, 30.0, 30.0, &stop);

  // Wait for buffer to fill to target depth.
  ASSERT_TRUE(WaitFor([&] { return buf.DepthFrames() >= 5; },
                       std::chrono::milliseconds(500)));

  EXPECT_TRUE(buf.IsPrimed());
  EXPECT_EQ(buf.DepthFrames(), 5);
  EXPECT_GE(buf.TotalFramesPushed(), 5);

  // Pop one frame.
  VideoBufferFrame out;
  ASSERT_TRUE(buf.TryPopFrame(out));
  EXPECT_EQ(out.video.width, 64);
  EXPECT_EQ(out.video.height, 48);
  EXPECT_TRUE(out.was_decoded);
  EXPECT_EQ(out.asset_uri, "test_asset.mp4");

  EXPECT_EQ(buf.TotalFramesPopped(), 1);

  buf.StopFilling(false);
}

// =============================================================================
// VLB-002: Underflow detection (empty buffer)
// =============================================================================
TEST(VideoLookaheadBufferTest, UnderflowDetection) {
  VideoLookaheadBuffer buf(5);

  EXPECT_EQ(buf.UnderflowCount(), 0);

  VideoBufferFrame out;
  EXPECT_FALSE(buf.TryPopFrame(out));
  EXPECT_EQ(buf.UnderflowCount(), 1);

  // Second underflow.
  EXPECT_FALSE(buf.TryPopFrame(out));
  EXPECT_EQ(buf.UnderflowCount(), 2);
}

// =============================================================================
// VLB-003: Reset clears everything
// =============================================================================
TEST(VideoLookaheadBufferTest, ResetClearsEverything) {
  VideoLookaheadBuffer buf(5);
  MockTickProducer mock(64, 48, 30.0, 100);
  std::atomic<bool> stop{false};

  buf.StartFilling(&mock, nullptr, 30.0, 30.0, &stop);

  ASSERT_TRUE(WaitFor([&] { return buf.DepthFrames() >= 5; },
                       std::chrono::milliseconds(500)));
  buf.StopFilling(false);

  EXPECT_TRUE(buf.IsPrimed());
  EXPECT_GT(buf.DepthFrames(), 0);
  EXPECT_GT(buf.TotalFramesPushed(), 0);

  buf.Reset();

  EXPECT_FALSE(buf.IsPrimed());
  EXPECT_EQ(buf.DepthFrames(), 0);
  EXPECT_EQ(buf.TotalFramesPushed(), 0);
  EXPECT_EQ(buf.TotalFramesPopped(), 0);
  EXPECT_EQ(buf.UnderflowCount(), 0);
}

// =============================================================================
// VLB-004: Target depth enforcement
// Fill thread should not exceed target_depth_frames.
// =============================================================================
TEST(VideoLookaheadBufferTest, TargetDepthEnforcement) {
  VideoLookaheadBuffer buf(8);
  MockTickProducer mock(64, 48, 30.0, 1000);
  std::atomic<bool> stop{false};

  buf.StartFilling(&mock, nullptr, 30.0, 30.0, &stop);

  // Wait for fill thread to stabilize.
  ASSERT_TRUE(WaitFor([&] { return buf.DepthFrames() >= 8; },
                       std::chrono::milliseconds(500)));

  // Buffer should not exceed target.
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  EXPECT_LE(buf.DepthFrames(), 8);

  buf.StopFilling(false);
}

// =============================================================================
// VLB-005: Fill thread refills after consumption
// Pop frames and verify fill thread refills the gap.
// =============================================================================
TEST(VideoLookaheadBufferTest, FillThreadRefillsAfterPop) {
  VideoLookaheadBuffer buf(5);
  MockTickProducer mock(64, 48, 30.0, 1000);
  std::atomic<bool> stop{false};

  buf.StartFilling(&mock, nullptr, 30.0, 30.0, &stop);

  ASSERT_TRUE(WaitFor([&] { return buf.DepthFrames() >= 5; },
                       std::chrono::milliseconds(500)));

  // Pop 3 frames.
  for (int i = 0; i < 3; i++) {
    VideoBufferFrame out;
    ASSERT_TRUE(buf.TryPopFrame(out));
  }

  EXPECT_EQ(buf.DepthFrames(), 2);

  // Wait for fill thread to refill.
  ASSERT_TRUE(WaitFor([&] { return buf.DepthFrames() >= 5; },
                       std::chrono::milliseconds(500)));

  EXPECT_EQ(buf.DepthFrames(), 5);

  buf.StopFilling(false);
}

// =============================================================================
// VLB-006: StopFilling with flush clears buffer
// =============================================================================
TEST(VideoLookaheadBufferTest, StopFillingWithFlush) {
  VideoLookaheadBuffer buf(5);
  MockTickProducer mock(64, 48, 30.0, 100);
  std::atomic<bool> stop{false};

  buf.StartFilling(&mock, nullptr, 30.0, 30.0, &stop);

  ASSERT_TRUE(WaitFor([&] { return buf.DepthFrames() >= 5; },
                       std::chrono::milliseconds(500)));

  EXPECT_TRUE(buf.IsPrimed());
  int64_t pushed_before = buf.TotalFramesPushed();

  buf.StopFilling(/*flush=*/true);

  EXPECT_FALSE(buf.IsPrimed());
  EXPECT_EQ(buf.DepthFrames(), 0);
  // Cumulative counters NOT reset on flush.
  EXPECT_EQ(buf.TotalFramesPushed(), pushed_before);
}

// =============================================================================
// VLB-007: Audio frames pushed to AudioLookaheadBuffer
// =============================================================================
TEST(VideoLookaheadBufferTest, AudioPushedToAudioBuffer) {
  VideoLookaheadBuffer buf(5);
  AudioLookaheadBuffer audio_buf(1000);
  MockTickProducer mock(64, 48, 30.0, 20);
  std::atomic<bool> stop{false};

  buf.StartFilling(&mock, &audio_buf, 30.0, 30.0, &stop);

  ASSERT_TRUE(WaitFor([&] { return buf.DepthFrames() >= 5; },
                       std::chrono::milliseconds(500)));

  // Audio should have been pushed (1024 samples per decoded frame).
  EXPECT_TRUE(audio_buf.IsPrimed());
  EXPECT_GT(audio_buf.TotalSamplesPushed(), 0);
  // At least 5 frames decoded → 5 * 1024 = 5120 samples.
  EXPECT_GE(audio_buf.TotalSamplesPushed(), 5 * 1024);

  buf.StopFilling(false);
}

// =============================================================================
// VLB-008: Primed frame consumed in StartFilling
// =============================================================================
TEST(VideoLookaheadBufferTest, PrimedFrameConsumedInStartFilling) {
  VideoLookaheadBuffer buf(5);
  MockTickProducer mock(64, 48, 30.0, 100);
  std::atomic<bool> stop{false};

  // Set up a primed frame.
  FrameData primed;
  primed.video = MakeVideoFrame(64, 48, 0xFF);
  primed.asset_uri = "primed_asset.mp4";
  primed.block_ct_ms = 0;
  primed.audio.push_back(MakeAudioFrame(1024, 42));
  mock.SetPrimedFrame(std::move(primed));

  EXPECT_TRUE(mock.HasPrimedFrame());

  buf.StartFilling(&mock, nullptr, 30.0, 30.0, &stop);

  // Primed frame should have been consumed and pushed immediately.
  EXPECT_TRUE(buf.IsPrimed());
  EXPECT_GE(buf.DepthFrames(), 1);

  // Pop the primed frame and verify its content.
  VideoBufferFrame out;
  ASSERT_TRUE(buf.TryPopFrame(out));
  EXPECT_EQ(out.asset_uri, "primed_asset.mp4");
  EXPECT_EQ(out.block_ct_ms, 0);
  EXPECT_TRUE(out.was_decoded);
  // Y-plane fill should be 0xFF.
  EXPECT_EQ(out.video.data[0], 0xFF);

  // Primed frame should now be consumed from the producer.
  EXPECT_FALSE(mock.HasPrimedFrame());

  buf.StopFilling(false);
}

// =============================================================================
// VLB-009: Cadence resolution — 23.976 → 30 fps produces decode/repeat pattern
// =============================================================================
TEST(VideoLookaheadBufferTest, CadenceResolution) {
  // Target depth large enough to capture the pattern.
  VideoLookaheadBuffer buf(50);
  // 20 source frames at 23.976fps should produce ~25 output frames at 30fps.
  MockTickProducer mock(64, 48, 23.976, 20);
  std::atomic<bool> stop{false};

  buf.StartFilling(&mock, nullptr, 23.976, 30.0, &stop);

  // Wait for fill thread to exhaust source content and fill with hold-last.
  ASSERT_TRUE(WaitFor([&] { return buf.DepthFrames() >= 25; },
                       std::chrono::milliseconds(1000)));

  buf.StopFilling(false);

  // Count decoded vs repeated frames.
  int decoded_count = 0;
  int repeat_count = 0;
  int total = buf.DepthFrames();
  for (int i = 0; i < total; i++) {
    VideoBufferFrame out;
    ASSERT_TRUE(buf.TryPopFrame(out));
    if (out.was_decoded) {
      decoded_count++;
    } else {
      repeat_count++;
    }
  }

  // All 20 source frames should have been decoded.
  EXPECT_EQ(decoded_count, 20);
  // There should be some repeats (cadence + hold-last after exhaustion).
  EXPECT_GT(repeat_count, 0);
}

// =============================================================================
// VLB-010: Content exhaustion produces hold-last frames
// =============================================================================
TEST(VideoLookaheadBufferTest, ContentExhaustionHoldLast) {
  VideoLookaheadBuffer buf(20);
  // Only 5 source frames — fill thread will switch to hold-last after.
  MockTickProducer mock(64, 48, 30.0, 5);
  std::atomic<bool> stop{false};

  buf.StartFilling(&mock, nullptr, 30.0, 30.0, &stop);

  // Wait for buffer to fill to target (5 real + 15 hold-last).
  ASSERT_TRUE(WaitFor([&] { return buf.DepthFrames() >= 20; },
                       std::chrono::milliseconds(500)));

  buf.StopFilling(false);

  // Pop all frames.
  int decoded = 0;
  int hold_last = 0;
  int total = buf.DepthFrames();
  for (int i = 0; i < total; i++) {
    VideoBufferFrame out;
    ASSERT_TRUE(buf.TryPopFrame(out));
    if (out.was_decoded) {
      decoded++;
    } else {
      hold_last++;
    }
  }

  // 5 real decodes + remaining are hold-last.
  EXPECT_EQ(decoded, 5);
  EXPECT_GT(hold_last, 0);
  EXPECT_EQ(decoded + hold_last, total);
}

// =============================================================================
// VLB-011: Stall simulation — decode delay absorbed by buffer
// Fill thread decodes with a 20ms delay; tick loop pops at ~33ms (30fps).
// Buffer should sustain the consumer without underflow.
// =============================================================================
TEST(VideoLookaheadBufferTest, StallSimulation) {
  VideoLookaheadBuffer buf(10);
  MockTickProducer mock(64, 48, 30.0, 200);
  std::atomic<bool> stop{false};

  // No delay initially — let buffer fill up.
  buf.StartFilling(&mock, nullptr, 30.0, 30.0, &stop);

  ASSERT_TRUE(WaitFor([&] { return buf.DepthFrames() >= 10; },
                       std::chrono::milliseconds(500)));

  // Now add a decode delay shorter than frame period.
  // 20ms decode + fill overhead < 33ms frame period → buffer should stay full.
  mock.SetDecodeDelay(std::chrono::milliseconds(20));

  // Simulate 30 ticks of consumption (~1 second at 30fps).
  int frames_consumed = 0;
  for (int i = 0; i < 30; i++) {
    VideoBufferFrame out;
    if (buf.TryPopFrame(out)) {
      frames_consumed++;
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(33));
  }

  // All 30 ticks should have gotten a frame (no underflow).
  EXPECT_EQ(frames_consumed, 30);
  EXPECT_EQ(buf.UnderflowCount(), 0);

  buf.StopFilling(false);
}

// =============================================================================
// VLB-012: External stop signal terminates fill thread
// =============================================================================
TEST(VideoLookaheadBufferTest, ExternalStopSignal) {
  VideoLookaheadBuffer buf(5);
  MockTickProducer mock(64, 48, 30.0, 10000);
  std::atomic<bool> stop{false};

  buf.StartFilling(&mock, nullptr, 30.0, 30.0, &stop);

  ASSERT_TRUE(WaitFor([&] { return buf.DepthFrames() >= 5; },
                       std::chrono::milliseconds(500)));

  EXPECT_TRUE(buf.IsFilling());

  // Set external stop signal.
  stop.store(true, std::memory_order_release);

  // StopFilling should return quickly (fill thread sees stop signal).
  buf.StopFilling(false);
  EXPECT_FALSE(buf.IsFilling());
}

// =============================================================================
// VLB-013: Multiple StartFilling/StopFilling cycles (block transitions)
// =============================================================================
TEST(VideoLookaheadBufferTest, MultipleStartStopCycles) {
  VideoLookaheadBuffer buf(5);
  std::atomic<bool> stop{false};

  // Block 1: 30 frames.
  MockTickProducer mock1(64, 48, 30.0, 30);
  buf.StartFilling(&mock1, nullptr, 30.0, 30.0, &stop);
  ASSERT_TRUE(WaitFor([&] { return buf.DepthFrames() >= 5; },
                       std::chrono::milliseconds(500)));

  // Pop a few frames.
  for (int i = 0; i < 3; i++) {
    VideoBufferFrame out;
    ASSERT_TRUE(buf.TryPopFrame(out));
  }

  // Stop and flush (simulating fence transition).
  buf.StopFilling(/*flush=*/true);
  EXPECT_FALSE(buf.IsPrimed());
  EXPECT_EQ(buf.DepthFrames(), 0);

  // Block 2: 50 frames.
  MockTickProducer mock2(64, 48, 30.0, 50);
  buf.StartFilling(&mock2, nullptr, 30.0, 30.0, &stop);
  ASSERT_TRUE(WaitFor([&] { return buf.DepthFrames() >= 5; },
                       std::chrono::milliseconds(500)));

  EXPECT_TRUE(buf.IsPrimed());

  // Pop from second block.
  VideoBufferFrame out;
  ASSERT_TRUE(buf.TryPopFrame(out));
  EXPECT_TRUE(out.was_decoded);

  buf.StopFilling(false);
}

}  // namespace
}  // namespace retrovue::blockplan::testing
