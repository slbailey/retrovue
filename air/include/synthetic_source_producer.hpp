// AIR vNext — SyntheticSourceProducer.
//
// Programmatic source that emits:
//   - Video frames at a configurable source framerate, each with its frame
//     index burned into the first 8 bytes of the Y plane (little-endian
//     int64). Tests use the burned index to verify cadence pattern
//     correctness after normalization.
//   - Audio samples at a configurable source sample rate, forming a
//     specified waveform (constant, linear ramp, or sine). Tests use the
//     waveform to verify SRC correctness.
//
// No decode, no external dependencies, no media files. Fully deterministic.
//
// Purpose: exercise StandardNormalizer's cadence and SRC paths in slice 2
// without decode or container complexity.

#ifndef AIR_SYNTHETIC_SOURCE_PRODUCER_HPP_
#define AIR_SYNTHETIC_SOURCE_PRODUCER_HPP_

#include <cstdint>
#include <optional>
#include <vector>

#include "channel_canonical.hpp"
#include "source_producer.hpp"

namespace retrovue::air {

enum class SyntheticAudioWaveform {
  kConstant,    // All samples = audio_constant_value.
  kLinearRamp,  // sample[n] = n * audio_ramp_step (wraps on int16 overflow).
  kSine,        // amp * sin(2pi * freq * n / rate), same on all channels.
};

class SyntheticSourceProducer : public ISourceProducer {
 public:
  struct Config {
    // Video
    Rational video_frame_rate;  // e.g., {24, 1}
    int video_width;
    int video_height;
    // Pixel format is YUV420P for first cut; kept implicit.

    // Audio
    int audio_sample_rate;  // e.g., 44100
    int audio_channels;     // e.g., 2
    SyntheticAudioWaveform audio_waveform = SyntheticAudioWaveform::kConstant;

    // Waveform parameters (used according to audio_waveform).
    int16_t audio_constant_value = 0;
    int16_t audio_ramp_step = 1;
    int audio_tone_frequency_hz = 1000;
    int16_t audio_tone_amplitude = 16000;

    // Block sizing — samples per channel per audio block emission.
    int audio_samples_per_block = 441;  // ~10ms at 44.1kHz
  };

  explicit SyntheticSourceProducer(Config config);

  bool Prepare() override;
  bool Activate() override;
  void Retire() override;

  std::optional<SourceVideoFrame> PullVideo() override;
  std::optional<SourceAudioBlock> PullAudio() override;

  ProducerHealth Health() const override { return ProducerHealth::kHealthy; }
  ProducerLifecycle Lifecycle() const override { return lifecycle_; }

  // Test helper: decode the frame index burned into a video frame's Y plane.
  // Expects at least 8 bytes of Y data; returns the little-endian int64
  // stored in bytes [0..7].
  static int64_t ReadFrameIndexFromYPlane(const std::vector<uint8_t>& data);

  // Accessors for state inspection.
  int64_t VideoFramesEmitted() const { return next_video_frame_index_; }
  int64_t AudioSamplesEmitted() const { return next_audio_sample_index_; }

 private:
  Config config_;
  ProducerLifecycle lifecycle_ = ProducerLifecycle::kConstructed;

  int64_t next_video_frame_index_ = 0;
  int64_t next_audio_sample_index_ = 0;

  // Pre-computed Y/U/V plane sizes.
  int y_size_;
  int uv_size_;
};

}  // namespace retrovue::air

#endif  // AIR_SYNTHETIC_SOURCE_PRODUCER_HPP_
