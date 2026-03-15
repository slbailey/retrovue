// Repository: Retrovue-playout
// Component: Broadcast Audio Processor
// Purpose: INV-BROADCAST-DRC-001 — per-sample dynamic range compression
//          for broadcast-grade audio output.
// Design Authority: pkg/air/docs/design/BROADCAST_AUDIO_PROCESSING.md
// Copyright (c) 2026 RetroVue

#ifndef RETROVUE_BLOCKPLAN_BROADCAST_AUDIO_PROCESSOR_HPP_
#define RETROVUE_BLOCKPLAN_BROADCAST_AUDIO_PROCESSOR_HPP_

#include <algorithm>
#include <cmath>
#include <cstdint>

#include "retrovue/buffer/FrameRingBuffer.h"

namespace retrovue::blockplan {

// BroadcastAudioProcessor — per-sample dynamic range compression.
//
// Operates on S16 stereo interleaved audio at 48 kHz (house format).
// Positioned in the pipeline AFTER loudness normalization (ApplyGainS16)
// and BEFORE encoding (encodeAudioFrame).
//
// Detection: linked stereo peak — max(abs(L), abs(R)) per sample.
// Envelope: exponential attack/release follower, per-sample update.
// Gain: computed and applied per sample (no windowed block processing).
//
// Invariants enforced:
//   INV-BROADCAST-DRC-001: Stage exists between normalization and encoding.
//   INV-BROADCAST-DRC-002: Sample count, channels, timing, PTS unchanged.
//   INV-BROADCAST-DRC-003: Envelope resets to unity on segment boundaries.
//   INV-BROADCAST-DRC-004: Linked stereo — same gain to both channels.
class BroadcastAudioProcessor {
 public:
  BroadcastAudioProcessor()
      : envelope_level_(0.0f) {
    // Precompute smoothing coefficients from time constants.
    // Standard exponential follower: coeff = exp(-1 / (tau_seconds * sample_rate))
    // Attack: envelope tracks rising signal.
    // Release: envelope decays toward falling signal.
    const float attack_samples = kAttackMs * kSampleRate / 1000.0f;
    const float release_samples = kReleaseMs * kSampleRate / 1000.0f;
    attack_coeff_ = std::exp(-1.0f / attack_samples);
    release_coeff_ = std::exp(-1.0f / release_samples);

    // Precompute threshold as linear amplitude for comparison in hot loop.
    // -18 dBFS → 10^(-18/20) ≈ 0.1259
    threshold_linear_ = std::pow(10.0f, kThresholdDbfs / 20.0f);

    // Precompute makeup gain as linear.
    makeup_linear_ = std::pow(10.0f, kMakeupGainDb / 20.0f);
  }

  // Process an AudioFrame in-place. Returns peak gain reduction in centidecibels
  // (dB × 100, integer). E.g. 3.5 dB reduction → 350. Zero means no compression.
  // INV-BROADCAST-DRC-002: Only frame.data (sample amplitudes) is modified.
  // Sample count, channel count, sample_rate, pts_us are never touched.
  int32_t Process(buffer::AudioFrame& frame) {
    const size_t total_samples =
        static_cast<size_t>(frame.nb_samples) * static_cast<size_t>(frame.channels);
    const size_t byte_count = total_samples * sizeof(int16_t);

    if (frame.data.size() < byte_count || frame.channels != kChannels) {
      return 0;
    }

    auto* samples = reinterpret_cast<int16_t*>(frame.data.data());
    const size_t num_pairs = static_cast<size_t>(frame.nb_samples);
    float peak_reduction_db = 0.0f;

    for (size_t i = 0; i < num_pairs; ++i) {
      const size_t idx = i * 2;

      // INV-BROADCAST-DRC-004: Linked stereo peak detection.
      // Level = max(abs(L), abs(R)) as linear amplitude normalized to [0, 1].
      const float left = std::abs(static_cast<float>(samples[idx]));
      const float right = std::abs(static_cast<float>(samples[idx + 1]));
      const float level = std::max(left, right) / 32768.0f;

      // Exponential envelope follower — per-sample update.
      if (level > envelope_level_) {
        // Attack: envelope rises toward signal.
        envelope_level_ = attack_coeff_ * envelope_level_ +
                          (1.0f - attack_coeff_) * level;
      } else {
        // Release: envelope decays toward signal.
        envelope_level_ = release_coeff_ * envelope_level_ +
                          (1.0f - release_coeff_) * level;
      }

      // Compute gain reduction from envelope.
      float reduction_db = 0.0f;
      float linear_gain = makeup_linear_;  // Default: makeup only, no reduction.

      if (envelope_level_ > threshold_linear_) {
        // Convert envelope to dBFS for gain computation.
        // Guard against log(0) — envelope_level_ > threshold_linear_ > 0 here.
        const float envelope_dbfs = 20.0f * std::log10(envelope_level_);
        reduction_db = (envelope_dbfs - kThresholdDbfs) * (1.0f - 1.0f / kRatio);
        // Total gain = makeup - reduction, converted to linear.
        linear_gain = std::pow(10.0f, (kMakeupGainDb - reduction_db) / 20.0f);
      }

      if (reduction_db > peak_reduction_db) {
        peak_reduction_db = reduction_db;
      }

      // Apply identical gain to both channels (INV-BROADCAST-DRC-004).
      float scaled_l = static_cast<float>(samples[idx]) * linear_gain;
      float scaled_r = static_cast<float>(samples[idx + 1]) * linear_gain;

      // Clamp to int16 range — no wraparound (same as ApplyGainS16 Rule 3).
      if (scaled_l > 32767.0f) scaled_l = 32767.0f;
      else if (scaled_l < -32768.0f) scaled_l = -32768.0f;
      if (scaled_r > 32767.0f) scaled_r = 32767.0f;
      else if (scaled_r < -32768.0f) scaled_r = -32768.0f;

      samples[idx] = static_cast<int16_t>(scaled_l);
      samples[idx + 1] = static_cast<int16_t>(scaled_r);
    }

    return static_cast<int32_t>(peak_reduction_db * 100.0f);
  }

  // INV-BROADCAST-DRC-003: Reset envelope to unity (silence).
  // Called on segment and block boundaries. The attack envelope provides
  // the smooth ramp from unity — no step discontinuity.
  void Reset() {
    envelope_level_ = 0.0f;
  }

 private:
  // v0.2 compiled constants — see design doc Section 13.3.
  // Tuned for retro TV aesthetic: tighter compression, faster response.
  static constexpr float kThresholdDbfs = -20.0f;
  static constexpr float kRatio = 4.0f;
  static constexpr float kAttackMs = 3.0f;
  static constexpr float kReleaseMs = 80.0f;
  static constexpr float kMakeupGainDb = 4.0f;
  static constexpr int kSampleRate = 48000;
  static constexpr int kChannels = 2;

  // Envelope state — smoothed peak level as linear amplitude [0, 1].
  float envelope_level_;

  // Precomputed smoothing coefficients.
  float attack_coeff_;
  float release_coeff_;

  // Precomputed threshold and makeup as linear amplitudes.
  float threshold_linear_;
  float makeup_linear_;
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_BROADCAST_AUDIO_PROCESSOR_HPP_
