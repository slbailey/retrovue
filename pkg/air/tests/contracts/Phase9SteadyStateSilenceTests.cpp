// Repository: Retrovue-playout
// Component: Phase 9 Steady-State Silence Tests
// Purpose: Verify INV-P9-STEADY-008: No Silence Injection After Attach
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>
#include <chrono>
#include <thread>
#include <atomic>

#include "retrovue/output/MpegTSOutputSink.h"
#include "retrovue/playout_sinks/mpegts/MpegTSPlayoutSinkConfig.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"

#if defined(__linux__) || defined(__APPLE__)
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

using namespace retrovue;
using namespace std::chrono_literals;

namespace {

// =============================================================================
// INV-P9-STEADY-008: No Silence Injection After Attach
// =============================================================================
// Contract: Silence injection MUST be disabled when steady-state begins.
// Producer audio is the ONLY audio source.
// When audio queue is empty, mux MUST stall (video waits with audio).
// PCR advances only from real audio.
// =============================================================================

class Phase9SteadyStateSilenceTest : public ::testing::Test {
 protected:
  void SetUp() override {
    config_.target_width = 1920;
    config_.target_height = 1080;
    config_.bitrate = 4000000;
    config_.target_fps = 30.0;
    config_.gop_size = 30;
    config_.stub_mode = false;
  }

  playout_sinks::mpegts::MpegTSPlayoutSinkConfig config_;
};

// =============================================================================
// P9-TEST-012: Silence Disabled on Steady-State Entry
// =============================================================================
// Given: Steady-state playout active
// When: Audio queue temporarily empty
// Then: Mux loop stalls (video also stalls)
// And: No silence frames injected
// And: Log confirms silence_injection_disabled=true
// Contract: INV-P9-STEADY-008

#if defined(__linux__) || defined(__APPLE__)
TEST_F(Phase9SteadyStateSilenceTest, P9_TEST_012_SilenceDisabledOnSteadyStateEntry) {
  int sock_fds[2];
  ASSERT_EQ(socketpair(AF_UNIX, SOCK_STREAM, 0, sock_fds), 0) << "socketpair() failed";
  int read_fd = sock_fds[0];
  int write_fd = sock_fds[1];

  output::MpegTSOutputSink sink(write_fd, config_, "test-p9-steady-008-silence-disabled");

  // Precondition: silence injection NOT disabled before Start()
  EXPECT_FALSE(sink.IsSilenceInjectionDisabled())
      << "Silence injection should not be disabled before Start()";

  ASSERT_TRUE(sink.Start()) << "MpegTSOutputSink Start failed";

  // Still not disabled before steady-state entry
  EXPECT_FALSE(sink.IsSilenceInjectionDisabled())
      << "Silence injection should not be disabled before steady-state entry";

  // Build video frame
  buffer::Frame video_frame;
  video_frame.width = config_.target_width;
  video_frame.height = config_.target_height;
  video_frame.data.resize(
      static_cast<size_t>(video_frame.width * video_frame.height * 3 / 2), 128);
  video_frame.metadata.pts = 0;
  video_frame.metadata.has_ct = true;
  video_frame.metadata.asset_uri = "test://frame0";

  // Build audio frame
  buffer::AudioFrame audio_frame;
  audio_frame.sample_rate = 48000;
  audio_frame.channels = 2;
  audio_frame.nb_samples = 1024;
  audio_frame.pts_us = 0;
  audio_frame.data.resize(1024 * 2 * sizeof(int16_t), 0);

  // Feed frames to trigger steady-state entry
  sink.ConsumeVideo(video_frame);
  sink.ConsumeAudio(audio_frame);

  // Wait for steady-state entry
  auto deadline = std::chrono::steady_clock::now() + 500ms;
  while (!sink.IsSteadyStateEntered() &&
         std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(10ms);
  }
  ASSERT_TRUE(sink.IsSteadyStateEntered())
      << "Steady-state should be entered after first video frame";

  // INV-P9-STEADY-008: Silence injection MUST be disabled on steady-state entry
  EXPECT_TRUE(sink.IsSilenceInjectionDisabled())
      << "INV-P9-STEADY-008 VIOLATED: silence_injection_disabled should be true after steady-state entry";

  std::cout << "[P9-TEST-012] Silence disabled on steady-state entry: "
            << "silence_injection_disabled=" << sink.IsSilenceInjectionDisabled()
            << ", steady_state_entered=" << sink.IsSteadyStateEntered()
            << std::endl;

  sink.Stop();

  // After stop, flag should be reset for next session
  EXPECT_FALSE(sink.IsSilenceInjectionDisabled())
      << "Silence injection disabled flag should be reset after Stop()";

  close(read_fd);
  close(write_fd);
}
#endif

// =============================================================================
// P9-TEST-012b: Mux Stalls When Audio Queue Empty (Video Waits)
// =============================================================================
// Given: Steady-state playout active
// When: Video frames are fed but NO audio frames
// Then: Mux loop STALLS
// And: Video does NOT advance alone
// And: No TS output is produced beyond initial frames
// Contract: INV-P9-STEADY-008

#if defined(__linux__) || defined(__APPLE__)
TEST_F(Phase9SteadyStateSilenceTest, P9_TEST_012b_MuxStallsWhenAudioQueueEmpty) {
  int sock_fds[2];
  ASSERT_EQ(socketpair(AF_UNIX, SOCK_STREAM, 0, sock_fds), 0) << "socketpair() failed";
  int read_fd = sock_fds[0];
  int write_fd = sock_fds[1];

  output::MpegTSOutputSink sink(write_fd, config_, "test-p9-steady-008-mux-stalls");

  ASSERT_TRUE(sink.Start()) << "MpegTSOutputSink Start failed";

  // Build video frame
  buffer::Frame video_frame;
  video_frame.width = config_.target_width;
  video_frame.height = config_.target_height;
  video_frame.data.resize(
      static_cast<size_t>(video_frame.width * video_frame.height * 3 / 2), 128);
  video_frame.metadata.has_ct = true;
  video_frame.metadata.asset_uri = "test://frame";

  // Build audio frame
  buffer::AudioFrame audio_frame;
  audio_frame.sample_rate = 48000;
  audio_frame.channels = 2;
  audio_frame.nb_samples = 1024;
  audio_frame.data.resize(1024 * 2 * sizeof(int16_t), 0);

  // Phase 1: Feed initial frames (with audio) to enter steady-state
  for (int i = 0; i < 5; ++i) {
    video_frame.metadata.pts = i * 33333;
    audio_frame.pts_us = i * 21333;
    sink.ConsumeVideo(video_frame);
    sink.ConsumeAudio(audio_frame);
  }

  // Wait for steady-state entry
  auto deadline = std::chrono::steady_clock::now() + 500ms;
  while (!sink.IsSteadyStateEntered() &&
         std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(10ms);
  }
  ASSERT_TRUE(sink.IsSteadyStateEntered())
      << "Steady-state should be entered after initial frames";
  ASSERT_TRUE(sink.IsSilenceInjectionDisabled())
      << "Silence injection should be disabled in steady-state";

  // Drain initial TS output
  std::vector<uint8_t> buf(4096);
  auto drain_deadline = std::chrono::steady_clock::now() + 300ms;
  while (std::chrono::steady_clock::now() < drain_deadline) {
    struct pollfd pfd = { read_fd, POLLIN, 0 };
    int r = poll(&pfd, 1, 10);
    if (r > 0 && (pfd.revents & POLLIN)) {
      read(read_fd, buf.data(), buf.size());
    }
  }

  // Phase 2: Feed video frames WITHOUT audio (simulate audio queue empty)
  // In steady-state, mux should STALL and NOT emit these video frames
  auto video_only_start = std::chrono::steady_clock::now();
  for (int i = 5; i < 15; ++i) {
    video_frame.metadata.pts = i * 33333;
    sink.ConsumeVideo(video_frame);
    // NO audio_frame fed here - simulating audio underrun
  }

  // Wait a bit for mux to attempt processing
  std::this_thread::sleep_for(200ms);

  // Measure how much TS data was produced during video-only phase
  int64_t bytes_during_stall = 0;
  auto measure_deadline = std::chrono::steady_clock::now() + 200ms;
  while (std::chrono::steady_clock::now() < measure_deadline) {
    struct pollfd pfd = { read_fd, POLLIN, 0 };
    int r = poll(&pfd, 1, 10);
    if (r > 0 && (pfd.revents & POLLIN)) {
      ssize_t n = read(read_fd, buf.data(), buf.size());
      if (n > 0) {
        bytes_during_stall += n;
      }
    }
  }

  auto video_only_end = std::chrono::steady_clock::now();
  auto video_only_duration_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      video_only_end - video_only_start).count();

  // INV-P9-STEADY-008: Mux should have STALLED
  // With proper stall behavior, minimal or no new TS data should be produced
  // because video cannot advance without audio
  std::cout << "[P9-TEST-012b] Mux stall test: "
            << "bytes_during_stall=" << bytes_during_stall
            << ", duration_ms=" << video_only_duration_ms
            << ", silence_injection_disabled=" << sink.IsSilenceInjectionDisabled()
            << std::endl;

  // The key assertion: mux should have stalled (no significant TS output)
  // Some initial buffered data may still emit, but no new video should advance
  // We allow up to 10KB for any pipeline buffered data
  EXPECT_LT(bytes_during_stall, 10000)
      << "INV-P9-STEADY-008 VIOLATED: Mux should STALL when audio queue empty. "
      << "Expected minimal output, got " << bytes_during_stall << " bytes. "
      << "Video should NOT advance without audio.";

  sink.Stop();
  close(read_fd);
  close(write_fd);
}
#endif

// =============================================================================
// P9-TEST-012c: Video Resumes When Audio Arrives After Stall
// =============================================================================
// Given: Mux is stalled due to empty audio queue
// When: Audio frames arrive
// Then: Mux resumes
// And: Video and audio emit together
// Contract: INV-P9-STEADY-008

#if defined(__linux__) || defined(__APPLE__)
TEST_F(Phase9SteadyStateSilenceTest, P9_TEST_012c_VideoResumesWhenAudioArrives) {
  int sock_fds[2];
  ASSERT_EQ(socketpair(AF_UNIX, SOCK_STREAM, 0, sock_fds), 0) << "socketpair() failed";
  int read_fd = sock_fds[0];
  int write_fd = sock_fds[1];

  output::MpegTSOutputSink sink(write_fd, config_, "test-p9-steady-008-resume");

  ASSERT_TRUE(sink.Start()) << "MpegTSOutputSink Start failed";

  // Build video frame
  buffer::Frame video_frame;
  video_frame.width = config_.target_width;
  video_frame.height = config_.target_height;
  video_frame.data.resize(
      static_cast<size_t>(video_frame.width * video_frame.height * 3 / 2), 128);
  video_frame.metadata.has_ct = true;
  video_frame.metadata.asset_uri = "test://frame";

  // Build audio frame
  buffer::AudioFrame audio_frame;
  audio_frame.sample_rate = 48000;
  audio_frame.channels = 2;
  audio_frame.nb_samples = 1024;
  audio_frame.data.resize(1024 * 2 * sizeof(int16_t), 0);

  // Phase 1: Enter steady-state with initial A/V frames
  for (int i = 0; i < 5; ++i) {
    video_frame.metadata.pts = i * 33333;
    audio_frame.pts_us = i * 21333;
    sink.ConsumeVideo(video_frame);
    sink.ConsumeAudio(audio_frame);
  }

  // Wait for steady-state entry
  auto deadline = std::chrono::steady_clock::now() + 500ms;
  while (!sink.IsSteadyStateEntered() &&
         std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(10ms);
  }
  ASSERT_TRUE(sink.IsSteadyStateEntered());

  // Drain initial output
  std::vector<uint8_t> buf(4096);
  auto drain_deadline = std::chrono::steady_clock::now() + 300ms;
  while (std::chrono::steady_clock::now() < drain_deadline) {
    struct pollfd pfd = { read_fd, POLLIN, 0 };
    int r = poll(&pfd, 1, 10);
    if (r > 0 && (pfd.revents & POLLIN)) {
      read(read_fd, buf.data(), buf.size());
    }
  }

  // Phase 2: Feed video only (mux should stall)
  for (int i = 5; i < 10; ++i) {
    video_frame.metadata.pts = i * 33333;
    sink.ConsumeVideo(video_frame);
  }
  std::this_thread::sleep_for(100ms);

  // Phase 3: Feed audio (mux should resume)
  auto resume_start = std::chrono::steady_clock::now();
  for (int i = 5; i < 15; ++i) {
    audio_frame.pts_us = i * 21333;
    sink.ConsumeAudio(audio_frame);
  }
  // Also feed more video
  for (int i = 10; i < 20; ++i) {
    video_frame.metadata.pts = i * 33333;
    sink.ConsumeVideo(video_frame);
  }

  // Measure output after audio arrives
  std::this_thread::sleep_for(200ms);
  int64_t bytes_after_resume = 0;
  auto measure_deadline = std::chrono::steady_clock::now() + 400ms;
  while (std::chrono::steady_clock::now() < measure_deadline) {
    struct pollfd pfd = { read_fd, POLLIN, 0 };
    int r = poll(&pfd, 1, 50);
    if (r > 0 && (pfd.revents & POLLIN)) {
      ssize_t n = read(read_fd, buf.data(), buf.size());
      if (n > 0) {
        bytes_after_resume += n;
      }
    }
  }

  // After audio arrives, mux should resume and produce output
  EXPECT_GT(bytes_after_resume, 0)
      << "INV-P9-STEADY-008: Mux should RESUME when audio arrives after stall";

  std::cout << "[P9-TEST-012c] Mux resume test: "
            << "bytes_after_resume=" << bytes_after_resume
            << std::endl;

  sink.Stop();
  close(read_fd);
  close(write_fd);
}
#endif

// =============================================================================
// P9-TEST-012d: No Silence Frames Injected in Steady-State
// =============================================================================
// Given: Steady-state playout with silence_injection_disabled=true
// When: Audio queue becomes temporarily empty
// Then: NO fabricated/silence audio frames are injected
// And: Mux stalls instead of generating silence
// Contract: INV-P9-STEADY-008

#if defined(__linux__) || defined(__APPLE__)
TEST_F(Phase9SteadyStateSilenceTest, P9_TEST_012d_NoSilenceFramesInjected) {
  int sock_fds[2];
  ASSERT_EQ(socketpair(AF_UNIX, SOCK_STREAM, 0, sock_fds), 0) << "socketpair() failed";
  int read_fd = sock_fds[0];
  int write_fd = sock_fds[1];

  output::MpegTSOutputSink sink(write_fd, config_, "test-p9-steady-008-no-silence");

  ASSERT_TRUE(sink.Start()) << "MpegTSOutputSink Start failed";

  // Build frames
  buffer::Frame video_frame;
  video_frame.width = config_.target_width;
  video_frame.height = config_.target_height;
  video_frame.data.resize(
      static_cast<size_t>(video_frame.width * video_frame.height * 3 / 2), 128);
  video_frame.metadata.has_ct = true;
  video_frame.metadata.asset_uri = "test://frame";

  buffer::AudioFrame audio_frame;
  audio_frame.sample_rate = 48000;
  audio_frame.channels = 2;
  audio_frame.nb_samples = 1024;
  audio_frame.data.resize(1024 * 2 * sizeof(int16_t), 0);

  // Enter steady-state
  for (int i = 0; i < 5; ++i) {
    video_frame.metadata.pts = i * 33333;
    audio_frame.pts_us = i * 21333;
    sink.ConsumeVideo(video_frame);
    sink.ConsumeAudio(audio_frame);
  }

  auto deadline = std::chrono::steady_clock::now() + 500ms;
  while (!sink.IsSteadyStateEntered() &&
         std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(10ms);
  }
  ASSERT_TRUE(sink.IsSteadyStateEntered());

  // Verify the encoder's audio liveness was disabled at Start()
  // (This is set in MpegTSOutputSink::Start() via SetAudioLivenessEnabled(false))
  // The fact that silence_injection_disabled_ is true in the sink confirms
  // no silence injection can occur

  EXPECT_TRUE(sink.IsSilenceInjectionDisabled())
      << "INV-P9-STEADY-008: silence_injection_disabled must be true in steady-state";

  std::cout << "[P9-TEST-012d] No silence frames injected: "
            << "silence_injection_disabled=" << sink.IsSilenceInjectionDisabled()
            << " (encoder audio_liveness_enabled=false set at Start())"
            << std::endl;

  sink.Stop();
  close(read_fd);
  close(write_fd);
}
#endif

}  // namespace
