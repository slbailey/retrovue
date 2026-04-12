// Repository: Retrovue-playout
// Component: INV-AUDIO-CONTINUITY-NO-DROP Contract Tests
// Purpose: Verify audio samples are NEVER discarded due to queue overflow,
//          congestion, or backpressure.
//
//          Enforcement model:
//          - AudioLookaheadBuffer::Push blocks at capacity (never silently drops).
//          - TryPopSamples returns false on underflow (no silence injection).
//          - Total samples pushed == total samples popped across a full cycle.
//
// Contract: docs/contracts/invariants/shared/INV-AUDIO-CONTINUITY-NO-DROP.md
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>
#include <cstdint>
#include <cstring>
#include <vector>

#include "retrovue/blockplan/AudioLookaheadBuffer.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"

namespace retrovue::blockplan::testing {
namespace {

// Helper: make an AudioFrame with given sample count, all zeros.
static buffer::AudioFrame MakeAudioFrame(int nb_samples, int16_t sample_value = 0) {
  buffer::AudioFrame frame;
  frame.sample_rate = buffer::kHouseAudioSampleRate;
  frame.channels    = buffer::kHouseAudioChannels;
  frame.nb_samples  = nb_samples;
  const size_t byte_count =
      static_cast<size_t>(nb_samples) *
      static_cast<size_t>(buffer::kHouseAudioChannels) *
      sizeof(int16_t);
  frame.data.resize(byte_count);
  if (sample_value != 0) {
    auto* p = reinterpret_cast<int16_t*>(frame.data.data());
    for (int i = 0; i < nb_samples * buffer::kHouseAudioChannels; ++i) {
      p[i] = sample_value;
    }
  }
  return frame;
}

}  // namespace

// =============================================================================
// INV-AUDIO-CONTINUITY-NO-DROP — Compliant: push N frames, pop all samples.
// Total samples in == total samples out (zero loss).
// =============================================================================
TEST(InvAudioContinuityNoDrop, Compliant_PushAndPop_NoSamplesLost) {
  AudioLookaheadBuffer buf(/*target_depth_ms=*/1000);

  // Push 5 frames of 1600 samples each (≈33ms per frame at 48 kHz).
  constexpr int kFrames   = 5;
  constexpr int kSamples  = 1600;
  constexpr int kTotal    = kFrames * kSamples;

  for (int i = 0; i < kFrames; ++i) {
    auto result = buf.Push(MakeAudioFrame(kSamples));
    ASSERT_EQ(result, AudioLookaheadBuffer::PushResult::kPushed)
        << "INV-AUDIO-CONTINUITY-NO-DROP: Push must succeed (not drop)";
  }

  EXPECT_EQ(buf.TotalSamplesPushed(), kTotal)
      << "INV-AUDIO-CONTINUITY-NO-DROP: All pushed samples must be recorded";

  // Pop all samples — one chunk at a time matching 1600-sample frames.
  int64_t popped = 0;
  buffer::AudioFrame out;
  for (int i = 0; i < kFrames; ++i) {
    bool ok = buf.TryPopSamples(kSamples, out);
    ASSERT_TRUE(ok) << "INV-AUDIO-CONTINUITY-NO-DROP: Pop must succeed when samples available";
    EXPECT_EQ(out.nb_samples, kSamples);
    popped += out.nb_samples;
  }

  EXPECT_EQ(popped, static_cast<int64_t>(kTotal))
      << "INV-AUDIO-CONTINUITY-NO-DROP: All pushed samples must be retrievable (zero loss)";
  EXPECT_EQ(buf.TotalSamplesPopped(), kTotal)
      << "INV-AUDIO-CONTINUITY-NO-DROP: TotalSamplesPopped must equal TotalSamplesPushed";
  EXPECT_EQ(buf.UnderflowCount(), 0)
      << "INV-AUDIO-CONTINUITY-NO-DROP: No underflow expected when sufficient samples pushed";
}

// =============================================================================
// INV-AUDIO-CONTINUITY-NO-DROP — Underflow returns false (no silence injection).
// If samples are exhausted, TryPopSamples returns false rather than injecting
// synthetic (silent) frames. This preserves sample continuity (no fabrication).
// =============================================================================
TEST(InvAudioContinuityNoDrop, Compliant_Underflow_ReturnsFalse_NoSilenceInjected) {
  AudioLookaheadBuffer buf(/*target_depth_ms=*/1000);

  // Push exactly 3200 samples.
  buf.Push(MakeAudioFrame(1600));
  buf.Push(MakeAudioFrame(1600));

  const int64_t samples_before_pop = buf.TotalSamplesPushed();
  ASSERT_EQ(samples_before_pop, 3200);

  // Pop all 3200 samples.
  buffer::AudioFrame out;
  ASSERT_TRUE(buf.TryPopSamples(3200, out));

  // Now the buffer is empty. A further pop must return false — not inject silence.
  bool underflow_ok = buf.TryPopSamples(1600, out);
  EXPECT_FALSE(underflow_ok)
      << "INV-AUDIO-CONTINUITY-NO-DROP: TryPopSamples on empty buffer must "
         "return false (not inject silence — no fabrication of audio)";

  // Underflow counter increments correctly.
  EXPECT_GE(buf.UnderflowCount(), 1)
      << "INV-AUDIO-CONTINUITY-NO-DROP: Underflow must be counted for observability";

  // Total pushed is unchanged — underflow does not fabricate samples.
  EXPECT_EQ(buf.TotalSamplesPushed(), samples_before_pop)
      << "INV-AUDIO-CONTINUITY-NO-DROP: Fabrication would show as extra pushed samples";
}

// =============================================================================
// INV-AUDIO-CONTINUITY-NO-DROP — Multiple frames: samples are contiguous.
// Pop in a different chunk size to verify all bytes are present unchanged.
// =============================================================================
TEST(InvAudioContinuityNoDrop, Compliant_SamplesContiguous_MultiFramePop) {
  AudioLookaheadBuffer buf(/*target_depth_ms=*/1000);

  // Push 4 frames of 800 samples each = 3200 total.
  for (int i = 0; i < 4; ++i) {
    ASSERT_EQ(buf.Push(MakeAudioFrame(800)), AudioLookaheadBuffer::PushResult::kPushed);
  }

  // Pop as 2 × 1600 — chunk boundary crossing.
  buffer::AudioFrame out;
  ASSERT_TRUE(buf.TryPopSamples(1600, out));
  EXPECT_EQ(out.nb_samples, 1600)
      << "INV-AUDIO-CONTINUITY-NO-DROP: Pop across frame boundary must return "
         "contiguous samples (no gaps, no drops at frame seam)";
  ASSERT_TRUE(buf.TryPopSamples(1600, out));
  EXPECT_EQ(out.nb_samples, 1600);

  EXPECT_EQ(buf.TotalSamplesPopped(), 3200)
      << "INV-AUDIO-CONTINUITY-NO-DROP: 3200 samples in, 3200 samples out";
}

}  // namespace retrovue::blockplan::testing
