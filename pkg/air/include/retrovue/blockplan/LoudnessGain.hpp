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

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_LOUDNESS_GAIN_HPP_
