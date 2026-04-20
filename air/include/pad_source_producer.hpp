// AIR vNext — PadSourceProducer.
//
// A SourceProducer that emits black YUV420P video and silence audio
// indefinitely. Used as the default continuity source: always ready,
// always healthy, conforms to the uniform SourceProducer contract.
//
// Design mirrors the existing runtime/ PadProducer approach: pre-allocated
// session-lifetime buffers (broadcast-safe black Y=0x10, U=V=0x80; silence
// = zero-filled PCM), zero per-pull allocations for the payload. The
// frames returned carry immutable-content but per-pull PTS.
//
// Because pad is trivially ready and already at its "source" rate (we
// generate at whatever rate is requested), a pad source naturally matches
// the channel canonical rate when the Normalizer is identity. The pad
// source generates at the channel's framerate/sample rate directly; the
// IdentityNormalizer then forwards without rate conversion.
//
// Vault references:
//   - SourceProducer (component spec)
//   - Normalizer (component spec)

#ifndef RETROVUE_AIR_PAD_SOURCE_PRODUCER_HPP_
#define RETROVUE_AIR_PAD_SOURCE_PRODUCER_HPP_

#include <cstdint>
#include <optional>
#include <vector>

#include "channel_canonical.hpp"
#include "source_producer.hpp"

namespace retrovue::air {

class PadSourceProducer : public ISourceProducer {
 public:
  // Construct with the channel canonical format. The pad source generates
  // directly at channel rates (video = channel framerate; audio sample rate
  // and channel count = channel audio canonical). This keeps the first slice
  // simple: pad + identity normalizer is a clean end-to-end validation.
  explicit PadSourceProducer(ChannelCanonical canonical);

  bool Prepare() override;
  bool Activate() override;
  void Retire() override;

  std::optional<SourceVideoFrame> PullVideo() override;
  std::optional<SourceAudioBlock> PullAudio() override;

  ProducerHealth Health() const override { return ProducerHealth::kHealthy; }
  ProducerLifecycle Lifecycle() const override { return lifecycle_; }

  // Test / observability accessors.
  int64_t VideoFramesEmitted() const { return video_frames_emitted_; }
  int64_t AudioBlocksEmitted() const { return audio_blocks_emitted_; }

 private:
  ChannelCanonical canonical_;
  ProducerLifecycle lifecycle_ = ProducerLifecycle::kConstructed;

  // Pre-allocated black YUV420P frame payload. Reused on every video pull.
  std::vector<uint8_t> pad_video_data_;

  // Per-audio-block sample counts (nb_samples) vary per tick based on
  // 48000/fps math; compute max at construction, cap at a safe ceiling.
  int audio_samples_per_block_;
  // Pre-allocated silence block payload (zero-filled PCM int16). Reused.
  std::vector<int16_t> pad_audio_data_;

  // PadSourceProducer's "source time" is synthetic (pad has no real
  // timeline). Source PTS is computed per-call as round-to-nearest from
  // the emission index via Rational::NthStepPtsUs / sample-rate formula,
  // not by linear accumulation. This matches StandardNormalizer's formula
  // so pad + StandardNormalizer produce identical PTS for the same
  // channel position.
  int64_t video_frames_emitted_ = 0;
  int64_t audio_blocks_emitted_ = 0;
};

}  // namespace retrovue::air

#endif  // RETROVUE_AIR_PAD_SOURCE_PRODUCER_HPP_
