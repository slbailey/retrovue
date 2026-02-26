// Repository: Retrovue-playout
// Component: FFmpeg Decoder
// Purpose: Real video decoding using libavformat/libavcodec.
// Copyright (c) 2025 RetroVue

#include "retrovue/decode/FFmpegDecoder.h"

#include <chrono>
#include <iostream>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"  // SnapToStandardRationalFps

namespace {

// Opaque for interrupt callback — layout matches FFmpegDecoder::InterruptFlags.
struct InterruptOpaque {
  std::atomic<bool>* fill_stop = nullptr;
  std::atomic<bool>* session_stop = nullptr;
};

// FFmpeg interrupt callback: return non-zero to abort I/O.
int InterruptCallback(void* opaque) {
  auto* flags = static_cast<InterruptOpaque*>(opaque);
  if (flags->fill_stop && flags->fill_stop->load(std::memory_order_acquire))
    return 1;
  if (flags->session_stop && flags->session_stop->load(std::memory_order_acquire))
    return 1;
  return 0;
}

}  // namespace

extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/imgutils.h>
#include <libavutil/samplefmt.h>
#include <libavutil/channel_layout.h>
#include <libavutil/error.h>
#include <libavutil/frame.h>
#include <libavutil/mem.h>  // av_freep (for av_image_alloc buffer)
#include <libavutil/log.h>  // For av_log_set_level
#include <libswscale/swscale.h>
#include <libswresample/swresample.h>
}

namespace {

// Deleter for AVFramePtr (av_frame_free takes AVFrame**).
void FreeAVFrame(AVFrame* f) {
  av_frame_free(&f);
}

}  // namespace

namespace retrovue::decode {

FFmpegDecoder::FFmpegDecoder(const DecoderConfig& config)
    : config_(config),
      format_ctx_(nullptr),
      codec_ctx_(nullptr),
      frame_(nullptr),
      scaled_frame_(nullptr),
      packet_(nullptr),
      sws_ctx_(nullptr),
      video_stream_index_(-1),
      eof_reached_(false),
      start_time_(0),
      time_base_(0.0),
      first_keyframe_seen_(false),
      stashed_video_frame_(nullptr, FreeAVFrame) {
  pump_scratch_frame_ = av_frame_alloc();
  if (!pump_scratch_frame_) {
    std::cerr << "[FFmpegDecoder] Failed to allocate pump scratch frame\n";
  }
}

FFmpegDecoder::~FFmpegDecoder() {
  Close();

  // Phase 2: Free pump scratch frame (only in destructor)
  if (pump_scratch_frame_) {
    av_frame_free(&pump_scratch_frame_);
  }
}

bool FFmpegDecoder::Open() {
  std::cout << "[FFmpegDecoder] Opening: " << config_.input_uri << std::endl;

  // Suppress FFmpeg warnings but keep errors visible
  av_log_set_level(AV_LOG_ERROR);

  // Allocate format context
  format_ctx_ = avformat_alloc_context();
  if (!format_ctx_) {
    std::cerr << "[FFmpegDecoder] Failed to allocate format context" << std::endl;
    return false;
  }

  // Set interrupt callback so av_read_frame etc. abort promptly on stop.
  if (interrupt_flags_.fill_stop || interrupt_flags_.session_stop) {
    format_ctx_->interrupt_callback.callback = InterruptCallback;
    format_ctx_->interrupt_callback.opaque = &interrupt_flags_;
  }

  // Open input file — DECODER_STEP: open_input
  int ret = avformat_open_input(&format_ctx_, config_.input_uri.c_str(), nullptr, nullptr);
  if (ret < 0) {
    char errbuf[AV_ERROR_MAX_STRING_SIZE];
    av_strerror(ret, errbuf, sizeof(errbuf));
    std::cerr << "[FFmpegDecoder] DECODER_STEP open_input FAILED uri=" << config_.input_uri
              << " ret=" << ret << " err=" << errbuf << std::endl;
    avformat_free_context(format_ctx_);
    format_ctx_ = nullptr;
    return false;
  }

  // Retrieve stream information — DECODER_STEP: avformat_find_stream_info
  ret = avformat_find_stream_info(format_ctx_, nullptr);
  if (ret < 0) {
    char errbuf[AV_ERROR_MAX_STRING_SIZE];
    av_strerror(ret, errbuf, sizeof(errbuf));
    std::cerr << "[FFmpegDecoder] DECODER_STEP avformat_find_stream_info FAILED uri="
              << config_.input_uri << " ret=" << ret << " err=" << errbuf << std::endl;
    Close();
    return false;
  }

  // Find video stream — DECODER_STEP: find_video_stream
  if (!FindVideoStream()) {
    std::cerr << "[FFmpegDecoder] DECODER_STEP find_video_stream FAILED uri="
              << config_.input_uri << " (no video stream)" << std::endl;
    Close();
    return false;
  }

  // Find audio stream (optional)
  FindAudioStream();

  // Initialize codec — DECODER_STEP: initialize_codec
  if (!InitializeCodec()) {
    std::cerr << "[FFmpegDecoder] DECODER_STEP initialize_codec FAILED uri="
              << config_.input_uri << std::endl;
    Close();
    return false;
  }

  // Initialize audio codec (if audio stream found)
  if (audio_stream_index_ >= 0) {
    std::cout << "[FFmpegDecoder] Audio stream found at index " << audio_stream_index_ << ", initializing audio decoder..." << std::endl;
    if (!InitializeAudioCodec()) {
      std::cerr << "[FFmpegDecoder] Failed to initialize audio codec" << std::endl;
      // Continue without audio
      audio_stream_index_ = -1;
    } else {
      std::cout << "[FFmpegDecoder] Audio decoder initialized successfully" << std::endl;
      if (!InitializeResampler()) {
        std::cerr << "[FFmpegDecoder] Failed to initialize audio resampler" << std::endl;
        // Continue without audio
        audio_stream_index_ = -1;
      } else {
        std::cout << "[FFmpegDecoder] Audio resampler initialized successfully" << std::endl;
      }
    }
  } else {
    std::cout << "[FFmpegDecoder] No audio stream found in file" << std::endl;
  }

  // Initialize scaler — DECODER_STEP: initialize_scaler
  if (!InitializeScaler()) {
    std::cerr << "[FFmpegDecoder] DECODER_STEP initialize_scaler FAILED uri="
              << config_.input_uri << std::endl;
    Close();
    return false;
  }

  // Allocate packet — DECODER_STEP: packet_alloc
  packet_ = av_packet_alloc();
  if (!packet_) {
    std::cerr << "[FFmpegDecoder] DECODER_STEP packet_alloc FAILED uri="
              << config_.input_uri << std::endl;
    Close();
    return false;
  }

  std::cout << "[FFmpegDecoder] DECODER_STEP open_input OK uri=" << config_.input_uri
            << " " << GetVideoWidth() << "x" 
            << GetVideoHeight() << " @ " << GetVideoRationalFps().num << "/" << GetVideoRationalFps().den << " fps" << std::endl;

  return true;
}

void FFmpegDecoder::SetInterruptFlags(const InterruptFlags& flags) {
  interrupt_flags_ = flags;
  if (format_ctx_) {
    format_ctx_->interrupt_callback.callback =
        (flags.fill_stop || flags.session_stop) ? InterruptCallback : nullptr;
    format_ctx_->interrupt_callback.opaque =
        (flags.fill_stop || flags.session_stop) ? &interrupt_flags_ : nullptr;
  }
}

bool FFmpegDecoder::DecodeNextFrame(buffer::FrameRingBuffer& output_buffer) {
  if (!IsOpen()) {
    return false;
  }

  if (eof_reached_) {
    return false;
  }

  auto start_time = std::chrono::steady_clock::now();

  buffer::Frame output_frame;
  if (!ReadAndDecodeFrame(output_frame)) {
    return false;
  }

  // Try to push to buffer
  if (!output_buffer.Push(output_frame)) {
    stats_.frames_dropped++;
    return false;  // Buffer full
  }

  auto end_time = std::chrono::steady_clock::now();
  double decode_time_ms = std::chrono::duration<double, std::milli>(
      end_time - start_time).count();
  
  UpdateStats(decode_time_ms);

  return true;
}

void FFmpegDecoder::Close() {
  std::cout << "[FFmpegDecoder] Closing decoder" << std::endl;

  if (sws_ctx_) {
    sws_freeContext(sws_ctx_);
    sws_ctx_ = nullptr;
  }

  if (scaled_frame_) {
    // scaled_frame_ buffer was allocated with av_image_alloc(); AVFrame does not own it.
    // Free it before av_frame_free to avoid leaking ~(width*height*1.5) bytes per Close().
    if (scaled_frame_->data[0]) {
      av_freep(&scaled_frame_->data[0]);
    }
    av_frame_free(&scaled_frame_);
    scaled_frame_ = nullptr;
  }

  if (frame_) {
    av_frame_free(&frame_);
  }

  if (packet_) {
    av_packet_free(&packet_);
  }

  if (swr_ctx_) {
    swr_free(&swr_ctx_);
  }

  if (audio_frame_) {
    av_frame_free(&audio_frame_);
  }

  if (audio_codec_ctx_) {
    avcodec_free_context(&audio_codec_ctx_);
  }

  if (codec_ctx_) {
    avcodec_free_context(&codec_ctx_);
  }

  if (format_ctx_) {
    avformat_close_input(&format_ctx_);
  }

  // Phase 2: Clear stashed video frame
  stashed_video_frame_.reset();
  has_stashed_video_frame_ = false;

  // Phase 2: Free deferred video packets (RAII handles av_packet_free)
  while (!deferred_video_packets_.empty()) {
    deferred_video_packets_.pop();
  }

  // Phase 2: Free pending video frames (RAII handles av_frame_free)
  while (!pending_video_frames_.empty()) {
    pending_video_frames_.pop();
  }

  // Phase 2: Reset EOF flush state
  demux_eof_reached_ = false;
  video_codec_flushed_ = false;
  audio_codec_flushed_ = false;

  // Phase 2: Reset debug counters (for clean soak metrics)
  pending_video_max_depth_ = 0;
  deferred_video_max_depth_ = 0;
  pump_calls_audio_only_ = 0;
  pump_backpressure_hits_ = 0;
  audio_frames_harvested_in_audio_only_ = 0;

  // Fix B safety: drain pending audio queue to prevent unbounded growth
  // across Close()/reopen cycles.
  while (!pending_audio_frames_.empty()) pending_audio_frames_.pop();

  video_stream_index_ = -1;
  audio_stream_index_ = -1;
  eof_reached_ = false;
  audio_eof_reached_ = false;
  first_keyframe_seen_ = false;
}

bool FFmpegDecoder::SeekToMs(int64_t position_ms) {
  if (!format_ctx_ || video_stream_index_ < 0) {
    return false;
  }

  // INV-BLOCK-WALLFENCE-003: Seeking to position 0 is a looping violation.
  // Segments default to loop=false.  EOF means "segment exhausted" and must
  // advance to the next segment, not restart the current one.
  // Hard violation: log and refuse the seek.
  if (position_ms == 0) {
    std::cerr << "[FFmpegDecoder] VIOLATION: SeekToMs(0) called"
              << " — refusing seek (EOF-loop prohibited)"
              << " uri=" << (config_.input_uri.empty() ? "unknown" : config_.input_uri)
              << std::endl;
    return false;
  }

  // Convert milliseconds to stream time base
  AVStream* stream = format_ctx_->streams[video_stream_index_];
  int64_t timestamp = av_rescale_q(position_ms * 1000,
                                    {1, AV_TIME_BASE},
                                    stream->time_base);

  // Seek to keyframe before the target position — DECODER_STEP: seek
  int ret = av_seek_frame(format_ctx_, video_stream_index_, timestamp,
                          AVSEEK_FLAG_BACKWARD);
  if (ret < 0) {
    char errbuf[AV_ERROR_MAX_STRING_SIZE];
    av_strerror(ret, errbuf, sizeof(errbuf));
    std::cerr << "[FFmpegDecoder] DECODER_STEP seek FAILED position_ms=" << position_ms
              << " ret=" << ret << " err=" << errbuf << std::endl;
    return false;
  }

  // Flush decoder buffers
  if (codec_ctx_) {
    avcodec_flush_buffers(codec_ctx_);
  }
  if (audio_codec_ctx_) {
    avcodec_flush_buffers(audio_codec_ctx_);
  }

  // Reset EOF flags
  eof_reached_ = false;
  audio_eof_reached_ = false;
  first_keyframe_seen_ = false;

  // Phase 2: Reset EOF flush state and queues so pump runs in normal mode after seek
  demux_eof_reached_ = false;
  video_codec_flushed_ = false;
  audio_codec_flushed_ = false;
  stashed_video_frame_.reset();
  has_stashed_video_frame_ = false;
  while (!deferred_video_packets_.empty())
    deferred_video_packets_.pop();
  while (!pending_video_frames_.empty())
    pending_video_frames_.pop();

  // Clear pending audio frames
  while (!pending_audio_frames_.empty()) {
    pending_audio_frames_.pop();
  }

  return true;
}

int FFmpegDecoder::SeekPreciseToMs(int64_t target_ms) {
  if (!SeekToMs(target_ms)) {
    return -1;
  }

  // No preroll needed for start of file
  if (target_ms <= 0) {
    return 0;
  }

  int preroll_count = 0;

  while (true) {
    buffer::Frame frame;
    if (!ReadAndDecodeFrame(frame)) {
      // EOF during preroll — no on-target frame found
      // Clear any audio frames accumulated during preroll
      while (!pending_audio_frames_.empty()) {
        pending_audio_frames_.pop();
      }
      return preroll_count;
    }

    // Convert frame PTS from microseconds to milliseconds
    int64_t pts_ms = frame.metadata.pts / 1000;

    if (pts_ms >= target_ms) {
      // This is the first on-target frame — store it as pending
      has_pending_frame_ = true;
      pending_frame_ = std::move(frame);
      // Flush audio from the preroll period but keep frames whose PTS
      // is at or after the target — they belong to the on-target
      // neighbourhood and are needed by PrimeFirstTick.
      {
        int64_t target_us = target_ms * 1000;
        std::queue<buffer::AudioFrame> kept;
        while (!pending_audio_frames_.empty()) {
          auto& af = pending_audio_frames_.front();
          if (af.pts_us >= target_us) {
            kept.push(std::move(af));
          }
          pending_audio_frames_.pop();
        }
        pending_audio_frames_ = std::move(kept);
      }
      return preroll_count;
    }

    // Discard this preroll frame
    preroll_count++;
  }
}

bool FFmpegDecoder::DecodeFrameToBuffer(buffer::Frame& output_frame) {
  if (has_pending_frame_) {
    has_pending_frame_ = false;
    output_frame = std::move(pending_frame_);
    return true;
  }
  if (!IsOpen() || eof_reached_) {
    return false;
  }
  return ReadAndDecodeFrame(output_frame);
}

int FFmpegDecoder::GetVideoWidth() const {
  if (!codec_ctx_) return 0;
  return codec_ctx_->width;
}

int FFmpegDecoder::GetVideoHeight() const {
  if (!codec_ctx_) return 0;
  return codec_ctx_->height;
}

blockplan::RationalFps FFmpegDecoder::GetVideoRationalFps() const {
  if (!format_ctx_ || video_stream_index_ < 0) return blockplan::RationalFps{0, 1};

  AVStream* stream = format_ctx_->streams[video_stream_index_];
  // Use r_frame_rate for cadence (container/codec nominal rate). avg_frame_rate is for
  // diagnostics only and is not authoritative for cadence math.
  AVRational fps = stream->r_frame_rate;
  if (fps.num <= 0 || fps.den <= 0) return blockplan::RationalFps{0, 1};
  blockplan::RationalFps normalized(static_cast<int64_t>(fps.num), static_cast<int64_t>(fps.den));
  return blockplan::SnapToStandardRationalFps(normalized);
}

double FFmpegDecoder::GetVideoDuration() const {
  if (!format_ctx_) return 0.0;
  
  if (format_ctx_->duration != AV_NOPTS_VALUE) {
    return static_cast<double>(format_ctx_->duration) / AV_TIME_BASE;
  }
  
  return 0.0;
}

bool FFmpegDecoder::FindVideoStream() {
  for (unsigned int i = 0; i < format_ctx_->nb_streams; i++) {
    if (format_ctx_->streams[i]->codecpar->codec_type == AVMEDIA_TYPE_VIDEO) {
      video_stream_index_ = i;
      
      AVStream* stream = format_ctx_->streams[i];
      time_base_ = av_q2d(stream->time_base);
      start_time_ = stream->start_time != AV_NOPTS_VALUE ? stream->start_time : 0;
      
      return true;
    }
  }
  
  return false;
}

bool FFmpegDecoder::FindAudioStream() {
  for (unsigned int i = 0; i < format_ctx_->nb_streams; i++) {
    if (format_ctx_->streams[i]->codecpar->codec_type == AVMEDIA_TYPE_AUDIO) {
      audio_stream_index_ = i;
      
      AVStream* stream = format_ctx_->streams[i];
      audio_time_base_ = av_q2d(stream->time_base);
      audio_start_time_ = stream->start_time != AV_NOPTS_VALUE ? stream->start_time : 0;
      
      return true;
    }
  }
  
  return false;
}

bool FFmpegDecoder::InitializeCodec() {
  AVStream* stream = format_ctx_->streams[video_stream_index_];
  AVCodecParameters* codecpar = stream->codecpar;

  // Find decoder
  const AVCodec* codec = avcodec_find_decoder(codecpar->codec_id);
  if (!codec) {
    std::cerr << "[FFmpegDecoder] Codec not found: " << codecpar->codec_id << std::endl;
    return false;
  }

  // Allocate codec context
  codec_ctx_ = avcodec_alloc_context3(codec);
  if (!codec_ctx_) {
    std::cerr << "[FFmpegDecoder] Failed to allocate codec context" << std::endl;
    return false;
  }

  // Copy codec parameters
  if (avcodec_parameters_to_context(codec_ctx_, codecpar) < 0) {
    std::cerr << "[FFmpegDecoder] Failed to copy codec parameters" << std::endl;
    return false;
  }

  // Set threading
  if (config_.max_decode_threads > 0) {
    codec_ctx_->thread_count = config_.max_decode_threads;
  }
  codec_ctx_->thread_type = FF_THREAD_FRAME;

  // Open codec
  if (avcodec_open2(codec_ctx_, codec, nullptr) < 0) {
    std::cerr << "[FFmpegDecoder] Failed to open codec" << std::endl;
    return false;
  }

  // Allocate frames
  frame_ = av_frame_alloc();
  scaled_frame_ = av_frame_alloc();
  
  if (!frame_ || !scaled_frame_) {
    std::cerr << "[FFmpegDecoder] Failed to allocate frames" << std::endl;
    return false;
  }

  return true;
}

bool FFmpegDecoder::InitializeScaler() {
  // Get source format
  int src_width = codec_ctx_->width;
  int src_height = codec_ctx_->height;
  AVPixelFormat src_format = codec_ctx_->pix_fmt;

  // Target format: YUV420P
  int dst_width = config_.target_width;
  int dst_height = config_.target_height;
  AVPixelFormat dst_format = AV_PIX_FMT_YUV420P;

  // Create scaler context
  sws_ctx_ = sws_getContext(
      src_width, src_height, src_format,
      dst_width, dst_height, dst_format,
      SWS_BILINEAR, nullptr, nullptr, nullptr);

  if (!sws_ctx_) {
    std::cerr << "[FFmpegDecoder] Failed to create scaler context" << std::endl;
    return false;
  }

  // Allocate buffer for scaled frame
  if (av_image_alloc(scaled_frame_->data, scaled_frame_->linesize,
                     dst_width, dst_height, dst_format, 32) < 0) {
    std::cerr << "[FFmpegDecoder] Failed to allocate scaled frame buffer" << std::endl;
    return false;
  }

  scaled_frame_->width = dst_width;
  scaled_frame_->height = dst_height;
  scaled_frame_->format = dst_format;

  return true;
}

bool FFmpegDecoder::InitializeAudioCodec() {
  if (audio_stream_index_ < 0) {
    return false;
  }

  AVStream* stream = format_ctx_->streams[audio_stream_index_];
  AVCodecParameters* codecpar = stream->codecpar;

  // Find decoder
  const AVCodec* codec = avcodec_find_decoder(codecpar->codec_id);
  if (!codec) {
    std::cerr << "[FFmpegDecoder] Audio codec not found: " << codecpar->codec_id << std::endl;
    return false;
  }

  // Allocate codec context
  audio_codec_ctx_ = avcodec_alloc_context3(codec);
  if (!audio_codec_ctx_) {
    std::cerr << "[FFmpegDecoder] Failed to allocate audio codec context" << std::endl;
    return false;
  }

  // Copy codec parameters
  if (avcodec_parameters_to_context(audio_codec_ctx_, codecpar) < 0) {
    std::cerr << "[FFmpegDecoder] Failed to copy audio codec parameters" << std::endl;
    return false;
  }

  // Open codec
  if (avcodec_open2(audio_codec_ctx_, codec, nullptr) < 0) {
    std::cerr << "[FFmpegDecoder] Failed to open audio codec" << std::endl;
    return false;
  }

  // Allocate audio frame
  audio_frame_ = av_frame_alloc();
  if (!audio_frame_) {
    std::cerr << "[FFmpegDecoder] Failed to allocate audio frame" << std::endl;
    return false;
  }

  return true;
}

bool FFmpegDecoder::InitializeResampler() {
  if (!audio_codec_ctx_ || audio_stream_index_ < 0) {
    return false;
  }

  // Source format (from decoder) - use modern AVChannelLayout API
  AVChannelLayout src_ch_layout;
  av_channel_layout_uninit(&src_ch_layout);  // Initialize to empty state
  int src_nb_channels = 0;
  
  // Try to use the new ch_layout field first
  if (audio_codec_ctx_->ch_layout.nb_channels > 0) {
    // Use the channel layout from codec context if available
    if (av_channel_layout_copy(&src_ch_layout, &audio_codec_ctx_->ch_layout) < 0) {
      std::cerr << "[FFmpegDecoder] Failed to copy source channel layout" << std::endl;
      return false;
    }
    src_nb_channels = src_ch_layout.nb_channels;
  } else {
    // Fallback: use ch_layout.nb_channels (modern API)
    src_nb_channels = audio_codec_ctx_->ch_layout.nb_channels;
    if (src_nb_channels <= 0) {
      std::cerr << "[FFmpegDecoder] Invalid channel count" << std::endl;
      return false;
    }
    // Copy the existing channel layout
    av_channel_layout_copy(&src_ch_layout, &audio_codec_ctx_->ch_layout);
    if (src_ch_layout.nb_channels == 0) {
      std::cerr << "[FFmpegDecoder] Failed to create default channel layout" << std::endl;
      return false;
    }
  }
  AVSampleFormat src_sample_fmt = audio_codec_ctx_->sample_fmt;
  int src_sample_rate = audio_codec_ctx_->sample_rate;

  // Target format: S16 interleaved, stereo, 48kHz
  AVChannelLayout dst_ch_layout;
  av_channel_layout_uninit(&dst_ch_layout);  // Initialize to empty state
  uint64_t dst_ch_mask = AV_CH_LAYOUT_STEREO;
  if (av_channel_layout_from_mask(&dst_ch_layout, dst_ch_mask) < 0) {
    std::cerr << "[FFmpegDecoder] Failed to create destination channel layout" << std::endl;
    av_channel_layout_uninit(&src_ch_layout);
    return false;
  }
  AVSampleFormat dst_sample_fmt = AV_SAMPLE_FMT_S16;
  int dst_sample_rate = 48000;

  // Create resampler context using modern API
  swr_ctx_ = swr_alloc();
  if (!swr_ctx_) {
    std::cerr << "[FFmpegDecoder] Failed to allocate resampler context" << std::endl;
    av_channel_layout_uninit(&src_ch_layout);
    av_channel_layout_uninit(&dst_ch_layout);
    return false;
  }

  // Set options using modern API
  if (swr_alloc_set_opts2(&swr_ctx_,
                          &dst_ch_layout, dst_sample_fmt, dst_sample_rate,
                          &src_ch_layout, src_sample_fmt, src_sample_rate,
                          0, nullptr) != 0) {
    std::cerr << "[FFmpegDecoder] Failed to set resampler options" << std::endl;
    swr_free(&swr_ctx_);
    av_channel_layout_uninit(&src_ch_layout);
    av_channel_layout_uninit(&dst_ch_layout);
    return false;
  }

  // Clean up channel layouts (swr_alloc_set_opts2 copies them)
  av_channel_layout_uninit(&src_ch_layout);
  av_channel_layout_uninit(&dst_ch_layout);

  // Initialize resampler
  if (swr_init(swr_ctx_) < 0) {
    std::cerr << "[FFmpegDecoder] Failed to initialize resampler" << std::endl;
    swr_free(&swr_ctx_);
    return false;
  }

  return true;
}

bool FFmpegDecoder::ReadAndDecodeFrame(buffer::Frame& output_frame) {
  while (true) {
    // Read packet
    int ret = av_read_frame(format_ctx_, packet_);

    if (ret == AVERROR_EOF) {
      eof_reached_ = true;
      audio_eof_reached_ = true;
      return false;
    }

    if (ret < 0) {
      stats_.decode_errors++;
      av_packet_unref(packet_);
      return false;
    }

    // Phase 8.9: Dispatch packet based on stream index
    // If it's an audio packet, send to audio decoder (don't discard!)
    if (packet_->stream_index == audio_stream_index_ && audio_codec_ctx_ != nullptr && audio_frame_ != nullptr) {
      ret = avcodec_send_packet(audio_codec_ctx_, packet_);
      av_packet_unref(packet_);

      // Drain all available audio frames immediately to prevent decoder backup
      // Convert and queue them for later retrieval by DecodeNextAudioFrame()
      if (ret >= 0 || ret == AVERROR(EAGAIN)) {
        while (true) {
          int drain_ret = avcodec_receive_frame(audio_codec_ctx_, audio_frame_);
          if (drain_ret == AVERROR(EAGAIN) || drain_ret == AVERROR_EOF) {
            break;  // No more frames available
          }
          if (drain_ret < 0) {
            break;  // Error
          }
          // Phase 8.9: Convert and queue the audio frame.
          // Fix B safety: cap queue size to prevent unbounded memory growth
          // when audio packets arrive faster than they are consumed.
          static constexpr size_t kMaxPendingAudioFrames = 120;
          buffer::AudioFrame converted_audio;
          if (ConvertAudioFrame(audio_frame_, converted_audio)) {
            if (pending_audio_frames_.size() < kMaxPendingAudioFrames) {
              pending_audio_frames_.push(std::move(converted_audio));
            }
          }
          av_frame_unref(audio_frame_);
        }
      }
      continue;  // Continue reading packets (looking for video)
    }

    // Check if packet is from video stream
    if (packet_->stream_index != video_stream_index_) {
      av_packet_unref(packet_);
      continue;
    }

    // Send packet to decoder.
    // With FF_THREAD_FRAME, send_packet may return EAGAIN when the
    // decoder's internal frame buffer is full.  Drain all buffered
    // frames via receive_frame, then retry send_packet with the same
    // packet.  Bounded to prevent infinite spin.
    static constexpr int kMaxEagainRetries = 4;
    for (int eagain_try = 0; eagain_try <= kMaxEagainRetries; ++eagain_try) {
      ret = avcodec_send_packet(codec_ctx_, packet_);
      if (ret != AVERROR(EAGAIN)) break;  // Sent (or hard error)

      // Decoder full — drain receive_frame until EAGAIN.
      // If any drained frame is a valid video frame, return it now;
      // the un-sent packet will be re-read on the next call (FFmpeg
      // keeps the read position; we just unref the packet below).
      while (true) {
        int drain_ret = avcodec_receive_frame(codec_ctx_, frame_);
        if (drain_ret == AVERROR(EAGAIN) || drain_ret == AVERROR_EOF) {
          break;  // Fully drained — retry send_packet
        }
        if (drain_ret < 0) {
          break;  // Error during drain
        }
        // Got a valid frame from the drain — return it.
        // Unref the packet we haven't sent yet; it will be re-read
        // on the next call to ReadAndDecodeFrame.
        av_packet_unref(packet_);
        return ConvertFrame(frame_, output_frame);
      }
      // Drained without a usable frame — retry send_packet.
    }
    av_packet_unref(packet_);

    if (ret < 0) {
      stats_.decode_errors++;
      return false;
    }

    // Receive decoded frame
    ret = avcodec_receive_frame(codec_ctx_, frame_);

    if (ret == AVERROR(EAGAIN)) {
      continue;  // Need more packets
    }

    if (ret < 0) {
      stats_.decode_errors++;
      return false;
    }

    // Successfully decoded a frame
    return ConvertFrame(frame_, output_frame);
  }
}

bool FFmpegDecoder::ConvertFrame(AVFrame* av_frame, buffer::Frame& output_frame) {
  // Scale frame
  sws_scale(sws_ctx_, 
            av_frame->data, av_frame->linesize, 0, codec_ctx_->height,
            scaled_frame_->data, scaled_frame_->linesize);

  // Set frame metadata
  output_frame.width = config_.target_width;
  output_frame.height = config_.target_height;

  // Calculate PTS in microseconds (MpegTSOutputSink expects microseconds)
  int64_t pts = av_frame->pts != AV_NOPTS_VALUE ? av_frame->pts : av_frame->best_effort_timestamp;
  // Convert from stream timebase to microseconds
  // pts * time_base_ gives seconds, multiply by 1,000,000 for microseconds
  int64_t pts_us = (pts != AV_NOPTS_VALUE)
      ? static_cast<int64_t>((pts - start_time_) * time_base_ * 1'000'000.0)
      : 0;
  output_frame.metadata.pts = pts_us;

#ifdef RETROVUE_DEBUG
  // Diagnostic: log PTS for first 20 frames
  static int decode_diag_count = 0;
  ++decode_diag_count;
  if (decode_diag_count <= 20) {
    std::cout << "[FFmpegDecoder] DIAG: frame=" << decode_diag_count
              << " av_pts=" << av_frame->pts
              << " pts_us=" << pts_us
              << " time_base=" << time_base_
              << " pict_type=" << av_get_picture_type_char(av_frame->pict_type)
              << std::endl;
  }
#endif
  output_frame.metadata.dts = av_frame->pkt_dts;
  // Use duration field (pkt_duration is deprecated in newer FFmpeg)
  int64_t frame_duration = av_frame->duration != AV_NOPTS_VALUE ? av_frame->duration : 0;
  if (frame_duration == 0) {
    // If duration is not available, estimate from frame rate or use default
    // This is a fallback - ideally duration should always be set
    frame_duration = 1;  // Default to 1 timebase unit if unknown
  }
  output_frame.metadata.duration = static_cast<double>(frame_duration) * time_base_;
  output_frame.metadata.asset_uri = config_.input_uri;

  // Copy YUV420 data
  int y_size = config_.target_width * config_.target_height;
  int uv_size = (config_.target_width / 2) * (config_.target_height / 2);
  int total_size = y_size + 2 * uv_size;

  output_frame.data.resize(total_size);

  // Copy Y plane
  uint8_t* dst = output_frame.data.data();
  for (int y = 0; y < config_.target_height; y++) {
    memcpy(dst + y * config_.target_width,
           scaled_frame_->data[0] + y * scaled_frame_->linesize[0],
           config_.target_width);
  }

  // Copy U plane
  dst += y_size;
  for (int y = 0; y < config_.target_height / 2; y++) {
    memcpy(dst + y * (config_.target_width / 2),
           scaled_frame_->data[1] + y * scaled_frame_->linesize[1],
           config_.target_width / 2);
  }

  // Copy V plane
  dst += uv_size;
  for (int y = 0; y < config_.target_height / 2; y++) {
    memcpy(dst + y * (config_.target_width / 2),
           scaled_frame_->data[2] + y * scaled_frame_->linesize[2],
           config_.target_width / 2);
  }

  return true;
}

bool FFmpegDecoder::DecodeNextAudioFrame(buffer::FrameRingBuffer& output_buffer) {
  if (!IsOpen() || audio_stream_index_ < 0) {
    return false;
  }

  if (audio_eof_reached_) {
    return false;
  }

  buffer::AudioFrame output_audio_frame;
  if (!ReadAndDecodeAudioFrame(output_audio_frame)) {
    return false;
  }

  // Try to push to buffer
  if (!output_buffer.PushAudioFrame(output_audio_frame)) {
    stats_.frames_dropped++;
    return false;  // Buffer full
  }

  return true;
}

bool FFmpegDecoder::ReadAndDecodeAudioFrame(buffer::AudioFrame& output_frame) {
  // Phase 8.9: Audio packets are dispatched by ReadAndDecodeFrame().
  // This function only receives frames that were already sent to the decoder.
  // It does NOT read packets (that would compete with the video demux loop).
  if (audio_stream_index_ < 0 || !audio_codec_ctx_ || audio_eof_reached_) {
    return false;
  }

  // Try to receive a decoded audio frame (non-blocking)
  int ret = avcodec_receive_frame(audio_codec_ctx_, audio_frame_);

  if (ret == AVERROR(EAGAIN)) {
    // No audio frame available yet - this is normal
    return false;
  }

  if (ret == AVERROR_EOF) {
    audio_eof_reached_ = true;
    return false;
  }

  if (ret < 0) {
    stats_.decode_errors++;
    return false;
  }

  // Successfully decoded an audio frame
  bool result = ConvertAudioFrame(audio_frame_, output_frame);
  av_frame_unref(audio_frame_);
  return result;
}

bool FFmpegDecoder::ConvertAudioFrame(AVFrame* av_frame, buffer::AudioFrame& output_frame) {
  if (!swr_ctx_) {
    return false;
  }

  // Calculate number of output samples
  int64_t delay = swr_get_delay(swr_ctx_, av_frame->sample_rate);
  int64_t out_samples = av_rescale_rnd(delay + av_frame->nb_samples,
                                        48000, av_frame->sample_rate,
                                        AV_ROUND_UP);

  // Allocate output buffer (S16 interleaved, stereo)
  int out_channels = 2;
  int out_sample_size = av_get_bytes_per_sample(AV_SAMPLE_FMT_S16);
  int out_buffer_size = out_samples * out_channels * out_sample_size;
  
  output_frame.data.resize(out_buffer_size);
  uint8_t* out_data[1] = { output_frame.data.data() };

  // Resample
  int samples_converted = swr_convert(swr_ctx_,
                                       out_data, out_samples,
                                       const_cast<const uint8_t**>(av_frame->data), av_frame->nb_samples);

  if (samples_converted < 0) {
    std::cerr << "[FFmpegDecoder] Audio resampling failed" << std::endl;
    return false;
  }

  // Update output frame metadata
  output_frame.sample_rate = 48000;
  output_frame.channels = 2;
  output_frame.nb_samples = samples_converted;

  // Calculate PTS in microseconds
  int64_t pts = av_frame->pts != AV_NOPTS_VALUE ? av_frame->pts : av_frame->best_effort_timestamp;
  if (pts != AV_NOPTS_VALUE) {
    // Convert from stream timebase to microseconds
    output_frame.pts_us = static_cast<int64_t>((pts - audio_start_time_) * audio_time_base_ * 1'000'000.0);
  } else {
    output_frame.pts_us = 0;
  }

  // Resize data to actual converted size
  output_frame.data.resize(samples_converted * out_channels * out_sample_size);

  return true;
}

bool FFmpegDecoder::GetPendingAudioFrame(buffer::AudioFrame& output_frame) {
  if (pending_audio_frames_.empty()) {
    return false;
  }
  output_frame = std::move(pending_audio_frames_.front());
  pending_audio_frames_.pop();
  return true;
}

void FFmpegDecoder::UpdateStats(double decode_time_ms) {
  stats_.frames_decoded++;

  // Update average decode time (exponential moving average)
  const double alpha = 0.1;
  stats_.average_decode_time_ms =
      alpha * decode_time_ms + (1.0 - alpha) * stats_.average_decode_time_ms;

  // Calculate current FPS
  if (stats_.average_decode_time_ms > 0.0) {
    stats_.current_fps = 1000.0 / stats_.average_decode_time_ms;
  }
}


// ============================================================================
// Phase 2: PumpDecoderOnce support - helper functions
// ============================================================================

FFmpegDecoder::AVFramePtr FFmpegDecoder::MakeFrame() {
  return AVFramePtr(av_frame_alloc(), FreeAVFrame);
}

FFmpegDecoder::AVPacketPtr FFmpegDecoder::MakePacket(AVPacket* pkt) {
  return AVPacketPtr(pkt, [](AVPacket* p) { av_packet_free(&p); });
}

void FFmpegDecoder::EnqueueScratchToPending() {
  auto f = MakeFrame();
  av_frame_move_ref(f.get(), pump_scratch_frame_);
  pending_video_frames_.push(std::move(f));

  if (pending_video_frames_.size() > pending_video_max_depth_)
    pending_video_max_depth_ = pending_video_frames_.size();
}

void FFmpegDecoder::DrainVideoFrames(int& frames_drained) {
  frames_drained = 0;

  // Release stashed frame first
  if (has_stashed_video_frame_) {
    if (pending_video_frames_.size() < kMaxPendingVideoFrames) {
      pending_video_frames_.push(std::move(stashed_video_frame_));
      has_stashed_video_frame_ = false;
      frames_drained++;

      if (pending_video_frames_.size() > pending_video_max_depth_)
        pending_video_max_depth_ = pending_video_frames_.size();
    } else {
      return;
    }
  }

  while (true) {
    int ret = avcodec_receive_frame(codec_ctx_, pump_scratch_frame_);

    if (ret == AVERROR(EAGAIN)) break;
    if (ret == AVERROR_EOF) {
      video_codec_flushed_ = true;
      break;
    }
    if (ret < 0) {
      stats_.decode_errors++;
      break;
    }

    if (pending_video_frames_.size() < kMaxPendingVideoFrames) {
      EnqueueScratchToPending();
      frames_drained++;
    } else {
      auto f = MakeFrame();
      av_frame_move_ref(f.get(), pump_scratch_frame_);
      stashed_video_frame_ = std::move(f);
      has_stashed_video_frame_ = true;
      break;
    }
  }
}

void FFmpegDecoder::DrainAudioFrames(int& frames_drained) {
  frames_drained = 0;

  if (!audio_codec_ctx_) return;

  while (true) {
    int ret = avcodec_receive_frame(audio_codec_ctx_, audio_frame_);

    if (ret == AVERROR(EAGAIN)) break;
    if (ret == AVERROR_EOF) {
      audio_codec_flushed_ = true;
      break;
    }
    if (ret < 0) break;

    buffer::AudioFrame converted;
    if (ConvertAudioFrame(audio_frame_, converted)) {
      if (pending_audio_frames_.size() < kMaxPendingAudioFrames) {
        pending_audio_frames_.push(std::move(converted));
        frames_drained++;
      }
    }

    av_frame_unref(audio_frame_);
  }
}

// ============================================================================
// Phase 2: PumpDecoderOnce - lossless packet-level backpressure + EOF flush
// ============================================================================

blockplan::PumpResult FFmpegDecoder::PumpDecoderOnce(blockplan::PumpMode mode) {
  using blockplan::PumpMode;
  using blockplan::PumpResult;

  if (mode == PumpMode::kAudioOnlyService) {
    pump_calls_audio_only_++;
  }

  // ========================= EOF FLUSH MODE ==============================

  if (demux_eof_reached_) {

    // Drain deferred packets first
    if (!deferred_video_packets_.empty()) {
      if (pending_video_frames_.size() >= kMaxPendingVideoFrames) {
        pump_backpressure_hits_++;
        return PumpResult::kBackpressured;
      }

      AVPacketPtr pkt = std::move(deferred_video_packets_.front());
      deferred_video_packets_.pop();

      int ret = avcodec_send_packet(codec_ctx_, pkt.get());
      if (ret == AVERROR(EAGAIN)) {
        int drained = 0;
        DrainVideoFrames(drained);
        ret = avcodec_send_packet(codec_ctx_, pkt.get());
      }

      if (ret < 0 && ret != AVERROR(EAGAIN)) {
        stats_.decode_errors++;
        return PumpResult::kError;
      }

      if (ret == AVERROR(EAGAIN)) {
        pump_backpressure_hits_++;
        return PumpResult::kBackpressured;
      }

      int drained = 0;
      DrainVideoFrames(drained);
      return PumpResult::kProgress;
    }

    // Flush video codec
    if (!video_codec_flushed_) {
      int ret = avcodec_send_packet(codec_ctx_, nullptr);
      if (ret == AVERROR(EAGAIN)) {
        int drained = 0;
        DrainVideoFrames(drained);
        ret = avcodec_send_packet(codec_ctx_, nullptr);
      }

      int drained = 0;
      DrainVideoFrames(drained);

      if (drained > 0) {
        return PumpResult::kProgress;
      }
    }

    // Flush audio codec
    if (audio_codec_ctx_ && !audio_codec_flushed_) {
      int ret = avcodec_send_packet(audio_codec_ctx_, nullptr);
      if (ret == AVERROR(EAGAIN)) {
        int drained = 0;
        DrainAudioFrames(drained);
        ret = avcodec_send_packet(audio_codec_ctx_, nullptr);
      }

      int drained = 0;
      DrainAudioFrames(drained);

      if (drained > 0) {
        if (mode == PumpMode::kAudioOnlyService) {
          audio_frames_harvested_in_audio_only_ += drained;
        }
        return PumpResult::kProgress;
      }
    }

    // Done when everything is exhausted
    if (deferred_video_packets_.empty() &&
        !has_stashed_video_frame_ &&
        pending_video_frames_.empty() &&
        video_codec_flushed_ &&
        audio_codec_flushed_) {
      eof_reached_ = true;
      audio_eof_reached_ = true;
      return PumpResult::kEof;
    }

    return PumpResult::kProgress;
  }

  // ========================= NORMAL MODE ==============================

  // Step 1: In normal mode, drain deferred video packets first
  if (mode == PumpMode::kNormal && !deferred_video_packets_.empty()) {
    if (pending_video_frames_.size() >= kMaxPendingVideoFrames) {
      pump_backpressure_hits_++;
      return PumpResult::kBackpressured;
    }

    AVPacketPtr pkt = std::move(deferred_video_packets_.front());
    deferred_video_packets_.pop();

    int ret = avcodec_send_packet(codec_ctx_, pkt.get());
    if (ret == AVERROR(EAGAIN)) {
      int drained = 0;
      DrainVideoFrames(drained);
      ret = avcodec_send_packet(codec_ctx_, pkt.get());
    }

    if (ret < 0 && ret != AVERROR(EAGAIN)) {
      stats_.decode_errors++;
      return PumpResult::kError;
    }

    if (ret == AVERROR(EAGAIN)) {
      pump_backpressure_hits_++;
      return PumpResult::kBackpressured;
    }

    int drained = 0;
    DrainVideoFrames(drained);
    return PumpResult::kProgress;
  }

  // Step 2: Read one packet from demuxer
  AVPacket* raw = av_packet_alloc();
  int ret = av_read_frame(format_ctx_, raw);

  if (ret == AVERROR_EOF) {
    av_packet_free(&raw);
    demux_eof_reached_ = true;
    return PumpResult::kProgress;
  }

  if (ret < 0) {
    av_packet_free(&raw);
    stats_.decode_errors++;
    return PumpResult::kError;
  }

  AVPacketPtr pkt = MakePacket(raw);

  // Step 3: Audio packet
  if (pkt->stream_index == audio_stream_index_ && audio_codec_ctx_) {
    int send_ret = avcodec_send_packet(audio_codec_ctx_, pkt.get());
    if (send_ret == AVERROR(EAGAIN)) {
      int drained = 0;
      DrainAudioFrames(drained);
      send_ret = avcodec_send_packet(audio_codec_ctx_, pkt.get());
    }

    if (send_ret < 0 && send_ret != AVERROR(EAGAIN)) {
      stats_.decode_errors++;
      return PumpResult::kError;
    }

    if (send_ret == AVERROR(EAGAIN)) {
      pump_backpressure_hits_++;
      return PumpResult::kBackpressured;
    }

    int drained = 0;
    DrainAudioFrames(drained);

    if (mode == PumpMode::kAudioOnlyService) {
      audio_frames_harvested_in_audio_only_ += drained;
    }

    return PumpResult::kProgress;
  }

  // Step 4: Video packet
  if (pkt->stream_index == video_stream_index_) {

    // 4a) Audio-only mode: defer video packets losslessly
    if (mode == PumpMode::kAudioOnlyService) {
      if (deferred_video_packets_.size() >= kMaxDeferredVideoPackets) {
        pump_backpressure_hits_++;
        return PumpResult::kBackpressured;
      }
      deferred_video_packets_.push(std::move(pkt));
      if (deferred_video_packets_.size() > deferred_video_max_depth_)
        deferred_video_max_depth_ = deferred_video_packets_.size();
      if (deferred_video_packets_.size() >= (kMaxDeferredVideoPackets * 90) / 100) {
        std::cerr << "[FFmpegDecoder] deferred video packets at 90% capacity ("
                  << deferred_video_packets_.size() << "/" << kMaxDeferredVideoPackets
                  << ")\n";
      }
      return PumpResult::kProgress;
    }

    // 4b) Normal mode: if pending full, defer losslessly
    if (pending_video_frames_.size() >= kMaxPendingVideoFrames) {
      if (deferred_video_packets_.size() >= kMaxDeferredVideoPackets) {
        pump_backpressure_hits_++;
        return PumpResult::kBackpressured;
      }
      deferred_video_packets_.push(std::move(pkt));
      if (deferred_video_packets_.size() > deferred_video_max_depth_)
        deferred_video_max_depth_ = deferred_video_packets_.size();
      return PumpResult::kProgress;
    }

    // 4c) Decode video packet normally
    int send_ret = avcodec_send_packet(codec_ctx_, pkt.get());
    if (send_ret == AVERROR(EAGAIN)) {
      int drained = 0;
      DrainVideoFrames(drained);
      send_ret = avcodec_send_packet(codec_ctx_, pkt.get());
    }

    if (send_ret < 0 && send_ret != AVERROR(EAGAIN)) {
      stats_.decode_errors++;
      return PumpResult::kError;
    }

    if (send_ret == AVERROR(EAGAIN)) {
      pump_backpressure_hits_++;
      return PumpResult::kBackpressured;
    }

    int drained = 0;
    DrainVideoFrames(drained);
    return PumpResult::kProgress;
  }

  // Step 5: Other streams (subtitles/data) skipped
  return PumpResult::kProgress;
}

}  // namespace retrovue::decode

