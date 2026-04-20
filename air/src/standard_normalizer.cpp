// AIR vNext — StandardNormalizer implementation.

#include "standard_normalizer.hpp"

extern "C" {
#include <libavutil/pixfmt.h>
#include <libswscale/swscale.h>
}

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstring>

namespace retrovue::air {

namespace {

constexpr int64_t kReanchorRePrepUs = 1'000'000;  // 1 second

// Broadcast-safe black fill values for YUV420P padding (letterbox /
// pillarbox bars). Matches PadSourceProducer.
constexpr uint8_t kBroadcastBlackY = 0x10;
constexpr uint8_t kNeutralChromaUV = 0x80;

// Compute aspect-preserving fit-to-contain layout for scaling src into
// dst. Output scaled dimensions fit entirely within dst; remaining area
// is letterbox (top/bottom) or pillarbox (left/right). All output values
// are even (YUV420P chroma alignment). pad offsets are also even.
void ComputeFitLayout(int src_w, int src_h, int dst_w, int dst_h,
                     int* scaled_w, int* scaled_h,
                     int* pad_x, int* pad_y) {
  // Which dimension is limiting? The smaller of dst_w/src_w and dst_h/src_h.
  // Cross-multiply to avoid floats:
  //   dst_w/src_w <= dst_h/src_h iff dst_w*src_h <= dst_h*src_w
  const int64_t dw_sh = static_cast<int64_t>(dst_w) * src_h;
  const int64_t dh_sw = static_cast<int64_t>(dst_h) * src_w;
  if (dw_sh <= dh_sw) {
    // Width is limiting (source is wider than channel or same aspect).
    *scaled_w = dst_w;
    *scaled_h = static_cast<int>(
        (static_cast<int64_t>(src_h) * dst_w + src_w / 2) / src_w);
  } else {
    // Height is limiting.
    *scaled_h = dst_h;
    *scaled_w = static_cast<int>(
        (static_cast<int64_t>(src_w) * dst_h + src_h / 2) / src_h);
  }
  // Round scaled dims down to even (YUV420P).
  *scaled_w -= (*scaled_w & 1);
  *scaled_h -= (*scaled_h & 1);
  // Compute pad. If pad is odd, shrink scaled dim by 2 to keep pad even
  // (required for YUV420P chroma offset).
  *pad_x = (dst_w - *scaled_w) / 2;
  *pad_y = (dst_h - *scaled_h) / 2;
  if (*pad_x & 1) { *scaled_w -= 2; *pad_x = (dst_w - *scaled_w) / 2; }
  if (*pad_y & 1) { *scaled_h -= 2; *pad_y = (dst_h - *scaled_h) / 2; }
}

}  // namespace

StandardNormalizer::StandardNormalizer(ChannelCanonical canonical,
                                       Rational source_video_frame_rate,
                                       int source_video_width,
                                       int source_video_height,
                                       int source_audio_sample_rate,
                                       ISourceProducer* source,
                                       ChannelOrigin origin,
                                       int samples_per_channel_audio_block)
    : canonical_(canonical),
      source_video_rate_(source_video_frame_rate),
      source_video_width_(source_video_width),
      source_video_height_(source_video_height),
      source_audio_rate_(source_audio_sample_rate),
      source_(source),
      origin_(origin),
      samples_per_channel_audio_block_(samples_per_channel_audio_block),
      reanchor_noop_threshold_us_(canonical.video.frame_rate.PeriodMicros()),
      reanchor_re_prep_threshold_us_(kReanchorRePrepUs) {
  // Allocate swscale context iff source dimensions differ from channel.
  // Both sides are YUV420P (FileSourceProducer requires it; channel is
  // YUV420P per the pixel format enum currently).
  //
  // Aspect preservation: swscale targets an intermediate (scaled_w_,
  // scaled_h_) that fits inside channel dims while preserving source
  // aspect ratio. PullVideo then composes this intermediate into a
  // broadcast-black channel-canonical frame, producing letterbox
  // (top/bottom bars) or pillarbox (left/right bars) as required.
  if (source_video_width_ != canonical_.video.width ||
      source_video_height_ != canonical_.video.height) {
    ComputeFitLayout(source_video_width_, source_video_height_,
                    canonical_.video.width, canonical_.video.height,
                    &scaled_w_, &scaled_h_, &pad_x_, &pad_y_);
    sws_ctx_ = sws_getContext(
        source_video_width_, source_video_height_, AV_PIX_FMT_YUV420P,
        scaled_w_, scaled_h_, AV_PIX_FMT_YUV420P,
        SWS_BILINEAR, nullptr, nullptr, nullptr);
    // Pre-allocate intermediate YUV420P buffer at scaled dims.
    const int y_sz = scaled_w_ * scaled_h_;
    const int uv_sz = (scaled_w_ / 2) * (scaled_h_ / 2);
    scaled_buffer_.assign(static_cast<size_t>(y_sz + 2 * uv_sz), 0);
    // sws_ctx_ can be null on allocation failure; PullVideo handles that
    // by passing through (which will produce wrong-sized output — caller
    // will observe via depth/size mismatch, surfacing the error).
  }
}

StandardNormalizer::~StandardNormalizer() {
  if (sws_ctx_) {
    sws_freeContext(sws_ctx_);
    sws_ctx_ = nullptr;
  }
}

int64_t StandardNormalizer::SourceFrameIndexForChannelFrame(int64_t k) const {
  // source_frame_idx = floor(k * source_num * channel_den
  //                          / (channel_num * source_den))
  const int64_t num = k * source_video_rate_.num *
                      canonical_.video.frame_rate.den;
  const int64_t den = canonical_.video.frame_rate.num *
                      source_video_rate_.den;
  return num / den;
}

int64_t StandardNormalizer::ChannelFrameStartPtsUs(int64_t k) const {
  return canonical_.video.frame_rate.NthStepPtsUs(k);
}

int64_t StandardNormalizer::ChannelSampleStartPtsUs(int64_t n) const {
  const int64_t rate = canonical_.audio.sample_rate;
  return (n * 1'000'000 + rate / 2) / rate;
}

std::optional<VideoFrame> StandardNormalizer::PullVideo() {
  const int64_t target_src_idx =
      SourceFrameIndexForChannelFrame(next_channel_video_frame_index_);

  // Pull source frames until our buffer covers target_src_idx.
  while (source_video_buffer_first_index_ +
             static_cast<int64_t>(source_video_buffer_.size()) <=
         target_src_idx) {
    auto src = source_->PullVideo();
    if (!src.has_value()) return std::nullopt;
    source_video_buffer_.push_back(std::move(*src));
  }

  // Prune source frames we will never need again. Cadence is monotonic
  // non-decreasing in k, so anything below target is safe to discard.
  while (source_video_buffer_first_index_ < target_src_idx &&
         !source_video_buffer_.empty()) {
    source_video_buffer_.pop_front();
    ++source_video_buffer_first_index_;
  }

  const SourceVideoFrame& src_frame = source_video_buffer_.front();

  VideoFrame out;
  out.pts_us_relative =
      ChannelFrameStartPtsUs(next_channel_video_frame_index_);
  out.source_pts_us_opaque = src_frame.source_pts_us;

  if (sws_ctx_ == nullptr) {
    // Source dims == channel dims: passthrough copy.
    out.data = src_frame.data;
  } else {
    // Aspect-preserving scale + letterbox/pillarbox compose.
    // 1. swscale source -> intermediate buffer at (scaled_w_, scaled_h_).
    // 2. Allocate final dst at channel dims, pre-filled with broadcast
    //    black (Y=0x10, U/V=0x80).
    // 3. Copy intermediate into dst at (pad_x_, pad_y_).
    const int src_w = source_video_width_;
    const int src_h = source_video_height_;
    const int src_y_sz = src_w * src_h;
    const int src_uv_sz = (src_w / 2) * (src_h / 2);

    const uint8_t* src_planes[4] = {
        src_frame.data.data(),
        src_frame.data.data() + src_y_sz,
        src_frame.data.data() + src_y_sz + src_uv_sz,
        nullptr,
    };
    const int src_strides[4] = {src_w, src_w / 2, src_w / 2, 0};

    // Intermediate planes (reusable member buffer).
    const int mid_y_sz = scaled_w_ * scaled_h_;
    const int mid_uv_sz = (scaled_w_ / 2) * (scaled_h_ / 2);
    uint8_t* mid_y = scaled_buffer_.data();
    uint8_t* mid_u = mid_y + mid_y_sz;
    uint8_t* mid_v = mid_u + mid_uv_sz;
    uint8_t* mid_planes[4] = {mid_y, mid_u, mid_v, nullptr};
    const int mid_strides[4] = {scaled_w_, scaled_w_ / 2, scaled_w_ / 2, 0};

    sws_scale(sws_ctx_, src_planes, src_strides, 0, src_h,
              mid_planes, mid_strides);

    // Channel-canonical dst buffer, pre-filled with broadcast black.
    const int dst_w = canonical_.video.width;
    const int dst_h = canonical_.video.height;
    const int dst_y_sz = dst_w * dst_h;
    const int dst_uv_w = dst_w / 2;
    const int dst_uv_h = dst_h / 2;
    const int dst_uv_sz = dst_uv_w * dst_uv_h;
    out.data.resize(static_cast<size_t>(dst_y_sz + 2 * dst_uv_sz));
    uint8_t* dst_y = out.data.data();
    uint8_t* dst_u = dst_y + dst_y_sz;
    uint8_t* dst_v = dst_u + dst_uv_sz;
    std::memset(dst_y, kBroadcastBlackY, static_cast<size_t>(dst_y_sz));
    std::memset(dst_u, kNeutralChromaUV, static_cast<size_t>(dst_uv_sz));
    std::memset(dst_v, kNeutralChromaUV, static_cast<size_t>(dst_uv_sz));

    // Compose: copy intermediate Y into dst Y at (pad_x_, pad_y_).
    for (int y = 0; y < scaled_h_; ++y) {
      std::memcpy(dst_y + (pad_y_ + y) * dst_w + pad_x_,
                  mid_y + y * scaled_w_,
                  static_cast<size_t>(scaled_w_));
    }
    // Compose U/V (half-res, starting at pad_*_/2 for chroma alignment).
    const int pad_x_uv = pad_x_ / 2;
    const int pad_y_uv = pad_y_ / 2;
    const int scaled_uv_w = scaled_w_ / 2;
    const int scaled_uv_h = scaled_h_ / 2;
    for (int y = 0; y < scaled_uv_h; ++y) {
      std::memcpy(dst_u + (pad_y_uv + y) * dst_uv_w + pad_x_uv,
                  mid_u + y * scaled_uv_w,
                  static_cast<size_t>(scaled_uv_w));
      std::memcpy(dst_v + (pad_y_uv + y) * dst_uv_w + pad_x_uv,
                  mid_v + y * scaled_uv_w,
                  static_cast<size_t>(scaled_uv_w));
    }
  }

  ++next_channel_video_frame_index_;
  return out;
}

std::optional<AudioBlock> StandardNormalizer::PullAudio() {
  const int64_t start_sample = next_channel_audio_sample_index_;
  const int64_t end_sample = start_sample + samples_per_channel_audio_block_;

  // Worst-case source sample index needed for interpolation: the sample
  // immediately after the floor of (end_sample - 1) * src/ch.
  const auto src_sample_for_ch = [this](int64_t n) {
    // Exact index: n * src / ch. Rational arithmetic: (n * src) / ch.
    // Floor: (n * src) / ch using integer division for non-negative.
    const int64_t src = source_audio_rate_;
    const int64_t ch = canonical_.audio.sample_rate;
    return (n * src) / ch;
  };

  const int64_t max_src_needed = src_sample_for_ch(end_sample - 1) + 1;

  const int channels = canonical_.audio.channels;
  // Pull source audio blocks until the interleaved buffer contains enough
  // samples to cover [0, max_src_needed].
  while (source_audio_first_sample_index_ +
             static_cast<int64_t>(source_audio_interleaved_.size() / channels) <=
         max_src_needed) {
    auto src = source_->PullAudio();
    if (!src.has_value()) return std::nullopt;
    for (int16_t s : src->data) {
      source_audio_interleaved_.push_back(s);
    }
  }

  AudioBlock out;
  out.pts_us_relative = ChannelSampleStartPtsUs(start_sample);
  out.nb_samples = samples_per_channel_audio_block_;
  out.data.resize(static_cast<size_t>(samples_per_channel_audio_block_) *
                  static_cast<size_t>(channels));

  // Interpolate each channel sample.
  const double src_rate_d = static_cast<double>(source_audio_rate_);
  const double ch_rate_d = static_cast<double>(canonical_.audio.sample_rate);
  const double ratio = src_rate_d / ch_rate_d;

  // For capturing any "first" source PTS observation on this block.
  out.source_pts_us_opaque = kSourcePtsUnknown;

  for (int64_t n = start_sample; n < end_sample; ++n) {
    const double exact = static_cast<double>(n) * ratio;
    const int64_t floor_idx = static_cast<int64_t>(std::floor(exact));
    const double frac = exact - static_cast<double>(floor_idx);

    const int64_t buf_floor = floor_idx - source_audio_first_sample_index_;
    const int64_t buf_ceil = buf_floor + 1;

    for (int c = 0; c < channels; ++c) {
      const int16_t s0 = source_audio_interleaved_[
          static_cast<size_t>(buf_floor * channels + c)];
      const int16_t s1 = source_audio_interleaved_[
          static_cast<size_t>(buf_ceil * channels + c)];
      const double interp =
          (1.0 - frac) * static_cast<double>(s0) +
          frac * static_cast<double>(s1);
      out.data[static_cast<size_t>((n - start_sample) * channels + c)] =
          static_cast<int16_t>(std::lround(interp));
    }
  }

  // Prune source samples below what the next block will need (keep at
  // least one sample before the next block's first source-sample for
  // interpolation).
  const int64_t next_block_first_src = src_sample_for_ch(end_sample);
  const int64_t prune_until = std::max<int64_t>(0, next_block_first_src - 1);

  while (source_audio_first_sample_index_ < prune_until &&
         source_audio_interleaved_.size() >=
             static_cast<size_t>(channels)) {
    for (int c = 0; c < channels; ++c) {
      source_audio_interleaved_.pop_front();
    }
    ++source_audio_first_sample_index_;
  }

  next_channel_audio_sample_index_ = end_sample;
  return out;
}

ReanchorTier StandardNormalizer::Reanchor(int64_t new_channel_pts_anchor_us) {
  const int64_t delta =
      std::abs(new_channel_pts_anchor_us - origin_.channel_pts_anchor_us);

  if (delta < reanchor_noop_threshold_us_) {
    return ReanchorTier::kNoop;
  }
  if (delta < reanchor_re_prep_threshold_us_) {
    origin_.channel_pts_anchor_us = new_channel_pts_anchor_us;
    return ReanchorTier::kAdjusted;
  }
  return ReanchorTier::kRePrepRequired;
}

}  // namespace retrovue::air
