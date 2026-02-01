// Repository: Retrovue-playout
// Component: Playout Engine Domain
// Purpose: Root execution unit of Air; single-session runtime enforcement.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_RUNTIME_PLAYOUT_ENGINE_H_
#define RETROVUE_RUNTIME_PLAYOUT_ENGINE_H_

// PlayoutEngine
//
// PlayoutEngine is the root execution unit of Air.
// It runs a single playout session at a time and owns:
//
// - runtime graph (producer → buffer → renderer → encoder)
// - clock coordination
// - engine-level state enforcement
//
// PlayoutEngine does NOT:
// - own channel lifecycle
// - interpret schedules
// - manage multiple channels
//
// Channel identity is external and supplied by Core.
// PlayoutEngine enforces only runtime execution correctness.

#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <optional>
#include <unordered_map>

#include "retrovue/runtime/ProgramFormat.h"

namespace retrovue::buffer {
struct Frame;
struct AudioFrame;
}
namespace retrovue::timing {
class MasterClock;
class TimelineController;
}
namespace retrovue::telemetry {
class MetricsExporter;
}
namespace retrovue::output {
class IOutputSink;
class OutputBus;
}

namespace retrovue::runtime {

// Phase 8: Typed result codes matching proto ResultCode enum
// Allows Core to distinguish between transient states and errors.
enum class ResultCode {
  kUnspecified = 0,        // Default/unknown
  kOk = 1,                 // Operation succeeded
  kNotReady = 2,           // Transient: switch armed, awaiting readiness
  kRejectedBusy = 3,       // Operation forbidden in current state
  kProtocolViolation = 4,  // Caller violated the protocol (e.g., SwitchToLive without LoadPreview)
  kFailed = 5              // Real error: operation failed permanently
};

// Domain result structure
struct EngineResult {
  bool success;
  std::string message;
  std::string error_code;  // Structured error code for retry logic (e.g., "NOT_READY_VIDEO")
  ResultCode result_code = ResultCode::kUnspecified;  // Phase 8: Typed result code

  // For LoadPreview
  bool shadow_decode_started = false;

  // For SwitchToLive
  bool pts_contiguous = false;
  uint64_t live_start_pts = 0;

  EngineResult(bool s, const std::string& msg)
      : success(s), message(msg) {}
};

class PlayoutEngine {
 public:
  // When control_surface_only is true, no media/decode/frames are used (Phase 6A.0).
  // StartChannel only initializes channel state; LoadPreview/SwitchToLive update state only.
  PlayoutEngine(
      std::shared_ptr<telemetry::MetricsExporter> metrics_exporter,
      std::shared_ptr<timing::MasterClock> master_clock,
      bool control_surface_only = false);
  
  ~PlayoutEngine();
  
  // Disable copy and move
  PlayoutEngine(const PlayoutEngine&) = delete;
  PlayoutEngine& operator=(const PlayoutEngine&) = delete;
  
  // Domain methods - these are the tested implementations
  EngineResult StartChannel(
      int32_t channel_id,
      const std::string& plan_handle,
      int32_t port,
      const std::optional<std::string>& uds_path = std::nullopt,
      const std::string& program_format_json = "");
  
  EngineResult StopChannel(int32_t channel_id);
  
  // Load a preview asset into shadow decode mode (frame-indexed execution)
  // INV-FRAME-001: start_frame is the first frame index within asset (0-based)
  // INV-FRAME-002: frame_count is the exact number of frames to play
  // INV-FRAME-003: fps is provided as numerator/denominator for precision
  EngineResult LoadPreview(
      int32_t channel_id,
      const std::string& asset_path,
      int64_t start_frame,
      int64_t frame_count,
      int32_t fps_numerator,
      int32_t fps_denominator);
  
  EngineResult SwitchToLive(int32_t channel_id);
  
  // Phase 8.1: live asset path set after SwitchToLive (for stream TS source)
  std::optional<std::string> GetLiveAssetPath(int32_t channel_id);

  // Phase 8.4: Register/unregister callback to receive each rendered frame (for TS mux).
  // Callback is invoked from render thread; callee should copy and queue for encoding.
  void RegisterMuxFrameCallback(int32_t channel_id,
                                std::function<void(const buffer::Frame&)> callback);
  void UnregisterMuxFrameCallback(int32_t channel_id);

  // Phase 8.9: Register/unregister callback to receive each audio frame (for TS mux).
  // Callback is invoked from render thread; callee should copy and queue for encoding.
  void RegisterMuxAudioFrameCallback(int32_t channel_id,
                                     std::function<void(const buffer::AudioFrame&)> callback);
  void UnregisterMuxAudioFrameCallback(int32_t channel_id);

  // Phase 9.0: OutputBus/OutputSink architecture
  // Attaches an output sink to the channel's OutputBus.
  // The sink will receive frames routed through the bus.
  // If replace_existing is true and a sink is already attached, replaces it.
  EngineResult AttachOutputSink(int32_t channel_id,
                                std::unique_ptr<output::IOutputSink> sink,
                                bool replace_existing = false);

  // Detaches the output sink from the channel's OutputBus.
  // If force is true, detaches immediately without waiting for graceful shutdown.
  EngineResult DetachOutputSink(int32_t channel_id, bool force = false);

  // Returns true if an output sink is attached to the channel's OutputBus.
  bool IsOutputSinkAttached(int32_t channel_id);

  // Gets the OutputBus for a channel (for direct access if needed).
  // Returns nullptr if channel not found.
  output::OutputBus* GetOutputBus(int32_t channel_id);

  // Gets the ProgramFormat for a channel.
  // Returns empty optional if channel not found.
  std::optional<ProgramFormat> GetProgramFormat(int32_t channel_id);

  // Connects the renderer to the OutputBus for frame routing.
  // Call this after attaching a sink to start frame flow.
  void ConnectRendererToOutputBus(int32_t channel_id);

  // Disconnects the renderer from the OutputBus (reverts to legacy callbacks).
  void DisconnectRendererFromOutputBus(int32_t channel_id);

  EngineResult UpdatePlan(
      int32_t channel_id,
      const std::string& plan_handle);
  
 private:
  std::shared_ptr<telemetry::MetricsExporter> metrics_exporter_;
  std::shared_ptr<timing::MasterClock> master_clock_;
  bool control_surface_only_;

  // Forward declaration for internal playout runtime (one per Air instance).
  struct PlayoutInstance;

  // Helper: Spawn background SwitchWatcher thread for auto-completion.
  // Called when SwitchToLive returns NOT_READY to ensure readiness polling.
  void SpawnSwitchWatcher(int32_t channel_id, PlayoutInstance* state);

  // Helper: Check if output sink is attached (caller must hold channels_mutex_).
  bool IsOutputSinkAttachedLocked(int32_t channel_id) const;

  // INV-FINALIZE-LIVE: Centralized wiring of output bus → program output.
  // Call after switch completes (normal or watcher) and after sink attach.
  // Ensures ProgramOutput is connected to OutputBus so frames route to sink.
  void FinalizeLiveOutput(int32_t channel_id);

  // TODO: Legacy/transitional. Air runs one playout session; channel identity is external (Core).
  mutable std::mutex channels_mutex_;
  std::unordered_map<int32_t, std::unique_ptr<PlayoutInstance>> channels_;
};

}  // namespace retrovue::runtime

#endif  // RETROVUE_RUNTIME_PLAYOUT_ENGINE_H_

