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
    double input_fps,
    double output_fps,
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
      VideoBufferFrame vf;
      vf.video = fd->video;          // copy for potential cache use
      vf.asset_uri = std::move(fd->asset_uri);
      vf.block_ct_ms = fd->block_ct_ms;
      vf.was_decoded = true;

      // Push decoded audio to AudioLookaheadBuffer.
      { std::ostringstream oss;
        oss << "[VideoBuffer:" << buffer_label_ << "] StartFilling:"
            << " primed_frame audio_count=" << fd->audio.size();
        Logger::Info(oss.str()); }
      if (audio_buffer_) {
        for (auto& af : fd->audio) {
          audio_buffer_->Push(std::move(af));
        }
        { std::ostringstream oss;
          oss << "[VideoBuffer:" << buffer_label_ << "] StartFilling:"
              << " audio_depth_ms=" << audio_buffer_->DepthMs();
          Logger::Info(oss.str()); }
      }

      std::lock_guard<std::mutex> lock(mutex_);
      frames_.push_back(std::move(vf));
      total_pushed_++;
      primed_ = true;
    }
  }

  // Log cadence detection (matches old InitCadence diagnostic).
  { std::ostringstream oss;
    oss << "[VideoBuffer:" << buffer_label_ << "] FPS_CADENCE:"
        << " input_fps=" << input_fps_
        << " output_fps=" << output_fps_;
    if (input_fps_ > 0.0 && input_fps_ < output_fps_ * 0.98) {
      oss << " cadence=ACTIVE ratio=" << (input_fps_ / output_fps_);
    } else {
      oss << " cadence=OFF";
    }
    Logger::Info(oss.str()); }

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

  // --- Cadence setup (same logic as old PipelineManager::InitCadence) ---
  bool cadence_active = false;
  double cadence_ratio = 0.0;
  double decode_budget = 0.0;

  // Activate cadence only when input is meaningfully slower than output.
  // Tolerance: 2% — avoids activation for 29.97 vs 30.
  if (input_fps_ > 0.0 && input_fps_ < output_fps_ * 0.98) {
    cadence_active = true;
    cadence_ratio = input_fps_ / output_fps_;
    decode_budget = 1.0;  // guarantees first tick decodes
  }

  // Pre-build silence template for hold-last / cadence-repeat ticks.
  // One tick demands at most ceil(48000 / output_fps) samples.
  buffer::AudioFrame silence_template;
  int silence_samples_per_frame = 0;
  if (audio_buffer && output_fps_ > 0.0) {
    silence_samples_per_frame = static_cast<int>(
        std::ceil(static_cast<double>(buffer::kHouseAudioSampleRate) / output_fps_));
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
        << " input_fps=" << input_fps_
        << " output_fps=" << output_fps_
        << " cadence_active=" << cadence_active
        << " my_audio_gen=" << my_audio_gen
        << " have_last_decoded=" << have_last_decoded;
    Logger::Info(oss.str()); }

  const char* exit_reason = "unknown";
  try {
  if (!producer) {
    exit_reason = "producer_null";
  }
  while (producer &&
         !fill_stop_.load(std::memory_order_acquire) &&
         !(stop_signal && stop_signal->load(std::memory_order_acquire))) {

    // INV-BUFFER-HYSTERESIS-001: Two-path depth control.
    //
    // FILLING path (steady_filling_ == true): The fill thread must decode
    // as fast as possible to build headroom.  Acquiring mutex_ per-frame
    // to evaluate the condvar predicate contends with TryPopFrame on every
    // tick, throttling the fill thread to ~consumption rate and preventing
    // depth from climbing.  Instead, read depth under a brief lock, check
    // the high-water cap, and proceed without parking.
    //
    // PARKED path (steady_filling_ == false): Block on space_cv_ until a
    // pop drops depth to low_water, or a boost/burst condition fires.
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
    // After a segment transition, audio buffer may be critically low while
    // video buffer is full (hold-last frames).  Allow decoding even when
    // video exceeds its normal target so audio can rebuild headroom.
    // Bounded by 4× video target to prevent unbounded growth.
    {
      bool is_bootstrap = fill_phase_.load(std::memory_order_relaxed) ==
          static_cast<int>(FillPhase::kBootstrap);
      bool filling_now = steady_filling_.load(std::memory_order_relaxed);
      bool skip_wait = false;

      if (!is_bootstrap && filling_now) {
        // FILLING path: brief lock for depth check + high-water cap.
        // No condvar park — decode at full speed.
        int depth;
        {
          std::lock_guard<std::mutex> lock(mutex_);
          depth = static_cast<int>(frames_.size());
        }
        int high_water = audio_boost_.load(std::memory_order_relaxed)
            ? target_depth_frames_ * 4
            : target_depth_frames_ * 2;
        if (depth >= high_water) {
          // Reached high water — transition to PARKED.
          steady_filling_.store(false, std::memory_order_relaxed);
          // Fall through to the condvar path below so we park properly.
        } else {
          // Below high water — skip condvar, proceed to decode.
          skip_wait = true;
        }
      }

      if (!skip_wait) {
        // PARKED path (or bootstrap): block on condvar.
        {
          std::unique_lock<std::mutex> lock(mutex_);
          space_cv_.wait(lock, [this, stop_signal, audio_buffer] {
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

            // STEADY phase (PARKED): wait until low water or burst trigger.
            if (depth <= target_depth_frames_) {
              steady_filling_.store(true, std::memory_order_relaxed);
              return true;
            }

            // Audio burst: proceed past high water when audio is critically low.
            if (audio_buffer && audio_buffer->DepthMs() < audio_burst_threshold_ms_) {
              int burst_cap = target_depth_frames_ * 4;
              return depth < burst_cap;
            }
            return false;
          });
        }
        if (fill_stop_.load(std::memory_order_acquire) ||
            (stop_signal && stop_signal->load(std::memory_order_acquire))) {
          exit_reason = fill_stop_.load(std::memory_order_acquire)
              ? "fill_stop" : "session_stop";
          break;
        }
        // BOOTSTRAP TRACE: log fill decisions during bootstrap phase only
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
      }
    }

    // INV-BUFFER-HYSTERESIS-001: Re-check stop after hysteresis decision.
    if (fill_stop_.load(std::memory_order_acquire) ||
        (stop_signal && stop_signal->load(std::memory_order_acquire))) {
      exit_reason = fill_stop_.load(std::memory_order_acquire)
          ? "fill_stop" : "session_stop";
      break;
    }

    // --- Cadence gate ---
    // ratio = input_fps / output_fps (e.g. 0.7992 for 23.976->30).
    // decode_budget accumulates ratio each frame; decode when >= 1.0.
    // Produces deterministic 4:1 dup pattern for 23.976->30.
    bool should_decode = true;
    if (cadence_active) {
      decode_budget += cadence_ratio;
      if (decode_budget >= 1.0) {
        decode_budget -= 1.0;
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

    // Push to buffer — generation gate prevents stale-frame bleed.
    {
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
      Logger::Info(oss.str()); }
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

  // P95: index = floor(0.95 * (n-1))
  int idx = static_cast<int>(0.95 * (n - 1));
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

double VideoLookaheadBuffer::RefillRateFps() const {
  std::lock_guard<std::mutex> lock(mutex_);
  if (total_pushed_ == 0) return 0.0;

  auto elapsed = std::chrono::steady_clock::now() - fill_start_time_;
  auto elapsed_us = std::chrono::duration_cast<std::chrono::microseconds>(elapsed).count();
  if (elapsed_us <= 0) return 0.0;

  return static_cast<double>(total_pushed_) * 1'000'000.0 / static_cast<double>(elapsed_us);
}

}  // namespace retrovue::blockplan
