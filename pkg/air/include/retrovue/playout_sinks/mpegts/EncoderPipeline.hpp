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
}
#endif

namespace retrovue::buffer {
struct Frame;
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
  
  // Encoder frame (reused for each frame)
  AVFrame* frame_;
  
  // Input frame buffer (for pixel format conversion)
  AVFrame* input_frame_;
  
  // Packet buffer (reused for each encoded packet)
  AVPacket* packet_;
  
  // Swscale context for format conversion
  SwsContext* sws_ctx_;
  
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

