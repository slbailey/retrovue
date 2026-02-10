// Repository: Retrovue-playout
// Component: PadProducer
// Purpose: Session-lifetime pre-allocated pad frame source for the TAKE path.
//          Provides immutable black video and silence audio with zero per-tick
//          allocations.  PadProducer is NOT an ITickProducer — it is a data
//          source selected by the TAKE at the commitment point.
// Contract Reference: INV-PAD-PRODUCER
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_BLOCKPLAN_PAD_PRODUCER_HPP_
#define RETROVUE_BLOCKPLAN_PAD_PRODUCER_HPP_

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <vector>

#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/blockplan/SeamProofTypes.hpp"

namespace retrovue::blockplan {

class PadProducer {
 public:
  // Construct with session format.  Pre-allocates immutable video + audio.
  PadProducer(int width, int height, int64_t fps_num, int64_t fps_den)
      : max_samples_per_frame_(0), video_crc32_(0) {
    // --- Video: black YUV420P frame ---
    const int w = width;
    const int h = height;
    const int y_size = w * h;
    const int uv_size = (w / 2) * (h / 2);

    video_frame_.width = w;
    video_frame_.height = h;
    video_frame_.data.resize(static_cast<size_t>(y_size + 2 * uv_size));

    // Y = 0x10 (broadcast black), U/V = 0x80 (neutral chroma)
    std::memset(video_frame_.data.data(), 0x10,
                static_cast<size_t>(y_size));
    std::memset(video_frame_.data.data() + y_size, 0x80,
                static_cast<size_t>(2 * uv_size));

    // CRC32: compute once over Y plane (up to kFingerprintYBytes).
    size_t crc_len = std::min(static_cast<size_t>(y_size), kFingerprintYBytes);
    video_crc32_ = CRC32YPlane(video_frame_.data.data(), crc_len);

    // --- Audio: silence (all zeros) ---
    // Worst-case samples per frame across all standard FPS values.
    // 23.976fps (24000/1001): ceil(48000 * 1001 / 24000) = 2002 samples.
    // We compute from the actual fps_num/fps_den but cap at 2002 minimum.
    int64_t sr = static_cast<int64_t>(buffer::kHouseAudioSampleRate);
    int computed_max = static_cast<int>(
        (sr * fps_den + fps_num - 1) / fps_num);
    // Ensure at least 2002 to handle any standard FPS that might be used
    // during the session lifetime.
    max_samples_per_frame_ = std::max(computed_max, 2002);

    audio_template_.sample_rate = buffer::kHouseAudioSampleRate;
    audio_template_.channels = buffer::kHouseAudioChannels;
    audio_template_.nb_samples = max_samples_per_frame_;
    audio_template_.pts_us = 0;
    audio_template_.data.resize(
        static_cast<size_t>(max_samples_per_frame_) *
        static_cast<size_t>(buffer::kHouseAudioChannels) *
        sizeof(int16_t), 0);
  }

  // Pre-allocated black YUV420P frame (Y=16, U=V=128).  Immutable.
  const buffer::Frame& VideoFrame() const { return video_frame_; }

  // Pre-allocated max-sized silence buffer (all zeros).  Caller sets
  // nb_samples per tick; data is large enough for any tick at any
  // supported FPS (max = ceil(48000/23.976) = 2002 samples).
  // Returns mutable reference so caller can set nb_samples without copy.
  buffer::AudioFrame& SilenceTemplate() { return audio_template_; }

  // Max audio samples per frame across all supported FPS.
  int MaxSamplesPerFrame() const { return max_samples_per_frame_; }

  // CRC32 of the pre-allocated Y plane (computed once, cached).
  uint32_t VideoCRC32() const { return video_crc32_; }

  static constexpr const char* kAssetUri = "internal://pad";

 private:
  buffer::Frame video_frame_;           // Immutable after ctor
  buffer::AudioFrame audio_template_;   // Data immutable (all zeros); nb_samples mutable
  int max_samples_per_frame_;
  uint32_t video_crc32_;
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_PAD_PRODUCER_HPP_
