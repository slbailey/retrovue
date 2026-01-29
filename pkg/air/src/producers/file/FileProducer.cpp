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
      ProducerEventCallback event_callback)
      : config_(config),
        output_buffer_(output_buffer),
        master_clock_(clock),
        event_callback_(event_callback),
        state_(ProducerState::STOPPED),
        stop_requested_(false),
        teardown_requested_(false),
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
        stub_pts_counter_(0),
        frame_interval_us_(static_cast<int64_t>(std::round(kMicrosecondsPerSecond / config.target_fps))),
        next_stub_deadline_utc_(0),
        shadow_decode_mode_(false),
        shadow_decode_ready_(false),
        pts_offset_us_(0),
        aspect_policy_(runtime::AspectPolicy::Preserve),
        scale_width_(0),
        scale_height_(0),
        pad_x_(0),
        pad_y_(0)
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
    stop_requested_.store(true, std::memory_order_release);
    std::cout << "[FileProducer] Force stop requested" << std::endl;
    EmitEvent("force_stop", "");
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
      double src_aspect = static_cast<double>(src_width) / src_height;
      double dst_aspect = static_cast<double>(dst_width) / dst_height;
      
      if (src_aspect > dst_aspect) {
        // Source is wider: fit to width, pad height
        scale_width_ = dst_width;
        scale_height_ = static_cast<int>(dst_width / src_aspect);
        pad_x_ = 0;
        pad_y_ = (dst_height - scale_height_) / 2;
      } else {
        // Source is taller: fit to height, pad width
        scale_width_ = static_cast<int>(dst_height * src_aspect);
        scale_height_ = dst_height;
        pad_x_ = (dst_width - scale_width_) / 2;
        pad_y_ = 0;
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

    // Phase 8.2: no container seek. Decode from start; segment start enforced by frame admission in ProduceRealFrame.

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
    // Phase 8.2: frame admission — discard until presentation_time (media PTS) >= start_offset_ms
    const int64_t start_offset_us = static_cast<int64_t>(config_.start_offset_ms) * 1000;
    if (base_pts_us < start_offset_us)
    {
      return true;  // Discard frame; continue decoding
    }

    // Phase 8.6: no duration-based cutoff. Run until natural EOF (decoder returns no more frames).
    // segment_end_pts_us_ is not used to stop; asset duration may be logged but must not force stop.

    // Apply PTS offset for alignment
    int64_t frame_pts_us = base_pts_us + pts_offset_us_;
    output_frame.metadata.pts = frame_pts_us;
    last_decoded_frame_pts_us_ = frame_pts_us;
    last_pts_us_ = frame_pts_us;

    // Establish time mapping on first emitted frame
    if (first_frame_pts_us_ == 0)
    {
      first_frame_pts_us_ = frame_pts_us;
      if (master_clock_)
      {
        playback_start_utc_us_ = master_clock_->now_utc_us();
        // Synchronize clock epoch with actual playback start time.
        // This ensures ProgramOutput's scheduled_to_utc_us() returns correct deadlines
        // relative to when playback actually started, not when AIR started.
        // Note: We do NOT subtract first_frame_pts_us_ because that would make audio
        // (which starts at PTS=0) appear early relative to video. Instead, we accept
        // that video frames may arrive slightly early due to B-frame decoding delay,
        // which is fine - early is better than late for client buffering.
        master_clock_->set_epoch_utc_us(playback_start_utc_us_);
        std::cout << "[FileProducer] Clock epoch synchronized: playback_start="
                  << playback_start_utc_us_ << "us, first_frame_pts=" << first_frame_pts_us_
                  << "us, epoch=" << playback_start_utc_us_ << "us" << std::endl;
      }
    }

    // Check if in shadow decode mode
    bool shadow_mode = shadow_decode_mode_.load(std::memory_order_acquire);
    if (shadow_mode)
    {
      // Shadow mode: cache first frame, don't push to buffer
      std::lock_guard<std::mutex> lock(shadow_decode_mutex_);
      if (!cached_first_frame_)
      {
        cached_first_frame_ = std::make_unique<buffer::Frame>(output_frame);
        shadow_decode_ready_.store(true, std::memory_order_release);
        std::cout << "[FileProducer] Shadow decode: first frame cached, PTS=" 
                  << frame_pts_us << std::endl;
        // Emit ShadowDecodeReady event
        EmitEvent("ShadowDecodeReady", "");
      }
      // Don't push to buffer in shadow mode, but continue decoding
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

    // Attempt to push decoded frame
    if (output_buffer_.Push(output_frame))
    {
      frames_produced_.fetch_add(1, std::memory_order_relaxed);
      return true;
    }
    else
    {
      // Buffer is full, back off
      buffer_full_count_.fetch_add(1, std::memory_order_relaxed);
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
    static int fp_scale_diag_count = 0;
    if (++fp_scale_diag_count <= 5) {
      std::cout << "[FileProducer] SCALE_DIAG frame=" << fp_scale_diag_count
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
      std::memset(scaled_frame_->data[0], 0, 
                  config_.target_width * config_.target_height);
      std::memset(scaled_frame_->data[1], 128, 
                  (config_.target_width / 2) * (config_.target_height / 2));
      std::memset(scaled_frame_->data[2], 128, 
                  (config_.target_width / 2) * (config_.target_height / 2));

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
    if (fp_scale_diag_count <= 5) {
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
        // Emit ShadowDecodeReady event
        EmitEvent("ShadowDecodeReady", "");
      }
      // Don't push to buffer in shadow mode
      return;
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
    // Calculate offset needed to align next frame to target_pts
    // Note: last_pts_us_ is not atomic, but this is called from state machine which holds a lock
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
    std::cout << "[FileProducer] Aligned PTS: target=" << target_pts 
              << ", offset=" << pts_offset_us_ << std::endl;
  }

  // Phase 8.9: Receive audio frames that were already sent to the decoder
  // This does NOT read packets - packets are dispatched by ProduceRealFrame()
  bool FileProducer::ReceiveAudioFrames()
  {
    if (audio_stream_index_ < 0 || !audio_codec_ctx_ || !audio_frame_ || audio_eof_reached_)
    {
      return false;
    }

    bool received_any = false;

    // Receive all available decoded audio frames (non-blocking)
    while (!stop_requested_.load(std::memory_order_acquire))
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
        // Track base PTS before offset
        int64_t base_pts_us = output_audio_frame.pts_us;
        
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

        // Push to buffer (non-blocking - if full, skip)
        static int audio_frame_count = 0;
        static int frames_since_producer_start = 0;  // Track frames since last producer start
        audio_frame_count++;
        frames_since_producer_start++;
        
        // Reset counter when we detect a new producer (when last_audio_pts_us_ resets to 0)
        static int64_t last_seen_audio_pts = -1;
        if (last_audio_pts_us_ == 0 && last_seen_audio_pts > 0) {
          frames_since_producer_start = 1;  // This is frame #1 of new producer
          std::cout << "[FileProducer] Detected new producer start, resetting frame counter" << std::endl;
        }
        last_seen_audio_pts = last_audio_pts_us_;
        
        // Always log first 50 frames after producer start, then every 100
        bool should_log = (frames_since_producer_start <= 50) || (frames_since_producer_start % 100 == 0);
        
        if (output_buffer_.PushAudioFrame(output_audio_frame))
        {
          received_any = true;
          
          if (should_log) {
            std::cout << "[FileProducer] Pushed audio frame #" << audio_frame_count 
                      << " (frames_since_start=" << frames_since_producer_start << ")"
                      << ", base_pts_us=" << base_pts_us
                      << ", offset=" << pts_offset_us_
                      << ", final_pts_us=" << output_audio_frame.pts_us
                      << ", samples=" << output_audio_frame.nb_samples
                      << ", sample_rate=" << output_audio_frame.sample_rate
                      << (pts_adjusted ? " [PTS_ADJUSTED]" : "") << std::endl;
          }
        }
        else
        {
          std::cerr << "[FileProducer] ===== FAILED TO PUSH AUDIO FRAME =====" << std::endl;
          std::cerr << "[FileProducer] Frame #" << audio_frame_count 
                    << " (frames_since_start=" << frames_since_producer_start << ")"
                    << ", base_pts_us=" << base_pts_us
                    << ", offset=" << pts_offset_us_
                    << ", final_pts_us=" << output_audio_frame.pts_us
                    << ", samples=" << output_audio_frame.nb_samples
                    << ", sample_rate=" << output_audio_frame.sample_rate
                    << " (BUFFER FULL)" << std::endl;
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
