// Repository: Retrovue-playout
// Component: Encoder Pipeline
// Purpose: Owns FFmpeg encoder/muxer handles and manages encoding lifecycle.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_PLAYOUT_SINKS_MPEGTS_ENCODER_PIPELINE_HPP_
#define RETROVUE_PLAYOUT_SINKS_MPEGTS_ENCODER_PIPELINE_HPP_

#include "retrovue/playout_sinks/mpegts/MpegTSPlayoutSinkConfig.hpp"

#include <cstdint>
#include <memory>
#include <vector>
#include <functional>

#ifdef RETROVUE_FFMPEG_AVAILABLE
extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/imgutils.h>
#include <libswscale/swscale.h>
#include <libswresample/swresample.h>
}
#endif

namespace retrovue::buffer {
struct Frame;
struct AudioFrame;
}  // namespace retrovue::buffer

namespace retrovue::playout_sinks::mpegts {

// EncoderPipeline owns FFmpeg encoder and muxer handles.
// It initializes the encoder in open(), encodes frames via encodeFrame(),
// and closes the muxer on close().
class EncoderPipeline {
 public:
  explicit EncoderPipeline(const MpegTSPlayoutSinkConfig& config);
  virtual ~EncoderPipeline();

  // Disable copy and move
  EncoderPipeline(const EncoderPipeline&) = delete;
  EncoderPipeline& operator=(const EncoderPipeline&) = delete;
  EncoderPipeline(EncoderPipeline&&) = delete;
  EncoderPipeline& operator=(EncoderPipeline&&) = delete;

  // Initialize encoder and muxer.
  // Must be called before encoding frames.
  // Returns true on success, false on failure.
  virtual bool open(const MpegTSPlayoutSinkConfig& config);
  
  // Initialize encoder and muxer with C-style write callback (for nonblocking mode)
  // opaque: Opaque pointer passed to write_callback
  // write_callback: C-style callback for writing encoded packets
  //   Callback signature: int write_callback(void* opaque, uint8_t* buf, int buf_size)
  //   Must always return buf_size (never block, never return < buf_size)
  virtual bool open(const MpegTSPlayoutSinkConfig& config, 
            void* opaque,
            int (*write_callback)(void* opaque, uint8_t* buf, int buf_size));

  // Encode a frame and mux into MPEG-TS.
  // frame: Decoded frame to encode
  // pts90k: Presentation timestamp in 90kHz units
  // Returns true on success, false on failure (non-fatal errors may be logged and continue)
  virtual bool encodeFrame(const retrovue::buffer::Frame& frame, int64_t pts90k);

  // Phase 8.9: Encode an audio frame and mux into MPEG-TS.
  // audio_frame: Decoded audio frame to encode
  // pts90k: Presentation timestamp in 90kHz units (producer-relative, rescaled by caller)
  // Returns true on success, false on failure (non-fatal errors may be logged and continue)
  virtual bool encodeAudioFrame(const retrovue::buffer::AudioFrame& audio_frame, int64_t pts90k);

  // Phase 8.9: Flush all buffered audio samples (resampler delay, partial frames, encoded packets).
  // This ensures all audio from the current producer is encoded and muxed before switching.
  // Returns true if flush completed successfully, false on error.
  virtual bool flushAudio();

  // Close muxer and encoder, releasing all resources.
  // Safe to call multiple times.
  virtual void close();

  // Check if encoder is initialized and ready.
  virtual bool IsInitialized() const;

 private:
#ifdef RETROVUE_FFMPEG_AVAILABLE
  // FFmpeg encoder context
  AVCodecContext* codec_ctx_;
  
  // FFmpeg muxer context
  AVFormatContext* format_ctx_;
  
  // Video stream in muxer
  AVStream* video_stream_;
  
  // Phase 8.9: Audio encoder and stream
  AVCodecContext* audio_codec_ctx_;
  AVStream* audio_stream_;
  AVFrame* audio_frame_;
  
  // Encoder frame (reused for each frame)
  AVFrame* frame_;
  
  // Input frame buffer (for pixel format conversion)
  AVFrame* input_frame_;
  
  // Packet buffer (reused for each encoded packet)
  AVPacket* packet_;
  
  // Swscale context for format conversion
  SwsContext* sws_ctx_;
  
  // Phase 8.9: Swresample context for audio sample rate conversion
  struct SwrContext* swr_ctx_;
  int last_input_sample_rate_;  // Track input sample rate to detect changes
  
  // Phase 8.9: Buffer for partial audio frames after resampling
  // AAC requires all frames (except last) to be exactly frame_size, so we buffer
  // any remainder from resampling and prepend it to the next input frame.
  std::vector<int16_t> audio_resample_buffer_;  // S16 interleaved samples
  int audio_resample_buffer_samples_;  // Number of samples currently buffered
  
  // Track last PTS to detect producer switches (for PTS continuity and flush timing)
  int64_t last_seen_audio_pts90k_;  // Last INCOMING PTS we saw (to detect backward jumps)
  int64_t audio_pts_offset_90k_;    // Offset to add to incoming PTS for muxer continuity
  
  // Frame dimensions
  int frame_width_;
  int frame_height_;
  
  // Input pixel format (defaults to YUV420P)
  AVPixelFormat input_pix_fmt_;
  
  // Flag to track if swscale context needs to be recreated
  bool sws_ctx_valid_;
  
  // Time base for video stream (1/90000 for MPEG-TS)
  AVRational time_base_;
  
  // Flag to track if header has been written
  bool header_written_;

  // True only after avcodec_open2 succeeds; avoid flush in close() when codec never opened.
  bool codec_opened_;
  
  // Muxer options for PCR cadence configuration (FE-019)
  AVDictionary* muxer_opts_;
  
  // Enforce strictly increasing DTS for mpegts muxer (and PTS for codec input)
  int64_t last_mux_dts_;
  int64_t last_input_pts_;

  // Ensure packet DTS (and PTS) are strictly increasing before av_interleaved_write_frame; update last_mux_dts_.
  void EnforceMonotonicDts();

  // Custom AVIO write callback (for nonblocking mode)
  void* avio_opaque_;
  int (*avio_write_callback_)(void* opaque, uint8_t* buf, int buf_size);
  AVIOContext* custom_avio_ctx_;

  static int AVIOWriteThunk(void* opaque, uint8_t* buf, int buf_size);
  int HandleAVIOWrite(uint8_t* buf, int buf_size);
#endif

  MpegTSPlayoutSinkConfig config_;
  bool initialized_;
};

}  // namespace retrovue::playout_sinks::mpegts

#endif  // RETROVUE_PLAYOUT_SINKS_MPEGTS_ENCODER_PIPELINE_HPP_

