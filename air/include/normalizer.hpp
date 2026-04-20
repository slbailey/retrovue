// AIR vNext — Normalizer abstract interface + ChannelOrigin type.
//
// Normalizer is the per-source authority that translates source-canonical
// frames and samples into channel-canonical frames and samples. Exactly
// one Normalizer exists per SourceProducer instance.
//
// The channel origin is the shared (source_pts_anchor, channel_pts_anchor)
// that both audio and video sub-normalizers resolve their output PTS
// against. This preserves A/V sync across independent rate conversions.
//
// Re-anchor policy is tiered:
//   - Tier 1 (delta < 1 channel frame period): no-op.
//   - Tier 2 (delta < 1 second): adjust origin; preview entries untouched.
//   - Tier 3 (delta >= 1 second): signal caller to re-prep.
//
// Vault references:
//   - Normalizer (component spec)
//   - Truth - Source Time Is Producer-Local, Channel Time Is Canonical

#ifndef RETROVUE_AIR_NORMALIZER_HPP_
#define RETROVUE_AIR_NORMALIZER_HPP_

#include <cstdint>
#include <optional>

#include "channel_canonical.hpp"
#include "frame_types.hpp"

namespace retrovue::air {

// The channel origin for one Normalizer's segment. Maps source time to
// channel time. Both video and audio sub-normalizers for this Normalizer
// MUST resolve their output PTS against this single origin.
struct ChannelOrigin {
  // Source PTS anchor, in microseconds on the source's own timeline.
  int64_t source_pts_anchor_us;
  // Channel PTS anchor, in microseconds on the channel's output timeline.
  int64_t channel_pts_anchor_us;
};

// Result of a re-anchor attempt.
enum class ReanchorTier {
  kNoop,       // Delta below threshold; origin unchanged.
  kAdjusted,   // Origin updated; preview entries remain valid.
  kRePrepRequired,  // Delta too large; caller must discard preview and
                    // re-prepare with a fresh origin.
};

class INormalizer {
 public:
  virtual ~INormalizer() = default;

  // The channel canonical parameters this Normalizer is producing to.
  virtual const ChannelCanonical& Canonical() const = 0;

  // The current channel origin.
  virtual const ChannelOrigin& Origin() const = 0;

  // Pull the next channel-canonical video frame, translated from the
  // upstream SourceProducer. Returns nullopt when no frame is currently
  // producible (producer stalled, rate-mismatch waiting for source
  // advance, or source exhausted).
  virtual std::optional<VideoFrame> PullVideo() = 0;

  // Pull the next channel-canonical audio block.
  virtual std::optional<AudioBlock> PullAudio() = 0;

  // Attempt a re-anchor to a new channel_pts_anchor_us. Returns the tier
  // the request fell into. If kAdjusted, the new anchor has taken effect.
  // If kRePrepRequired, the caller must invalidate its preview and
  // reconstruct this Normalizer with a fresh origin.
  virtual ReanchorTier Reanchor(int64_t new_channel_pts_anchor_us) = 0;

  // Threshold below which a re-anchor is a no-op. Expressed as absolute
  // microseconds delta from current anchor.
  virtual int64_t ReanchorNoopThresholdUs() const = 0;

  // Threshold below which a re-anchor is adjust; at or above, re-prep.
  virtual int64_t ReanchorRePrepThresholdUs() const = 0;
};

}  // namespace retrovue::air

#endif  // RETROVUE_AIR_NORMALIZER_HPP_
