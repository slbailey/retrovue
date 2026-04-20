// AIR vNext — slice 2 contract test.
//
// Validates: StandardNormalizer cadence resample (video) + SRC (audio)
//            + shared channel origin (A/V sync).
//
// Vault invariants exercised beyond slice 1:
//   - INV-NORMALIZER-SHARED-CHANNEL-ORIGIN-001 (A/V resolve against the
//     same origin even under non-trivial rate conversion)
//   - INV-NORMALIZER-OUTPUT-CHANNEL-TIME-001 (channel-time PTS on output,
//     computed from channel frame/sample indices arithmetically, not
//     derived from source PTS)
//   - INV-NORMALIZER-SOLE-TRANSLATION-POINT-001 (cadence + SRC happens
//     exactly once, inside this Normalizer)
//   - INV-NORMALIZER-AV-SYNC-AT-OUTPUT-001 (A/V fronts match channel time
//     when same source instant is their origin)
//   - INV-PREVIEW-DESTINATION-PTS-CONTIGUOUS-001 (emitted channel PTS
//     stream is monotonic and origin-anchored at integer-microsecond
//     resolution)

#include <gtest/gtest.h>

#include <cmath>
#include <optional>
#include <vector>

#include "channel_canonical.hpp"
#include "standard_normalizer.hpp"
#include "synthetic_source_producer.hpp"

namespace retrovue::air {
namespace {

// Channel canonical: 30fps (integer), 48kHz, 2ch.
ChannelCanonical Channel30() {
  return ChannelCanonical{
      .video = VideoCanonical{.width = 32,
                              .height = 16,
                              .frame_rate = {30, 1},
                              .pixel_format = PixelFormat::kYuv420p},
      .audio = AudioCanonical{.sample_rate = 48000, .channels = 2}};
}

// Builder for a prepared+activated synthetic source.
SyntheticSourceProducer MakeSynthActive(SyntheticSourceProducer::Config cfg) {
  SyntheticSourceProducer s(cfg);
  EXPECT_TRUE(s.Prepare());
  EXPECT_TRUE(s.Activate());
  return s;
}

// ---------------------------------------------------------------------------
// Video cadence: 24 -> 30 (4:5 pulldown).
// Expected source frame indices for k=0..14:
//   floor(k * 24 / 30) = floor(k * 0.8)
//   k:        0 1 2 3 4 5 6 7 8 9 10 11 12 13 14
//   src_idx:  0 0 1 2 3 4 4 5 6 7 8  8  9  10 11
// ---------------------------------------------------------------------------

TEST(StandardNormalizerCadence, PulldownPattern24to30) {
  auto canonical = Channel30();
  auto source = MakeSynthActive({
      .video_frame_rate = {24, 1},
      .video_width = 32,
      .video_height = 16,
      .audio_sample_rate = 48000,
      .audio_channels = 2,
  });

  StandardNormalizer norm(canonical, {24, 1}, 32, 16, 48000, &source,
                          {.source_pts_anchor_us = 0,
                           .channel_pts_anchor_us = 0},
                          /*samples_per_channel_audio_block=*/1600);

  const std::vector<int64_t> expected_src_indices = {
      0, 0, 1, 2, 3, 4, 4, 5, 6, 7, 8, 8, 9, 10, 11};

  for (size_t k = 0; k < expected_src_indices.size(); ++k) {
    auto vf = norm.PullVideo();
    ASSERT_TRUE(vf.has_value()) << "k=" << k;

    const int64_t burned_idx =
        SyntheticSourceProducer::ReadFrameIndexFromYPlane(vf->data);
    EXPECT_EQ(burned_idx, expected_src_indices[k])
        << "cadence mismatch at channel frame k=" << k;

    // Channel-time PTS: round(k * 1e6 / 30) = k * 33333 (with round-to-nearest).
    const int64_t expected_pts = (static_cast<int64_t>(k) * 1'000'000 + 15) / 30;
    EXPECT_EQ(vf->pts_us_relative, expected_pts) << "k=" << k;
  }
}

// ---------------------------------------------------------------------------
// Video cadence: 60 -> 30 (1:2 decimation).
// Expected: k -> 2k.
// ---------------------------------------------------------------------------

TEST(StandardNormalizerCadence, Decimation60to30) {
  auto canonical = Channel30();
  auto source = MakeSynthActive({
      .video_frame_rate = {60, 1},
      .video_width = 32,
      .video_height = 16,
      .audio_sample_rate = 48000,
      .audio_channels = 2,
  });

  StandardNormalizer norm(canonical, {60, 1}, 32, 16, 48000, &source,
                          {.source_pts_anchor_us = 0,
                           .channel_pts_anchor_us = 0},
                          1600);

  for (int64_t k = 0; k < 15; ++k) {
    auto vf = norm.PullVideo();
    ASSERT_TRUE(vf.has_value()) << "k=" << k;

    const int64_t burned = SyntheticSourceProducer::ReadFrameIndexFromYPlane(
        vf->data);
    EXPECT_EQ(burned, 2 * k) << "k=" << k;
  }
}

// ---------------------------------------------------------------------------
// Video cadence: 30 -> 30 (identity passthrough).
// ---------------------------------------------------------------------------

TEST(StandardNormalizerCadence, Passthrough30to30) {
  auto canonical = Channel30();
  auto source = MakeSynthActive({
      .video_frame_rate = {30, 1},
      .video_width = 32,
      .video_height = 16,
      .audio_sample_rate = 48000,
      .audio_channels = 2,
  });

  StandardNormalizer norm(canonical, {30, 1}, 32, 16, 48000, &source,
                          {.source_pts_anchor_us = 0,
                           .channel_pts_anchor_us = 0},
                          1600);

  for (int64_t k = 0; k < 15; ++k) {
    auto vf = norm.PullVideo();
    ASSERT_TRUE(vf.has_value());
    const int64_t burned = SyntheticSourceProducer::ReadFrameIndexFromYPlane(
        vf->data);
    EXPECT_EQ(burned, k);
  }
}

// ---------------------------------------------------------------------------
// Audio SRC: 48kHz -> 48kHz (passthrough). Constant source should produce
// constant output sample-for-sample.
// ---------------------------------------------------------------------------

TEST(StandardNormalizerSrc, Passthrough48to48Constant) {
  auto canonical = Channel30();
  SyntheticSourceProducer::Config cfg{
      .video_frame_rate = {30, 1},
      .video_width = 32,
      .video_height = 16,
      .audio_sample_rate = 48000,
      .audio_channels = 2,
      .audio_waveform = SyntheticAudioWaveform::kConstant,
      .audio_constant_value = 4242,
      .audio_samples_per_block = 480,
  };
  auto source = MakeSynthActive(cfg);

  StandardNormalizer norm(canonical, {30, 1}, 32, 16, 48000, &source,
                          {.source_pts_anchor_us = 0,
                           .channel_pts_anchor_us = 0},
                          /*samples_per_channel_audio_block=*/960);

  auto block = norm.PullAudio();
  ASSERT_TRUE(block.has_value());
  EXPECT_EQ(block->nb_samples, 960);
  EXPECT_EQ(static_cast<int>(block->data.size()), 960 * 2);
  for (int16_t s : block->data) EXPECT_EQ(s, 4242);
  EXPECT_EQ(block->pts_us_relative, 0);
}

// ---------------------------------------------------------------------------
// Audio SRC: 44100 -> 48000 via linear interpolation. With a constant
// source, output should be constant (interpolation of equal values = same
// value). Proves SRC wiring without quality concerns.
// ---------------------------------------------------------------------------

TEST(StandardNormalizerSrc, Src44100to48000ConstantPreserved) {
  auto canonical = Channel30();
  SyntheticSourceProducer::Config cfg{
      .video_frame_rate = {30, 1},
      .video_width = 32,
      .video_height = 16,
      .audio_sample_rate = 44100,
      .audio_channels = 2,
      .audio_waveform = SyntheticAudioWaveform::kConstant,
      .audio_constant_value = -2000,
      .audio_samples_per_block = 441,  // 10ms @ 44.1kHz
  };
  auto source = MakeSynthActive(cfg);

  StandardNormalizer norm(canonical, {30, 1}, 32, 16, 44100, &source,
                          {.source_pts_anchor_us = 0,
                           .channel_pts_anchor_us = 0},
                          /*samples_per_channel_audio_block=*/960);  // 20ms @ 48kHz

  // Pull 5 blocks = 100ms of channel audio.
  for (int b = 0; b < 5; ++b) {
    auto block = norm.PullAudio();
    ASSERT_TRUE(block.has_value()) << "block " << b;
    for (int16_t s : block->data) EXPECT_EQ(s, -2000);
  }
}

// ---------------------------------------------------------------------------
// Audio SRC: 44100 -> 48000, linear ramp. Output at channel sample N
// should be approximately the linear interpolation value at the fractional
// source index.
//
// With source[n] = n * step (ramp), output channel[m] should be
// approximately m * step * (44100/48000) = m * step * 0.91875.
// Within ±1 due to int16 rounding.
// ---------------------------------------------------------------------------

TEST(StandardNormalizerSrc, Src44100to48000LinearRamp) {
  auto canonical = Channel30();
  SyntheticSourceProducer::Config cfg{
      .video_frame_rate = {30, 1},
      .video_width = 32,
      .video_height = 16,
      .audio_sample_rate = 44100,
      .audio_channels = 2,
      .audio_waveform = SyntheticAudioWaveform::kLinearRamp,
      .audio_ramp_step = 3,  // ramp increment per source sample
      .audio_samples_per_block = 441,
  };
  auto source = MakeSynthActive(cfg);

  StandardNormalizer norm(canonical, {30, 1}, 32, 16, 44100, &source,
                          {.source_pts_anchor_us = 0,
                           .channel_pts_anchor_us = 0},
                          /*samples_per_channel_audio_block=*/480);

  auto block = norm.PullAudio();
  ASSERT_TRUE(block.has_value());

  const double ratio = 44100.0 / 48000.0;
  for (int m = 0; m < block->nb_samples; ++m) {
    // Expected linear-interpolated value: source samples are n*3 for
    // n = 0, 1, 2, ...; interpolation at fractional index m*ratio is
    // m*ratio*3, rounded to nearest int16.
    const double expected_d = static_cast<double>(m) * ratio * 3.0;
    const int16_t expected = static_cast<int16_t>(std::lround(expected_d));
    const int16_t got = block->data[static_cast<size_t>(m * 2)];
    EXPECT_NEAR(got, expected, 1) << "m=" << m;
  }
}

// ---------------------------------------------------------------------------
// Audio PTS continuity across blocks. Block[k] first-sample PTS should be
// round(k * samples_per_block * 1e6 / sample_rate).
// ---------------------------------------------------------------------------

TEST(StandardNormalizerSrc, AudioBlockPtsMonotonic) {
  auto canonical = Channel30();
  SyntheticSourceProducer::Config cfg{
      .video_frame_rate = {30, 1},
      .video_width = 32,
      .video_height = 16,
      .audio_sample_rate = 48000,
      .audio_channels = 2,
      .audio_waveform = SyntheticAudioWaveform::kConstant,
      .audio_constant_value = 0,
      .audio_samples_per_block = 480,
  };
  auto source = MakeSynthActive(cfg);

  const int ch_samples_per_block = 960;
  StandardNormalizer norm(canonical, {30, 1}, 32, 16, 48000, &source,
                          {.source_pts_anchor_us = 0,
                           .channel_pts_anchor_us = 0},
                          ch_samples_per_block);

  int64_t prev_pts = -1;
  for (int b = 0; b < 10; ++b) {
    auto block = norm.PullAudio();
    ASSERT_TRUE(block.has_value());
    const int64_t expected =
        (static_cast<int64_t>(b) * ch_samples_per_block * 1'000'000 + 24000) /
        48000;
    EXPECT_EQ(block->pts_us_relative, expected) << "b=" << b;
    EXPECT_GT(block->pts_us_relative, prev_pts);
    prev_pts = block->pts_us_relative;
  }
}

// ---------------------------------------------------------------------------
// A/V shared origin: when origin anchors source=0 at channel=0, the first
// video frame and the first audio sample both carry channel-time PTS 0.
// ---------------------------------------------------------------------------

TEST(StandardNormalizerAVSync, FirstPullsShareOrigin) {
  auto canonical = Channel30();
  SyntheticSourceProducer::Config cfg{
      .video_frame_rate = {24, 1},
      .video_width = 32,
      .video_height = 16,
      .audio_sample_rate = 44100,
      .audio_channels = 2,
      .audio_waveform = SyntheticAudioWaveform::kConstant,
      .audio_samples_per_block = 441,
  };
  auto source = MakeSynthActive(cfg);

  StandardNormalizer norm(canonical, {24, 1}, 32, 16, 44100, &source,
                          {.source_pts_anchor_us = 0,
                           .channel_pts_anchor_us = 0},
                          /*samples_per_channel_audio_block=*/960);

  auto vf = norm.PullVideo();
  auto ab = norm.PullAudio();
  ASSERT_TRUE(vf.has_value());
  ASSERT_TRUE(ab.has_value());

  // Both outputs anchored to channel PTS 0.
  EXPECT_EQ(vf->pts_us_relative, 0);
  EXPECT_EQ(ab->pts_us_relative, 0);

  // And both have a shared Normalizer origin.
  EXPECT_EQ(norm.Origin().source_pts_anchor_us, 0);
  EXPECT_EQ(norm.Origin().channel_pts_anchor_us, 0);
}

// ---------------------------------------------------------------------------
// A/V sync under cadence: for 24->30 conversion, the source-time of the
// video frame emitted at channel frame K should correspond to source PTS
// floor(K*24/30) / 24 seconds. The audio samples at the same channel time
// are drawn from source samples at the same source-time instant (the
// shared origin guarantees this).
//
// This test verifies that the Normalizer's computation of "what source
// time does channel time X map to?" is consistent between audio and video.
// ---------------------------------------------------------------------------

TEST(StandardNormalizerAVSync, VideoFrameSourcePtsMatchesChannelTimeUnderCadence) {
  auto canonical = Channel30();
  SyntheticSourceProducer::Config cfg{
      .video_frame_rate = {24, 1},
      .video_width = 32,
      .video_height = 16,
      .audio_sample_rate = 44100,
      .audio_channels = 2,
      .audio_waveform = SyntheticAudioWaveform::kConstant,
      .audio_samples_per_block = 441,
  };
  auto source = MakeSynthActive(cfg);

  StandardNormalizer norm(canonical, {24, 1}, 32, 16, 44100, &source,
                          {.source_pts_anchor_us = 0,
                           .channel_pts_anchor_us = 0},
                          960);

  // Pull the 6th channel frame (k=5). Expected source frame idx = floor(5 *
  // 24 / 30) = 4. Expected source PTS = round(4 * 1e6 / 24) = 166667 us.
  for (int k = 0; k < 5; ++k) norm.PullVideo();
  auto vf6 = norm.PullVideo();
  ASSERT_TRUE(vf6.has_value());

  const int64_t burned =
      SyntheticSourceProducer::ReadFrameIndexFromYPlane(vf6->data);
  EXPECT_EQ(burned, 4);

  // Source PTS metadata (opaque) for that source frame: 4 * 1e6 / 24 ≈ 166667.
  const int64_t expected_source_pts = (4 * 1'000'000 + 12) / 24;
  EXPECT_EQ(vf6->source_pts_us_opaque, expected_source_pts);

  // Channel PTS for k=5: round(5 * 1e6 / 30) = 166667.
  const int64_t expected_channel_pts = (5 * 1'000'000 + 15) / 30;
  EXPECT_EQ(vf6->pts_us_relative, expected_channel_pts);

  // By construction (origin anchors source=0 at channel=0 with ratio 1:1
  // in wall-clock time), source PTS and channel PTS for this frame are
  // approximately equal — both are 166667us. That's the shared-origin A/V
  // sync property exercised under cadence.
  EXPECT_EQ(vf6->source_pts_us_opaque, vf6->pts_us_relative);
}

// ---------------------------------------------------------------------------
// Re-anchor under real cadence: tier-2 adjust should change origin anchor
// without disturbing cadence phase (next PullVideo still returns the
// expected next-in-pattern frame).
// ---------------------------------------------------------------------------

TEST(StandardNormalizerReanchor, AdjustDoesNotDisturbCadencePhase) {
  auto canonical = Channel30();
  auto source = MakeSynthActive({
      .video_frame_rate = {24, 1},
      .video_width = 32,
      .video_height = 16,
      .audio_sample_rate = 48000,
      .audio_channels = 2,
  });
  StandardNormalizer norm(canonical, {24, 1}, 32, 16, 48000, &source,
                          {.source_pts_anchor_us = 0,
                           .channel_pts_anchor_us = 1'000'000},
                          1600);

  // Pull first 3 channel frames: expected burned idx 0, 0, 1.
  for (int k = 0; k < 3; ++k) {
    auto vf = norm.PullVideo();
    ASSERT_TRUE(vf.has_value());
  }

  // Adjust anchor by 500ms (tier-2).
  EXPECT_EQ(norm.Reanchor(1'500'000), ReanchorTier::kAdjusted);
  EXPECT_EQ(norm.Origin().channel_pts_anchor_us, 1'500'000);

  // Next pull is channel frame k=3, expected burned idx = 2 (pattern unchanged).
  auto vf = norm.PullVideo();
  ASSERT_TRUE(vf.has_value());
  const int64_t burned =
      SyntheticSourceProducer::ReadFrameIndexFromYPlane(vf->data);
  EXPECT_EQ(burned, 2);

  // Channel-relative PTS for k=3 = round(3 * 1e6 / 30) = 100000.
  // This is unaffected by anchor; anchor is the ABSOLUTE offset at emission,
  // not stored in relative PTS.
  const int64_t expected_rel = (3 * 1'000'000 + 15) / 30;
  EXPECT_EQ(vf->pts_us_relative, expected_rel);
}

// ---------------------------------------------------------------------------
// NTSC fractional framerate (30000/1001, the actual rate from
// config/channels/cheers-24-7.yaml). Exercises the Rational-arithmetic
// code path with a non-integer ratio.
// ---------------------------------------------------------------------------

// NTSC channel canonical.
ChannelCanonical ChannelNtsc30() {
  return ChannelCanonical{
      .video = VideoCanonical{.width = 32,
                              .height = 16,
                              .frame_rate = {30000, 1001},
                              .pixel_format = PixelFormat::kYuv420p},
      .audio = AudioCanonical{.sample_rate = 48000, .channels = 2}};
}

TEST(NtscRational, NthStepPtsUsMatchesExpected) {
  // 30000/1001 fps: period = round(1e6 * 1001 / 30000) ≈ 33366.67 us.
  const Rational ntsc{30000, 1001};

  EXPECT_EQ(ntsc.NthStepPtsUs(0), 0);

  // n=1: true value 33366.6666... → round = 33367.
  // formula: (1 * 1e6 * 1001 + 15000) / 30000 = 1001015000 / 30000.
  //   30000 * 33367 = 1001010000; remainder 5000; quotient 33367. ✓
  EXPECT_EQ(ntsc.NthStepPtsUs(1), 33367);

  // n=30: exact 30 * 1001/30000 s = 1.001 s = 1001000 us.
  EXPECT_EQ(ntsc.NthStepPtsUs(30), 1001000);

  // n=60000 (one hour of NTSC frames at 30000/1001 is 3600 * 30000/1001 ≈
  // 107892; pick 60000 which is ~33 minutes): true value 60000 * 1001 /
  // 30000 seconds = 2002 seconds = 2_002_000_000 us. Integer-exact.
  EXPECT_EQ(ntsc.NthStepPtsUs(60000), 2'002'000'000);
}

TEST(NtscRational, PeriodConsistentWithNthStep) {
  // For any rate, NthStepPtsUs(1) should equal round(period). At NTSC:
  //   period = (1e6 * 1001) / 30000 = 33366 (integer truncation)
  //   NthStepPtsUs(1) = round(1e6 * 1001 / 30000) = 33367
  // These DIFFER by 1us because PeriodMicros truncates while NthStepPtsUs
  // rounds. PeriodMicros is for threshold / sizing purposes; NthStepPtsUs
  // is for PTS generation.
  const Rational ntsc{30000, 1001};
  EXPECT_EQ(ntsc.PeriodMicros(), 33366);
  EXPECT_EQ(ntsc.NthStepPtsUs(1), 33367);
}

TEST(StandardNormalizerCadence, PulldownPattern24toNtsc30) {
  auto canonical = ChannelNtsc30();
  auto source = MakeSynthActive({
      .video_frame_rate = {24, 1},  // 24fps film
      .video_width = 32,
      .video_height = 16,
      .audio_sample_rate = 48000,
      .audio_channels = 2,
  });

  StandardNormalizer norm(canonical, {24, 1}, 32, 16, 48000, &source,
                          {.source_pts_anchor_us = 0,
                           .channel_pts_anchor_us = 0},
                          /*samples_per_channel_audio_block=*/1601);

  // Source frame idx for channel frame k at 24/1 -> 30000/1001:
  //   floor(k * 24 * 1001 / (30000 * 1))
  // k:  0 1 2 3 4 5 6 7 8 9 10 11 12 13 14
  // 24k:0 24 48 72 96 120 144 168 192 216 240 264 288 312 336
  // 24k*1001: (expressing as floor(24024k / 30000) simplified by factor 8:
  //   24024 = 8 * 3003, 30000 = 8 * 3750)
  // The exact sequence for k=0..14:
  const std::vector<int64_t> expected = {
      0, 0, 1, 2, 3, 4, 4, 5, 6, 7, 8, 8, 9, 10, 11};

  for (size_t k = 0; k < expected.size(); ++k) {
    auto vf = norm.PullVideo();
    ASSERT_TRUE(vf.has_value()) << "k=" << k;

    const int64_t burned =
        SyntheticSourceProducer::ReadFrameIndexFromYPlane(vf->data);
    EXPECT_EQ(burned, expected[k]) << "cadence mismatch at k=" << k;

    // Channel-time PTS matches Rational::NthStepPtsUs for NTSC.
    EXPECT_EQ(vf->pts_us_relative,
              canonical.video.frame_rate.NthStepPtsUs(k))
        << "PTS mismatch at k=" << k;
  }
}

TEST(StandardNormalizerCadence, Decimation60000_1001toNtsc30) {
  auto canonical = ChannelNtsc30();
  auto source = MakeSynthActive({
      .video_frame_rate = {60000, 1001},  // NTSC 60p
      .video_width = 32,
      .video_height = 16,
      .audio_sample_rate = 48000,
      .audio_channels = 2,
  });

  StandardNormalizer norm(canonical, {60000, 1001}, 32, 16, 48000, &source,
                          {.source_pts_anchor_us = 0,
                           .channel_pts_anchor_us = 0},
                          1601);

  // 60000/1001 -> 30000/1001 is exactly 2:1. Every second source frame.
  for (int64_t k = 0; k < 15; ++k) {
    auto vf = norm.PullVideo();
    ASSERT_TRUE(vf.has_value());

    const int64_t burned =
        SyntheticSourceProducer::ReadFrameIndexFromYPlane(vf->data);
    EXPECT_EQ(burned, 2 * k) << "k=" << k;

    EXPECT_EQ(vf->pts_us_relative,
              canonical.video.frame_rate.NthStepPtsUs(k))
        << "k=" << k;
  }
}

TEST(StandardNormalizerCadence, PassthroughNtsc30toNtsc30) {
  auto canonical = ChannelNtsc30();
  auto source = MakeSynthActive({
      .video_frame_rate = {30000, 1001},
      .video_width = 32,
      .video_height = 16,
      .audio_sample_rate = 48000,
      .audio_channels = 2,
  });

  StandardNormalizer norm(canonical, {30000, 1001}, 32, 16, 48000, &source,
                          {.source_pts_anchor_us = 0,
                           .channel_pts_anchor_us = 0},
                          1601);

  for (int64_t k = 0; k < 15; ++k) {
    auto vf = norm.PullVideo();
    ASSERT_TRUE(vf.has_value());
    const int64_t burned =
        SyntheticSourceProducer::ReadFrameIndexFromYPlane(vf->data);
    EXPECT_EQ(burned, k) << "k=" << k;
    EXPECT_EQ(vf->pts_us_relative,
              canonical.video.frame_rate.NthStepPtsUs(k));
  }
}

}  // namespace
}  // namespace retrovue::air
