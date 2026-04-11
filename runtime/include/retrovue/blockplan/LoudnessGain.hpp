// Repository: Retrovue-playout
// Component: Loudness Gain Application
// Purpose: INV-LOUDNESS-NORMALIZED-001 — apply constant gain to S16 audio
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_BLOCKPLAN_LOUDNESS_GAIN_HPP_
#define RETROVUE_BLOCKPLAN_LOUDNESS_GAIN_HPP_

#include <algorithm>
#include <cmath>
#include <cstdint>

#include "retrovue/buffer/FrameRingBuffer.h"

namespace retrovue::blockplan {

// Convert dB to linear gain factor: 10^(gain_db / 20)
inline float GainDbToLinear(float gain_db) {
  return std::pow(10.0f, gain_db / 20.0f);
}

// Convert dB to Q16 fixed-point linear gain: int32(10^(gain_db/20) * 65536).
// Called ONCE at segment activation (offline). Unity = 65536 (1.0 in Q16).
inline int32_t GainDbToQ16(float gain_db) {
  float linear = std::pow(10.0f, gain_db / 20.0f);
  // Clamp to prevent overflow: max ~31.999× (≈+30 dB)
  if (linear > 31.999f) linear = 31.999f;
  return static_cast<int32_t>(linear * 65536.0f + 0.5f);
}

// INV-LOUDNESS-NORMALIZED-001 Rule 1,2,3:
// Apply constant linear gain to every S16 sample in an AudioFrame.
// - Sample count and timing remain unchanged (Rule 2).
// - Clamps to int16 range [-32768, +32767] (Rule 3).
// - gain_db == 0.0 must not be called (Rule 4: caller guards).
inline void ApplyGainS16(buffer::AudioFrame& frame, float linear_gain) {
  const size_t total_samples =
      static_cast<size_t>(frame.nb_samples) * static_cast<size_t>(frame.channels);
  const size_t byte_count = total_samples * sizeof(int16_t);

  if (frame.data.size() < byte_count) return;

  auto* samples = reinterpret_cast<int16_t*>(frame.data.data());
  for (size_t i = 0; i < total_samples; ++i) {
    float scaled = static_cast<float>(samples[i]) * linear_gain;
    // Rule 3: clamp to int16 range, no wraparound
    if (scaled > 32767.0f) scaled = 32767.0f;
    else if (scaled < -32768.0f) scaled = -32768.0f;
    samples[i] = static_cast<int16_t>(scaled);
  }
}

// Q16 fixed-point version of ApplyGainS16 for hot-path use.
// gain_q16 = 65536 means unity (1.0). No floats. No drift.
// sample = clamp((sample * gain_q16) >> 16, -32768, +32767)
inline void ApplyGainS16Q16(buffer::AudioFrame& frame, int32_t gain_q16) {
  const size_t total_samples =
      static_cast<size_t>(frame.nb_samples) * static_cast<size_t>(frame.channels);
  const size_t byte_count = total_samples * sizeof(int16_t);

  if (frame.data.size() < byte_count) return;

  auto* samples = reinterpret_cast<int16_t*>(frame.data.data());
  for (size_t i = 0; i < total_samples; ++i) {
    int64_t scaled = (static_cast<int64_t>(samples[i]) * gain_q16) >> 16;
    if (scaled > 32767) scaled = 32767;
    else if (scaled < -32768) scaled = -32768;
    samples[i] = static_cast<int16_t>(scaled);
  }
}

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_LOUDNESS_GAIN_HPP_
