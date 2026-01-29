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
};

}  // namespace retrovue::runtime

#endif  // RETROVUE_RUNTIME_PLAYOUT_CONTROL_H_
