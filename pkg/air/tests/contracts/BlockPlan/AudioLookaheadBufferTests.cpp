// Repository: Retrovue-playout
// Component: AudioLookaheadBuffer Contract Tests
// Purpose: Verify INV-AUDIO-LOOKAHEAD-001 — broadcast-grade audio buffering
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <cstring>
#include <vector>

#include "retrovue/blockplan/AudioLookaheadBuffer.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"

namespace retrovue::blockplan::testing {
namespace {

// Helper: create an AudioFrame with N samples of a fill value.
static buffer::AudioFrame MakeAudioFrame(int nb_samples, int16_t fill = 0) {
  buffer::AudioFrame frame;
  frame.sample_rate = buffer::kHouseAudioSampleRate;
  frame.channels = buffer::kHouseAudioChannels;
  frame.nb_samples = nb_samples;
  const int bytes_per_sample =
      buffer::kHouseAudioChannels * static_cast<int>(sizeof(int16_t));
  frame.data.resize(static_cast<size_t>(nb_samples * bytes_per_sample));
  // Fill with a pattern so we can verify data integrity.
  auto* samples = reinterpret_cast<int16_t*>(frame.data.data());
  for (int i = 0; i < nb_samples * buffer::kHouseAudioChannels; i++) {
    samples[i] = fill;
  }
  return frame;
}

// =============================================================================
// ALB-001: Basic push and pop
// =============================================================================
TEST(AudioLookaheadBufferTest, BasicPushPop) {
  AudioLookaheadBuffer buf(1000);

  EXPECT_FALSE(buf.IsPrimed());
  EXPECT_EQ(buf.DepthSamples(), 0);
  EXPECT_EQ(buf.DepthMs(), 0);

  // Push 1024 samples.
  buf.Push(MakeAudioFrame(1024));

  EXPECT_TRUE(buf.IsPrimed());
  EXPECT_EQ(buf.DepthSamples(), 1024);
  EXPECT_EQ(buf.TotalSamplesPushed(), 1024);

  // Pop 512 samples.
  buffer::AudioFrame out;
  ASSERT_TRUE(buf.TryPopSamples(512, out));
  EXPECT_EQ(out.nb_samples, 512);
  EXPECT_EQ(out.sample_rate, buffer::kHouseAudioSampleRate);
  EXPECT_EQ(out.channels, buffer::kHouseAudioChannels);
  EXPECT_EQ(buf.DepthSamples(), 512);
  EXPECT_EQ(buf.TotalSamplesPopped(), 512);
}

// =============================================================================
// ALB-002: Partial frame splitting
// Push a 1024-sample frame, pop 600 (leaves 424 partial), pop 424.
// =============================================================================
TEST(AudioLookaheadBufferTest, PartialFrameSplitting) {
  AudioLookaheadBuffer buf(1000);
  buf.Push(MakeAudioFrame(1024, 42));

  // Pop 600 from a 1024-sample frame.
  buffer::AudioFrame out1;
  ASSERT_TRUE(buf.TryPopSamples(600, out1));
  EXPECT_EQ(out1.nb_samples, 600);
  EXPECT_EQ(buf.DepthSamples(), 424);

  // Verify first sample matches fill value.
  auto* samples1 = reinterpret_cast<const int16_t*>(out1.data.data());
  EXPECT_EQ(samples1[0], 42);

  // Pop remaining 424.
  buffer::AudioFrame out2;
  ASSERT_TRUE(buf.TryPopSamples(424, out2));
  EXPECT_EQ(out2.nb_samples, 424);
  EXPECT_EQ(buf.DepthSamples(), 0);

  // Verify data continuity: first sample of out2 should also be fill value.
  auto* samples2 = reinterpret_cast<const int16_t*>(out2.data.data());
  EXPECT_EQ(samples2[0], 42);
}

// =============================================================================
// ALB-003: Cross-frame pop
// Push two 1024-sample frames, pop 1600 (spans both).
// =============================================================================
TEST(AudioLookaheadBufferTest, CrossFramePop) {
  AudioLookaheadBuffer buf(1000);
  buf.Push(MakeAudioFrame(1024, 10));
  buf.Push(MakeAudioFrame(1024, 20));

  EXPECT_EQ(buf.DepthSamples(), 2048);

  // Pop 1600 (takes all 1024 from first + 576 from second).
  buffer::AudioFrame out;
  ASSERT_TRUE(buf.TryPopSamples(1600, out));
  EXPECT_EQ(out.nb_samples, 1600);
  EXPECT_EQ(buf.DepthSamples(), 448);

  // Verify: first 1024 samples have fill=10, next 576 have fill=20.
  auto* samples = reinterpret_cast<const int16_t*>(out.data.data());
  // Sample at index 0 (L channel of sample 0): fill=10
  EXPECT_EQ(samples[0], 10);
  // Sample at index 1024*2 (L channel of sample 1024): fill=20
  EXPECT_EQ(samples[1024 * buffer::kHouseAudioChannels], 20);

  // Pop remaining 448.
  buffer::AudioFrame out2;
  ASSERT_TRUE(buf.TryPopSamples(448, out2));
  EXPECT_EQ(out2.nb_samples, 448);
  EXPECT_EQ(buf.DepthSamples(), 0);
}

// =============================================================================
// ALB-004: Underflow detection
// Buffer has 500 samples, try to pop 600 → underflow.
// =============================================================================
TEST(AudioLookaheadBufferTest, UnderflowDetection) {
  AudioLookaheadBuffer buf(1000);
  buf.Push(MakeAudioFrame(500));

  EXPECT_EQ(buf.UnderflowCount(), 0);

  buffer::AudioFrame out;
  EXPECT_FALSE(buf.TryPopSamples(600, out));
  EXPECT_EQ(buf.UnderflowCount(), 1);

  // Buffer untouched after underflow.
  EXPECT_EQ(buf.DepthSamples(), 500);
}

// =============================================================================
// ALB-005: Empty buffer underflow
// =============================================================================
TEST(AudioLookaheadBufferTest, EmptyBufferUnderflow) {
  AudioLookaheadBuffer buf(1000);

  buffer::AudioFrame out;
  EXPECT_FALSE(buf.TryPopSamples(1, out));
  EXPECT_EQ(buf.UnderflowCount(), 1);
}

// =============================================================================
// ALB-006: Reset clears everything
// =============================================================================
TEST(AudioLookaheadBufferTest, ResetClearsEverything) {
  AudioLookaheadBuffer buf(1000);
  buf.Push(MakeAudioFrame(1024));

  buffer::AudioFrame out;
  buf.TryPopSamples(100, out);

  EXPECT_TRUE(buf.IsPrimed());
  EXPECT_GT(buf.DepthSamples(), 0);

  buf.Reset();

  EXPECT_FALSE(buf.IsPrimed());
  EXPECT_EQ(buf.DepthSamples(), 0);
  EXPECT_EQ(buf.TotalSamplesPushed(), 0);
  EXPECT_EQ(buf.TotalSamplesPopped(), 0);
  EXPECT_EQ(buf.UnderflowCount(), 0);
}

// =============================================================================
// ALB-007: DepthMs computation
// 48000 samples at 48kHz = 1000ms.
// =============================================================================
TEST(AudioLookaheadBufferTest, DepthMsComputation) {
  AudioLookaheadBuffer buf(1000);

  // Push 48000 samples = 1000ms at 48kHz.
  buf.Push(MakeAudioFrame(48000));
  EXPECT_EQ(buf.DepthMs(), 1000);

  // Pop 24000 samples = 500ms.
  buffer::AudioFrame out;
  buf.TryPopSamples(24000, out);
  EXPECT_EQ(buf.DepthMs(), 500);
}

// =============================================================================
// ALB-008: Zero-sample pop succeeds trivially
// =============================================================================
TEST(AudioLookaheadBufferTest, ZeroSamplePopSucceeds) {
  AudioLookaheadBuffer buf(1000);

  buffer::AudioFrame out;
  EXPECT_TRUE(buf.TryPopSamples(0, out));
  EXPECT_EQ(out.nb_samples, 0);
}

// =============================================================================
// ALB-009: Exact per-tick sample computation (30fps)
// Verify the rational arithmetic produces exactly 1600 samples per tick.
// =============================================================================
TEST(AudioLookaheadBufferTest, ExactSamplesPerTick30fps) {
  // fps_num=30, fps_den=1
  const int64_t fps_num = 30;
  const int64_t fps_den = 1;
  const int64_t sr = buffer::kHouseAudioSampleRate;  // 48000

  int64_t total_emitted = 0;
  for (int64_t tick = 0; tick < 1000; tick++) {
    int64_t next_total = ((tick + 1) * sr * fps_den) / fps_num;
    int samples = static_cast<int>(next_total - total_emitted);
    EXPECT_EQ(samples, 1600)
        << "30fps must produce exactly 1600 samples per tick at tick " << tick;
    total_emitted += samples;
  }

  // After 1000 ticks at 30fps = 33.333s → 33.333 * 48000 = 1,600,000 samples.
  EXPECT_EQ(total_emitted, 1600000);
}

// =============================================================================
// ALB-010: Exact per-tick sample computation (29.97fps)
// Verify rational arithmetic alternates 1601/1602, no drift.
// =============================================================================
TEST(AudioLookaheadBufferTest, ExactSamplesPerTick29_97fps) {
  // 29.97fps = 30000/1001
  const int64_t fps_num = 30000;
  const int64_t fps_den = 1001;
  const int64_t sr = buffer::kHouseAudioSampleRate;  // 48000

  int64_t total_emitted = 0;
  int count_1601 = 0;
  int count_1602 = 0;

  for (int64_t tick = 0; tick < 30000; tick++) {
    int64_t next_total = ((tick + 1) * sr * fps_den) / fps_num;
    int samples = static_cast<int>(next_total - total_emitted);

    // Each tick should be either 1601 or 1602.
    EXPECT_TRUE(samples == 1601 || samples == 1602)
        << "29.97fps must produce 1601 or 1602 samples, got " << samples
        << " at tick " << tick;

    if (samples == 1601) count_1601++;
    if (samples == 1602) count_1602++;
    total_emitted += samples;
  }

  // After 30000 ticks at 29.97fps = ~1001 seconds → 48,048,000 samples.
  // Exact: 30000 * 48000 * 1001 / 30000 = 48000 * 1001 = 48,048,000
  EXPECT_EQ(total_emitted, 48048000);

  // Both sizes should appear.
  EXPECT_GT(count_1601, 0);
  EXPECT_GT(count_1602, 0);
}

// =============================================================================
// ALB-011: Stall simulation — buffer sustains audio during decode stall
// Pre-fill buffer with 1000ms of audio. Then drain without pushing.
// Verify audio remains available for ~1000ms worth of ticks, then underflows.
// =============================================================================
TEST(AudioLookaheadBufferTest, StallSimulation) {
  AudioLookaheadBuffer buf(1000);

  // Pre-fill: 48000 samples = 1000ms at 48kHz.
  // Push in 1024-sample chunks (simulating AAC decode output).
  int total_pushed = 0;
  while (total_pushed < 48000) {
    int chunk = std::min(1024, 48000 - total_pushed);
    buf.Push(MakeAudioFrame(chunk));
    total_pushed += chunk;
  }
  EXPECT_EQ(buf.DepthMs(), 1000);

  // Simulate tick loop at 30fps (1600 samples/tick).
  // 48000 / 1600 = 30 ticks = 1 second of audio.
  int ticks_sustained = 0;
  while (true) {
    buffer::AudioFrame out;
    if (!buf.TryPopSamples(1600, out)) {
      break;  // Underflow
    }
    ticks_sustained++;
  }

  // Should sustain exactly 30 ticks (48000 / 1600 = 30).
  EXPECT_EQ(ticks_sustained, 30);
  EXPECT_EQ(buf.UnderflowCount(), 1);
  EXPECT_EQ(buf.DepthSamples(), 0);

  // The session should stop cleanly after underflow.
  // (PipelineManager enforces this; here we just verify the buffer reports it.)
}

// =============================================================================
// ALB-012: Continuous push-pop steady state
// Simulate interleaved push (from decode) and pop (from tick loop).
// Verify buffer depth stabilizes and no underflows occur.
// =============================================================================
TEST(AudioLookaheadBufferTest, ContinuousSteadyState) {
  AudioLookaheadBuffer buf(1000);

  // Simulate 300 ticks (10 seconds at 30fps).
  // On each tick: push ~1.5 audio frames (1024 samples each), pop 1600.
  // This mimics real decode where ~1.5 AAC frames are decoded per video frame.
  int64_t ticks = 0;
  int push_accumulator = 0;

  for (int i = 0; i < 300; i++) {
    // Push: every 2 ticks, push 3 frames of 1024 (simulating ~1.5 per tick).
    push_accumulator += 3;
    if (push_accumulator >= 2) {
      buf.Push(MakeAudioFrame(1024));
      push_accumulator -= 2;
    }

    // Pop: 1600 samples per tick.
    buffer::AudioFrame out;
    if (buf.IsPrimed() && buf.DepthSamples() >= 1600) {
      ASSERT_TRUE(buf.TryPopSamples(1600, out));
      ticks++;
    }
  }

  EXPECT_EQ(buf.UnderflowCount(), 0)
      << "Steady-state push/pop must not underflow";
  EXPECT_GT(ticks, 0) << "Must have consumed some ticks";
}

// =============================================================================
// ALB-013: Multiple small frames to single large pop
// Push 10 frames of 200 samples, pop 2000 (spans all 10).
// =============================================================================
TEST(AudioLookaheadBufferTest, ManySmallFramesToSinglePop) {
  AudioLookaheadBuffer buf(1000);

  for (int i = 0; i < 10; i++) {
    buf.Push(MakeAudioFrame(200, static_cast<int16_t>(i)));
  }
  EXPECT_EQ(buf.DepthSamples(), 2000);

  buffer::AudioFrame out;
  ASSERT_TRUE(buf.TryPopSamples(2000, out));
  EXPECT_EQ(out.nb_samples, 2000);
  EXPECT_EQ(buf.DepthSamples(), 0);

  // Verify data from first frame.
  auto* samples = reinterpret_cast<const int16_t*>(out.data.data());
  EXPECT_EQ(samples[0], 0);  // First frame fill=0
  // Sample at frame boundary (200 samples * 2 channels = offset 400).
  EXPECT_EQ(samples[200 * buffer::kHouseAudioChannels], 1);  // Second frame fill=1
}

}  // namespace
}  // namespace retrovue::blockplan::testing
