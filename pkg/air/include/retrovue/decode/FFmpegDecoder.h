// Repository: Retrovue-playout
// Component: FFmpeg Decoder
// Purpose: Real video decoding using libavformat/libavcodec.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_DECODE_FFMPEG_DECODER_H_
#define RETROVUE_DECODE_FFMPEG_DECODER_H_

#include <atomic>
#include <cstdint>
#include <memory>
#include <queue>
#include <string>

#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/blockplan/RationalFps.hpp"

// Forward declarations for FFmpeg types (avoids pulling in FFmpeg headers here)
struct AVFormatContext;
struct AVCodecContext;
struct AVFrame;
struct AVPacket;
struct SwsContext;
struct SwrContext;

namespace retrovue::decode {

// DecoderConfig holds configuration for FFmpeg-based decoding.
struct DecoderConfig {
  std::string input_uri;        // File path or URI to decode
  int target_width;             // Target output width (for scaling)
  int target_height;            // Target output height (for scaling)
  bool hw_accel_enabled;        // Enable hardware acceleration if available
  int max_decode_threads;       // Maximum decoder threads (0 = auto)
  
  DecoderConfig()
      : target_width(1920),
        target_height(1080),
        hw_accel_enabled(false),
        max_decode_threads(0) {}
};

// DecoderStats tracks decoding performance and errors.
struct DecoderStats {
  uint64_t frames_decoded;
  uint64_t frames_dropped;
  uint64_t decode_errors;
  double average_decode_time_ms;
  double current_fps;
  
  DecoderStats()
      : frames_decoded(0),
        frames_dropped(0),
        decode_errors(0),
        average_decode_time_ms(0.0),
        current_fps(0.0) {}
};

// FFmpegDecoder decodes video files using libavformat and libavcodec.
//
// Features:
// - Supports H.264, HEVC, and other common codecs
// - Automatic format detection via libavformat
// - Optional scaling to target resolution
// - YUV420 output format
// - Frame timing from PTS
//
// Thread Safety:
// - Not thread-safe: Use from single decode thread
// - Outputs to thread-safe FrameRingBuffer
//
// Lifecycle:
// 1. Construct with config
// 2. Call Open() to initialize decoder
// 3. Call DecodeNextFrame() repeatedly
// 4. Call Close() or rely on destructor
//
// Error Handling:
// - Returns false on errors with stats updated
// - Supports recovery from transient decode errors
// - Tracks error count for monitoring
class FFmpegDecoder {
 public:
  explicit FFmpegDecoder(const DecoderConfig& config);
  ~FFmpegDecoder();

  // Disable copy and move
  FFmpegDecoder(const FFmpegDecoder&) = delete;
  FFmpegDecoder& operator=(const FFmpegDecoder&) = delete;

  // Opens the input file and initializes decoder.
  // Returns true on success, false on error.
  bool Open();

  // Decodes the next frame and pushes it to the output buffer.
  // Returns true if frame decoded successfully, false on error or EOF.
  bool DecodeNextFrame(buffer::FrameRingBuffer& output_buffer);

  // Decodes the next audio frame and pushes it to the output buffer.
  // Returns true if audio frame decoded successfully, false on error or EOF.
  bool DecodeNextAudioFrame(buffer::FrameRingBuffer& output_buffer);

  // Closes the decoder and releases resources.
  void Close();

  // Seek to position in milliseconds.
  // Seeks to nearest keyframe before the target position.
  bool SeekToMs(int64_t position_ms);

  // Seek precisely to target position with preroll.
  // 1. Seeks to keyframe BEFORE target (via SeekToMs)
  // 2. Decodes and discards frames until PTS >= target_ms
  // 3. Leaves the first on-target frame pending for next DecodeFrameToBuffer()
  // Returns number of preroll frames discarded, or -1 on seek error.
  int SeekPreciseToMs(int64_t target_ms);

  // Decode next frame directly to Frame struct (no ring buffer).
  // Used by BlockPlan executor for frame-by-frame decoding.
  bool DecodeFrameToBuffer(buffer::Frame& output_frame);

  // Check if there are pending audio frames from video decoding.
  // Audio frames are automatically decoded when video packets are read.
  bool HasPendingAudioFrame() const { return !pending_audio_frames_.empty(); }

  // Get next pending audio frame (already resampled to house format).
  // Returns false if no pending audio frames.
  bool GetPendingAudioFrame(buffer::AudioFrame& output_frame);

  // Returns true if decoder is open and ready.
  bool IsOpen() const { return format_ctx_ != nullptr; }

  // Set interrupt flags for FFmpeg I/O. When either is true, av_read_frame
  // and other blocking calls abort promptly. Call before or after Open().
  struct InterruptFlags {
    std::atomic<bool>* fill_stop = nullptr;
    std::atomic<bool>* session_stop = nullptr;
  };
  void SetInterruptFlags(const InterruptFlags& flags);

  // Returns true if end of file reached.
  bool IsEOF() const { return eof_reached_; }

  // Gets current decoder statistics.
  const DecoderStats& GetStats() const { return stats_; }

  // Gets video stream information.
  int GetVideoWidth() const;
  int GetVideoHeight() const;
  blockplan::RationalFps GetVideoRationalFps() const;
  double GetVideoDuration() const;

  // True if the asset has an audio stream (for INV-AUDIO-PRIME-002 / priming logs).
  bool HasAudioStream() const { return audio_stream_index_ >= 0; }

 private:
  // Finds the best video stream in the input.
  bool FindVideoStream();

  // Finds the best audio stream in the input.
  bool FindAudioStream();

  // Initializes the codec and codec context.
  bool InitializeCodec();

  // Initializes the audio codec and codec context.
  bool InitializeAudioCodec();

  // Initializes the scaler for resolution conversion.
  bool InitializeScaler();

  // Initializes the resampler for audio format conversion.
  bool InitializeResampler();

  // Reads and decodes a single frame.
  bool ReadAndDecodeFrame(buffer::Frame& output_frame);

  // Reads and decodes a single audio frame.
  bool ReadAndDecodeAudioFrame(buffer::AudioFrame& output_frame);

  // Converts AVFrame to our Frame format.
  bool ConvertFrame(AVFrame* av_frame, buffer::Frame& output_frame);

  // Converts AVFrame to our AudioFrame format (PCM S16 interleaved).
  bool ConvertAudioFrame(AVFrame* av_frame, buffer::AudioFrame& output_frame);

  // Updates decoder statistics.
  void UpdateStats(double decode_time_ms);

  DecoderConfig config_;
  DecoderStats stats_;

  // FFmpeg contexts (opaque pointers)
  AVFormatContext* format_ctx_ = nullptr;
  AVCodecContext* codec_ctx_ = nullptr;
  AVCodecContext* audio_codec_ctx_ = nullptr;
  AVFrame* frame_ = nullptr;
  AVFrame* scaled_frame_ = nullptr;
  AVFrame* audio_frame_ = nullptr;
  AVPacket* packet_ = nullptr;
  SwsContext* sws_ctx_ = nullptr;
  ::SwrContext* swr_ctx_ = nullptr;  // Audio resampler (FFmpeg type, global scope)

  int video_stream_index_ = -1;
  int audio_stream_index_ = -1;
  bool eof_reached_ = false;
  InterruptFlags interrupt_flags_;
  bool audio_eof_reached_ = false;

  // Skip pre-keyframe frames to avoid scaling artifacts
  bool first_keyframe_seen_;
  
  // Timing
  int64_t start_time_ = 0;
  double time_base_ = 0.0;
  int64_t audio_start_time_ = 0;
  double audio_time_base_ = 0.0;

  // Pending frame from SeekPreciseToMs() preroll
  bool has_pending_frame_ = false;
  buffer::Frame pending_frame_;

  // Phase 8.9: Queue for audio frames decoded during video packet processing
  std::queue<buffer::AudioFrame> pending_audio_frames_;
};

}  // namespace retrovue::decode

#endif  // RETROVUE_DECODE_FFMPEG_DECODER_H_

