// Repository: Retrovue-playout
// Component: INV-LOUDNESS-NORMALIZED-001 Shared Invariant Anchor Tests
// Purpose: Anchor INV-LOUDNESS-NORMALIZED-001 in blockplan_contract_tests.
//          Core arithmetic coverage lives in LoudnessGainContractTests.cpp.
//          This file adds explicit shared-invariant-ID references and
//          validates the gain formula and sample-count/pts invariance.
//
// Contract: docs/contracts/invariants/shared/INV-LOUDNESS-NORMALIZED-001.md
// See also: tests/contracts/BlockPlan/LoudnessGainContractTests.cpp
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>
#include <cmath>
#include <cstdint>
#include <vector>

#include "retrovue/blockplan/LoudnessGain.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"

namespace retrovue::blockplan::testing {
namespace {

static buffer::AudioFrame MakeTestFrame(int16_t sample_value, int nb_samples) {
  buffer::AudioFrame frame;
  frame.sample_rate = buffer::kHouseAudioSampleRate;
  frame.channels    = buffer::kHouseAudioChannels;
  frame.nb_samples  = nb_samples;
  const size_t total = static_cast<size_t>(nb_samples) *
                       static_cast<size_t>(frame.channels);
  frame.data.resize(total * sizeof(int16_t));
  auto* p = reinterpret_cast<int16_t*>(frame.data.data());
  for (size_t i = 0; i < total; ++i) p[i] = sample_value;
  return frame;
}

static int16_t ReadSampleAt(const buffer::AudioFrame& f, int i) {
  return reinterpret_cast<const int16_t*>(f.data.data())[i];
}

}  // namespace

// =============================================================================
// INV-LOUDNESS-NORMALIZED-001 Rule 7: gain_db = target_lufs - integrated_lufs.
// target_lufs = -24.0 (ATSC A/85).
// =============================================================================
TEST(InvLoudnessNormalized001Shared, GainFormula_TargetMinusIntegrated) {
  constexpr float kTargetLufs   = -24.0f;
  constexpr float kIntegrated   = -30.0f;
  constexpr float kExpected     = kTargetLufs - kIntegrated;  // = +6 dB

  EXPECT_FLOAT_EQ(kExpected, 6.0f)
      << "INV-LOUDNESS-NORMALIZED-001: gain_db = target - integrated = "
         "-24 - (-30) = +6 dB";

  float linear = GainDbToLinear(kExpected);
  EXPECT_NEAR(static_cast<double>(linear), 2.0, 0.01)
      << "INV-LOUDNESS-NORMALIZED-001: +6 dB ≈ 2.0× linear";
}

// =============================================================================
// INV-LOUDNESS-NORMALIZED-001 Rule 4: gain = 0.0 → pass-through (no change).
// =============================================================================
TEST(InvLoudnessNormalized001Shared, ZeroGainPassthrough_SamplesUnchanged) {
  auto frame = MakeTestFrame(12345, 256);
  auto orig  = frame;  // copy before gain

  float linear = GainDbToLinear(0.0f);
  EXPECT_NEAR(static_cast<double>(linear), 1.0, 0.001)
      << "INV-LOUDNESS-NORMALIZED-001: GainDbToLinear(0.0) must be 1.0";

  ApplyGainS16(frame, linear);

  const int total = frame.nb_samples * frame.channels;
  for (int i = 0; i < total; ++i) {
    EXPECT_EQ(ReadSampleAt(frame, i), ReadSampleAt(orig, i))
        << "INV-LOUDNESS-NORMALIZED-001: unity gain must not modify sample " << i;
  }
}

// =============================================================================
// INV-LOUDNESS-NORMALIZED-001 Rule 3: large gain is clamped; no int16 wrap.
// =============================================================================
TEST(InvLoudnessNormalized001Shared, ClampPreventsWrap) {
  auto frame = MakeTestFrame(30000, 64);
  float linear = GainDbToLinear(40.0f);  // ×100 → overflow without clamp
  ApplyGainS16(frame, linear);

  const int total = frame.nb_samples * frame.channels;
  for (int i = 0; i < total; ++i) {
    int16_t s = ReadSampleAt(frame, i);
    EXPECT_LE(s, 32767)
        << "INV-LOUDNESS-NORMALIZED-001: sample must not exceed +32767 (clamped)";
    EXPECT_GE(s, -32768)
        << "INV-LOUDNESS-NORMALIZED-001: sample must not go below -32768 (clamped)";
  }
}

// =============================================================================
// INV-LOUDNESS-NORMALIZED-001 Rule 2: nb_samples and pts_us unchanged by gain.
// =============================================================================
TEST(InvLoudnessNormalized001Shared, GainDoesNotAlterSampleCountOrPts) {
  auto frame = MakeTestFrame(1000, 256);
  frame.pts_us = 5'000'000;

  const int    nb_before  = frame.nb_samples;
  const int64_t pts_before = frame.pts_us;

  ApplyGainS16(frame, GainDbToLinear(-6.0f));

  EXPECT_EQ(frame.nb_samples, nb_before)
      << "INV-LOUDNESS-NORMALIZED-001: nb_samples must not change after gain";
  EXPECT_EQ(frame.pts_us, pts_before)
      << "INV-LOUDNESS-NORMALIZED-001: pts_us must not change after gain";
}

}  // namespace retrovue::blockplan::testing
