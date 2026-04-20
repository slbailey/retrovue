// AIR vNext — MpegTsEncoder.
//
// Minimal MPEG-TS encoder that accepts channel-canonical VideoFrame /
// AudioBlock (YUV420P + S16 interleaved) and emits an MPEG-TS byte stream
// via a caller-supplied BytesOutCallback.
//
// Internals are hidden behind a PIMPL so this header does not leak libav
// types. Implementation lives in src/mpeg_ts_encoder.cpp.
//
// Design lineage: minimal transplant of runtime's EncoderPipeline with
// SwsContext / silence injection / egress pacing / NVENC / producer-CT-
// authoritative / packet-capture-callback paths dropped. Input is already
// channel-canonical so no conversion is needed; silence is handled upstream
// by PadSourceProducer. Audio PTS is derived from an internal sample
// counter per INV-AUDIO-SAMPLE-CLOCK.

#ifndef AIR_MPEG_TS_ENCODER_HPP_
#define AIR_MPEG_TS_ENCODER_HPP_

#include <cstdint>
#include <functional>
#include <memory>

#include "frame_types.hpp"

namespace retrovue::air {

struct MpegTsEncoderConfig {
  // Video
  int video_width;
  int video_height;
  int video_fps_num;
  int video_fps_den;
  int video_bitrate_bps;   // e.g. 4'000'000 = 4 Mbps
  // Audio
  int audio_sample_rate;   // e.g. 48000
  int audio_channels;      // e.g. 2
  int audio_bitrate_bps;   // e.g. 192'000 = 192 kbps
};

// Byte-out callback. Must always return buf_size (never block, never partial
// write). Called from the encoder thread when MPEG-TS bytes are ready.
using BytesOutCallback = std::function<int(const uint8_t* buf, int buf_size)>;

class MpegTsEncoder {
 public:
  MpegTsEncoder();
  ~MpegTsEncoder();
  MpegTsEncoder(const MpegTsEncoder&) = delete;
  MpegTsEncoder& operator=(const MpegTsEncoder&) = delete;

  // Open codec + muxer + custom AVIO with the given byte-out callback.
  // Returns true on success. config must be populated; callback must be
  // non-null.
  bool Open(const MpegTsEncoderConfig& config, BytesOutCallback bytes_out);

  // Encode one video frame. frame.data must be YUV420P channel-canonical
  // bytes (Y plane w*h + U plane (w/2)*(h/2) + V plane (w/2)*(h/2)).
  // frame.pts_us_relative is converted to 90kHz via the channel fps.
  bool EncodeVideo(const VideoFrame& frame);

  // Encode one audio block. block.data must be interleaved S16 at channel
  // sample_rate. PTS is derived internally from a sample counter (caller's
  // pts_us_relative is observability only, per runtime INV-AUDIO-SAMPLE-CLOCK).
  bool EncodeAudio(const AudioBlock& block);

  // Flush encoders + interleaver, write trailer. Call once at end.
  void Flush();

  // Release all resources. Safe to call multiple times. Called by dtor.
  void Close();

  bool IsOpen() const;

 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace retrovue::air

#endif  // AIR_MPEG_TS_ENCODER_HPP_
