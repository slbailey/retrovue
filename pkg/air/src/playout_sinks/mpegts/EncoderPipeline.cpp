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
      frame_(nullptr),
      input_frame_(nullptr),
      packet_(nullptr),
      sws_ctx_(nullptr),
      frame_width_(0),
      frame_height_(0),
      input_pix_fmt_(AV_PIX_FMT_YUV420P),
      sws_ctx_valid_(false),
      header_written_(false),
      codec_opened_(false),
      muxer_opts_(nullptr),
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

  // Open codec (dimensions will be set from first frame)
  // We'll open it after we get the first frame dimensions
  codec_ctx_->width = 0;
  codec_ctx_->height = 0;

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
  // Single ownership: frame_ allocated here, freed exactly once in close(). No manual metadata/side-data free (av_frame_unref/av_frame_free own it).
  frame_->metadata = nullptr;
  frame_->opaque = nullptr;
  frame_->buf[0] = nullptr;  // Explicit: never unref a freshly allocated frame until get_buffer has run.
  // Explicitly null buffer pointers (av_frame_alloc may not zero them on all builds).
  input_frame_->data[0] = input_frame_->data[1] = input_frame_->data[2] = nullptr;
  input_frame_->linesize[0] = input_frame_->linesize[1] = input_frame_->linesize[2] = 0;
  if (kEncoderPipelineDebugAlloc) {
    std::cerr << "[EncoderPipeline] open: frame_=" << static_cast<void*>(frame_)
              << " input_frame_=" << static_cast<void*>(input_frame_)
              << " packet_=" << static_cast<void*>(packet_)
              << " muxer_opts_=" << static_cast<void*>(muxer_opts_) << std::endl;
  }

  initialized_ = true;
  std::cout << "[EncoderPipeline] Encoder pipeline initialized (will set dimensions from first frame)" << std::endl;
  return true;
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

  // Check if codec needs to be opened (first frame or dimensions changed)
  if (!codec_ctx_->width || !codec_ctx_->height || 
      codec_ctx_->width != frame.width || codec_ctx_->height != frame.height) {
    
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

    const AVCodec* codec = avcodec_find_encoder_by_name("libx264");
    if (!codec) {
      std::cerr << "[EncoderPipeline] libx264 not found" << std::endl;
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

  // Set frame PTS from pts90k (already in 90kHz units)
  // pts90k is monotonic and aligned with the producer's timeline
  // Convert from 90kHz timebase to codec timebase
  AVRational tb90k = {1, 90000};  // 90kHz timebase
  frame_->pts = av_rescale_q(pts90k, tb90k, codec_ctx_->time_base);

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
    } else {
      std::cout << "[EncoderPipeline] Trailer written successfully" << std::endl;
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

  if (sws_ctx_) {
    sws_freeContext(sws_ctx_);
    sws_ctx_ = nullptr;
  }
  sws_ctx_valid_ = false;

  video_stream_ = nullptr;
  frame_width_ = 0;
  frame_height_ = 0;
  header_written_ = false;
#endif

  std::cout << "[EncoderPipeline] Encoder pipeline closed" << std::endl;
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

}  // namespace retrovue::playout_sinks::mpegts
