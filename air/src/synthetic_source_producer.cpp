// AIR vNext — SyntheticSourceProducer implementation.

#include "synthetic_source_producer.hpp"

#include <cmath>
#include <cstring>
#include <cstdint>

namespace retrovue::air {

namespace {

// Write a little-endian int64_t into the first 8 bytes of a buffer.
// Assumes buffer is at least 8 bytes.
void WriteLE64(uint8_t* dst, int64_t value) {
  const uint64_t u = static_cast<uint64_t>(value);
  for (int i = 0; i < 8; ++i) {
    dst[i] = static_cast<uint8_t>((u >> (i * 8)) & 0xFF);
  }
}

}  // namespace

SyntheticSourceProducer::SyntheticSourceProducer(Config config)
    : config_(config),
      y_size_(config.video_width * config.video_height),
      uv_size_((config.video_width / 2) * (config.video_height / 2)) {}

bool SyntheticSourceProducer::Prepare() {
  if (lifecycle_ != ProducerLifecycle::kConstructed) return false;
  lifecycle_ = ProducerLifecycle::kPrepared;
  return true;
}

bool SyntheticSourceProducer::Activate() {
  if (lifecycle_ != ProducerLifecycle::kPrepared) return false;
  lifecycle_ = ProducerLifecycle::kActivated;
  return true;
}

void SyntheticSourceProducer::Retire() {
  lifecycle_ = ProducerLifecycle::kRetired;
}

std::optional<SourceVideoFrame> SyntheticSourceProducer::PullVideo() {
  if (lifecycle_ != ProducerLifecycle::kActivated) return std::nullopt;

  const int64_t k = next_video_frame_index_;

  SourceVideoFrame frame;
  frame.width = config_.video_width;
  frame.height = config_.video_height;
  // Source PTS: sample-accurate integer microseconds.
  // pts_us = round(k * 1_000_000 * fps_den / fps_num)
  const int64_t num = config_.video_frame_rate.num;
  const int64_t den = config_.video_frame_rate.den;
  frame.source_pts_us =
      (k * 1'000'000 * den + num / 2) / num;

  // YUV420P payload. Y = broadcast black (0x10), U/V = neutral chroma (0x80).
  // First 8 bytes of Y encode frame index (little-endian int64).
  frame.data.assign(static_cast<size_t>(y_size_ + 2 * uv_size_), 0);
  std::memset(frame.data.data(), 0x10, static_cast<size_t>(y_size_));
  WriteLE64(frame.data.data(), k);  // Override first 8 bytes of Y with index.
  std::memset(frame.data.data() + y_size_, 0x80,
              static_cast<size_t>(2 * uv_size_));

  ++next_video_frame_index_;
  return frame;
}

std::optional<SourceAudioBlock> SyntheticSourceProducer::PullAudio() {
  if (lifecycle_ != ProducerLifecycle::kActivated) return std::nullopt;

  SourceAudioBlock block;
  block.sample_rate = config_.audio_sample_rate;
  block.channels = config_.audio_channels;
  block.nb_samples = config_.audio_samples_per_block;

  const int64_t sample_rate = config_.audio_sample_rate;
  const int64_t n_start = next_audio_sample_index_;
  block.source_pts_us =
      (n_start * 1'000'000 + sample_rate / 2) / sample_rate;

  const int channels = config_.audio_channels;
  const int nb = config_.audio_samples_per_block;
  block.data.resize(static_cast<size_t>(nb) * static_cast<size_t>(channels));

  switch (config_.audio_waveform) {
    case SyntheticAudioWaveform::kConstant: {
      for (size_t i = 0; i < block.data.size(); ++i) {
        block.data[i] = config_.audio_constant_value;
      }
      break;
    }
    case SyntheticAudioWaveform::kLinearRamp: {
      for (int n = 0; n < nb; ++n) {
        const int16_t v = static_cast<int16_t>(
            (n_start + n) * config_.audio_ramp_step);
        for (int c = 0; c < channels; ++c) {
          block.data[static_cast<size_t>(n * channels + c)] = v;
        }
      }
      break;
    }
    case SyntheticAudioWaveform::kSine: {
      const double two_pi_f_over_rate = 2.0 * M_PI *
          static_cast<double>(config_.audio_tone_frequency_hz) /
          static_cast<double>(sample_rate);
      const double amp = static_cast<double>(config_.audio_tone_amplitude);
      for (int n = 0; n < nb; ++n) {
        const double phase =
            two_pi_f_over_rate * static_cast<double>(n_start + n);
        const double v = amp * std::sin(phase);
        const int16_t iv = static_cast<int16_t>(std::round(v));
        for (int c = 0; c < channels; ++c) {
          block.data[static_cast<size_t>(n * channels + c)] = iv;
        }
      }
      break;
    }
  }

  next_audio_sample_index_ += nb;
  return block;
}

int64_t SyntheticSourceProducer::ReadFrameIndexFromYPlane(
    const std::vector<uint8_t>& data) {
  if (data.size() < 8) return -1;
  uint64_t u = 0;
  for (int i = 0; i < 8; ++i) {
    u |= static_cast<uint64_t>(data[i]) << (i * 8);
  }
  return static_cast<int64_t>(u);
}

}  // namespace retrovue::air
