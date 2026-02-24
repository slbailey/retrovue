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

#include <mutex>
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
 private:
  std::vector<int64_t> captured_real_audio_pts90k_;
  std::vector<int64_t> captured_silence_audio_pts90k_;
  mutable std::mutex m_;

 public:
  explicit FakeEncoderPipeline(const MpegTSPlayoutSinkConfig& config)
      : EncoderPipeline(config) {
    captured_real_audio_pts90k_.reserve(16);
    captured_silence_audio_pts90k_.reserve(16);
  }

  // Capture audio PTS without actual encoding (thread-safe)
  // Real and silence frames recorded separately for contract assertions.
  // Signature MUST match EncoderPipeline.hpp exactly (const ref, default param).
  bool encodeAudioFrame(const retrovue::buffer::AudioFrame& audio_frame, int64_t pts90k,
                        bool is_silence_pad = false) override {
    std::cout << "[FakeEncoderPipeline::encodeAudioFrame] pts90k=" << pts90k
              << " is_silence_pad=" << is_silence_pad
              << " nb_samples=" << audio_frame.nb_samples << std::endl;
    std::lock_guard<std::mutex> lock(m_);
    if (is_silence_pad) {
      captured_silence_audio_pts90k_.push_back(pts90k);
    } else {
      captured_real_audio_pts90k_.push_back(pts90k);
    }
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
  
  // All accessors take m_ for full duration so test thread never reads while mux thread pushes.

  // Thread-safe size check (real audio only; used to wait for N real frames)
  size_t CaptureCount() const {
    std::lock_guard<std::mutex> lock(m_);
    return captured_real_audio_pts90k_.size();
  }

  // Thread-safe silence count (for logging only; test does not fail on silence yet)
  size_t SilenceCaptureCount() const {
    std::lock_guard<std::mutex> lock(m_);
    return captured_silence_audio_pts90k_.size();
  }

  // Thread-safe copy for assertions (real audio PTS only). Copy is made under lock.
  std::vector<int64_t> GetCapturedPTS() const {
    std::lock_guard<std::mutex> lock(m_);
    std::vector<int64_t> copy = captured_real_audio_pts90k_;
    return copy;
  }
};

} // anonymous namespace

TEST(INV_AUDIO_PTS_HOUSE_CLOCK_001, MpegTSOutputSink_AudioPTS_IgnoresContentPTS_UsesSampleClock) {
  // Create dummy pipe (sink writes to it, we do not read it)
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
  
  // =========================================================================
  // CRITICAL: Add dummy video frame to drive mux loop
  // =========================================================================
  // Mux loop is video-driven. Audio drains only when video frame is dequeued.
  // Video PTS defines cutoff: audio_frame.pts_us <= video_frame.metadata.pts
  // =========================================================================
  
  Frame video_frame;
  video_frame.metadata.pts = 1'000'000;   // 1 second in microseconds
  video_frame.metadata.dts = 1'000'000;
  video_frame.metadata.duration = 1.0 / 30.0;
  video_frame.width = 640;
  video_frame.height = 480;
  // Allocate minimal YUV420 data (not actually used by FakeEncoder)
  size_t yuv_size = video_frame.width * video_frame.height * 3 / 2;
  video_frame.data.resize(yuv_size, 0);
  
  sink->ConsumeVideo(video_frame);
  
  // =========================================================================
  // Create 3 audio frames with garbage/non-monotonic pts_us
  // =========================================================================
  // These pts_us values are GARBAGE and should be IGNORED.
  // Expected behavior: encoded PTS is monotonic and sample-based.
  // Adjusted to be <= video PTS (1'000'000) for mux loop gating.
  // =========================================================================
  
  constexpr int nb_samples_per_frame = 1024;
  
  std::vector<AudioFrame> frames(3);
  
  // Frame 1: pts_us = 500'000 (0.5 sec) - GARBAGE but <= video PTS
  frames[0].nb_samples = nb_samples_per_frame;
  frames[0].sample_rate = 48000;  // 48000
  frames[0].channels = 2;       // 2
  frames[0].pts_us = 500'000;  // GARBAGE VALUE (should be ignored)
  frames[0].data.resize(nb_samples_per_frame * frames[0].channels * sizeof(int16_t), 0);
  
  // Frame 2: pts_us = 100 (NON-MONOTONIC! Way earlier than frame 1)
  frames[1].nb_samples = nb_samples_per_frame;
  frames[1].sample_rate = 48000;
  frames[1].channels = 2;
  frames[1].pts_us = 100;  // GARBAGE VALUE (should be ignored)
  frames[1].data.resize(nb_samples_per_frame * frames[1].channels * sizeof(int16_t), 0);
  
  // Frame 3: pts_us = 900'000 (0.9 sec - another jump)
  frames[2].nb_samples = nb_samples_per_frame;
  frames[2].sample_rate = 48000;
  frames[2].channels = 2;
  frames[2].pts_us = 900'000;  // GARBAGE VALUE (should be ignored)
  frames[2].data.resize(nb_samples_per_frame * frames[2].channels * sizeof(int16_t), 0);
  
  // Push audio frames to sink
  for (const auto& frame : frames) {
    sink->ConsumeAudio(frame);
  }
  
  // =========================================================================
  // SYNCHRONIZATION: Wait until 3 frames are captured (with timeout)
  // =========================================================================
  
  bool captured_all = false;
  for (int attempt = 0; attempt < 50; ++attempt) {  // 5 second timeout
    if (fake_encoder_ptr->CaptureCount() >= 3) {
      captured_all = true;
      break;
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
  }
  
  ASSERT_TRUE(captured_all)
      << "Timeout waiting for 3 audio frames to be captured. "
      << "Got: " << fake_encoder_ptr->CaptureCount();

  // =========================================================================
  // SNAPSHOT captured data BEFORE Stop(): Stop() destroys encoder_ (and the
  // injected FakeEncoderPipeline), so fake_encoder_ptr would be dangling.
  // =========================================================================
  const std::vector<int64_t> pts_values = fake_encoder_ptr->GetCapturedPTS();
  const size_t silence_captured = fake_encoder_ptr->SilenceCaptureCount();

  // =========================================================================
  // Now stop sink and join MuxLoop thread (encoder_ is destroyed here)
  // =========================================================================
  sink->Stop();
  sink.reset();
  close(write_fd);

  // Assertions use local pts_values only; do not touch fake_encoder_ptr after Stop().

  // Log silence frames only; do not fail the test on silence count yet
  std::cout << "\n[INV-AUDIO-PTS] Silence frames captured: " << silence_captured << "\n";
  
  ASSERT_GE(pts_values.size(), 3u) 
      << "Expected at least 3 REAL audio frames to be encoded. "
      << "Got: " << pts_values.size();
  
  // Debug output (real audio PTS only; monotonic+delta assertions use this)
  std::cout << "\n=== Real Audio PTS (captured_real_audio_pts90k) ===\n";
  std::cout << "Expected PTS: 0, 1920, 3840 (sample-based)\n";
  std::cout << "Actual PTS:   ";
  for (size_t i = 0; i < std::min(pts_values.size(), size_t(3)); ++i) {
    if (i > 0) std::cout << ", ";
    std::cout << pts_values[i];
  }
  std::cout << "\n\n";
  
  // 1️⃣ Verify monotonicity (strictly increasing)
  for (size_t i = 1; i < std::min(pts_values.size(), size_t(3)); ++i) {
    EXPECT_GT(pts_values[i], pts_values[i - 1])
        << "Audio PTS must be strictly increasing. "
        << "PTS[" << i - 1 << "] = " << pts_values[i - 1] << ", "
        << "PTS[" << i << "] = " << pts_values[i]
        << " (FAILS if using audio_frame.pts_us which is non-monotonic: 500000, 100, 900000)";
  }
  
  // 2️⃣ Verify PTS deltas match sample-based calculation
  // Expected delta: (nb_samples * 90000) / sample_rate
  // For 1024 samples at 48kHz: (1024 * 90000) / 48000 = 1920
  int64_t expected_delta_90k = (nb_samples_per_frame * 90000) / 48000;
  
  for (size_t i = 1; i < std::min(pts_values.size(), size_t(3)); ++i) {
    int64_t actual_delta = pts_values[i] - pts_values[i - 1];
    
    EXPECT_NEAR(actual_delta, expected_delta_90k, 1)
        << "Audio PTS delta must match sample-based calculation. "
        << "Expected: " << expected_delta_90k << ", "
        << "Actual: " << actual_delta
        << " (FAILS if using audio_frame.pts_us - deltas would be inconsistent)";
  }
  
  // 3️⃣ Verify PTS does NOT match transformed content pts_us
  // If sink is using pts_us, we would see:
  //   frame[0]: (500'000 * 90) / 1000 = 45'000
  //   frame[1]: (100 * 90) / 1000 = 9
  //   frame[2]: (900'000 * 90) / 1000 = 81'000
  
  if (pts_values.size() >= 2) {
    int64_t wrong_pts_0 = (frames[0].pts_us * 90) / 1000;  // 45000
    int64_t wrong_pts_1 = (frames[1].pts_us * 90) / 1000;  // 9
    
    // If using pts_us, frame[1] PTS would be 9, way smaller than frame[0]'s 45000
    // The delta would be negative: 9 - 45000 = -44991
    int64_t delta_0_1 = pts_values[1] - pts_values[0];
    int64_t wrong_delta = wrong_pts_1 - wrong_pts_0;  // -44991
    
    EXPECT_NE(delta_0_1, wrong_delta)
        << "Audio PTS delta MUST NOT match content pts_us delta. "
        << "Sample-based delta: ~" << expected_delta_90k << ", "
        << "If using pts_us delta would be: " << wrong_delta
        << " (negative because pts_us is non-monotonic: 500000, 100, 900000)";
    
    // Explicitly check frame[1] is NOT the wrong value
    EXPECT_NE(pts_values[1], wrong_pts_1)
        << "Frame[1] PTS MUST NOT be " << wrong_pts_1 
        << " (transformed from pts_us=100). "
        << "This FAILS if using audio_frame.pts_us.";
  }
  
  // =========================================================================
  // Summary: This test FAILS if MpegTSOutputSink uses audio_frame.pts_us
  // It PASSES only when using sample clock for PTS derivation.
  // =========================================================================
}
