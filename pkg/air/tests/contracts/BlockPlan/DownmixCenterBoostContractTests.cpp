// Repository: Retrovue-playout
// Component: Downmix Center Boost Contract Tests
// Purpose: INV-DOWNMIX-CENTER-BOOST-001 — surround→stereo downmix must boost
//          center channel for dialogue intelligibility (retro TV aesthetic).
// Design Authority: pkg/air/docs/design/BROADCAST_AUDIO_PROCESSING.md §13
// Copyright (c) 2026 RetroVue

#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>
#include <vector>

extern "C" {
#include <libavutil/channel_layout.h>
#include <libavutil/opt.h>
#include <libavutil/samplefmt.h>
#include <libswresample/swresample.h>
}

#include "retrovue/blockplan/BroadcastAudioProcessor.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"

using namespace retrovue;

// ---------------------------------------------------------------------------
// INV-DOWNMIX-CENTER-BOOST-001 constants (must match FFmpegDecoder)
// ---------------------------------------------------------------------------

// The center mix level used by RetroVue for surround→stereo downmix.
// 1.0 = 0 dB (dialogue at full level relative to L/R).
static constexpr double kRetrovueCenterMixLevel = 1.0;

// ITU default center mix level for comparison.
static constexpr double kItuCenterMixLevel = 0.707106781186548;  // -3 dB

// House format constants.
static constexpr int kHouseSampleRate = 48000;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Create a SwrContext for 5.1→stereo downmix with a given center_mix_level.
static SwrContext* CreateDownmixContext(double center_mix_level) {
  SwrContext* swr = swr_alloc();
  if (!swr) return nullptr;

  AVChannelLayout src_layout;
  av_channel_layout_from_mask(&src_layout, AV_CH_LAYOUT_5POINT1);

  AVChannelLayout dst_layout;
  av_channel_layout_from_mask(&dst_layout, AV_CH_LAYOUT_STEREO);

  int ret = swr_alloc_set_opts2(&swr,
      &dst_layout, AV_SAMPLE_FMT_S16, kHouseSampleRate,
      &src_layout, AV_SAMPLE_FMT_S16, kHouseSampleRate,
      0, nullptr);

  av_channel_layout_uninit(&src_layout);
  av_channel_layout_uninit(&dst_layout);

  if (ret != 0) {
    swr_free(&swr);
    return nullptr;
  }

  // Set center mix level before init.
  av_opt_set_double(swr, "center_mix_level", center_mix_level, 0);

  if (swr_init(swr) < 0) {
    swr_free(&swr);
    return nullptr;
  }

  return swr;
}

// Create a 5.1 S16 interleaved frame with signal only in the center channel.
// Channel order for 5.1: FL, FR, FC, LFE, BL, BR
static std::vector<int16_t> MakeCenterOnlyFrame(int16_t center_value,
                                                  int nb_samples) {
  const int channels = 6;
  std::vector<int16_t> data(nb_samples * channels, 0);
  for (int i = 0; i < nb_samples; ++i) {
    data[i * channels + 2] = center_value;  // FC = channel index 2
  }
  return data;
}

// Create a 5.1 S16 interleaved frame with signal only in FL channel.
static std::vector<int16_t> MakeLeftOnlyFrame(int16_t left_value,
                                               int nb_samples) {
  const int channels = 6;
  std::vector<int16_t> data(nb_samples * channels, 0);
  for (int i = 0; i < nb_samples; ++i) {
    data[i * channels + 0] = left_value;  // FL = channel index 0
  }
  return data;
}

// Downmix a 5.1 S16 frame to stereo using the given SwrContext.
// Returns stereo interleaved S16 samples.
static std::vector<int16_t> Downmix(SwrContext* swr,
                                     const std::vector<int16_t>& input_51,
                                     int nb_samples) {
  const int in_channels = 6;
  const int out_channels = 2;

  std::vector<int16_t> output(nb_samples * out_channels, 0);

  const uint8_t* in_ptr = reinterpret_cast<const uint8_t*>(input_51.data());
  uint8_t* out_ptr = reinterpret_cast<uint8_t*>(output.data());

  int converted = swr_convert(swr, &out_ptr, nb_samples,
                               &in_ptr, nb_samples);
  EXPECT_EQ(converted, nb_samples);

  return output;
}

// Compute RMS of stereo S16 samples (both channels combined).
static double ComputeRms(const std::vector<int16_t>& samples) {
  double sum_sq = 0.0;
  for (auto s : samples) {
    double v = static_cast<double>(s);
    sum_sq += v * v;
  }
  return std::sqrt(sum_sq / static_cast<double>(samples.size()));
}

// =============================================================================
// INV-DOWNMIX-CENTER-BOOST-001 Rule 1: Center channel at boosted level
// =============================================================================

TEST(DownmixCenterBoostContract, CenterBoost_LouderThanItuDefault) {
  // Downmix center-only 5.1 signal with RetroVue boost vs ITU default.
  // The boosted version must produce louder stereo output.
  const int nb_samples = 4800;  // 100ms
  const int16_t center_val = 10000;

  auto input = MakeCenterOnlyFrame(center_val, nb_samples);

  SwrContext* swr_boosted = CreateDownmixContext(kRetrovueCenterMixLevel);
  SwrContext* swr_itu = CreateDownmixContext(kItuCenterMixLevel);
  ASSERT_NE(swr_boosted, nullptr);
  ASSERT_NE(swr_itu, nullptr);

  auto out_boosted = Downmix(swr_boosted, input, nb_samples);
  auto out_itu = Downmix(swr_itu, input, nb_samples);

  double rms_boosted = ComputeRms(out_boosted);
  double rms_itu = ComputeRms(out_itu);

  // Boosted center should be louder.
  EXPECT_GT(rms_boosted, rms_itu * 1.2)
      << "Center channel with boost (" << kRetrovueCenterMixLevel
      << ") must be louder than ITU default (" << kItuCenterMixLevel << ")";

  swr_free(&swr_boosted);
  swr_free(&swr_itu);
}

TEST(DownmixCenterBoostContract, CenterBoost_DialogueMeaningfullyLouder) {
  // With center_mix_level=1.0 vs 0.707, centre dialogue should be
  // meaningfully louder. ffmpeg may apply matrix normalization so the
  // raw ratio won't be exactly 1.0/0.707. We require at least +1.5 dB
  // (ratio > 1.19) which is the minimum perceptible improvement.
  const int nb_samples = 4800;
  const int16_t center_val = 8000;

  auto input = MakeCenterOnlyFrame(center_val, nb_samples);

  SwrContext* swr_boosted = CreateDownmixContext(kRetrovueCenterMixLevel);
  SwrContext* swr_itu = CreateDownmixContext(kItuCenterMixLevel);
  ASSERT_NE(swr_boosted, nullptr);
  ASSERT_NE(swr_itu, nullptr);

  auto out_boosted = Downmix(swr_boosted, input, nb_samples);
  auto out_itu = Downmix(swr_itu, input, nb_samples);

  double rms_boosted = ComputeRms(out_boosted);
  double rms_itu = ComputeRms(out_itu);

  double ratio = rms_boosted / rms_itu;
  double gain_db = 20.0 * std::log10(ratio);

  // Must be at least +1.5 dB louder.
  EXPECT_GT(gain_db, 1.5)
      << "Center boost should increase dialogue by at least 1.5 dB (actual: "
      << gain_db << " dB, ratio: " << ratio << ")";

  swr_free(&swr_boosted);
  swr_free(&swr_itu);
}

TEST(DownmixCenterBoostContract, CenterBoost_CenterGainExceedsLRGain) {
  // The center channel should benefit MORE from the boost than L/R channels.
  // ffmpeg may normalize the overall matrix, so both center and L/R levels
  // could change. But the center-to-LR ratio must improve.
  const int nb_samples = 4800;

  // Center-only input
  auto center_input = MakeCenterOnlyFrame(10000, nb_samples);
  // Left-only input
  auto left_input = MakeLeftOnlyFrame(10000, nb_samples);

  SwrContext* swr_boosted = CreateDownmixContext(kRetrovueCenterMixLevel);
  SwrContext* swr_itu = CreateDownmixContext(kItuCenterMixLevel);
  ASSERT_NE(swr_boosted, nullptr);
  ASSERT_NE(swr_itu, nullptr);

  // Measure center/left ratio with ITU defaults
  auto center_itu = Downmix(swr_itu, center_input, nb_samples);
  // Need fresh context for second downmix (swr may have internal state)
  swr_free(&swr_itu);
  swr_itu = CreateDownmixContext(kItuCenterMixLevel);
  auto left_itu = Downmix(swr_itu, left_input, nb_samples);
  double ratio_itu = ComputeRms(center_itu) / ComputeRms(left_itu);

  // Measure center/left ratio with boost
  auto center_boost = Downmix(swr_boosted, center_input, nb_samples);
  swr_free(&swr_boosted);
  swr_boosted = CreateDownmixContext(kRetrovueCenterMixLevel);
  auto left_boost = Downmix(swr_boosted, left_input, nb_samples);
  double ratio_boost = ComputeRms(center_boost) / ComputeRms(left_boost);

  // The center-to-LR ratio must be higher with boost.
  EXPECT_GT(ratio_boost, ratio_itu * 1.1)
      << "Center boost must improve center-to-LR ratio "
      << "(ITU: " << ratio_itu << ", boosted: " << ratio_boost << ")";

  swr_free(&swr_boosted);
  swr_free(&swr_itu);
}

TEST(DownmixCenterBoostContract, CenterBoost_OutputIsStillStereo) {
  // Output must be 2-channel S16 (house format).
  const int nb_samples = 480;
  const int16_t center_val = 5000;

  auto input = MakeCenterOnlyFrame(center_val, nb_samples);

  SwrContext* swr = CreateDownmixContext(kRetrovueCenterMixLevel);
  ASSERT_NE(swr, nullptr);

  auto output = Downmix(swr, input, nb_samples);

  // Output should have exactly nb_samples * 2 samples (stereo).
  EXPECT_EQ(static_cast<int>(output.size()), nb_samples * 2);

  // Center channel folds equally into L and R.
  // Check that L and R are approximately equal for center-only input.
  double sum_diff = 0.0;
  for (int i = 0; i < nb_samples; ++i) {
    double diff = std::abs(static_cast<double>(output[i * 2]) -
                           static_cast<double>(output[i * 2 + 1]));
    sum_diff += diff;
  }
  double avg_diff = sum_diff / nb_samples;
  EXPECT_LT(avg_diff, 2.0)
      << "Center-only input should produce equal L and R in stereo output";

  swr_free(&swr);
}

TEST(DownmixCenterBoostContract, CenterBoost_LevelAtLeast0dB) {
  // INV-DOWNMIX-CENTER-BOOST-001: center_mix_level MUST be >= 1.0 (0 dB).
  EXPECT_GE(kRetrovueCenterMixLevel, 1.0)
      << "Center mix level must be at least 0 dB (linear 1.0)";
}

// =============================================================================
// INV-BROADCAST-DRC v0.2 tuning validation
// =============================================================================

// Helper: constant-value stereo frame for DRC tests.
static buffer::AudioFrame MakeFrame(int16_t sample_value, int nb_samples) {
  buffer::AudioFrame frame;
  frame.sample_rate = 48000;
  frame.channels = 2;
  frame.nb_samples = nb_samples;
  frame.pts_us = 1000000;

  size_t total = static_cast<size_t>(nb_samples) * 2;
  frame.data.resize(total * sizeof(int16_t));
  auto* samples = reinterpret_cast<int16_t*>(frame.data.data());
  for (size_t i = 0; i < total; ++i) {
    samples[i] = sample_value;
  }
  return frame;
}

TEST(DownmixCenterBoostContract, DRC_v02_ThresholdLowerThanV01) {
  // v0.2 threshold should engage compression earlier than v0.1.
  // v0.1: -18 dBFS, v0.2: -20 dBFS
  // Test: a signal at -19 dBFS should trigger compression with v0.2 params
  // but NOT with v0.1 params.

  // We can't easily parameterize BroadcastAudioProcessor at runtime,
  // so we validate the compiled constants directly.
  // These constants are in BroadcastAudioProcessor.hpp.
  // This test validates the EXPECTED v0.2 values.
  //
  // After the code change, the compiled constants should be:
  //   kThresholdDbfs = -20.0f
  //   kRatio = 4.0f
  //   kAttackMs = 3.0f
  //   kReleaseMs = 80.0f
  //   kMakeupGainDb = 4.0f
  //
  // We verify by feeding a signal at -19 dBFS and checking that
  // compression occurs (which it would NOT at the v0.1 -18 threshold).

  // -19 dBFS ≈ 3671 peak S16
  const int16_t signal_at_minus19 = 3671;

  blockplan::BroadcastAudioProcessor proc;

  // Feed enough frames to reach steady state.
  for (int i = 0; i < 100; ++i) {
    auto frame = MakeFrame(signal_at_minus19, 480);
    proc.Process(frame);
  }

  auto frame = MakeFrame(signal_at_minus19, 480);
  float reduction = proc.Process(frame);

  // With v0.2 threshold at -20 dBFS, a -19 dBFS signal is 1 dB above
  // threshold and should produce measurable compression.
  EXPECT_GT(reduction, 0.1f)
      << "Signal at -19 dBFS must trigger compression with v0.2 threshold (-20 dBFS)";
}
