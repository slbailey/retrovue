// Repository: Retrovue-playout
// Component: VideoLookaheadBuffer
// Purpose: Non-blocking video frame buffer with background fill thread.
// Contract Reference: INV-VIDEO-LOOKAHEAD-001
// Copyright (c) 2025 RetroVue

#include "retrovue/blockplan/VideoLookaheadBuffer.hpp"

#include <algorithm>
#include <chrono>
#include <cstring>
#include <cmath>
#include <iostream>
#include <numeric>
#include <sstream>
#include <utility>

#include "retrovue/blockplan/AudioLookaheadBuffer.hpp"
#include "retrovue/blockplan/ITickProducer.hpp"
#include "retrovue/blockplan/TickProducer.hpp"
#include "retrovue/util/Logger.hpp"

namespace retrovue::blockplan {

using retrovue::util::Logger;

VideoLookaheadBuffer::VideoLookaheadBuffer(int target_depth_frames,
                                           int low_water_frames)
    : target_depth_frames_(target_depth_frames),
      low_water_frames_(low_water_frames) {}

VideoLookaheadBuffer::~VideoLookaheadBuffer() {
  StopFilling(false);
}

// =============================================================================
// StartFilling — consume primed frame synchronously, then spawn fill thread
// =============================================================================

void VideoLookaheadBuffer::StartFilling(
    ITickProducer* producer,
    AudioLookaheadBuffer* audio_buffer,
    RationalFps input_fps,
    RationalFps output_fps,
    std::atomic<bool>* stop_signal) {
  // Ensure no fill thread is running.
  StopFilling(false);

  fill_stop_.store(false, std::memory_order_release);
  steady_filling_.store(true, std::memory_order_relaxed);  // INV-BUFFER-HYSTERESIS-001: start filling
  producer_ = producer;
  audio_buffer_ = audio_buffer;
  stop_signal_ = stop_signal;
  // Wire interrupt flags so FFmpeg I/O (av_read_frame etc.) aborts promptly on stop.
  ITickProducer::InterruptFlags flags;
  flags.fill_stop = &fill_stop_;
  flags.session_stop = stop_signal;
  producer_->SetInterruptFlags(flags);
  input_fps_ = input_fps;
  output_fps_ = output_fps;
  resample_mode_ = producer ? producer->GetResampleMode() : ResampleMode::OFF;
  drop_step_ = producer ? producer->GetDropStep() : 1;
  fill_start_time_ = std::chrono::steady_clock::now();

  // INV-BLOCK-PRIME-002: Consume primed frame synchronously (non-blocking).
  // This guarantees the buffer has at least one frame immediately after
  // StartFilling returns, enabling the fence-tick to pop without delay.
  // INV-AUDIO-PRIME-001: The primed frame carries its own decoded audio
  // (typically 1-2 frames).  Remaining primed audio is distributed across
  // buffered_frames_, which the fill thread processes immediately (no I/O)
  // after StartFilling spawns the thread.
  bool has_primed = producer_->HasPrimedFrame();
  { std::ostringstream oss;
    oss << "[VideoBuffer:" << buffer_label_ << "] StartFilling:"
        << " HasPrimedFrame=" << has_primed
        << " has_decoder=" << producer_->HasDecoder()
        << " audio_buffer=" << (audio_buffer_ ? "yes" : "null");
    Logger::Info(oss.str()); }
  if (has_primed) {
    auto fd = producer_->TryGetFrame();
    if (fd) {
      const size_t primed_audio_count = fd->audio.size();
      const bool has_audio_stream = producer_->HasAudioStream();

      VideoBufferFrame vf;
      vf.video = fd->video;          // copy for potential cache use
      vf.asset_uri = std::move(fd->asset_uri);
      vf.block_ct_ms = fd->block_ct_ms;
      vf.was_decoded = true;

      // Push decoded audio to AudioLookaheadBuffer.
      if (audio_buffer_) {
        for (auto& af : fd->audio) {
          audio_buffer_->Push(std::move(af));
        }
      }

      int audio_depth_ms = audio_buffer_ ? audio_buffer_->DepthMs() : -1;
      constexpr int kMinAudioForSeamMs = 200;  // below this, gate will wait
      bool ready_for_seam = (!audio_buffer_) || (audio_depth_ms >= kMinAudioForSeamMs);
      const char* reason = !audio_buffer_ ? "no_audio_buffer"
          : (primed_audio_count == 0 && has_audio_stream) ? "primed_has_no_audio"
          : (audio_depth_ms >= kMinAudioForSeamMs) ? "sufficient_audio"
          : "insufficient_audio";

      { std::ostringstream oss;
        oss << "[VideoBuffer:" << buffer_label_ << "] StartFilling: primed_frame"
            << " has_audio_stream=" << has_audio_stream
            << " audio_count=" << primed_audio_count
            << " audio_depth_ms=" << audio_depth_ms
            << " ready_for_seam=" << ready_for_seam
            << " reason=" << reason;
        Logger::Info(oss.str()); }

      std::lock_guard<std::mutex> lock(mutex_);
      frames_.push_back(std::move(vf));
      total_pushed_++;
      primed_ = true;
    }
  }

  // Log resample mode (rational detection: OFF / DROP / CADENCE). DEBUG: chatty per segment.
  { std::ostringstream oss;
    oss << "[VideoBuffer:" << buffer_label_ << "] FPS_CADENCE:"
        << " input_fps=" << input_fps_.num << "/" << input_fps_.den
        << " output_fps=" << output_fps_.num << "/" << output_fps_.den;
    if (resample_mode_ == ResampleMode::OFF) {
      oss << " mode=OFF";
    } else if (resample_mode_ == ResampleMode::DROP) {
      oss << " mode=DROP ratio=" << drop_step_;
      if (output_fps_.num > 0) {
        oss << " tick_duration_ms=" << (1000 * output_fps_.den / output_fps_.num);
      }
    } else {
      int64_t ratio_num = (output_fps_.num > 0 && input_fps_.num > 0)
          ? (input_fps_.num * output_fps_.den) / (input_fps_.den * output_fps_.num)
          : 0;
      oss << " mode=CADENCE ratio_approx=" << ratio_num;
    }
    Logger::Debug(oss.str()); }

  fill_running_ = true;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    fill_generation_++;  // New generation for new fill thread
  }
  fill_thread_ = std::thread(&VideoLookaheadBuffer::FillLoop, this);
}

// =============================================================================
// StopFilling — join fill thread, optionally flush buffer
// =============================================================================

void VideoLookaheadBuffer::StopFilling(bool flush) {
  if (fill_running_) {
    fill_stop_.store(true, std::memory_order_release);
    space_cv_.notify_all();  // wake fill thread if waiting for space
    if (fill_thread_.joinable()) {
      fill_thread_.join();
    }
    fill_running_ = false;
  }

  if (flush) {
    std::lock_guard<std::mutex> lock(mutex_);
    frames_.clear();
    primed_ = false;
    // total_pushed_ / total_popped_ are cumulative — not reset on flush.
  }

  producer_ = nullptr;
  audio_buffer_ = nullptr;
  stop_signal_ = nullptr;
}

// =============================================================================
// StopFillingAsync — signal fill thread, flush, extract thread for deferred join
// =============================================================================

VideoLookaheadBuffer::DetachedFill
VideoLookaheadBuffer::StopFillingAsync(bool flush) {
  DetachedFill result;
  if (fill_running_) {
    fill_stop_.store(true, std::memory_order_release);
    space_cv_.notify_all();
    result.thread = std::move(fill_thread_);
    fill_running_ = false;
  }
  {
    std::lock_guard<std::mutex> lock(mutex_);
    fill_generation_++;  // Invalidate any in-flight push from old thread
    if (flush) {
      frames_.clear();
      primed_ = false;
    }
  }
  producer_ = nullptr;
  audio_buffer_ = nullptr;
  stop_signal_ = nullptr;
  return result;
}

bool VideoLookaheadBuffer::IsFilling() const {
  return fill_running_;
}

// =============================================================================
// FillLoop — background thread: decode ahead, resolve cadence, push to buffer
// =============================================================================


void VideoLookaheadBuffer::FillLoop() {
  // Capture producer/audio/stop at thread start so StopFillingAsync can null
  // members immediately. The fill thread uses only these locals — objects
  // remain valid (owned by PipelineManager deferred_* until reaper joins).
  ITickProducer* producer = producer_;
  AudioLookaheadBuffer* audio_buffer = audio_buffer_;
  std::atomic<bool>* stop_signal = stop_signal_;

  // Capture generation at thread start; any mismatch means fence happened.
  uint64_t my_gen;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    my_gen = fill_generation_;
  }

  // Capture audio generation for generation-gated audio pushes.
  uint64_t my_audio_gen = 0;
  if (audio_buffer) {
    my_audio_gen = audio_buffer->CurrentGeneration();
  }

  // --- Cadence setup: use ResampleMode from TickProducer (rational detection) ---
  // Decode rate is bounded by source cadence (e.g. ~23.976 decodes/sec for 24fps assets).
  // We do NOT chase output tick rate; TickLoop performs repeat-vs-advance and only pops
  // on advance ticks, so buffer drain rate matches source cadence and FillLoop is not
  // forced to decode at 30/sec for 24fps content.
  // INV-FPS-MAPPING: decode_budget / input_fps-derived budgeting ONLY when mode==CADENCE.
  // OFF and DROP must not use input_fps for decode gating; they decode every tick.
  bool cadence_active = (resample_mode_ == ResampleMode::CADENCE);
  using Wide = __int128;
  Wide cadence_budget_num = 0;
  Wide cadence_budget_den = 1;
  if (cadence_active && output_fps_.num > 0 && output_fps_.den > 0 &&
      input_fps_.num > 0 && input_fps_.den > 0) {
    cadence_budget_num = static_cast<Wide>(output_fps_.num) * static_cast<Wide>(input_fps_.den);
    cadence_budget_den = static_cast<Wide>(input_fps_.num) * static_cast<Wide>(output_fps_.den);
  }
  // OFF: 1:1 decode every tick. DROP: TickProducer decodes step internally, we decode every tick.

  // Pre-build silence template for hold-last / cadence-repeat ticks.
  // One tick demands at most ceil(48000 / output_fps) samples.
  buffer::AudioFrame silence_template;
  int silence_samples_per_frame = 0;
  if (audio_buffer && output_fps_.num > 0) {
    const int64_t samples_num = static_cast<int64_t>(buffer::kHouseAudioSampleRate) * output_fps_.den;
    silence_samples_per_frame = static_cast<int>((samples_num + output_fps_.num - 1) / output_fps_.num);
    silence_template.sample_rate = buffer::kHouseAudioSampleRate;
    silence_template.channels = buffer::kHouseAudioChannels;
    silence_template.nb_samples = silence_samples_per_frame;
    silence_template.data.resize(
        static_cast<size_t>(silence_samples_per_frame) *
        buffer::kHouseAudioChannels * sizeof(int16_t), 0);
  }

  // Seed last_decoded from the primed frame (if consumed in StartFilling).
  buffer::Frame last_decoded;
  bool have_last_decoded = false;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!frames_.empty()) {
      last_decoded = frames_.back().video;
      have_last_decoded = true;
    }
  }

  // INV-BLOCK-WALLFENCE-003: content_gap tracks whether the CURRENT
  // TryGetFrame cycle returned nullopt.  Unlike the old permanent
  // content_exhausted flag, this is RE-EVALUATED every decode cycle so
  // the TickProducer's segment-advancement logic (boundary check inside
  // TryGetFrame) continues to fire.  When TryGetFrame eventually opens
  // the next segment (filler/pad), content_gap clears and real frames
  // flow again.
  bool content_gap = false;

  { std::ostringstream oss;
    oss << "[FillLoop:" << buffer_label_ << "] ENTER"
        << " input_fps=" << input_fps_.num << "/" << input_fps_.den
        << " output_fps=" << output_fps_.num << "/" << output_fps_.den
        << " cadence_active=" << cadence_active
        << " my_audio_gen=" << my_audio_gen
        << " have_last_decoded=" << have_last_decoded;
    Logger::Debug(oss.str()); }

  const char* exit_reason = "unknown";
  try {
  if (!producer) {
    exit_reason = "producer_null";
  }
  while (producer &&
         !fill_stop_.load(std::memory_order_acquire) &&
         !(stop_signal && stop_signal->load(std::memory_order_acquire))) {

    // INV-AUDIO-LIVENESS-001: When we continue decode for audio while video full,
    // we drop the video frame this cycle (do not enqueue); audio is still pushed.
    bool drop_video_this_cycle = false;

    // INV-P10-PIPELINE-FLOW-CONTROL: Strict slot-based gating (no hysteresis).
    //
    // FILLING path (steady_filling_ == true): Read depth under a brief lock.
    // Park when depth >= target_depth_frames_ (no 2×/4× high-water).
    //
    // INV-AUDIO-LIVENESS-001: Audio-first decode under backpressure.
    // When video is at capacity but audio is below low-water, do NOT park:
    // continue decoding to service audio; push audio only, drop video frame.
    //
    // PARKED path (steady_filling_ == false): Block on space_cv_ until
    // depth < target (one slot free) or audio burst fires. notify_one per
    // TryPopFrame() allows exactly one decode cycle when at boundary.
    //
    // Bootstrap phase always uses the condvar path (needs audio-gated
    // parking logic).
    //
    // INV-AUDIO-PRIME-003: Bootstrap phase.
    // During BOOTSTRAP, the fill thread must not park solely because
    // video_depth >= target.  It must continue decoding until audio
    // depth reaches the gate threshold, bounded by bootstrap_cap.
    //
    // INV-TICK-GUARANTEED-OUTPUT: Audio burst-fill mode.
    // When audio is critically low, predicate may return true even when
    // depth >= target (up to burst_cap), so decode can resume without
    // draining to <= target.
    {
      bool is_bootstrap = fill_phase_.load(std::memory_order_relaxed) ==
          static_cast<int>(FillPhase::kBootstrap);
      bool filling_now = steady_filling_.load(std::memory_order_relaxed);
      bool skip_wait = false;

      if (!is_bootstrap && filling_now) {
        // FILLING path: park when depth >= target (strict slot-based).
        // INV-AUDIO-LIVENESS-001: unless audio is below low-water — then continue
        // decoding for audio only (drop video frame this cycle).
        int depth;
        {
          std::lock_guard<std::mutex> lock(mutex_);
          depth = static_cast<int>(frames_.size());
        }
        if (depth >= target_depth_frames_) {
          const int audio_depth_ms = audio_buffer ? audio_buffer->DepthMs() : 0;
          const int audio_low_ms = audio_buffer ? audio_buffer->LowWaterMs() : 0;
          const bool audio_below_low = (audio_buffer && audio_depth_ms < audio_low_ms);
          if (audio_below_low) {
            // Audio-first: do not park; continue decode to service audio; drop video.
            skip_wait = true;
            drop_video_this_cycle = true;
          } else {
            // At or above target, audio sufficient — transition to PARKED.
            steady_filling_.store(false, std::memory_order_relaxed);
            { std::ostringstream oss;
              oss << "[FillLoop:" << buffer_label_ << "] PARK"
                  << " video_depth_frames=" << depth
                  << " audio_depth_ms=" << audio_depth_ms;
              Logger::Debug(oss.str()); }
            // Fall through to the condvar path below so we park properly.
          }
        } else {
          // Below target — skip condvar, proceed to decode.
          skip_wait = true;
        }
      }

      if (!skip_wait) {
        // PARKED path (or bootstrap): block on condvar.
        // INV-AUDIO-LIVENESS-001: Use a short timeout so we re-check the predicate
        // (including audio < low_water) periodically; otherwise we only wake on
        // TryPopFrame notify and would never service audio when consumer pops audio only.
        constexpr auto kParkWaitTimeout = std::chrono::milliseconds(20);
        {
          std::unique_lock<std::mutex> lock(mutex_);
          space_cv_.wait_for(lock, kParkWaitTimeout, [this, stop_signal, audio_buffer] {
            bool stopping = fill_stop_.load(std::memory_order_acquire) ||
                (stop_signal && stop_signal->load(std::memory_order_acquire));
            if (stopping) return true;

            int depth = static_cast<int>(frames_.size());

            // INV-AUDIO-PRIME-003: Bootstrap phase — audio-gated parking.
            if (fill_phase_.load(std::memory_order_relaxed) ==
                static_cast<int>(FillPhase::kBootstrap)) {
              // Hard cap: never exceed bootstrap_cap regardless of audio state.
              if (depth >= bootstrap_cap_frames_) return false;
              // Below bootstrap target: always decode.
              if (depth < bootstrap_target_frames_) return true;
              // At/above bootstrap target but below cap: decode only if audio
              // hasn't reached the gate threshold yet.
              if (audio_buffer && audio_buffer->DepthMs() < bootstrap_min_audio_ms_)
                return true;
              return false;
            }

            // STEADY phase (PARKED): resume when depth < target (slot free).
            // Strict slot-based: one pop → one wake → one decode cycle at boundary.
            if (depth < target_depth_frames_) {
              steady_filling_.store(true, std::memory_order_relaxed);
              { std::ostringstream oss;
                oss << "[FillLoop:" << buffer_label_ << "] UNPARK"
                    << " video_depth_frames=" << depth
                    << " audio_depth_ms=" << (audio_buffer ? audio_buffer->DepthMs() : -1);
                Logger::Debug(oss.str()); }
              return true;
            }

            // Audio burst: resume when audio critically low (need not drain to target).
            if (audio_buffer && audio_buffer->DepthMs() < audio_burst_threshold_ms_) {
              int burst_cap = target_depth_frames_ * 4;
              return depth < burst_cap;
            }
            // INV-AUDIO-LIVENESS-001: Wake to service audio when below low-water even if video full.
            if (depth >= target_depth_frames_ && audio_buffer &&
                audio_buffer->DepthMs() < audio_buffer->LowWaterMs()) {
              steady_filling_.store(true, std::memory_order_relaxed);
              return true;  // Decode this cycle; video frame will be dropped (set after wait).
            }
            return false;
          });
        }
        // INV-AUDIO-LIVENESS-001: If we woke from wait and video is still full with audio low,
        // this cycle we decode for audio only and drop the video frame.
        if (!skip_wait && audio_buffer) {
          int d;
          { std::lock_guard<std::mutex> lock(mutex_); d = static_cast<int>(frames_.size()); }
          const int a_ms = audio_buffer->DepthMs();
          const int low_ms = audio_buffer->LowWaterMs();
          if (d >= target_depth_frames_ && a_ms < low_ms)
            drop_video_this_cycle = true;
        }
        if (fill_stop_.load(std::memory_order_acquire) ||
            (stop_signal && stop_signal->load(std::memory_order_acquire))) {
          exit_reason = fill_stop_.load(std::memory_order_acquire)
              ? "fill_stop" : "session_stop";
          break;
        }
        // BOOTSTRAP: log each wake only when debugging (enable RETROVUE_DEBUG_BOOTSTRAP at build).
#ifdef RETROVUE_DEBUG_BOOTSTRAP
        if (fill_phase_.load(std::memory_order_relaxed) ==
            static_cast<int>(FillPhase::kBootstrap)) {
          int d = static_cast<int>(frames_.size());
          int a_ms = audio_buffer ? audio_buffer->DepthMs() : -1;
          { std::ostringstream oss;
            oss << "[FillLoop:" << buffer_label_ << "] BOOTSTRAP_WAKE"
                << " bootstrap_epoch_ms=" << bootstrap_epoch_ms_
                << " video_depth=" << d
                << " bootstrap_target=" << bootstrap_target_frames_
                << " cap=" << bootstrap_cap_frames_
                << " audio_depth_ms=" << a_ms
                << " min_audio_ms=" << bootstrap_min_audio_ms_;
            Logger::Info(oss.str()); }
        }
#endif
      }
      // Temporary debug: once per second — video depth, steady_filling_, parked vs decoding.
      {
        static auto last_fill_log = std::chrono::steady_clock::now();
        auto now = std::chrono::steady_clock::now();
        if (std::chrono::duration_cast<std::chrono::milliseconds>(now - last_fill_log).count() >= 1000) {
          last_fill_log = now;
          int depth;
          { std::lock_guard<std::mutex> lock(mutex_); depth = static_cast<int>(frames_.size()); }
          bool filling = steady_filling_.load(std::memory_order_relaxed);
          const char* state = skip_wait ? "decoding" : "parked";
          std::ostringstream oss;
          oss << "[FillLoop:" << buffer_label_ << "] DBG_VIDEO_DEPTH"
              << " depth=" << depth
              << " steady_filling=" << (filling ? "true" : "false")
              << " state=" << state;
          Logger::Debug(oss.str());
        }
      }
    }

    // Re-check stop after depth/condvar decision.
    if (fill_stop_.load(std::memory_order_acquire) ||
        (stop_signal && stop_signal->load(std::memory_order_acquire))) {
      exit_reason = fill_stop_.load(std::memory_order_acquire)
          ? "fill_stop" : "session_stop";
      break;
    }

    // --- Cadence gate ---
    // Rational cadence gate: budget += input/output per tick (integer accumulator).
    bool should_decode = true;
    if (cadence_active) {
      cadence_budget_num += static_cast<Wide>(input_fps_.num) * static_cast<Wide>(output_fps_.den);
      if (cadence_budget_num >= cadence_budget_den) {
        cadence_budget_num -= cadence_budget_den;
        should_decode = true;
      } else {
        should_decode = false;
      }
    }

    VideoBufferFrame vf;

    // INV-SEAM-SEG-006: TryGetFrame returns nullopt permanently when the
    // current segment's content is exhausted.  The fill thread enters
    // hold-last mode until PipelineManager performs the segment swap
    // (pointer rotation).  No decoder lifecycle work happens on this thread.
    if (should_decode) {
      auto decode_start = std::chrono::steady_clock::now();
      auto fd = producer->TryGetFrame();
      auto decode_end = std::chrono::steady_clock::now();
      if (fd) {
        content_gap = false;
        // Record decode latency (separate lock scope from frame push).
        {
          auto latency_us = std::chrono::duration_cast<std::chrono::microseconds>(
              decode_end - decode_start).count();
          std::lock_guard<std::mutex> lock(mutex_);
          decode_latency_us_[latency_ring_pos_] = latency_us;
          latency_ring_pos_ = (latency_ring_pos_ + 1) % kLatencyRingSize;
          if (latency_ring_count_ < kLatencyRingSize) latency_ring_count_++;
        }
        // Cache for cadence repeats and hold-last.
        last_decoded = fd->video;  // copy to cache
        have_last_decoded = true;

        vf.video = std::move(fd->video);  // move to buffer frame
        vf.asset_uri = std::move(fd->asset_uri);
        vf.block_ct_ms = fd->block_ct_ms;
        vf.was_decoded = true;

        // Bail out before pushing if stop was requested or generation changed.
        if (fill_stop_.load(std::memory_order_acquire)) {
          exit_reason = "fill_stop";
          break;
        }

        // Push decoded audio to AudioLookaheadBuffer (generation-gated).
        if (audio_buffer) {
          for (auto& af : fd->audio) {
            audio_buffer->Push(std::move(af), my_audio_gen);
          }
        }
      } else if (have_last_decoded) {
        // Content gap — hold last frame while TryGetFrame advances block_ct_ms
        // toward the next segment boundary (filler/pad).
        content_gap = true;
        vf.video = last_decoded;
        vf.was_decoded = false;
        // INV-HOLD-LAST-AUDIO: Push silence so audio buffer doesn't underflow.
        if (audio_buffer && silence_samples_per_frame > 0) {
          audio_buffer->Push(silence_template, my_audio_gen);
        }
      } else {
        // No frame ever decoded (decoder failure on first frame).
        // Exit fill loop; tick loop will remain in pad mode.
        exit_reason = "first_frame_fail";
        break;
      }
    } else if (have_last_decoded) {
      // Cadence repeat (or content-gap hold-last).
      vf.video = last_decoded;
      vf.was_decoded = false;
      // Push silence on cadence-skip cycles when in a content gap
      // to prevent audio underflow on the block tail.
      if (content_gap && audio_buffer && silence_samples_per_frame > 0) {
        audio_buffer->Push(silence_template, my_audio_gen);
      }
    } else {
      // No frame available yet — shouldn't happen (first tick always decodes
      // unless content_exhausted on first frame, handled above).
      continue;
    }

    // Bail out before pushing if stop was requested or generation changed.
    if (fill_stop_.load(std::memory_order_acquire)) {
      exit_reason = "fill_stop";
      break;
    }

    // INV-AUDIO-LIVENESS-001: When video was full but we decoded for audio only,
    // push audio (already done above) but do not enqueue video — drop frame to avoid unbounded growth.
    if (drop_video_this_cycle) {
      decode_continued_for_audio_while_video_full_.fetch_add(1, std::memory_order_relaxed);
      // Skip frame push; primed_ and buffer depth unchanged.
    } else {
      // Push to buffer — generation gate prevents stale-frame bleed.
      std::lock_guard<std::mutex> lock(mutex_);
      if (fill_generation_ != my_gen) {
        exit_reason = "audio_gen_mismatch";
        break;  // Fence happened during decode
      }
      frames_.push_back(std::move(vf));
      total_pushed_++;
      primed_ = true;
    }
  }
  // Exited via while condition — determine reason
  if (strcmp(exit_reason, "unknown") == 0) {
    exit_reason = fill_stop_.load(std::memory_order_acquire)
        ? "fill_stop"
        : (stop_signal && stop_signal->load(std::memory_order_acquire)
            ? "session_stop" : "loop_exit");
  }
  } catch (const std::exception& e) {
    exit_reason = "exception";
    { std::ostringstream oss;
      oss << "[FillLoop:" << buffer_label_ << "] FILL_EXIT reason=exception"
          << " what=" << e.what();
      Logger::Error(oss.str()); }
  }
  if (strcmp(exit_reason, "exception") != 0) {
    { std::ostringstream oss;
      oss << "[FillLoop:" << buffer_label_ << "] FILL_EXIT reason=" << exit_reason;
      Logger::Debug(oss.str()); }
  }
}

// =============================================================================
// TryPopFrame — non-blocking consumer for the tick loop
// =============================================================================

bool VideoLookaheadBuffer::TryPopFrame(VideoBufferFrame& out) {
  std::lock_guard<std::mutex> lock(mutex_);

  if (frames_.empty()) {
    underflow_count_++;
    return false;
  }

  out = std::move(frames_.front());
  frames_.pop_front();
  total_popped_++;

  // Signal fill thread that space is available.
  space_cv_.notify_one();
  return true;
}

// =============================================================================
// Observability
// =============================================================================

int VideoLookaheadBuffer::DepthFrames() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return static_cast<int>(frames_.size());
}

int64_t VideoLookaheadBuffer::UnderflowCount() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return underflow_count_;
}

int64_t VideoLookaheadBuffer::TotalFramesPushed() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return total_pushed_;
}

int64_t VideoLookaheadBuffer::TotalFramesPopped() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return total_popped_;
}

bool VideoLookaheadBuffer::IsPrimed() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return primed_;
}

// =============================================================================
// Reset — stop fill thread, clear buffer and counters
// =============================================================================

void VideoLookaheadBuffer::Reset() {
  StopFilling(false);
  steady_filling_.store(true, std::memory_order_relaxed);  // INV-BUFFER-HYSTERESIS-001
  decode_continued_for_audio_while_video_full_.store(0, std::memory_order_relaxed);
  decode_parked_video_full_audio_low_.store(0, std::memory_order_relaxed);
  std::lock_guard<std::mutex> lock(mutex_);
  frames_.clear();
  total_pushed_ = 0;
  total_popped_ = 0;
  underflow_count_ = 0;
  primed_ = false;
  latency_ring_pos_ = 0;
  latency_ring_count_ = 0;
}

// =============================================================================
// Low-water mark + decode latency + refill rate
// =============================================================================

bool VideoLookaheadBuffer::IsBelowLowWater() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return primed_ && static_cast<int>(frames_.size()) < low_water_frames_;
}

void VideoLookaheadBuffer::SetAudioBoost(bool enable) {
  audio_boost_.store(enable, std::memory_order_release);
  if (enable) {
    // Wake fill thread on every enable call (not just transition) so it
    // re-evaluates the audio burst condition while audio is critically low.
    space_cv_.notify_all();
  }
}

// =============================================================================
// INV-AUDIO-PRIME-003: Bootstrap fill phase
// =============================================================================

void VideoLookaheadBuffer::EnterBootstrap(int bootstrap_target_frames,
                                           int bootstrap_cap_frames,
                                           int min_audio_ms,
                                           int64_t bootstrap_epoch_ms) {
  bootstrap_target_frames_ = bootstrap_target_frames;
  bootstrap_cap_frames_ = bootstrap_cap_frames;
  bootstrap_min_audio_ms_ = min_audio_ms;
  bootstrap_epoch_ms_ = bootstrap_epoch_ms;
  int vd = static_cast<int>(frames_.size());
  int a_ms = audio_buffer_ ? audio_buffer_->DepthMs() : -1;
  { std::ostringstream oss;
    oss << "[VideoBuffer:" << buffer_label_ << "] EnterBootstrap"
        << " bootstrap_epoch_ms=" << bootstrap_epoch_ms
        << " target=" << bootstrap_target_frames
        << " cap=" << bootstrap_cap_frames
        << " min_audio_ms=" << min_audio_ms
        << " video_depth=" << vd
        << " audio_depth_ms=" << a_ms;
    Logger::Info(oss.str()); }
  fill_phase_.store(static_cast<int>(FillPhase::kBootstrap),
                    std::memory_order_release);
  // Wake fill thread so it re-evaluates with bootstrap policy.
  space_cv_.notify_all();
}

void VideoLookaheadBuffer::EndBootstrap() {
  int vd = static_cast<int>(frames_.size());
  int a_ms = audio_buffer_ ? audio_buffer_->DepthMs() : -1;
  { std::ostringstream oss;
    oss << "[VideoBuffer:" << buffer_label_ << "] EndBootstrap"
        << " bootstrap_epoch_ms=" << bootstrap_epoch_ms_
        << " video_depth=" << vd
        << " audio_depth_ms=" << a_ms;
    Logger::Info(oss.str()); }
  fill_phase_.store(static_cast<int>(FillPhase::kSteady),
                    std::memory_order_release);
  // No wake needed — steady-state is more restrictive.
}

VideoLookaheadBuffer::FillPhase VideoLookaheadBuffer::GetFillPhase() const {
  return static_cast<FillPhase>(fill_phase_.load(std::memory_order_acquire));
}

int64_t VideoLookaheadBuffer::DecodeLatencyP95Us() const {
  std::lock_guard<std::mutex> lock(mutex_);
  if (latency_ring_count_ == 0) return 0;

  // Copy the valid portion and sort.
  std::array<int64_t, kLatencyRingSize> tmp{};
  int n = latency_ring_count_;
  for (int i = 0; i < n; i++) {
    tmp[i] = decode_latency_us_[i];
  }
  std::sort(tmp.begin(), tmp.begin() + n);

  // P95: index = floor(95/100 * (n-1))
  int idx = (95 * (n - 1)) / 100;
  return tmp[idx];
}

int64_t VideoLookaheadBuffer::DecodeLatencyMeanUs() const {
  std::lock_guard<std::mutex> lock(mutex_);
  if (latency_ring_count_ == 0) return 0;

  int64_t sum = 0;
  for (int i = 0; i < latency_ring_count_; i++) {
    sum += decode_latency_us_[i];
  }
  return sum / latency_ring_count_;
}

VideoLookaheadBuffer::RefillRate VideoLookaheadBuffer::GetRefillRate() const {
  std::lock_guard<std::mutex> lock(mutex_);
  auto elapsed = std::chrono::steady_clock::now() - fill_start_time_;
  int64_t elapsed_us = std::chrono::duration_cast<std::chrono::microseconds>(elapsed).count();
  return RefillRate{total_pushed_, elapsed_us > 0 ? elapsed_us : 0};
}

int64_t VideoLookaheadBuffer::DecodeContinuedForAudioWhileVideoFull() const {
  return decode_continued_for_audio_while_video_full_.load(std::memory_order_relaxed);
}

int64_t VideoLookaheadBuffer::DecodeParkedVideoFullAudioLow() const {
  return decode_parked_video_full_audio_low_.load(std::memory_order_relaxed);
}

}  // namespace retrovue::blockplan
