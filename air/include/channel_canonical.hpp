// AIR vNext — ChannelCanonical configuration.
//
// The channel's canonical output format. Immutable for the lifetime of a
// session. Every SourceProducer and Normalizer receives a reference to the
// channel's canonical configuration; Normalizers produce frames that conform
// to it.
//
// Vault references:
//   - Truth - Source Time Is Producer-Local, Channel Time Is Canonical
//   - Normalizer (component spec)
//   - BufferStore (archetype)
//
// Contract: channel canonical parameters are supplied at Normalizer
// construction and MUST NOT change for the Normalizer's lifetime.

#ifndef RETROVUE_AIR_CHANNEL_CANONICAL_HPP_
#define RETROVUE_AIR_CHANNEL_CANONICAL_HPP_

#include <cstdint>

namespace retrovue::air {

// Rational representation of a rate. Framerate is canonically rational
// (e.g. 30000/1001 for NTSC). Sample rate is integer but exposed through the
// same shape for uniformity where rationals are useful elsewhere.
struct Rational {
  int64_t num;
  int64_t den;

  constexpr bool IsValid() const {
    return num > 0 && den > 0;
  }

  // Microseconds per unit (per frame for framerate).
  // Example: 30000/1001 fps → (1e6 * 1001) / 30000 ≈ 33366.7 us/frame.
  // Returned as int64 microseconds; for exact arithmetic use num/den directly.
  constexpr int64_t PeriodMicros() const {
    return (int64_t{1'000'000} * den) / num;
  }

  // PTS in microseconds of the Nth step at this rate, starting from 0.
  // Uses round-to-nearest to minimize drift over long sequences.
  //   value = round(n * 1e6 * den / num)
  // This is the canonical channel-time PTS formula — anywhere that needs
  // "what is the PTS of frame N at this rate" or "what is the PTS of sample
  // N at this rate", use this method. Do NOT accumulate PeriodMicros()
  // linearly; that drifts ~1us per step and compounds over long segments.
  constexpr int64_t NthStepPtsUs(int64_t n) const {
    return (n * int64_t{1'000'000} * den + num / 2) / num;
  }
};

// Pixel format enum. First slice supports YUV420P only; additional formats
// added as concrete producers and normalizers require them.
enum class PixelFormat {
  kYuv420p,
};

struct VideoCanonical {
  int width;
  int height;
  Rational frame_rate;
  PixelFormat pixel_format;

  bool IsValid() const {
    return width > 0 && height > 0 && frame_rate.IsValid();
  }
};

struct AudioCanonical {
  int sample_rate;
  int channels;

  bool IsValid() const {
    return sample_rate > 0 && channels > 0;
  }
};

struct ChannelCanonical {
  VideoCanonical video;
  AudioCanonical audio;

  bool IsValid() const {
    return video.IsValid() && audio.IsValid();
  }
};

}  // namespace retrovue::air

#endif  // RETROVUE_AIR_CHANNEL_CANONICAL_HPP_
