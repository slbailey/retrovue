// Repository: Retrovue-playout
// Component: VideoLookaheadBuffer
// Purpose: Non-blocking video frame buffer with background fill thread.
// Contract Reference: INV-VIDEO-LOOKAHEAD-001
// Copyright (c) 2025 RetroVue

#include "retrovue/blockplan/VideoLookaheadBuffer.hpp"

#include <algorithm>
#include <chrono>
#include <iostream>
#include <numeric>
#include <utility>

#include "retrovue/blockplan/AudioLookaheadBuffer.hpp"
#include "retrovue/blockplan/ITickProducer.hpp"
#include "retrovue/blockplan/TickProducer.hpp"

namespace retrovue::blockplan {

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
  producer_ = producer;
  audio_buffer_ = audio_buffer;
  stop_signal_ = stop_signal;
  input_fps_ = input_fps;
  output_fps_ = output_fps;
  fill_start_time_ = std::chrono::steady_clock::now();

  // INV-BLOCK-PRIME-002: Consume primed frame synchronously (non-blocking).
  // This guarantees the buffer has at least one frame immediately after
  // StartFilling returns, enabling the fence-tick to pop without delay.
  // INV-AUDIO-PRIME-001: When primed via PrimeFirstTick, the primed frame's
  // audio vector contains accumulated audio from multiple decodes (covering
  // the audio prime threshold).  All audio is pushed to AudioLookaheadBuffer
  // here in one call — zero decode I/O on the tick thread.
  // Buffered video frames from PrimeFirstTick are returned by TryGetFrame
  // in the fill thread (they sit in TickProducer::buffered_frames_).
  if (producer_->HasPrimedFrame()) {
    auto fd = producer_->TryGetFrame();
    if (fd) {
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

      std::lock_guard<std::mutex> lock(mutex_);
      frames_.push_back(std::move(vf));
      total_pushed_++;
      primed_ = true;
    }
  }

  // Log cadence detection (matches old InitCadence diagnostic).
  std::cout << "[VideoLookaheadBuffer] FPS_CADENCE: input_fps=" << input_fps_
            << " output_fps=" << output_fps_;
  if (input_fps_ > 0.0 && input_fps_ < output_fps_ * 0.98) {
    std::cout << " cadence=ACTIVE ratio=" << (input_fps_ / output_fps_);
  } else {
    std::cout << " cadence=OFF";
  }
  std::cout << std::endl;

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
  // Capture generation at thread start; any mismatch means fence happened.
  uint64_t my_gen;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    my_gen = fill_generation_;
  }

  // Capture audio generation for generation-gated audio pushes.
  uint64_t my_audio_gen = 0;
  if (audio_buffer_) {
    my_audio_gen = audio_buffer_->CurrentGeneration();
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

  bool content_exhausted = false;

  while (!fill_stop_.load(std::memory_order_acquire) &&
         !(stop_signal_ && stop_signal_->load(std::memory_order_acquire))) {

    // Wait for space in buffer.
    {
      std::unique_lock<std::mutex> lock(mutex_);
      space_cv_.wait(lock, [this] {
        return static_cast<int>(frames_.size()) < target_depth_frames_ ||
               fill_stop_.load(std::memory_order_acquire) ||
               (stop_signal_ && stop_signal_->load(std::memory_order_acquire));
      });
      if (fill_stop_.load(std::memory_order_acquire) ||
          (stop_signal_ && stop_signal_->load(std::memory_order_acquire))) {
        break;
      }
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

    if (should_decode && !content_exhausted) {
      auto decode_start = std::chrono::steady_clock::now();
      auto fd = producer_->TryGetFrame();
      auto decode_end = std::chrono::steady_clock::now();
      if (fd) {
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
        if (fill_stop_.load(std::memory_order_acquire)) break;

        // Push decoded audio to AudioLookaheadBuffer (generation-gated).
        if (audio_buffer_) {
          for (auto& af : fd->audio) {
            audio_buffer_->Push(std::move(af), my_audio_gen);
          }
        }
      } else if (have_last_decoded) {
        // Content exhausted — hold last frame to prevent underflow.
        content_exhausted = true;
        vf.video = last_decoded;
        vf.was_decoded = false;
      } else {
        // No frame ever decoded (decoder failure on first frame).
        // Exit fill loop; tick loop will remain in pad mode.
        break;
      }
    } else if (have_last_decoded) {
      // Cadence repeat (or content exhausted hold-last).
      // No audio produced — content stream has no extra audio at higher rate.
      vf.video = last_decoded;
      vf.was_decoded = false;
    } else {
      // No frame available yet — shouldn't happen (first tick always decodes
      // unless content_exhausted on first frame, handled above).
      continue;
    }

    // Bail out before pushing if stop was requested or generation changed.
    if (fill_stop_.load(std::memory_order_acquire)) break;

    // Push to buffer — generation gate prevents stale-frame bleed.
    {
      std::lock_guard<std::mutex> lock(mutex_);
      if (fill_generation_ != my_gen) break;  // Fence happened during decode
      frames_.push_back(std::move(vf));
      total_pushed_++;
      primed_ = true;
    }
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
