// Repository: Retrovue-playout
// Component: AudioLookaheadBuffer
// Purpose: Broadcast-grade audio buffering for tick-aligned consumption.
// Contract Reference: INV-AUDIO-LOOKAHEAD-001
// Copyright (c) 2025 RetroVue

#include "retrovue/blockplan/AudioLookaheadBuffer.hpp"

#include <algorithm>
#include <chrono>
#include <cstring>
#include <iostream>
#include <sstream>

#include "retrovue/util/Logger.hpp"

namespace {
int64_t boot_mono_ms() {
  static auto t0 = std::chrono::steady_clock::now();
  return std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::steady_clock::now() - t0).count();
}
}  // namespace

namespace retrovue::blockplan {
using retrovue::util::Logger;

AudioLookaheadBuffer::AudioLookaheadBuffer(int target_depth_ms,
                                           int sample_rate,
                                           int channels,
                                           int low_water_ms,
                                           int high_water_ms)
    : sample_rate_(sample_rate),
      channels_(channels),
      target_depth_ms_(target_depth_ms),
      low_water_ms_(low_water_ms),
      high_water_ms_(high_water_ms) {}

AudioLookaheadBuffer::~AudioLookaheadBuffer() = default;

void AudioLookaheadBuffer::Push(const buffer::AudioFrame& frame,
                                uint64_t expected_generation) {
  if (frame.nb_samples <= 0) return;
  std::lock_guard<std::mutex> lock(mutex_);
  if (expected_generation != 0 && expected_generation != generation_) {
    { std::ostringstream oss;
      oss << "[AudioBuffer] PUSH_REJECTED_GEN T+" << boot_mono_ms()
          << "ms nb_samples=" << frame.nb_samples
          << " expected_gen=" << expected_generation
          << " current_gen=" << generation_;
      Logger::Warn(oss.str()); }
    return;
  }
  // PUSH_DIAG (copy overload) — shared counter with move overload.
  {
    // Use extern linkage via the move overload's static counter.
    const int16_t* s16 = reinterpret_cast<const int16_t*>(frame.data.data());
    int total_s16 = frame.nb_samples * frame.channels;
    int16_t p_min = 0, p_max = 0;
    for (int i = 0; i < total_s16; ++i) {
      if (s16[i] < p_min) p_min = s16[i];
      if (s16[i] > p_max) p_max = s16[i];
    }
    static int push_copy_diag_count = 0;
    if (push_copy_diag_count < 10) {
      std::ostringstream oss;
      oss << "[PUSH_DIAG_COPY] push#" << push_copy_diag_count
          << " nb_samples=" << frame.nb_samples
          << " s16_min=" << p_min << " s16_max=" << p_max;
      Logger::Info(oss.str());
      push_copy_diag_count++;
    }
  }

  total_samples_pushed_ += frame.nb_samples;
  total_samples_in_buffer_ += frame.nb_samples;
  primed_ = true;
  frames_.push_back(frame);
}

void AudioLookaheadBuffer::Push(buffer::AudioFrame&& frame,
                                uint64_t expected_generation) {
  if (frame.nb_samples <= 0) return;
  std::lock_guard<std::mutex> lock(mutex_);
  if (expected_generation != 0 && expected_generation != generation_) {
    { std::ostringstream oss;
      oss << "[AudioBuffer] PUSH_REJECTED_GEN T+" << boot_mono_ms()
          << "ms nb_samples=" << frame.nb_samples
          << " expected_gen=" << expected_generation
          << " current_gen=" << generation_;
      Logger::Warn(oss.str()); }
    return;
  }
  // PUSH_DIAG: Verify data integrity before storing in buffer.
  {
    static int push_diag_count = 0;
    if (push_diag_count < 30) {
      const int16_t* s16 = reinterpret_cast<const int16_t*>(frame.data.data());
      int total_s16 = frame.nb_samples * frame.channels;
      int expected_bytes = total_s16 * static_cast<int>(sizeof(int16_t));
      int16_t p_min = 0, p_max = 0;
      bool all_zero = true;
      for (int i = 0; i < total_s16; ++i) {
        if (s16[i] < p_min) p_min = s16[i];
        if (s16[i] > p_max) p_max = s16[i];
        if (s16[i] != 0) all_zero = false;
      }
      std::ostringstream oss;
      oss << "[PUSH_DIAG] push#" << push_diag_count
          << " nb_samples=" << frame.nb_samples
          << " data_bytes=" << frame.data.size()
          << " expected_bytes=" << expected_bytes
          << " s16_min=" << p_min << " s16_max=" << p_max
          << " all_zero=" << all_zero
          << " gen=" << generation_;
      Logger::Info(oss.str());
      push_diag_count++;
    }
  }

  total_samples_pushed_ += frame.nb_samples;
  total_samples_in_buffer_ += frame.nb_samples;
  primed_ = true;
  frames_.push_back(std::move(frame));
}

bool AudioLookaheadBuffer::TryPopSamples(int samples_needed,
                                          buffer::AudioFrame& out) {
  if (samples_needed <= 0) {
    out = buffer::AudioFrame{};
    out.sample_rate = sample_rate_;
    out.channels = channels_;
    out.nb_samples = 0;
    return true;
  }

  std::lock_guard<std::mutex> lock(mutex_);

  if (total_samples_in_buffer_ < samples_needed) {
    underflow_count_++;
    return false;
  }

  // Prepare output frame.
  const int bytes_per_sample = channels_ * static_cast<int>(sizeof(int16_t));
  out.sample_rate = sample_rate_;
  out.channels = channels_;
  out.nb_samples = samples_needed;
  out.data.resize(static_cast<size_t>(samples_needed * bytes_per_sample));

  int samples_remaining = samples_needed;
  int out_offset_bytes = 0;

  // 1) Drain from partial frame if present.
  if (has_partial_) {
    int avail = partial_.nb_samples - partial_consumed_samples_;
    int take = std::min(avail, samples_remaining);
    int src_offset = partial_consumed_samples_ * bytes_per_sample;

    std::memcpy(out.data.data() + out_offset_bytes,
                partial_.data.data() + src_offset,
                static_cast<size_t>(take * bytes_per_sample));

    out_offset_bytes += take * bytes_per_sample;
    samples_remaining -= take;
    partial_consumed_samples_ += take;

    if (partial_consumed_samples_ >= partial_.nb_samples) {
      has_partial_ = false;
      partial_ = buffer::AudioFrame{};
      partial_consumed_samples_ = 0;
    }
  }

  // 2) Drain from queued complete frames.
  while (samples_remaining > 0 && !frames_.empty()) {
    auto& front = frames_.front();
    int avail = front.nb_samples;
    int take = std::min(avail, samples_remaining);

    std::memcpy(out.data.data() + out_offset_bytes,
                front.data.data(),
                static_cast<size_t>(take * bytes_per_sample));

    out_offset_bytes += take * bytes_per_sample;
    samples_remaining -= take;

    if (take < avail) {
      // Partial consumption — save remainder.
      partial_ = std::move(front);
      partial_consumed_samples_ = take;
      has_partial_ = true;
      frames_.pop_front();
    } else {
      frames_.pop_front();
    }
  }

  total_samples_in_buffer_ -= samples_needed;
  total_samples_popped_ += samples_needed;

  // TRYPOP_OUTPUT_DIAG: Verify assembled output data integrity.
  {
    static int trypop_diag_count = 0;
    if (trypop_diag_count < 30) {
      const int16_t* s16 = reinterpret_cast<const int16_t*>(out.data.data());
      int total_s16 = out.nb_samples * out.channels;
      int16_t p_min = 0, p_max = 0;
      bool all_zero = true;
      for (int i = 0; i < total_s16; ++i) {
        if (s16[i] < p_min) p_min = s16[i];
        if (s16[i] > p_max) p_max = s16[i];
        if (s16[i] != 0) all_zero = false;
      }
      std::ostringstream oss;
      oss << "[TRYPOP_OUTPUT_DIAG] pop#" << trypop_diag_count
          << " nb_samples=" << out.nb_samples
          << " data_bytes=" << out.data.size()
          << " data_ptr=" << static_cast<const void*>(out.data.data())
          << " s16_min=" << p_min << " s16_max=" << p_max
          << " all_zero=" << all_zero
          << " first4=" << (total_s16 >= 4 ? s16[0] : 0) << "," << (total_s16 >= 4 ? s16[1] : 0)
          << "," << (total_s16 >= 4 ? s16[2] : 0) << "," << (total_s16 >= 4 ? s16[3] : 0)
          << " frames_remain=" << frames_.size()
          << " has_partial=" << has_partial_;
      Logger::Info(oss.str());
      trypop_diag_count++;
    }
  }

  return true;
}

int AudioLookaheadBuffer::DepthMs() const {
  std::lock_guard<std::mutex> lock(mutex_);
  if (sample_rate_ <= 0) return 0;
  int depth_ms = static_cast<int>((total_samples_in_buffer_ * 1000) / sample_rate_);
  // Temporary debug: once per second — total_samples_in_buffer_, depth_ms.
  {
    static auto last_depth_log = std::chrono::steady_clock::now();
    auto now = std::chrono::steady_clock::now();
    if (std::chrono::duration_cast<std::chrono::milliseconds>(now - last_depth_log).count() >= 1000) {
      last_depth_log = now;
      std::ostringstream oss;
      oss << "[AudioBuffer] DBG_AUDIO_DEPTH"
          << " total_samples_in_buffer=" << total_samples_in_buffer_
          << " depth_ms=" << depth_ms;
      Logger::Debug(oss.str());
    }
  }
  return depth_ms;
}

int AudioLookaheadBuffer::DepthSamples() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return static_cast<int>(total_samples_in_buffer_);
}

int64_t AudioLookaheadBuffer::TotalSamplesPushed() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return total_samples_pushed_;
}

int64_t AudioLookaheadBuffer::TotalSamplesPopped() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return total_samples_popped_;
}

int64_t AudioLookaheadBuffer::UnderflowCount() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return underflow_count_;
}

bool AudioLookaheadBuffer::IsPrimed() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return primed_;
}

void AudioLookaheadBuffer::Reset() {
  std::lock_guard<std::mutex> lock(mutex_);
  int old_depth_ms = (sample_rate_ > 0)
      ? static_cast<int>((total_samples_in_buffer_ * 1000) / sample_rate_)
      : 0;
  generation_++;  // Invalidate any in-flight Push from old fill thread
  frames_.clear();
  partial_ = buffer::AudioFrame{};
  partial_consumed_samples_ = 0;
  has_partial_ = false;
  total_samples_in_buffer_ = 0;
  total_samples_pushed_ = 0;
  total_samples_popped_ = 0;
  underflow_count_ = 0;
  primed_ = false;
  { std::ostringstream oss;
    oss << "[AudioBuffer] RESET T+" << boot_mono_ms()
        << "ms old_depth_ms=" << old_depth_ms
        << " new_gen=" << generation_;
    Logger::Info(oss.str()); }
}

uint64_t AudioLookaheadBuffer::CurrentGeneration() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return generation_;
}

bool AudioLookaheadBuffer::IsBelowLowWater() const {
  std::lock_guard<std::mutex> lock(mutex_);
  if (!primed_ || sample_rate_ <= 0) return false;
  int depth_ms = static_cast<int>((total_samples_in_buffer_ * 1000) / sample_rate_);
  return depth_ms < low_water_ms_;
}

bool AudioLookaheadBuffer::IsAboveHighWater() const {
  std::lock_guard<std::mutex> lock(mutex_);
  if (sample_rate_ <= 0) return false;
  int depth_ms = static_cast<int>((total_samples_in_buffer_ * 1000) / sample_rate_);
  return depth_ms >= high_water_ms_;
}

}  // namespace retrovue::blockplan
