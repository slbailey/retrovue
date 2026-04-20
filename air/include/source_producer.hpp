// AIR vNext — SourceProducer abstract interface.
//
// SourceProducer is the runtime contract for any source that supplies
// decoded frames and samples to a per-source Normalizer. Each concrete
// SourceProducer (pad, file-backed, weather, guide, emergency slate, future
// dynamic sources) conforms to this contract.
//
// A SourceProducer emits decoded source-canonical output (source rate,
// source format, source PTS). Source-to-channel translation happens
// downstream in the SourceProducer's dedicated Normalizer.
//
// Lifecycle intents (prepare / activate / retire) are issued by
// PlaybackDirector; the concrete SourceProducer implements the state machine.
//
// First slice uses a Pull API: the Normalizer requests the next frame /
// audio block; the producer returns one or signals no-output-yet /
// end-of-source. A push / event-driven API is possible later if needed.
//
// Vault references:
//   - SourceProducer (component spec)
//   - Truth - Source Time Is Producer-Local, Channel Time Is Canonical

#ifndef RETROVUE_AIR_SOURCE_PRODUCER_HPP_
#define RETROVUE_AIR_SOURCE_PRODUCER_HPP_

#include <cstdint>
#include <optional>

#include "channel_canonical.hpp"
#include "frame_types.hpp"

namespace retrovue::air {

// A decoded video frame in SOURCE-canonical form, emitted by SourceProducer.
// Distinct from VideoFrame (which is channel-canonical). The conversion
// happens inside Normalizer.
struct SourceVideoFrame {
  int width;
  int height;
  // Source PTS, in microseconds on the source's own timeline.
  int64_t source_pts_us;
  // Raw pixel data, source pixel format (first slice: YUV420P).
  std::vector<uint8_t> data;
};

// A block of decoded audio samples in SOURCE-canonical form.
struct SourceAudioBlock {
  int sample_rate;
  int channels;
  int nb_samples;
  int64_t source_pts_us;
  std::vector<int16_t> data;  // interleaved PCM int16
};

// Health classification for a SourceProducer. Drives ReadinessController
// verdicts and signals to PlaybackDirector whether a producer is fit to
// supply its segment.
enum class ProducerHealth {
  kHealthy,
  kDegraded,
  kFailed,
};

// Lifecycle state of a SourceProducer.
enum class ProducerLifecycle {
  kConstructed,   // Allocated but not yet prepared.
  kPrepared,      // Ready to emit on demand.
  kActivated,     // Emitting; Normalizer pulling output.
  kRetired,       // Released; no further output.
};

class ISourceProducer {
 public:
  virtual ~ISourceProducer() = default;

  // Prepare: transition Constructed -> Prepared. After this call, the
  // producer is ready to emit. May fail if source is unreachable.
  virtual bool Prepare() = 0;

  // Activate: transition Prepared -> Activated. After this, PullVideo /
  // PullAudio may return output.
  virtual bool Activate() = 0;

  // Retire: transition to Retired and release source-local resources.
  virtual void Retire() = 0;

  // Pull the next source-canonical video frame. Returns nullopt if no frame
  // is currently available (consumer should retry) or source exhausted.
  virtual std::optional<SourceVideoFrame> PullVideo() = 0;

  // Pull the next source-canonical audio block (chunk of samples at source
  // sample rate). Returns nullopt if no block available or source exhausted.
  virtual std::optional<SourceAudioBlock> PullAudio() = 0;

  // Current health signal. Read by Normalizer and by ReadinessController.
  virtual ProducerHealth Health() const = 0;

  // Current lifecycle state.
  virtual ProducerLifecycle Lifecycle() const = 0;
};

}  // namespace retrovue::air

#endif  // RETROVUE_AIR_SOURCE_PRODUCER_HPP_
