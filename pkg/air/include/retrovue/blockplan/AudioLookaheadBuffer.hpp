// Repository: Retrovue-playout
// Component: AudioLookaheadBuffer
// Purpose: Decouples audio consumption from production for broadcast-grade
//          continuous audio. The tick loop consumes fixed-size samples per
//          tick from this buffer, never decoding audio directly.
//          Underflow (buffer cannot satisfy a pop) is a hard fault.
// Contract Reference: INV-AUDIO-LOOKAHEAD-001
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_BLOCKPLAN_AUDIO_LOOKAHEAD_BUFFER_HPP_
#define RETROVUE_BLOCKPLAN_AUDIO_LOOKAHEAD_BUFFER_HPP_

#include <cstdint>
#include <deque>
#include <mutex>

#include "retrovue/buffer/FrameRingBuffer.h"

namespace retrovue::blockplan {

// AudioLookaheadBuffer accumulates decoded audio frames (house format:
// 48 kHz stereo S16) and dispenses exact per-tick sample counts.
//
// Producer side: Push() decoded AudioFrames as they arrive from the
// decode pipeline (side-effect of video demux).
//
// Consumer side: TryPopSamples() pulls exactly N samples for the
// current tick.  Handles partial-frame splitting transparently.
//
// Underflow (buffer cannot satisfy a pop) increments the underflow
// counter and returns false — callers treat this as a hard fault.
//
// Thread safety: all public methods are mutex-protected.
class AudioLookaheadBuffer {
 public:
  explicit AudioLookaheadBuffer(
      int target_depth_ms = 1000,
      int sample_rate = buffer::kHouseAudioSampleRate,
      int channels = buffer::kHouseAudioChannels,
      int low_water_ms = 333,
      int high_water_ms = 800);
  ~AudioLookaheadBuffer();

  AudioLookaheadBuffer(const AudioLookaheadBuffer&) = delete;
  AudioLookaheadBuffer& operator=(const AudioLookaheadBuffer&) = delete;

  // --- Producer ---

  // Push a decoded audio frame into the buffer.
  // If expected_generation != 0 and doesn't match current generation_,
  // the push is silently dropped (stale data from old fill thread).
  void Push(const buffer::AudioFrame& frame, uint64_t expected_generation = 0);
  void Push(buffer::AudioFrame&& frame, uint64_t expected_generation = 0);

  // Current generation counter (for fill thread capture).
  uint64_t CurrentGeneration() const;

  // --- Consumer ---

  // Pop exactly samples_needed samples into out.
  // Returns true on success, false on underflow (hard fault).
  // Non-blocking.
  bool TryPopSamples(int samples_needed, buffer::AudioFrame& out);

  // --- Observability ---

  // Current buffer depth in milliseconds.
  int DepthMs() const;

  // Current buffer depth in samples.
  int DepthSamples() const;

  // Total samples pushed since creation or last Reset().
  int64_t TotalSamplesPushed() const;

  // Total samples popped since creation or last Reset().
  int64_t TotalSamplesPopped() const;

  // Number of underflow events (TryPopSamples returned false).
  int64_t UnderflowCount() const;

  // True once at least one audio frame has been pushed.
  bool IsPrimed() const;

  // Target depth in milliseconds (configuration).
  int TargetDepthMs() const { return target_depth_ms_; }

  // Low-water mark in milliseconds (configuration).
  int LowWaterMs() const { return low_water_ms_; }

  // High-water mark in milliseconds (configuration).
  int HighWaterMs() const { return high_water_ms_; }

  // True when primed AND current depth_ms < low_water_ms.
  bool IsBelowLowWater() const;

  // True when current depth_ms >= high_water_ms.
  bool IsAboveHighWater() const;

  // --- Lifecycle ---

  // Clear buffer, partial state, and counters.
  void Reset();

 private:
  mutable std::mutex mutex_;

  // Queued complete frames.
  std::deque<buffer::AudioFrame> frames_;

  // Partial frame: remainder from a frame that was partially consumed.
  buffer::AudioFrame partial_;
  int partial_consumed_samples_ = 0;
  bool has_partial_ = false;

  // House format parameters.
  int sample_rate_;
  int channels_;
  int target_depth_ms_;
  int low_water_ms_;
  int high_water_ms_;

  // Monotonic generation counter — bumped on Reset().
  uint64_t generation_ = 0;

  // Running counters.
  int64_t total_samples_in_buffer_ = 0;
  int64_t total_samples_pushed_ = 0;
  int64_t total_samples_popped_ = 0;
  int64_t underflow_count_ = 0;
  bool primed_ = false;
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_AUDIO_LOOKAHEAD_BUFFER_HPP_
