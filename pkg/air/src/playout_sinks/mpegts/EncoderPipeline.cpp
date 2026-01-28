// Repository: Retrovue-playout
// Component: Encoder Pipeline
// Purpose: Owns FFmpeg encoder/muxer handles and manages encoding lifecycle.
// Copyright (c) 2025 RetroVue

#include "retrovue/playout_sinks/mpegts/EncoderPipeline.hpp"
#include "retrovue/playout_sinks/mpegts/MpegTSPlayoutSinkConfig.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"

#include <cassert>
#include <cstdlib>
#include <iostream>
#include <iomanip>
#include <sstream>
#include <cstring>

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
      last_mux_dts_(AV_NOPTS_VALUE),
      last_input_pts_(AV_NOPTS_VALUE),
      avio_opaque_(nullptr),
      avio_write_callback_(nullptr),
      custom_avio_ctx_(nullptr) {
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
    std::cout << "[EncoderPipeline] Stub mode enabled - skipping real encoding" << std::endl;
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
    std::cout << "[EncoderPipeline] Opening encoder pipeline with custom AVIO" << std::endl;
  } else {
    std::ostringstream url_stream;
    url_stream << "tcp://" << config.bind_host << ":" << config.port << "?listen=1";
    url = url_stream.str();
    std::cout << "[EncoderPipeline] Opening encoder pipeline: " << url << std::endl;
  }

  int ret = avformat_alloc_output_context2(&format_ctx_, nullptr, "mpegts", url.c_str());
  if (ret < 0 || !format_ctx_) {
    char errbuf[AV_ERROR_MAX_STRING_SIZE];
    av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
    std::cerr << "[EncoderPipeline] Failed to allocate output context: " << errbuf << std::endl;
    return false;
  }

  AVDictionary* muxer_opts = nullptr;
  av_dict_set(&muxer_opts, "max_delay", "100000", 0);
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
      // Verify it worked by checking nb_channels
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

    std::cout << "[EncoderPipeline] Audio encoder initialized: "
              << "sample_rate=" << audio_codec_ctx_->sample_rate
              << ", channels=" << audio_codec_ctx_->ch_layout.nb_channels
              << ", format=" << audio_codec_ctx_->sample_fmt << std::endl;
  } else {
    std::cerr << "[EncoderPipeline] Warning: No AAC encoder found (aac or libfdk_aac). Audio will be disabled." << std::endl;
  }

skip_audio:
  // Continue with video encoder setup even if audio failed

  // Phase 8.6: per-channel fixed resolution. If target_width/height set, open codec once and write header here.
  const bool fixed_dimensions = (config.target_width > 0 && config.target_height > 0);
  if (!fixed_dimensions) {
    codec_ctx_->width = 0;
    codec_ctx_->height = 0;
  } else {
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
    AVDictionary* opts = nullptr;
    av_dict_set(&opts, "preset", "ultrafast", 0);
    av_dict_set(&opts, "tune", "zerolatency", 0);
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
  std::cerr << "ALLOC frame_=" << frame_
            << " input_frame_=" << input_frame_
            << " packet_=" << packet_ << "\n";
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
    ret = avformat_write_header(format_ctx_, &muxer_opts_);
    if (ret < 0) {
      char errbuf[AV_ERROR_MAX_STRING_SIZE];
      av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
      std::cerr << "[EncoderPipeline] Failed to write header (fixed): " << errbuf << std::endl;
      close();
      return false;
    }
    av_dict_free(&muxer_opts_);
    muxer_opts_ = nullptr;
    header_written_ = true;
    std::cout << "[EncoderPipeline] Encoder pipeline initialized at " << frame_width_ << "x" << frame_height_
              << " (per-channel fixed; all content scaled to this)" << std::endl;
  }

  initialized_ = true;
  if (!fixed_dimensions) {
    std::cout << "[EncoderPipeline] Encoder pipeline initialized (will set dimensions from first frame)" << std::endl;
  }
  return true;
}

void EncoderPipeline::EnforceMonotonicDts() {
  if (!packet_ || !video_stream_) return;
  int64_t dts = packet_->dts;
  int64_t pts = packet_->pts;
  if (last_mux_dts_ != AV_NOPTS_VALUE) {
    if (dts != AV_NOPTS_VALUE && dts <= last_mux_dts_)
      dts = last_mux_dts_ + 1;
    else if (pts != AV_NOPTS_VALUE && pts <= last_mux_dts_)
      pts = last_mux_dts_ + 1;
  }
  if (pts != AV_NOPTS_VALUE && dts != AV_NOPTS_VALUE && pts < dts)
    pts = dts;
  packet_->dts = dts;
  packet_->pts = pts;
  if (dts != AV_NOPTS_VALUE)
    last_mux_dts_ = dts;
  else if (pts != AV_NOPTS_VALUE)
    last_mux_dts_ = pts;
}

bool EncoderPipeline::encodeFrame(const retrovue::buffer::Frame& frame, int64_t pts90k) {
  std::cerr << "ALLOC frame_=" << frame_
            << " input_frame_=" << input_frame_
            << " packet_=" << packet_ << "\n";
  if (packet_ == reinterpret_cast<AVPacket*>(input_frame_)) {
    std::cerr << "FATAL: packet_ == input_frame_ at encodeFrame entry (corruption before frame data touched)\n";
    std::abort();
  }
  std::cerr << "[EncoderPipeline] encodeFrame enter codec_ctx_=" << codec_ctx_
            << " format_ctx_=" << format_ctx_
            << " pb=" << (format_ctx_ ? format_ctx_->pb : nullptr)
            << " cb=" << reinterpret_cast<void*>(avio_write_callback_)
            << " opaque=" << avio_opaque_
            << std::endl;
  if (!initialized_) {
    return false;
  }

  if (config_.stub_mode) {
    std::cout << "[EncoderPipeline] encodeFrame() - stub mode | PTS_us=" << frame.metadata.pts
              << " | size=" << frame.width << "x" << frame.height << std::endl;
    return true;
  }

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
    // Enforce strictly increasing input PTS (same as main path) to avoid muxer DTS errors.
    AVRational tb90k = {1, 90000};
    int64_t pts = av_rescale_q(pts90k, tb90k, codec_ctx_->time_base);
    if (last_input_pts_ != AV_NOPTS_VALUE && pts <= last_input_pts_)
      pts = last_input_pts_ + 1;
    last_input_pts_ = pts;
    frame_->pts = pts;
    frame_->metadata = nullptr;
    frame_->opaque = nullptr;
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
          av_write_frame(format_ctx_, packet_);
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
    constexpr int max_packets_per_frame = 10;
    int n = 0;
    while (n < max_packets_per_frame) {
      int recv_ret = avcodec_receive_packet(codec_ctx_, packet_);
      if (recv_ret == AVERROR(EAGAIN) || recv_ret == AVERROR_EOF) break;
      if (recv_ret < 0) return false;
      ++n;
      packet_->stream_index = video_stream_->index;
      av_packet_rescale_ts(packet_, codec_ctx_->time_base, video_stream_->time_base);
      EnforceMonotonicDts();
      if (av_write_frame(format_ctx_, packet_) < 0) { /* logged elsewhere */ }
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

    // Set encoder options for low latency using AVDictionary
    // This is more reliable than av_opt_set and works with all FFmpeg versions
    AVDictionary* opts = nullptr;
    av_dict_set(&opts, "preset", "ultrafast", 0);
    av_dict_set(&opts, "tune", "zerolatency", 0);

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
      std::cout << "[EncoderPipeline] Header written successfully" << std::endl;
    }

    std::cout << "[EncoderPipeline] Codec opened: " << frame.width << "x" << frame.height << std::endl;
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
        // av_write_frame takes ownership and unrefs the packet.
        int write_ret = av_write_frame(format_ctx_, packet_);
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

    // Write packet to muxer.
    // av_write_frame takes ownership and unrefs the packet.
    int write_ret = av_write_frame(format_ctx_, packet_);

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

  return true;
}

void EncoderPipeline::close() {
  if (!initialized_) return;
  if (config_.stub_mode) {
    initialized_ = false;
    std::cout << "[EncoderPipeline] close() - stub mode" << std::endl;
    return;
  }

#ifdef RETROVUE_FFMPEG_AVAILABLE
  // Idempotent: prevent double-close (e.g. from destructor) from re-running teardown.
  initialized_ = false;
  last_mux_dts_ = AV_NOPTS_VALUE;
  last_input_pts_ = AV_NOPTS_VALUE;

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
        // av_write_frame takes ownership and unrefs the packet.
        int write_ret = av_write_frame(format_ctx_, packet_);
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
  
  // Clear audio resample buffer and reset PTS tracking
  audio_resample_buffer_.clear();
  audio_resample_buffer_samples_ = 0;
  last_seen_audio_pts90k_ = AV_NOPTS_VALUE;
  audio_pts_offset_90k_ = 0;
  sws_ctx_valid_ = false;

  video_stream_ = nullptr;
  frame_width_ = 0;
  frame_height_ = 0;
  header_written_ = false;
#endif
}

bool EncoderPipeline::IsInitialized() const {
  return initialized_;
}

#ifdef RETROVUE_FFMPEG_AVAILABLE
int EncoderPipeline::AVIOWriteThunk(void* opaque, uint8_t* buf, int buf_size) {
  std::cerr << "[EncoderPipeline] AVIOWriteThunk opaque=" << opaque
            << " buf_size=" << buf_size << std::endl;
  if (opaque == nullptr) return -1;
  auto* pipeline = reinterpret_cast<EncoderPipeline*>(opaque);
  return pipeline->HandleAVIOWrite(buf, buf_size);
}

int EncoderPipeline::HandleAVIOWrite(uint8_t* buf, int buf_size) {
  std::cerr << "[EncoderPipeline] HandleAVIOWrite cb=" << reinterpret_cast<void*>(avio_write_callback_)
            << " opaque=" << avio_opaque_ << " buf_size=" << buf_size << std::endl;
  if (!avio_write_callback_) return -1;
  int ret = avio_write_callback_(avio_opaque_, buf, buf_size);
  return (ret == buf_size) ? buf_size : -1;
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

  // Stub: just log
  std::cout << "[EncoderPipeline] encodeFrame() - FFmpeg not available | PTS=" << pts90k
            << " | size=" << frame.width << "x" << frame.height << std::endl;
  return true;
}

void EncoderPipeline::close() {
  if (!initialized_) {
    return;
  }

  std::cout << "[EncoderPipeline] close() - FFmpeg not available" << std::endl;
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

  static int audio_frame_count = 0;
  audio_frame_count++;
  
  // Log every frame for first 50 frames, then every 100
  bool should_log = (audio_frame_count <= 50) || (audio_frame_count % 100 == 0);
  if (should_log) {
    std::cout << "[EncoderPipeline] Encoding audio frame #" << audio_frame_count 
              << ", pts90k=" << pts90k 
              << ", samples=" << audio_frame.nb_samples
              << ", sample_rate=" << audio_frame.sample_rate << std::endl;
  }

#ifdef RETROVUE_FFMPEG_AVAILABLE
  if (!audio_codec_ctx_ || !audio_stream_ || !audio_frame_ || !packet_) {
    return false;  // Audio encoder not initialized
  }

  // Phase 8.9: Handle sample rate conversion if input rate differs from encoder rate
  const int input_sample_rate = audio_frame.sample_rate;
  const int encoder_sample_rate = audio_codec_ctx_->sample_rate;
  const int nb_channels = audio_codec_ctx_->ch_layout.nb_channels;
  
  // Handle sample rate changes: clear buffer and reset resampler state
  const bool sample_rate_changed = (last_input_sample_rate_ != input_sample_rate);
  const bool needs_resampling = (input_sample_rate != encoder_sample_rate);
  
  if (sample_rate_changed) {
    std::cout << "[EncoderPipeline] ===== AUDIO SAMPLE RATE CHANGE =====" << std::endl;
    std::cout << "[EncoderPipeline] Audio sample rate changed: "
              << last_input_sample_rate_ << " Hz → " << input_sample_rate << " Hz" << std::endl;
    std::cout << "[EncoderPipeline] Encoder sample rate: " << encoder_sample_rate << " Hz" << std::endl;
    std::cout << "[EncoderPipeline] Needs resampling: " << (needs_resampling ? "YES" : "NO") << std::endl;
    std::cout << "[EncoderPipeline] Current resampler state: " << (swr_ctx_ ? "ACTIVE" : "NULL") << std::endl;
    std::cout << "[EncoderPipeline] Buffered samples: " << audio_resample_buffer_samples_ << std::endl;

    // IMPORTANT: Encode any buffered samples from the PREVIOUS producer before switching!
    // These are already-resampled samples waiting to fill a complete AAC frame.
    // We need to encode them (padded with silence if needed) to avoid losing audio.
    if (audio_resample_buffer_samples_ > 0) {
      const int frame_size = audio_codec_ctx_->frame_size;
      AVRational tb90k{1, 90000};
      AVRational tb_audio = audio_codec_ctx_->time_base;

      // Get current PTS to continue from
      int64_t flush_pts90k = 0;
      if (last_mux_dts_ != AV_NOPTS_VALUE && audio_stream_) {
        flush_pts90k = av_rescale_q(last_mux_dts_, audio_stream_->time_base, tb90k);
        int64_t frame_duration_90k = (static_cast<int64_t>(frame_size) * 90000) / encoder_sample_rate;
        flush_pts90k += frame_duration_90k;
      }

      // Pad buffered samples with silence to make a complete frame
      int samples_to_pad = frame_size - audio_resample_buffer_samples_;
      if (samples_to_pad > 0 && samples_to_pad < frame_size) {
        std::cout << "[EncoderPipeline] Padding " << audio_resample_buffer_samples_
                  << " buffered samples with " << samples_to_pad << " silence samples" << std::endl;
        audio_resample_buffer_.resize(frame_size * nb_channels, 0);  // Pad with silence
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
                        frame_size * nb_channels * sizeof(int16_t));
          } else if (audio_codec_ctx_->sample_fmt == AV_SAMPLE_FMT_FLTP) {
            for (int c = 0; c < nb_channels; ++c) {
              float* dst_plane = reinterpret_cast<float*>(audio_frame_->data[c]);
              for (int i = 0; i < frame_size; ++i) {
                dst_plane[i] = static_cast<float>(audio_resample_buffer_[i * nb_channels + c]) / 32768.0f;
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
              av_write_frame(format_ctx_, packet_);
            }
            std::cout << "[EncoderPipeline] Encoded buffered samples from previous producer" << std::endl;
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
          std::vector<uint8_t> flush_buffer(flush_samples * nb_channels * sizeof(int16_t));
          uint8_t* out_data[1] = {flush_buffer.data()};
          int flushed = swr_convert(swr_ctx_, out_data, flush_samples, nullptr, 0);
          if (flushed > 0) {
            std::cout << "[EncoderPipeline] Flushed " << flushed << " samples from resampler delay buffer" << std::endl;
            // These samples should also be encoded, but they're typically very few
            // and would require another partial frame handling. For now, log them.
            // TODO: Accumulate and encode these with the next frame if significant.
          }
        }
      }
      swr_free(&swr_ctx_);
      swr_ctx_ = nullptr;
      std::cout << "[EncoderPipeline] Freed existing resampler due to sample rate change" << std::endl;
    }

    last_input_sample_rate_ = input_sample_rate;
  }
  
  // Create resampler ONLY if resampling is needed
  // (input rate differs from encoder rate)
  if (needs_resampling && !swr_ctx_) {
    // Create resampler: S16 interleaved @ input_rate → S16 interleaved @ encoder_rate
    AVChannelLayout src_ch_layout, dst_ch_layout;
    av_channel_layout_copy(&src_ch_layout, &audio_codec_ctx_->ch_layout);
    av_channel_layout_copy(&dst_ch_layout, &audio_codec_ctx_->ch_layout);
    
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
    
    std::cout << "[EncoderPipeline] ===== AUDIO RESAMPLER INITIALIZED =====" << std::endl;
    std::cout << "[EncoderPipeline] Audio resampler initialized: " 
              << input_sample_rate << " Hz → " << encoder_sample_rate << " Hz" << std::endl;
    std::cout << "[EncoderPipeline] Frame #" << audio_frame_count << std::endl;
  } else if (!needs_resampling && swr_ctx_) {
    // Input rate matches encoder rate, but we have a resampler from previous clip
    // Free it since resampling is no longer needed
    swr_free(&swr_ctx_);
    swr_ctx_ = nullptr;
    std::cout << "[EncoderPipeline] Audio resampler freed (input rate matches encoder: " 
              << input_sample_rate << " Hz)" << std::endl;
  } else if (!needs_resampling && !swr_ctx_) {
    // No resampling needed and no resampler - this is the normal case for matching rates
    if (audio_frame_count <= 5 || audio_frame_count % 100 == 0) {
      std::cout << "[EncoderPipeline] Audio passthrough (no resampling): " 
                << input_sample_rate << " Hz input → " << encoder_sample_rate << " Hz encoder" << std::endl;
    }
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
                                  static_cast<size_t>(nb_channels) *
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
    
    if (audio_frame_count % 100 == 0) {
      std::cout << "[EncoderPipeline] Resampled audio: " << src_nb_samples 
                << " samples @ " << input_sample_rate << " Hz → " 
                << dst_nb_samples << " samples @ " << encoder_sample_rate << " Hz" << std::endl;
    }
    
    // Use resampled data as source
    src_data = resampled_data.data();
    src_nb_samples = dst_nb_samples;
  } else if (needs_resampling) {
    // This should never happen - if resampling is needed, swr_ctx_ should exist
    std::cerr << "[EncoderPipeline] ERROR: Resampling needed but no resampler context!" << std::endl;
    return false;
  }
  
  // Prepend any buffered samples from previous call (only if sample rate hasn't changed)
  // If sample rate changed, buffer was already cleared above
  std::vector<int16_t> combined_samples;
  if (audio_resample_buffer_samples_ > 0 && last_input_sample_rate_ == input_sample_rate) {
    combined_samples.reserve(audio_resample_buffer_samples_ + src_nb_samples);
    combined_samples.insert(combined_samples.end(),
                            audio_resample_buffer_.begin(),
                            audio_resample_buffer_.begin() + audio_resample_buffer_samples_ * nb_channels);
    audio_resample_buffer_samples_ = 0;  // Clear buffer
  }
  
  // Append new samples
  const int16_t* new_samples = reinterpret_cast<const int16_t*>(src_data);
  if (audio_resample_buffer_samples_ > 0 && last_input_sample_rate_ == input_sample_rate) {
    // We prepended buffered samples above
    combined_samples.insert(combined_samples.end(),
                            new_samples,
                            new_samples + src_nb_samples * nb_channels);
  } else {
    // No buffered samples (or sample rate changed), just use new samples directly
    combined_samples.insert(combined_samples.end(),
                            new_samples,
                            new_samples + src_nb_samples * nb_channels);
  }
  
  int total_samples = static_cast<int>(combined_samples.size()) / nb_channels;
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
      std::cout << "[EncoderPipeline] ===== PRODUCER SWITCH DETECTED =====" << std::endl;
      std::cout << "[EncoderPipeline] Previous incoming PTS (90kHz): " << last_seen_audio_pts90k_ << std::endl;
      std::cout << "[EncoderPipeline] New incoming PTS (90kHz): " << pts90k << std::endl;
      std::cout << "[EncoderPipeline] Backward jump: " << (last_seen_audio_pts90k_ - pts90k) << " (threshold: " << backward_threshold << ")" << std::endl;
    }
  }

  // Always update last_seen_audio_pts90k_ with the ORIGINAL incoming PTS
  // This tracks the SOURCE timeline, not the muxed timeline
  last_seen_audio_pts90k_ = pts90k;

  // Now handle PTS rebasing for the muxer
  // On a producer switch, we need to calculate the offset to continue from last muxed PTS
  if (is_first_frame_of_new_producer && last_mux_dts_ != AV_NOPTS_VALUE && audio_stream_) {
    // Convert last_mux_dts_ from stream timebase to 90kHz
    int64_t last_muxed_pts90k = av_rescale_q(last_mux_dts_, audio_stream_->time_base, tb90k);

    // Calculate duration of one AAC frame in 90kHz units
    const int frame_size = audio_codec_ctx_->frame_size;
    int64_t frame_duration_90k = (static_cast<int64_t>(frame_size) * 90000) / encoder_sample_rate;

    // Calculate the offset needed to rebase the new producer's PTS
    // New producer's first frame should have PTS = last_muxed + one_frame_duration
    int64_t target_pts = last_muxed_pts90k + frame_duration_90k;
    audio_pts_offset_90k_ = target_pts - pts90k;

    std::cout << "[EncoderPipeline] ===== AUDIO PTS REBASING =====" << std::endl;
    std::cout << "[EncoderPipeline] Last muxed PTS (90kHz): " << last_muxed_pts90k << std::endl;
    std::cout << "[EncoderPipeline] New producer first PTS (90kHz): " << pts90k << std::endl;
    std::cout << "[EncoderPipeline] Target PTS (90kHz): " << target_pts << std::endl;
    std::cout << "[EncoderPipeline] New PTS offset (90kHz): " << audio_pts_offset_90k_ << std::endl;
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
                               static_cast<size_t>(nb_channels) *
                               sizeof(int16_t);
      std::memcpy(audio_frame_->data[0], samples_ptr, data_size);
    } else if (audio_codec_ctx_->sample_fmt == AV_SAMPLE_FMT_FLTP) {
      // Convert S16 interleaved → planar float [-1.0, 1.0]
      for (int c = 0; c < nb_channels; ++c) {
        float* dst_plane = reinterpret_cast<float*>(audio_frame_->data[c]);
        for (int i = 0; i < samples_this_frame; ++i) {
          const int idx = i * nb_channels + c;
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
          av_write_frame(format_ctx_, packet_);
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
      
      // Enforce monotonic DTS for audio (same as video)
      // Special case: If encoder was just reopened (last_mux_dts_ == AV_NOPTS_VALUE) and
      // the incoming DTS is very low, initialize last_mux_dts_ to a reasonable starting value
      // to prevent backward jumps that cause stuttering
      if (last_mux_dts_ == AV_NOPTS_VALUE && packet_->dts != AV_NOPTS_VALUE && packet_->dts < 100000) {
        // Initialize to a reasonable starting DTS to avoid backward jumps
        // Use a value that's safely above typical initial PTS values
        last_mux_dts_ = 100000;
        if (audio_frame_count <= 5) {
          std::cout << "[EncoderPipeline] Initialized last_mux_dts_ to " << last_mux_dts_ 
                    << " (incoming DTS was " << packet_->dts << ")" << std::endl;
        }
      }
      
      EnforceMonotonicDts();
      
      // Log every packet for first 50 frames, then every 100
      bool should_log_packet = (audio_frame_count <= 50) || (audio_frame_count % 100 == 0);
      if (should_log_packet) {
        std::cout << "[EncoderPipeline] Muxing audio packet: stream=" << packet_->stream_index
                  << ", pts=" << packet_->pts << ", dts=" << packet_->dts
                  << ", size=" << packet_->size
                  << ", frame_count=" << audio_frame_count << std::endl;
      }
      
      int mux_ret = av_write_frame(format_ctx_, packet_);
      if (mux_ret < 0) {
        char errbuf[AV_ERROR_MAX_STRING_SIZE];
        av_strerror(mux_ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
        std::cerr << "[EncoderPipeline] Error muxing audio packet: " << errbuf << std::endl;
      }
    }
    
    // Advance pointer for next chunk
    // Note: PTS is handled by encoder_audio_pts_ counter (already incremented above)
    samples_ptr += samples_this_frame * nb_channels;
    samples_remaining -= samples_this_frame;
  }
  
  // Buffer any remaining samples (< frame_size) for the next call
  // These will be prepended to the next input frame
  if (samples_remaining > 0) {
    audio_resample_buffer_.resize(samples_remaining * nb_channels);
    std::memcpy(audio_resample_buffer_.data(), samples_ptr, 
                samples_remaining * nb_channels * sizeof(int16_t));
    audio_resample_buffer_samples_ = samples_remaining;
  } else {
    audio_resample_buffer_samples_ = 0;
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

  std::cout << "[EncoderPipeline] ===== FLUSHING AUDIO BUFFERS =====" << std::endl;
  
  const int encoder_sample_rate = audio_codec_ctx_->sample_rate;
  const int frame_size = audio_codec_ctx_->frame_size;
  const int nb_channels = audio_codec_ctx_->ch_layout.nb_channels;
  AVRational tb90k{1, 90000};
  AVRational tb_audio = audio_codec_ctx_->time_base;
  
  // Step 1: Flush resampler delay buffer (if resampler exists)
  if (swr_ctx_ && last_input_sample_rate_ > 0) {
    int64_t delay = swr_get_delay(swr_ctx_, last_input_sample_rate_);
    if (delay > 0) {
      std::cout << "[EncoderPipeline] Flushing resampler delay: " << delay << " samples" << std::endl;
      // Estimate output samples for the delay
      int64_t flush_samples = av_rescale_rnd(delay, encoder_sample_rate, last_input_sample_rate_, AV_ROUND_UP);
      if (flush_samples > 0) {
        std::vector<uint8_t> flush_buffer(flush_samples * nb_channels * sizeof(int16_t));
        uint8_t* out_data[1] = { flush_buffer.data() };
        int flushed = swr_convert(swr_ctx_, out_data, flush_samples, nullptr, 0);
        if (flushed > 0) {
          // Add flushed samples to resample buffer
          int16_t* flush_samples_ptr = reinterpret_cast<int16_t*>(flush_buffer.data());
          audio_resample_buffer_.insert(audio_resample_buffer_.end(),
                                        flush_samples_ptr,
                                        flush_samples_ptr + flushed * nb_channels);
          audio_resample_buffer_samples_ += flushed;
          std::cout << "[EncoderPipeline] Flushed " << flushed << " samples from resampler" << std::endl;
        }
      }
    }
  }
  
  // Step 2: Encode any remaining buffered samples (including flushed resampler output)
  // Get current PTS from last_mux_dts_ if available, otherwise use a reasonable value
  int64_t current_pts90k = 0;
  if (last_mux_dts_ != AV_NOPTS_VALUE && audio_stream_) {
    current_pts90k = av_rescale_q(last_mux_dts_, audio_stream_->time_base, tb90k);
    // Add duration of one frame to continue from last
    int64_t frame_duration_90k = (static_cast<int64_t>(frame_size) * 90000) / encoder_sample_rate;
    current_pts90k += frame_duration_90k;
  }
  
  // Process any buffered samples
  if (audio_resample_buffer_samples_ > 0) {
    std::cout << "[EncoderPipeline] Encoding " << audio_resample_buffer_samples_ 
              << " buffered samples" << std::endl;
    
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
                                 static_cast<size_t>(nb_channels) *
                                 sizeof(int16_t);
        std::memcpy(audio_frame_->data[0], samples_ptr, data_size);
      } else if (audio_codec_ctx_->sample_fmt == AV_SAMPLE_FMT_FLTP) {
        for (int c = 0; c < nb_channels; ++c) {
          float* dst_plane = reinterpret_cast<float*>(audio_frame_->data[c]);
          for (int i = 0; i < samples_this_frame; ++i) {
            int16_t sample = samples_ptr[i * nb_channels + c];
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
        av_write_frame(format_ctx_, packet_);
      }
      
      // Advance PTS and pointer
      int64_t frame_duration_90k = (static_cast<int64_t>(samples_this_frame) * 90000) / encoder_sample_rate;
      current_pts90k += frame_duration_90k;
      samples_ptr += samples_this_frame * nb_channels;
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
    av_write_frame(format_ctx_, packet_);
  }
  
  std::cout << "[EncoderPipeline] Audio flush complete: drained " << packets_drained << " packets" << std::endl;
  std::cout << "[EncoderPipeline] Note: Encoder remains active (not flushed to EOF) to allow continued encoding" << std::endl;
  return true;
#else
  return true;
#endif
}

}  // namespace retrovue::playout_sinks::mpegts
