#ifndef RETROVUE_RUNTIME_PLAYOUT_CONTROL_H_
#define RETROVUE_RUNTIME_PLAYOUT_CONTROL_H_

#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include <mutex>

#include <functional>

#include "retrovue/runtime/TimingLoop.h"
#include "retrovue/runtime/ProducerBus.h"
#include "retrovue/runtime/ProgramFormat.h"
#include "retrovue/producers/black/BlackFrameProducer.h"
#include "retrovue/blockplan/RationalFps.hpp"

namespace retrovue {
namespace buffer {
  class FrameRingBuffer;
}
namespace timing {
  class MasterClock;
}
namespace producers {
  class IProducer;
}
namespace renderer {
  class ProgramOutput;
}
}

namespace retrovue::runtime {

// PlayoutControl
//
// Enforces valid sequencing of runtime operations inside a single Air
// playout engine instance.
//
// This control plane exists to protect timing, buffer, and encoder
// invariants (PTS continuity, buffer priming, decode/render ordering).
//
// It does NOT represent:
// - channel lifecycle
// - scheduling state
// - business logic
// - multi-channel coordination
//
// Channel identity and lifecycle are owned by Core.
// This control plane only governs internal engine physics.
class PlayoutControl {
 public:
  // RuntimePhase represents the current execution phase
  // of the playout pipeline, not channel lifecycle state.
  enum class RuntimePhase {
    kIdle,       // No active playout graph
    kBuffering,  // Priming decode/render buffers
    kReady,      // Buffers primed, safe to start output
    kPlaying,    // Actively emitting frames
    kPaused,     // Pipeline halted, state retained
    kStopping,   // Graceful shutdown in progress
    kError       // Fatal runtime invariant violation
  };

  struct MetricsSnapshot {
    std::map<std::pair<RuntimePhase, RuntimePhase>, uint64_t> transitions;
    uint64_t illegal_transition_total = 0;
    uint64_t latency_violation_total = 0;
    uint64_t timeout_total = 0;
    uint64_t queue_overflow_total = 0;
    uint64_t recover_total = 0;
    uint64_t consistency_failure_total = 0;
    uint64_t late_seek_total = 0;
    double pause_latency_p95_ms = 0.0;
    double resume_latency_p95_ms = 0.0;
    double seek_latency_p95_ms = 0.0;
    double stop_latency_p95_ms = 0.0;
    double pause_deviation_p95_ms = 0.0;
    double last_pause_latency_ms = 0.0;
    double last_resume_latency_ms = 0.0;
    double last_seek_latency_ms = 0.0;
    double last_stop_latency_ms = 0.0;
    double last_pause_deviation_ms = 0.0;
    RuntimePhase state = RuntimePhase::kIdle;
  };

  PlayoutControl();

  PlayoutControl(const PlayoutControl&) = delete;
  PlayoutControl& operator=(const PlayoutControl&) = delete;

  bool BeginSession(const std::string& command_id, int64_t request_utc_us);
  bool Pause(const std::string& command_id,
             int64_t request_utc_us,
             int64_t effective_utc_us,
             double boundary_deviation_ms);
  bool Resume(const std::string& command_id,
              int64_t request_utc_us,
              int64_t effective_utc_us);
  bool Seek(const std::string& command_id,
            int64_t request_utc_us,
            int64_t target_pts_us,
            int64_t effective_utc_us);
  bool Stop(const std::string& command_id,
            int64_t request_utc_us,
            int64_t effective_utc_us);
  bool Recover(const std::string& command_id, int64_t request_utc_us);

  void OnBufferDepth(std::size_t depth,
                     std::size_t capacity,
                     int64_t event_utc_us);
  void OnBackPressureEvent(TimingLoop::BackPressureEvent event,
                           int64_t event_utc_us);
  void OnBackPressureCleared(int64_t event_utc_us);

  void OnExternalTimeout(int64_t event_utc_us);
  void OnQueueOverflow();

  [[nodiscard]] RuntimePhase state() const;
  [[nodiscard]] MetricsSnapshot Snapshot() const;

  // Dual-producer slot management (Phase 6A.1 ExecutionProducer)
  // Factory creates a producer for the given segment; segment params are passed for hard_stop enforcement.
  using ProducerFactory = std::function<std::unique_ptr<producers::IProducer>(
      const std::string& path,
      const std::string& assetId,
      buffer::FrameRingBuffer& ringBuffer,
      std::shared_ptr<timing::MasterClock> clock,
      int64_t start_offset_ms,
      int64_t hard_stop_time_ms)>;
  
  void setProducerFactory(ProducerFactory factory);

  // Loads a producer into the preview bus with segment params (Phase 6A.1).
  // Requires: setProducerFactory() must be called first, and ringBuffer/clock must be provided.
  // Returns true on success, false on failure.
  bool loadPreviewAsset(const std::string& path,
                       const std::string& assetId,
                       buffer::FrameRingBuffer& ringBuffer,
                       std::shared_ptr<timing::MasterClock> clock,
                       int64_t start_offset_ms = 0,
                       int64_t hard_stop_time_ms = 0);

  // Switches preview bus to live bus.
  // Stops live producer, flushes renderer, resets timestamps, and swaps producers.
  // Requires: renderer pointer for flushing (can be nullptr if not available).
  // Returns true on success, false on failure.
  bool activatePreviewAsLive(renderer::ProgramOutput* program_output = nullptr);

  // Gets the preview bus (const access).
  const ProducerBus& getPreviewBus() const;

  // Gets the live bus (const access).
  const ProducerBus& getLiveBus() const;

  // OutputBus integration (Phase 9.0: OutputBus/OutputSink architecture)
  // Returns true if a sink can be attached in the current phase.
  // Valid phases for attach: kReady, kPlaying, kPaused
  [[nodiscard]] bool CanAttachSink() const;

  // Returns true if a sink can be detached in the current phase.
  // Detach is allowed in any phase (forced detach always allowed).
  [[nodiscard]] bool CanDetachSink() const;

  // Called when a sink is attached.
  // Updates internal sink tracking state.
  void OnSinkAttached();

  // Called when a sink is detached.
  // Updates internal sink tracking state.
  void OnSinkDetached();

  // Returns true if a sink is currently attached.
  [[nodiscard]] bool IsSinkAttached() const;

  // ============================================================================
  // BlackFrameProducer Fallback Support (per BlackFrameProducerContract.md)
  // ============================================================================
  //
  // INVARIANT 1: Fallback is a DEAD-MAN STATE, not a convenience mechanism.
  //   - AIR enters fallback ONLY when the live producer has no frames available
  //     (underrun, EOF, or end-PTS clamp reached) AND Core has not yet issued
  //     the next control command.
  //   - Fallback is NEVER entered during planned transitions, between segments,
  //     or as part of SwitchToLive/preview promotion.
  //
  // INVARIANT 2: Fallback exit requires EXPLICIT Core reassertion.
  //   - AIR remains in fallback indefinitely until Core issues LoadPreview +
  //     SwitchToLive (or equivalent command).
  //   - AIR does NOT exit fallback due to time passing, producers becoming
  //     available, or internal heuristics.
  //
  // INVARIANT 3: End-PTS clamp triggers fallback.
  //   - When a producer reaches its end-PTS boundary, it is considered
  //     exhausted (IsExhausted() returns true).
  //   - This causes fallback entry, reflecting that Core failed to supply
  //     the next segment before the current one ended.
  //   - This is intentional: end-PTS exhaustion = loss of direction = fallback.
  //
  // ============================================================================

  // Sets the session/house output FPS (INV-FPS-RESAMPLE, INV-FPS-TICK-PTS).
  // PTS step on seamless switch uses this, not producer FPS. Call when session
  // format is established (e.g. StartChannel). If never set, one-tick duration
  // falls back to house default (FPS_30) when session fps invalid.
  void SetSessionOutputFps(retrovue::blockplan::RationalFps fps);

  // Configures the fallback producer with the program format.
  // Must be called before fallback can be entered.
  void ConfigureFallbackProducer(const ProgramFormat& format,
                                 buffer::FrameRingBuffer& buffer,
                                 std::shared_ptr<timing::MasterClock> clock);

  // Enters fallback mode (dead-man failsafe).
  //
  // PRECONDITIONS (caller must ensure):
  //   - Live producer has no frames available (underrun/EOF/end-PTS)
  //   - Core has not yet issued the next control command
  //
  // This method MUST NOT be called:
  //   - During planned transitions
  //   - As part of SwitchToLive or preview promotion
  //   - For convenience or "between segments"
  //
  // Returns true if fallback was entered, false if already in fallback.
  bool EnterFallback(int64_t continuation_pts_us);

  // Exits fallback mode.
  //
  // This method MUST ONLY be called as a result of an explicit Core command
  // (e.g., SwitchToLive via activatePreviewAsLive).
  //
  // AIR MUST NOT call this method autonomously based on:
  //   - Time passing
  //   - Producers becoming available
  //   - Internal heuristics
  //
  // Returns true if fallback was exited, false if not in fallback.
  bool ExitFallback();

  // Returns true if currently in fallback mode (BlackFrameProducer active).
  [[nodiscard]] bool IsInFallback() const;

  // Returns the number of times fallback has been entered (telemetry).
  [[nodiscard]] uint64_t GetFallbackEntryCount() const;

  // Returns the BlackFrameProducer (for inspection/testing).
  // May return nullptr if fallback is not configured or not active.
  [[nodiscard]] producers::black::BlackFrameProducer* GetFallbackProducer() const;

  // Test-only: last PTS step (µs) used in activatePreviewAsLive for seamless switch.
  // Used by PlayoutControlPtsStepUsesSessionFpsNotProducer to assert session FPS authority.
  [[nodiscard]] int64_t LastPtsStepUsForTest() const { return last_pts_step_us_; }

 private:
  void TransitionLocked(RuntimePhase to, int64_t event_utc_us);
  void RecordTransitionLocked(RuntimePhase from, RuntimePhase to);
  void RecordLatencyLocked(std::vector<double>& samples, double value_ms);
  double PercentileLocked(const std::vector<double>& samples, double percentile) const;
  bool RegisterCommandLocked(const std::string& command_id);
  void RecordIllegalTransitionLocked(RuntimePhase from, RuntimePhase attempted_to);

  constexpr static double kPauseLatencyThresholdMs = 33.0;
  constexpr static double kResumeLatencyThresholdMs = 50.0;
  constexpr static double kSeekLatencyThresholdMs = 250.0;
  constexpr static double kStopLatencyThresholdMs = 500.0;
  constexpr static std::size_t kReadinessThresholdFrames = 3;

  mutable std::mutex mutex_;

  RuntimePhase state_;
  std::unordered_map<std::string, int64_t> processed_commands_;
  int64_t current_pts_us_;
  std::map<std::pair<RuntimePhase, RuntimePhase>, uint64_t> transitions_;
  uint64_t illegal_transition_total_;
  uint64_t latency_violation_total_;
  uint64_t timeout_total_;
  uint64_t queue_overflow_total_;
  uint64_t recover_total_;
  uint64_t consistency_failure_total_;
  uint64_t late_seek_total_;
  std::vector<double> pause_latencies_ms_;
  std::vector<double> resume_latencies_ms_;
  std::vector<double> seek_latencies_ms_;
  std::vector<double> stop_latencies_ms_;
  std::vector<double> pause_deviation_ms_;

  // Dual-producer buses
  ProducerBus previewBus;
  ProducerBus liveBus;

  // Producer factory (set by playout_service)
  ProducerFactory producer_factory_;

  // Sink attachment tracking (Phase 9.0: OutputBus/OutputSink)
  bool sink_attached_ = false;

  // Session/house output FPS (INV-FPS-RESAMPLE). Authority for PTS step on switch.
  retrovue::blockplan::RationalFps session_output_fps_{0, 1};

  // Set in activatePreviewAsLive; read by LastPtsStepUsForTest() for contract tests.
  mutable int64_t last_pts_step_us_ = 0;

  // BlackFrameProducer fallback state
  std::unique_ptr<producers::black::BlackFrameProducer> fallback_producer_;
  bool in_fallback_ = false;
  uint64_t fallback_entry_count_ = 0;  // Telemetry: times fallback entered
  ProgramFormat fallback_format_;
  buffer::FrameRingBuffer* fallback_buffer_ = nullptr;
  std::shared_ptr<timing::MasterClock> fallback_clock_;
};

}  // namespace retrovue::runtime

#endif  // RETROVUE_RUNTIME_PLAYOUT_CONTROL_H_
