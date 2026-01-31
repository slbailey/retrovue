// Repository: Retrovue-playout
// Component: Encoder Pipeline
// Purpose: Owns FFmpeg encoder/muxer handles and manages encoding lifecycle.
// Copyright (c) 2025 RetroVue

#include "retrovue/playout_sinks/mpegts/EncoderPipeline.hpp"
#include "retrovue/playout_sinks/mpegts/MpegTSPlayoutSinkConfig.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"

#include <cassert>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <thread>

#ifdef RETROVUE_FFMPEG_AVAILABLE
#include <libavutil/dict.h>
#include <libavutil/time.h>
#include <libavutil/mathematics.h>  // For av_rescale_q
#include <libavutil/log.h>  // For av_log_set_level
#include <libavutil/channel_layout.h>  // For av_channel_layout_from_mask, av_channel_layout_copy
#include <libavutil/samplefmt.h>
#include <libswresample/swresample.h>
#endif

namespace retrovue::playout_sinks::mpegts {

#ifdef RETROVUE_FFMPEG_AVAILABLE
// Set to true to log buffer addresses and allocation sizes (debug builds).
static constexpr bool kEncoderPipelineDebugAlloc = false;

EncoderPipeline::EncoderPipeline(const MpegTSPlayoutSinkConfig& config)
    : config_(config),
      initialized_(false),
      codec_ctx_(nullptr),
      format_ctx_(nullptr),
      video_stream_(nullptr),
      audio_codec_ctx_(nullptr),
      audio_stream_(nullptr),
      audio_frame_(nullptr),
      frame_(nullptr),
      input_frame_(nullptr),
      packet_(nullptr),
      sws_ctx_(nullptr),
      swr_ctx_(nullptr),
      last_input_sample_rate_(0),
      last_input_channels_(0),
      audio_resample_buffer_samples_(0),
      last_seen_audio_pts90k_(AV_NOPTS_VALUE),
      audio_pts_offset_90k_(0),
      frame_width_(0),
      frame_height_(0),
      input_pix_fmt_(AV_PIX_FMT_YUV420P),
      sws_ctx_valid_(false),
      header_written_(false),
      codec_opened_(false),
      muxer_opts_(nullptr),
      last_video_mux_dts_(AV_NOPTS_VALUE),
      last_video_mux_pts_(AV_NOPTS_VALUE),
      last_audio_mux_dts_(AV_NOPTS_VALUE),
      last_audio_mux_pts_(AV_NOPTS_VALUE),
      last_input_pts_(AV_NOPTS_VALUE),
      first_frame_encoded_(false),
      video_frame_count_(0),
      audio_prime_stall_count_(0),
      avio_opaque_(nullptr),
      avio_write_callback_(nullptr),
      custom_avio_ctx_(nullptr),
      output_timing_anchor_set_(false),
      output_timing_anchor_pts_(0),
      output_timing_anchor_wall_(),
      output_timing_enabled_(true),  // P8-IO-001: Enabled by default, disable during prebuffer
      // INV-P9-AUDIO-LIVENESS: Deterministic silence generation state
      real_audio_received_(false),
      silence_injection_active_(false),
      silence_audio_pts_90k_(0),
      silence_frames_generated_(0),
      audio_liveness_enabled_(true) {  // INV-P10-PCR-PACED-MUX: Default on, disable for PCR-paced
  time_base_.num = 1;
  time_base_.den = 90000;  // MPEG-TS timebase is 90kHz
}

EncoderPipeline::~EncoderPipeline() {
  close();
}

bool EncoderPipeline::open(const MpegTSPlayoutSinkConfig& config) {
  return open(config, nullptr, nullptr);
}

bool EncoderPipeline::open(const MpegTSPlayoutSinkConfig& config, 
                            void* opaque,
                            int (*write_callback)(void* opaque, uint8_t* buf, int buf_size)) {
  if (initialized_) {
    return true;  // Already initialized
  }

  if (config.stub_mode) {
    initialized_ = true;
    return true;
  }

  // All-or-nothing: require libx264 so open() fails before allocating when encoder unavailable.
  const AVCodec* codec = avcodec_find_encoder_by_name("libx264");
  if (!codec) {
    std::cerr << "[EncoderPipeline] libx264 not found (required for Phase 8.4)" << std::endl;
    return false;
  }

  av_log_set_level(AV_LOG_ERROR);

  avio_opaque_ = opaque ? opaque : this;
  avio_write_callback_ = write_callback;

  std::string url;
  if (avio_write_callback_) {
    url = "dummy://";
  } else {
    std::ostringstream url_stream;
    url_stream << "tcp://" << config.bind_host << ":" << config.port << "?listen=1";
    url = url_stream.str();
  }

  int ret = avformat_alloc_output_context2(&format_ctx_, nullptr, "mpegts", url.c_str());
  if (ret < 0 || !format_ctx_) {
    char errbuf[AV_ERROR_MAX_STRING_SIZE];
    av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
    std::cerr << "[EncoderPipeline] Failed to allocate output context: " << errbuf << std::endl;
    return false;
  }

  AVDictionary* muxer_opts = nullptr;
  av_dict_set(&muxer_opts, "max_delay", "0", 0);  // No muxer delay for immediate output
  av_dict_set(&muxer_opts, "muxrate", "0", 0);
  muxer_opts_ = muxer_opts;

  if (!config.persistent_mux) {
    av_dict_set(&muxer_opts_, "mpegts_flags", "resend_headers+pat_pmt_at_frames", 0);
  }

  if (avio_write_callback_) {
    // Allocate smaller buffer for AVIO (16KB buffer) to reduce blocking risk
    // Smaller buffer means less data can accumulate before backpressure is felt
    const size_t buffer_size = 16 * 1024;  // 16KB instead of 64KB
    uint8_t* buffer = (uint8_t*)av_malloc(buffer_size);
    if (!buffer) {
      std::cerr << "[EncoderPipeline] Failed to allocate AVIO buffer" << std::endl;
      close();
      return false;
    }
    
    // Create custom AVIO context with write callback
    // Use the provided callback directly (not our wrapper)
    custom_avio_ctx_ = avio_alloc_context(
        buffer, buffer_size, 1, this, nullptr, &EncoderPipeline::AVIOWriteThunk, nullptr);
    if (!custom_avio_ctx_) {
      std::cerr << "[EncoderPipeline] Failed to allocate AVIO context" << std::endl;
      av_free(buffer);
      close();
      return false;
    }
    
    // Explicitly mark as non-blocking (required on some FFmpeg builds)
    custom_avio_ctx_->seekable = 0;
    
    // Set AVIO context on format context
    format_ctx_->pb = custom_avio_ctx_;
    format_ctx_->flags |= AVFMT_FLAG_CUSTOM_IO;
    // Phase 8.9: Force immediate packet writes to avoid buffering delays
    // when audio stream exists but no audio packets are being sent
    format_ctx_->flags |= AVFMT_FLAG_FLUSH_PACKETS;
    // P8-IO-001: Forward Progress Guarantee - disable interleave buffering
    // Forces FFmpeg to write packets immediately instead of buffering for A/V interleaving
    format_ctx_->max_interleave_delta = 0;
    // P8-IO-001: Instruct TS muxer to behave like a live sink
    format_ctx_->flush_packets = 1;
  }

  // Create video stream (codec already validated at start of open())
  video_stream_ = avformat_new_stream(format_ctx_, codec);
  if (!video_stream_) {
    std::cerr << "[EncoderPipeline] Failed to create video stream" << std::endl;
    close();
    return false;
  }

  video_stream_->id = format_ctx_->nb_streams - 1;

  // Allocate codec context
  codec_ctx_ = avcodec_alloc_context3(codec);
  if (!codec_ctx_) {
    std::cerr << "[EncoderPipeline] Failed to allocate codec context" << std::endl;
    close();
    return false;
  }

  // Set codec parameters
  // Note: Frame dimensions will be set from first frame
  codec_ctx_->codec_id = AV_CODEC_ID_H264;
  codec_ctx_->codec_type = AVMEDIA_TYPE_VIDEO;
  codec_ctx_->pix_fmt = AV_PIX_FMT_YUV420P;
  codec_ctx_->bit_rate = config.bitrate;
  codec_ctx_->gop_size = config.gop_size;
  codec_ctx_->max_b_frames = 0;  // No B-frames for low latency
  codec_ctx_->time_base.num = 1;
  codec_ctx_->time_base.den = static_cast<int>(config.target_fps);
  codec_ctx_->framerate.num = static_cast<int>(config.target_fps);
  codec_ctx_->framerate.den = 1;

  // Set stream time base to 90kHz (MPEG-TS standard)
  video_stream_->time_base.num = 1;
  video_stream_->time_base.den = 90000;

  // Copy codec parameters to stream
  ret = avcodec_parameters_from_context(video_stream_->codecpar, codec_ctx_);
  if (ret < 0) {
    char errbuf[AV_ERROR_MAX_STRING_SIZE];
    av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
    std::cerr << "[EncoderPipeline] Failed to copy codec parameters: " << errbuf << std::endl;
    close();
    return false;
  }

  // Phase 8.9: Create audio encoder and stream
  const AVCodec* audio_codec = avcodec_find_encoder_by_name("aac");
  if (!audio_codec) {
    // Try libfdk_aac as fallback
    audio_codec = avcodec_find_encoder_by_name("libfdk_aac");
  }
  if (audio_codec) {
    audio_stream_ = avformat_new_stream(format_ctx_, audio_codec);
    if (!audio_stream_) {
      std::cerr << "[EncoderPipeline] Failed to create audio stream" << std::endl;
      close();
      return false;
    }
    audio_stream_->id = format_ctx_->nb_streams - 1;

    audio_codec_ctx_ = avcodec_alloc_context3(audio_codec);
    if (!audio_codec_ctx_) {
      std::cerr << "[EncoderPipeline] Failed to allocate audio codec context" << std::endl;
      close();
      return false;
    }

    // Set audio codec parameters
    audio_codec_ctx_->codec_id = audio_codec->id;
    audio_codec_ctx_->codec_type = AVMEDIA_TYPE_AUDIO;
    audio_codec_ctx_->sample_fmt = AV_SAMPLE_FMT_FLTP;  // AAC typically uses float planar
    if (audio_codec->sample_fmts) {
      // Use first supported format
      audio_codec_ctx_->sample_fmt = audio_codec->sample_fmts[0];
    }
    audio_codec_ctx_->sample_rate = 48000;  // Standard broadcast rate
    
    // Phase 8.9: Use new FFmpeg API for channel layout (av_channel_layout_from_mask)
    ret = av_channel_layout_from_mask(&audio_codec_ctx_->ch_layout, AV_CH_LAYOUT_STEREO);
    if (ret < 0) {
      char errbuf[AV_ERROR_MAX_STRING_SIZE];
      av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
      std::cerr << "[EncoderPipeline] Failed to set audio channel layout: " << errbuf << std::endl;
      // Fallback: try default layout for 2 channels (av_channel_layout_default returns void)
      av_channel_layout_default(&audio_codec_ctx_->ch_layout, 2);
      // Verify it worked by checking encoder_channels
      if (audio_codec_ctx_->ch_layout.nb_channels != 2) {
        std::cerr << "[EncoderPipeline] Failed to set default channel layout for 2 channels" << std::endl;
        // Continue without audio - will degrade to video-only
        avcodec_free_context(&audio_codec_ctx_);
        audio_codec_ctx_ = nullptr;
        audio_stream_ = nullptr;
        std::cerr << "[EncoderPipeline] Audio encoder initialization failed, continuing with video-only" << std::endl;
        goto skip_audio;  // Skip to video encoder setup
      }
    }
    
    audio_codec_ctx_->bit_rate = 128000;  // 128 kbps
    // Let the codec choose a sensible time base; we'll derive PTS in that base.
    audio_codec_ctx_->time_base.num = 1;
    audio_codec_ctx_->time_base.den = audio_codec_ctx_->sample_rate;

    // For audio, keep the stream time base aligned with the codec time base.
    // The TS muxer will handle conversion to 90kHz internally.
    audio_stream_->time_base = audio_codec_ctx_->time_base;
    
    // Open audio codec (this is where libavcodec will populate extradata for AAC)
    ret = avcodec_open2(audio_codec_ctx_, audio_codec, nullptr);
    if (ret < 0) {
      char errbuf[AV_ERROR_MAX_STRING_SIZE];
      av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
      std::cerr << "[EncoderPipeline] Failed to open audio codec: " << errbuf << std::endl;
      // Degrade gracefully to video-only (don't fail entire encoder)
      avcodec_free_context(&audio_codec_ctx_);
      audio_codec_ctx_ = nullptr;
      if (audio_frame_) {
        av_frame_free(&audio_frame_);
        audio_frame_ = nullptr;
      }
      audio_stream_ = nullptr;
      std::cerr << "[EncoderPipeline] Audio encoder open failed, continuing with video-only" << std::endl;
      goto skip_audio;
    }

    // Copy codec parameters (including extradata) to stream AFTER avcodec_open2.
    ret = avcodec_parameters_from_context(audio_stream_->codecpar, audio_codec_ctx_);
    if (ret < 0) {
      char errbuf[AV_ERROR_MAX_STRING_SIZE];
      av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
      std::cerr << "[EncoderPipeline] Failed to copy audio codec parameters: " << errbuf << std::endl;
      // Degrade gracefully to video-only
      avcodec_free_context(&audio_codec_ctx_);
      audio_codec_ctx_ = nullptr;
      audio_stream_ = nullptr;
      std::cerr << "[EncoderPipeline] Audio encoder setup failed, continuing with video-only" << std::endl;
      goto skip_audio;
    }

    // For container muxers like MPEG-TS, leave codec_tag to 0 so muxer chooses proper tag.
    audio_stream_->codecpar->codec_tag = 0;

    // Allocate audio frame
    audio_frame_ = av_frame_alloc();
    if (!audio_frame_) {
      std::cerr << "[EncoderPipeline] Failed to allocate audio frame" << std::endl;
      close();
      return false;
    }

  } else {
    std::cerr << "[EncoderPipeline] No AAC encoder found, audio disabled" << std::endl;
  }

skip_audio:
  // Continue with video encoder setup even if audio failed

  // Phase 8.6: per-channel fixed resolution. If target_width/height set, open codec once and write header here.
  const bool fixed_dimensions = (config.target_width > 0 && config.target_height > 0);
  std::cout << "[EncoderPipeline] open: target_width=" << config.target_width
            << " target_height=" << config.target_height
            << " fixed_dimensions=" << fixed_dimensions << std::endl;

  // =========================================================================
  // INV-P9-BOOT-LIVENESS: Require dimensions for immediate header write
  // =========================================================================
  // A newly attached sink must emit a decodable transport stream within a
  // bounded time. This requires writing the MPEG-TS header immediately in
  // open(), which requires known dimensions.
  //
  // Dynamic dimensions (deferring header to first frame) violates this
  // invariant because viewers tuning in get no output until first frame.
  // =========================================================================
  if (!fixed_dimensions) {
    std::cerr << "[EncoderPipeline] INV-P9-BOOT-LIVENESS violated: "
              << "dimensions required for immediate header write "
              << "(target_width=" << config.target_width
              << ", target_height=" << config.target_height << ")" << std::endl;
    close();
    return false;
  }

  {
    codec_ctx_->width = config.target_width;
    codec_ctx_->height = config.target_height;
    frame_width_ = config.target_width;
    frame_height_ = config.target_height;
    video_stream_->codecpar->width = config.target_width;
    video_stream_->codecpar->height = config.target_height;
    ret = avcodec_parameters_from_context(video_stream_->codecpar, codec_ctx_);
    if (ret < 0) {
      char errbuf[AV_ERROR_MAX_STRING_SIZE];
      av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
      std::cerr << "[EncoderPipeline] Failed to copy codec parameters (fixed): " << errbuf << std::endl;
      close();
      return false;
    }
    // Set low delay flag to minimize encoder buffering
    codec_ctx_->flags |= AV_CODEC_FLAG_LOW_DELAY;
    // Explicitly set delay to 0 (tells FFmpeg we want immediate output)
    codec_ctx_->delay = 0;

    // VBV-constrained VBR (industry standard for streaming)
    // This allows variable bitrate but limits spikes to prevent decoder buffer issues.
    // vbv-maxrate = 1.5x target gives headroom for complex scenes
    // vbv-bufsize = 1 second of buffer (standard for streaming)
    codec_ctx_->rc_max_rate = config.bitrate;          // Hard cap at target (no headroom)
    codec_ctx_->rc_buffer_size = config.bitrate / 4;   // 0.25 second buffer

    AVDictionary* opts = nullptr;
    av_dict_set(&opts, "preset", "ultrafast", 0);
    // zerolatency tune: disables lookahead, B-frames, and other latency-adding features
    av_dict_set(&opts, "tune", "zerolatency", 0);
    // Force single-threaded encoding to eliminate frame reordering
    av_dict_set(&opts, "threads", "1", 0);
    // VBV-constrained VBR with settings to handle startup:
    // - vbv-init=0.9: Start with buffer nearly full for immediate output
    // - bframes=0: Already set by zerolatency tune
    av_dict_set(&opts, "x264-params",
        "bframes=0:nal-hrd=vbr:vbv-init=0.9",
        0);
    ret = avcodec_open2(codec_ctx_, codec, &opts);
    av_dict_free(&opts);
    if (ret < 0) {
      char errbuf[AV_ERROR_MAX_STRING_SIZE];
      av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
      std::cerr << "[EncoderPipeline] Failed to open codec (fixed): " << errbuf << std::endl;
      close();
      return false;
    }
    codec_opened_ = true;

    // CRITICAL: Re-copy codec parameters AFTER avcodec_open2 to capture extradata (SPS/PPS).
    // Without this, P-frames cannot be decoded because the decoder lacks sequence parameters.
    ret = avcodec_parameters_from_context(video_stream_->codecpar, codec_ctx_);
    if (ret < 0) {
      char errbuf[AV_ERROR_MAX_STRING_SIZE];
      av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
      std::cerr << "[EncoderPipeline] Failed to copy codec parameters after open: " << errbuf << std::endl;
      close();
      return false;
    }
  }

  // Allocate frame, input frame, and packet
  frame_ = av_frame_alloc();
  input_frame_ = av_frame_alloc();
  packet_ = av_packet_alloc();
  if (!frame_ || !input_frame_ || !packet_) {
    std::cerr << "[EncoderPipeline] Failed to allocate frame, input_frame, or packet" << std::endl;
    close();
    return false;
  }
  assert(packet_ != reinterpret_cast<AVPacket*>(frame_) && "packet_ must not alias frame_");
  assert(packet_ != reinterpret_cast<AVPacket*>(input_frame_) && "packet_ must not alias input_frame_");
  if (packet_ == reinterpret_cast<AVPacket*>(input_frame_)) {
    std::cerr << "FATAL: packet_ == input_frame_ immediately after alloc\n";
    std::abort();
  }
  frame_->metadata = nullptr;
  frame_->opaque = nullptr;
  frame_->buf[0] = nullptr;
  input_frame_->data[0] = input_frame_->data[1] = input_frame_->data[2] = nullptr;
  input_frame_->linesize[0] = input_frame_->linesize[1] = input_frame_->linesize[2] = 0;
  if (kEncoderPipelineDebugAlloc) {
    std::cerr << "[EncoderPipeline] open: frame_=" << static_cast<void*>(frame_)
              << " input_frame_=" << static_cast<void*>(input_frame_)
              << " packet_=" << static_cast<void*>(packet_)
              << " muxer_opts_=" << static_cast<void*>(muxer_opts_) << std::endl;
  }

  if (fixed_dimensions) {
    frame_->format = AV_PIX_FMT_YUV420P;
    frame_->width = frame_width_;
    frame_->height = frame_height_;
    ret = av_frame_get_buffer(frame_, 32);
    if (ret < 0) {
      char errbuf[AV_ERROR_MAX_STRING_SIZE];
      av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
      std::cerr << "[EncoderPipeline] Failed to allocate frame buffer (fixed): " << errbuf << std::endl;
      close();
      return false;
    }
    if (!avio_write_callback_ && !(format_ctx_->oformat->flags & AVFMT_NOFILE)) {
      ret = avio_open(&format_ctx_->pb, format_ctx_->url, AVIO_FLAG_WRITE);
      if (ret < 0) {
        char errbuf[AV_ERROR_MAX_STRING_SIZE];
        av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
        std::cerr << "[EncoderPipeline] Failed to open output (fixed): " << errbuf << std::endl;
        close();
        return false;
      }
    }
    // =========================================================================
    // INV-P9-BOOT-LIVENESS: Write header immediately on sink attach
    // =========================================================================
    // A newly attached sink must emit a decodable TS (PAT/PMT + PCR cadence)
    // within N milliseconds, even if audio is not yet available.
    //
    // Previously (INV-P8-AUDIO-PRIME-001), header was deferred until first audio
    // frame to ensure PMT included audio info. This violated boot liveness -
    // viewers tuning in got nothing until audio arrived.
    //
    // Fix: Write header immediately. Video can flow without audio. If audio
    // stream is configured, it will be included in PMT but audio packets
    // simply won't arrive until audio is ready. This is valid MPEG-TS.
    // =========================================================================
    std::cout << "[EncoderPipeline] INV-P9-BOOT-LIVENESS: Writing header immediately" << std::endl;
    std::cout << "[EncoderPipeline] streams=" << format_ctx_->nb_streams
              << " video=" << (video_stream_ ? "yes" : "no")
              << " audio=" << (audio_stream_ ? "yes" : "no") << std::endl;
    ret = avformat_write_header(format_ctx_, &muxer_opts_);
    if (ret < 0) {
      char errbuf[AV_ERROR_MAX_STRING_SIZE];
      av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
      std::cerr << "[EncoderPipeline] Failed to write header (boot): " << errbuf << std::endl;
      close();
      return false;
    }
    if (muxer_opts_) {
      av_dict_free(&muxer_opts_);
      muxer_opts_ = nullptr;
    }
    header_written_ = true;
    std::cout << "[EncoderPipeline] Header written - TS output is now decodable" << std::endl;
  }

  initialized_ = true;
  return true;
}

void EncoderPipeline::EnforceMonotonicDts() {
  if (!packet_) return;

  // OutputContinuity (OutputContinuityContract.md): per-stream monotonic PTS/DTS,
  // minimal correction only (MUST NOT adjust by more than minimum delta).
  bool is_video = video_stream_ && packet_->stream_index == video_stream_->index;
  bool is_audio = audio_stream_ && packet_->stream_index == audio_stream_->index;

  int64_t& last_dts = is_video ? last_video_mux_dts_ : last_audio_mux_dts_;
  int64_t& last_pts = is_video ? last_video_mux_pts_ : last_audio_mux_pts_;

  int64_t dts = packet_->dts;
  int64_t pts = packet_->pts;

  // Minimal correction per stream: only advance to last_* + 1 when violated.
  if (last_dts != AV_NOPTS_VALUE && dts != AV_NOPTS_VALUE && dts <= last_dts)
    dts = last_dts + 1;
  if (last_pts != AV_NOPTS_VALUE && pts != AV_NOPTS_VALUE && pts <= last_pts)
    pts = last_pts + 1;
  // Decoder requirement: PTS must not be before DTS.
  if (pts != AV_NOPTS_VALUE && dts != AV_NOPTS_VALUE && pts < dts)
    pts = dts;

  packet_->dts = dts;
  packet_->pts = pts;
  if (dts != AV_NOPTS_VALUE)
    last_dts = dts;
  if (pts != AV_NOPTS_VALUE)
    last_pts = pts;
}

bool EncoderPipeline::encodeFrame(const retrovue::buffer::Frame& frame, int64_t pts90k) {
  if (!initialized_) {
    return false;
  }

  if (config_.stub_mode) {
    return true;
  }

  // INV-P9-BOOT-LIVENESS: Header is now written in open(), so this should never trigger.
  // If it does, it indicates a bug in the initialization path.
  if (!header_written_) {
    std::cerr << "[EncoderPipeline] BUG: encodeFrame called but header not written. "
              << "This should not happen with INV-P9-BOOT-LIVENESS." << std::endl;
    return false;  // Fail explicitly - this is a bug
  }

  // =========================================================================
  // INV-P9-AUDIO-LIVENESS: Generate silence audio frames up to this video PTS
  // =========================================================================
  // Before encoding each video frame, ensure audio is caught up by generating
  // silence frames if real audio hasn't arrived yet. This ensures:
  // - Continuous, monotonically increasing audio PTS from header write
  // - A/V sync from the very first frame
  // - Seamless transition when real audio arrives
  // =========================================================================
  GenerateSilenceFrames(pts90k);

  // Early validity guard: ignore invalid/control frames (no dereference, no fail).
  if (frame.width <= 0 || frame.height <= 0) {
    std::cerr << "[EncoderPipeline] encodeFrame: ignoring invalid frame "
              << frame.width << "x" << frame.height << std::endl;
    return true;  // Not an error; just ignore
  }
  if (frame.data.empty()) {
    std::cerr << "[EncoderPipeline] encodeFrame: ignoring empty frame data"
              << std::endl;
    return true;
  }
#ifndef NDEBUG
  assert(frame.width > 0 && frame.height > 0 &&
         "encodeFrame called with invalid frame dimensions");
#endif

  // Phase 8.6: per-channel fixed resolution. If already opened at fixed size, scale input to it; no reinit.
  if (frame_width_ > 0 && frame_height_ > 0 && codec_opened_) {
    // CRITICAL: Ensure frame buffer is writable before copying data
    // Without this, the encoder may hold references to the buffer from previous frames
    int wr = av_frame_make_writable(frame_);
    if (wr < 0) {
      char errbuf[AV_ERROR_MAX_STRING_SIZE];
      av_strerror(wr, errbuf, AV_ERROR_MAX_STRING_SIZE);
      std::cerr << "[EncoderPipeline] av_frame_make_writable failed (fixed path): " << errbuf << std::endl;
      return false;
    }

    const bool needs_scale = (frame.width != frame_width_ || frame.height != frame_height_);

    if (needs_scale) {
      size_t y_size = static_cast<size_t>(frame.width) * static_cast<size_t>(frame.height);
      size_t uv_size = (frame.width / 2) * (frame.height / 2);
      if (frame.data.size() < y_size + 2 * uv_size) return false;
      if (!sws_ctx_valid_ || sws_ctx_ == nullptr) {
        if (sws_ctx_) { sws_freeContext(sws_ctx_); sws_ctx_ = nullptr; }
        sws_ctx_ = sws_getContext(
            frame.width, frame.height, AV_PIX_FMT_YUV420P,
            frame_width_, frame_height_, AV_PIX_FMT_YUV420P,
            SWS_BILINEAR, nullptr, nullptr, nullptr);
        if (!sws_ctx_) return false;
        sws_ctx_valid_ = true;
      }
      const uint8_t* src[3] = {
          frame.data.data(),
          frame.data.data() + y_size,
          frame.data.data() + y_size + uv_size
      };
      int src_stride[3] = { frame.width, frame.width / 2, frame.width / 2 };
      sws_scale(sws_ctx_, src, src_stride, 0, frame.height, frame_->data, frame_->linesize);
    } else {
      size_t y_size = static_cast<size_t>(frame.width) * static_cast<size_t>(frame.height);
      size_t uv_size = (frame.width / 2) * (frame.height / 2);
      size_t expected_size = y_size + 2 * uv_size;
      if (frame.data.size() < expected_size) return false;
      if (!frame_->data[0] || !frame_->data[1] || !frame_->data[2]) return false;
      const uint8_t* y_plane = frame.data.data();
      for (int y = 0; y < frame.height; ++y) {
        memcpy(frame_->data[0] + y * frame_->linesize[0], y_plane + y * frame.width, static_cast<size_t>(frame.width));
      }
      const uint8_t* u_plane = frame.data.data() + y_size;
      int uv_w = frame.width / 2, uv_h = frame.height / 2;
      for (int y = 0; y < uv_h; ++y) {
        memcpy(frame_->data[1] + y * frame_->linesize[1], u_plane + y * uv_w, static_cast<size_t>(uv_w));
      }
      const uint8_t* v_plane = frame.data.data() + y_size + uv_size;
      for (int y = 0; y < uv_h; ++y) {
        memcpy(frame_->data[2] + y * frame_->linesize[2], v_plane + y * uv_w, static_cast<size_t>(uv_w));
      }
    }
    frame_->format = AV_PIX_FMT_YUV420P;

    // Use source pts90k converted to codec timebase with proper rounding.
    // This keeps video on the same timeline as audio for proper A/V sync.
    AVRational tb90k = {1, 90000};
    int64_t pts = av_rescale_q_rnd(pts90k, tb90k, codec_ctx_->time_base,
                                    static_cast<AVRounding>(AV_ROUND_NEAR_INF | AV_ROUND_PASS_MINMAX));

    // Ensure monotonically increasing PTS (handles rounding collisions)
    if (last_input_pts_ != AV_NOPTS_VALUE && pts <= last_input_pts_) {
      pts = last_input_pts_ + 1;
    }
    last_input_pts_ = pts;
    frame_->pts = pts;
    frame_->metadata = nullptr;
    frame_->opaque = nullptr;

    // Let encoder decide frame type (no forcing)
    frame_->pict_type = AV_PICTURE_TYPE_NONE;

    int send_ret = avcodec_send_frame(codec_ctx_, frame_);
    if (send_ret < 0) {
      if (send_ret == AVERROR(EAGAIN)) {
        constexpr int max_drain_attempts = 5;
        for (int d = 0; d < max_drain_attempts; ++d) {
          int dr = avcodec_receive_packet(codec_ctx_, packet_);
          if (dr == AVERROR(EAGAIN) || dr == AVERROR_EOF) break;
          if (dr < 0) break;
          packet_->stream_index = video_stream_->index;
          av_packet_rescale_ts(packet_, codec_ctx_->time_base, video_stream_->time_base);
          EnforceMonotonicDts();
          GateOutputTiming(packet_->pts);  // Video stream is already 90kHz
          av_interleaved_write_frame(format_ctx_, packet_);
        }
        send_ret = avcodec_send_frame(codec_ctx_, frame_);
      }
      if (send_ret < 0) {
        char errbuf[AV_ERROR_MAX_STRING_SIZE];
        av_strerror(send_ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
        std::cerr << "[EncoderPipeline] Error sending frame (fixed): " << errbuf << std::endl;
        return false;
      }
    }
    // INV-P8-OUTPUT-001: Deterministic Output Liveness
    // Receive all available packets and write to muxer with explicit flush
    constexpr int max_packets_per_frame = 10;
    int n = 0;
    while (n < max_packets_per_frame) {
      int recv_ret = avcodec_receive_packet(codec_ctx_, packet_);
      if (recv_ret == AVERROR(EAGAIN) || recv_ret == AVERROR_EOF) {
        break;
      }
      if (recv_ret < 0) {
        return false;
      }
      ++n;
      packet_->stream_index = video_stream_->index;
      av_packet_rescale_ts(packet_, codec_ctx_->time_base, video_stream_->time_base);
      EnforceMonotonicDts();
      GateOutputTiming(packet_->pts);  // Video stream is already 90kHz
      int write_ret = av_interleaved_write_frame(format_ctx_, packet_);
      if (write_ret < 0) {
        char errbuf[AV_ERROR_MAX_STRING_SIZE];
        av_strerror(write_ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
        std::cerr << "[EncoderPipeline] write_frame failed: " << errbuf << std::endl;
      }
    }
    // INV-P8-OUTPUT-001: Explicit flush - output must not depend on muxer buffering
    if (n > 0 && format_ctx_->pb) {
      avio_flush(format_ctx_->pb);
    }
    return true;
  }

  // Check if codec needs to be opened (first frame or dimensions changed)
  if (!codec_ctx_->width || !codec_ctx_->height || 
      codec_ctx_->width != frame.width || codec_ctx_->height != frame.height) {
    
    const AVCodec* codec = avcodec_find_encoder_by_name("libx264");
    if (!codec) {
      std::cerr << "[EncoderPipeline] libx264 not found" << std::endl;
      return false;
    }

    // Re-create codec context when dimensions change (avcodec_close is deprecated in FFmpeg 6.x).
    if (codec_ctx_->width > 0 && codec_ctx_->height > 0) {
      avcodec_free_context(&codec_ctx_);
      codec_ctx_ = avcodec_alloc_context3(codec);
      if (!codec_ctx_) {
        std::cerr << "[EncoderPipeline] Failed to re-allocate codec context" << std::endl;
        return false;
      }
      codec_ctx_->codec_id = AV_CODEC_ID_H264;
      codec_ctx_->codec_type = AVMEDIA_TYPE_VIDEO;
      codec_ctx_->pix_fmt = AV_PIX_FMT_YUV420P;
      codec_ctx_->bit_rate = config_.bitrate;
      codec_ctx_->gop_size = config_.gop_size;
      codec_ctx_->max_b_frames = 0;
      codec_ctx_->time_base.num = 1;
      codec_ctx_->time_base.den = static_cast<int>(config_.target_fps);
      codec_ctx_->framerate.num = static_cast<int>(config_.target_fps);
      codec_ctx_->framerate.den = 1;
      codec_opened_ = false;
      // Only unref if this frame ever had buffers (av_frame_get_buffer sets buf[0]); never unref freshly alloc'd frame.
      if (frame_->buf[0] != nullptr) {
        av_frame_unref(frame_);
      }
      // Invalidate swscale context (will be recreated with new dimensions)
      if (sws_ctx_) {
        sws_freeContext(sws_ctx_);
        sws_ctx_ = nullptr;
      }
      sws_ctx_valid_ = false;
    }
    
    // We do not allocate input_frame_->data in this pipeline; only frame_ is used for encode.

    // Set dimensions
    codec_ctx_->width = frame.width;
    codec_ctx_->height = frame.height;
    frame_width_ = frame.width;
    frame_height_ = frame.height;

    // Update stream codec parameters
    video_stream_->codecpar->width = frame.width;
    video_stream_->codecpar->height = frame.height;

    // Re-copy codec parameters to stream (with new dimensions)
    int ret = avcodec_parameters_from_context(video_stream_->codecpar, codec_ctx_);
    if (ret < 0) {
      char errbuf[AV_ERROR_MAX_STRING_SIZE];
      av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
      std::cerr << "[EncoderPipeline] Failed to copy codec parameters: " << errbuf << std::endl;
      return false;
    }

    // Set low delay flag to minimize encoder buffering
    codec_ctx_->flags |= AV_CODEC_FLAG_LOW_DELAY;
    // Explicitly set delay to 0 (tells FFmpeg we want immediate output)
    codec_ctx_->delay = 0;

    // VBV-constrained VBR (industry standard for streaming)
    codec_ctx_->rc_max_rate = config_.bitrate;          // Hard cap at target
    codec_ctx_->rc_buffer_size = config_.bitrate / 4;   // 0.25 second buffer

    // Set encoder options for streaming
    AVDictionary* opts = nullptr;
    av_dict_set(&opts, "preset", "ultrafast", 0);
    // Force single-threaded encoding to eliminate frame reordering
    av_dict_set(&opts, "threads", "1", 0);
    // VBV-constrained VBR with settings to handle startup/fade-in
    av_dict_set(&opts, "x264-params",
        "rc-lookahead=10:sync-lookahead=0:bframes=0:nal-hrd=vbr:vbv-init=0.5:qpmin=18",
        0);

    // Open codec with options
    ret = avcodec_open2(codec_ctx_, codec, &opts);
    if (ret < 0) {
      char errbuf[AV_ERROR_MAX_STRING_SIZE];
      av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
      std::cerr << "[EncoderPipeline] Failed to open codec: " << errbuf << std::endl;
      av_dict_free(&opts);
      return false;
    }
    codec_opened_ = true;

    // Free options dictionary (options are now applied to codec context)
    // Note: avcodec_open2 consumes the options, so we free the dictionary
    av_dict_free(&opts);

    // Sanity check: avoid allocation with invalid dimensions (can cause get_buffer to fail or corrupt).
    if (frame.width <= 0 || frame.height <= 0 ||
        frame.width > 32767 || frame.height > 32767) {
      std::cerr << "[EncoderPipeline] Invalid frame dimensions: " << frame.width << "x" << frame.height << std::endl;
      avcodec_close(codec_ctx_);
      codec_opened_ = false;
      return false;
    }
    // Only unref if frame_ ever had buffers; never call av_frame_unref on a freshly allocated frame (buf[0] set in open()).
    if (frame_->buf[0] != nullptr) {
      av_frame_unref(frame_);
    }
    // Allocate frame buffer via av_frame_get_buffer so FFmpeg owns all buffer memory (no test-owned pointers).
    frame_->format = AV_PIX_FMT_YUV420P;
    frame_->width = frame.width;
    frame_->height = frame.height;
    ret = av_frame_get_buffer(frame_, 32);
    if (ret < 0) {
      char errbuf[AV_ERROR_MAX_STRING_SIZE];
      av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
      std::cerr << "[EncoderPipeline] Failed to allocate frame buffer (" << frame.width << "x" << frame.height
                << "): " << errbuf << std::endl;
      if (kEncoderPipelineDebugAlloc) {
        std::cerr << "[EncoderPipeline] frame_=" << static_cast<void*>(frame_)
                  << " input_frame_=" << static_cast<void*>(input_frame_)
                  << " packet_=" << static_cast<void*>(packet_)
                  << " expected_YUV420P_bytes=" << (frame.width * frame.height * 3 / 2) << std::endl;
      }
      avcodec_close(codec_ctx_);
      codec_opened_ = false;
      return false;  // Do not touch frame_->data; caller may call close() next.
    }
    if (kEncoderPipelineDebugAlloc) {
      std::cerr << "[EncoderPipeline] get_buffer ok frame_=" << static_cast<void*>(frame_)
                << " linesize[0]=" << frame_->linesize[0] << " [1]=" << frame_->linesize[1]
                << " [2]=" << frame_->linesize[2] << std::endl;
    }

    // Invalidate swscale context (will be recreated after input_frame_ is allocated)
    if (sws_ctx_) {
      sws_freeContext(sws_ctx_);
      sws_ctx_ = nullptr;
    }
    sws_ctx_valid_ = false;

    // Write header if not already written
    if (!header_written_) {
      // Only open AVIO if using URL mode (not custom AVIO)
      if (!avio_write_callback_ && !(format_ctx_->oformat->flags & AVFMT_NOFILE)) {
        ret = avio_open(&format_ctx_->pb, format_ctx_->url, AVIO_FLAG_WRITE);
        if (ret < 0) {
          char errbuf[AV_ERROR_MAX_STRING_SIZE];
          av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
          std::cerr << "[EncoderPipeline] Failed to open output: " << errbuf << std::endl;
          return false;
        }
      }

      // Write stream header (only on first frame)
      // Note: This may call the write callback, which should be non-blocking
      // If write callback returns EAGAIN, avformat_write_header should handle it
      // Use muxer_opts_ to configure PCR cadence (FE-019)
      ret = avformat_write_header(format_ctx_, &muxer_opts_);
      if (ret < 0) {
        char errbuf[AV_ERROR_MAX_STRING_SIZE];
        av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
        
        // If header write fails with EAGAIN, it means write callback couldn't write
        // This shouldn't block, but log it and return false to retry later
        if (ret == AVERROR(EAGAIN)) {
          std::cerr << "[EncoderPipeline] Header write blocked (EAGAIN) - will retry on next frame" << std::endl;
          return false;  // Retry on next frame
        }
        
        std::cerr << "[EncoderPipeline] Failed to write header: " << errbuf << std::endl;
        return false;
      }
      av_dict_free(&muxer_opts_);
      muxer_opts_ = nullptr;
      header_written_ = true;
    }
  }

  // Treat input frame as ephemeral: copy pixel data only into FFmpeg-owned buffers (no pointers to test-owned data).
  // frame.data is YUV420 planar (Y, U, V planes stored contiguously); copy row-by-row using linesize.
  // Verify frame data size (YUV420P: width*height*3/2)
  size_t y_size = static_cast<size_t>(frame.width) * static_cast<size_t>(frame.height);
  size_t uv_size = (frame.width / 2) * (frame.height / 2);
  size_t expected_size = y_size + 2 * uv_size;

  if (frame.data.size() < expected_size) {
    std::cerr << "[EncoderPipeline] Frame data too small: got " << frame.data.size()
              << " bytes, expected " << expected_size << " bytes" << std::endl;
    return false;
  }
  // Do not write to frame_->data unless all planes are valid (prevents heap smash).
  if (!frame_->data[0] || !frame_->data[1] || !frame_->data[2]) {
    std::cerr << "[EncoderPipeline] Frame data planes not allocated" << std::endl;
    return false;
  }
  if (frame_->linesize[0] < frame.width ||
      frame_->linesize[1] < frame.width / 2 ||
      frame_->linesize[2] < frame.width / 2) {
    std::cerr << "[EncoderPipeline] Invalid linesize: "
              << frame_->linesize[0] << "," << frame_->linesize[1] << "," << frame_->linesize[2]
              << " for " << frame.width << "x" << frame.height << "\n";
    return false;
  }
  int wr = av_frame_make_writable(frame_);
  if (wr < 0) {
    char errbuf[AV_ERROR_MAX_STRING_SIZE];
    av_strerror(wr, errbuf, AV_ERROR_MAX_STRING_SIZE);
    std::cerr << "[EncoderPipeline] av_frame_make_writable failed: " << errbuf << std::endl;
    return false;
  }

  // YUV420P copy: use linesize[] for destination stride, width/2 for U/V; source is contiguous row-length.
  const uint8_t* y_plane = frame.data.data();
  for (int y = 0; y < frame.height; ++y) {
    memcpy(frame_->data[0] + y * frame_->linesize[0],
           y_plane + y * frame.width,
           static_cast<size_t>(frame.width));
  }
  const uint8_t* u_plane = frame.data.data() + y_size;
  int uv_w = frame.width / 2;
  int uv_h = frame.height / 2;
  for (int y = 0; y < uv_h; ++y) {
    memcpy(frame_->data[1] + y * frame_->linesize[1],
           u_plane + y * uv_w,
           static_cast<size_t>(uv_w));
  }
  const uint8_t* v_plane = frame.data.data() + y_size + uv_size;
  for (int y = 0; y < uv_h; ++y) {
    memcpy(frame_->data[2] + y * frame_->linesize[2],
           v_plane + y * uv_w,
           static_cast<size_t>(uv_w));
  }

  // Set frame format explicitly (already YUV420P)
  frame_->format = AV_PIX_FMT_YUV420P;

  // Set frame PTS from pts90k (already in 90kHz units). Enforce strictly increasing so
  // the muxer never sees non-monotonic DTS (codec can emit same DTS for duplicate input PTS).
  AVRational tb90k = {1, 90000};  // 90kHz timebase
  int64_t pts = av_rescale_q(pts90k, tb90k, codec_ctx_->time_base);
  if (last_input_pts_ != AV_NOPTS_VALUE && pts <= last_input_pts_)
    pts = last_input_pts_ + 1;
  last_input_pts_ = pts;
  frame_->pts = pts;

  // Do not manually free frame_->metadata (av_frame_unref/av_frame_free own it). Clear pointers so codec never sees stale refs.
  frame_->metadata = nullptr;
  frame_->opaque = nullptr;

  // Force first frame to be a keyframe (I-frame) to ensure clean stream start
  if (!first_frame_encoded_) {
    frame_->pict_type = AV_PICTURE_TYPE_I;
    first_frame_encoded_ = true;
  } else {
    frame_->pict_type = AV_PICTURE_TYPE_NONE;
  }

  // Send frame to encoder
  int send_ret = avcodec_send_frame(codec_ctx_, frame_);
  if (send_ret < 0) {
    char errbuf[AV_ERROR_MAX_STRING_SIZE];
    av_strerror(send_ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
    
    // EAGAIN means encoder is busy - try to drain packets first
    if (send_ret == AVERROR(EAGAIN)) {
      // Encoder is full - drain packets to make room
      // This handles encoder backpressure
      // Limit drain attempts to prevent infinite loops
      constexpr int max_drain_attempts = 5;
      int drain_attempts = 0;
      
      while (drain_attempts < max_drain_attempts) {
        int drain_ret = avcodec_receive_packet(codec_ctx_, packet_);
        if (drain_ret == AVERROR(EAGAIN) || drain_ret == AVERROR_EOF) {
          break;  // No more packets available
        }
        if (drain_ret < 0) {
          // Error draining - continue anyway
          break;
        }
        
        drain_attempts++;
        
        // Write drained packet
        packet_->stream_index = video_stream_->index;
        av_packet_rescale_ts(packet_, codec_ctx_->time_base, video_stream_->time_base);
        EnforceMonotonicDts();
        GateOutputTiming(packet_->pts);  // Video stream is already 90kHz
        // av_interleaved_write_frame takes ownership and unrefs the packet.
        int write_ret = av_interleaved_write_frame(format_ctx_, packet_);
        if (write_ret == AVERROR(EAGAIN)) {
          break;
        }
        if (write_ret < 0) {
          char write_errbuf[AV_ERROR_MAX_STRING_SIZE];
          av_strerror(write_ret, write_errbuf, AV_ERROR_MAX_STRING_SIZE);
          std::cerr << "[EncoderPipeline] Error writing drained packet: " << write_errbuf << std::endl;
        }
      }
      
      // Try sending frame again after draining
      send_ret = avcodec_send_frame(codec_ctx_, frame_);
      if (send_ret == AVERROR(EAGAIN)) {
        // Still full - frame will be processed on next iteration
        return true;  // Not an error, just backpressure
      }
    }
    
    if (send_ret < 0) {
      // Real error
      std::cerr << "[EncoderPipeline] Error sending frame: " << errbuf << std::endl;
      return false;
    }
  }

  // Receive encoded packets (may produce zero or more packets per input frame)
  // Handle encoder backpressure: EAGAIN means no packet available yet
  // Limit number of packets processed per frame to prevent infinite loops
  constexpr int max_packets_per_frame = 10;  // Safety limit
  int packets_processed = 0;
  
  while (packets_processed < max_packets_per_frame) {
    int recv_ret = avcodec_receive_packet(codec_ctx_, packet_);
    
    if (recv_ret == AVERROR(EAGAIN)) {
      // No packet available yet - this is normal (encoder needs more input)
      // This is backpressure, not an error
      break;
    }
    
    if (recv_ret == AVERROR_EOF) {
      // Encoder is flushed - no more packets
      break;
    }
    
    if (recv_ret < 0) {
      // Real error
      char errbuf[AV_ERROR_MAX_STRING_SIZE];
      av_strerror(recv_ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
      std::cerr << "[EncoderPipeline] Error receiving packet: " << errbuf << std::endl;
      return false;
    }

    packets_processed++;

    // Packet received successfully
    packet_->stream_index = video_stream_->index;
    av_packet_rescale_ts(packet_, codec_ctx_->time_base, video_stream_->time_base);
    EnforceMonotonicDts();
    GateOutputTiming(packet_->pts);  // Video stream is already 90kHz

    // Write packet to muxer.
    // av_interleaved_write_frame takes ownership and unrefs the packet.
    int write_ret = av_interleaved_write_frame(format_ctx_, packet_);

    if (write_ret == AVERROR(EAGAIN)) {
      break;
    }
    if (write_ret < 0) {
      char errbuf[AV_ERROR_MAX_STRING_SIZE];
      av_strerror(write_ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
      std::cerr << "[EncoderPipeline] Error writing packet: " << errbuf << std::endl;
      continue;
    }
  }

  // P8-IO-001: Forward Progress Guarantee - flush periodically to ensure
  // AVIO buffer doesn't hold data waiting for more bytes (every 10 frames)
  // Flush unconditionally - encoder lookahead may delay packet production
  ++video_frame_count_;
  if (format_ctx_->pb && (video_frame_count_ % 10 == 0)) {
    avio_flush(format_ctx_->pb);
  }

  return true;
}

void EncoderPipeline::close() {
  if (!initialized_) return;
  if (config_.stub_mode) {
    initialized_ = false;
    return;
  }

#ifdef RETROVUE_FFMPEG_AVAILABLE
  // Idempotent: prevent double-close (e.g. from destructor) from re-running teardown.
  initialized_ = false;
  last_video_mux_dts_ = AV_NOPTS_VALUE;
  last_video_mux_pts_ = AV_NOPTS_VALUE;
  last_audio_mux_dts_ = AV_NOPTS_VALUE;
  last_audio_mux_pts_ = AV_NOPTS_VALUE;
  last_input_pts_ = AV_NOPTS_VALUE;
  first_frame_encoded_ = false;
  video_frame_count_ = 0;

  if (muxer_opts_) {
    av_dict_free(&muxer_opts_);
    muxer_opts_ = nullptr;
  }
  
  if (codec_ctx_ && codec_opened_ && packet_ &&
      reinterpret_cast<void*>(packet_) != reinterpret_cast<void*>(frame_) &&
      reinterpret_cast<void*>(packet_) != reinterpret_cast<void*>(input_frame_)) {
    avcodec_send_frame(codec_ctx_, nullptr);
    while (true) {
      int ret = avcodec_receive_packet(codec_ctx_, packet_);
      if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF) break;
      if (ret >= 0) {
        packet_->stream_index = video_stream_->index;
        av_packet_rescale_ts(packet_, codec_ctx_->time_base, video_stream_->time_base);
        EnforceMonotonicDts();
        GateOutputTiming(packet_->pts);  // Video stream is already 90kHz
        // av_interleaved_write_frame takes ownership and unrefs the packet.
        int write_ret = av_interleaved_write_frame(format_ctx_, packet_);
        if (write_ret < 0 && write_ret != AVERROR(EAGAIN)) {
          char errbuf[AV_ERROR_MAX_STRING_SIZE];
          av_strerror(write_ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
          std::cerr << "[EncoderPipeline] Error writing flushed packet: " << errbuf << std::endl;
        }
      }
    }
  }

  if (format_ctx_ && header_written_) {
    int ret = av_write_trailer(format_ctx_);
    if (ret < 0) {
      char errbuf[AV_ERROR_MAX_STRING_SIZE];
      av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
      std::cerr << "[EncoderPipeline] Error writing trailer: " << errbuf << std::endl;
    }
  }

  // Close AVIO (do not free custom_avio_ctx_->buffer manually; avio_context_free owns it).
  if (custom_avio_ctx_) {
    avio_context_free(&custom_avio_ctx_);
    custom_avio_ctx_ = nullptr;
    if (format_ctx_) format_ctx_->pb = nullptr;
  } else if (format_ctx_ && format_ctx_->pb && !(format_ctx_->oformat->flags & AVFMT_NOFILE)) {
    avio_closep(&format_ctx_->pb);
  }
  // Null only after AVIO is freed so AVIOWriteThunk (if still called during teardown) sees valid callback/opaque.
  avio_opaque_ = nullptr;
  avio_write_callback_ = nullptr;

  // Free frame_ and input_frame_ exactly once (allocated once in open()). Do not call av_frame_unref after this.
  // Avoid double-free if pointer corruption made packet_ equal to frame_ or input_frame_ (GDB has shown this).
  void* const save_frame = frame_;
  void* const save_input_frame = input_frame_;
  if (frame_) {
    av_frame_free(&frame_);
    frame_ = nullptr;
  }
  if (input_frame_) {
    av_frame_free(&input_frame_);
    input_frame_ = nullptr;
  }
  if (packet_) {
    if (reinterpret_cast<void*>(packet_) == save_frame || reinterpret_cast<void*>(packet_) == save_input_frame) {
      std::cerr << "[EncoderPipeline] FATAL: packet_ aliased frame memory" << std::endl;
    } else {
      av_packet_free(&packet_);
    }
    packet_ = nullptr;
  }
  if (codec_ctx_) {
    avcodec_free_context(&codec_ctx_);
    codec_ctx_ = nullptr;
  }
  if (format_ctx_) {
    avformat_free_context(format_ctx_);
    format_ctx_ = nullptr;
  }

  // Phase 8.9: Clean up audio encoder
  if (audio_frame_) {
    av_frame_free(&audio_frame_);
    audio_frame_ = nullptr;
  }
  if (audio_codec_ctx_) {
    avcodec_free_context(&audio_codec_ctx_);
    audio_codec_ctx_ = nullptr;
  }
  audio_stream_ = nullptr;  // Owned by format_ctx_

  if (sws_ctx_) {
    sws_freeContext(sws_ctx_);
    sws_ctx_ = nullptr;
  }

  // Phase 8.9: Free audio resampler
  if (swr_ctx_) {
    swr_free(&swr_ctx_);
    swr_ctx_ = nullptr;
  }
  
  // Clear audio resample buffer and reset PTS/format tracking
  audio_resample_buffer_.clear();
  audio_resample_buffer_samples_ = 0;
  last_seen_audio_pts90k_ = AV_NOPTS_VALUE;
  audio_pts_offset_90k_ = 0;
  last_input_sample_rate_ = 0;
  last_input_channels_ = 0;
  sws_ctx_valid_ = false;

  video_stream_ = nullptr;
  frame_width_ = 0;
  frame_height_ = 0;
  header_written_ = false;
  audio_prime_stall_count_ = 0;  // Reset diagnostic counter

  // INV-P9-AUDIO-LIVENESS: Reset silence generation state
  real_audio_received_ = false;
  silence_injection_active_ = false;
  silence_audio_pts_90k_ = 0;
  silence_frames_generated_ = 0;
#endif
}

bool EncoderPipeline::IsInitialized() const {
  return initialized_;
}

#ifdef RETROVUE_FFMPEG_AVAILABLE
int EncoderPipeline::AVIOWriteThunk(void* opaque, uint8_t* buf, int buf_size) {
  if (opaque == nullptr) return -1;
  auto* pipeline = reinterpret_cast<EncoderPipeline*>(opaque);
  return pipeline->HandleAVIOWrite(buf, buf_size);
}

int EncoderPipeline::HandleAVIOWrite(uint8_t* buf, int buf_size) {
  static int write_count = 0;
  static int64_t total_bytes = 0;
  write_count++;
  total_bytes += buf_size;
  if (write_count <= 5 || write_count % 100 == 0) {
    std::cout << "[EncoderPipeline] AVIO_WRITE #" << write_count
              << " bytes=" << buf_size << " total=" << total_bytes << std::endl;
  }
  if (!avio_write_callback_) return -1;
  return avio_write_callback_(avio_opaque_, buf, buf_size);
}
#endif  // RETROVUE_FFMPEG_AVAILABLE

// =========================================================================
// INV-P9-AUDIO-LIVENESS: Generate deterministic silence audio frames
// =========================================================================
// From the moment the MPEG-TS header is written, output MUST contain
// continuous, monotonically increasing audio PTS. If no real audio is
// available, silence frames are injected to maintain A/V sync.
// - 1024 samples at encoder rate (48kHz)
// - PTS monotonically increasing, aligned to video CT
// - Seamless transition when real audio arrives (no discontinuity)
// =========================================================================
#ifdef RETROVUE_FFMPEG_AVAILABLE
void EncoderPipeline::GenerateSilenceFrames(int64_t target_pts_90k) {
  // INV-P10-PCR-PACED-MUX: When audio liveness is disabled, never inject silence.
  // Producer audio is authoritative; if audio queue is empty, mux should stall.
  if (!audio_liveness_enabled_) {
    return;
  }

  // Only generate if we haven't received real audio yet
  if (real_audio_received_) {
    return;
  }

  // Need audio encoder to be ready
  if (!audio_codec_ctx_ || !audio_stream_ || !audio_frame_ || !packet_ || !header_written_) {
    return;
  }

  const int encoder_sample_rate = audio_codec_ctx_->sample_rate;
  const int encoder_channels = audio_codec_ctx_->ch_layout.nb_channels;
  const int frame_size = audio_codec_ctx_->frame_size > 0 ? audio_codec_ctx_->frame_size : 1024;

  // Calculate duration of one audio frame in 90kHz units
  const int64_t frame_duration_90k = (static_cast<int64_t>(frame_size) * 90000) / encoder_sample_rate;

  // INV-P9-AUDIO-LIVENESS: Log when silence injection starts
  if (!silence_injection_active_ && silence_frames_generated_ == 0) {
    std::cout << "INV-P9-AUDIO-LIVENESS: injecting_silence started" << std::endl;
    silence_injection_active_ = true;
  }

  // Generate silence frames until we catch up to the video PTS
  // Add a small buffer (one frame duration) to stay slightly ahead
  const int64_t deadline_pts_90k = target_pts_90k + frame_duration_90k;

  AVRational tb90k{1, 90000};
  AVRational tb_audio = audio_codec_ctx_->time_base;

  while (silence_audio_pts_90k_ < deadline_pts_90k) {
    // Set frame parameters
    audio_frame_->format = audio_codec_ctx_->sample_fmt;
    audio_frame_->sample_rate = encoder_sample_rate;
    int ret = av_channel_layout_copy(&audio_frame_->ch_layout, &audio_codec_ctx_->ch_layout);
    if (ret < 0) {
      std::cerr << "[EncoderPipeline] INV-P9-AUDIO-LIVENESS: Failed to copy channel layout" << std::endl;
      break;
    }
    audio_frame_->nb_samples = frame_size;
    audio_frame_->pts = av_rescale_q(silence_audio_pts_90k_, tb90k, tb_audio);

    // Allocate frame buffer
    ret = av_frame_get_buffer(audio_frame_, 0);
    if (ret < 0) {
      char errbuf[AV_ERROR_MAX_STRING_SIZE];
      av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
      std::cerr << "[EncoderPipeline] INV-P9-AUDIO-LIVENESS: Failed to allocate buffer: " << errbuf << std::endl;
      break;
    }

    // Fill with silence (zeros)
    if (audio_codec_ctx_->sample_fmt == AV_SAMPLE_FMT_S16) {
      // S16 interleaved: zero all samples
      std::memset(audio_frame_->data[0], 0,
                  static_cast<size_t>(frame_size) * static_cast<size_t>(encoder_channels) * sizeof(int16_t));
    } else if (audio_codec_ctx_->sample_fmt == AV_SAMPLE_FMT_FLTP) {
      // Float planar: zero each plane
      for (int c = 0; c < encoder_channels; ++c) {
        std::memset(audio_frame_->data[c], 0, static_cast<size_t>(frame_size) * sizeof(float));
      }
    } else {
      // Fallback: try to zero first plane
      if (audio_frame_->data[0]) {
        std::memset(audio_frame_->data[0], 0, audio_frame_->linesize[0]);
      }
    }

    // Send frame to encoder
    ret = avcodec_send_frame(audio_codec_ctx_, audio_frame_);
    if (ret < 0 && ret != AVERROR(EAGAIN)) {
      char errbuf[AV_ERROR_MAX_STRING_SIZE];
      av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
      std::cerr << "[EncoderPipeline] INV-P9-AUDIO-LIVENESS: Send failed: " << errbuf << std::endl;
      break;
    }

    // Receive and write packets
    while (true) {
      ret = avcodec_receive_packet(audio_codec_ctx_, packet_);
      if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF) break;
      if (ret < 0) break;

      packet_->stream_index = audio_stream_->index;
      av_packet_rescale_ts(packet_, audio_codec_ctx_->time_base, audio_stream_->time_base);
      EnforceMonotonicDts();

      // Convert audio PTS to 90kHz for output timing
      int64_t audio_pts_90k = av_rescale_q(packet_->pts, audio_stream_->time_base, tb90k);
      GateOutputTiming(audio_pts_90k);

      int write_ret = av_interleaved_write_frame(format_ctx_, packet_);
      if (write_ret < 0) {
        char errbuf[AV_ERROR_MAX_STRING_SIZE];
        av_strerror(write_ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
        std::cerr << "[EncoderPipeline] INV-P9-AUDIO-LIVENESS: Write failed: " << errbuf << std::endl;
      }
    }

    // Advance PTS for next silence frame
    silence_audio_pts_90k_ += frame_duration_90k;
    silence_frames_generated_++;

    // Unref frame for next iteration
    av_frame_unref(audio_frame_);
  }

  // Log progress periodically (metric: retrovue_audio_silence_frames_injected_total)
  if (silence_frames_generated_ > 0 && (silence_frames_generated_ == 1 || silence_frames_generated_ % 100 == 0)) {
    std::cout << "[EncoderPipeline] INV-P9-AUDIO-LIVENESS: silence_frames_injected="
              << silence_frames_generated_
              << ", audio_pts_90k=" << silence_audio_pts_90k_ << std::endl;
  }
}
#endif  // RETROVUE_FFMPEG_AVAILABLE

#else
// Stub implementations when FFmpeg is not available

EncoderPipeline::EncoderPipeline(const MpegTSPlayoutSinkConfig& config)
    : config_(config), initialized_(false) {
}

EncoderPipeline::~EncoderPipeline() {
  close();
}

bool EncoderPipeline::open(const MpegTSPlayoutSinkConfig& config) {
  if (initialized_) {
    return true;
  }

  std::cerr << "[EncoderPipeline] ERROR: FFmpeg not available. Rebuild with FFmpeg to enable real encoding." << std::endl;
  initialized_ = true;  // Allow stub mode to continue
  return true;
}

bool EncoderPipeline::encodeFrame(const retrovue::buffer::Frame& frame, int64_t pts90k) {
  if (!initialized_) {
    return false;
  }

  return true;
}

void EncoderPipeline::close() {
  if (!initialized_) {
    return;
  }
  initialized_ = false;
}

bool EncoderPipeline::IsInitialized() const {
  return initialized_;
}

#endif  // RETROVUE_FFMPEG_AVAILABLE

// Phase 8.9: Encode audio frame and mux into MPEG-TS
bool EncoderPipeline::encodeAudioFrame(const retrovue::buffer::AudioFrame& audio_frame, int64_t pts90k) {
  if (!initialized_ || config_.stub_mode) {
    return false;
  }

#ifdef RETROVUE_FFMPEG_AVAILABLE
  if (!audio_codec_ctx_ || !audio_stream_ || !audio_frame_ || !packet_) {
    return false;  // Audio encoder not initialized
  }

  // INV-P9-BOOT-LIVENESS: Header is now written in open(), so this should never trigger.
  // If it does, it indicates a bug in the initialization path.
  if (!header_written_) {
    std::cerr << "[EncoderPipeline] BUG: encodeAudioFrame called but header not written. "
              << "This should not happen with INV-P9-BOOT-LIVENESS." << std::endl;
    return false;  // Fail explicitly - this is a bug
  }

  // Phase 8.9: Handle sample rate AND channel conversion if input differs from encoder
  const int input_sample_rate = audio_frame.sample_rate;
  const int input_channels = audio_frame.channels;
  const int encoder_sample_rate = audio_codec_ctx_->sample_rate;
  const int encoder_channels = audio_codec_ctx_->ch_layout.nb_channels;

  // Validate input - skip invalid frames to avoid crashes
  if (input_sample_rate <= 0 || input_channels <= 0 || audio_frame.nb_samples <= 0) {
    static int invalid_frame_count = 0;
    if (++invalid_frame_count <= 5) {
      std::cerr << "[EncoderPipeline] Skipping invalid audio frame: sample_rate="
                << input_sample_rate << ", channels=" << input_channels
                << ", samples=" << audio_frame.nb_samples << std::endl;
    }
    return true;  // Skip, not a fatal error
  }

  // INV-P9-AUDIO-LIVENESS: Mark that real audio has arrived.
  // From this point, we stop generating silence and use real audio.
  if (!real_audio_received_) {
    real_audio_received_ = true;
    if (silence_injection_active_) {
      std::cout << "INV-P9-AUDIO-LIVENESS: injecting_silence ended (real_audio_ready=true)"
                << ", total_silence_frames=" << silence_frames_generated_ << std::endl;
      silence_injection_active_ = false;
    }
  }

  // Handle sample rate OR channel count changes: clear buffer and reset resampler state
  const bool sample_rate_changed = (last_input_sample_rate_ != input_sample_rate);
  const bool channels_changed = (last_input_channels_ != input_channels);
  const bool audio_format_changed = sample_rate_changed || channels_changed;
  const bool needs_resampling = (input_sample_rate != encoder_sample_rate) ||
                                (input_channels != encoder_channels);
  
  if (audio_format_changed) {
    std::cout << "[EncoderPipeline] AUDIO_FORMAT_CHANGE: "
              << last_input_sample_rate_ << "Hz/" << last_input_channels_ << "ch -> "
              << input_sample_rate << "Hz/" << input_channels << "ch"
              << " (buffered_samples=" << audio_resample_buffer_samples_
              << ", swr_ctx=" << (swr_ctx_ ? "yes" : "no") << ")" << std::endl;
    // IMPORTANT: Encode any buffered samples from the PREVIOUS producer before switching!
    // These are already-resampled samples waiting to fill a complete AAC frame.
    // We need to encode them (padded with silence if needed) to avoid losing audio.
    if (audio_resample_buffer_samples_ > 0) {
      const int frame_size = audio_codec_ctx_->frame_size;
      AVRational tb90k{1, 90000};
      AVRational tb_audio = audio_codec_ctx_->time_base;

      // Get current PTS to continue from
      int64_t flush_pts90k = 0;
      if (last_audio_mux_dts_ != AV_NOPTS_VALUE && audio_stream_) {
        flush_pts90k = av_rescale_q(last_audio_mux_dts_, audio_stream_->time_base, tb90k);
        int64_t frame_duration_90k = (static_cast<int64_t>(frame_size) * 90000) / encoder_sample_rate;
        flush_pts90k += frame_duration_90k;
      }

      // Pad buffered samples with silence to make a complete frame
      int samples_to_pad = frame_size - audio_resample_buffer_samples_;
      if (samples_to_pad > 0 && samples_to_pad < frame_size) {
        audio_resample_buffer_.resize(frame_size * encoder_channels, 0);
        audio_resample_buffer_samples_ = frame_size;
      }

      // Now encode the padded frame
      if (audio_resample_buffer_samples_ >= frame_size) {
        audio_frame_->format = audio_codec_ctx_->sample_fmt;
        audio_frame_->sample_rate = encoder_sample_rate;
        av_channel_layout_copy(&audio_frame_->ch_layout, &audio_codec_ctx_->ch_layout);
        audio_frame_->nb_samples = frame_size;
        audio_frame_->pts = av_rescale_q(flush_pts90k, tb90k, tb_audio);

        int ret = av_frame_get_buffer(audio_frame_, 0);
        if (ret >= 0) {
          // Convert and copy the samples
          if (audio_codec_ctx_->sample_fmt == AV_SAMPLE_FMT_S16) {
            std::memcpy(audio_frame_->data[0], audio_resample_buffer_.data(),
                        frame_size * encoder_channels * sizeof(int16_t));
          } else if (audio_codec_ctx_->sample_fmt == AV_SAMPLE_FMT_FLTP) {
            for (int c = 0; c < encoder_channels; ++c) {
              float* dst_plane = reinterpret_cast<float*>(audio_frame_->data[c]);
              for (int i = 0; i < frame_size; ++i) {
                dst_plane[i] = static_cast<float>(audio_resample_buffer_[i * encoder_channels + c]) / 32768.0f;
              }
            }
          }

          ret = avcodec_send_frame(audio_codec_ctx_, audio_frame_);
          if (ret >= 0 || ret == AVERROR(EAGAIN)) {
            // Drain packets
            while (true) {
              ret = avcodec_receive_packet(audio_codec_ctx_, packet_);
              if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF) break;
              if (ret < 0) break;
              packet_->stream_index = audio_stream_->index;
              av_packet_rescale_ts(packet_, audio_codec_ctx_->time_base, audio_stream_->time_base);
              EnforceMonotonicDts();
              // Convert audio PTS to 90kHz for consistent output timing
              int64_t pts_90k = av_rescale_q(packet_->pts, audio_stream_->time_base, {1, 90000});
              GateOutputTiming(pts_90k);
              av_interleaved_write_frame(format_ctx_, packet_);
            }
          }
        }
      }

      // Now clear the buffer
      audio_resample_buffer_.clear();
      audio_resample_buffer_samples_ = 0;
    }

    // Flush and free existing resampler before switching
    if (swr_ctx_) {
      // Flush any remaining samples from the old resampler and ADD them to be encoded
      int64_t delay = swr_get_delay(swr_ctx_, last_input_sample_rate_);
      if (delay > 0) {
        int64_t flush_samples = av_rescale_rnd(delay, encoder_sample_rate, last_input_sample_rate_, AV_ROUND_UP);
        if (flush_samples > 0) {
          std::vector<uint8_t> flush_buffer(flush_samples * encoder_channels * sizeof(int16_t));
          uint8_t* out_data[1] = {flush_buffer.data()};
          swr_convert(swr_ctx_, out_data, flush_samples, nullptr, 0);
        }
      }
      swr_free(&swr_ctx_);
      swr_ctx_ = nullptr;
    }

    // Only reset output timing on ACTUAL format changes (not first frame)
    // First frame has last_input_sample_rate_=0, which isn't a real producer switch
    if (last_input_sample_rate_ > 0) {
      ResetOutputTiming();
      std::cout << "[EncoderPipeline] Output timing anchor reset for new producer" << std::endl;
    }

    last_input_sample_rate_ = input_sample_rate;
    last_input_channels_ = input_channels;
  }
  
  // Create resampler when needed for sample rate OR channel conversion
  if (needs_resampling && !swr_ctx_) {
    // Create resampler: S16 interleaved @ input config → S16 interleaved @ encoder config
    AVChannelLayout src_ch_layout, dst_ch_layout;

    // Source layout: from input's channel count (mono, stereo, etc.)
    if (input_channels == 1) {
      av_channel_layout_from_mask(&src_ch_layout, AV_CH_LAYOUT_MONO);
    } else if (input_channels == 2) {
      av_channel_layout_from_mask(&src_ch_layout, AV_CH_LAYOUT_STEREO);
    } else {
      // Fallback for other channel counts
      av_channel_layout_default(&src_ch_layout, input_channels);
    }

    // Destination layout: encoder's layout (always stereo for our AAC encoder)
    av_channel_layout_copy(&dst_ch_layout, &audio_codec_ctx_->ch_layout);

    std::cout << "[EncoderPipeline] Creating audio resampler: "
              << input_sample_rate << "Hz/" << input_channels << "ch -> "
              << encoder_sample_rate << "Hz/" << encoder_channels << "ch" << std::endl;

    swr_ctx_ = swr_alloc();
    if (!swr_ctx_) {
      std::cerr << "[EncoderPipeline] Failed to allocate resampler context" << std::endl;
      av_channel_layout_uninit(&src_ch_layout);
      av_channel_layout_uninit(&dst_ch_layout);
      return false;
    }

    int swr_ret = swr_alloc_set_opts2(&swr_ctx_,
                                      &dst_ch_layout, AV_SAMPLE_FMT_S16, encoder_sample_rate,
                                      &src_ch_layout, AV_SAMPLE_FMT_S16, input_sample_rate,
                                      0, nullptr);
    av_channel_layout_uninit(&src_ch_layout);
    av_channel_layout_uninit(&dst_ch_layout);

    if (swr_ret < 0) {
      std::cerr << "[EncoderPipeline] Failed to set resampler options" << std::endl;
      swr_free(&swr_ctx_);
      swr_ctx_ = nullptr;
      return false;
    }

    if (swr_init(swr_ctx_) < 0) {
      std::cerr << "[EncoderPipeline] Failed to initialize resampler" << std::endl;
      swr_free(&swr_ctx_);
      swr_ctx_ = nullptr;
      return false;
    }

  } else if (!needs_resampling && swr_ctx_) {
    // Input matches encoder config exactly, free unneeded resampler
    std::cout << "[EncoderPipeline] Freeing unneeded resampler (input now matches encoder)" << std::endl;
    swr_free(&swr_ctx_);
    swr_ctx_ = nullptr;
  }
  
  // AAC encoder has a fixed frame_size (typically 1024 samples).
  // ALL frames except the very last one MUST be exactly frame_size.
  // We buffer partial samples from resampling and only send complete frames.
  const int frame_size = audio_codec_ctx_->frame_size > 0 ? audio_codec_ctx_->frame_size : 1024;
  
  // Resample if needed (output will be S16 interleaved @ encoder_rate)
  std::vector<uint8_t> resampled_data;
  const uint8_t* src_data = audio_frame.data.data();
  int src_nb_samples = audio_frame.nb_samples;
  int dst_nb_samples = 0;
  
  if (swr_ctx_) {
    // Calculate output sample count after resampling
    dst_nb_samples = static_cast<int>(av_rescale_rnd(
        src_nb_samples, encoder_sample_rate, input_sample_rate, AV_ROUND_UP));
    
    // Allocate resampled buffer (S16 interleaved)
    const size_t resampled_size = static_cast<size_t>(dst_nb_samples) *
                                  static_cast<size_t>(encoder_channels) *
                                  sizeof(int16_t);
    resampled_data.resize(resampled_size);
    
    // Resample
    const uint8_t* in_data[1] = {src_data};
    uint8_t* out_data[1] = {resampled_data.data()};
    int ret = swr_convert(swr_ctx_, out_data, dst_nb_samples, in_data, src_nb_samples);
    if (ret < 0) {
      char errbuf[AV_ERROR_MAX_STRING_SIZE];
      av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
      std::cerr << "[EncoderPipeline] Resampling failed: " << errbuf << std::endl;
      return false;
    }
    dst_nb_samples = ret;  // Actual samples produced

    // Use resampled data as source
    src_data = resampled_data.data();
    src_nb_samples = dst_nb_samples;
  } else if (needs_resampling) {
    // This should never happen - if resampling is needed, swr_ctx_ should exist
    std::cerr << "[EncoderPipeline] ERROR: Resampling needed but no resampler context!" << std::endl;
    return false;
  }
  
  // Prepend any buffered samples from previous call, then append new samples
  // If sample rate changed, buffer was already cleared above
  std::vector<int16_t> combined_samples;
  const int16_t* new_samples = reinterpret_cast<const int16_t*>(src_data);

  if (audio_resample_buffer_samples_ > 0) {
    // We have buffered samples from previous call - prepend them
    combined_samples.reserve((audio_resample_buffer_samples_ + src_nb_samples) * encoder_channels);
    combined_samples.insert(combined_samples.end(),
                            audio_resample_buffer_.begin(),
                            audio_resample_buffer_.begin() + audio_resample_buffer_samples_ * encoder_channels);
    combined_samples.insert(combined_samples.end(),
                            new_samples,
                            new_samples + src_nb_samples * encoder_channels);
    audio_resample_buffer_samples_ = 0;  // Clear buffer after prepending
  } else {
    // No buffered samples, just use new samples directly
    combined_samples.reserve(src_nb_samples * encoder_channels);
    combined_samples.insert(combined_samples.end(),
                            new_samples,
                            new_samples + src_nb_samples * encoder_channels);
  }
  
  int total_samples = static_cast<int>(combined_samples.size()) / encoder_channels;
  const int16_t* samples_ptr = combined_samples.data();
  int samples_remaining = total_samples;
  int64_t current_pts90k = pts90k;
  
  // Enforce PTS continuity: if we've already muxed packets and this PTS is very low,
  // it's likely a new producer starting. Adjust it to continue from last muxed PTS.
  // Convert last_mux_dts_ from stream timebase to 90kHz for comparison
  AVRational tb90k{1, 90000};

  // Producer switch detection: We need to detect when a NEW producer starts (PTS resets to low value)
  // and calculate an offset to rebase its PTS to continue from where we left off.
  //
  // Key insight: After a switch, ALL frames from the new producer will have "low" PTS values
  // relative to the muxed stream. We must NOT re-detect a switch on every frame!
  //
  // Solution: Track the PTS offset that converts producer PTS → muxed PTS.
  // A switch is detected when incoming PTS is MUCH lower than what we'd expect from the
  // current producer (i.e., lower than previous incoming PTS by a large margin).

  bool is_first_frame_of_new_producer = false;

  // Detect switch by comparing to PREVIOUS INCOMING PTS (not muxed PTS)
  // This detects when the source timeline resets/jumps backward significantly
  if (last_seen_audio_pts90k_ != AV_NOPTS_VALUE) {
    // A backward jump of more than 5 seconds indicates a producer switch
    // (normal playback only moves forward or has small jitter)
    const int64_t backward_threshold = 450000;  // 5 seconds in 90kHz
    if (pts90k < last_seen_audio_pts90k_ - backward_threshold) {
      is_first_frame_of_new_producer = true;
    }
  }

  // Always update last_seen_audio_pts90k_ with the ORIGINAL incoming PTS
  // This tracks the SOURCE timeline, not the muxed timeline
  last_seen_audio_pts90k_ = pts90k;

  // Now handle PTS rebasing for the muxer
  // On a producer switch, we need to calculate the offset to continue from last muxed PTS
  if (is_first_frame_of_new_producer && last_audio_mux_dts_ != AV_NOPTS_VALUE && audio_stream_) {
    // Convert last_audio_mux_dts_ from stream timebase to 90kHz
    int64_t last_muxed_pts90k = av_rescale_q(last_audio_mux_dts_, audio_stream_->time_base, tb90k);

    // Calculate duration of one AAC frame in 90kHz units
    const int frame_size = audio_codec_ctx_->frame_size;
    int64_t frame_duration_90k = (static_cast<int64_t>(frame_size) * 90000) / encoder_sample_rate;

    // Calculate the offset needed to rebase the new producer's PTS
    // New producer's first frame should have PTS = last_muxed + one_frame_duration
    int64_t target_pts = last_muxed_pts90k + frame_duration_90k;
    audio_pts_offset_90k_ = target_pts - pts90k;
  }

  // Apply the PTS offset to get the muxed PTS
  current_pts90k = pts90k + audio_pts_offset_90k_;
  
  // Convert caller's 90kHz PTS into the codec's time base for audio.
  AVRational tb_audio = audio_codec_ctx_->time_base;
  
  // Process samples, sending only complete frame_size chunks
  // Buffer any remainder for the next call
  while (samples_remaining >= frame_size) {
    const int samples_this_frame = frame_size;  // Always exactly frame_size
    
    // Set frame parameters (encoder format and rate)
    audio_frame_->format = audio_codec_ctx_->sample_fmt;
    audio_frame_->sample_rate = encoder_sample_rate;
    int audio_ret = av_channel_layout_copy(&audio_frame_->ch_layout, &audio_codec_ctx_->ch_layout);
    if (audio_ret < 0) {
      std::cerr << "[EncoderPipeline] Failed to copy channel layout to audio frame" << std::endl;
      return false;
    }
    audio_frame_->nb_samples = samples_this_frame;
    audio_frame_->pts = av_rescale_q(current_pts90k, tb90k, tb_audio);

    // Allocate frame buffer if needed
    int ret = av_frame_get_buffer(audio_frame_, 0);
    if (ret < 0) {
      char errbuf[AV_ERROR_MAX_STRING_SIZE];
      av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
      std::cerr << "[EncoderPipeline] Failed to allocate audio frame buffer: " << errbuf << std::endl;
      return false;
    }

    // Copy / convert audio data for this chunk
    if (audio_codec_ctx_->sample_fmt == AV_SAMPLE_FMT_S16) {
      // Direct copy for S16 interleaved → interleaved
      const size_t data_size = static_cast<size_t>(samples_this_frame) *
                               static_cast<size_t>(encoder_channels) *
                               sizeof(int16_t);
      std::memcpy(audio_frame_->data[0], samples_ptr, data_size);
    } else if (audio_codec_ctx_->sample_fmt == AV_SAMPLE_FMT_FLTP) {
      // Convert S16 interleaved → planar float [-1.0, 1.0]
      for (int c = 0; c < encoder_channels; ++c) {
        float* dst_plane = reinterpret_cast<float*>(audio_frame_->data[c]);
        for (int i = 0; i < samples_this_frame; ++i) {
          const int idx = i * encoder_channels + c;
          const int16_t s = samples_ptr[idx];
          // Scale int16 [-32768, 32767] to float [-1.0, 1.0]
          dst_plane[i] = static_cast<float>(s) / 32768.0f;
        }
      }
    } else {
      std::cerr << "[EncoderPipeline] Audio format conversion not implemented for encoder format: "
                << audio_codec_ctx_->sample_fmt << std::endl;
      return false;
    }

    // Send frame to encoder
    ret = avcodec_send_frame(audio_codec_ctx_, audio_frame_);
    if (ret < 0) {
      if (ret == AVERROR(EAGAIN)) {
        // Drain encoder first
        while (true) {
          ret = avcodec_receive_packet(audio_codec_ctx_, packet_);
          if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF) break;
          if (ret < 0) break;
          packet_->stream_index = audio_stream_->index;
          av_packet_rescale_ts(packet_, audio_codec_ctx_->time_base, audio_stream_->time_base);
          EnforceMonotonicDts();
          // Convert audio PTS to 90kHz for consistent output timing
          int64_t audio_pts_90k = av_rescale_q(packet_->pts, audio_stream_->time_base, {1, 90000});
          GateOutputTiming(audio_pts_90k);
          av_interleaved_write_frame(format_ctx_, packet_);
        }
        ret = avcodec_send_frame(audio_codec_ctx_, audio_frame_);
      }
      if (ret < 0) {
        char errbuf[AV_ERROR_MAX_STRING_SIZE];
        av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
        std::cerr << "[EncoderPipeline] Error sending audio frame: " << errbuf << std::endl;
        return false;
      }
    }

    // Receive encoded packets for this chunk
    constexpr int max_packets_per_frame = 10;
    int n = 0;
    while (n < max_packets_per_frame) {
      ret = avcodec_receive_packet(audio_codec_ctx_, packet_);
      if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF) break;
      if (ret < 0) return false;
      ++n;
      packet_->stream_index = audio_stream_->index;
      av_packet_rescale_ts(packet_, audio_codec_ctx_->time_base, audio_stream_->time_base);
      
      // Enforce monotonic DTS for audio
      // If first packet has negative or zero DTS (common with AAC encoder priming),
      // just clamp to 0 and track from there.
      if (last_audio_mux_dts_ == AV_NOPTS_VALUE) {
        if (packet_->dts != AV_NOPTS_VALUE && packet_->dts < 0) {
          packet_->dts = 0;
          if (packet_->pts < packet_->dts) {
            packet_->pts = packet_->dts;
          }
        }
        last_audio_mux_dts_ = (packet_->dts != AV_NOPTS_VALUE) ? packet_->dts : 0;
      }

      EnforceMonotonicDts();
      
      // Convert audio PTS to 90kHz for consistent output timing
      int64_t audio_pts_90k_gate = av_rescale_q(packet_->pts, audio_stream_->time_base, {1, 90000});
      GateOutputTiming(audio_pts_90k_gate);

      int mux_ret = av_interleaved_write_frame(format_ctx_, packet_);
      if (mux_ret < 0) {
        char errbuf[AV_ERROR_MAX_STRING_SIZE];
        av_strerror(mux_ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
        std::cerr << "[EncoderPipeline] Error muxing audio packet: " << errbuf << std::endl;
      }
    }
    
    // Advance pointer and PTS for next chunk
    samples_ptr += samples_this_frame * encoder_channels;
    samples_remaining -= samples_this_frame;

    // Advance PTS by the duration of the chunk we just encoded
    // Duration in 90kHz units = (samples * 90000) / sample_rate
    int64_t chunk_duration_90k = (static_cast<int64_t>(samples_this_frame) * 90000) / encoder_sample_rate;
    current_pts90k += chunk_duration_90k;
  }
  
  // Buffer any remaining samples (< frame_size) for the next call
  // These will be prepended to the next input frame
  if (samples_remaining > 0) {
    audio_resample_buffer_.resize(samples_remaining * encoder_channels);
    std::memcpy(audio_resample_buffer_.data(), samples_ptr,
                samples_remaining * encoder_channels * sizeof(int16_t));
    audio_resample_buffer_samples_ = samples_remaining;
  } else {
    audio_resample_buffer_samples_ = 0;
  }

  // P8-IO-001: Forward Progress Guarantee - flush periodically (every 30 audio encodes)
  // Audio produces packets immediately (no lookahead), so slightly lower cadence is fine
  static int audio_encode_count = 0;
  ++audio_encode_count;
  if (format_ctx_->pb && (audio_encode_count % 30 == 0)) {
    avio_flush(format_ctx_->pb);
  }

  return true;
#else
  return false;
#endif
}

bool EncoderPipeline::flushAudio() {
  if (!initialized_ || config_.stub_mode) {
    return true;  // Nothing to flush
  }

#ifdef RETROVUE_FFMPEG_AVAILABLE
  if (!audio_codec_ctx_ || !audio_stream_ || !audio_frame_ || !packet_) {
    return true;  // Audio encoder not initialized, nothing to flush
  }

  const int encoder_sample_rate = audio_codec_ctx_->sample_rate;
  const int frame_size = audio_codec_ctx_->frame_size;
  const int encoder_channels = audio_codec_ctx_->ch_layout.nb_channels;
  AVRational tb90k{1, 90000};
  AVRational tb_audio = audio_codec_ctx_->time_base;
  
  // Step 1: Flush resampler delay buffer (if resampler exists)
  if (swr_ctx_ && last_input_sample_rate_ > 0) {
    int64_t delay = swr_get_delay(swr_ctx_, last_input_sample_rate_);
    if (delay > 0) {
      // Estimate output samples for the delay
      int64_t flush_samples = av_rescale_rnd(delay, encoder_sample_rate, last_input_sample_rate_, AV_ROUND_UP);
      if (flush_samples > 0) {
        std::vector<uint8_t> flush_buffer(flush_samples * encoder_channels * sizeof(int16_t));
        uint8_t* out_data[1] = { flush_buffer.data() };
        int flushed = swr_convert(swr_ctx_, out_data, flush_samples, nullptr, 0);
        if (flushed > 0) {
          // Add flushed samples to resample buffer
          int16_t* flush_samples_ptr = reinterpret_cast<int16_t*>(flush_buffer.data());
          audio_resample_buffer_.insert(audio_resample_buffer_.end(),
                                        flush_samples_ptr,
                                        flush_samples_ptr + flushed * encoder_channels);
          audio_resample_buffer_samples_ += flushed;
        }
      }
    }
  }

  // Step 2: Encode any remaining buffered samples (including flushed resampler output)
  // Get current PTS from last_audio_mux_dts_ if available, otherwise use a reasonable value
  int64_t current_pts90k = 0;
  if (last_audio_mux_dts_ != AV_NOPTS_VALUE && audio_stream_) {
    current_pts90k = av_rescale_q(last_audio_mux_dts_, audio_stream_->time_base, tb90k);
    // Add duration of one frame to continue from last
    int64_t frame_duration_90k = (static_cast<int64_t>(frame_size) * 90000) / encoder_sample_rate;
    current_pts90k += frame_duration_90k;
  }
  
  // Process any buffered samples
  if (audio_resample_buffer_samples_ > 0) {
    const int16_t* samples_ptr = audio_resample_buffer_.data();
    int samples_remaining = audio_resample_buffer_samples_;
    
    while (samples_remaining >= frame_size) {
      const int samples_this_frame = frame_size;
      
      // Set frame parameters
      audio_frame_->format = audio_codec_ctx_->sample_fmt;
      audio_frame_->sample_rate = encoder_sample_rate;
      int audio_ret = av_channel_layout_copy(&audio_frame_->ch_layout, &audio_codec_ctx_->ch_layout);
      if (audio_ret < 0) {
        std::cerr << "[EncoderPipeline] Failed to copy channel layout during flush" << std::endl;
        break;
      }
      audio_frame_->nb_samples = samples_this_frame;
      audio_frame_->pts = av_rescale_q(current_pts90k, tb90k, tb_audio);
      
      // Allocate frame buffer
      int ret = av_frame_get_buffer(audio_frame_, 0);
      if (ret < 0) {
        std::cerr << "[EncoderPipeline] Failed to allocate audio frame buffer during flush" << std::endl;
        break;
      }
      
      // Copy audio data
      if (audio_codec_ctx_->sample_fmt == AV_SAMPLE_FMT_S16) {
        const size_t data_size = static_cast<size_t>(samples_this_frame) *
                                 static_cast<size_t>(encoder_channels) *
                                 sizeof(int16_t);
        std::memcpy(audio_frame_->data[0], samples_ptr, data_size);
      } else if (audio_codec_ctx_->sample_fmt == AV_SAMPLE_FMT_FLTP) {
        for (int c = 0; c < encoder_channels; ++c) {
          float* dst_plane = reinterpret_cast<float*>(audio_frame_->data[c]);
          for (int i = 0; i < samples_this_frame; ++i) {
            int16_t sample = samples_ptr[i * encoder_channels + c];
            dst_plane[i] = static_cast<float>(sample) / 32768.0f;
          }
        }
      }
      
      // Send to encoder
      ret = avcodec_send_frame(audio_codec_ctx_, audio_frame_);
      if (ret < 0 && ret != AVERROR(EAGAIN)) {
        std::cerr << "[EncoderPipeline] Error sending frame during flush" << std::endl;
        break;
      }
      
      // Drain packets
      while (true) {
        ret = avcodec_receive_packet(audio_codec_ctx_, packet_);
        if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF) break;
        if (ret < 0) break;
        
        packet_->stream_index = audio_stream_->index;
        av_packet_rescale_ts(packet_, audio_codec_ctx_->time_base, audio_stream_->time_base);
        EnforceMonotonicDts();
        // Convert audio PTS to 90kHz for consistent output timing
        int64_t flush_audio_pts_90k = av_rescale_q(packet_->pts, audio_stream_->time_base, {1, 90000});
        GateOutputTiming(flush_audio_pts_90k);
        av_interleaved_write_frame(format_ctx_, packet_);
      }
      
      // Advance PTS and pointer
      int64_t frame_duration_90k = (static_cast<int64_t>(samples_this_frame) * 90000) / encoder_sample_rate;
      current_pts90k += frame_duration_90k;
      samples_ptr += samples_this_frame * encoder_channels;
      samples_remaining -= samples_this_frame;
    }
    
    // Clear buffer (remaining samples < frame_size are discarded - they're incomplete)
    audio_resample_buffer_.clear();
    audio_resample_buffer_samples_ = 0;
  }
  
  // Step 3: Drain any packets already in the encoder (without flushing)
  // Don't send NULL frame here - that puts encoder in EOF state and breaks subsequent frames
  // Instead, just drain any packets that are already ready
  int packets_drained = 0;
  while (true) {
    int ret = avcodec_receive_packet(audio_codec_ctx_, packet_);
    if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF) break;
    if (ret < 0) {
      char errbuf[AV_ERROR_MAX_STRING_SIZE];
      av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
      std::cerr << "[EncoderPipeline] Error receiving packet during flush: " << errbuf << std::endl;
      break;
    }
    
    packets_drained++;
    packet_->stream_index = audio_stream_->index;
    av_packet_rescale_ts(packet_, audio_codec_ctx_->time_base, audio_stream_->time_base);
    EnforceMonotonicDts();
    // Convert audio PTS to 90kHz for consistent output timing
    int64_t drain_audio_pts_90k = av_rescale_q(packet_->pts, audio_stream_->time_base, {1, 90000});
    GateOutputTiming(drain_audio_pts_90k);
    av_interleaved_write_frame(format_ctx_, packet_);
  }

  return true;
#else
  return true;
#endif
}

// OutputTiming: Gate packet emission to enforce real-time delivery discipline.
// Per OutputTimingContract.md:
// - Enforce that output media time does not advance faster than real elapsed time
// - Use a process-local monotonic clock (steady_clock)
// - Gate packet emission to prevent early delivery
// - Late packets emit immediately (no resync)
void EncoderPipeline::GateOutputTiming(int64_t packet_pts_90k) {
#ifdef RETROVUE_FFMPEG_AVAILABLE
  // P8-IO-001: Skip gating during prebuffer phase
  if (!output_timing_enabled_) {
    return;
  }

  // Cannot gate without a valid timestamp
  if (packet_pts_90k == AV_NOPTS_VALUE) {
    return;
  }

  // First packet establishes the timing anchor
  if (!output_timing_anchor_set_) {
    output_timing_anchor_pts_ = packet_pts_90k;
    output_timing_anchor_wall_ = std::chrono::steady_clock::now();
    output_timing_anchor_set_ = true;
    return;  // First packet emits immediately
  }

  // Calculate media time elapsed since anchor (in microseconds)
  // packet_pts is in 90kHz units, convert to microseconds: pts * 1000000 / 90000
  int64_t media_elapsed_us = (packet_pts_90k - output_timing_anchor_pts_) * 1000000 / 90000;

  // Delivery rule (OutputTimingContract.md §5.4):
  // (packet_pts − anchor_output_pts) ≤ (elapsed_wall_time_since_anchor)
  // If packet is early, wait. If late, emit immediately.

  // Use short sleeps (≤2ms) to avoid oversleeping per ChatGPT recommendation
  while (true) {
    auto wall_elapsed = std::chrono::steady_clock::now() - output_timing_anchor_wall_;
    auto wall_us = std::chrono::duration_cast<std::chrono::microseconds>(wall_elapsed).count();

    if (wall_us >= media_elapsed_us) {
      break;  // Real time has caught up to media time
    }

    auto remaining_us = media_elapsed_us - wall_us;
    // Cap sleep to ~2ms to avoid oversleeping and accumulating jitter
    auto sleep_us = std::min<int64_t>(remaining_us, 2000);
    std::this_thread::sleep_for(std::chrono::microseconds(sleep_us));
  }
#else
  (void)packet_pts_90k;
#endif
}

// Reset output timing anchor (per OutputTimingContract.md §6: SwitchToLive Semantics)
// On SwitchToLive:
// - OutputTiming resets its internal timing anchor
// - OutputTiming does not modify output PTS
// - SwitchToLive defines a new output pacing epoch, not a new media timeline
void EncoderPipeline::ResetOutputTiming() {
#ifdef RETROVUE_FFMPEG_AVAILABLE
  output_timing_anchor_set_ = false;
  output_timing_anchor_pts_ = 0;
  // anchor_wall_ will be set on next packet
#endif
}

// P8-IO-001: Enable/disable output timing gating
// Disable during prebuffer phase to allow rapid filling without real-time blocking
void EncoderPipeline::SetOutputTimingEnabled(bool enabled) {
#ifdef RETROVUE_FFMPEG_AVAILABLE
  output_timing_enabled_ = enabled;
  if (enabled) {
    // Reset anchor when re-enabling so timing starts fresh
    output_timing_anchor_set_ = false;
  }
  std::cout << "[EncoderPipeline] Output timing " << (enabled ? "ENABLED" : "DISABLED") << std::endl;
#else
  (void)enabled;
#endif
}

// INV-P10-PCR-PACED-MUX: Enable/disable audio liveness silence injection
// When disabled, no silence frames are generated - producer audio is authoritative.
void EncoderPipeline::SetAudioLivenessEnabled(bool enabled) {
#ifdef RETROVUE_FFMPEG_AVAILABLE
  audio_liveness_enabled_ = enabled;
  std::cout << "[EncoderPipeline] INV-P10-PCR-PACED-MUX: Audio liveness "
            << (enabled ? "ENABLED" : "DISABLED (producer audio authoritative)") << std::endl;
#else
  (void)enabled;
#endif
}

}  // namespace retrovue::playout_sinks::mpegts
