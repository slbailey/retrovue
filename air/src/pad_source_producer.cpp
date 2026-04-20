// AIR vNext — PadSourceProducer implementation.
//
// See pad_source_producer.hpp for contract notes.

#include "pad_source_producer.hpp"

#include <algorithm>
#include <cstring>

namespace retrovue::air {

namespace {

constexpr uint8_t kBroadcastBlackY = 0x10;
constexpr uint8_t kNeutralChromaUV = 0x80;

// Compute worst-case samples per video-frame-period across standard
// framerates, sized from the declared channel rate. The pad producer
// pre-allocates a buffer that fits this size so per-pull emits are zero-alloc.
// We cap at a minimum that handles the slowest common framerate (23.976).
int ComputeAudioSamplesPerBlock(const AudioCanonical& audio,
                                const Rational& fps) {
  // samples_per_frame = sample_rate / fps = sample_rate * fps_den / fps_num
  // (rounded up for worst-case allocation).
  const int64_t sr = audio.sample_rate;
  const int64_t computed =
      (sr * fps.den + fps.num - 1) / fps.num;
  const int minimum = 2002;  // Safe floor for 23.976fps at 48kHz.
  return static_cast<int>(std::max<int64_t>(computed, minimum));
}

}  // namespace

PadSourceProducer::PadSourceProducer(ChannelCanonical canonical)
    : canonical_(canonical),
      audio_samples_per_block_(
          ComputeAudioSamplesPerBlock(canonical.audio,
                                      canonical.video.frame_rate)) {
  // Video: YUV420P black. Y plane = w*h; U plane = (w/2)*(h/2);
  // V plane = (w/2)*(h/2). Total = w*h * 3/2.
  const int w = canonical_.video.width;
  const int h = canonical_.video.height;
  const int y_size = w * h;
  const int uv_size = (w / 2) * (h / 2);
  pad_video_data_.assign(
      static_cast<size_t>(y_size + 2 * uv_size), 0);
  std::memset(pad_video_data_.data(), kBroadcastBlackY,
              static_cast<size_t>(y_size));
  std::memset(pad_video_data_.data() + y_size, kNeutralChromaUV,
              static_cast<size_t>(2 * uv_size));

  // Audio: silence PCM int16, interleaved.
  pad_audio_data_.assign(
      static_cast<size_t>(audio_samples_per_block_) *
          static_cast<size_t>(canonical_.audio.channels),
      0);
}

bool PadSourceProducer::Prepare() {
  if (lifecycle_ != ProducerLifecycle::kConstructed) return false;
  lifecycle_ = ProducerLifecycle::kPrepared;
  return true;
}

bool PadSourceProducer::Activate() {
  if (lifecycle_ != ProducerLifecycle::kPrepared) return false;
  lifecycle_ = ProducerLifecycle::kActivated;
  return true;
}

void PadSourceProducer::Retire() {
  lifecycle_ = ProducerLifecycle::kRetired;
  // Payload buffers remain allocated until destruction; no per-pull alloc
  // and no need to free early.
}

std::optional<SourceVideoFrame> PadSourceProducer::PullVideo() {
  if (lifecycle_ != ProducerLifecycle::kActivated) return std::nullopt;

  SourceVideoFrame frame;
  frame.width = canonical_.video.width;
  frame.height = canonical_.video.height;
  // Source PTS via round-to-nearest from the frame emission index.
  // Matches StandardNormalizer's channel-time formula so cross-segment
  // continuity is exact.
  frame.source_pts_us =
      canonical_.video.frame_rate.NthStepPtsUs(video_frames_emitted_);
  frame.data = pad_video_data_;

  ++video_frames_emitted_;
  return frame;
}

std::optional<SourceAudioBlock> PadSourceProducer::PullAudio() {
  if (lifecycle_ != ProducerLifecycle::kActivated) return std::nullopt;

  SourceAudioBlock block;
  block.sample_rate = canonical_.audio.sample_rate;
  block.channels = canonical_.audio.channels;
  block.nb_samples = audio_samples_per_block_;
  // Source PTS of this block's first sample, via round-to-nearest from
  // the cumulative sample index. Drift-free over long sessions.
  const int64_t start_sample_index =
      audio_blocks_emitted_ * static_cast<int64_t>(audio_samples_per_block_);
  const int64_t rate = canonical_.audio.sample_rate;
  block.source_pts_us =
      (start_sample_index * int64_t{1'000'000} + rate / 2) / rate;
  block.data = pad_audio_data_;

  ++audio_blocks_emitted_;
  return block;
}

}  // namespace retrovue::air
