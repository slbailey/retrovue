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
#include <mutex>
#include <sstream>
#include <thread>
#include <unordered_map>
#include <unordered_set>

// FFmpeg headers are C; keep type unambiguous (::SwrContext everywhere).
extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/channel_layout.h>
#include <libavutil/imgutils.h>
#include <libavutil/mathematics.h>
#include <libavutil/opt.h>
#include <libavutil/rational.h>
#include <libavutil/samplefmt.h>
#include <libswresample/swresample.h>
#include <libswscale/swscale.h>
}

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/runtime/AspectPolicy.h"
#include "retrovue/timing/MasterClock.h"
#include "retrovue/timing/TimelineController.h"

#include <cstring>

namespace retrovue::producers::file
{

  namespace
  {
    constexpr int64_t kProducerBackoffUs = 10'000; // 10ms backoff when buffer is full
    constexpr int kMaxAudioFramesPerTick = 8;      // INV-AUDIO-DEBT: Cap frames drained per video tick
    constexpr int64_t kMicrosecondsPerSecond = 1'000'000;

    // INV-P10-AUDIO-VIDEO-GATE (P1-FP-001/002/003): video epoch time per producer for 100ms deadline
    std::unordered_map<void*, std::chrono::steady_clock::time_point> g_video_epoch_time;
    std::mutex g_video_epoch_mutex;
    std::unordered_set<void*> g_p10_av_gate_violation_logged;

    // ==========================================================================
    // INV-P10-SLOT-BASED-UNBLOCK: Block at capacity, unblock on one slot free
    // ==========================================================================
    // Slot-based flow control eliminates the sawtooth buffer pattern:
    //   - Block only when buffer is at capacity (not at high-water mark)
    //   - Unblock immediately when one slot frees (no low-water drain)
    //   - Producer and consumer flow in lockstep when buffer is full
    //
    // This replaces the previous hysteresis approach which caused:
    //   Fill to high-water → hard stop → drain to low-water → frantic refill
    // The new approach provides smooth, continuous flow.
    // ==========================================================================
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
        planned_frame_count_(-1),
        frames_delivered_(0),
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
        eof_signaled_(false),
        truncation_logged_(false),
        time_base_({0, 1}),
        last_mt_pts_us_(0),
        last_decoded_mt_pts_us_(0),
        first_mt_pts_us_(0),
        playback_start_utc_us_(0),
        segment_end_pts_us_(-1),
        audio_codec_ctx_(nullptr),
        audio_frame_(nullptr),
        audio_stream_index_(-1),
        audio_time_base_({0, 1}),
        audio_eof_reached_(false),
        last_audio_pts_us_(0),
        audio_swr_ctx_(nullptr),
        audio_swr_src_rate_(0),
        audio_swr_src_channels_(0),
        audio_swr_src_fmt_(-1),  // AV_SAMPLE_FMT_NONE = -1
        effective_seek_target_us_(0),
        stub_pts_counter_(0),
        frame_interval_us_(config.target_fps.FrameDurationUs()),
        next_stub_deadline_utc_(0),
        shadow_decode_mode_(false),
        shadow_decode_ready_(false),
        cached_frame_flushed_(false),
        pts_offset_us_(0),
        pts_aligned_(false),
        aspect_policy_(runtime::AspectPolicy::Preserve),
        scale_width_(0),
        scale_height_(0),
        pad_x_(0),
        pad_y_(0),
        video_frame_count_(0),
        video_discard_count_(0),
        seek_discard_logged_(false),
        audio_frame_count_(0),
        frames_since_producer_start_(0),
        audio_skip_count_(0),
        audio_drop_count_(0),
        audio_mapping_gate_drop_count_(0),
        audio_ungated_logged_(false),
        mapping_locked_this_iteration_(false),
        decode_gate_block_count_(0),
        decode_gate_blocked_(false),
        decode_probe_window_start_us_(0),
        decode_probe_window_frames_(0),
        decode_probe_last_rate_(0),
        decode_probe_in_seek_(false),
        decode_rate_violation_logged_(false)
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
    last_mt_pts_us_ = 0;
    last_decoded_mt_pts_us_ = 0;
    last_audio_pts_us_ = 0;
    first_mt_pts_us_ = 0;
    video_epoch_set_ = false;
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

    // P8-PLAN-001 INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001: Capture planning authority from Core at start
    planned_frame_count_ = config_.frame_count;
    frames_delivered_.store(0, std::memory_order_release);
    truncation_logged_ = false;
    eof_signaled_ = false;
    
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

  void FileProducer::RequestStop()
  {
    // Idempotent: safe to call multiple times (e.g. SwitchToLive path then watcher).
    if (stop_requested_.load(std::memory_order_acquire)) {
      return;
    }
    // Phase 7: Hard write barrier - disable writes BEFORE signaling stop
    // This prevents any in-flight frames from being pushed after this point
    writes_disabled_.store(true, std::memory_order_release);
    stop_requested_.store(true, std::memory_order_release);
    std::cout << "[FileProducer] Request stop (writes disabled)" << std::endl;
    EmitEvent("request_stop", "");
  }

  bool FileProducer::IsStopped() const
  {
    return !isRunning();
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

  // ==========================================================================
  // INV-P10-BACKPRESSURE-SYMMETRIC: Unified A/V gating
  // ==========================================================================

  bool FileProducer::CanPushAV() const
  {
    // Gate is closed if ANY of these conditions are true:
    // 1. Write barrier is set
    // 2. Video buffer is full
    // 3. Audio buffer is full
    // 4. Stop was requested
    if (writes_disabled_.load(std::memory_order_acquire)) {
      return false;
    }
    if (stop_requested_.load(std::memory_order_acquire)) {
      return false;
    }
    if (output_buffer_.IsFull()) {
      return false;
    }
    if (output_buffer_.IsAudioFull()) {
      return false;
    }
    return true;
  }

  bool FileProducer::WaitForAVPushReady()
  {
    static bool logged_backpressure = false;

    while (!CanPushAV()) {
      // Check termination conditions
      if (stop_requested_.load(std::memory_order_acquire)) {
        return false;
      }
      if (writes_disabled_.load(std::memory_order_acquire)) {
        return false;  // Write barrier set - caller should drop frame
      }

      // Log backpressure event (once per episode)
      if (!logged_backpressure) {
        buffer_full_count_.fetch_add(1, std::memory_order_relaxed);
        std::cout << "[FileProducer] INV-P10-BACKPRESSURE-SYMMETRIC: A/V gated together "
                  << "(video_full=" << output_buffer_.IsFull()
                  << ", audio_full=" << output_buffer_.IsAudioFull() << ")"
                  << std::endl;
        logged_backpressure = true;
      }

      // Yield and retry
      if (master_clock_ && !master_clock_->is_fake()) {
        std::this_thread::sleep_for(std::chrono::microseconds(kProducerBackoffUs));
      } else {
        std::this_thread::yield();
      }
    }

    logged_backpressure = false;  // Reset for next backpressure episode
    return true;
  }

  // ==========================================================================
  // RULE-P10-DECODE-GATE: Architectural rule for all producers
  // ==========================================================================
  //
  // DOCTRINE: "Slot-based flow control eliminates sawtooth stuttering."
  //
  // Flow control must be applied at the earliest admission point (decode/demux),
  // not at push/emit. Use SLOT-BASED gating (block at capacity, unblock on one
  // slot free) to maintain smooth producer-consumer flow:
  //
  // ✅ CORRECT: Slot-based gate
  //    WaitForDecodeReady()  ← blocks only when buffer is at capacity
  //      └── av_read_frame()        (resumes when one slot frees)
  //            ├── audio packet → decode → push
  //            └── video packet → decode → push
  //
  // ❌ WRONG: Hysteresis with low-water mark (causes sawtooth stutter)
  //    Fill to high-water → hard stop → drain to 2 frames → frantic refill
  //
  // ❌ WRONG: Gate at push level (causes A/V desync)
  //    Audio runs ahead while video is blocked
  //
  // Slot-based unblocking keeps producer and consumer in lockstep when full.
  // Future producers (Prevue, Weather, Emergency) inherit this for free.
  // ==========================================================================

  bool FileProducer::WaitForDecodeReady()
  {
    // INV-P10-SLOT-BASED-UNBLOCK: Block only at capacity, unblock on one slot free.
    // No hysteresis - this eliminates the sawtooth fill/drain pattern that causes
    // bursty delivery and stuttering.
    //
    // Previous behavior (hysteresis):
    //   Block at high-water (capacity - 5), wait until low-water (2 frames)
    //   → Sawtooth: fill → hard stop → drain to 2 → frantic refill → repeat
    //
    // New behavior (slot-based):
    //   Block at capacity, unblock when one slot frees
    //   → Smooth: decode one, push one, block only when truly full

    // Check termination conditions first
    if (stop_requested_.load(std::memory_order_acquire)) return false;
    if (writes_disabled_.load(std::memory_order_acquire)) return false;

    size_t video_capacity = output_buffer_.Capacity();
    size_t audio_capacity = output_buffer_.AudioCapacity();
    size_t video_depth = output_buffer_.Size();
    size_t audio_depth = output_buffer_.AudioSize();

    // Block only when EITHER buffer is at capacity
    bool video_at_capacity = video_depth >= video_capacity;
    bool audio_at_capacity = audio_depth >= audio_capacity;

    if (!video_at_capacity && !audio_at_capacity) {
      // At least one slot free in both buffers - decode immediately
      decode_gate_blocked_ = false;
      return true;
    }

    // At capacity - enter blocking state
    bool was_blocked = decode_gate_blocked_;
    decode_gate_blocked_ = true;

    if (!was_blocked) {
      decode_gate_block_count_++;
      // ==========================================================================
      // HYPOTHESIS TEST T1: Identify which buffer is causing the block
      // ==========================================================================
      // H1 predicts: audio_at_capacity=true, video_at_capacity=false
      // This log discriminates between audio-caused vs video-caused blocking.
      const char* block_cause = "UNKNOWN";
      if (audio_at_capacity && !video_at_capacity) {
        block_cause = "AUDIO_ONLY";
      } else if (video_at_capacity && !audio_at_capacity) {
        block_cause = "VIDEO_ONLY";
      } else if (audio_at_capacity && video_at_capacity) {
        block_cause = "BOTH";
      }
      std::cout << "[FileProducer] INV-P10-SLOT-GATE: Blocking at capacity "
                << "(video=" << video_depth << "/" << video_capacity
                << ", audio=" << audio_depth << "/" << audio_capacity
                << ", episode=" << decode_gate_block_count_
                << ", block_cause=" << block_cause << ")" << std::endl;

      // T4: Log audio/video depth ratio at block time
      if (video_capacity > 0) {
        // Report raw depth ratio without float division
        std::cout << "[FileProducer] HYPOTHESIS_TEST_T4: audio_depth=" << audio_depth
                  << " video_depth=" << video_depth
                  // av_ratio reported above
                  << " (H1 predicts: audio_full with video_low)" << std::endl;
      }
    }

    // Wait until ONE slot frees in the full buffer(s)
    // No low-water mark - resume immediately when space available
    while (true) {
      if (stop_requested_.load(std::memory_order_acquire)) return false;
      if (writes_disabled_.load(std::memory_order_acquire)) return false;

      video_depth = output_buffer_.Size();
      audio_depth = output_buffer_.AudioSize();

      // Resume when at least one slot is free in BOTH buffers
      bool video_has_slot = video_depth < video_capacity;
      bool audio_has_slot = audio_depth < audio_capacity;

      if (video_has_slot && audio_has_slot) {
        // Only log if we actually blocked for a significant time
        if (was_blocked) {
          // ==========================================================================
          // HYPOTHESIS TEST T1 (continued): Log which buffer was the bottleneck
          // ==========================================================================
          // At release time, identify which buffer drained first (the other was bottleneck)
          const char* bottleneck = "UNKNOWN";
          // If audio was at capacity when we started and video wasn't, audio was bottleneck
          if (audio_at_capacity && !video_at_capacity) {
            bottleneck = "AUDIO";
          } else if (video_at_capacity && !audio_at_capacity) {
            bottleneck = "VIDEO";
          } else {
            bottleneck = "BOTH";
          }
          std::cout << "[FileProducer] INV-P10-SLOT-GATE: Released "
                    << "(video=" << video_depth << "/" << video_capacity
                    << ", audio=" << audio_depth << "/" << audio_capacity
                    << ", bottleneck_was=" << bottleneck << ")" << std::endl;
        }
        decode_gate_blocked_ = false;
        return true;
      }

      if (master_clock_ && !master_clock_->is_fake()) {
        std::this_thread::sleep_for(std::chrono::microseconds(kProducerBackoffUs));
      } else {
        std::this_thread::yield();
      }
    }
  }

  // ==========================================================================
  // INV-P9-STEADY-003: Symmetric A/V backpressure
  // ==========================================================================
  // Audio MUST NOT run too far ahead of video. The constraint "1 frame duration"
  // (33ms at 30fps) maps to approximately 1.5 audio frames at 48kHz/1024 samples.
  // We allow audio to be up to 2 frames ahead to account for different frame rates.
  //
  // This is a FRAME COUNT constraint, not a PTS constraint. PTS-based throttling
  // would require knowing the next frame's PTS before decoding, which isn't possible.
  // ==========================================================================
  bool FileProducer::CanAudioAdvance() const
  {
    // INV-P9-STEADY-003: PTS-based symmetric throttling
    // Audio and video have different frame durations (video ~33ms, audio ~21ms).
    // Frame-count-based throttling causes PTS divergence because limiting audio
    // frames causes audio to fall behind video in PTS.
    //
    // For now, disable frame-count throttle and rely on buffer backpressure.
    // The ring buffer's audio capacity is 3x video capacity specifically to
    // accommodate the higher audio frame rate while maintaining flow.
    //
    // TODO: Implement true PTS-based throttling if needed.
    return true;
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

  std::optional<producers::AsRunFrameStats> FileProducer::GetAsRunFrameStats() const
  {
    producers::AsRunFrameStats stats;
    stats.asset_path = config_.asset_uri;
    stats.start_frame = config_.start_frame;
    stats.frames_emitted = GetFramesProduced();
    return stats;
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

    // INV-FPS-RESAMPLE: Initialize resampler for stub mode when stub_source_fps is set.
    // Rational target FPS for tick grid (no rounded interval).
    // Target FPS already initialized in constructor
    if (config_.stub_mode && config_.stub_source_fps > 0) {
      source_fps_r_ = retrovue::blockplan::DeriveRationalFPS(config_.stub_source_fps);
      resample_active_ = !target_fps_r_.MatchesWithinTolerance(source_fps_r_, kFpsMatchToleranceRatio);
      if (resample_active_) {
        // Override stub frame interval to source fps (decode at source rate)
        frame_interval_us_ = static_cast<int64_t>(
            source_fps_r_.FrameDurationUs());
        std::cout << "[FileProducer] INV-FPS-RESAMPLE (stub): Active"
                  << " source=" << source_fps_r_.num << "/" << source_fps_r_.den << "fps"
                  << " target=" << config_.target_fps.num << "/" << config_.target_fps.den << "fps"
                  << " stub_frame_interval=" << frame_interval_us_ << "us"
                  << " tick_duration=" << TickDurationUs() << "us"
                  << std::endl;
      }
    }

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

      // ==========================================================================
      // INV-P10-FRAME-INDEXED-EXECUTION: Check frame count completion
      // ==========================================================================
      // Segment completion is determined by frame count, not elapsed time or EOF.
      // If frame_count is set (>= 0), stop when we've produced that many frames.
      // If frame_count is -1, fall back to EOF-based completion (legacy behavior).
      // ==========================================================================
      if (config_.frame_count >= 0)
      {
        uint64_t produced = frames_produced_.load(std::memory_order_acquire);
        if (static_cast<int64_t>(produced) >= config_.frame_count)
        {
          if (!eof_event_emitted_)
          {
            eof_event_emitted_ = true;
            std::cout << "[FileProducer] Frame count reached (" << produced
                      << "/" << config_.frame_count << "); segment complete (INV-FRAME-001)" << std::endl;
            EmitEvent("segment_complete", "frame_count_reached");
          }
          // Wait for explicit stop (like EOF behavior in Phase 8.8)
          std::this_thread::sleep_for(std::chrono::milliseconds(10));
          continue;
        }
      }

      // P8-PLAN-003 INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001: Long content truncated at planned_frame_count
      const int64_t delivered = frames_delivered_.load(std::memory_order_acquire);
      if (planned_frame_count_ >= 0 && delivered >= planned_frame_count_)
      {
        if (!truncation_logged_)
        {
          truncation_logged_ = true;
          std::cout << "[FileProducer] CONTENT_TRUNCATED segment=" << config_.asset_uri
                    << " planned=" << planned_frame_count_
                    << " delivered=" << delivered
                    << " (truncating at boundary)" << std::endl;
        }
        if (!eof_event_emitted_)
        {
          eof_event_emitted_ = true;
          EmitEvent("segment_complete", "truncated_at_boundary");
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
        continue;
      }

      // Phase 8.6: When frame_count is not set (-1), segment end = natural EOF only.

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
          std::cout << "[FileProducer] Teardown timeout reached; requesting stop" << std::endl;
          EmitEvent("teardown_timeout", "");
          RequestStop();
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

          // =====================================================================
          // INV-SEGMENT-CONTENT-001 DIAGNOSTIC PROBE: EOF reached
          // =====================================================================
          // Log contract probe data to discriminate between:
          //   - INV-SEGMENT-CONTENT-001 violation (EOF before segment end)
          //   - Normal EOF at segment end
          //
          // If frame_count was specified and we produced fewer, this is a
          // potential content depth violation. If frame_count was not specified
          // (-1), this is just natural EOF which may or may not be a violation
          // depending on the scheduled slot duration (known only to Core).
          //
          // See: docs/contracts/semantics/PrimitiveInvariants.md
          // =====================================================================
          const uint64_t produced = frames_produced_.load(std::memory_order_acquire);
          std::cout << "[FileProducer] INV-SEGMENT-CONTENT-001 PROBE: "
                    << "eof=true, "
                    << "frames_produced=" << produced << ", "
                    << "configured_frame_count=" << config_.frame_count << ", "
                    << "decode_active=false, "
                    << "buffer_depth=" << output_buffer_.Size()
                    << std::endl;

          // Flag potential violation if frame_count was specified but not met
          if (config_.frame_count > 0 && static_cast<int64_t>(produced) < config_.frame_count) {
            std::cout << "[FileProducer] INV-SEGMENT-CONTENT-001 POTENTIAL VIOLATION: "
                      << "EOF before frame_count reached ("
                      << produced << "/" << config_.frame_count << ")"
                      << std::endl;
          }

          // P8-PLAN-002 INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001: Detect early EOF (content deficit)
          const int64_t delivered = frames_delivered_.load(std::memory_order_acquire);
          if (planned_frame_count_ >= 0 && delivered < planned_frame_count_) {
            const int64_t deficit = planned_frame_count_ - delivered;
            std::cout << "[FileProducer] EARLY_EOF segment=" << config_.asset_uri
                      << " planned=" << planned_frame_count_
                      << " delivered=" << delivered
                      << " deficit_frames=" << deficit << std::endl;
            EmitEvent("early_eof", "deficit_frames=" + std::to_string(deficit));
          }

          // P8-EOF-001 INV-P8-SEGMENT-EOF-DISTINCT-001: Signal decoder EOF to PlayoutEngine (idempotent)
          if (!eof_signaled_) {
            eof_signaled_ = true;
            const int64_t delivered_eof = frames_delivered_.load(std::memory_order_acquire);
            const int64_t ct_at_eof = timeline_controller_
                ? timeline_controller_->GetCTCursor()
                : 0;
            std::cout << "[FileProducer] DECODER_EOF segment=" << config_.asset_uri
                      << " ct=" << ct_at_eof
                      << " frames_delivered=" << delivered_eof
                      << " planned=" << planned_frame_count_ << std::endl;
            if (live_producer_eof_callback_) {
              live_producer_eof_callback_(config_.asset_uri, ct_at_eof, delivered_eof);
            }
          }
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
        time_base_ = stream->time_base;

        // INV-FPS-RESAMPLE: Detect source frame rate for PTS-driven resampling.
        // Use AVRational directly - never round-trip through double
        AVRational guessed_fps = av_guess_frame_rate(format_ctx_, stream, nullptr);
        retrovue::blockplan::RationalFps source_fps_r;
        if (guessed_fps.num > 0 && guessed_fps.den > 0) {
          source_fps_r = retrovue::blockplan::RationalFps(guessed_fps.num, guessed_fps.den);
          // source_fps_r will be used for logging directly
        } else {
          source_fps_r = config_.target_fps;
          // source_fps_r will be used for logging directly
        }

        // Activate when source and target differ by > 1%
        resample_active_ = !target_fps_r_.MatchesWithinTolerance(source_fps_r_, kFpsMatchToleranceRatio);
        if (resample_active_) {
          std::cout << "[FileProducer] INV-FPS-RESAMPLE: Active"
                    << " source=" << source_fps_r_.num << "/" << source_fps_r_.den << "fps"
                    << " target=" << target_fps_r_.num << "/" << target_fps_r_.den << "fps"
                    << " tick_duration=" << TickDurationUs() << "us"
                    << std::endl;
        }

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
        audio_time_base_ = stream->time_base;
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
      // Use Display Aspect Ratio (DAR) via integer cross-multiplication
      // Compare DAR to avoid float division: src_DAR vs dst_aspect
      // src_DAR = (src_width * sar.num) / (src_height * sar.den)
      // dst_aspect = dst_width / dst_height
      // Compare: src_width * sar.num * dst_height  vs  src_height * sar.den * dst_width
      
      AVRational sar = codec_ctx_->sample_aspect_ratio;
      int64_t src_dar_num, src_dar_den;
      if (sar.num > 0 && sar.den > 0) {
        src_dar_num = static_cast<int64_t>(src_width) * sar.num;
        src_dar_den = static_cast<int64_t>(src_height) * sar.den;
      } else {
        // No SAR: assume square pixels
        src_dar_num = src_width;
        src_dar_den = src_height;
      }
      
      // Cross-multiply to compare aspect ratios
      const int64_t src_cross = src_dar_num * dst_height;
      const int64_t dst_cross = src_dar_den * dst_width;

      // Calculate scaled dimensions using integer ratios (no float division)
      int calc_scale_width, calc_scale_height;
      if (src_cross > dst_cross) {
        // Source is wider: fit to width, pad height (letterbox)
        calc_scale_width = dst_width;
        calc_scale_height = static_cast<int>((static_cast<int64_t>(dst_width) * src_dar_den) / src_dar_num);
      } else {
        // Source is taller or equal: fit to height, pad width (pillarbox)
        calc_scale_width = static_cast<int>((static_cast<int64_t>(dst_height) * src_dar_num) / src_dar_den);
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

    // =========================================================================
    // INV-P10-SCALE: One-time scale pipeline configuration log
    // =========================================================================
    {
      AVRational sar = codec_ctx_->sample_aspect_ratio;
      std::cout << "[FileProducer] INV-P10-SCALE: src=" << src_width << "x" << src_height;
      if (sar.num > 0 && sar.den > 0) {
        std::cout << " SAR=" << sar.num << ":" << sar.den;
      }
      std::cout << " -> scale=" << scale_width_ << "x" << scale_height_
                << " pad=(" << pad_x_ << "," << pad_y_ << ")"
                << " -> target=" << dst_width << "x" << dst_height << std::endl;
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
    eof_signaled_ = false;
    truncation_logged_ = false;
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

    // INV-P10.5-HOUSE-AUDIO-FORMAT: Clean up audio resampler (::SwrContext*)
    if (audio_swr_ctx_)
    {
      ::SwrContext* ctx = audio_swr_ctx_;
      audio_swr_ctx_ = nullptr;
      swr_free(&ctx);
    }
    audio_swr_src_rate_ = 0;
    audio_swr_src_channels_ = 0;

    decoder_initialized_ = false;
    video_stream_index_ = -1;
    audio_stream_index_ = -1;
    eof_reached_ = false;
    audio_eof_reached_ = false;
    eof_event_emitted_ = false;
    eof_signaled_ = false;
    truncation_logged_ = false;
  }

  void FileProducer::SetLiveProducerEOFCallback(LiveProducerEOFCallback callback) {
    live_producer_eof_callback_ = std::move(callback);
  }

  bool FileProducer::ProduceRealFrame()
  {
    if (!decoder_initialized_)
    {
      return false;
    }

    // INV-P10-BACKPRESSURE-SYMMETRIC: Decode-level gate
    // Exception: Shadow mode bypasses for ONE frame (then waits via INV-P8-SHADOW-PACE)
    bool in_shadow = shadow_decode_mode_.load(std::memory_order_acquire);
    if (!in_shadow && !WaitForDecodeReady()) {
      return true;  // Stop or write barrier - continue loop to check termination
    }

    // INV-FPS-RESAMPLE: Check for pending frame repeats (one per call max)
    {
      buffer::Frame repeat_frame;
      int64_t repeat_pts = 0;
      if (ResamplePromotePending(repeat_frame, repeat_pts)) {
        // Single emit via EmitFrameAtTick — no duplicated epoch/pacing/push logic
        EmitFrameAtTick(repeat_frame, repeat_pts);
        return true;  // One repeat emitted; next call checks pending again
      }
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
      // HYPOTHESIS TEST T3: Track audio packet count
      audio_packets_processed_++;
      av_rate_probe_audio_count_++;

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

    // HYPOTHESIS TEST T3: Track video packet count
    video_packets_processed_++;
    av_rate_probe_video_count_++;

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
    video_frame_count_++;

    // ==========================================================================
    // HYPOTHESIS TEST T3: Periodic A/V packet rate logging
    // ==========================================================================
    // Log every 100 video frames to show audio/video packet ratio.
    // H1 predicts: audio_packets >> video_packets (typically 3-5x for 48kHz audio)
    if (video_frame_count_ % 100 == 0) {
      const int64_t now_us = master_clock_ ? master_clock_->now_utc_us()
          : std::chrono::duration_cast<std::chrono::microseconds>(
                std::chrono::steady_clock::now().time_since_epoch()).count();
      if (av_rate_probe_start_us_ == 0) {
        av_rate_probe_start_us_ = now_us;
      }
      const int64_t elapsed_us = now_us - av_rate_probe_start_us_;
      if (elapsed_us > 0) {
        // Report counts and ratio without float math
        std::cout << "[FileProducer] HYPOTHESIS_TEST_T3: "
                  << "audio_packets=" << audio_packets_processed_
                  << " video_packets=" << video_packets_processed_
                  << " audio_count=" << av_rate_probe_audio_count_
                  << " video_count=" << av_rate_probe_video_count_
                  << " window_us=" << elapsed_us
                  << " (H1 predicts: audio >> video)" << std::endl;
        // Detect imbalance: audio packets > 3x video packets (integer comparison)
        const bool imbalance_detected = (av_rate_probe_audio_count_ > av_rate_probe_video_count_ * 3);
        if (imbalance_detected && !av_rate_imbalance_logged_) {
          av_rate_imbalance_logged_ = true;
          std::cout << "[FileProducer] HYPOTHESIS_TEST_T3: AV_IMBALANCE_DETECTED "
                    << "(audio=" << av_rate_probe_audio_count_ << " > 3*video=" << av_rate_probe_video_count_ * 3 << ", consistent with H1)" << std::endl;
        }
      }
    }

    // Phase 8: Load shadow mode state early - needed for gating decisions
    bool in_shadow_mode = shadow_decode_mode_.load(std::memory_order_acquire);

    // =========================================================================
    // INV-SEEK-DISCARD: Keyframe seek discard phase
    // =========================================================================
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
      // INV-SEEK-DISCARD: Log once at start of discard phase
      if (!seek_discard_logged_)
      {
        seek_discard_logged_ = true;
        std::cout << "[FileProducer] INV-SEEK-DISCARD: Discarding to target_pts="
                  << (effective_seek_target_us_ / 1000) << "ms" << std::endl;
      }
      return true;  // Discard frame; continue decoding
    }

    // =========================================================================
    // INV-SEEK-DISCARD: Completion - log summary when first frame is emitted
    // =========================================================================
    if (phase6_gating_active && effective_seek_target_us_ > 0 && !video_epoch_set_)
    {
      int64_t accuracy_us = base_pts_us - effective_seek_target_us_;
      std::cout << "[FileProducer] INV-SEEK-DISCARD: Complete, discarded="
                << video_discard_count_ << " frames, accuracy="
                << (accuracy_us / 1000) << "ms (first_emitted=" << base_pts_us << "us)"
                << std::endl;

      std::ostringstream msg;
      msg << "target_pts=" << effective_seek_target_us_ << "us, first_emitted_pts=" << base_pts_us
          << "us, accuracy_ms=" << (accuracy_us / 1000);
      EmitEvent("first_frame_emitted", msg.str());
    }

    // Phase 8.6: no duration-based cutoff. Run until natural EOF (decoder returns no more frames).
    // segment_end_pts_us_ is not used to stop; asset duration may be logged but must not force stop.

    // =========================================================================
    // INV-P8-SHADOW-PACE: Shadow mode caches first frame, then waits IN PLACE
    // =========================================================================
    // This MUST happen BEFORE the AdmitFrame decision so that when shadow is
    // disabled, the frame can call AdmitFrame and be pushed to buffer.
    if (in_shadow_mode)
    {
      // Cache first frame if not already cached
      {
        std::lock_guard<std::mutex> lock(shadow_decode_mutex_);
        if (!cached_first_frame_)
        {
          cached_first_frame_ = std::make_unique<buffer::Frame>(output_frame);
          shadow_decode_ready_.store(true, std::memory_order_release);
          std::cout << "[FileProducer] Shadow decode: first frame cached, PTS="
                    << base_pts_us << std::endl;
          EmitEvent("ShadowDecodeReady", "");

          // ====================================================================
          // INV-P8-SHADOW-EPOCH: Establish video epoch from cached frame
          // ====================================================================
          // Set first_mt_pts_us_ when caching the first shadow frame so that:
          // 1. Audio can pass INV-P10-AUDIO-VIDEO-GATE during shadow preroll
          // 2. A/V sync is maintained from the switch point forward
          // Scoped to shadow mode only - live mode establishes epoch normally.
          // ====================================================================
          if (!video_epoch_set_) {
            first_mt_pts_us_ = base_pts_us;
            video_epoch_set_ = true;
            playback_start_utc_us_ = master_clock_ ? master_clock_->now_utc_us() : 0;
            {
              std::lock_guard<std::mutex> epoch_lock(g_video_epoch_mutex);
              g_video_epoch_time[this] = std::chrono::steady_clock::now();
            }
            std::cout << "[FileProducer] INV-P8-SHADOW-EPOCH: Epoch established from cached frame "
                      << "(first_mt_pts_us=" << first_mt_pts_us_ << ")" << std::endl;
          }
        }
      }

      // ==========================================================================
      // INV-P8-SHADOW-PREROLL: Continue demuxing during shadow wait
      // ==========================================================================
      // Shadow preroll ensures both audio AND video buffers are populated before
      // the switch deadline arrives. Without preroll, buffers would be empty at
      // switch time, triggering the safety rail.
      //
      // Behavior:
      // - Audio packets: decode and buffer (gated only until epoch exists)
      // - Video packets: decode and buffer (after first frame is cached)
      // - Continues until shadow mode disabled OR buffers full OR EOF
      // ==========================================================================
      uint64_t shadow_audio_buffered = 0;
      uint64_t shadow_video_buffered = 0;
      bool video_preroll_complete = false;  // INV-P8-SHADOW-PREROLL-STOP: Stop video decode when buffer full
      std::cout << "[FileProducer] INV-P8-SHADOW-PREROLL: Entering "
                << "(audio_depth=" << output_buffer_.AudioSize()
                << ", video_depth=" << output_buffer_.Size() << ")" << std::endl;

      // Continue demuxing until shadow is disabled or termination requested
      while (shadow_decode_mode_.load(std::memory_order_acquire) &&
             !stop_requested_.load(std::memory_order_acquire) &&
             !teardown_requested_.load(std::memory_order_acquire)) {

        // Check if BOTH buffers are full - if so, yield and retry
        if (output_buffer_.IsAudioFull() && output_buffer_.IsFull()) {
          std::this_thread::sleep_for(std::chrono::milliseconds(1));
          continue;
        }

        // Read next packet from demuxer
        int ret = av_read_frame(format_ctx_, packet_);

        if (ret == AVERROR_EOF) {
          // EOF during shadow preroll - stop demuxing, wait for switch
          if (shadow_audio_buffered > 0 || shadow_video_buffered > 0) {
            std::cout << "[FileProducer] INV-P8-SHADOW-PREROLL: EOF reached "
                      << "(audio_buffered=" << shadow_audio_buffered
                      << ", video_buffered=" << shadow_video_buffered << ")" << std::endl;
          }
          // Sleep until shadow disabled since we can't demux anymore
          while (shadow_decode_mode_.load(std::memory_order_acquire) &&
                 !stop_requested_.load(std::memory_order_acquire) &&
                 !teardown_requested_.load(std::memory_order_acquire)) {
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
          }
          break;
        }

        if (ret < 0) {
          av_packet_unref(packet_);
          std::this_thread::sleep_for(std::chrono::milliseconds(1));
          continue;  // Transient error, retry
        }

        // Dispatch packet based on stream type
        if (packet_->stream_index == audio_stream_index_ && audio_codec_ctx_ != nullptr) {
          // Audio packet: decode and buffer
          audio_packets_processed_++;
          ret = avcodec_send_packet(audio_codec_ctx_, packet_);
          av_packet_unref(packet_);
          if (ret >= 0 || ret == AVERROR(EAGAIN)) {
            ReceiveAudioFrames();
            shadow_audio_buffered++;
          }
        } else if (packet_->stream_index == video_stream_index_) {
          // =======================================================================
          // INV-P8-SHADOW-PREROLL: Video decode and buffer
          // =======================================================================
          // Decode video frames during shadow preroll so the buffer is populated
          // at switch time. First frame is already cached; subsequent frames fill
          // the buffer for seamless playback after the switch.
          //
          // INV-P8-SHADOW-PREROLL-STOP: Once video buffer is full, STOP decoding
          // video packets entirely. This prevents frame_ from advancing past the
          // buffered content, which would cause REJECTED_EARLY after the switch.
          // =======================================================================
          if (video_preroll_complete) {
            // Video buffer already full - discard packet without decoding
            // This prevents frame_ from advancing past buffered content
            av_packet_unref(packet_);
            continue;
          }

          video_packets_processed_++;
          ret = avcodec_send_packet(codec_ctx_, packet_);
          av_packet_unref(packet_);

          if (ret >= 0 || ret == AVERROR(EAGAIN)) {
            // Receive all available decoded frames from this packet
            while (true) {
              ret = avcodec_receive_frame(codec_ctx_, frame_);
              if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF) {
                break;  // Need more packets or done
              }
              if (ret < 0) {
                break;  // Decode error
              }

              // Scale and assemble the frame
              if (!ScaleFrame()) {
                continue;  // Skip frame on scale error
              }

              buffer::Frame output_frame;
              if (!AssembleFrame(output_frame)) {
                continue;  // Skip frame on assemble error
              }

              // Check video buffer capacity before push
              if (output_buffer_.IsFull()) {
                video_preroll_complete = true;  // INV-P8-SHADOW-PREROLL-STOP: Mark complete
                break;  // Buffer full, preroll complete for video
              }

              // Push to buffer (MT-based PTS, transformed at switch via TimelineController)
              if (output_buffer_.Push(output_frame)) {
                shadow_video_buffered++;
              }
            }
          }
        } else {
          // Other packet: discard
          av_packet_unref(packet_);
        }
      }

      // ==========================================================================
      // INV-P8-SHADOW-PREROLL: Log preroll completion
      // ==========================================================================
      const size_t audio_depth_at_exit = output_buffer_.AudioSize();
      const size_t video_depth_at_exit = output_buffer_.Size();
      std::cout << "[FileProducer] INV-P8-SHADOW-PREROLL: Complete "
                << "(audio_depth=" << audio_depth_at_exit
                << ", video_depth=" << video_depth_at_exit
                << ", audio_buffered=" << shadow_audio_buffered
                << ", video_buffered=" << shadow_video_buffered << ")" << std::endl;

      // INV-P8-SHADOW-FLUSH: Check if frame was already flushed by PlayoutEngine
      if (cached_frame_flushed_.load(std::memory_order_acquire)) {
        std::cout << "[FileProducer] Shadow disabled, frame already flushed by SwitchToLive - "
                  << "skipping to next frame" << std::endl;
        // Frame was already pushed by FlushCachedFrameToBuffer(), skip this frame
        return true;  // Return success to continue producing next frame
      }

      // =========================================================================
      // INV-P8-SHADOW-STALE-FRAME-DISCARD: Handle flush failure due to buffer full
      // =========================================================================
      // If we reach here, cached_frame_flushed_ is false, meaning FlushCachedFrameToBuffer
      // either wasn't called or failed. If the buffer is full, the flush failed because
      // there was no room for the cached frame (frame 624). In this case:
      //   - Buffer contains frames 625-684 (shadow preroll content)
      //   - frame_ holds the last decoded frame (684 or later)
      //   - The cached frame (624) is NOT in the buffer
      //
      // We must NOT process frame_ through AdmitFrame because:
      //   1. The segment mapping expects frames starting at the cached frame's MT
      //   2. frame_ is past the buffered content, would be REJECTED_EARLY
      //   3. This would cause buffer starvation and pad frame emission
      //
      // Solution: Discard frame_ and return. ProgramOutput will consume the buffered
      // frames (625-684). The missing cached frame (624) is a gap, but better than
      // total buffer starvation. The TimelineController will handle the MT discontinuity.
      // =========================================================================
      if (output_buffer_.IsFull()) {
        std::cout << "[FileProducer] INV-P8-SHADOW-STALE-FRAME-DISCARD: Buffer full after shadow exit, "
                  << "discarding stale frame_ (MT=" << base_pts_us << "us) to prevent REJECTED_EARLY cascade"
                  << std::endl;
        // Don't process frame_ - it's past the buffer content
        // Return true to continue producing (will decode fresh frames)
        return true;
      }

      // Shadow disabled - update local variable so this frame goes through AdmitFrame
      in_shadow_mode = false;
      std::cout << "[FileProducer] Shadow disabled, processing frame through AdmitFrame"
                << std::endl;
    }

    // Phase 8: Unified Timeline Authority
    // Three paths for PTS/CT assignment:
    // 1. Shadow mode: emit raw MT only (time-blind, no CT assignment)
    // 2. TimelineController available: use it for CT assignment
    // 3. Legacy (no TimelineController): use pts_offset_us_
    int64_t frame_pts_us;
    // Note: in_shadow_mode may have been updated above if shadow was disabled

    // Phase 8: CRITICAL - Check write barrier BEFORE touching TimelineController.
    // If write barrier is set, this producer is being phased out during a segment
    // transition. We must NOT call AdmitFrame() because that could lock the new
    // segment's mapping with the wrong MT (from the old producer).
    if (writes_disabled_.load(std::memory_order_acquire))
    {
      // INV-P8-WRITE-BARRIER-DIAG: Log when write barrier triggers.
      // This should ONLY happen for the OLD live producer during switch, never for preview.
      // If this fires for preview producer, it indicates a bug in switch orchestration.
      std::cout << "[FileProducer] INV-P8-WRITE-BARRIER: Frame dropped (writes_disabled), "
                << "MT=" << base_pts_us << "us, asset=" << config_.asset_uri << std::endl;
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
      // INV-P8-AUDIO-GATE Fix #2: Track if this AdmitFrame call locks the mapping.
      // If mapping was pending and becomes locked, we MUST ensure audio flows ungated.
      bool was_pending = timeline_controller_->IsMappingPending();

      int64_t assigned_ct_us = 0;
      timing::AdmissionResult result = timeline_controller_->AdmitFrame(base_pts_us, assigned_ct_us);

      switch (result)
      {
        case timing::AdmissionResult::ADMITTED:
          frame_pts_us = assigned_ct_us;
          output_frame.metadata.has_ct = true;  // Timeline-valid

          // INV-P8-AUDIO-GATE Fix #2: If mapping just locked, set flag to override audio gating.
          // This ensures audio for this iteration flows to buffer, not dropped.
          if (was_pending && !timeline_controller_->IsMappingPending()) {
            mapping_locked_this_iteration_ = true;
            std::cout << "[FileProducer] INV-P8-AUDIO-GATE: Mapping locked this iteration, "
                      << "audio will bypass gating" << std::endl;
          }
          break;

        case timing::AdmissionResult::REJECTED_LATE:
          // Frame is too late - drop it and continue decoding
          // One-shot diagnostic with full context for debugging MT coordinate issues
          {
            static bool late_logged_once = false;
            if (!late_logged_once) {
              late_logged_once = true;
              std::cerr << "[FileProducer] INV-P8-MT-MONOTONIC-WITHIN-SEGMENT: Frame REJECTED (late) - "
                        << "asset=" << config_.asset_uri
                        << ", producer=" << static_cast<const void*>(this)
                        << ", raw_pts=" << (frame_ ? frame_->pts : -1)
                        << ", time_base=" << time_base_.num << "/" << time_base_.den
                        << ", computed_mt_us=" << base_pts_us
                        << ", mt_start_us=" << timeline_controller_->GetSegmentMTStart()
                        << ", ct_cursor=" << timeline_controller_->GetCTCursor()
                        << std::endl;
            }
          }
          return true;  // Continue decoding next frame

        case timing::AdmissionResult::REJECTED_EARLY:
          // Frame is too early - this is unusual, log and drop
          // One-shot diagnostic
          {
            static bool early_logged_once = false;
            if (!early_logged_once) {
              early_logged_once = true;
              std::cerr << "[FileProducer] INV-P8-MT-MONOTONIC-WITHIN-SEGMENT: Frame REJECTED (early) - "
                        << "asset=" << config_.asset_uri
                        << ", producer=" << static_cast<const void*>(this)
                        << ", raw_pts=" << (frame_ ? frame_->pts : -1)
                        << ", time_base=" << time_base_.num << "/" << time_base_.den
                        << ", computed_mt_us=" << base_pts_us
                        << ", mt_start_us=" << timeline_controller_->GetSegmentMTStart()
                        << ", ct_cursor=" << timeline_controller_->GetCTCursor()
                        << std::endl;
            }
          }
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
    // CRITICAL: Store MT (base_pts_us), NOT CT (frame_pts_us)!
    // These variables are used in AssembleFrame's monotonicity check which operates in MT domain.
    // Storing CT here causes contamination: next frame's raw MT gets "corrected" to CT-based value.
    last_decoded_mt_pts_us_ = base_pts_us;  // MT, not CT!
    last_mt_pts_us_ = base_pts_us;  // MT, not CT!

    // INV-FPS-RESAMPLE: PTS-driven resampler gate
    {
      auto gate_result = ResampleGate(output_frame, base_pts_us);
      if (gate_result == ResampleGateResult::HOLD) {
        return true;  // Continue decoding
      }
      if (gate_result == ResampleGateResult::EMIT) {
        // Resampler selected a frame for this tick. Emit via the single
        // canonical emit path — no fallthrough to the non-resampled path.
        EmitFrameAtTick(output_frame, base_pts_us);
        return true;
      }
      // PASS: resampler inactive, fall through to existing emission path
    }

    // Establish time mapping on first emitted frame (VIDEO_EPOCH_SET)
    // CRITICAL: Use base_pts_us (MT), not frame_pts_us (CT)!
    // frame_pts_us may be CT if TimelineController mapped it.
    // Producer internal tracking must use MT to avoid double-mapping.
    if (!video_epoch_set_)
    {
      first_mt_pts_us_ = base_pts_us;  // MT, not CT!
      video_epoch_set_ = true;

      // Critical diagnostic: video epoch is now set, audio can start emitting
      // Log MT (base_pts_us), not CT (frame_pts_us) - this is what we store
      std::cout << "[FileProducer] VIDEO_EPOCH_SET first_mt_pts_us=" << base_pts_us
                << " (CT=" << frame_pts_us << ") target_us=" << effective_seek_target_us_ << std::endl;
      {
        std::lock_guard<std::mutex> lock(g_video_epoch_mutex);
        g_video_epoch_time[this] = std::chrono::steady_clock::now();
      }
      std::cout << "[FileProducer] INV-P10-AUDIO-VIDEO-GATE: Video epoch set, awaiting first audio (deadline=100ms)" << std::endl;

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
        // LEGACY PATH (no TimelineController) - epoch owned by PlayoutEngine.
        // Producers must never set epoch. PlayoutEngine establishes epoch at StartChannel.
        if (master_clock_)
        {
          playback_start_utc_us_ = master_clock_->now_utc_us();
          std::cout << "[FileProducer] Legacy path: epoch owned by PlayoutEngine (existing="
                    << master_clock_->get_epoch_utc_us() << "us)" << std::endl;
        }
      }
    }

    // INV-P10-AUDIO-VIDEO-GATE (P1-FP-003): Log violation once if 100ms elapsed without first audio
    if (video_epoch_set_ && !audio_ungated_logged_) {
      std::lock_guard<std::mutex> lock(g_video_epoch_mutex);
      auto it = g_video_epoch_time.find(this);
      if (it != g_video_epoch_time.end()) {
        int elapsed_ms = static_cast<int>(std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - it->second).count());
        if (elapsed_ms >= 100 && g_p10_av_gate_violation_logged.find(this) == g_p10_av_gate_violation_logged.end()) {
          g_p10_av_gate_violation_logged.insert(this);
          std::cout << "[FileProducer] INV-P10-AUDIO-VIDEO-GATE VIOLATION: No audio after "
                    << elapsed_ms << "ms (deadline=100ms), aq=0" << std::endl;
        }
      }
    }

    // INV-P8-SHADOW-PACE: Shadow handling now happens earlier (before AdmitFrame decision)
    // so that the cached frame goes through AdmitFrame when shadow is disabled.

    // Calculate target UTC time for this frame: playback_start + (frame_MT - first_frame_MT)
    // CRITICAL: Use base_pts_us (MT), NOT frame_pts_us (which may be CT after AdmitFrame)
    // Pacing offset must be in MT domain - it represents relative time within the media file.
    int64_t frame_offset_us = base_pts_us - first_mt_pts_us_;
    int64_t target_utc_us = playback_start_utc_us_ + frame_offset_us;

    // Frame decoded and ready to push

    // INV-AUDIO-DEBT: Tick-driven audio drain after video emission (non-resampled path).
    DrainAudioForTick(TickDurationUs());

    // INV-P8-AUDIO-GATE Fix #2: Clear the flag after audio has been processed.
    // The flag was set when AdmitFrame locked the mapping, and ensured audio
    // for this iteration bypassed gating. Now reset for next iteration.
    mapping_locked_this_iteration_ = false;

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

    // P8-PLAN-003 INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001: Do not deliver beyond planned_frame_count
    if (planned_frame_count_ >= 0 && frames_delivered_.load(std::memory_order_acquire) >= planned_frame_count_)
    {
      if (!truncation_logged_)
      {
        truncation_logged_ = true;
        std::cout << "[FileProducer] CONTENT_TRUNCATED segment=" << config_.asset_uri
                  << " planned=" << planned_frame_count_
                  << " delivered=" << frames_delivered_.load(std::memory_order_acquire)
                  << " (stopping at boundary)" << std::endl;
      }
      return true;  // No more frames from this segment; loop will hit truncation wait
    }

    // =======================================================================
    // INV-P10-ELASTIC-FLOW-CONTROL: Push with backpressure retry
    // =======================================================================
    // Elastic gating allows bounded decode-ahead, so push may occasionally fail
    // if buffer fills between gate check and push. Retry with backpressure.
    while (!output_buffer_.Push(output_frame))
    {
      if (stop_requested_.load(std::memory_order_acquire)) return true;
      if (writes_disabled_.load(std::memory_order_acquire)) return true;

      buffer_full_count_.fetch_add(1, std::memory_order_relaxed);

      if (master_clock_ && !master_clock_->is_fake()) {
        std::this_thread::sleep_for(std::chrono::microseconds(kProducerBackoffUs));
      } else {
        std::this_thread::yield();
      }
    }

    frames_produced_.fetch_add(1, std::memory_order_relaxed);
    frames_delivered_.fetch_add(1, std::memory_order_relaxed);

    // =========================================================================
    // INV-P9-STEADY-003: Video counter (kept for potential future use)
    // =========================================================================
    // Note: Frame-count-based throttling was removed because audio and video have
    // different frame durations (video ~33ms, audio ~21ms). Limiting audio frames
    // to match video frames caused audio to fall behind in PTS. The buffer's 3x
    // audio capacity naturally maintains PTS sync without explicit throttling.
    // =========================================================================
    steady_state_video_count_.fetch_add(1, std::memory_order_release);

    // =========================================================================
    // INV-DECODE-RATE-001 DIAGNOSTIC PROBE: Detect decode rate violations
    // =========================================================================
    // Measures decode rate to detect when producer falls behind real-time.
    // Violation: decode rate < target_fps during steady state (not seek/startup).
    //
    // NOTE: This probe only measures SUCCESSFUL frame production. If pacing
    // violation (INV-PACING-001) is active, decode rate may appear normal while
    // buffer still drains due to consumption outpacing production.
    //
    // See: docs/contracts/semantics/PrimitiveInvariants.md
    // =========================================================================
    {
      const int64_t now_us = master_clock_ ? master_clock_->now_utc_us()
                                           : std::chrono::duration_cast<std::chrono::microseconds>(
                                                 std::chrono::steady_clock::now().time_since_epoch()).count();

      // Initialize probe on first frame
      if (decode_probe_window_start_us_ == 0) {
        decode_probe_window_start_us_ = now_us;
        decode_probe_window_frames_ = 0;
      }

      // Track if we're in seek discard phase
      decode_probe_in_seek_ = (video_discard_count_ > 0 && !video_epoch_set_);

      decode_probe_window_frames_++;

      // Check 1-second window for rate measurement
      const int64_t window_elapsed_us = now_us - decode_probe_window_start_us_;
      if (window_elapsed_us >= kDecodeProbeWindowUs) {
        // Decode rate monitoring: use integer comparison to avoid float math
        // Rate check: observed_frames/window < target*0.9
        // Rearrange: observed_frames * 10 < target*window*9
        const int64_t observed_frames_x10 = decode_probe_window_frames_ * 10;
        const int64_t threshold_90 = (window_elapsed_us * target_fps_r_.num * 9) / (target_fps_r_.den * 1000000);
        
        // Only flag violation if NOT in seek phase and rate is below threshold
        const bool in_steady_state = !decode_probe_in_seek_ && video_epoch_set_;
        const bool is_violation = in_steady_state && (observed_frames_x10 < threshold_90);

        if (is_violation && !decode_rate_violation_logged_) {
          decode_rate_violation_logged_ = true;
          std::cout << "[FileProducer] INV-DECODE-RATE-001 VIOLATION DETECTED: "
                    << "frames=" << decode_probe_window_frames_
                    << ", window_us=" << window_elapsed_us
                    << ", target=" << target_fps_r_.num << "/" << target_fps_r_.den << "fps"
                    << ", frames_produced=" << frames_produced_.load()
                    << ", eof=" << (eof_reached_ ? "true" : "false")
                    << ", buffer_depth=" << output_buffer_.Size()
                    << std::endl;
        }

        // Log probe data only when approaching violation threshold (rate < 95% of target)
        const int64_t threshold_95 = (window_elapsed_us * target_fps_r_.num * 19) / (target_fps_r_.den * 1000000 * 20);
        const bool approaching_violation = in_steady_state && (decode_probe_window_frames_ < threshold_95);
        if (approaching_violation) {
          std::cout << "[FileProducer] INV-DECODE-RATE-001 PROBE: "
                    << "frames=" << decode_probe_window_frames_
                    << ", window_us=" << window_elapsed_us
                    << ", target=" << target_fps_r_.num << "/" << target_fps_r_.den << "fps, "
                    << "in_seek=" << (decode_probe_in_seek_ ? "true" : "false")
                    << ", steady_state=" << (in_steady_state ? "true" : "false")
                    << ", buffer_depth=" << output_buffer_.Size()
                    << std::endl;
        }

        // Reset window
        decode_probe_window_start_us_ = now_us;
        decode_probe_window_frames_ = 0;
      }
    }

    return true;
  }

  bool FileProducer::ScaleFrame()
  {
    if (!sws_ctx_ || !frame_ || !scaled_frame_)
    {
      return false;
    }

    // Check if padding needed (aspect preserve)
    bool needs_padding = (intermediate_frame_ != nullptr);

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

    // No pixel-level diagnostics here - per INV-P10-CONTENT-BLIND, pixel sampling
    // does not drive logic and is only useful for debugging specific decode issues.
    // Frame geometry is logged above; pixel content is the asset's responsibility.

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
    int64_t pts_us = (pts * time_base_.num * kMicrosecondsPerSecond) / time_base_.den;
    int64_t dts_us = (dts * time_base_.num * kMicrosecondsPerSecond) / time_base_.den;
    const int64_t raw_mt_pts_us = pts_us;  // Capture raw decoder MT before any correction

    // Ensure PTS monotonicity (operating in MT domain)
    // ASSERTION GUARD: last_mt_pts_us_ must be MT, not CT. CT values in a running channel
    // are much larger (seconds-to-hours in channel timeline). If last_mt_pts_us_ exceeds
    // a reasonable media duration bound, we have MT/CT contamination.
    constexpr int64_t kMaxReasonableMediaDurationUs = 4 * 3600 * 1000000LL;  // 4 hours
    if (last_mt_pts_us_ > kMaxReasonableMediaDurationUs)
    {
      std::cerr << "[FileProducer] BUG: last_mt_pts_us_=" << last_mt_pts_us_
                << "us exceeds max reasonable MT (" << kMaxReasonableMediaDurationUs
                << "us). This indicates MT/CT contamination!" << std::endl;
    }
    if (pts_us <= last_mt_pts_us_)
    {
      std::cout
        << "[MT_REPAIR_TRIGGERED]"
        << " asset=" << config_.asset_uri
        << " raw_pts=" << raw_mt_pts_us
        << " last_mt=" << last_mt_pts_us_
        << " repaired_to=" << (last_mt_pts_us_ + frame_interval_us_)
        << " frame_interval_us=" << frame_interval_us_
        << " source_fps=" << source_fps_r_.num << "/" << source_fps_r_.den
        << " target_fps=" << config_.target_fps.num << "/" << config_.target_fps.den
        << std::endl;
      pts_us = last_mt_pts_us_ + frame_interval_us_;
    }
    // First 10 frame MT deltas for Ricola (diagnostic for 60fps→30fps resample slope)
    if (config_.asset_uri.find("Ricola") != std::string::npos &&
        debug_mt_delta_count_ < 10)
    {
      std::cout
        << "[MT_DELTA]"
        << " asset=" << config_.asset_uri
        << " pts_us=" << pts_us
        << " delta=" << (pts_us - last_mt_pts_us_)
        << " source_fps=" << source_fps_r_.num << "/" << source_fps_r_.den
        << " target_fps=" << config_.target_fps.num << "/" << config_.target_fps.den
        << std::endl;
      debug_mt_delta_count_++;
    }
    // DOMAIN MIXING DETECTION: If raw decoder MT is small (<1s) but corrected pts_us
    // is large (>1s), we're mixing MT with CT. This catches the case where last_mt_pts_us_
    // was contaminated with CT.
    constexpr int64_t kSmallMT = 1000000LL;  // 1 second
    if (raw_mt_pts_us < kSmallMT && pts_us > kSmallMT * 10)
    {
      std::cerr << "[FileProducer] BUG: Domain mixing detected! raw_mt=" << raw_mt_pts_us
                << "us, corrected_pts=" << pts_us << "us, last_mt_pts_us_=" << last_mt_pts_us_
                << "us. CT was injected into MT state!" << std::endl;
    }
    last_mt_pts_us_ = pts_us;

    // Ensure DTS <= PTS
    if (dts_us > pts_us)
    {
      dts_us = pts_us;
    }

    output_frame.metadata.pts = pts_us;
    output_frame.metadata.dts = dts_us;
    output_frame.metadata.duration = target_fps_r_.FrameDurationSec();
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
    frame.metadata.duration = target_fps_r_.FrameDurationSec();
    frame.metadata.asset_uri = config_.asset_uri;

    // Update last_mt_pts_us_ for PTS tracking (use MT, not offset-adjusted PTS)
    last_mt_pts_us_ = base_pts;  // MT, not CT!

    // Generate YUV420 planar data (stub: all zeros for now)
    size_t frame_size = static_cast<size_t>(config_.target_width * config_.target_height * 3 / 2);
    frame.data.resize(frame_size, 0);

    // INV-FPS-RESAMPLE: Route stub frames through resampler gate.
    // At most one emission per ProduceStubFrame call — same contract as real mode.
    // If repeats need draining, the main loop calls us again next iteration.
    if (resample_active_) {
      // Check for pending repeat first (one per call max)
      buffer::Frame repeat_frame;
      int64_t repeat_pts = 0;
      if (ResamplePromotePending(repeat_frame, repeat_pts)) {
        // Emit single repeat via EmitFrameAtTick, skip decode this iteration
        EmitFrameAtTick(repeat_frame, repeat_pts);
        return;  // Next call checks pending again before decoding
      }

      int64_t base_pts = frame.metadata.pts;
      auto result = ResampleGate(frame, base_pts);
      if (result == ResampleGateResult::HOLD) {
        return;  // Frame absorbed, continue to next stub frame
      }
      // EMIT: emit via EmitFrameAtTick, then return (don't fall through to legacy push)
      EmitFrameAtTick(frame, base_pts);
      return;
    }

    // INV-P8-SHADOW-PACE: Shadow mode caches first frame, then waits IN PLACE
    bool in_shadow_mode = shadow_decode_mode_.load(std::memory_order_acquire);
    if (in_shadow_mode)
    {
      // Shadow mode: cache first frame
      {
        std::lock_guard<std::mutex> lock(shadow_decode_mutex_);
        if (!cached_first_frame_)
        {
          cached_first_frame_ = std::make_unique<buffer::Frame>(frame);
          shadow_decode_ready_.store(true, std::memory_order_release);
          std::cout << "[FileProducer] Shadow decode (stub): first frame cached, PTS="
                    << frame.metadata.pts << std::endl;
          EmitEvent("ShadowDecodeReady", "");
        }
      }

      // Wait IN PLACE until shadow is disabled
      // Also check teardown_requested_ to avoid hanging during StopChannel
      while (shadow_decode_mode_.load(std::memory_order_acquire) &&
             !stop_requested_.load(std::memory_order_acquire) &&
             !teardown_requested_.load(std::memory_order_acquire)) {
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
      }

      // INV-P8-SHADOW-FLUSH: Check if frame was already flushed
      if (cached_frame_flushed_.load(std::memory_order_acquire)) {
        std::cout << "[FileProducer] Shadow disabled (stub), frame already flushed" << std::endl;
        return;  // Frame was already pushed by FlushCachedFrameToBuffer
      }

      in_shadow_mode = false;
      std::cout << "[FileProducer] Shadow disabled (stub), processing frame" << std::endl;
    }

    // Phase 7: Check write barrier before pushing
    if (writes_disabled_.load(std::memory_order_acquire)) {
      return;  // Silently drop - producer is being force-stopped
    }

    // P8-PLAN-003: Do not deliver beyond planned_frame_count (stub path)
    if (planned_frame_count_ >= 0 && frames_delivered_.load(std::memory_order_acquire) >= planned_frame_count_) {
      if (!truncation_logged_) {
        truncation_logged_ = true;
        std::cout << "[FileProducer] CONTENT_TRUNCATED segment=" << config_.asset_uri
                  << " planned=" << planned_frame_count_
                  << " delivered=" << frames_delivered_.load(std::memory_order_acquire)
                  << " (stopping at boundary, stub)" << std::endl;
      }
      return;
    }

    // Normal mode: attempt to push decoded frame
    if (output_buffer_.Push(frame))
    {
      frames_produced_.fetch_add(1, std::memory_order_relaxed);
      frames_delivered_.fetch_add(1, std::memory_order_relaxed);
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
      // INV-P8-SHADOW-FLUSH: Do NOT reset cached_first_frame_ here.
      // It will be handled by FlushCachedFrameToBuffer() or the producer thread.
      // Just clear the ready flag.
      shadow_decode_ready_.store(false, std::memory_order_release);
    }
    else
    {
      // Entering shadow mode - reset ALL state
      std::lock_guard<std::mutex> lock(shadow_decode_mutex_);
      shadow_decode_ready_.store(false, std::memory_order_release);
      cached_first_frame_.reset();
      cached_frame_flushed_.store(false, std::memory_order_release);

      // =========================================================================
      // INV-P8-ZERO-FRAME-READY: When frame_count == 0, signal ready immediately
      // =========================================================================
      // A segment with frame_count=0 is a valid Core-computed scenario (e.g., grid
      // reconciliation rounds to 0 frames). The producer will never decode a frame
      // because the segment is "complete" before starting. Without this fix,
      // SwitchToLive would wait forever for IsShadowDecodeReady() which never fires.
      //
      // Fix: Signal ready immediately when there's nothing to cache. SwitchToLive
      // proceeds, buffer is empty, and safety rails (pad frames) activate.
      // This preserves the Output Liveness Invariant.
      // =========================================================================
      if (config_.frame_count == 0) {
        shadow_decode_ready_.store(true, std::memory_order_release);
        std::cout << "[FileProducer] INV-P8-ZERO-FRAME-READY: frame_count=0, "
                  << "signaling shadow_decode_ready=true immediately" << std::endl;
      }
    }
  }

  bool FileProducer::FlushCachedFrameToBuffer()
  {
    // INV-P8-SHADOW-FLUSH: Push cached shadow frame to buffer immediately.
    // This is called by PlayoutEngine after SetShadowDecodeMode(false) to ensure
    // the buffer has frames for readiness check without race condition.
    //
    // The frame goes through AdmitFrame for proper CT assignment (which locks
    // the segment mapping on first frame per INV-P8-SWITCH-002).

    std::lock_guard<std::mutex> lock(shadow_decode_mutex_);

    if (!cached_first_frame_) {
      // =========================================================================
      // INV-P8-ZERO-FRAME-READY: Vacuous flush success for zero-frame segments
      // =========================================================================
      // When frame_count=0, there's nothing to cache and nothing to flush.
      // Return true (vacuous success) to avoid triggering spurious violation logs.
      // This is expected behavior, not an error.
      // =========================================================================
      if (config_.frame_count == 0) {
        std::cout << "[FileProducer] INV-P8-ZERO-FRAME-READY: FlushCachedFrameToBuffer "
                  << "returns true (vacuous) for frame_count=0" << std::endl;
        return true;
      }
      std::cout << "[FileProducer] FlushCachedFrameToBuffer: no cached frame" << std::endl;
      return false;
    }

    buffer::Frame& frame = *cached_first_frame_;
    int64_t media_time_us = frame.metadata.pts;  // This is MT (raw media time from shadow)

    if (timeline_controller_) {
      int64_t ct_us = 0;
      auto result = timeline_controller_->AdmitFrame(media_time_us, ct_us);

      if (result == timing::AdmissionResult::ADMITTED) {
        frame.metadata.pts = ct_us;
        frame.metadata.has_ct = true;

        if (output_buffer_.Push(frame)) {
          frames_produced_.fetch_add(1, std::memory_order_relaxed);
          frames_delivered_.fetch_add(1, std::memory_order_relaxed);

          // CRITICAL: Set first_mt_pts_us_ to MT (not CT!) so the producer thread
          // knows the first frame was already processed and doesn't re-establish epoch.
          // This prevents MT/CT contamination on subsequent frames.
          if (!video_epoch_set_) {
            first_mt_pts_us_ = media_time_us;  // MT, not CT!
            video_epoch_set_ = true;
            std::cout << "[FileProducer] INV-P8-SHADOW-FLUSH: Set first_frame_pts_us=" << media_time_us
                      << "us (MT) to prevent epoch re-establishment" << std::endl;
          }

          std::cout << "[FileProducer] INV-P8-SHADOW-FLUSH: Cached frame flushed to buffer, "
                    << "MT=" << media_time_us << "us -> CT=" << ct_us << "us" << std::endl;
          cached_first_frame_.reset();
          cached_frame_flushed_.store(true, std::memory_order_release);
          return true;
        } else {
          // =========================================================================
          // INV-P8-SHADOW-FLUSH-BUFFER-FULL: Buffer full during flush
          // =========================================================================
          // The buffer filled during shadow preroll before flush was called.
          // This means frames 625+ are already in the buffer, but frame 624 (the
          // cached first frame) couldn't be inserted.
          //
          // We must handle this gracefully:
          // 1. Log a warning about the dropped frame
          // 2. Clear cached_first_frame_ to prevent orphan
          // 3. Set cached_frame_flushed_=true so producer thread discards frame_
          //    (which is past the buffered content and would cause REJECTED_EARLY)
          // 4. Return true to indicate switch can proceed (with 1 frame gap)
          //
          // The alternative (returning false) causes worse problems: the producer
          // thread would try to use frame_ which is far ahead, causing a cascade
          // of REJECTED_EARLY and eventual buffer starvation with pad frames.
          // =========================================================================
          std::cerr << "[FileProducer] INV-P8-SHADOW-FLUSH-BUFFER-FULL: Buffer full (depth="
                    << output_buffer_.Size() << "), cached frame MT=" << media_time_us
                    << "us dropped. Buffer contains subsequent frames; accepting 1-frame gap."
                    << std::endl;
          cached_first_frame_.reset();
          cached_frame_flushed_.store(true, std::memory_order_release);
          return true;  // Proceed with switch despite dropped frame
        }
      } else {
        std::cerr << "[FileProducer] WARNING: FlushCachedFrameToBuffer frame rejected by AdmitFrame: "
                  << static_cast<int>(result) << std::endl;
      }
    } else {
      // Legacy path: no TimelineController, just push with raw PTS
      if (output_buffer_.Push(frame)) {
        frames_produced_.fetch_add(1, std::memory_order_relaxed);
        frames_delivered_.fetch_add(1, std::memory_order_relaxed);

        // Set first_mt_pts_us_ for legacy path too
        if (!video_epoch_set_) {
          first_mt_pts_us_ = media_time_us;
          video_epoch_set_ = true;
        }

        std::cout << "[FileProducer] INV-P8-SHADOW-FLUSH: Cached frame flushed (legacy), PTS="
                  << media_time_us << "us" << std::endl;
        cached_first_frame_.reset();
        cached_frame_flushed_.store(true, std::memory_order_release);
        return true;
      }
    }

    return false;
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
    // This is last_mt_pts_us_ + frame_interval_us_ + pts_offset_us_
    // Note: last_mt_pts_us_ is not atomic, but we're reading it in a const method
    // In practice, this is called from the state machine which holds a lock
    int64_t next_pts = last_mt_pts_us_;
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
    int64_t next_pts_without_offset = last_mt_pts_us_;
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

  bool FileProducer::IsEOF() const
  {
    // Phase 8 (INV-P8-EOF-SWITCH): Returns true when the producer has exhausted
    // all frames from the source. Used to detect when live producer reaches EOF
    // so that switch-to-live can complete immediately (bypass buffer depth checks).
    return eof_reached_;
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
    int frames_this_call = 0;
    constexpr int kMaxOpportunisticFrames = 2;  // INV-AUDIO-DEBT: Bounded opportunistic drain

    // Receive decoded audio frames — bounded opportunistic drain.
    // Primary throughput is handled by DrainAudioForTick (tick-driven debt model).
    // This function provides bounded opportunistic drain from inline packet dispatch.
    while (!stop_requested_.load(std::memory_order_acquire) && frames_this_call < kMaxOpportunisticFrames)
    {
      // INV-P9-STEADY-003: Check audio buffer capacity BEFORE receiving
      // If audio buffer is full, return immediately and let the outer decode
      // loop iterate. WaitForDecodeReady() will block until space is available.
      // This prevents spin-waiting inside this function.
      if (output_buffer_.IsAudioFull()) {
        // Audio buffer at capacity - exit and let WaitForDecodeReady gate
        return received_any;
      }

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

        // =======================================================================
        // INV-P10-AUDIO-SAMPLE-CLOCK: Audio CT driven by sample duration
        // =======================================================================
        // Audio time is SIMPLE:
        //   1. TimelineController sets origin CT (first frame only)
        //   2. Producer advances CT by sample_duration each frame
        //   3. That's it. No adjustments. No nudging. No repairs.
        //
        // Sample durations:
        //   48kHz, 1024 samples → 21333µs
        //   44.1kHz, 1024 samples → 23219µs
        //
        // WHY NO ADJUSTMENTS:
        //   - Audio clock is inherently monotonic (sample counter)
        //   - Sample duration defines cadence, not frame-by-frame fixups
        //   - Video jitter does NOT affect audio slope
        //   - PCR (audio-master) must free-run continuously
        //   - Any +1µs nudging or equality clamping freezes PCR
        //
        // This is how real broadcast chains work.
        // =======================================================================
        if (timeline_controller_ && !shadow_decode_mode_.load(std::memory_order_acquire))
        {
          // Calculate sample duration in microseconds
          int64_t sample_duration_us = (static_cast<int64_t>(output_audio_frame.nb_samples) * 1000000LL)
                                       / output_audio_frame.sample_rate;

          if (last_audio_pts_us_ == 0) {
            // FIRST audio frame: use AdmitFrame to get CT origin
            int64_t audio_ct_us = 0;
            timing::AdmissionResult result = timeline_controller_->AdmitFrame(base_pts_us, audio_ct_us);

            if (result == timing::AdmissionResult::ADMITTED) {
              output_audio_frame.pts_us = audio_ct_us;
              std::cout << "[FileProducer] INV-P10-AUDIO-SAMPLE-CLOCK: Origin CT=" << audio_ct_us
                        << "us, sample_duration=" << sample_duration_us << "us" << std::endl;
            } else {
              // Audio rejected (late/early/no mapping) - skip this frame
              av_frame_unref(audio_frame_);
              continue;
            }
          } else {
            // SUBSEQUENT frames: advance CT by sample duration (sample clock)
            // This is the ONLY rule. No adjustments. No nudging.
            output_audio_frame.pts_us = last_audio_pts_us_ + sample_duration_us;
          }

          // Monotonicity guard: ONLY if time goes backwards (should never happen)
          // ⚠️ No +1µs nudge - just hold at last value
          // ⚠️ No equality clamp - equal is fine
          if (output_audio_frame.pts_us < last_audio_pts_us_) {
            output_audio_frame.pts_us = last_audio_pts_us_;
          }
        }
        else
        {
          // Legacy path: Apply PTS offset for alignment
          output_audio_frame.pts_us += pts_offset_us_;

          // Legacy monotonicity guard (same rules)
          if (output_audio_frame.pts_us < last_audio_pts_us_) {
            output_audio_frame.pts_us = last_audio_pts_us_;
          }
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
          if (!video_epoch_set_)
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
                      << " aligned_to_video_pts_us=" << first_mt_pts_us_ << std::endl;
            {
              std::lock_guard<std::mutex> lock(g_video_epoch_mutex);
              auto it = g_video_epoch_time.find(this);
              if (it != g_video_epoch_time.end()) {
                int elapsed_ms = static_cast<int>(std::chrono::duration_cast<std::chrono::milliseconds>(
                    std::chrono::steady_clock::now() - it->second).count());
                if (elapsed_ms <= 100) {
                  std::cout << "[FileProducer] INV-P10-AUDIO-VIDEO-GATE: First audio queued at "
                            << elapsed_ms << "ms after video epoch" << std::endl;
                }
              }
            }
            audio_ungated_logged_ = true;
          }

          // For FAKE clocks (tests only): clock-gate audio to maintain determinism
          if (master_clock_->is_fake())
          {
            // Use base_pts_us (MT), NOT output_audio_frame.pts_us (has offset/CT mapping)
            int64_t frame_offset_us = base_pts_us - first_mt_pts_us_;
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

        // =======================================================================
        // INV-P8-SHADOW-AUDIO-GATE: Gate audio until video epoch exists
        // =======================================================================
        // Audio must NOT advance ahead of video during shadow mode. However, once
        // the video epoch is established (video_epoch_set_), audio is aligned
        // to the video timeline and can safely buffer during shadow preroll.
        //
        // Gate conditions:
        // - Shadow mode active AND no video epoch → GATE (drop audio)
        // - Shadow mode active AND video epoch exists → ALLOW (preroll buffering)
        // - Shadow mode disabled → ALLOW (normal operation)
        // - Mapping just locked this iteration → ALLOW (bypass for live startup)
        //
        // This enables INV-P8-SHADOW-PREROLL to populate both audio and video
        // buffers before the switch deadline.
        // =======================================================================
        bool audio_should_be_gated = shadow_decode_mode_.load(std::memory_order_acquire)
                                     && (!video_epoch_set_);  // Only gate if no video epoch
        if (mapping_locked_this_iteration_) {
          audio_should_be_gated = false;  // Override: mapping just locked, audio must flow
        }
        if (audio_should_be_gated) {
          audio_mapping_gate_drop_count_++;
          if (audio_mapping_gate_drop_count_ <= 5 || audio_mapping_gate_drop_count_ % 100 == 0) {
            std::cout << "[FileProducer] AUDIO_GATED #" << audio_mapping_gate_drop_count_
                      << " - shadow mode active AND no video epoch (waiting for first video frame)"
                      << std::endl;
          }
          av_frame_unref(audio_frame_);
          continue;  // Drop this audio frame, continue decoding
        }

        // Push to buffer with backpressure (block until space available)
        // Per-instance counters ensure accurate tracking per producer
        audio_frame_count_++;
        frames_since_producer_start_++;

        // =======================================================================
        // INV-P10-ELASTIC-FLOW-CONTROL: Push with backpressure retry
        // P11A-002: INV-AUDIO-SAMPLE-CONTINUITY-001 observability
        // =======================================================================
        // Elastic gating allows bounded decode-ahead, so push may occasionally fail
        // if buffer fills between gate check and push. Retry with backpressure.
        static thread_local bool audio_backpressure_logged = false;
        while (!output_buffer_.PushAudioFrame(output_audio_frame))
        {
          if (!audio_backpressure_logged) {
            std::cout << "[FileProducer] Audio backpressure: blocking at queue capacity" << std::endl;  // P11A-002/003
            audio_backpressure_logged = true;
          }
          if (stop_requested_.load(std::memory_order_acquire)) {
            av_frame_unref(audio_frame_);
            return received_any;
          }
          if (writes_disabled_.load(std::memory_order_acquire)) {
            av_frame_unref(audio_frame_);
            return received_any;
          }

          if (master_clock_ && !master_clock_->is_fake()) {
            std::this_thread::sleep_for(std::chrono::microseconds(kProducerBackoffUs));
          } else {
            std::this_thread::yield();
          }
        }
        if (audio_backpressure_logged) {
          std::cout << "[FileProducer] Audio backpressure: released" << std::endl;  // P11A-002/003
          audio_backpressure_logged = false;
        }

        // =====================================================================
        // INV-P9-STEADY-003: Increment audio counter after successful push
        // =====================================================================
        steady_state_audio_count_.fetch_add(1, std::memory_order_release);

        received_any = true;
        frames_this_call++;
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

    // Get source format info
    AVSampleFormat src_fmt = static_cast<AVSampleFormat>(av_frame->format);
    int src_channels = av_frame->ch_layout.nb_channels;
    int src_rate = av_frame->sample_rate;
    int src_samples = av_frame->nb_samples;

    if (src_samples <= 0 || src_channels <= 0 || src_rate <= 0)
    {
      return false;
    }

    // =========================================================================
    // INV-P10.5-HOUSE-AUDIO-FORMAT: Always resample to house format
    // =========================================================================
    // All audio MUST be converted to house format (48kHz, 2ch, S16) before output.
    // EncoderPipeline never negotiates format - it assumes correctness.
    // This prevents AUDIO_FORMAT_CHANGE errors after TS header is written.
    // =========================================================================
    constexpr int dst_rate = buffer::kHouseAudioSampleRate;     // 48000
    constexpr int dst_channels = buffer::kHouseAudioChannels;   // 2
    constexpr AVSampleFormat dst_fmt = AV_SAMPLE_FMT_S16;       // Interleaved S16

    // Calculate PTS in microseconds (producer-relative)
    int64_t pts_us = 0;
    if (av_frame->pts != AV_NOPTS_VALUE)
    {
      pts_us = (av_frame->pts * audio_time_base_.num * kMicrosecondsPerSecond) / audio_time_base_.den;
    }
    else if (av_frame->best_effort_timestamp != AV_NOPTS_VALUE)
    {
      pts_us = (av_frame->best_effort_timestamp * audio_time_base_.num * kMicrosecondsPerSecond) / audio_time_base_.den;
    }

    // Check if we need to create/recreate the resampler
    // Must also recreate if source FORMAT changes (not just rate/channels)
    // FFmpeg decoders typically output FLTP (planar float), not S16!
    bool need_new_swr = (audio_swr_ctx_ == nullptr) ||
                        (audio_swr_src_rate_ != src_rate) ||
                        (audio_swr_src_channels_ != src_channels) ||
                        (audio_swr_src_fmt_ != static_cast<int>(src_fmt));

    if (need_new_swr)
    {
      // Log format change (only when actually changing, not on first frame)
      if (audio_swr_ctx_ != nullptr)
      {
        std::cout << "[FileProducer] INV-P10.5-HOUSE-AUDIO: Source format changed from "
                  << audio_swr_src_rate_ << "Hz/" << audio_swr_src_channels_ << "ch/"
                  << av_get_sample_fmt_name(static_cast<AVSampleFormat>(audio_swr_src_fmt_)) << " to "
                  << src_rate << "Hz/" << src_channels << "ch/"
                  << av_get_sample_fmt_name(src_fmt) << " (resampling to house format)"
                  << std::endl;
        ::SwrContext* old_ctx = audio_swr_ctx_;
        audio_swr_ctx_ = nullptr;
        swr_free(&old_ctx);
      }
      else
      {
        std::cout << "[FileProducer] INV-P10.5-HOUSE-AUDIO: Initializing resampler "
                  << src_rate << "Hz/" << src_channels << "ch/"
                  << av_get_sample_fmt_name(src_fmt) << " -> "
                  << dst_rate << "Hz/" << dst_channels << "ch/s16" << std::endl;
      }

      // Create resampler with newer API; pointer type explicit (::SwrContext*)
      AVChannelLayout src_layout;
      av_channel_layout_default(&src_layout, src_channels);
      AVChannelLayout dst_layout;
      av_channel_layout_default(&dst_layout, dst_channels);

      // CRITICAL: Use ACTUAL source format (src_fmt), not hardcoded S16!
      // Most decoders output FLTP (planar float). Mismatched format = static noise.
      ::SwrContext* new_ctx = nullptr;
      int ret = swr_alloc_set_opts2(&new_ctx,
                                    &dst_layout, AV_SAMPLE_FMT_S16, dst_rate,
                                    &src_layout, src_fmt, src_rate,
                                    0, nullptr);
      av_channel_layout_uninit(&src_layout);
      av_channel_layout_uninit(&dst_layout);

      if (ret < 0 || !new_ctx)
      {
        char errbuf[AV_ERROR_MAX_STRING_SIZE];
        if (ret < 0) av_strerror(ret, errbuf, sizeof(errbuf));
        else std::snprintf(errbuf, sizeof(errbuf), "swr_alloc_set_opts2 returned null");
        std::cerr << "[FileProducer] Failed to allocate SwrContext: " << errbuf << std::endl;
        return false;
      }

      ret = swr_init(new_ctx);
      if (ret < 0)
      {
        char errbuf[AV_ERROR_MAX_STRING_SIZE];
        av_strerror(ret, errbuf, sizeof(errbuf));
        std::cerr << "[FileProducer] Failed to init SwrContext: " << errbuf << std::endl;
        swr_free(&new_ctx);
        return false;
      }

      audio_swr_ctx_ = new_ctx;
      audio_swr_src_rate_ = src_rate;
      audio_swr_src_channels_ = src_channels;
      audio_swr_src_fmt_ = static_cast<int>(src_fmt);
    }

    // Calculate output sample count after resampling
    int64_t delay = swr_get_delay(audio_swr_ctx_, src_rate);
    int dst_samples = static_cast<int>(av_rescale_rnd(
        delay + src_samples, dst_rate, src_rate, AV_ROUND_UP));

    // Allocate output buffer
    const size_t data_size = static_cast<size_t>(dst_samples) *
                             static_cast<size_t>(dst_channels) *
                             sizeof(int16_t);
    output_frame.data.resize(data_size);

    // Perform resampling (swr_convert expects const uint8_t ** for input)
    uint8_t* out_ptr = output_frame.data.data();
    const uint8_t** in_planes = const_cast<const uint8_t**>(av_frame->extended_data);

    int samples_out = swr_convert(audio_swr_ctx_,
                                   &out_ptr, dst_samples,
                                   in_planes, src_samples);

    if (samples_out < 0)
    {
      char errbuf[AV_ERROR_MAX_STRING_SIZE];
      av_strerror(samples_out, errbuf, sizeof(errbuf));
      std::cerr << "[FileProducer] swr_convert failed: " << errbuf << std::endl;
      return false;
    }

    // Resize output to actual sample count
    const size_t actual_size = static_cast<size_t>(samples_out) *
                               static_cast<size_t>(dst_channels) *
                               sizeof(int16_t);
    output_frame.data.resize(actual_size);

    // Output is ALWAYS in house format
    output_frame.sample_rate = dst_rate;
    output_frame.channels = dst_channels;
    output_frame.pts_us = pts_us;
    output_frame.nb_samples = samples_out;

    return true;
  }

  // ======================================================================
  // ======================================================================
  // INV-AUDIO-DEBT: ReceiveOneAudioFrameAndPush — decode and push exactly one
  // audio frame from the decoder queue. Reports pushed duration for debt tracking.
  // Returns true if a frame was successfully pushed (pushed_duration_us set).
  // Returns false on EAGAIN/EOF/error/buffer-full/stop/write-barrier.
  // ======================================================================
  bool FileProducer::ReceiveOneAudioFrameAndPush(int64_t& pushed_duration_us)
  {
    pushed_duration_us = 0;

    if (audio_stream_index_ < 0 || !audio_codec_ctx_ || !audio_frame_ || audio_eof_reached_)
      return false;

    if (stop_requested_.load(std::memory_order_acquire))
      return false;

    if (output_buffer_.IsAudioFull())
      return false;

    int ret = avcodec_receive_frame(audio_codec_ctx_, audio_frame_);
    if (ret == AVERROR(EAGAIN))
      return false;
    if (ret == AVERROR_EOF) {
      audio_eof_reached_ = true;
      return false;
    }
    if (ret < 0)
      return false;

    buffer::AudioFrame output_audio_frame;
    if (!ConvertAudioFrame(audio_frame_, output_audio_frame)) {
      std::cerr << "[FileProducer] ===== FAILED TO CONVERT AUDIO FRAME =====" << std::endl;
      av_frame_unref(audio_frame_);
      return false;
    }

    // Write barrier check
    if (writes_disabled_.load(std::memory_order_acquire)) {
      av_frame_unref(audio_frame_);
      return false;
    }

    int64_t base_pts_us = output_audio_frame.pts_us;

    // Phase 6 gating (seek discard)
    bool audio_shadow_mode = shadow_decode_mode_.load(std::memory_order_acquire);
    bool audio_mapping_pending = timeline_controller_ && timeline_controller_->IsMappingPending();
    bool audio_phase6_gating_active = !timeline_controller_ || audio_shadow_mode || audio_mapping_pending;

    if (audio_phase6_gating_active && base_pts_us < effective_seek_target_us_) {
      av_frame_unref(audio_frame_);
      return false;  // Pre-seek frame, don't count as pushed
    }

    // First audio frame accuracy log
    if (audio_phase6_gating_active && effective_seek_target_us_ > 0 && last_audio_pts_us_ == 0) {
      int64_t accuracy_us = base_pts_us - effective_seek_target_us_;
      std::cout << "[FileProducer] Phase 6: First audio frame - target_pts=" << effective_seek_target_us_
                << "us, first_emitted_pts=" << base_pts_us
                << "us, accuracy=" << accuracy_us << "us ("
                << (accuracy_us / 1000) << "ms)" << std::endl;
    }

    // INV-P10-AUDIO-SAMPLE-CLOCK: CT assignment
    int64_t sample_duration_us = 0;
    if (timeline_controller_ && !shadow_decode_mode_.load(std::memory_order_acquire)) {
      sample_duration_us = (static_cast<int64_t>(output_audio_frame.nb_samples) * 1000000LL)
                           / output_audio_frame.sample_rate;
      if (last_audio_pts_us_ == 0) {
        int64_t audio_ct_us = 0;
        timing::AdmissionResult result = timeline_controller_->AdmitFrame(base_pts_us, audio_ct_us);
        if (result == timing::AdmissionResult::ADMITTED) {
          output_audio_frame.pts_us = audio_ct_us;
          std::cout << "[FileProducer] INV-P10-AUDIO-SAMPLE-CLOCK: Origin CT=" << audio_ct_us
                    << "us, sample_duration=" << sample_duration_us << "us" << std::endl;
        } else {
          av_frame_unref(audio_frame_);
          return false;
        }
      } else {
        output_audio_frame.pts_us = last_audio_pts_us_ + sample_duration_us;
      }
      if (output_audio_frame.pts_us < last_audio_pts_us_)
        output_audio_frame.pts_us = last_audio_pts_us_;
    } else {
      // Legacy path
      sample_duration_us = (static_cast<int64_t>(output_audio_frame.nb_samples) * 1000000LL)
                           / output_audio_frame.sample_rate;
      output_audio_frame.pts_us += pts_offset_us_;
      if (output_audio_frame.pts_us < last_audio_pts_us_)
        output_audio_frame.pts_us = last_audio_pts_us_;
    }
    last_audio_pts_us_ = output_audio_frame.pts_us;

    // Video epoch gate (Phase 6 only)
    if (master_clock_ && audio_phase6_gating_active) {
      if (!video_epoch_set_) {
        audio_skip_count_++;
        if (audio_skip_count_ == 1 || audio_skip_count_ % 100 == 0) {
          std::cout << "[FileProducer] AUDIO_SKIP #" << audio_skip_count_
                    << " waiting for video epoch (audio_pts_us=" << base_pts_us << ")" << std::endl;
        }
        av_frame_unref(audio_frame_);
        return false;
      }
      if (!audio_ungated_logged_) {
        std::cout << "[FileProducer] AUDIO_UNGATED first_audio_pts_us=" << base_pts_us
                  << " aligned_to_video_pts_us=" << first_mt_pts_us_ << std::endl;
        {
          std::lock_guard<std::mutex> lock(g_video_epoch_mutex);
          auto it = g_video_epoch_time.find(this);
          if (it != g_video_epoch_time.end()) {
            int elapsed_ms = static_cast<int>(std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::steady_clock::now() - it->second).count());
            if (elapsed_ms <= 100) {
              std::cout << "[FileProducer] INV-P10-AUDIO-VIDEO-GATE: First audio queued at "
                        << elapsed_ms << "ms after video epoch" << std::endl;
            }
          }
        }
        audio_ungated_logged_ = true;
      }
      // Fake clock gating (tests only)
      if (master_clock_->is_fake()) {
        int64_t frame_offset_us = base_pts_us - first_mt_pts_us_;
        int64_t target_utc_us = playback_start_utc_us_ + frame_offset_us;
        while (master_clock_->now_utc_us() < target_utc_us &&
               !stop_requested_.load(std::memory_order_acquire))
          std::this_thread::yield();
      }
    }

    // Shadow audio gate
    bool audio_should_be_gated = shadow_decode_mode_.load(std::memory_order_acquire)
                                 && (!video_epoch_set_);
    if (mapping_locked_this_iteration_)
      audio_should_be_gated = false;
    if (audio_should_be_gated) {
      audio_mapping_gate_drop_count_++;
      if (audio_mapping_gate_drop_count_ <= 5 || audio_mapping_gate_drop_count_ % 100 == 0) {
        std::cout << "[FileProducer] AUDIO_GATED #" << audio_mapping_gate_drop_count_
                  << " - shadow mode active AND no video epoch" << std::endl;
      }
      av_frame_unref(audio_frame_);
      return false;
    }

    // Push with backpressure
    audio_frame_count_++;
    frames_since_producer_start_++;
    static thread_local bool audio_backpressure_logged = false;
    while (!output_buffer_.PushAudioFrame(output_audio_frame)) {
      if (!audio_backpressure_logged) {
        std::cout << "[FileProducer] Audio backpressure: blocking at queue capacity" << std::endl;
        audio_backpressure_logged = true;
      }
      if (stop_requested_.load(std::memory_order_acquire)) { av_frame_unref(audio_frame_); return false; }
      if (writes_disabled_.load(std::memory_order_acquire)) { av_frame_unref(audio_frame_); return false; }
      if (master_clock_ && !master_clock_->is_fake())
        std::this_thread::sleep_for(std::chrono::microseconds(kProducerBackoffUs));
      else
        std::this_thread::yield();
    }
    if (audio_backpressure_logged) {
      std::cout << "[FileProducer] Audio backpressure: released" << std::endl;
      audio_backpressure_logged = false;
    }

    steady_state_audio_count_.fetch_add(1, std::memory_order_release);
    av_frame_unref(audio_frame_);

    pushed_duration_us = sample_duration_us;
    return true;
  }

  // ======================================================================
  // INV-AUDIO-DEBT: DrainAudioForTick — tick-driven audio time-debt drain
  // ======================================================================
  // Called after each video tick emission (both resampled and non-resampled).
  // Adds tick_us to audio_debt_us_, then drains decoded audio frames until
  // enough audio duration has been pushed to cover the debt.
  //
  // At 30fps / AAC 48kHz 1024-sample:
  //   tick_us = 33333us, audio frame = 21333us
  //   → typically drains 1-2 frames per tick, averaging ~1.56 frames/tick
  //   → over 30 ticks/sec: ~46.8 frames/sec (matches audio requirement)
  //
  // Bounded by kMaxAudioFramesPerTick to prevent runaway in edge cases.
  // ======================================================================
  void FileProducer::DrainAudioForTick(int64_t tick_us)
  {
    audio_debt_us_ += tick_us;

    int frames_drained = 0;
    while (audio_debt_us_ > 0 && frames_drained < kMaxAudioFramesPerTick) {
      if (stop_requested_.load(std::memory_order_acquire)) break;
      if (writes_disabled_.load(std::memory_order_acquire)) break;

      int64_t pushed_us = 0;
      if (!ReceiveOneAudioFrameAndPush(pushed_us))
        break;  // EAGAIN/EOF/full — no more frames available

      audio_debt_us_ -= pushed_us;
      frames_drained++;
    }

    // Clamp debt to prevent unbounded accumulation on prolonged starvation
    // (e.g. audio EOF reached before video). Allow small negative debt (audio ahead).
    if (audio_debt_us_ > 200000) {  // Cap at 200ms debt
      audio_debt_us_ = 200000;
    }

    // One-shot diagnostic at frame 300 (~10s at 30fps)
    if (!audio_debt_diagnostic_logged_ && audio_frame_count_ >= 300) {
      audio_debt_diagnostic_logged_ = true;
      std::cout << "[FileProducer] INV-AUDIO-DEBT: 10s checkpoint"
                << " audio_frames=" << audio_frame_count_
                << " debt_us=" << audio_debt_us_
                << " (target ~469 frames for 48k/1024)" << std::endl;
    }
  }

  // DrainAudioDecoderIfNeeded: LEGACY — now delegates to DrainAudioForTick
  // Kept for any remaining call sites; uses one tick of debt.
  void FileProducer::DrainAudioDecoderIfNeeded()
  {
    if (audio_stream_index_ >= 0 && !audio_eof_reached_) {
      DrainAudioForTick(TickDurationUs());
    }
  }

  // INV-FPS-RESAMPLE: tick_time_us(n) = DurationFromFramesUs(n) [using RationalFps helper]. Integer math, no drift.
  int64_t FileProducer::TickTimeUs(int64_t n) const
  {
    if (target_fps_r_.num <= 0) return 0;
    return (n * 1'000'000 * target_fps_r_.den) / target_fps_r_.num;
  }

  // ======================================================================
  // INV-FPS-RESAMPLE: EmitFrameAtTick — sole emission path for resampled frames
  // ======================================================================
  // This is the ONLY place where resampler-emitted frames:
  //   - Get PTS/duration stamped to tick grid
  //   - Trigger VIDEO_EPOCH_SET
  //   - Get paced to wall clock
  //   - Get pushed to output buffer
  // By routing all resampler emissions through here, the single-emit-per-tick
  // contract is mechanically enforced: callers select frames, this method emits.
  // ======================================================================
  bool FileProducer::EmitFrameAtTick(buffer::Frame& frame, int64_t tick_pts_us)
  {
    // Stamp PTS and duration to tick grid — NEVER source PTS
    frame.metadata.pts = tick_pts_us;
    frame.metadata.duration = target_fps_r_.FrameDurationSec();
    frame.metadata.has_ct = true;

    // Update MT tracking to tick grid
    last_decoded_mt_pts_us_ = tick_pts_us;
    last_mt_pts_us_ = tick_pts_us;

    // VIDEO_EPOCH_SET (if first emitted frame)
    if (!video_epoch_set_) {
      video_epoch_set_ = true;
      first_mt_pts_us_ = tick_pts_us;
      if (master_clock_) {
        playback_start_utc_us_ = master_clock_->now_utc_us();
      }
      std::cout << "[FileProducer] VIDEO_EPOCH_SET (resample) first_mt_pts_us="
                << tick_pts_us << std::endl;
      {
        std::lock_guard<std::mutex> lock(g_video_epoch_mutex);
        g_video_epoch_time[this] = std::chrono::steady_clock::now();
      }
      if (timeline_controller_ && master_clock_) {
        playback_start_utc_us_ = master_clock_->now_utc_us();
      }
    }

    // Pacing: wait until target UTC time
    int64_t frame_offset_us = tick_pts_us - first_mt_pts_us_;
    int64_t target_utc_us = playback_start_utc_us_ + frame_offset_us;
    if (master_clock_) {
      int64_t now_us = master_clock_->now_utc_us();
      if (now_us < target_utc_us && !stop_requested_.load(std::memory_order_acquire)) {
        if (master_clock_->is_fake()) {
          while (master_clock_->now_utc_us() < target_utc_us &&
                 !stop_requested_.load(std::memory_order_acquire))
            std::this_thread::yield();
        } else {
          int64_t sleep_us = target_utc_us - now_us;
          if (sleep_us > 0)
            std::this_thread::sleep_for(std::chrono::microseconds(sleep_us));
        }
      }
    }

    // Truncation check
    if (planned_frame_count_ >= 0 &&
        frames_delivered_.load(std::memory_order_acquire) >= planned_frame_count_) {
      return false;  // Truncated — caller should stop
    }

    // Push with backpressure
    while (!output_buffer_.Push(frame)) {
      if (stop_requested_.load(std::memory_order_acquire)) return false;
      if (writes_disabled_.load(std::memory_order_acquire)) return false;
      buffer_full_count_.fetch_add(1, std::memory_order_relaxed);
      if (master_clock_ && !master_clock_->is_fake())
        std::this_thread::sleep_for(std::chrono::microseconds(kProducerBackoffUs));
      else
        std::this_thread::yield();
    }

    frames_produced_.fetch_add(1, std::memory_order_relaxed);
    frames_delivered_.fetch_add(1, std::memory_order_relaxed);

    // INV-AUDIO-DEBT: Tick-driven audio drain after video emission
    DrainAudioForTick(TickDurationUs());

    return true;  // Frame emitted successfully
  }

  // ======================================================================
  // INV-FPS-RESAMPLE: Extracted resampler gate
  // ======================================================================
  ResampleGateResult FileProducer::ResampleGate(
      buffer::Frame& output_frame, int64_t& base_pts_us)
  {
    if (!resample_active_) {
      return ResampleGateResult::PASS;
    }

    resample_frames_decoded_++;

    // Initialize tick grid from first frame: align tick index so current tick contains base_pts_us.
    if (next_output_tick_us_ < 0) {
      // tick_index_ such that tick_time_us(tick_index_) <= base_pts_us < tick_time_us(tick_index_+1)
      if (target_fps_r_.num > 0 && target_fps_r_.den > 0) {
        tick_index_ = (base_pts_us * target_fps_r_.num) / (1'000'000 * target_fps_r_.den);
      }
      next_output_tick_us_ = TickTimeUs(tick_index_);
      std::cout << "[FileProducer] INV-FPS-RESAMPLE: Tick grid anchored at "
                << base_pts_us << "us tick_index=" << tick_index_
                << " (source=" << source_fps_r_.num << "/" << source_fps_r_.den
                << "fps, target=" << config_.target_fps.num << "/" << config_.target_fps.den << "fps)" << std::endl;
    }

    // Is this frame a candidate for the current tick?
    if (base_pts_us <= next_output_tick_us_) {
      // At or before tick boundary — hold as best candidate, continue decoding
      held_frame_storage_ = output_frame;
      held_frame_valid_ = true;
      held_frame_mt_us_ = base_pts_us;
      // HOLD returns to caller (ProduceRealFrame), which returns true to the main
      // decode loop. The loop immediately calls ProduceRealFrame() again, which calls
      // av_read_frame(). Audio packets are dispatched at the av_read_frame level
      // (audio packet → ReceiveAudioFrames() → return true). Therefore HOLD never
      // starves audio: there is no internal spin, and packet consumption remains
      // interleaved between video HOLD iterations.
      return ResampleGateResult::HOLD;
    }

    // Crossed tick boundary: base_pts_us > next_output_tick_us_
    // Check if the crossing frame is ALSO past the NEXT tick (slow source / repeat case)
    int64_t after_tick = TickTimeUs(tick_index_ + 1);
    if (base_pts_us > after_tick && held_frame_valid_) {
      // Crossing frame is past the next tick too — repeat held frame,
      // save crossing frame for later
      pending_frame_storage_ = output_frame;
      pending_frame_valid_ = true;
      pending_frame_mt_us_ = base_pts_us;
      output_frame = held_frame_storage_;
    } else {
      // Normal case: crossing frame between current and next tick
      buffer::Frame crossing = output_frame;
      int64_t crossing_mt = base_pts_us;
      if (held_frame_valid_) {
        output_frame = held_frame_storage_;
      }
      held_frame_storage_ = crossing;
      held_frame_valid_ = true;
      held_frame_mt_us_ = crossing_mt;
    }

    // Stamp output to tick grid (rational: no accumulated interval)
    int64_t tick_pts_us = next_output_tick_us_;
    output_frame.metadata.pts = tick_pts_us;
    output_frame.metadata.duration = target_fps_r_.FrameDurationSec();
    base_pts_us = tick_pts_us;
    last_decoded_mt_pts_us_ = tick_pts_us;
    last_mt_pts_us_ = tick_pts_us;
    resample_frames_emitted_++;
    next_output_tick_us_ = TickTimeUs(++tick_index_);

    // Periodic stats
    if (resample_frames_emitted_ % 300 == 0) {
      std::cout << "[FileProducer] INV-FPS-RESAMPLE: decoded="
                << resample_frames_decoded_
                << " emitted=" << resample_frames_emitted_
                << " skip=" << (resample_frames_decoded_ - resample_frames_emitted_)
                << std::endl;
    }

    // Reset consecutive repeat counter — this is a fresh (non-repeat) emission
    consecutive_repeat_emits_ = 0;

    return ResampleGateResult::EMIT;
  }

  // ======================================================================
  // INV-FPS-RESAMPLE: Pending frame promotion (for slow source repeats)
  // ======================================================================
  bool FileProducer::ResamplePromotePending(
      buffer::Frame& output_frame, int64_t& base_pts_us)
  {
    if (!resample_active_ || !pending_frame_valid_) {
      return false;
    }

    if (pending_frame_mt_us_ <= next_output_tick_us_) {
      // Promote pending to held, let caller decode next
      held_frame_storage_ = pending_frame_storage_;
      held_frame_valid_ = true;
      held_frame_mt_us_ = pending_frame_mt_us_;
      pending_frame_valid_ = false;
      consecutive_repeat_emits_ = 0;  // Pending promoted — repeat streak ended
      return false;
    }

    if (!held_frame_valid_) {
      return false;
    }

    // Pending still past current tick — emit held as repeat
    output_frame = held_frame_storage_;
    int64_t tick_pts_us = next_output_tick_us_;
    base_pts_us = tick_pts_us;
    output_frame.metadata.pts = tick_pts_us;
    output_frame.metadata.duration = target_fps_r_.FrameDurationSec();
    last_decoded_mt_pts_us_ = tick_pts_us;
    last_mt_pts_us_ = tick_pts_us;
    resample_frames_emitted_++;
    next_output_tick_us_ = TickTimeUs(++tick_index_);

    // Track consecutive repeats for freeze-frame diagnostics.
    // Freeze-frame under source stall is valid broadcast behavior, but extended
    // repeats may indicate a stuck decoder or missing content.
    consecutive_repeat_emits_++;
    if (consecutive_repeat_emits_ == kRepeatLogThreshold ||
        (consecutive_repeat_emits_ > kRepeatLogThreshold &&
         consecutive_repeat_emits_ % (kRepeatLogThreshold * 10) == 0)) {
      std::cout << "[FileProducer] INV-FPS-RESAMPLE: consecutive repeats="
                << consecutive_repeat_emits_
                << " (source may be stalled or content missing)" << std::endl;
    }

    return true;  // Caller should emit this frame, skip decode
  }

} // namespace retrovue::producers::file
