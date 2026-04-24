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
#include <optional>
#include <string>
#include <thread>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/FrameIndexedVideoStore.hpp"
#include "retrovue/blockplan/VideoBufferFrame.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"

namespace retrovue::blockplan {

// INV-AV-FILL-INTERLOCK-001: Explicit reason codes for audio suppression.
// Legitimate reasons to suppress audio while video advances LatestIndex:
//  1) generation mismatch (stale fill thread after fence/swap), or
//  2) explicit A/V lead clamp to keep bootstrap/fill phase bounded.
enum class AudioSuppressionReason {
  kNone,               // audio was pushed — no suppression
  kGenerationMismatch, // stale fill thread; audio buffer swapped to new generation
  kAvLeadClamp,        // audio suppressed to enforce bounded A/V lead during fill/bootstrap
};

// INV-BUFFER-LIFECYCLE-001: Unified buffer lifecycle state.
// All VideoLookaheadBuffer instances (PREVIEW, SEGMENT_B, LIVE) use this model.
// Transitions: FILLING → PRIMED → STOPPED (terminal once STOPPED via StopFilling).
// PRIMED: seam-readiness threshold met; buffer awaits StopFilling() from caller.
// LIVE buffers do not configure min_audio_prime_ms and remain in FILLING.
enum class BufferFillState {
  FILLING,  // fill thread running, decoding ahead
  PRIMED,   // both video and audio thresholds met; ready for seam-take
  STOPPED,  // terminal; fill thread joined; no further decode permitted
};

class AudioLookaheadBuffer;
class ITickProducer;

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
                                int low_water_frames = 5,
                                int lookahead_target = -1);
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
  BufferFillState FillState() const;
  // Set minimum audio depth (ms) required for PRIMED transition.
  // Default -1 = no auto-PRIMED transition (LIVE buffer). Set to
  // kMinAudioPrimeMs for PREVIEW and SEGMENT_B before StartFilling().
  void SetMinAudioPrimeMs(int ms);

  // --- Consumer ---

  // Pop one video frame for the tick loop. Non-blocking.
  // Returns false on underflow (hard fault).
  bool TryPopFrame(VideoBufferFrame& out);

  // Peek front without popping. Returns false if empty. For consumption-time alignment only.
  bool TryPeekFront(VideoBufferFrame& out) const;
  // Discard front frame (pop without returning). No-op if empty. Wakes fill thread.
  void DiscardFront();

  // --- FIVS: Indexed Access (Frame-Indexed Video Store) ---

  // Retrieve frame by source_frame_index. Returns nullopt if not present.
  // Thread-safe (acquires mutex_, copies frame under lock). FIVS-ALIGN: never returns frame with index > requested.
  std::optional<VideoBufferFrame> GetByIndex(int64_t source_frame_index);

  // Evict all frames with index < min_index from the indexed store.
  // Thread-safe (acquires mutex_). FIVS-EVICTION-SAFETY.
  void EvictBelow(int64_t min_index);

  // Current indexed store depth (number of frames in FIVS).
  size_t IndexedStoreSize() const;

  // INV-FIVS-LOOKAHEAD-001: Update the consumer's current timeline position.
  // Called by tick loop after computing selected_src_this_tick.
  // The fill thread uses this to compute lookahead = LatestIndex - selected_src.
  void UpdateConsumerPosition(int64_t selected_src);

  // Current lookahead target (frames ahead of consumer). For diagnostics.
  int LookaheadTarget() const { return lookahead_target_; }
  // --- Observability ---

  // Current buffer depth in frames (container size). INV-VIDEO-BOUNDED: must be <= HardCapFrames().
  int DepthFrames() const;

  // Hard cap in frames. Invariant: frames_.size() <= HardCapFrames() (enforced on push).
  int HardCapFrames() const { return hard_cap_frames_; }

  // Frames dropped because container would exceed hard cap (enforced on push).
  int64_t DropsTotal() const;

  // Number of underflow events (TryPopFrame returned false).
  int64_t UnderflowCount() const;
  // INV-AV-FILL-INTERLOCK-001: non-zero means audio was dropped without generation mismatch.
  int64_t AudioFramesSuppressedNonGeneration() const {
    return audio_frames_suppressed_non_generation_.load(std::memory_order_relaxed);
  }

  // INV-FILL-AV-LEAD-CLAMP-001 — events where audio was not pushed due to kAvLeadClamp.
  int64_t AvLeadClampEventCount() const {
    return av_lead_clamp_events_.load(std::memory_order_relaxed);
  }

  // INV-FILL-AV-LEAD-CLAMP-001 / INV-BOOTSTRAP-AV-PHASE-001 — must match PipelineManagerOptions.av_phase_tolerance_ms.
  void SetAvPhaseToleranceMs(int ms);
  int AvPhaseToleranceMs() const { return av_phase_tolerance_ms_; }

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
  // Post-handoff transition drain mode: when enabled, bootstrap phase becomes
  // drain-first and suppresses decode admission until disabled.
  void SetTransitionDrainOnly(bool enable);
  bool IsTransitionDrainOnly() const {
    return transition_drain_only_.load(std::memory_order_acquire);
  }

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

  // INV-FIVS-LOOKAHEAD-001: Compute lookahead (frames ahead of consumer).
  // Returns -1 when consumer position is unknown (pre-first-tick).
  // Must be called with mutex_ held (reads frame_store_).
  int ComputeLookaheadLocked() const;

  int target_depth_frames_;
  int low_water_frames_;
  int lookahead_target_;  // INV-FIVS-LOOKAHEAD-001: frames ahead of consumer before parking
  std::atomic<bool> audio_boost_{false};

  // INV-AUDIO-LIVENESS-001 (Step 2 — audio-burst hysteresis):
  // Sticky flag set when audio depth drops below LowWaterMs(), cleared
  // when audio depth crosses HighWaterMs(). While set, the fill thread
  // does NOT park on video lookahead — it keeps decoding (and the
  // drop-video-for-audio path discards surplus video frames) until
  // audio is comfortably above high-water. This prevents the park/
  // unpark pingpong where audio_liveness wakes decode exactly one
  // frame and immediately re-park.
  std::atomic<bool> audio_burst_active_{false};

  // INV-AUDIO-LIVENESS-001 (Step 4 — AV_LEAD_CLAMP starvation bypass):
  // Hysteresis flag: set when audio_buffer depth drops below LowWaterMs,
  // cleared when depth crosses HighWaterMs. While set, AV_LEAD_CLAMP is
  // bypassed so the full decoded audio burst can reach the buffer — the
  // clamp's overshoot-prevention purpose is inverted during starvation.
  // Audio buffer's own hard_cap_ms remains the safety ceiling.
  std::atomic<bool> av_lead_clamp_bypass_active_{false};

  // INV-BUFFER-HYSTERESIS-001: Dual-threshold steady-state fill control.
  // true  = fill thread is actively decoding (depth <= low water).
  // false = fill thread is parked (depth >= high water).
  // Eliminates single-frame oscillation at target boundary.
  std::atomic<bool> steady_filling_{true};

  // INV-AUDIO-PREROLL-ISOLATION-001: Buffer context label for diagnostics.
  std::string buffer_label_{"UNKNOWN"};
  // STARTUP_TRACE: Log first push to LIVE_VIDEO_BUFFER only once per fill session.
  bool first_push_to_live_logged_ = false;

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
  // FIVS: indexed store for O(1) frame lookup by source_frame_index.
  // Protected by mutex_. Used alongside deque for dual-path access.
  FrameIndexedVideoStore frame_store_;
  std::condition_variable space_cv_;  // fill thread waits when buffer full

  std::thread fill_thread_;
  std::atomic<bool> fill_stop_{false};
  bool fill_running_ = false;
  // INV-BUFFER-LIFECYCLE-001: lifecycle state, owned by this buffer.
  std::atomic<int> fill_state_{static_cast<int>(BufferFillState::STOPPED)};
  // Auto-PRIMED threshold. -1 = disabled (LIVE). Set via SetMinAudioPrimeMs().
  std::atomic<int> min_audio_prime_ms_{-1};
  std::atomic<uint64_t> fill_generation_{0};  // Monotonic; bumped at StopFillingAsync/StartFilling (atomic so tick path can bump without taking mutex_)

  // INV-FIVS-LOOKAHEAD-001: Consumer timeline position (set by tick loop, read by fill thread).
  // -1 means consumer hasn't computed its first selected_src yet.
  std::atomic<int64_t> consumer_selected_src_{-1};

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
  // INV-VIDEO-BOUNDED: log only on first exceed per session (reset when depth goes back under cap).
  mutable bool violation_logged_this_session_{false};

  // INV-AUDIO-LIVENESS-001 diagnostics (not invariants): audio-first decode under backpressure.
  std::atomic<int64_t> decode_continued_for_audio_while_video_full_{0};
  std::atomic<int64_t> decode_parked_video_full_audio_low_{0};

  // INV-AV-FILL-INTERLOCK-001: counts audio suppressed for reasons OTHER than
  // generation mismatch. Any increment on a LIVE buffer is a hard contract violation.
  std::atomic<int64_t> audio_frames_suppressed_non_generation_{0};
  // INV-FILL-AV-LEAD-CLAMP-001: decode cycles where kAvLeadClamp suppressed Push.
  std::atomic<int64_t> av_lead_clamp_events_{0};

  int av_phase_tolerance_ms_{120};
  std::atomic<bool> transition_drain_only_{false};

  // --- FIVS stall diagnostics (INV-FIVS-LOOKAHEAD-STATE-001) ---
 public:
  struct FivsDiag {
    int64_t store_min_index = -1;
    int64_t store_max_index = -1;
    size_t store_size = 0;
    int64_t last_trygetframe_age_ms = -1;  // ms since last TryGetFrame returned
    std::array<int64_t, 8> last_inserted;  // ring of last N inserted source_frame_index
    int last_inserted_count = 0;           // how many valid entries
  };
  FivsDiag SnapshotFivsDiag() const;
 private:
  // Ring buffer of last 8 inserted source_frame_index values (under mutex_).
  static constexpr int kDiagInsertRingSize = 8;
  std::array<int64_t, kDiagInsertRingSize> diag_insert_ring_{};
  int diag_insert_ring_pos_ = 0;
  int diag_insert_ring_count_ = 0;
  // Timestamp of last TryGetFrame return (under mutex_).
  std::chrono::steady_clock::time_point diag_last_trygetframe_time_{};
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_VIDEO_LOOKAHEAD_BUFFER_HPP_
