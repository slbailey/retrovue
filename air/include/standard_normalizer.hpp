// AIR vNext — StandardNormalizer.
//
// Non-identity Normalizer that performs:
//   - Video cadence resample: integer rate ratios via frame repeat / drop,
//     non-integer ratios via the pattern-based formula
//         source_frame_idx(k) = floor(k * source_num * channel_den /
//                                      (channel_num * source_den))
//     which naturally produces 4:5 pulldown for 24->30, 1:2 decimation for
//     60->30, identity for 30->30, etc.
//   - Audio sample-rate conversion via linear interpolation between source
//     samples. First-cut quality (linear); production quality (polyphase /
//     libsamplerate) is a later knob.
//   - Shared channel origin across audio and video sub-normalizers. This
//     preserves A/V sync across independent rate conversions.
//
// Channel-time PTS on output:
//   - Video: pts_us_relative = round(k * 1_000_000 * ch_den / ch_num).
//   - Audio: pts_us_relative of first sample = round(n * 1_000_000 /
//            ch_audio_rate), where n is the channel sample index.
//
// Source PTS is tagged on output frames as opaque metadata (observability
// only). Downstream components MUST NOT consume it as a decision input.

#ifndef AIR_STANDARD_NORMALIZER_HPP_
#define AIR_STANDARD_NORMALIZER_HPP_

#include <cstdint>
#include <deque>
#include <optional>
#include <vector>

#include "channel_canonical.hpp"
#include "frame_types.hpp"
#include "normalizer.hpp"
#include "source_producer.hpp"

// Forward-declare libswscale's context so callers don't need ffmpeg headers.
struct SwsContext;

namespace retrovue::air {

class StandardNormalizer : public INormalizer {
 public:
  // Construct with:
  //   - Channel canonical parameters (immutable for normalizer's lifetime).
  //   - Source video frame rate (source producer's native video rate).
  //   - Source video dimensions. If different from channel dimensions,
  //     the normalizer configures swscale to rescale each source frame
  //     to channel resolution on PullVideo. Assumes YUV420P for both
  //     source and channel pixel format (future: add format conversion).
  //   - Source audio sample rate (source producer's native audio rate).
  //   - Borrowed source pointer (normalizer does not own).
  //   - Initial channel origin.
  //   - Samples per channel audio block (number of channel samples per
  //     PullAudio() call). Typical value = channel_sample_rate / ch_fps.
  StandardNormalizer(ChannelCanonical canonical,
                     Rational source_video_frame_rate,
                     int source_video_width,
                     int source_video_height,
                     int source_audio_sample_rate,
                     ISourceProducer* source,
                     ChannelOrigin origin,
                     int samples_per_channel_audio_block);

  ~StandardNormalizer();
  StandardNormalizer(const StandardNormalizer&) = delete;
  StandardNormalizer& operator=(const StandardNormalizer&) = delete;

  const ChannelCanonical& Canonical() const override { return canonical_; }
  const ChannelOrigin& Origin() const override { return origin_; }

  std::optional<VideoFrame> PullVideo() override;
  std::optional<AudioBlock> PullAudio() override;

  ReanchorTier Reanchor(int64_t new_channel_pts_anchor_us) override;

  int64_t ReanchorNoopThresholdUs() const override {
    return reanchor_noop_threshold_us_;
  }
  int64_t ReanchorRePrepThresholdUs() const override {
    return reanchor_re_prep_threshold_us_;
  }

  // Inspection.
  int64_t NextChannelVideoFrameIndex() const {
    return next_channel_video_frame_index_;
  }
  int64_t NextChannelAudioSampleIndex() const {
    return next_channel_audio_sample_index_;
  }

 private:
  // Source video frame index needed for channel frame k.
  int64_t SourceFrameIndexForChannelFrame(int64_t k) const;

  // Channel-time PTS helpers (rounded integer microseconds).
  int64_t ChannelFrameStartPtsUs(int64_t k) const;
  int64_t ChannelSampleStartPtsUs(int64_t n) const;

  ChannelCanonical canonical_;
  Rational source_video_rate_;
  int source_video_width_;
  int source_video_height_;
  int source_audio_rate_;
  ISourceProducer* source_;
  ChannelOrigin origin_;
  int samples_per_channel_audio_block_;

  int64_t reanchor_noop_threshold_us_;
  int64_t reanchor_re_prep_threshold_us_;

  // libswscale context. Null when source dims == channel dims
  // (passthrough). Allocated in ctor if scaling is needed, freed in dtor.
  // When active, scales source to (scaled_w_, scaled_h_) — which may be
  // smaller than channel dims — preserving aspect ratio. The result is
  // then composited into a black-filled channel-canonical frame at
  // (pad_x_, pad_y_), producing letterbox/pillarbox as needed.
  SwsContext* sws_ctx_ = nullptr;
  int scaled_w_ = 0;
  int scaled_h_ = 0;
  int pad_x_ = 0;
  int pad_y_ = 0;
  // Reusable intermediate YUV420P buffer at scaled_w_ x scaled_h_.
  std::vector<uint8_t> scaled_buffer_;

  // Video buffering state.
  std::deque<SourceVideoFrame> source_video_buffer_;
  int64_t source_video_buffer_first_index_ = 0;
  int64_t next_channel_video_frame_index_ = 0;

  // Audio buffering state. Samples stored interleaved (all channels packed).
  std::deque<int16_t> source_audio_interleaved_;
  int64_t source_audio_first_sample_index_ = 0;
  int64_t next_channel_audio_sample_index_ = 0;
};

}  // namespace retrovue::air

#endif  // AIR_STANDARD_NORMALIZER_HPP_
