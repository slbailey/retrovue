// Repository: Retrovue-playout
// Component: Encoder Pipeline
// Purpose: Owns FFmpeg encoder/muxer handles and manages encoding lifecycle.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_PLAYOUT_SINKS_MPEGTS_ENCODER_PIPELINE_HPP_
#define RETROVUE_PLAYOUT_SINKS_MPEGTS_ENCODER_PIPELINE_HPP_

#include "retrovue/playout_sinks/mpegts/MpegTSPlayoutSinkConfig.hpp"

#include <chrono>
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
  // audio_frame: Decoded audio frame to encode (must be house format; INV-AUDIO-HOUSE-FORMAT-001).
  // pts90k: Presentation timestamp in 90kHz units (producer-relative, rescaled by caller).
  // is_silence_pad: If true, frame is pad/silence; same path/CT/cadence/format, but do not set real_audio_received_.
  // Returns true on success, false on failure (format mismatch is explicit failure).
  virtual bool encodeAudioFrame(const retrovue::buffer::AudioFrame& audio_frame, int64_t pts90k,
                               bool is_silence_pad = false);

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
  
  // Phase 8.9: Buffer for partial house-format audio frames (INV-AUDIO-HOUSE-FORMAT-001).
  // AAC requires all frames (except last) to be exactly frame_size; we buffer
  // remainder and prepend to the next input. No resampling — input must be house format.
  std::vector<int16_t> audio_resample_buffer_;  // S16 interleaved, house format
  int audio_resample_buffer_samples_;
  
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
  
  // OutputContinuity (per OutputContinuityContract.md): per-stream monotonic PTS/DTS.
  // Separate trackers for video and audio; minimal correction only.
  int64_t last_video_mux_dts_;
  int64_t last_video_mux_pts_;
  int64_t last_audio_mux_dts_;
  int64_t last_audio_mux_pts_;
  int64_t last_input_pts_;

  // Force first frame to be an I-frame (keyframe) to avoid initial stutter
  bool first_frame_encoded_;

  // =========================================================================
  // INV-AIR-IDR-BEFORE-OUTPUT: Keyframe gate for segment start
  // =========================================================================
  // AIR must not emit any video packets for a segment until an IDR frame
  // has been produced by the encoder for that segment.
  // This gate blocks output until avcodec_receive_packet() returns a packet
  // with AV_PKT_FLAG_KEY set. Reset on segment switch (ResetOutputTiming).
  bool first_keyframe_emitted_;

  // Video frame counter for CFR PTS generation (resets per session)
  int64_t video_frame_count_;

  // INV-P8-AUDIO-PRIME-STALL: Diagnostic counter for video frames dropped
  // waiting for audio to prime the header. If this exceeds threshold, emit warning.
  int audio_prime_stall_count_;

  // =========================================================================
  // INV-P9-AUDIO-LIVENESS: Deterministic silence generation
  // =========================================================================
  // From the moment the MPEG-TS header is written, output MUST contain
  // continuous, monotonically increasing audio PTS. If no real audio is
  // available, silence frames are injected to maintain:
  // - 1024 samples at stream rate (48kHz)
  // - PTS monotonically increasing, aligned to video CT
  // - Seamless transition when real audio arrives (no discontinuity)
  // =========================================================================
  bool real_audio_received_;           // True once first real audio frame encoded
  bool silence_injection_active_;      // True while injecting silence (for logging/metrics)
  int64_t silence_audio_pts_90k_;      // Next PTS for silence frame (90kHz)
  int silence_frames_generated_;       // Counter: retrovue_audio_silence_frames_injected_total
  bool audio_liveness_enabled_;        // INV-P10-PCR-PACED-MUX: False to disable silence injection

  // Generate and encode silence frames to fill gap up to target_pts_90k
  void GenerateSilenceFrames(int64_t target_pts_90k);

  // OutputContinuity: enforce monotonic PTS/DTS per stream with minimal correction.
  void EnforceMonotonicDts();

  // Custom AVIO write callback (for nonblocking mode)
  void* avio_opaque_;
  int (*avio_write_callback_)(void* opaque, uint8_t* buf, int buf_size);
  AVIOContext* custom_avio_ctx_;

  static int AVIOWriteThunk(void* opaque, uint8_t* buf, int buf_size);
  int HandleAVIOWrite(uint8_t* buf, int buf_size);

  // OutputTiming: Gate packet emission to enforce real-time delivery discipline.
  // See OutputTimingContract.md for invariants.
  // Gating happens after av_packet_rescale_ts(), before av_interleaved_write_frame().
  void GateOutputTiming(int64_t packet_pts_90k);

  // OutputTiming state (per OutputTimingContract.md)
  bool output_timing_anchor_set_;
  int64_t output_timing_anchor_pts_;  // First packet's PTS (90kHz timebase)
  std::chrono::steady_clock::time_point output_timing_anchor_wall_;
  bool output_timing_enabled_;  // P8-IO-001: Can disable during prebuffer
#endif

  MpegTSPlayoutSinkConfig config_;
  bool initialized_;

 public:
  // Reset output timing anchor (call on SwitchToLive per OutputTimingContract.md §6)
  void ResetOutputTiming();

  // P8-IO-001: Enable/disable output timing gating (disable during prebuffer)
  void SetOutputTimingEnabled(bool enabled);

  // INV-P10-PCR-PACED-MUX: Disable audio liveness injection when PCR-paced mux is active.
  // When disabled, no silence frames are generated - producer audio is authoritative.
  void SetAudioLivenessEnabled(bool enabled);
};

}  // namespace retrovue::playout_sinks::mpegts

#endif  // RETROVUE_PLAYOUT_SINKS_MPEGTS_ENCODER_PIPELINE_HPP_

