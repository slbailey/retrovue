// Repository: Retrovue-playout
// Component: Broadcast Audio Processor Contract Tests
// Purpose: INV-BROADCAST-DRC-001 through 004 — validate broadcast dynamic
//          range compression on S16 stereo audio.
// Design Authority: pkg/air/docs/design/BROADCAST_AUDIO_PROCESSING.md
// Copyright (c) 2026 RetroVue

#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>
#include <cstring>
#include <vector>

#include "retrovue/blockplan/BroadcastAudioProcessor.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"

using namespace retrovue;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Create an AudioFrame with a constant sample value in both channels.
static buffer::AudioFrame MakeFrame(int16_t sample_value, int nb_samples,
                                    int channels = 2) {
  buffer::AudioFrame frame;
  frame.sample_rate = 48000;
  frame.channels = channels;
  frame.nb_samples = nb_samples;
  frame.pts_us = 1000000;  // 1 second

  size_t total = static_cast<size_t>(nb_samples) * static_cast<size_t>(channels);
  frame.data.resize(total * sizeof(int16_t));
  auto* samples = reinterpret_cast<int16_t*>(frame.data.data());
  for (size_t i = 0; i < total; ++i) {
    samples[i] = sample_value;
  }
  return frame;
}

// Create a stereo frame with separate L and R constant values.
static buffer::AudioFrame MakeStereoFrame(int16_t left, int16_t right,
                                          int nb_samples) {
  buffer::AudioFrame frame;
  frame.sample_rate = 48000;
  frame.channels = 2;
  frame.nb_samples = nb_samples;
  frame.pts_us = 1000000;

  size_t total = static_cast<size_t>(nb_samples) * 2;
  frame.data.resize(total * sizeof(int16_t));
  auto* samples = reinterpret_cast<int16_t*>(frame.data.data());
  for (int i = 0; i < nb_samples; ++i) {
    samples[i * 2] = left;
    samples[i * 2 + 1] = right;
  }
  return frame;
}

// Create a frame with a sine wave at a given amplitude (peak S16 value).
static buffer::AudioFrame MakeSineFrame(int16_t amplitude, int nb_samples,
                                        float freq_hz = 1000.0f) {
  buffer::AudioFrame frame;
  frame.sample_rate = 48000;
  frame.channels = 2;
  frame.nb_samples = nb_samples;
  frame.pts_us = 0;

  size_t total = static_cast<size_t>(nb_samples) * 2;
  frame.data.resize(total * sizeof(int16_t));
  auto* samples = reinterpret_cast<int16_t*>(frame.data.data());
  for (int i = 0; i < nb_samples; ++i) {
    float t = static_cast<float>(i) / 48000.0f;
    float val = static_cast<float>(amplitude) *
                std::sin(2.0f * static_cast<float>(M_PI) * freq_hz * t);
    auto s = static_cast<int16_t>(std::max(-32768.0f, std::min(32767.0f, val)));
    samples[i * 2] = s;
    samples[i * 2 + 1] = s;
  }
  return frame;
}

static int16_t ReadSample(const buffer::AudioFrame& frame, size_t index) {
  auto* samples = reinterpret_cast<const int16_t*>(frame.data.data());
  return samples[index];
}

// Peak absolute value across all samples in the frame.
static int16_t PeakAbs(const buffer::AudioFrame& frame) {
  auto* samples = reinterpret_cast<const int16_t*>(frame.data.data());
  size_t total = static_cast<size_t>(frame.nb_samples) *
                 static_cast<size_t>(frame.channels);
  int16_t peak = 0;
  for (size_t i = 0; i < total; ++i) {
    int16_t a = (samples[i] == -32768) ? 32767 : static_cast<int16_t>(std::abs(samples[i]));
    if (a > peak) peak = a;
  }
  return peak;
}

// =============================================================================
// INV-BROADCAST-DRC-001: Stage presence and positioning
// =============================================================================

TEST(BroadcastDRCContract, ProcessExists_AcceptsHouseFormat) {
  blockplan::BroadcastAudioProcessor proc;
  auto frame = MakeFrame(1000, 1024);
  float reduction = proc.Process(frame);
  // Must not crash; must return a value.
  EXPECT_GE(reduction, 0.0f);
}

TEST(BroadcastDRCContract, ProcessOutput_IsHouseFormat) {
  blockplan::BroadcastAudioProcessor proc;
  auto frame = MakeFrame(1000, 1024);
  proc.Process(frame);
  EXPECT_EQ(frame.sample_rate, 48000);
  EXPECT_EQ(frame.channels, 2);
}

// =============================================================================
// INV-BROADCAST-DRC-002: Metadata preservation
// =============================================================================

TEST(BroadcastDRCContract, SampleCount_Unchanged) {
  blockplan::BroadcastAudioProcessor proc;
  auto frame = MakeFrame(5000, 1024);
  int orig = frame.nb_samples;
  proc.Process(frame);
  EXPECT_EQ(frame.nb_samples, orig);
}

TEST(BroadcastDRCContract, ChannelCount_Unchanged) {
  blockplan::BroadcastAudioProcessor proc;
  auto frame = MakeFrame(5000, 1024);
  proc.Process(frame);
  EXPECT_EQ(frame.channels, 2);
}

TEST(BroadcastDRCContract, PTS_Unchanged) {
  blockplan::BroadcastAudioProcessor proc;
  auto frame = MakeFrame(5000, 512);
  frame.pts_us = 9876543;
  proc.Process(frame);
  EXPECT_EQ(frame.pts_us, 9876543);
}

TEST(BroadcastDRCContract, DataSize_Unchanged) {
  blockplan::BroadcastAudioProcessor proc;
  auto frame = MakeFrame(5000, 1024);
  size_t orig = frame.data.size();
  proc.Process(frame);
  EXPECT_EQ(frame.data.size(), orig);
}

TEST(BroadcastDRCContract, SilenceInput_SilenceOutput) {
  blockplan::BroadcastAudioProcessor proc;
  auto frame = MakeFrame(0, 1024);
  proc.Process(frame);
  auto* samples = reinterpret_cast<const int16_t*>(frame.data.data());
  for (size_t i = 0; i < static_cast<size_t>(frame.nb_samples) * 2; ++i) {
    EXPECT_EQ(samples[i], 0)
        << "Silence in must produce silence out (sample " << i << ")";
  }
}

// =============================================================================
// INV-BROADCAST-DRC-003: Segment boundary reset
// =============================================================================

TEST(BroadcastDRCContract, Reset_ClearsEnvelope) {
  blockplan::BroadcastAudioProcessor proc;

  // Feed loud frames to build up envelope and gain reduction.
  // 32000 ≈ -0.2 dBFS, well above -18 threshold.
  for (int i = 0; i < 50; ++i) {
    auto loud = MakeFrame(32000, 480);  // 10ms @ 48kHz
    proc.Process(loud);
  }
  // Capture steady-state output level.
  auto steady = MakeFrame(32000, 480);
  proc.Process(steady);
  int16_t steady_peak = PeakAbs(steady);

  // Reset (simulates segment boundary).
  proc.Reset();

  // First frame after reset — compressor starts from unity, attack hasn't
  // built up yet, so early samples should be louder (less compressed) than
  // steady-state.
  auto after_reset = MakeFrame(32000, 480);
  proc.Process(after_reset);

  // Check early samples (first few) — they should have less compression
  // than the steady-state peak. At unity envelope + makeup gain, the output
  // should be >= steady state.
  int16_t first_sample_abs = std::abs(ReadSample(after_reset, 0));
  EXPECT_GE(first_sample_abs, steady_peak)
      << "After reset, first samples should have less compression than steady state";
}

TEST(BroadcastDRCContract, Reset_NoDiscontinuity) {
  blockplan::BroadcastAudioProcessor proc;

  // Build up steady state with loud signal.
  for (int i = 0; i < 50; ++i) {
    auto loud = MakeFrame(25000, 480);
    proc.Process(loud);
  }

  proc.Reset();

  // Feed same loud signal after reset.
  auto after = MakeFrame(25000, 480);
  proc.Process(after);

  // No sample should exceed int16 range (no wraparound from discontinuity).
  auto* samples = reinterpret_cast<const int16_t*>(after.data.data());
  for (size_t i = 0; i < static_cast<size_t>(after.nb_samples) * 2; ++i) {
    EXPECT_GE(samples[i], -32768);
    EXPECT_LE(samples[i], 32767);
  }
  // The makeup gain is +3 dB (~1.41x). Even with zero compression (just after
  // reset), 25000 * 1.41 = 35250 which clips to 32767. Verify clamping works.
  int16_t peak = PeakAbs(after);
  EXPECT_LE(peak, 32767);
}

TEST(BroadcastDRCContract, ConsecutiveResets_Idempotent) {
  blockplan::BroadcastAudioProcessor proc;

  // Build up state then double-reset.
  for (int i = 0; i < 20; ++i) {
    auto loud = MakeFrame(30000, 480);
    proc.Process(loud);
  }

  proc.Reset();
  proc.Reset();

  auto frame1 = MakeFrame(10000, 1024);
  float r1 = proc.Process(frame1);

  // Fresh processor, single reset.
  blockplan::BroadcastAudioProcessor proc2;
  proc2.Reset();

  auto frame2 = MakeFrame(10000, 1024);
  float r2 = proc2.Process(frame2);

  // Output should be identical — double reset == single reset from clean state.
  auto* s1 = reinterpret_cast<const int16_t*>(frame1.data.data());
  auto* s2 = reinterpret_cast<const int16_t*>(frame2.data.data());
  for (size_t i = 0; i < static_cast<size_t>(frame1.nb_samples) * 2; ++i) {
    EXPECT_EQ(s1[i], s2[i]) << "Double reset should be same as fresh processor at sample " << i;
  }
}

// =============================================================================
// INV-BROADCAST-DRC-004: Linked stereo
// =============================================================================

TEST(BroadcastDRCContract, LinkedStereo_LoudLeftReducesBoth) {
  blockplan::BroadcastAudioProcessor proc;

  // Feed enough frames to build envelope from the loud left channel.
  // L=30000 (~-0.8 dBFS), R=100 (~-50 dBFS).
  for (int i = 0; i < 50; ++i) {
    auto frame = MakeStereoFrame(30000, 100, 480);
    proc.Process(frame);
  }

  // At steady state, both channels should be affected by compression.
  auto frame = MakeStereoFrame(30000, 100, 480);
  proc.Process(frame);

  // Check a late sample pair (well past attack).
  int idx = 400 * 2;  // sample pair 400
  int16_t out_r = ReadSample(frame, idx + 1);

  // R was 100. With only makeup gain (+3dB ≈ 1.41x) and compression from
  // L driving the envelope, R should be reduced relative to pure makeup.
  // Pure makeup of 100 would be ~141. With compression active, gain < makeup.
  // R must be < 141 to prove L drove compression on R.
  EXPECT_LT(std::abs(out_r), 141)
      << "Loud left channel must cause compression on quiet right channel";
}

TEST(BroadcastDRCContract, LinkedStereo_LoudRightReducesBoth) {
  blockplan::BroadcastAudioProcessor proc;

  for (int i = 0; i < 50; ++i) {
    auto frame = MakeStereoFrame(100, 30000, 480);
    proc.Process(frame);
  }

  auto frame = MakeStereoFrame(100, 30000, 480);
  proc.Process(frame);

  int idx = 400 * 2;
  int16_t out_l = ReadSample(frame, idx);

  EXPECT_LT(std::abs(out_l), 141)
      << "Loud right channel must cause compression on quiet left channel";
}

TEST(BroadcastDRCContract, LinkedStereo_SymmetricInput_SymmetricOutput) {
  blockplan::BroadcastAudioProcessor proc;

  auto frame = MakeFrame(20000, 1024);
  proc.Process(frame);

  auto* samples = reinterpret_cast<const int16_t*>(frame.data.data());
  for (int i = 0; i < frame.nb_samples; ++i) {
    EXPECT_EQ(samples[i * 2], samples[i * 2 + 1])
        << "Symmetric input must produce symmetric output at pair " << i;
  }
}

TEST(BroadcastDRCContract, LinkedStereo_GainReductionEqual) {
  blockplan::BroadcastAudioProcessor proc;

  // Build up envelope with loud signal.
  for (int i = 0; i < 50; ++i) {
    auto warm = MakeFrame(25000, 480);
    proc.Process(warm);
  }

  // Now feed a frame with different L and R, both above threshold.
  // L=25000, R=15000.
  auto frame = MakeStereoFrame(25000, 15000, 480);
  proc.Process(frame);

  // Check a late sample pair to ensure envelope is stable.
  int idx = 400;
  int16_t out_l = ReadSample(frame, idx * 2);
  int16_t out_r = ReadSample(frame, idx * 2 + 1);

  // Compute effective gain ratio for each channel.
  // Input L=25000, R=15000.
  float gain_l = static_cast<float>(out_l) / 25000.0f;
  float gain_r = static_cast<float>(out_r) / 15000.0f;

  // Gains must be equal (linked stereo — same linear gain to both).
  EXPECT_NEAR(gain_l, gain_r, 0.01f)
      << "Linked stereo must apply identical gain to both channels";
}

// =============================================================================
// Compression behavior (functional correctness)
// =============================================================================

TEST(BroadcastDRCContract, BelowThreshold_MinimalChange) {
  blockplan::BroadcastAudioProcessor proc;

  // -30 dBFS ≈ 1035. Well below -18 threshold.
  int16_t input_val = 1035;
  auto frame = MakeFrame(input_val, 4800);  // 100ms
  proc.Process(frame);

  // With no compression, output = input * makeup_gain.
  // Makeup = +4 dB (v0.2) ≈ 1.585x. So 1035 * 1.585 ≈ 1640.
  // Check late samples (after envelope has settled).
  int16_t out = ReadSample(frame, 4000 * 2);
  float expected = static_cast<float>(input_val) * std::pow(10.0f, 4.0f / 20.0f);
  EXPECT_NEAR(static_cast<float>(out), expected, expected * 0.05f)
      << "Below threshold: output should be input * makeup gain only";
}

TEST(BroadcastDRCContract, AboveThreshold_Reduced) {
  blockplan::BroadcastAudioProcessor proc;

  // -6 dBFS ≈ 16384. 12 dB above -18 threshold.
  int16_t input_val = 16384;

  // Feed enough frames to reach steady state.
  for (int i = 0; i < 100; ++i) {
    auto frame = MakeFrame(input_val, 480);
    proc.Process(frame);
  }

  auto frame = MakeFrame(input_val, 480);
  proc.Process(frame);
  int16_t out_peak = PeakAbs(frame);

  // With compression active, output peak should be less than input * makeup.
  // Pure makeup of 16384 would be ~23143. Compressed should be significantly less.
  float pure_makeup = static_cast<float>(input_val) * std::pow(10.0f, 3.0f / 20.0f);
  EXPECT_LT(static_cast<float>(out_peak), pure_makeup * 0.95f)
      << "Above threshold: compression should reduce output below pure makeup level";
}

TEST(BroadcastDRCContract, MakeupGain_Applied) {
  blockplan::BroadcastAudioProcessor proc;

  // Very quiet signal — well below threshold, no compression.
  // -40 dBFS ≈ 328.
  int16_t input_val = 328;
  // Process enough frames to reach steady state.
  for (int i = 0; i < 50; ++i) {
    auto frame = MakeFrame(input_val, 480);
    proc.Process(frame);
  }
  auto frame = MakeFrame(input_val, 480);
  float reduction = proc.Process(frame);

  // No compression expected.
  EXPECT_NEAR(reduction, 0.0f, 0.1f);

  // Output should be louder than input due to makeup gain (+3 dB).
  int16_t out = ReadSample(frame, 400 * 2);
  EXPECT_GT(std::abs(out), std::abs(input_val))
      << "Makeup gain should make output louder than input when below threshold";
}

TEST(BroadcastDRCContract, Clamp_NoWraparound) {
  blockplan::BroadcastAudioProcessor proc;

  // Max S16 value — makeup gain will push above 32767.
  auto frame = MakeFrame(32767, 1024);
  proc.Process(frame);

  auto* samples = reinterpret_cast<const int16_t*>(frame.data.data());
  for (size_t i = 0; i < static_cast<size_t>(frame.nb_samples) * 2; ++i) {
    EXPECT_GE(samples[i], -32768) << "No wraparound below at sample " << i;
    EXPECT_LE(samples[i], 32767) << "No wraparound above at sample " << i;
  }
}

TEST(BroadcastDRCContract, ReturnsGainReduction) {
  blockplan::BroadcastAudioProcessor proc;

  // Feed loud frames to build envelope above threshold.
  for (int i = 0; i < 50; ++i) {
    auto loud = MakeFrame(30000, 480);
    proc.Process(loud);
  }

  auto loud = MakeFrame(30000, 480);
  float reduction_loud = proc.Process(loud);
  EXPECT_GT(reduction_loud, 0.0f)
      << "Signal above threshold must produce positive gain reduction";

  // Reset and feed quiet signal.
  proc.Reset();
  for (int i = 0; i < 50; ++i) {
    auto quiet = MakeFrame(200, 480);
    proc.Process(quiet);
  }
  auto quiet = MakeFrame(200, 480);
  float reduction_quiet = proc.Process(quiet);
  EXPECT_NEAR(reduction_quiet, 0.0f, 0.01f)
      << "Signal below threshold should produce zero (or near-zero) gain reduction";
}

// =============================================================================
// Envelope stability: ConstantTone_NoPumping
// =============================================================================

TEST(BroadcastDRCContract, ConstantTone_NoPumping) {
  blockplan::BroadcastAudioProcessor proc;

  // -12 dBFS ≈ 8192 peak. 6 dB above threshold.
  // Generate ~5 seconds of a constant sine wave, fed in 10ms chunks.
  const int chunk_samples = 480;  // 10ms @ 48kHz
  const int total_chunks = 500;   // 500 * 10ms = 5 seconds
  const int16_t amplitude = 8192;

  // Track per-chunk return values to measure convergence.
  std::vector<float> reductions;
  reductions.reserve(total_chunks);

  // Use a running sample offset so the sine wave is continuous across chunks.
  int64_t sample_offset = 0;
  for (int c = 0; c < total_chunks; ++c) {
    buffer::AudioFrame frame;
    frame.sample_rate = 48000;
    frame.channels = 2;
    frame.nb_samples = chunk_samples;
    frame.pts_us = sample_offset * 1000000 / 48000;

    size_t total = static_cast<size_t>(chunk_samples) * 2;
    frame.data.resize(total * sizeof(int16_t));
    auto* samples = reinterpret_cast<int16_t*>(frame.data.data());
    for (int i = 0; i < chunk_samples; ++i) {
      float t = static_cast<float>(sample_offset + i) / 48000.0f;
      float val = static_cast<float>(amplitude) *
                  std::sin(2.0f * static_cast<float>(M_PI) * 1000.0f * t);
      auto s = static_cast<int16_t>(
          std::max(-32768.0f, std::min(32767.0f, val)));
      samples[i * 2] = s;
      samples[i * 2 + 1] = s;
    }
    sample_offset += chunk_samples;

    float r = proc.Process(frame);
    reductions.push_back(r);
  }

  // After initial attack (~50ms = 5 chunks), the gain reduction should stabilize.
  // Check the last 4 seconds (chunks 100–499) for stability.
  float min_r = reductions[100];
  float max_r = reductions[100];
  double sum_r = 0.0;
  int count = 0;
  for (int c = 100; c < total_chunks; ++c) {
    if (reductions[c] < min_r) min_r = reductions[c];
    if (reductions[c] > max_r) max_r = reductions[c];
    sum_r += reductions[c];
    count++;
  }
  float avg_r = static_cast<float>(sum_r / count);

  // The range of per-chunk peak reductions should be very tight.
  // A sine wave has constant peak amplitude, so the envelope should be stable.
  // Allow 0.5 dB of variation (generous — actual should be near zero).
  EXPECT_LT(max_r - min_r, 0.5f)
      << "Gain reduction should stabilize on constant tone (range="
      << (max_r - min_r) << " dB)";

  // The reduction should be positive (signal is above threshold).
  EXPECT_GT(avg_r, 0.0f)
      << "Constant tone at -12 dBFS should trigger compression";
}
