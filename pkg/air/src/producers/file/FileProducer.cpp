// Repository: Retrovue-playout
// Component: File Producer
// Purpose: Self-contained decoder that reads and decodes video files, producing decoded YUV420 frames.
// Copyright (c) 2025 RetroVue

#include "retrovue/producers/file/FileProducer.h"

#include <chrono>
#include <cmath>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <thread>

extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/imgutils.h>
#include <libavutil/mathematics.h>
#include <libavutil/rational.h>
#include <libavutil/samplefmt.h>
#include <libswscale/swscale.h>
}

#include "retrovue/runtime/AspectPolicy.h"
#include "retrovue/timing/MasterClock.h"
#include "retrovue/timing/TimelineController.h"

#include <cstring>

namespace retrovue::producers::file
{

  namespace
  {
    constexpr int64_t kProducerBackoffUs = 10'000; // 10ms backoff when buffer is full
    constexpr int64_t kMicrosecondsPerSecond = 1'000'000;
  }

  FileProducer::FileProducer(
      const ProducerConfig &config,
      buffer::FrameRingBuffer &output_buffer,
      std::shared_ptr<timing::MasterClock> clock,
      ProducerEventCallback event_callback,
      timing::TimelineController* timeline_controller)
      : config_(config),
        output_buffer_(output_buffer),
        master_clock_(clock),
        timeline_controller_(timeline_controller),
        event_callback_(event_callback),
        state_(ProducerState::STOPPED),
        stop_requested_(false),
        teardown_requested_(false),
        writes_disabled_(false),
        frames_produced_(0),
        buffer_full_count_(0),
        decode_errors_(0),
        drain_timeout_(std::chrono::milliseconds(0)),
        format_ctx_(nullptr),
        codec_ctx_(nullptr),
        frame_(nullptr),
        scaled_frame_(nullptr),
        intermediate_frame_(nullptr),
        packet_(nullptr),
        sws_ctx_(nullptr),
        video_stream_index_(-1),
        decoder_initialized_(false),
        eof_reached_(false),
        eof_event_emitted_(false),
        time_base_(0.0),
        last_pts_us_(0),
        last_decoded_frame_pts_us_(0),
        first_frame_pts_us_(0),
        playback_start_utc_us_(0),
        segment_end_pts_us_(-1),
        audio_codec_ctx_(nullptr),
        audio_frame_(nullptr),
        audio_stream_index_(-1),
        audio_time_base_(0.0),
        audio_eof_reached_(false),
        last_audio_pts_us_(0),
        effective_seek_target_us_(0),
        stub_pts_counter_(0),
        frame_interval_us_(static_cast<int64_t>(std::round(kMicrosecondsPerSecond / config.target_fps))),
        next_stub_deadline_utc_(0),
        shadow_decode_mode_(false),
        shadow_decode_ready_(false),
        pts_offset_us_(0),
        pts_aligned_(false),
        aspect_policy_(runtime::AspectPolicy::Preserve),
        scale_width_(0),
        scale_height_(0),
        pad_x_(0),
        pad_y_(0),
        video_frame_count_(0),
        video_discard_count_(0),
        audio_frame_count_(0),
        frames_since_producer_start_(0),
        audio_skip_count_(0),
        audio_drop_count_(0),
        audio_ungated_logged_(false),
        scale_diag_count_(0)
  {
  }

  FileProducer::~FileProducer()
  {
    stop();
    CloseDecoder();
  }

  void FileProducer::SetState(ProducerState new_state)
  {
    ProducerState old_state = state_.exchange(new_state, std::memory_order_acq_rel);
    if (old_state != new_state)
    {
      std::ostringstream msg;
      msg << "state=" << static_cast<int>(new_state);
      EmitEvent("state_change", msg.str());
    }
  }

  void FileProducer::EmitEvent(const std::string &event_type, const std::string &message)
  {
    if (event_callback_)
    {
      event_callback_(event_type, message);
    }
  }

  bool FileProducer::start()
  {
    ProducerState current_state = state_.load(std::memory_order_acquire);
    if (current_state != ProducerState::STOPPED)
    {
      return false; // Not in stopped state
    }

    SetState(ProducerState::STARTING);
    stop_requested_.store(false, std::memory_order_release);
    teardown_requested_.store(false, std::memory_order_release);
    stub_pts_counter_.store(0, std::memory_order_release);
    next_stub_deadline_utc_.store(0, std::memory_order_release);
    eof_reached_ = false;
    eof_event_emitted_ = false;
    last_pts_us_ = 0;
    last_decoded_frame_pts_us_ = 0;
    last_audio_pts_us_ = 0;
    first_frame_pts_us_ = 0;
    playback_start_utc_us_ = 0;
    segment_end_pts_us_ = -1;

    // Phase 6A.2: non-stub mode — init decoder before starting thread
    // If initialization fails (e.g. file not found), fail start() so caller knows
    if (!config_.stub_mode)
    {
      if (!InitializeDecoder())
      {
        SetState(ProducerState::STOPPED);
        return false;
      }
    }

    // Set state to RUNNING before starting thread (so loop sees correct state)
    SetState(ProducerState::RUNNING);
    
    // In stub mode, emit ready immediately
    if (config_.stub_mode)
    {
      EmitEvent("ready", "");
    }
    
    // Start producer thread
    producer_thread_ = std::make_unique<std::thread>(&FileProducer::ProduceLoop, this);
    
    std::cout << "[FileProducer] Started for asset: " << config_.asset_uri << std::endl;
    EmitEvent("started", "");
    
    return true;
  }

  void FileProducer::stop()
  {
    ProducerState current_state = state_.load(std::memory_order_acquire);

    // No thread: already fully stopped (or never started).
    if (!producer_thread_ || !producer_thread_->joinable())
    {
      if (current_state == ProducerState::STOPPED)
        return;
      CloseDecoder();
      SetState(ProducerState::STOPPED);
      std::cout << "[FileProducer] Stopped. Total decoded frames produced: "
                << frames_produced_.load(std::memory_order_acquire) << std::endl;
      EmitEvent("stopped", "");
      return;
    }

    // Thread exists and is joinable. If loop exited on its own (hard stop, EOF), state may
    // already be STOPPED; we must still join to avoid std::terminate() when destroying the thread.
    if (current_state != ProducerState::STOPPED)
    {
      SetState(ProducerState::STOPPING);
      stop_requested_.store(true, std::memory_order_release);
      teardown_requested_.store(false, std::memory_order_release);
    }
    producer_thread_->join();
    producer_thread_.reset();

    CloseDecoder();
    SetState(ProducerState::STOPPED);
    std::cout << "[FileProducer] Stopped. Total decoded frames produced: "
              << frames_produced_.load(std::memory_order_acquire) << std::endl;
    EmitEvent("stopped", "");
  }

  void FileProducer::RequestTeardown(std::chrono::milliseconds drain_timeout)
  {
    if (!isRunning())
    {
      return;
    }

    drain_timeout_ = drain_timeout;
    teardown_deadline_ = std::chrono::steady_clock::now() + drain_timeout_;
    teardown_requested_.store(true, std::memory_order_release);
    std::cout << "[FileProducer] Teardown requested (timeout="
              << drain_timeout_.count() << " ms)" << std::endl;
    EmitEvent("teardown_requested", "");
  }

  void FileProducer::ForceStop()
  {
    // Phase 7: Hard write barrier - disable writes BEFORE signaling stop
    // This prevents any in-flight frames from being pushed after this point
    writes_disabled_.store(true, std::memory_order_release);
    stop_requested_.store(true, std::memory_order_release);
    std::cout << "[FileProducer] Force stop requested (writes disabled)" << std::endl;
    EmitEvent("force_stop", "");
  }

  void FileProducer::SetWriteBarrier()
  {
    // Phase 8: Disable writes without stopping the producer.
    // Producer continues decoding but frames are silently dropped.
    // Used when switching segments to prevent old producer from affecting
    // the TimelineController's segment mapping.
    writes_disabled_.store(true, std::memory_order_release);
    std::cout << "[FileProducer] Write barrier set (producer continues decoding)" << std::endl;
    EmitEvent("write_barrier", "");
  }

  bool FileProducer::isRunning() const
  {
    ProducerState current_state = state_.load(std::memory_order_acquire);
    return current_state == ProducerState::RUNNING;
  }

  uint64_t FileProducer::GetFramesProduced() const
  {
    return frames_produced_.load(std::memory_order_acquire);
  }

  uint64_t FileProducer::GetBufferFullCount() const
  {
    return buffer_full_count_.load(std::memory_order_acquire);
  }

  uint64_t FileProducer::GetDecodeErrors() const
  {
    return decode_errors_.load(std::memory_order_acquire);
  }

  ProducerState FileProducer::GetState() const
  {
    return state_.load(std::memory_order_acquire);
  }

  void FileProducer::ProduceLoop()
  {
    std::cout << "[FileProducer] Decode loop started (stub_mode=" 
              << (config_.stub_mode ? "true" : "false") << ")" << std::endl;

    // Non-stub: decoder already initialized in start() (Phase 6A.2). Init here only if not yet done.
    if (!config_.stub_mode && !decoder_initialized_)
    {
      if (!InitializeDecoder())
      {
        std::cerr << "[FileProducer] Failed to initialize internal decoder, falling back to stub mode" 
                  << std::endl;
        config_.stub_mode = true;
        EmitEvent("error", "Failed to initialize internal decoder, falling back to stub mode");
        EmitEvent("ready", "");
      }
      else
      {
        std::cout << "[FileProducer] Internal decoder initialized successfully" << std::endl;
        EmitEvent("ready", "");
      }
    }

    // Main production loop
    while (!stop_requested_.load(std::memory_order_acquire))
    {
      ProducerState current_state = state_.load(std::memory_order_acquire);
      if (current_state != ProducerState::RUNNING)
      {
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
        continue;
      }

      // Phase 8.6: no fixed segment cutoff. Segment end = natural EOF only (decoder reports no more frames).
      // hard_stop_time_ms / segment_end_pts are not used to forcibly stop; avoids premature termination and timing drift.

      // Check teardown timeout
      if (teardown_requested_.load(std::memory_order_acquire))
      {
        if (output_buffer_.IsEmpty())
        {
          std::cout << "[FileProducer] Buffer drained; completing teardown" << std::endl;
          EmitEvent("buffer_drained", "");
          break;
        }
        if (std::chrono::steady_clock::now() >= teardown_deadline_)
        {
          std::cout << "[FileProducer] Teardown timeout reached; forcing stop" << std::endl;
          EmitEvent("teardown_timeout", "");
          ForceStop();
          break;
        }
      }

      // Phase 8.8: Producer exhaustion (EOF) must NOT imply playout completion. Do NOT exit the
      // loop on EOF; the render path owns completion. Stay running until explicit stop/teardown
      // so that buffered frames can be presented at wall-clock time.
      if (eof_reached_)
      {
        if (!eof_event_emitted_)
        {
          eof_event_emitted_ = true;
          std::cout << "[FileProducer] End of file reached (no more frames to produce); waiting for explicit stop (Phase 8.8)" << std::endl;
          EmitEvent("eof", "");
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
        continue;
      }

      if (config_.stub_mode)
      {
        ProduceStubFrame();
        // Small yield to allow other threads
        std::this_thread::sleep_for(std::chrono::microseconds(100));
      }
      else
      {
        if (!ProduceRealFrame())
        {
          // EOF: eof_reached_ is set; next iteration will enter exhausted wait (Phase 8.8). Do not break.
          if (eof_reached_)
            continue;
          // Transient decode error - back off and retry
          decode_errors_.fetch_add(1, std::memory_order_relaxed);
          std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
      }
    }

    SetState(ProducerState::STOPPED);
    std::cout << "[FileProducer] Decode loop exited" << std::endl;
    EmitEvent("decode_loop_exited", "");
  }

  bool FileProducer::InitializeDecoder()
  {
    // Phase 8.1.5: libav required; no stub. Allocate format context
    format_ctx_ = avformat_alloc_context();
    if (!format_ctx_)
    {
      std::cerr << "[FileProducer] Failed to allocate format context" << std::endl;
      return false;
    }

    // Open input file
    if (avformat_open_input(&format_ctx_, config_.asset_uri.c_str(), nullptr, nullptr) < 0)
    {
      std::cerr << "[FileProducer] Failed to open input: " << config_.asset_uri << std::endl;
      avformat_free_context(format_ctx_);
      format_ctx_ = nullptr;
      return false;
    }

    // Retrieve stream information
    if (avformat_find_stream_info(format_ctx_, nullptr) < 0)
    {
      std::cerr << "[FileProducer] Failed to find stream info" << std::endl;
      CloseDecoder();
      return false;
    }

    // Find video stream
    video_stream_index_ = -1;
    for (unsigned int i = 0; i < format_ctx_->nb_streams; i++)
    {
      if (format_ctx_->streams[i]->codecpar->codec_type == AVMEDIA_TYPE_VIDEO)
      {
        video_stream_index_ = i;
        AVStream* stream = format_ctx_->streams[i];
        time_base_ = av_q2d(stream->time_base);
        break;
      }
    }

    if (video_stream_index_ < 0)
    {
      std::cerr << "[FileProducer] No video stream found" << std::endl;
      CloseDecoder();
      return false;
    }

    // Phase 8.9: Find audio stream (optional - file may not have audio)
    audio_stream_index_ = -1;
    for (unsigned int i = 0; i < format_ctx_->nb_streams; i++)
    {
      if (format_ctx_->streams[i]->codecpar->codec_type == AVMEDIA_TYPE_AUDIO)
      {
        audio_stream_index_ = i;
        AVStream* stream = format_ctx_->streams[i];
        audio_time_base_ = av_q2d(stream->time_base);
        break;
      }
    }

    // Initialize codec
    AVStream* stream = format_ctx_->streams[video_stream_index_];
    AVCodecParameters* codecpar = stream->codecpar;
    const AVCodec* codec = avcodec_find_decoder(codecpar->codec_id);
    if (!codec)
    {
      std::cerr << "[FileProducer] Codec not found: " << codecpar->codec_id << std::endl;
      CloseDecoder();
      return false;
    }

    codec_ctx_ = avcodec_alloc_context3(codec);
    if (!codec_ctx_)
    {
      std::cerr << "[FileProducer] Failed to allocate codec context" << std::endl;
      CloseDecoder();
      return false;
    }

    if (avcodec_parameters_to_context(codec_ctx_, codecpar) < 0)
    {
      std::cerr << "[FileProducer] Failed to copy codec parameters" << std::endl;
      CloseDecoder();
      return false;
    }

    if (avcodec_open2(codec_ctx_, codec, nullptr) < 0)
    {
      std::cerr << "[FileProducer] Failed to open codec" << std::endl;
      CloseDecoder();
      return false;
    }

    // Allocate frames
    frame_ = av_frame_alloc();
    scaled_frame_ = av_frame_alloc();
    if (!frame_ || !scaled_frame_)
    {
      std::cerr << "[FileProducer] Failed to allocate frames" << std::endl;
      CloseDecoder();
      return false;
    }

    // Phase 8.9: Initialize audio decoder if audio stream exists
    if (audio_stream_index_ >= 0)
    {
      AVStream* audio_stream = format_ctx_->streams[audio_stream_index_];
      AVCodecParameters* audio_codecpar = audio_stream->codecpar;
      const AVCodec* audio_codec = avcodec_find_decoder(audio_codecpar->codec_id);
      if (!audio_codec)
      {
        std::cerr << "[FileProducer] Audio codec not found: " << audio_codecpar->codec_id << std::endl;
        // Continue without audio - not fatal
        audio_stream_index_ = -1;
      }
      else
      {
        audio_codec_ctx_ = avcodec_alloc_context3(audio_codec);
        if (!audio_codec_ctx_)
        {
          std::cerr << "[FileProducer] Failed to allocate audio codec context" << std::endl;
          audio_stream_index_ = -1;
        }
        else
        {
          if (avcodec_parameters_to_context(audio_codec_ctx_, audio_codecpar) < 0)
          {
            std::cerr << "[FileProducer] Failed to copy audio codec parameters" << std::endl;
            avcodec_free_context(&audio_codec_ctx_);
            audio_codec_ctx_ = nullptr;
            audio_stream_index_ = -1;
          }
          else if (avcodec_open2(audio_codec_ctx_, audio_codec, nullptr) < 0)
          {
            std::cerr << "[FileProducer] Failed to open audio codec" << std::endl;
            avcodec_free_context(&audio_codec_ctx_);
            audio_codec_ctx_ = nullptr;
            audio_stream_index_ = -1;
          }
          else
          {
            audio_frame_ = av_frame_alloc();
            if (!audio_frame_)
            {
              std::cerr << "[FileProducer] Failed to allocate audio frame" << std::endl;
              avcodec_free_context(&audio_codec_ctx_);
              audio_codec_ctx_ = nullptr;
              audio_stream_index_ = -1;
            }
            else
            {
            std::cout << "[FileProducer] Audio decoder initialized: "
                      << "sample_rate=" << audio_codec_ctx_->sample_rate
                      << ", channels=" << audio_codec_ctx_->ch_layout.nb_channels
                      << ", format=" << audio_codec_ctx_->sample_fmt << std::endl;
            std::cout << "[FileProducer] Audio stream index: " << audio_stream_index_ << std::endl;
            }
          }
        }
      }
    }

    // Initialize scaler with aspect ratio handling
    int src_width = codec_ctx_->width;
    int src_height = codec_ctx_->height;
    AVPixelFormat src_format = codec_ctx_->pix_fmt;
    int dst_width = config_.target_width;
    int dst_height = config_.target_height;
    AVPixelFormat dst_format = AV_PIX_FMT_YUV420P;

    // Compute scale dimensions based on aspect policy
    if (aspect_policy_ == runtime::AspectPolicy::Preserve) {
      // Preserve aspect: scale to fit, pad with black bars
      // Use Display Aspect Ratio (DAR) which accounts for Sample Aspect Ratio (SAR)
      // DAR = (width * SAR.num) / (height * SAR.den)
      double src_aspect;
      AVRational sar = codec_ctx_->sample_aspect_ratio;
      if (sar.num > 0 && sar.den > 0) {
        // SAR is defined: calculate DAR
        src_aspect = (static_cast<double>(src_width) * sar.num) /
                     (static_cast<double>(src_height) * sar.den);
        std::cout << "[FileProducer] Using SAR " << sar.num << ":" << sar.den
                  << " -> DAR " << src_aspect << std::endl;
      } else {
        // No SAR: assume square pixels
        src_aspect = static_cast<double>(src_width) / src_height;
        std::cout << "[FileProducer] No SAR, using pixel aspect " << src_aspect << std::endl;
      }
      double dst_aspect = static_cast<double>(dst_width) / dst_height;

      // Calculate scaled dimensions with proper rounding
      int calc_scale_width, calc_scale_height;
      if (src_aspect > dst_aspect) {
        // Source is wider: fit to width, pad height (letterbox)
        calc_scale_width = dst_width;
        calc_scale_height = static_cast<int>(std::round(dst_width / src_aspect));
      } else {
        // Source is taller or equal: fit to height, pad width (pillarbox)
        calc_scale_width = static_cast<int>(std::round(dst_height * src_aspect));
        calc_scale_height = dst_height;
      }

      // If within 1 pixel of target, use target dimensions (avoid sub-pixel padding)
      if (std::abs(calc_scale_width - dst_width) <= 1 &&
          std::abs(calc_scale_height - dst_height) <= 1) {
        scale_width_ = dst_width;
        scale_height_ = dst_height;
        pad_x_ = 0;
        pad_y_ = 0;
      } else {
        scale_width_ = calc_scale_width;
        scale_height_ = calc_scale_height;
        pad_x_ = (dst_width - scale_width_) / 2;
        pad_y_ = (dst_height - scale_height_) / 2;
      }
    } else {
      // Stretch: use target dimensions directly
      scale_width_ = dst_width;
      scale_height_ = dst_height;
      pad_x_ = 0;
      pad_y_ = 0;
    }

    sws_ctx_ = sws_getContext(
        src_width, src_height, src_format,
        scale_width_, scale_height_, dst_format,
        SWS_BILINEAR, nullptr, nullptr, nullptr);

    if (!sws_ctx_)
    {
      std::cerr << "[FileProducer] Failed to create scaler context" << std::endl;
      CloseDecoder();
      return false;
    }

    // Allocate buffer for scaled frame
    if (av_image_alloc(scaled_frame_->data, scaled_frame_->linesize,
                       dst_width, dst_height, dst_format, 32) < 0)
    {
      std::cerr << "[FileProducer] Failed to allocate scaled frame buffer" << std::endl;
      CloseDecoder();
      return false;
    }

    scaled_frame_->width = dst_width;
    scaled_frame_->height = dst_height;
    scaled_frame_->format = dst_format;

    // Allocate intermediate frame if padding needed (for aspect preserve)
    bool needs_padding = (scale_width_ != dst_width || scale_height_ != dst_height);
    if (needs_padding) {
      intermediate_frame_ = av_frame_alloc();
      if (!intermediate_frame_) {
        CloseDecoder();
        return false;
      }
      if (av_image_alloc(intermediate_frame_->data, intermediate_frame_->linesize,
                        scale_width_, scale_height_, dst_format, 32) < 0) {
        av_frame_free(&intermediate_frame_);
        CloseDecoder();
        return false;
      }
      intermediate_frame_->width = scale_width_;
      intermediate_frame_->height = scale_height_;
      intermediate_frame_->format = dst_format;
    }

    // Allocate packet
    packet_ = av_packet_alloc();
    if (!packet_)
    {
      std::cerr << "[FileProducer] Failed to allocate packet" << std::endl;
      CloseDecoder();
      return false;
    }

    // Phase 6 (INV-P6-002): Container seek for mid-segment join
    // When start_offset_ms > 0, seek to the nearest keyframe at or before target PTS
    if (config_.start_offset_ms > 0)
    {
      auto seek_start_time = std::chrono::steady_clock::now();

      // Get media duration for modulo calculation (INV-P6-008)
      AVStream* video_stream = format_ctx_->streams[video_stream_index_];
      int64_t media_duration_us = 0;
      if (format_ctx_->duration != AV_NOPTS_VALUE)
      {
        // format_ctx_->duration is in AV_TIME_BASE (microseconds)
        media_duration_us = format_ctx_->duration;
      }
      else if (video_stream->duration != AV_NOPTS_VALUE)
      {
        // Stream duration in stream time_base
        media_duration_us = av_rescale_q(
            video_stream->duration,
            video_stream->time_base,
            {1, static_cast<int>(kMicrosecondsPerSecond)});
      }

      // Calculate effective seek target in media time (INV-P6-008)
      // For looping content: target = start_offset % media_duration
      int64_t raw_target_us = config_.start_offset_ms * 1000;  // ms -> us
      int64_t target_us = raw_target_us;

      if (media_duration_us > 0 && raw_target_us >= media_duration_us)
      {
        target_us = raw_target_us % media_duration_us;
        std::cout << "[FileProducer] Phase 6 (INV-P6-008): Adjusted seek target for looping - "
                  << "raw_offset=" << raw_target_us << "us, media_duration=" << media_duration_us
                  << "us, effective_target=" << target_us << "us" << std::endl;
      }

      // Store effective seek target for frame admission (INV-P6-008)
      effective_seek_target_us_ = target_us;

      int64_t target_ts = av_rescale_q(
          target_us,
          {1, static_cast<int>(kMicrosecondsPerSecond)},
          video_stream->time_base);

      std::cout << "[FileProducer] Phase 6: Seeking to offset " << (target_us / 1000)
                << "ms (target_ts=" << target_ts << " in stream time_base)" << std::endl;

      // INV-P6-002: Seek to nearest keyframe at or before target
      // INV-P6-003: Single seek per join (no retry loops)
      int seek_ret = av_seek_frame(format_ctx_, video_stream_index_, target_ts, AVSEEK_FLAG_BACKWARD);

      if (seek_ret < 0)
      {
        char errbuf[AV_ERROR_MAX_STRING_SIZE];
        av_strerror(seek_ret, errbuf, sizeof(errbuf));
        std::cerr << "[FileProducer] Phase 6: Seek failed (" << errbuf
                  << "), falling back to decode-from-start with frame admission" << std::endl;
        // INV-P6-003: No retry loop - fall back to decode-from-start
        // Frame admission (INV-P6-004) will still filter frames < start_offset
      }
      else
      {
        // INV-P6-006: Flush decoder buffers after seek to maintain A/V sync
        avcodec_flush_buffers(codec_ctx_);

        if (audio_codec_ctx_ != nullptr)
        {
          avcodec_flush_buffers(audio_codec_ctx_);
        }

        auto seek_end_time = std::chrono::steady_clock::now();
        auto seek_latency_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            seek_end_time - seek_start_time).count();

        // Phase 6 observability: emit structured log
        std::cout << "[FileProducer] Phase 6: Seek complete - target_pts=" << target_us
                  << "us, seek_latency_ms=" << seek_latency_ms << std::endl;

        std::ostringstream msg;
        msg << "target_pts=" << target_us << "us, seek_latency_ms=" << seek_latency_ms;
        EmitEvent("seek_complete", msg.str());
      }
    }

    decoder_initialized_ = true;
    eof_reached_ = false;
    eof_event_emitted_ = false;
    return true;
  }

  void FileProducer::CloseDecoder()
  {
    if (sws_ctx_)
    {
      sws_freeContext(sws_ctx_);
      sws_ctx_ = nullptr;
    }

    if (intermediate_frame_)
    {
      if (intermediate_frame_->data[0])
      {
        av_freep(&intermediate_frame_->data[0]);
      }
      av_frame_free(&intermediate_frame_);
      intermediate_frame_ = nullptr;
    }

    if (scaled_frame_)
    {
      if (scaled_frame_->data[0])
      {
        av_freep(&scaled_frame_->data[0]);
      }
      av_frame_free(&scaled_frame_);
      scaled_frame_ = nullptr;
    }

    if (frame_)
    {
      av_frame_free(&frame_);
      frame_ = nullptr;
    }

    if (packet_)
    {
      av_packet_free(&packet_);
      packet_ = nullptr;
    }

    if (codec_ctx_)
    {
      avcodec_free_context(&codec_ctx_);
      codec_ctx_ = nullptr;
    }

    if (format_ctx_)
    {
      avformat_close_input(&format_ctx_);
      format_ctx_ = nullptr;
    }

    // Phase 8.9: Clean up audio decoder
    if (audio_frame_)
    {
      av_frame_free(&audio_frame_);
      audio_frame_ = nullptr;
    }

    if (audio_codec_ctx_)
    {
      avcodec_free_context(&audio_codec_ctx_);
      audio_codec_ctx_ = nullptr;
    }

    decoder_initialized_ = false;
    video_stream_index_ = -1;
    audio_stream_index_ = -1;
    eof_reached_ = false;
    audio_eof_reached_ = false;
    eof_event_emitted_ = false;
  }

  bool FileProducer::ProduceRealFrame()
  {
    if (!decoder_initialized_)
    {
      return false;
    }

    // Decode ONE frame at a time (paced according to fake time)
    // Read packet
    int ret = av_read_frame(format_ctx_, packet_);

    if (ret == AVERROR_EOF)
    {
      eof_reached_ = true;
      audio_eof_reached_ = true;
      return false;
    }

    if (ret < 0)
    {
      av_packet_unref(packet_);
      return false;  // Read error
    }

    // Phase 8.9: Dispatch packet based on stream index
    // If it's an audio packet, send to audio decoder and continue reading
    if (packet_->stream_index == audio_stream_index_ && audio_codec_ctx_ != nullptr)
    {
      // Send audio packet to decoder
      ret = avcodec_send_packet(audio_codec_ctx_, packet_);
      av_packet_unref(packet_);

      if (ret >= 0 || ret == AVERROR(EAGAIN))
      {
        // Try to receive any decoded audio frames
        ReceiveAudioFrames();
      }
      return true;  // Continue reading packets (looking for video)
    }

    // Check if packet is from video stream
    if (packet_->stream_index != video_stream_index_)
    {
      av_packet_unref(packet_);
      return true;  // Skip other non-video/non-audio packets, try again
    }

    // Send packet to decoder
    ret = avcodec_send_packet(codec_ctx_, packet_);
    av_packet_unref(packet_);

    if (ret < 0)
    {
      std::cerr << "[FileProducer] Video send_packet error: " << ret << std::endl;
      return false;  // Decode error
    }

    // Receive decoded frame
    ret = avcodec_receive_frame(codec_ctx_, frame_);

    if (ret == AVERROR(EAGAIN))
    {
      return true;  // Need more packets, try again
    }

    if (ret < 0)
    {
      std::cerr << "[FileProducer] Video receive_frame error: " << ret << std::endl;
      return false;  // Decode error
    }

    // Successfully decoded a frame - scale and assemble
    if (!ScaleFrame())
    {
      return false;
    }

    buffer::Frame output_frame;
    if (!AssembleFrame(output_frame))
    {
      return false;
    }

    // Extract frame PTS in microseconds (media-relative)
    int64_t base_pts_us = output_frame.metadata.pts;

    // Debug: log video frame decode with full PTS info for diagnosis
    video_frame_count_++;
    if (video_frame_count_ <= 10 || video_frame_count_ % 100 == 0)
    {
      std::cout << "[FileProducer] VIDEO_PTS raw_ts=" << frame_->pts
                << " tb=" << format_ctx_->streams[video_stream_index_]->time_base.num
                << "/" << format_ctx_->streams[video_stream_index_]->time_base.den
                << " -> pts_us=" << base_pts_us
                << " target_us=" << effective_seek_target_us_
                << (base_pts_us < effective_seek_target_us_ ? " DISCARD" : " EMIT")
                << std::endl;
    }

    // Phase 8: Load shadow mode state early - needed for gating decisions
    bool in_shadow_mode = shadow_decode_mode_.load(std::memory_order_acquire);

    // Phase 6 (INV-P6-004/INV-P6-008): frame admission — discard until PTS >= effective_seek_target
    // SCOPED by Phase 8 (INV-P8-TIME-BLINDNESS): This gating applies ONLY when:
    //   - TimelineController is NOT active (legacy mode), OR
    //   - Producer is in shadow mode, OR
    //   - TimelineController mapping is PENDING (awaiting seek-stable frame to lock)
    //
    // The mapping_pending case is CRITICAL: when BeginSegment is called, the mapping
    // is pending until the first frame locks it. We MUST continue Phase 6 gating
    // during this window to ensure only seek-stable frames (MT >= target) can lock
    // the mapping. Without this, the first random keyframe would lock with wrong MT.
    bool mapping_pending = timeline_controller_ && timeline_controller_->IsMappingPending();
    bool phase6_gating_active = !timeline_controller_ || in_shadow_mode || mapping_pending;

    if (phase6_gating_active && base_pts_us < effective_seek_target_us_)
    {
      video_discard_count_++;
      if (video_discard_count_ <= 5 || video_discard_count_ % 100 == 0)
      {
        std::cout << "[FileProducer] DROP_VIDEO_BEFORE_START #" << video_discard_count_
                  << " pts_us=" << base_pts_us
                  << " target_us=" << effective_seek_target_us_
                  << " (need " << ((effective_seek_target_us_ - base_pts_us) / 1000) << "ms more)"
                  << std::endl;
      }
      return true;  // Discard frame; continue decoding
    }

    // Phase 6 (INV-P6-005/INV-P6-ALIGN-FIRST-FRAME): Log first emitted frame accuracy after seek
    // SCOPED by Phase 8: Only log in legacy/shadow mode. In Phase 8 with TimelineController,
    // "first frame accuracy" is meaningless - TimelineController assigns CT, not producer.
    if (phase6_gating_active && effective_seek_target_us_ > 0 && first_frame_pts_us_ == 0)
    {
      int64_t accuracy_us = base_pts_us - effective_seek_target_us_;
      std::cout << "[FileProducer] Phase 6: First emitted video frame - target_pts=" << effective_seek_target_us_
                << "us, first_emitted_pts=" << base_pts_us
                << "us, accuracy=" << accuracy_us << "us ("
                << (accuracy_us / 1000) << "ms)" << std::endl;

      std::ostringstream msg;
      msg << "target_pts=" << effective_seek_target_us_ << "us, first_emitted_pts=" << base_pts_us
          << "us, accuracy_ms=" << (accuracy_us / 1000);
      EmitEvent("first_frame_emitted", msg.str());
    }

    // Phase 8.6: no duration-based cutoff. Run until natural EOF (decoder returns no more frames).
    // segment_end_pts_us_ is not used to stop; asset duration may be logged but must not force stop.

    // Phase 8: Unified Timeline Authority
    // Three paths for PTS/CT assignment:
    // 1. Shadow mode: emit raw MT only (time-blind, no CT assignment)
    // 2. TimelineController available: use it for CT assignment
    // 3. Legacy (no TimelineController): use pts_offset_us_
    int64_t frame_pts_us;
    // Note: in_shadow_mode already loaded above for Phase 6 gating scope check

    // Phase 8: CRITICAL - Check write barrier BEFORE touching TimelineController.
    // If write barrier is set, this producer is being phased out during a segment
    // transition. We must NOT call AdmitFrame() because that could lock the new
    // segment's mapping with the wrong MT (from the old producer).
    if (writes_disabled_.load(std::memory_order_acquire))
    {
      // Silently drop - producer is being phased out
      return true;
    }

    if (in_shadow_mode)
    {
      // Phase 8 §7.2: Shadow mode emits raw MT only.
      // No offsets, no CT assignment. PTS field carries MT for caching.
      // CT will be assigned by TimelineController after SwitchToLive.
      frame_pts_us = base_pts_us;
      output_frame.metadata.has_ct = false;  // NOT timeline-valid yet
    }
    else if (timeline_controller_)
    {
      // Phase 8: TimelineController assigns CT
      int64_t assigned_ct_us = 0;
      timing::AdmissionResult result = timeline_controller_->AdmitFrame(base_pts_us, assigned_ct_us);

      switch (result)
      {
        case timing::AdmissionResult::ADMITTED:
          frame_pts_us = assigned_ct_us;
          output_frame.metadata.has_ct = true;  // Timeline-valid
          break;

        case timing::AdmissionResult::REJECTED_LATE:
          // Frame is too late - drop it and continue decoding
          std::cout << "[FileProducer] Phase 8: Frame rejected (late), MT=" << base_pts_us
                    << "us, CT_cursor=" << timeline_controller_->GetCTCursor() << "us" << std::endl;
          return true;  // Continue decoding next frame

        case timing::AdmissionResult::REJECTED_EARLY:
          // Frame is too early - this is unusual, log and drop
          std::cout << "[FileProducer] Phase 8: Frame rejected (early), MT=" << base_pts_us
                    << "us, CT_cursor=" << timeline_controller_->GetCTCursor() << "us" << std::endl;
          return true;  // Continue decoding next frame

        case timing::AdmissionResult::REJECTED_NO_MAPPING:
          // No segment mapping - this is a configuration error
          std::cerr << "[FileProducer] Phase 8: ERROR - No segment mapping, MT=" << base_pts_us << "us" << std::endl;
          return true;  // Continue decoding (maybe mapping will be set)
      }
    }
    else
    {
      // Legacy path (no TimelineController): apply PTS offset for alignment
      frame_pts_us = base_pts_us + pts_offset_us_;
      output_frame.metadata.has_ct = true;  // Legacy assumes PTS == CT
    }

    output_frame.metadata.pts = frame_pts_us;
    last_decoded_frame_pts_us_ = frame_pts_us;
    last_pts_us_ = frame_pts_us;

    // Establish time mapping on first emitted frame (VIDEO_EPOCH_SET)
    if (first_frame_pts_us_ == 0)
    {
      first_frame_pts_us_ = frame_pts_us;

      // Critical diagnostic: video epoch is now set, audio can start emitting
      std::cout << "[FileProducer] VIDEO_EPOCH_SET first_video_pts_us=" << frame_pts_us
                << " target_us=" << effective_seek_target_us_ << std::endl;

      // Phase 8: If TimelineController is active, it owns the epoch.
      // Producer is "time-blind" and should not set epoch.
      if (timeline_controller_)
      {
        std::cout << "[FileProducer] Phase 8: TimelineController owns epoch (producer is time-blind)"
                  << std::endl;
        // Still need playback_start_utc_us_ for internal pacing calculations
        if (master_clock_)
        {
          playback_start_utc_us_ = master_clock_->now_utc_us();
        }
      }
      else
      {
        // Legacy path: Per Phase 7 contract (INV-P7-004): Epoch stability.
        // Only the first (live) producer sets the epoch.
        // Preview/shadow producers must NOT reset the epoch - they inherit the channel's epoch.
        // Belt-and-suspenders: even if shadow_mode check fails, TrySetEpochOnce() will refuse.
        bool shadow_mode = shadow_decode_mode_.load(std::memory_order_acquire);
        if (master_clock_ && !shadow_mode)
        {
          playback_start_utc_us_ = master_clock_->now_utc_us();
          // CRITICAL FIX for mid-segment join (Phase 6):
          // The epoch must account for the media PTS offset after seek.
          // Without this, scheduled_to_utc_us(frame_pts) returns a time far in the future
          // (playback_start + frame_pts), when it should return a time near playback_start.
          //
          // Correct formula: epoch = playback_start - first_frame_pts
          // Then: scheduled_to_utc_us(frame_pts) = epoch + frame_pts
          //                                      = playback_start - first_frame_pts + frame_pts
          //                                      = playback_start + (frame_pts - first_frame_pts)
          // So the first frame is due at playback_start, and subsequent frames are due
          // at playback_start + (their offset from first frame).
          int64_t epoch_utc_us = playback_start_utc_us_ - first_frame_pts_us_;

          // Phase 7: Use TrySetEpochOnce with LIVE role - if epoch already set, this is a no-op
          if (master_clock_->TrySetEpochOnce(epoch_utc_us, timing::MasterClock::EpochSetterRole::LIVE)) {
            std::cout << "[FileProducer] Clock epoch synchronized: playback_start="
                      << playback_start_utc_us_ << "us, first_frame_pts=" << first_frame_pts_us_
                      << "us, epoch=" << epoch_utc_us << "us" << std::endl;
          } else {
            // Epoch was already set by another producer - read existing epoch
            int64_t existing_epoch = master_clock_->get_epoch_utc_us();
            std::cout << "[FileProducer] Epoch already established (existing=" << existing_epoch
                      << "), not resetting (INV-P7-004)" << std::endl;
          }
        } else if (shadow_mode) {
          std::cout << "[FileProducer] Shadow mode: inheriting existing epoch (no reset)" << std::endl;
        }
      }
    }

    // Shadow mode: cache first frame only, do NOT fill buffer yet.
    // Buffer must be filled AFTER AlignPTS is called in SwitchToLive to ensure correct PTS.
    // Phase 7: Epoch protection is via TrySetEpochOnce (PREVIEW role rejected).
    // Note: in_shadow_mode was loaded earlier for Phase 8 TimelineController check
    if (in_shadow_mode)
    {
      // Cache the first frame for potential use
      std::lock_guard<std::mutex> lock(shadow_decode_mutex_);
      if (!cached_first_frame_)
      {
        cached_first_frame_ = std::make_unique<buffer::Frame>(output_frame);
        shadow_decode_ready_.store(true, std::memory_order_release);
        std::cout << "[FileProducer] Shadow decode: first frame cached, PTS="
                  << frame_pts_us << std::endl;
        EmitEvent("ShadowDecodeReady", "");
      }
      // Do NOT fill buffer in shadow mode - wait for AlignPTS before filling
      return true;
    }

    // Calculate target UTC time for this frame: playback_start + (frame_pts - first_frame_pts)
    int64_t frame_offset_us = frame_pts_us - first_frame_pts_us_;
    int64_t target_utc_us = playback_start_utc_us_ + frame_offset_us;

    // Frame decoded and ready to push

    // Phase 8.9: Try to receive any pending audio frames (non-blocking)
    if (audio_stream_index_ >= 0 && !audio_eof_reached_)
    {
      ReceiveAudioFrames();
    }

    // Wait until target UTC time before pushing (real-time pacing)
    if (master_clock_)
    {
      int64_t now_us = master_clock_->now_utc_us();
      if (now_us < target_utc_us)
      {
        if (master_clock_->is_fake())
        {
          // Busy-wait for fake clock to advance
          while (master_clock_->now_utc_us() < target_utc_us &&
                 !stop_requested_.load(std::memory_order_acquire))
          {
            std::this_thread::yield();
          }
        }
        else
        {
          // Sleep until target time for real clock (real-time pacing)
          int64_t sleep_us = target_utc_us - now_us;
          if (sleep_us > 0 && !stop_requested_.load(std::memory_order_acquire))
          {
            std::this_thread::sleep_for(std::chrono::microseconds(sleep_us));
          }
        }
      }
    }

    // Phase 7: Check write barrier before pushing
    if (writes_disabled_.load(std::memory_order_acquire)) {
      return true;  // Silently drop - producer is being force-stopped
    }

    // Attempt to push decoded frame
    if (output_buffer_.Push(output_frame))
    {
      uint64_t produced = frames_produced_.fetch_add(1, std::memory_order_relaxed) + 1;
      if (produced <= 5 || produced % 100 == 0)
      {
        std::cout << "[FileProducer] Video frame pushed #" << produced
                  << ", pts=" << output_frame.metadata.pts << std::endl;
      }
      return true;
    }
    else
    {
      // Buffer is full, back off
      uint64_t full_count = buffer_full_count_.fetch_add(1, std::memory_order_relaxed) + 1;
      if (full_count <= 5 || full_count % 100 == 0)
      {
        std::cerr << "[FileProducer] Video buffer full #" << full_count
                  << ", pts=" << output_frame.metadata.pts << std::endl;
      }
      if (master_clock_)
      {
        int64_t now_utc_us = master_clock_->now_utc_us();
        int64_t deadline_utc_us = now_utc_us + kProducerBackoffUs;
        if (master_clock_->is_fake())
        {
          // For fake clock, busy-wait
          while (master_clock_->now_utc_us() < deadline_utc_us && 
                 !stop_requested_.load(std::memory_order_acquire))
          {
            std::this_thread::yield();
          }
        }
        else
        {
          while (master_clock_->now_utc_us() < deadline_utc_us && 
                 !stop_requested_.load(std::memory_order_acquire))
          {
            std::this_thread::sleep_for(std::chrono::microseconds(100));
          }
        }
      }
      else
      {
        std::this_thread::sleep_for(std::chrono::microseconds(kProducerBackoffUs));
      }
      // Retry on next iteration
      return true;  // Frame was decoded successfully, just couldn't push
    }
  }

  bool FileProducer::ScaleFrame()
  {
    if (!sws_ctx_ || !frame_ || !scaled_frame_)
    {
      return false;
    }

    // Check if padding needed (aspect preserve)
    bool needs_padding = (intermediate_frame_ != nullptr);

    // Diagnostic for first 5 frames
    if (++scale_diag_count_ <= 5) {
      std::cout << "[FileProducer] SCALE_DIAG frame=" << scale_diag_count_
                << " src=" << frame_->width << "x" << frame_->height
                << " src_linesize=[" << frame_->linesize[0] << "," << frame_->linesize[1] << "," << frame_->linesize[2] << "]"
                << " scale=" << scale_width_ << "x" << scale_height_
                << " pad=(" << pad_x_ << "," << pad_y_ << ")"
                << " target=" << config_.target_width << "x" << config_.target_height
                << " target_linesize=[" << scaled_frame_->linesize[0] << "," << scaled_frame_->linesize[1] << "," << scaled_frame_->linesize[2] << "]"
                << " needs_padding=" << (needs_padding ? "Y" : "N")
                << std::endl;
      if (needs_padding && intermediate_frame_) {
        std::cout << "[FileProducer] SCALE_DIAG intermediate_linesize=["
                  << intermediate_frame_->linesize[0] << ","
                  << intermediate_frame_->linesize[1] << ","
                  << intermediate_frame_->linesize[2] << "]" << std::endl;
      }
      // Log first 16 bytes of decoded Y plane
      std::cout << "[FileProducer] SCALE_DIAG src_Y_first16: ";
      for (int i = 0; i < 16 && i < frame_->linesize[0]; ++i) {
        std::cout << std::hex << std::setfill('0') << std::setw(2) << (int)frame_->data[0][i] << " ";
      }
      std::cout << std::dec << std::endl;
    }

    // Scale to intermediate dimensions (preserving aspect if needed)
    AVFrame* scale_target = needs_padding ? intermediate_frame_ : scaled_frame_;

    // Scale frame
    sws_scale(sws_ctx_,
              frame_->data, frame_->linesize, 0, codec_ctx_->height,
              scale_target->data, scale_target->linesize);

    // If padding needed, copy scaled frame to final frame with padding
    if (needs_padding) {
      // Clear target frame (black for Y, gray for UV)
      // Use linesize * height to clear entire buffer including alignment padding
      std::memset(scaled_frame_->data[0], 0,
                  static_cast<size_t>(scaled_frame_->linesize[0]) * config_.target_height);
      std::memset(scaled_frame_->data[1], 128,
                  static_cast<size_t>(scaled_frame_->linesize[1]) * (config_.target_height / 2));
      std::memset(scaled_frame_->data[2], 128,
                  static_cast<size_t>(scaled_frame_->linesize[2]) * (config_.target_height / 2));

      // Copy Y plane with padding
      for (int y = 0; y < scale_height_; y++) {
        std::memcpy(scaled_frame_->data[0] + (pad_y_ + y) * scaled_frame_->linesize[0] + pad_x_,
                    intermediate_frame_->data[0] + y * intermediate_frame_->linesize[0],
                    scale_width_);
      }

      // Copy U plane with padding
      int uv_pad_x = pad_x_ / 2;
      int uv_pad_y = pad_y_ / 2;
      for (int y = 0; y < scale_height_ / 2; y++) {
        std::memcpy(scaled_frame_->data[1] + (uv_pad_y + y) * scaled_frame_->linesize[1] + uv_pad_x,
                    intermediate_frame_->data[1] + y * intermediate_frame_->linesize[1],
                    scale_width_ / 2);
      }

      // Copy V plane with padding
      for (int y = 0; y < scale_height_ / 2; y++) {
        std::memcpy(scaled_frame_->data[2] + (uv_pad_y + y) * scaled_frame_->linesize[2] + uv_pad_x,
                    intermediate_frame_->data[2] + y * intermediate_frame_->linesize[2],
                    scale_width_ / 2);
      }
    }

    // Diagnostic for first 5 frames - output data
    if (scale_diag_count_ <= 5) {
      // Sample Y plane at content start (after padding)
      int sample_y = pad_y_;
      int sample_x = pad_x_;
      std::cout << "[FileProducer] SCALE_DIAG output_Y at (" << sample_x << "," << sample_y << "): ";
      uint8_t* row = scaled_frame_->data[0] + sample_y * scaled_frame_->linesize[0];
      for (int i = sample_x; i < sample_x + 16 && i < config_.target_width; ++i) {
        std::cout << std::hex << std::setfill('0') << std::setw(2) << (int)row[i] << " ";
      }
      std::cout << std::dec << std::endl;
      // Also sample the pillarbox/letterbox area (should be black = 0 for Y)
      if (pad_x_ > 0) {
        std::cout << "[FileProducer] SCALE_DIAG pillarbox_Y at (0,0): ";
        uint8_t* pbox_row = scaled_frame_->data[0];
        for (int i = 0; i < std::min(pad_x_, 16); ++i) {
          std::cout << std::hex << std::setfill('0') << std::setw(2) << (int)pbox_row[i] << " ";
        }
        std::cout << std::dec << std::endl;
      }
    }

    return true;
  }

  bool FileProducer::AssembleFrame(buffer::Frame& output_frame)
  {
    if (!scaled_frame_)
    {
      return false;
    }

    // Set frame dimensions
    output_frame.width = config_.target_width;
    output_frame.height = config_.target_height;

    // Calculate PTS/DTS in microseconds
    // Use frame PTS (from decoded frame) or best_effort_timestamp
    int64_t pts = frame_->pts != AV_NOPTS_VALUE ? frame_->pts : frame_->best_effort_timestamp;
    int64_t dts = frame_->pkt_dts != AV_NOPTS_VALUE ? frame_->pkt_dts : pts;

    // Convert to microseconds
    int64_t pts_us = static_cast<int64_t>(pts * time_base_ * kMicrosecondsPerSecond);
    int64_t dts_us = static_cast<int64_t>(dts * time_base_ * kMicrosecondsPerSecond);

    // Ensure PTS monotonicity
    if (pts_us <= last_pts_us_)
    {
      pts_us = last_pts_us_ + frame_interval_us_;
    }
    last_pts_us_ = pts_us;

    // Ensure DTS <= PTS
    if (dts_us > pts_us)
    {
      dts_us = pts_us;
    }

    output_frame.metadata.pts = pts_us;
    output_frame.metadata.dts = dts_us;
    output_frame.metadata.duration = 1.0 / config_.target_fps;
    output_frame.metadata.asset_uri = config_.asset_uri;

    // Copy YUV420 planar data
    int y_size = config_.target_width * config_.target_height;
    int uv_size = (config_.target_width / 2) * (config_.target_height / 2);
    int total_size = y_size + 2 * uv_size;

    output_frame.data.resize(total_size);

    // Copy Y plane
    uint8_t* dst = output_frame.data.data();
    for (int y = 0; y < config_.target_height; y++)
    {
      std::memcpy(dst + y * config_.target_width,
                  scaled_frame_->data[0] + y * scaled_frame_->linesize[0],
                  config_.target_width);
    }

    // Copy U plane
    dst += y_size;
    for (int y = 0; y < config_.target_height / 2; y++)
    {
      std::memcpy(dst + y * (config_.target_width / 2),
                  scaled_frame_->data[1] + y * scaled_frame_->linesize[1],
                  config_.target_width / 2);
    }

    // Copy V plane
    dst += uv_size;
    for (int y = 0; y < config_.target_height / 2; y++)
    {
      std::memcpy(dst + y * (config_.target_width / 2),
                  scaled_frame_->data[2] + y * scaled_frame_->linesize[2],
                  config_.target_width / 2);
    }

    return true;
  }

  void FileProducer::ProduceStubFrame()
  {
    // Wait until deadline (aligned to master clock if available)
    if (master_clock_)
    {
      int64_t now_utc_us = master_clock_->now_utc_us();
      int64_t deadline = next_stub_deadline_utc_.load(std::memory_order_acquire);
      if (deadline == 0)
      {
        // First frame: produce immediately, set next deadline
        deadline = now_utc_us + frame_interval_us_;
        next_stub_deadline_utc_.store(deadline, std::memory_order_release);
        // Don't wait for first frame
      }
      else
      {
        // Wait until deadline for subsequent frames
        while (now_utc_us < deadline && !stop_requested_.load(std::memory_order_acquire))
        {
          std::this_thread::sleep_for(std::chrono::microseconds(100));
          now_utc_us = master_clock_->now_utc_us();
        }
        next_stub_deadline_utc_.store(deadline + frame_interval_us_, std::memory_order_release);
      }
    }
    else
    {
      // Without master clock, check if this is the first frame
      int64_t pts_counter = stub_pts_counter_.load(std::memory_order_acquire);
      if (pts_counter == 0)
      {
        // First frame: produce immediately
      }
      else
      {
        // Subsequent frames: wait for frame interval
        std::this_thread::sleep_for(std::chrono::microseconds(frame_interval_us_));
      }
    }

    // Create stub decoded frame
    buffer::Frame frame;
    frame.width = config_.target_width;
    frame.height = config_.target_height;
    
    int64_t pts_counter = stub_pts_counter_.fetch_add(1, std::memory_order_relaxed);
    int64_t base_pts = pts_counter * frame_interval_us_;
    frame.metadata.pts = base_pts + pts_offset_us_;  // Apply PTS offset for alignment
    frame.metadata.dts = frame.metadata.pts;
    frame.metadata.duration = 1.0 / config_.target_fps;
    frame.metadata.asset_uri = config_.asset_uri;

    // Update last_pts_us_ for PTS tracking
    last_pts_us_ = frame.metadata.pts;

    // Generate YUV420 planar data (stub: all zeros for now)
    size_t frame_size = static_cast<size_t>(config_.target_width * config_.target_height * 1.5);
    frame.data.resize(frame_size, 0);

    // Check if in shadow decode mode
    bool shadow_mode = shadow_decode_mode_.load(std::memory_order_acquire);
    if (shadow_mode)
    {
      // Shadow mode: cache first frame, don't push to buffer
      std::lock_guard<std::mutex> lock(shadow_decode_mutex_);
      if (!cached_first_frame_)
      {
        cached_first_frame_ = std::make_unique<buffer::Frame>(frame);
        shadow_decode_ready_.store(true, std::memory_order_release);
        std::cout << "[FileProducer] Shadow decode: first frame cached, PTS="
                  << frame.metadata.pts << std::endl;
        EmitEvent("ShadowDecodeReady", "");
      }
      // Don't push to buffer in shadow mode - wait for AlignPTS
      return;
    }

    // Phase 7: Check write barrier before pushing
    if (writes_disabled_.load(std::memory_order_acquire)) {
      return;  // Silently drop - producer is being force-stopped
    }

    // Normal mode: attempt to push decoded frame
    if (output_buffer_.Push(frame))
    {
      frames_produced_.fetch_add(1, std::memory_order_relaxed);
    }
    else
    {
      // Buffer is full, back off
      buffer_full_count_.fetch_add(1, std::memory_order_relaxed);
      if (master_clock_)
      {
        // Wait using master clock if available
        int64_t now_utc_us = master_clock_->now_utc_us();
        int64_t deadline_utc_us = now_utc_us + kProducerBackoffUs;
        while (master_clock_->now_utc_us() < deadline_utc_us && 
               !stop_requested_.load(std::memory_order_acquire))
        {
          std::this_thread::sleep_for(std::chrono::microseconds(100));
        }
      }
      else
      {
        std::this_thread::sleep_for(std::chrono::microseconds(kProducerBackoffUs));
      }
    }
  }

  void FileProducer::SetShadowDecodeMode(bool enabled)
  {
    shadow_decode_mode_.store(enabled, std::memory_order_release);
    if (!enabled)
    {
      // Exiting shadow mode - clear cached frame
      std::lock_guard<std::mutex> lock(shadow_decode_mutex_);
      cached_first_frame_.reset();
      shadow_decode_ready_.store(false, std::memory_order_release);
    }
    else
    {
      // Entering shadow mode - reset readiness state
      std::lock_guard<std::mutex> lock(shadow_decode_mutex_);
      shadow_decode_ready_.store(false, std::memory_order_release);
      cached_first_frame_.reset();
    }
  }

  bool FileProducer::IsShadowDecodeMode() const
  {
    return shadow_decode_mode_.load(std::memory_order_acquire);
  }

  bool FileProducer::IsShadowDecodeReady() const
  {
    return shadow_decode_ready_.load(std::memory_order_acquire);
  }

  int64_t FileProducer::GetNextPTS() const
  {
    // Return the PTS that the next frame will have
    // This is last_pts_us_ + frame_interval_us_ + pts_offset_us_
    // Note: last_pts_us_ is not atomic, but we're reading it in a const method
    // In practice, this is called from the state machine which holds a lock
    int64_t next_pts = last_pts_us_;
    if (next_pts == 0)
    {
      // First frame - use pts_offset_us_ as base
      return pts_offset_us_;
    }
    return next_pts + frame_interval_us_ + pts_offset_us_;
  }

  void FileProducer::AlignPTS(int64_t target_pts)
  {
    // Phase 7: Idempotent - only align once
    if (pts_aligned_.exchange(true, std::memory_order_acq_rel)) {
      std::cout << "[FileProducer] AlignPTS ignored (already aligned)" << std::endl;
      return;
    }

    // Calculate offset needed to align next frame to target_pts
    int64_t next_pts_without_offset = last_pts_us_;
    if (next_pts_without_offset == 0)
    {
      // First frame - set offset directly
      pts_offset_us_ = target_pts;
    }
    else
    {
      // Calculate offset: target_pts - (next_pts_without_offset + frame_interval_us_)
      pts_offset_us_ = target_pts - (next_pts_without_offset + frame_interval_us_);
    }
    std::cout << "[FileProducer] PTS aligned: target=" << target_pts
              << ", offset=" << pts_offset_us_ << std::endl;
  }

  bool FileProducer::IsPTSAligned() const
  {
    return pts_aligned_.load(std::memory_order_acquire);
  }

  // Phase 8.9: Receive audio frames that were already sent to the decoder
  // This does NOT read packets - packets are dispatched by ProduceRealFrame()
  // Phase 6 fix: Process only ONE audio frame per call to prevent burst emission.
  // This allows video/audio to interleave properly for correct clock-gating pacing.
  bool FileProducer::ReceiveAudioFrames()
  {
    if (audio_stream_index_ < 0 || !audio_codec_ctx_ || !audio_frame_ || audio_eof_reached_)
    {
      return false;
    }

    bool received_any = false;
    bool processed_one = false;  // Phase 6: Exit after processing one frame

    // Receive decoded audio frames - but exit after processing ONE to prevent burst
    while (!stop_requested_.load(std::memory_order_acquire) && !processed_one)
    {
      int ret = avcodec_receive_frame(audio_codec_ctx_, audio_frame_);
      if (ret == AVERROR(EAGAIN))
      {
        // No more frames available right now
        break;
      }
      if (ret == AVERROR_EOF)
      {
        audio_eof_reached_ = true;
        break;
      }
      if (ret < 0)
      {
        // Decode error
        break;
      }

      // Convert to AudioFrame and push to buffer
      buffer::AudioFrame output_audio_frame;
      if (ConvertAudioFrame(audio_frame_, output_audio_frame))
      {
        // Phase 8: CRITICAL - Check write barrier BEFORE any processing.
        // If write barrier is set, silently drop all frames from this producer.
        if (writes_disabled_.load(std::memory_order_acquire))
        {
          av_frame_unref(audio_frame_);
          continue;  // Silently drop
        }

        // Track base PTS before offset
        int64_t base_pts_us = output_audio_frame.pts_us;

        // Phase 6 (INV-P6-004/INV-P6-008): Audio frame admission gate
        // SCOPED by Phase 8 (INV-P8-TIME-BLINDNESS): This gating applies ONLY when:
        //   - TimelineController is NOT active (legacy mode), OR
        //   - Producer is in shadow mode, OR
        //   - TimelineController mapping is PENDING (awaiting seek-stable frame)
        bool audio_shadow_mode = shadow_decode_mode_.load(std::memory_order_acquire);
        bool audio_mapping_pending = timeline_controller_ && timeline_controller_->IsMappingPending();
        bool audio_phase6_gating_active = !timeline_controller_ || audio_shadow_mode || audio_mapping_pending;

        if (audio_phase6_gating_active && base_pts_us < effective_seek_target_us_)
        {
          // Discard audio frame before target PTS; continue decoding
          av_frame_unref(audio_frame_);
          continue;
        }

        // Phase 6 (INV-P6-005/006/INV-P6-ALIGN-FIRST-FRAME): Log first audio frame accuracy
        // SCOPED by Phase 8: Only log in legacy/shadow mode.
        if (audio_phase6_gating_active && effective_seek_target_us_ > 0 && last_audio_pts_us_ == 0)
        {
          int64_t accuracy_us = base_pts_us - effective_seek_target_us_;
          std::cout << "[FileProducer] Phase 6: First audio frame - target_pts=" << effective_seek_target_us_
                    << "us, first_emitted_pts=" << base_pts_us
                    << "us, accuracy=" << accuracy_us << "us ("
                    << (accuracy_us / 1000) << "ms)" << std::endl;
        }

        // Apply PTS offset for alignment (same as video)
        output_audio_frame.pts_us += pts_offset_us_;

        // Enforce monotonicity
        bool pts_adjusted = false;
        if (output_audio_frame.pts_us <= last_audio_pts_us_)
        {
          int64_t old_pts = output_audio_frame.pts_us;
          output_audio_frame.pts_us = last_audio_pts_us_ + 1;
          pts_adjusted = true;
          std::cout << "[FileProducer] Audio PTS adjusted: " << old_pts
                    << " -> " << output_audio_frame.pts_us
                    << " (last_audio_pts=" << last_audio_pts_us_ << ")" << std::endl;
        }
        last_audio_pts_us_ = output_audio_frame.pts_us;

        // Phase 6 (INV-P6-010): Audio MUST NOT emit until video establishes the epoch
        // SCOPED by Phase 8 (INV-P8-TIME-BLINDNESS): This epoch gating applies ONLY when:
        //   - TimelineController is NOT active, OR
        //   - Producer is in shadow mode
        // When TimelineController is active and NOT in shadow mode, audio/video sync
        // is handled by TimelineController's unified CT assignment, not producer epoch gating.
        //
        // CRITICAL: Do NOT sleep/block for audio clock gating!
        // Sleeping for audio would starve video decoding because they share a thread.
        // Instead:
        // 1. Wait for video epoch before emitting any audio (Phase 6 only)
        // 2. After epoch, emit audio immediately (no sleep)
        // 3. Rely on buffer backpressure and downstream encoder to pace audio
        //
        // The downstream encoder/muxer interleaves audio with video based on PTS,
        // so audio emitted "early" will be held until the video catches up.
        if (master_clock_ && audio_phase6_gating_active)
        {
          // Skip audio emission if video epoch not yet established
          // This allows video decode loop to continue until video emits
          if (first_frame_pts_us_ == 0)
          {
            // Log every 100 skips to show progress without spam
            audio_skip_count_++;
            if (audio_skip_count_ == 1 || audio_skip_count_ % 100 == 0)
            {
              std::cout << "[FileProducer] AUDIO_SKIP #" << audio_skip_count_
                        << " waiting for video epoch (audio_pts_us=" << base_pts_us << ")"
                        << std::endl;
            }
            av_frame_unref(audio_frame_);
            continue;  // Skip this audio frame, continue decoding
          }

          // Log when audio starts emitting after video epoch is set (one-shot)
          if (!audio_ungated_logged_)
          {
            std::cout << "[FileProducer] AUDIO_UNGATED first_audio_pts_us=" << base_pts_us
                      << " aligned_to_video_pts_us=" << first_frame_pts_us_ << std::endl;
            audio_ungated_logged_ = true;
          }

          // For FAKE clocks (tests only): clock-gate audio to maintain determinism
          if (master_clock_->is_fake())
          {
            int64_t frame_offset_us = output_audio_frame.pts_us - first_frame_pts_us_;
            int64_t target_utc_us = playback_start_utc_us_ + frame_offset_us;

            // Busy-wait for fake clock to advance (tests only)
            while (master_clock_->now_utc_us() < target_utc_us &&
                   !stop_requested_.load(std::memory_order_acquire))
            {
              std::this_thread::yield();
            }
          }
          // For REAL clocks: NO clock gating for audio - emit immediately
          // Buffer backpressure and downstream encoder will pace output
        }

        // Push to buffer with backpressure (block until space available)
        // Per-instance counters ensure accurate tracking per producer
        audio_frame_count_++;
        frames_since_producer_start_++;
        
        // Always log first 50 frames after producer start, then every 100
        bool should_log = (frames_since_producer_start_ <= 50) || (frames_since_producer_start_ % 100 == 0);

        // Phase 7: Check write barrier before pushing audio
        if (writes_disabled_.load(std::memory_order_acquire)) {
          return true;  // Silently drop - producer is being force-stopped
        }

        // Phase 6: Blocking push with backpressure - wait for space when buffer full
        bool pushed = false;
        int retry_count = 0;
        while (!pushed && !stop_requested_.load(std::memory_order_acquire))
        {
          if (output_buffer_.PushAudioFrame(output_audio_frame))
          {
            received_any = true;
            pushed = true;
            processed_one = true;  // Phase 6: Exit loop after this frame

            if (should_log)
            {
              std::cout << "[FileProducer] Pushed audio frame #" << audio_frame_count_
                        << " (frames_since_start=" << frames_since_producer_start_ << ")"
                        << ", base_pts_us=" << base_pts_us
                        << ", offset=" << pts_offset_us_
                        << ", final_pts_us=" << output_audio_frame.pts_us
                        << ", samples=" << output_audio_frame.nb_samples
                        << ", sample_rate=" << output_audio_frame.sample_rate
                        << (pts_adjusted ? " [PTS_ADJUSTED]" : "")
                        << (retry_count > 0 ? " [RETRIED=" + std::to_string(retry_count) + "]" : "")
                        << std::endl;
            }
          }
          else
          {
            // Buffer full - back off and retry (Phase 6 flow control)
            retry_count++;

            // CRITICAL: Don't retry forever! If buffer is consistently full,
            // give up after a reasonable number of retries to avoid deadlock.
            // The audio frame will be dropped, but this is better than blocking
            // video decode indefinitely.
            constexpr int kMaxAudioRetries = 50;
            if (retry_count > kMaxAudioRetries)
            {
              audio_drop_count_++;
              if (audio_drop_count_ <= 5 || audio_drop_count_ % 100 == 0)
              {
                std::cout << "[FileProducer] Audio frame dropped #" << audio_drop_count_
                          << " (buffer full after " << kMaxAudioRetries << " retries)"
                          << std::endl;
              }
              break;  // Give up on this frame, continue decoding
            }

            if (retry_count == 1 || retry_count % 100 == 0)
            {
              std::cout << "[FileProducer] Audio buffer full, backing off (retry #"
                        << retry_count << ")" << std::endl;
            }
            if (master_clock_ && !master_clock_->is_fake())
            {
              std::this_thread::sleep_for(std::chrono::microseconds(kProducerBackoffUs));
            }
            else
            {
              std::this_thread::yield();
            }
          }
        }
      }
      else
      {
        std::cerr << "[FileProducer] ===== FAILED TO CONVERT AUDIO FRAME =====" << std::endl;
        std::cerr << "[FileProducer] ConvertAudioFrame returned false" << std::endl;
      }

      av_frame_unref(audio_frame_);
    }

    return received_any;
  }

  bool FileProducer::ConvertAudioFrame(AVFrame* av_frame, buffer::AudioFrame& output_frame)
  {
    if (!av_frame || !audio_codec_ctx_)
    {
      return false;
    }

    // Get sample format and channel layout
    AVSampleFormat sample_fmt = static_cast<AVSampleFormat>(av_frame->format);
    int nb_channels = av_frame->ch_layout.nb_channels;
    int sample_rate = av_frame->sample_rate;
    int nb_samples = av_frame->nb_samples;

    if (nb_samples <= 0 || nb_channels <= 0 || sample_rate <= 0)
    {
      return false;
    }

    // Convert to interleaved S16 format (required by AudioFrame)
    // For now, we'll copy the data directly if it's already in the right format
    // In a full implementation, we'd use libswresample for format conversion

    // Calculate PTS in microseconds (producer-relative)
    // Use same approach as video: pts * time_base * 1,000,000
    int64_t pts_us = 0;
    if (av_frame->pts != AV_NOPTS_VALUE)
    {
      pts_us = static_cast<int64_t>(av_frame->pts * audio_time_base_ * kMicrosecondsPerSecond);
    }
    else
    {
      // Fallback: use best_effort_timestamp if pts is not set
      if (av_frame->best_effort_timestamp != AV_NOPTS_VALUE)
      {
        pts_us = static_cast<int64_t>(av_frame->best_effort_timestamp * audio_time_base_ * kMicrosecondsPerSecond);
      }
    }

    // For Phase 8.9, handle the common cases:
    // - AV_SAMPLE_FMT_S16 (interleaved)  → copy directly
    // - AV_SAMPLE_FMT_FLTP (planar float) → convert to S16 interleaved
    //
    // NOTE: EncoderPipeline currently expects S16 interleaved samples.
    
    // Calculate data size for S16 interleaved
    const size_t data_size = static_cast<size_t>(nb_samples) *
                             static_cast<size_t>(nb_channels) *
                             sizeof(int16_t);
    output_frame.data.resize(data_size);

    if (sample_fmt == AV_SAMPLE_FMT_S16)
    {
      // Already S16 interleaved - copy directly from data[0]
      std::memcpy(output_frame.data.data(), av_frame->data[0], data_size);
    }
    else if (sample_fmt == AV_SAMPLE_FMT_FLTP)
    {
      // Planar float [-1.0, 1.0] per channel in data[c][i] → S16 interleaved
      int16_t* dst = reinterpret_cast<int16_t*>(output_frame.data.data());

      for (int i = 0; i < nb_samples; ++i)
      {
        for (int c = 0; c < nb_channels; ++c)
        {
          const float* src_plane = reinterpret_cast<const float*>(av_frame->data[c]);
          float sample = src_plane[i];

          // Clamp to [-1.0, 1.0] and scale to int16 range
          if (sample < -1.0f) sample = -1.0f;
          if (sample >  1.0f) sample =  1.0f;
          const float scaled = sample * 32767.0f;
          const int16_t s16 = static_cast<int16_t>(std::lrintf(scaled));

          dst[i * nb_channels + c] = s16;
        }
      }
    }
    else
    {
      // Other formats would require a full SwrContext; keep Phase 8.9 simple.
      std::cerr << "[FileProducer] Audio format conversion not implemented for format: "
                << sample_fmt << std::endl;
      return false;
    }

    output_frame.sample_rate = sample_rate;
    output_frame.channels = nb_channels;
    output_frame.pts_us = pts_us;
    output_frame.nb_samples = nb_samples;

    return true;
  }

} // namespace retrovue::producers::file
