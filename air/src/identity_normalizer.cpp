// AIR vNext — IdentityNormalizer implementation.

#include "identity_normalizer.hpp"

#include <cstdlib>

namespace retrovue::air {

namespace {

// Re-anchor thresholds.
//
// Noop threshold: one video frame period. Deltas smaller than this are
// cosmetic — below output resolution — and applying them would just shift
// jitter without observable benefit.
//
// Re-prep threshold: one second. Above this, the preview is far enough out
// of date that rebuilding is cheaper (or at least clearer) than rewriting
// origin-relative PTS. Below this, origin adjustment is a single scalar.
constexpr int64_t kReanchorRePrepUs = 1'000'000;

}  // namespace

IdentityNormalizer::IdentityNormalizer(ChannelCanonical canonical,
                                       ISourceProducer* source,
                                       ChannelOrigin origin)
    : canonical_(canonical),
      source_(source),
      origin_(origin),
      reanchor_noop_threshold_us_(canonical.video.frame_rate.PeriodMicros()),
      reanchor_re_prep_threshold_us_(kReanchorRePrepUs) {}

std::optional<VideoFrame> IdentityNormalizer::PullVideo() {
  auto src = source_->PullVideo();
  if (!src.has_value()) return std::nullopt;

  // Identity transform: pass payload through. Compute channel-time PTS
  // from the Normalizer's OWN channel frame index via the canonical
  // round-to-nearest formula — NOT by forwarding source PTS. Source PTS
  // survives as opaque metadata only.
  //
  // "Identity" here means format + rate pass-through (no resolution or
  // rate conversion). PTS is still derived on the channel side; this
  // satisfies INV-NORMALIZER-OUTPUT-CHANNEL-TIME-001 even if the source
  // has PTS jitter or discontinuities.
  VideoFrame out;
  out.pts_us_relative =
      canonical_.video.frame_rate.NthStepPtsUs(next_channel_video_frame_index_);
  out.source_pts_us_opaque = src->source_pts_us;
  out.data = std::move(src->data);
  ++next_channel_video_frame_index_;
  return out;
}

std::optional<AudioBlock> IdentityNormalizer::PullAudio() {
  auto src = source_->PullAudio();
  if (!src.has_value()) return std::nullopt;

  // Channel-time PTS of this block's first sample, derived from the
  // cumulative channel sample index (NOT from source PTS). Same formula
  // StandardNormalizer uses for ChannelSampleStartPtsUs.
  const int64_t rate = canonical_.audio.sample_rate;
  const int64_t start_sample = next_channel_audio_sample_index_;

  AudioBlock out;
  out.pts_us_relative =
      (start_sample * int64_t{1'000'000} + rate / 2) / rate;
  out.source_pts_us_opaque = src->source_pts_us;
  out.nb_samples = src->nb_samples;
  out.data = std::move(src->data);
  next_channel_audio_sample_index_ += src->nb_samples;
  return out;
}

ReanchorTier IdentityNormalizer::Reanchor(int64_t new_channel_pts_anchor_us) {
  const int64_t delta =
      std::abs(new_channel_pts_anchor_us - origin_.channel_pts_anchor_us);

  if (delta < reanchor_noop_threshold_us_) {
    return ReanchorTier::kNoop;
  }
  if (delta < reanchor_re_prep_threshold_us_) {
    origin_.channel_pts_anchor_us = new_channel_pts_anchor_us;
    return ReanchorTier::kAdjusted;
  }
  // Caller handles re-prep; we do not mutate origin here because re-prep
  // semantics require a clean reconstruction with a fresh origin value,
  // which is the caller's responsibility.
  return ReanchorTier::kRePrepRequired;
}

int64_t IdentityNormalizer::ReanchorNoopThresholdUs() const {
  return reanchor_noop_threshold_us_;
}

int64_t IdentityNormalizer::ReanchorRePrepThresholdUs() const {
  return reanchor_re_prep_threshold_us_;
}

}  // namespace retrovue::air
