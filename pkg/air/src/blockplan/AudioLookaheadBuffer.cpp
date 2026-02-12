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

namespace {
int64_t boot_mono_ms() {
  static auto t0 = std::chrono::steady_clock::now();
  return std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::steady_clock::now() - t0).count();
}
}  // namespace

namespace retrovue::blockplan {

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
    std::cout << "[AudioBuffer] PUSH_REJECTED_GEN T+" << boot_mono_ms()
              << "ms nb_samples=" << frame.nb_samples
              << " expected_gen=" << expected_generation
              << " current_gen=" << generation_ << std::endl;
    return;
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
    std::cout << "[AudioBuffer] PUSH_REJECTED_GEN T+" << boot_mono_ms()
              << "ms nb_samples=" << frame.nb_samples
              << " expected_gen=" << expected_generation
              << " current_gen=" << generation_ << std::endl;
    return;
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
  return true;
}

int AudioLookaheadBuffer::DepthMs() const {
  std::lock_guard<std::mutex> lock(mutex_);
  if (sample_rate_ <= 0) return 0;
  return static_cast<int>((total_samples_in_buffer_ * 1000) / sample_rate_);
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
  std::cout << "[AudioBuffer] RESET T+" << boot_mono_ms()
            << "ms old_depth_ms=" << old_depth_ms
            << " new_gen=" << generation_ << std::endl;
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
