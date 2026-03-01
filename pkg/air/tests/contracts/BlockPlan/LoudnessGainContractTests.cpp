// Repository: Retrovue-playout
// Component: Loudness Gain Contract Tests
// Purpose: INV-LOUDNESS-NORMALIZED-001 — validate gain arithmetic on S16 audio
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>
#include <cstring>
#include <vector>

#include "retrovue/blockplan/LoudnessGain.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"

using namespace retrovue;

// Helper: create an AudioFrame with constant sample value
static buffer::AudioFrame MakeFrame(int16_t sample_value, int nb_samples, int channels = 2) {
  buffer::AudioFrame frame;
  frame.sample_rate = 48000;
  frame.channels = channels;
  frame.nb_samples = nb_samples;
  frame.pts_us = 1000000;  // 1 second

  size_t total_samples = static_cast<size_t>(nb_samples) * static_cast<size_t>(channels);
  frame.data.resize(total_samples * sizeof(int16_t));
  auto* samples = reinterpret_cast<int16_t*>(frame.data.data());
  for (size_t i = 0; i < total_samples; ++i) {
    samples[i] = sample_value;
  }
  return frame;
}

// Helper: read sample at index
static int16_t ReadSample(const buffer::AudioFrame& frame, size_t index) {
  auto* samples = reinterpret_cast<const int16_t*>(frame.data.data());
  return samples[index];
}

// =============================================================================
// INV-LOUDNESS-NORMALIZED-001 Rule 1: gain_db = -6.0 → output ~50% of input
// =============================================================================

TEST(LoudnessGainContract, GainApplied_ReducesAmplitude) {
  // -6.0 dB ≈ 0.501 linear gain → samples should be roughly halved
  auto frame = MakeFrame(10000, 1024);
  float linear_gain = blockplan::GainDbToLinear(-6.0f);

  // Verify linear gain is approximately 0.5
  EXPECT_NEAR(linear_gain, 0.5012f, 0.01f);

  blockplan::ApplyGainS16(frame, linear_gain);

  // All samples should be approximately half of original
  auto* samples = reinterpret_cast<const int16_t*>(frame.data.data());
  for (int i = 0; i < 10; ++i) {
    EXPECT_NEAR(samples[i], 5012, 10)
        << "Sample " << i << " should be ~50% of 10000 with -6dB gain";
  }
}

// =============================================================================
// INV-LOUDNESS-NORMALIZED-001 Rule 1: gain_db = +6.0 → output ~200% of input
// =============================================================================

TEST(LoudnessGainContract, GainApplied_IncreasesAmplitude) {
  // +6.0 dB ≈ 1.995 linear gain → samples should roughly double
  auto frame = MakeFrame(5000, 1024);
  float linear_gain = blockplan::GainDbToLinear(6.0f);

  // Verify linear gain is approximately 2.0
  EXPECT_NEAR(linear_gain, 1.9953f, 0.01f);

  blockplan::ApplyGainS16(frame, linear_gain);

  auto* samples = reinterpret_cast<const int16_t*>(frame.data.data());
  for (int i = 0; i < 10; ++i) {
    EXPECT_NEAR(samples[i], 9977, 10)
        << "Sample " << i << " should be ~200% of 5000 with +6dB gain";
  }
}

// =============================================================================
// INV-LOUDNESS-NORMALIZED-001 Rule 4: gain_db = 0.0 → pass-through (bitwise)
// =============================================================================

TEST(LoudnessGainContract, ZeroGain_PassThrough) {
  // 0.0 dB = linear gain 1.0 → output must be bitwise identical to input
  auto frame = MakeFrame(12345, 512);

  // Save original data
  std::vector<uint8_t> original(frame.data.begin(), frame.data.end());

  float linear_gain = blockplan::GainDbToLinear(0.0f);
  EXPECT_FLOAT_EQ(linear_gain, 1.0f);

  blockplan::ApplyGainS16(frame, linear_gain);

  // Bitwise comparison
  ASSERT_EQ(frame.data.size(), original.size());
  EXPECT_EQ(std::memcmp(frame.data.data(), original.data(), original.size()), 0)
      << "0 dB gain must produce bitwise identical output";
}

// =============================================================================
// INV-LOUDNESS-NORMALIZED-001 Rule 3: clamp to int16 range, no wraparound
// =============================================================================

TEST(LoudnessGainContract, Clipping_ClampsToInt16Range) {
  // Large positive samples + positive gain → must clamp to +32767
  auto frame_pos = MakeFrame(30000, 64);
  float linear_gain = blockplan::GainDbToLinear(6.0f);  // ~2x
  blockplan::ApplyGainS16(frame_pos, linear_gain);

  auto* samples_pos = reinterpret_cast<const int16_t*>(frame_pos.data.data());
  for (int i = 0; i < 64 * 2; ++i) {
    EXPECT_EQ(samples_pos[i], 32767)
        << "Positive overflow must clamp to +32767, not wrap";
  }

  // Large negative samples + positive gain → must clamp to -32768
  auto frame_neg = MakeFrame(-30000, 64);
  blockplan::ApplyGainS16(frame_neg, linear_gain);

  auto* samples_neg = reinterpret_cast<const int16_t*>(frame_neg.data.data());
  for (int i = 0; i < 64 * 2; ++i) {
    EXPECT_EQ(samples_neg[i], -32768)
        << "Negative overflow must clamp to -32768, not wrap";
  }
}

// =============================================================================
// INV-LOUDNESS-NORMALIZED-001 Rule 2: nb_samples unchanged
// =============================================================================

TEST(LoudnessGainContract, SampleCount_Unchanged) {
  const int expected_samples = 1024;
  auto frame = MakeFrame(8000, expected_samples);
  int original_nb_samples = frame.nb_samples;
  size_t original_data_size = frame.data.size();

  blockplan::ApplyGainS16(frame, blockplan::GainDbToLinear(-3.0f));

  EXPECT_EQ(frame.nb_samples, original_nb_samples)
      << "nb_samples must not change after gain application";
  EXPECT_EQ(frame.data.size(), original_data_size)
      << "data size must not change after gain application";
}

// =============================================================================
// INV-LOUDNESS-NORMALIZED-001 Rule 2: pts_us unchanged
// =============================================================================

TEST(LoudnessGainContract, FrameTiming_Unchanged) {
  auto frame = MakeFrame(8000, 512);
  int64_t original_pts = frame.pts_us;
  int original_rate = frame.sample_rate;
  int original_channels = frame.channels;

  blockplan::ApplyGainS16(frame, blockplan::GainDbToLinear(4.5f));

  EXPECT_EQ(frame.pts_us, original_pts)
      << "pts_us must not change after gain application";
  EXPECT_EQ(frame.sample_rate, original_rate)
      << "sample_rate must not change after gain application";
  EXPECT_EQ(frame.channels, original_channels)
      << "channels must not change after gain application";
}
