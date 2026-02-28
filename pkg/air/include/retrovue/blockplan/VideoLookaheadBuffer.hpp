// Repository: Retrovue-playout
// Component: VideoLookaheadBuffer
// Purpose: Decouples video consumption from decode for non-blocking tick loop.
//          The tick loop consumes pre-decoded video frames from this buffer;
//          a background fill thread decodes ahead and resolves cadence.
//          Underflow (buffer cannot satisfy a pop) is a hard fault.
// Contract Reference: INV-VIDEO-LOOKAHEAD-001
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_BLOCKPLAN_VIDEO_LOOKAHEAD_BUFFER_HPP_
#define RETROVUE_BLOCKPLAN_VIDEO_LOOKAHEAD_BUFFER_HPP_

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <mutex>
#include <string>
#include <thread>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"

namespace retrovue::blockplan {

class AudioLookaheadBuffer;
class ITickProducer;

// VideoBufferFrame carries a decoded (or repeated) video frame plus
// metadata needed by the tick loop for fingerprinting and accumulation.
struct VideoBufferFrame {
  buffer::Frame video;
  std::string asset_uri;
  int64_t block_ct_ms = -1;  // CT at decode time; -1 for repeats
  bool was_decoded = false;   // true = real decode, false = cadence repeat or hold-last
  int32_t segment_origin_id = -1;  // INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001: segment that produced this frame
};

// VideoLookaheadBuffer accumulates decoded video frames from a background
// fill thread and dispenses them one per tick to the main loop.
//
// Fill thread (producer): calls TryGetFrame() on an ITickProducer, resolves
// cadence (decode vs repeat), and pushes audio to AudioLookaheadBuffer.
// Bounded: blocks when buffer reaches target depth.
//
// Tick loop (consumer): TryPopFrame() pulls one frame per tick.
// Underflow (empty buffer after priming) increments the underflow counter
// and returns false — callers treat this as a hard fault.
//
// Lifecycle:
//   1. Construct with target depth
//   2. StartFilling() — synchronously consumes primed frame (if any),
//      then spawns background fill thread
//   3. TryPopFrame() per tick
//   4. StopFilling() — joins fill thread, optionally flushes buffer
//   5. Repeat 2-4 on block transitions
//
// Thread safety: all public methods are safe to call from any thread.
class VideoLookaheadBuffer {
 public:
  explicit VideoLookaheadBuffer(int target_depth_frames = 15,
                                int low_water_frames = 5);
  ~VideoLookaheadBuffer();

  VideoLookaheadBuffer(const VideoLookaheadBuffer&) = delete;
  VideoLookaheadBuffer& operator=(const VideoLookaheadBuffer&) = delete;

  // --- Fill Thread Lifecycle ---

  // Start the background fill loop.
  // producer: ITickProducer to decode from (must be kReady).
  // audio_buffer: decoded audio is pushed here (may be nullptr to skip).
  // input_fps: detected input FPS from decoder (for cadence computation).
  // output_fps: session output FPS.
  // stop_signal: external stop request flag (session stop).
  //
  // If the producer has a primed frame, it is consumed synchronously
  // (non-blocking) and pushed to the buffer before the fill thread starts.
  // INV-AUDIO-PRIME-001: When the primed frame was created by PrimeFirstTick,
  // its audio vector contains accumulated audio covering the prime threshold.
  // All accumulated audio is pushed to audio_buffer in one call here.
  // Buffered video frames (from PrimeFirstTick) are returned by subsequent
  // TryGetFrame calls in the fill thread — no special handling needed.
  void StartFilling(ITickProducer* producer,
                    AudioLookaheadBuffer* audio_buffer,
                    RationalFps input_fps, RationalFps output_fps,
                    std::atomic<bool>* stop_signal);
  // Stop the fill loop and join the thread.
  // If flush=true, clears all buffered frames and resets IsPrimed().
  void StopFilling(bool flush = false);

  // Async stop: signal fill thread to exit, optionally flush buffer,
  // extract thread handle for deferred join.  Does NOT join.
  // Increments fill_generation_ so any late push from the old thread is rejected.
  struct DetachedFill {
    std::thread thread;  // Must be joined before producer is destroyed
  };
  DetachedFill StopFillingAsync(bool flush = false);

  // True while the fill thread is running.
  bool IsFilling() const;

  // --- Consumer ---

  // Pop one video frame for the tick loop. Non-blocking.
  // Returns false on underflow (hard fault).
  bool TryPopFrame(VideoBufferFrame& out);

  // --- Observability ---

  // Current buffer depth in frames (container size). INV-VIDEO-BOUNDED: must be <= HardCapFrames().
  int DepthFrames() const;

  // Hard cap in frames. Invariant: frames_.size() <= HardCapFrames() (enforced on push).
  int HardCapFrames() const { return hard_cap_frames_; }

  // Frames dropped because container would exceed hard cap (enforced on push).
  int64_t DropsTotal() const;

  // Number of underflow events (TryPopFrame returned false).
  int64_t UnderflowCount() const;

  // Total frames pushed since creation or last Reset().
  int64_t TotalFramesPushed() const;

  // Total frames popped since creation or last Reset().
  int64_t TotalFramesPopped() const;

  // True once at least one frame has been pushed.
  bool IsPrimed() const;

  // Target buffer depth in frames (configuration).
  int TargetDepthFrames() const { return target_depth_frames_; }

  // Low-water mark in frames (configuration).
  int LowWaterFrames() const { return low_water_frames_; }

  // INV-BUFFER-HYSTERESIS-001: Effective high-water mark (for diagnostics).
  // Returns the current high-water threshold accounting for audio_boost_.
  int HighWaterFrames() const {
    return audio_boost_.load(std::memory_order_relaxed)
        ? target_depth_frames_ * 4
        : target_depth_frames_ * 2;
  }

  // INV-BUFFER-HYSTERESIS-001: Current fill state (for diagnostics).
  bool IsSteadyFilling() const {
    return steady_filling_.load(std::memory_order_relaxed);
  }

  // True when primed AND current depth < low-water mark.
  bool IsBelowLowWater() const;

  // INV-AUDIO-BUFFER-POLICY-001: Audio boost mode.
  // When enabled, the fill thread's effective target depth doubles,
  // allowing more decodes (and thus more audio) before parking.
  // Called by PipelineManager when audio drops below LOW_WATER (enable)
  // or rises above HIGH_WATER (disable).
  void SetAudioBoost(bool enable);

  // INV-AUDIO-PREROLL-ISOLATION-001: Buffer context label for log clarity.
  // Set before StartFilling to identify LIVE vs PREVIEW vs SEGMENT_PREROLL.
  void SetBufferLabel(const char* label) { buffer_label_ = label; }
  const std::string& BufferLabel() const { return buffer_label_; }

  // INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001: Segment origin stamped on every
  // frame pushed by the fill thread.  Set before StartFilling.
  void SetSegmentOriginId(int32_t id) { segment_origin_id_ = id; }
  int32_t SegmentOriginId() const { return segment_origin_id_; }

  // --- Bootstrap Phase (INV-AUDIO-PRIME-003) ---

  // Fill-phase concept for session bootstrap.
  // BOOTSTRAP: fill thread parks only when audio depth >= min_audio_ms
  //            AND video depth >= bootstrap_target, OR video >= cap.
  // STEADY:    normal steady-state policy (video depth only).
  enum class FillPhase { kBootstrap, kSteady };

  // Enter bootstrap phase.  Must be called AFTER StartFilling().
  // bootstrap_target_frames: computed target for bootstrap
  //   (typically max(target, ceil(min_audio_ms * input_fps / 1000) + margin))
  // bootstrap_cap_frames: hard upper bound on video depth during bootstrap.
  // min_audio_ms: audio depth threshold that ends bootstrap parking.
  void EnterBootstrap(int bootstrap_target_frames,
                      int bootstrap_cap_frames,
                      int min_audio_ms,
                      int64_t bootstrap_epoch_ms);

  // Exit bootstrap phase, restoring steady-state fill policy.
  void EndBootstrap();

  // Current fill phase (observable).
  FillPhase GetFillPhase() const;

  // P95 decode latency in microseconds (from last kLatencyRingSize decodes).
  // Returns 0 when no decodes have occurred.
  int64_t DecodeLatencyP95Us() const;

  // Mean decode latency in microseconds (from last kLatencyRingSize decodes).
  // Returns 0 when no decodes have occurred.
  int64_t DecodeLatencyMeanUs() const;

  // Fill thread refill rate: frames pushed and elapsed us since StartFilling.
  // INV-FPS-RATIONAL-001: Caller may display as (frames * 1000000 / elapsed_us) for telemetry.
  struct RefillRate { int64_t frames = 0; int64_t elapsed_us = 0; };
  RefillRate GetRefillRate() const;

  // INV-AUDIO-LIVENESS-001 diagnostics: audio-first decode under backpressure (counters only).
  int64_t DecodeContinuedForAudioWhileVideoFull() const;
  int64_t DecodeParkedVideoFullAudioLow() const;

  // --- Lifecycle ---

  // Stop fill thread (if running), clear buffer and counters.
  void Reset();

 private:
  void FillLoop();

  int target_depth_frames_;
  int low_water_frames_;
  std::atomic<bool> audio_boost_{false};

  // INV-BUFFER-HYSTERESIS-001: Dual-threshold steady-state fill control.
  // true  = fill thread is actively decoding (depth <= low water).
  // false = fill thread is parked (depth >= high water).
  // Eliminates single-frame oscillation at target boundary.
  std::atomic<bool> steady_filling_{true};

  // INV-AUDIO-PREROLL-ISOLATION-001: Buffer context label for diagnostics.
  std::string buffer_label_{"UNKNOWN"};

  // INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001: Segment origin for frame stamping.
  int32_t segment_origin_id_ = -1;

  // INV-AUDIO-PRIME-003: Bootstrap fill phase state.
  std::atomic<int> fill_phase_{static_cast<int>(FillPhase::kSteady)};
  int bootstrap_target_frames_ = 0;
  int bootstrap_cap_frames_ = 60;
  int bootstrap_min_audio_ms_ = 500;
  int64_t bootstrap_epoch_ms_ = 0;

  // INV-TICK-GUARANTEED-OUTPUT: Audio burst-fill threshold.
  // When audio_buffer_->DepthMs() < this, the fill thread proceeds past
  // the normal video target (up to 4× cap) to rebuild audio headroom.
  // Default 200ms — enough to bridge a segment transition without silence.
  int audio_burst_threshold_ms_ = 200;

  static constexpr int kLatencyRingSize = 128;

  mutable std::mutex mutex_;
  std::deque<VideoBufferFrame> frames_;
  std::condition_variable space_cv_;  // fill thread waits when buffer full

  std::thread fill_thread_;
  std::atomic<bool> fill_stop_{false};
  bool fill_running_ = false;
  std::atomic<uint64_t> fill_generation_{0};  // Monotonic; bumped at StopFillingAsync/StartFilling (atomic so tick path can bump without taking mutex_)

  // Fill thread parameters (set by StartFilling, read by FillLoop).
  ITickProducer* producer_ = nullptr;
  AudioLookaheadBuffer* audio_buffer_ = nullptr;
  std::atomic<bool>* stop_signal_ = nullptr;
  RationalFps input_fps_ = FPS_30;
  RationalFps output_fps_ = FPS_30;
  ResampleMode resample_mode_ = ResampleMode::OFF;
  int64_t drop_step_ = 1;

  // Metrics (under mutex_).
  int64_t total_pushed_ = 0;
  int64_t total_popped_ = 0;
  int64_t drops_total_ = 0;  // INV-VIDEO-BOUNDED: dropped to enforce hard cap
  int64_t underflow_count_ = 0;
  bool primed_ = false;

  // INV-VIDEO-BOUNDED: Strict upper bound on frames_.size(). Enforced on every push.
  static int ComputeHardCap(int target_depth_frames) {
    const int from_target = (target_depth_frames > 0) ? target_depth_frames * 4 : 60;
    return std::max(from_target, 200);
  }
  int hard_cap_frames_;

  // Decode latency ring buffer (under mutex_).
  std::array<int64_t, kLatencyRingSize> decode_latency_us_{};
  int latency_ring_pos_ = 0;
  int latency_ring_count_ = 0;

  // Fill start time for refill rate computation.
  std::chrono::steady_clock::time_point fill_start_time_{};

  // Per-instance MEM_WATCHDOG rate-limit: 1Hz or when depth/state changes significantly.
  mutable std::chrono::steady_clock::time_point last_fill_log_{};
  mutable int last_watchdog_depth_{-1};
  mutable std::string last_watchdog_state_{};

  // INV-AUDIO-LIVENESS-001 diagnostics (not invariants): audio-first decode under backpressure.
  std::atomic<int64_t> decode_continued_for_audio_while_video_full_{0};
  std::atomic<int64_t> decode_parked_video_full_audio_low_{0};
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_VIDEO_LOOKAHEAD_BUFFER_HPP_
