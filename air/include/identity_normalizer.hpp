// AIR vNext — IdentityNormalizer.
//
// A Normalizer that forwards source output unchanged to channel-canonical
// output. Valid only when the upstream SourceProducer already emits at
// channel rate / channel format (the paradigmatic case is PadSourceProducer,
// which generates directly at channel canonical).
//
// Purpose: validates the Normalizer contract surface and the channel-origin
// model end-to-end without the complexity of real rate / format conversion.
// The "transform" is data-pass-through; the PTS translation and origin
// bookkeeping are what's being exercised.
//
// Re-anchor thresholds follow the vault's tiered policy.
//
// Vault references:
//   - Normalizer (component spec)
//   - Truth - Source Time Is Producer-Local, Channel Time Is Canonical

#ifndef RETROVUE_AIR_IDENTITY_NORMALIZER_HPP_
#define RETROVUE_AIR_IDENTITY_NORMALIZER_HPP_

#include <cstdint>
#include <optional>

#include "channel_canonical.hpp"
#include "frame_types.hpp"
#include "normalizer.hpp"
#include "source_producer.hpp"

namespace retrovue::air {

class IdentityNormalizer : public INormalizer {
 public:
  // Construct with channel canonical parameters, the upstream
  // SourceProducer (borrowed pointer; Normalizer does not own the producer),
  // and the initial channel origin.
  //
  // Preconditions:
  //   - canonical.IsValid()
  //   - source is non-null and has been Prepare()d and Activate()d.
  //   - origin anchor values are in the expected units (microseconds).
  IdentityNormalizer(ChannelCanonical canonical,
                     ISourceProducer* source,
                     ChannelOrigin origin);

  const ChannelCanonical& Canonical() const override { return canonical_; }
  const ChannelOrigin& Origin() const override { return origin_; }

  std::optional<VideoFrame> PullVideo() override;
  std::optional<AudioBlock> PullAudio() override;

  ReanchorTier Reanchor(int64_t new_channel_pts_anchor_us) override;

  int64_t ReanchorNoopThresholdUs() const override;
  int64_t ReanchorRePrepThresholdUs() const override;

 private:
  ChannelCanonical canonical_;
  ISourceProducer* source_;  // not owned
  ChannelOrigin origin_;

  // Cached thresholds (computed at construction from canonical framerate).
  int64_t reanchor_noop_threshold_us_;
  int64_t reanchor_re_prep_threshold_us_;

  // Channel frame / sample indices, owned by the Normalizer. Channel-time
  // PTS is derived from these via Rational::NthStepPtsUs for video and
  // sample-index arithmetic for audio. Source PTS is NEVER used as a
  // decision input downstream of the Normalizer — it survives only as
  // opaque metadata on emitted frames.
  int64_t next_channel_video_frame_index_ = 0;
  int64_t next_channel_audio_sample_index_ = 0;
};

}  // namespace retrovue::air

#endif  // RETROVUE_AIR_IDENTITY_NORMALIZER_HPP_
