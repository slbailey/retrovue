// Repository: Retrovue-playout
// Component: INV-AUDIO-PTS-HOUSE-CLOCK-001 contract test
// Purpose: Audio transport PTS must be derived from emitted sample count,
//          not AudioFrame.pts_us (which may be garbage/non-monotonic).
// Contract Reference: INV-AUDIO-PTS-HOUSE-CLOCK-001
// Copyright (c) 2025 RetroVue
//
// This test MUST FAIL under current implementation where MpegTSOutputSink
// uses audio_frame.pts_us for encode PTS. It will PASS only when PTS is
// derived from sample clock: pts_90k = (samples_emitted * 90000) / sample_rate

#include <gtest/gtest.h>

#include <vector>
#include <memory>
#include <cstdint>
#include <unistd.h>
#include <thread>
#include <chrono>

#include "retrovue/output/MpegTSOutputSink.h"
#include "retrovue/playout_sinks/mpegts/EncoderPipeline.hpp"
#include "retrovue/playout_sinks/mpegts/MpegTSPlayoutSinkConfig.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"

using namespace retrovue::output;
using namespace retrovue::playout_sinks::mpegts;
using namespace retrovue::buffer;

namespace {

// FakeEncoderPipeline: Test seam that captures audio PTS values
class FakeEncoderPipeline : public EncoderPipeline {
 public:
  std::vector<int64_t> captured_audio_pts90k;

  explicit FakeEncoderPipeline(const MpegTSPlayoutSinkConfig& config)
      : EncoderPipeline(config) {}

  // Capture audio PTS without actual encoding
  bool encodeAudioFrame(const AudioFrame& audio_frame, int64_t pts90k,
                        bool is_silence_pad = false) override {
    captured_audio_pts90k.push_back(pts90k);
    return true;  // Success
  }

  // Fake open (no FFmpeg initialization)
  bool open(const MpegTSPlayoutSinkConfig& config) override {
    return true;
  }

  bool open(const MpegTSPlayoutSinkConfig& config, 
            void* opaque,
            int (*write_callback)(void* opaque, uint8_t* buf, int buf_size)) override {
    return true;
  }

  // Fake other methods
  bool encodeFrame(const retrovue::buffer::Frame& frame, int64_t pts90k) override {
    return true;  // No-op for video in this test
  }

  bool flushAudio() override {
    return true;
  }

  void close() override {
    // No-op
  }

  bool IsInitialized() const override {
    return true;
  }
};

} // anonymous namespace

TEST(INV_AUDIO_PTS_HOUSE_CLOCK_001, MpegTSOutputSink_AudioPTS_IgnoresContentPTS_UsesSampleClock) {
  // Create dummy pipe (sink writes to it, we don't read it)
  int pipe_fds[2];
  ASSERT_EQ(pipe(pipe_fds), 0);
  int write_fd = pipe_fds[1];
  close(pipe_fds[0]);  // Don't need read end
  
  // Create fake encoder
  MpegTSPlayoutSinkConfig config;
  config.fps_num = 30;
  config.fps_den = 1;
  config.enable_audio = true;
  
  auto fake_encoder = std::make_unique<FakeEncoderPipeline>(config);
  FakeEncoderPipeline* fake_encoder_ptr = fake_encoder.get();  // Keep pointer before move
  
  // Create sink with injected fake encoder
  std::unique_ptr<MpegTSOutputSink> sink(
      new MpegTSOutputSink(write_fd, config, std::move(fake_encoder), "test-audio-pts"));
  
  ASSERT_TRUE(sink->Start());
  
  // Give sink time to start mux loop
  std::this_thread::sleep_for(std::chrono::milliseconds(100));
  
  // Create 3 audio frames with deliberately wrong/non-monotonic pts_us
  constexpr int nb_samples_per_frame = 1024;
  constexpr int sample_rate = 48000;
  constexpr int channels = 2;
  
  std::vector<AudioFrame> frames(3);
  
  // Frame 1: pts_us = 1'000'000 (1 second) - GARBAGE
  frames[0].nb_samples = nb_samples_per_frame;
  frames[0].sample_rate = sample_rate;
  frames[0].channels = channels;
  frames[0].pts_us = 1'000'000;
  frames[0].data.resize(nb_samples_per_frame * channels * sizeof(int16_t), 0);
  
  // Frame 2: pts_us = 100 (NON-MONOTONIC! earlier than frame 1) - GARBAGE
  frames[1].nb_samples = nb_samples_per_frame;
  frames[1].sample_rate = sample_rate;
  frames[1].channels = channels;
  frames[1].pts_us = 100;
  frames[1].data.resize(nb_samples_per_frame * channels * sizeof(int16_t), 0);
  
  // Frame 3: pts_us = 50'000'000 (50 seconds - huge jump) - GARBAGE
  frames[2].nb_samples = nb_samples_per_frame;
  frames[2].sample_rate = sample_rate;
  frames[2].channels = channels;
  frames[2].pts_us = 50'000'000;
  frames[2].data.resize(nb_samples_per_frame * channels * sizeof(int16_t), 0);
  
  // Push frames to sink
  for (const auto& frame : frames) {
    sink->ConsumeAudio(frame);
  }
  
  // Give mux loop time to process
  std::this_thread::sleep_for(std::chrono::milliseconds(300));
  
  // Stop sink
  sink->Stop();
  sink.reset();
  close(write_fd);
  
  // Verify captured PTS values
  const auto& pts_values = fake_encoder_ptr->captured_audio_pts90k;
  
  ASSERT_GE(pts_values.size(), 3u) 
      << "Expected at least 3 audio frames to be encoded";
  
  // 1. Verify monotonicity (strictly increasing)
  for (size_t i = 1; i < pts_values.size(); ++i) {
    EXPECT_GT(pts_values[i], pts_values[i - 1])
        << "Audio PTS must be strictly increasing. "
        << "PTS[" << i - 1 << "] = " << pts_values[i - 1] << ", "
        << "PTS[" << i << "] = " << pts_values[i]
        << " (FAILS if using audio_frame.pts_us which is non-monotonic)";
  }
  
  // 2. Verify PTS deltas match sample-based calculation
  // Expected delta: (nb_samples * 90000) / sample_rate
  // For 1024 samples at 48kHz: (1024 * 90000) / 48000 = 1920
  int64_t expected_delta_90k = (nb_samples_per_frame * 90000) / sample_rate;
  
  for (size_t i = 1; i < std::min(pts_values.size(), size_t(3)); ++i) {
    int64_t actual_delta = pts_values[i] - pts_values[i - 1];
    
    EXPECT_NEAR(actual_delta, expected_delta_90k, 1)
        << "Audio PTS delta must match sample-based calculation. "
        << "Expected: " << expected_delta_90k << ", "
        << "Actual: " << actual_delta
        << " (FAILS if using audio_frame.pts_us)";
  }
  
  // 3. Verify PTS does NOT match transformed content pts_us
  // If sink is using pts_us, we'd see:
  //   frame[0]: (1'000'000 * 90) / 1000 = 90'000
  //   frame[1]: (100 * 90) / 1000 = 9
  //   frame[2]: (50'000'000 * 90) / 1000 = 4'500'000
  
  if (pts_values.size() >= 2) {
    int64_t wrong_pts_0 = (frames[0].pts_us * 90) / 1000;
    int64_t wrong_pts_1 = (frames[1].pts_us * 90) / 1000;
    
    // If using pts_us, frame[1] PTS would be 9, way smaller than frame[0]'s 90000
    // The delta would be negative: 9 - 90000 = -89991
    int64_t delta_0_1 = pts_values[1] - pts_values[0];
    int64_t wrong_delta = wrong_pts_1 - wrong_pts_0;  // -89991
    
    EXPECT_NE(delta_0_1, wrong_delta)
        << "Audio PTS delta MUST NOT match content pts_us delta. "
        << "Sample-based delta: ~" << expected_delta_90k << ", "
        << "If using pts_us delta would be: " << wrong_delta
        << " (negative because pts_us is non-monotonic)";
    
    // Explicitly check frame[1] is NOT the wrong value
    EXPECT_NE(pts_values[1], wrong_pts_1)
        << "Frame[1] PTS MUST NOT be " << wrong_pts_1 
        << " (transformed from pts_us=100). "
        << "This FAILS if using audio_frame.pts_us.";
  }
  
  // Summary: This test FAILS if MpegTSOutputSink uses audio_frame.pts_us
  // It PASSES only when using sample clock for PTS derivation.
}

