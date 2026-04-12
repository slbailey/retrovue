// Repository: Retrovue-playout
// Component: Program Output
// Purpose: Consumes decoded frames and delivers program signal to OutputBus or display.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_RENDERER_PROGRAM_OUTPUT_H_
#define RETROVUE_RENDERER_PROGRAM_OUTPUT_H_

#include <atomic>
#include <chrono>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

#include "retrovue/buffer/FrameRingBuffer.h"
namespace retrovue::telemetry {
struct ChannelMetrics;
class MetricsExporter;
}  // namespace retrovue::telemetry

namespace retrovue::timing {
class MasterClock;
}  // namespace retrovue::timing

namespace retrovue::producers {
class IProducer;
}  // namespace retrovue::producers

namespace retrovue::output {
class OutputBus;
}  // namespace retrovue::output

namespace retrovue::renderer {

// RenderMode specifies the output type.
enum class RenderMode {
  HEADLESS = 0,  // No display output (production mode)
  PREVIEW = 1,   // Preview window (debug/development mode)
};

// RenderConfig holds configuration for program output.
struct RenderConfig {
  RenderMode mode;
  int window_width;
  int window_height;
  std::string window_title;
  bool vsync_enabled;

  RenderConfig()
      : mode(RenderMode::HEADLESS),
        window_width(1920),
        window_height(1080),
        window_title("RetroVue Playout Preview"),
        vsync_enabled(true) {}
};

// RenderStats tracks output performance and frame timing.
struct RenderStats {
  uint64_t frames_rendered;
  uint64_t frames_skipped;
  uint64_t frames_dropped;
  uint64_t corrections_total;
  double average_render_time_ms;
  double current_render_fps;
  double frame_gap_ms;  // Time since last frame

  RenderStats()
      : frames_rendered(0),
        frames_skipped(0),
        frames_dropped(0),
        corrections_total(0),
        average_render_time_ms(0.0),
        current_render_fps(0.0),
        frame_gap_ms(0.0) {}
};

// =============================================================================
// INV-P10-PAD-REASON: Classification of pad frame causes for diagnostics
// =============================================================================
// Every pad frame emission must be classified by root cause.
// This enables correlation with gating, CT tracking, and buffer state.
enum class PadReason {
  BUFFER_TRULY_EMPTY,    // Buffer depth is 0, producer is starved
  PRODUCER_GATED,        // Buffer has frames but producer is blocked at gate
  CT_SLOT_SKIPPED,       // Frame exists but CT mismatch caused skip
  FRAME_CT_MISMATCH,     // Frame CT doesn't match expected output CT
  UNKNOWN                // Fallback for unclassified cases
};

// Converts PadReason to string for logging
inline const char* PadReasonToString(PadReason reason) {
  switch (reason) {
    case PadReason::BUFFER_TRULY_EMPTY: return "BUFFER_TRULY_EMPTY";
    case PadReason::PRODUCER_GATED: return "PRODUCER_GATED";
    case PadReason::CT_SLOT_SKIPPED: return "CT_SLOT_SKIPPED";
    case PadReason::FRAME_CT_MISMATCH: return "FRAME_CT_MISMATCH";
    case PadReason::UNKNOWN: return "UNKNOWN";
    default: return "UNKNOWN";
  }
}

// ProgramOutput consumes frames from the ring buffer and delivers program signal.
//
// Design:
// - Abstract base class with two concrete implementations:
//   - HeadlessProgramOutput: Consumes frames without display (production)
//   - PreviewProgramOutput: Opens SDL2/OpenGL window (debug/development)
// - Runs in dedicated output thread
// - Frame timing driven by metadata.pts
// - Back-pressure handling when buffer empty
//
// Thread Model:
// - Output runs in its own thread
// - Pops frames from FrameRingBuffer (thread-safe)
// - Independent from decode thread
//
// Lifecycle:
// 1. Construct with config and ring buffer reference
// 2. Call Start() to begin output
// 3. Call Stop() to gracefully shutdown
// 4. Destructor ensures thread is joined
class ProgramOutput {
 public:
  virtual ~ProgramOutput();

  // Starts the output thread.
  // Returns true if started successfully.
  bool Start();

  // Stops the output thread gracefully.
  void Stop();

  // Returns true if output is currently running.
  bool IsRunning() const { return running_.load(std::memory_order_acquire); }

  // Gets current output statistics.
  const RenderStats& GetStats() const { return stats_; }

  // Sets the producer (for switching between preview and live).
  void setProducer(producers::IProducer* producer);

  // Resets the pipeline (flushes buffers, resets timestamp state).
  // Called when switching producers to ensure clean state.
  void resetPipeline();

  // Redirects input to a different buffer (for hot-switching buses).
  // Per OutputSwitchingContract: Output Bus can change its source immediately.
  // Thread-safe: takes effect on next frame pop.
  void SetInputBuffer(buffer::FrameRingBuffer* buffer);

  // Phase 7: Returns the PTS of the last emitted frame.
  // Used by SwitchToLive to ensure PTS continuity across segment boundaries.
  // Per INV-P7-001: Channel PTS must be monotonically increasing.
  int64_t GetLastEmittedPTS() const;

  // Contract-level observability: first emitted PTS for AIR_AS_RUN_FRAME_RANGE.
  // Set on first real (non-pad) frame; reset when input buffer changes (new segment).
  int64_t GetFirstEmittedPTS() const;

  // Phase 8.4: Optional callback invoked for each frame (e.g. to feed TS mux).
  void SetSideSink(std::function<void(const buffer::Frame&)> fn);
  void ClearSideSink();

  // Phase 8.9: Optional callback invoked for each audio frame (e.g. to feed TS mux).
  void SetAudioSideSink(std::function<void(const buffer::AudioFrame&)> fn);
  void ClearAudioSideSink();

  // Phase 9.0: OutputBus integration
  // Sets the OutputBus to route frames to (replaces side_sink_ callbacks).
  // OutputBus pointer is NOT owned by ProgramOutput.
  void SetOutputBus(output::OutputBus* bus);
  void ClearOutputBus();

  // INV-P8-SUCCESSOR-OBSERVABILITY: Segment emission observer callback.
  // Called exactly once when first real (non-pad) successor video frame is routed.
  // Must be registered before any segment may commit.
  using OnSuccessorVideoEmittedCallback = std::function<void()>;
  void SetOnSuccessorVideoEmitted(OnSuccessorVideoEmittedCallback callback);

  // P8-FILL-002: PlayoutEngine sets this so ProgramOutput emits pad during content deficit (EOF before boundary).
  // Pointer is NOT owned; must outlive ProgramOutput.
  void SetContentDeficitActiveFlag(std::atomic<bool>* flag);

  // Factory method to create appropriate output based on mode.
  static std::unique_ptr<ProgramOutput> Create(
      const RenderConfig& config,
      buffer::FrameRingBuffer& input_buffer,
      const std::shared_ptr<timing::MasterClock>& clock,
      const std::shared_ptr<telemetry::MetricsExporter>& metrics,
      int32_t channel_id);

 protected:
  // Protected constructor - use factory method.
  ProgramOutput(const RenderConfig& config,
                buffer::FrameRingBuffer& input_buffer,
                const std::shared_ptr<timing::MasterClock>& clock,
                const std::shared_ptr<telemetry::MetricsExporter>& metrics,
                int32_t channel_id);

  // Main output loop (runs in output thread).
  void RenderLoop();

  // Subclass-specific initialization.
  virtual bool Initialize() = 0;

  // Subclass-specific frame output.
  virtual void RenderFrame(const buffer::Frame& frame) = 0;

  // Subclass-specific cleanup.
  virtual void Cleanup() = 0;

  // Updates output statistics.
  void UpdateStats(double render_time_ms, double frame_gap_ms);
  void PublishMetrics(double frame_gap_ms);

  // =========================================================================
  // INV-P10.5-OUTPUT-SAFETY-RAIL: Pad frame generation for continuity
  // =========================================================================
  // Generates deterministic black video frame when producer is starved.
  // Frame has correct resolution, format, and PTS to maintain CT continuity.
  buffer::Frame GeneratePadFrame(int64_t pts_us);

  // Generates deterministic silence audio for corresponding duration.
  // Audio has correct sample rate, channels, and PTS to maintain CT continuity.
  buffer::AudioFrame GeneratePadAudio(int64_t pts_us, int nb_samples);

  RenderConfig config_;
  buffer::FrameRingBuffer* input_buffer_;  // Pointer for hot-switch redirection
  mutable std::mutex input_buffer_mutex_;  // Protects input_buffer_ pointer
  RenderStats stats_;

  std::shared_ptr<timing::MasterClock> clock_;
  std::shared_ptr<telemetry::MetricsExporter> metrics_;
  int32_t channel_id_;

  std::atomic<bool> running_;
  std::atomic<bool> stop_requested_;
  std::unique_ptr<std::thread> render_thread_;

  mutable std::mutex side_sink_mutex_;
  std::function<void(const buffer::Frame&)> side_sink_;

  // Phase 8.9: Audio side sink callback
  mutable std::mutex audio_side_sink_mutex_;
  std::function<void(const buffer::AudioFrame&)> audio_side_sink_;

  // Phase 9.0: OutputBus for frame routing (replaces side_sink_ when set)
  mutable std::mutex output_bus_mutex_;
  output::OutputBus* output_bus_ = nullptr;  // Not owned

  // INV-P8-SUCCESSOR-OBSERVABILITY: Observer callback for first real video emission.
  // Fires once per segment; latches after first real frame routed.
  mutable std::mutex successor_observer_mutex_;
  OnSuccessorVideoEmittedCallback on_successor_video_emitted_;
  bool successor_observer_fired_for_segment_ = false;

  int64_t last_pts_;
  int64_t first_pts_{0};
  bool first_pts_set_{false};
  int64_t last_frame_time_utc_;
  std::chrono::steady_clock::time_point fallback_last_frame_time_;

  // =========================================================================
  // INV-AIR-CONTENT-BEFORE-PAD: First real content frame gates pad emission
  // =========================================================================
  // Pad frames may ONLY be emitted AFTER at least one real decoded content
  // frame has been successfully encoded and muxed. This ensures:
  //   1. First emitted frame is a real content frame (with IDR/SPS/PPS)
  //   2. VLC can decode the stream from the start
  //   3. Pad frames (which may lack keyframe treatment) don't corrupt decoder state
  //
  // =========================================================================
  // INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT: Output-first, content-second
  // =========================================================================
  // After AttachStream, emit decodable TS within 500ms using fallback if needed.
  // Wait briefly for real content, then emit pad (black + silence) anyway.
  //
  // Philosophy: Output is unconditional; content is best-effort.
  // Professional playout systems emit the moment output is armed.
  //
  // This replaces the retired INV-AIR-CONTENT-BEFORE-PAD which had the
  // philosophy backwards (gating output on content availability).
  //
  // EXCEPTION: When no_content_segment_=true (zero-frame segment), pad frames
  // are allowed immediately without waiting.
  // =========================================================================
  bool first_real_frame_emitted_ = false;

  // Maximum time to wait for first real frame before emitting fallback.
  // 500ms is long enough for decoder to produce IDR/SPS/PPS, short enough
  // that viewers see black quickly if content is unavailable.
  static constexpr int64_t kFirstContentWaitWindowUs = 500'000;  // 500ms
  int64_t first_content_wait_start_us_ = 0;  // 0 = not yet started waiting
  bool first_content_wait_expired_ = false;  // true once window exceeded

  // =========================================================================
  // INV-P8-ZERO-FRAME-BOOTSTRAP: Allow pad frames when no content expected
  // =========================================================================
  // When a segment has frame_count=0, no real content will ever arrive.
  // In this case, pad frames must be allowed immediately so the encoder
  // can initialize and output can flow. The first pad frame serves as
  // the "bootstrap frame" for SPS/PPS emission.
  bool no_content_segment_ = false;

  // P8-FILL-002: Content deficit active flag from PlayoutEngine (EOF before boundary).
  // When set, emit pad immediately when buffer empty (no freeze window).
  std::atomic<bool>* content_deficit_active_ptr_ = nullptr;

  // =========================================================================
  // INV-PACING-ENFORCEMENT-002: RealTimeHoldPolicy state
  // =========================================================================
  // Enforces wall-clock pacing with freeze-then-pad behavior.
  // See: docs/contracts/semantics/RealTimeHoldPolicy.md
  //
  // CLAUSE 1: "emit at most one frame per frame period"
  // CLAUSE 2A: "re-emit last frame" for up to freeze_window
  // CLAUSE 2B: "emit pad frames" after freeze window exceeded
  // =========================================================================
  int64_t pacing_last_emission_us_ = 0;            // Wall-clock of last emission
  int64_t pacing_frame_period_us_ = 33333;         // 1/fps in microseconds (updated from first frame)
  buffer::Frame pacing_last_emitted_frame_;        // For freeze re-emission
  bool pacing_has_last_frame_ = false;             // Whether we have a frame to freeze
  int64_t pacing_freeze_start_us_ = 0;             // When current freeze episode started
  bool pacing_in_freeze_mode_ = false;             // Currently in freeze mode
  static constexpr int64_t kDefaultFreezeWindowUs = 250'000;  // 250ms default
  int64_t pacing_freeze_window_us_ = kDefaultFreezeWindowUs;

  // Telemetry (CLAUSE 4: mandatory observability)
  uint64_t pacing_freeze_frames_ = 0;              // Count of freeze re-emissions
  uint64_t pacing_late_events_ = 0;                // Count of missed deadlines
  int64_t pacing_freeze_duration_ms_ = 0;          // Current continuous freeze time
  uint64_t pacing_max_freeze_streak_ = 0;          // Longest consecutive freeze run
  uint64_t pacing_current_freeze_streak_ = 0;      // Current freeze streak

  // =========================================================================
  // INV-PACING-001: Diagnostic probe state for render loop pacing
  // =========================================================================
  // Tracks wall-clock time between frame emissions to detect pacing violations.
  // Violation: emission rate >> target_fps (CPU speed instead of frame rate).
  // See: docs/contracts/semantics/PrimitiveInvariants.md
  // =========================================================================
  int64_t pacing_probe_last_emission_us_ = 0;      // Wall-clock time of last emission
  uint64_t pacing_probe_fast_emissions_ = 0;       // Count of emissions faster than threshold
  uint64_t pacing_probe_total_emissions_ = 0;      // Total emissions for rate calculation
  int64_t pacing_probe_window_start_us_ = 0;       // Start of current measurement window
  uint64_t pacing_probe_window_frames_ = 0;        // Frames in current measurement window
  static constexpr int64_t kPacingProbeWindowUs = 1'000'000;  // 1-second window
  static constexpr double kPacingViolationThreshold = 0.5;    // Gap < 50% of frame_duration = violation
  bool pacing_violation_logged_ = false;           // Log violation once per episode

  // =========================================================================
  // INV-P10.5-OUTPUT-SAFETY-RAIL: Pad frame state
  // =========================================================================
  // Tracks frame dimensions and rate learned from first real frame.
  // Used to generate matching pad frames when producer is starved.
  bool pad_frame_initialized_ = false;
  int pad_frame_width_ = 1920;
  int pad_frame_height_ = 1080;
  int64_t pad_frame_duration_us_ = 33333;  // Default 30fps
  uint64_t pad_frames_emitted_ = 0;  // Metric: retrovue_pad_frames_emitted_total

  // =========================================================================
  // INV-P10-PAD-REASON: Correlation counters by pad reason
  // =========================================================================
  // Per-reason counters for diagnostic correlation with gating and CT state.
  uint64_t pads_buffer_empty_ = 0;       // BUFFER_TRULY_EMPTY
  uint64_t pads_producer_gated_ = 0;     // PRODUCER_GATED (not currently detectable)
  uint64_t pads_ct_skipped_ = 0;         // CT_SLOT_SKIPPED
  uint64_t pads_ct_mismatch_ = 0;        // FRAME_CT_MISMATCH
  uint64_t pads_unknown_ = 0;            // UNKNOWN fallback

  // =========================================================================
  // INV-P9-STEADY-004: No Pad While Depth High
  // =========================================================================
  // Pad frame emission while buffer depth >= 10 is a CONTRACT VIOLATION.
  // If frames exist in the buffer but are not being consumed, this indicates
  // a flow control or CT tracking bug, not content starvation.
  // Counter tracks violations; log emitted on each occurrence.
  // =========================================================================
  uint64_t pad_while_depth_high_ = 0;
  static constexpr size_t kDepthHighThreshold = 10;

  // =========================================================================
  // INV-P10.5-AUDIO-FORMAT-LOCK: Pad audio format is FIXED at channel start
  // =========================================================================
  // Pad audio format is locked to canonical values (48000 Hz, 2 channels).
  // These values NEVER change, regardless of producer audio format.
  // This prevents AUDIO_FORMAT_CHANGE after TS header is written.
  //
  // If producer audio has different format (e.g., 44100 Hz), the encoder's
  // resampler handles it. Pad audio always uses the canonical format.
  // =========================================================================
  static constexpr int kCanonicalPadSampleRate = 48000;
  static constexpr int kCanonicalPadChannels = 2;
  bool audio_format_locked_ = false;  // Set true at channel start

  // Fractional sample accumulator for phase-continuous pad audio.
  // Reset ONLY on segment boundary (CT ownership change), not on first pad frame.
  double audio_sample_remainder_ = 0.0;

  // =========================================================================
  // INV-P9-STEADY-005: Buffer Equilibrium Sustained (P9-CORE-008, P9-OPT-001)
  // =========================================================================
  // Buffer depth MUST oscillate around target (default: 3 frames).
  // Depth MUST remain in range [1, 2N] during steady-state.
  // Monitor periodically and warn if outside range for > 1 second.
  //
  // Observability only (Phase 9) - no enforcement.
  // Rate-limited logging to avoid spam (max 1 log per 5 seconds).
  // =========================================================================
  static constexpr int kEquilibriumTargetDepth = 3;
  static constexpr int kEquilibriumMinDepth = 1;
  static constexpr int kEquilibriumMaxDepth = 2 * kEquilibriumTargetDepth;  // 6
  static constexpr int64_t kEquilibriumSampleIntervalUs = 1'000'000;        // 1 second
  static constexpr int64_t kEquilibriumLogRateLimitUs = 5'000'000;          // 5 seconds

  int64_t equilibrium_last_check_us_ = 0;           // Wall-clock of last sample
  int64_t equilibrium_violation_start_us_ = 0;      // When violation episode started
  bool equilibrium_in_violation_ = false;           // Currently outside [1, 2N]
  int64_t equilibrium_last_log_us_ = 0;             // Wall-clock of last warning log
  uint64_t equilibrium_violations_total_ = 0;       // Count of 1s+ violations (metric)
  size_t equilibrium_last_depth_ = 0;               // Depth at last sample

  // Called from RenderLoop to check buffer equilibrium periodically
  void CheckBufferEquilibrium();

 public:
  // Called at channel start to lock pad audio format.
  // Must be called before any frames are emitted.
  void LockPadAudioFormat() {
    audio_format_locked_ = true;
  }

  // INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT: Check if real content has arrived.
  // Used by diagnostics and tests to verify fallback-to-content transition.
  bool HasEmittedRealFrame() const {
    return first_real_frame_emitted_;
  }

  // INV-P9-STEADY-004: Get violation count for pad emitted while depth >= 10.
  // Used by tests to verify violation detection.
  uint64_t GetPadWhileDepthHighViolations() const {
    return pad_while_depth_high_;
  }

  // INV-P8-ZERO-FRAME-BOOTSTRAP: Set when segment has no real content.
  // When true, pad frames are allowed immediately (bypasses CONTENT-BEFORE-PAD).
  // The first pad frame acts as "bootstrap frame" for encoder initialization.
  // Call with true when switching to a zero-frame segment.
  // Call with false when switching to a segment with real content.
  void SetNoContentSegment(bool value);

  // Returns true if current segment has no content (frame_count=0).
  bool IsNoContentSegment() const {
    return no_content_segment_;
  }

  // INV-P9-STEADY-005: Get equilibrium violation count (violations lasting > 1s).
  // Used by tests to verify equilibrium monitoring.
  uint64_t GetEquilibriumViolations() const {
    return equilibrium_violations_total_;
  }

  // INV-P9-STEADY-005: Check if currently in equilibrium violation state.
  bool IsInEquilibriumViolation() const {
    return equilibrium_in_violation_;
  }

  // INV-P9-STEADY-005: Get last sampled buffer depth for diagnostics.
  size_t GetLastEquilibriumDepth() const {
    return equilibrium_last_depth_;
  }

  // Called on segment boundary to reset pad audio phase accumulator.
  // This keeps filler phase-continuous within a segment.
  void ResetPadAudioAccumulator() { audio_sample_remainder_ = 0.0; }
};

// HeadlessProgramOutput consumes frames without displaying them.
class HeadlessProgramOutput : public ProgramOutput {
 public:
  HeadlessProgramOutput(const RenderConfig& config,
                        buffer::FrameRingBuffer& input_buffer,
                        const std::shared_ptr<timing::MasterClock>& clock,
                        const std::shared_ptr<telemetry::MetricsExporter>& metrics,
                        int32_t channel_id);
  ~HeadlessProgramOutput() override;

 protected:
  bool Initialize() override;
  void RenderFrame(const buffer::Frame& frame) override;
  void Cleanup() override;
};

// PreviewProgramOutput displays frames in an SDL2 window.
class PreviewProgramOutput : public ProgramOutput {
 public:
  PreviewProgramOutput(const RenderConfig& config,
                       buffer::FrameRingBuffer& input_buffer,
                       const std::shared_ptr<timing::MasterClock>& clock,
                       const std::shared_ptr<telemetry::MetricsExporter>& metrics,
                       int32_t channel_id);
  ~PreviewProgramOutput() override;

 protected:
  bool Initialize() override;
  void RenderFrame(const buffer::Frame& frame) override;
  void Cleanup() override;

 private:
  // SDL2/OpenGL context (opaque pointers)
  void* window_;       // SDL_Window*
  void* sdl_renderer_;  // SDL_Renderer*
  void* texture_;      // SDL_Texture*
};

}  // namespace retrovue::renderer

#endif  // RETROVUE_RENDERER_PROGRAM_OUTPUT_H_
