// Repository: Retrovue-playout
// Component: Playout Controller
// Purpose: High-level controller that orchestrates channel lifecycle operations.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_RUNTIME_PLAYOUT_CONTROLLER_H_
#define RETROVUE_RUNTIME_PLAYOUT_CONTROLLER_H_

#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <optional>

namespace retrovue::buffer {
struct Frame;
struct AudioFrame;
}
namespace retrovue::output {
class IOutputSink;
class OutputBus;
}
namespace retrovue::runtime {

// Forward declaration
class PlayoutEngine;

// Result structure for controller operations
struct ControllerResult {
  bool success;
  std::string message;
  
  // For LoadPreview
  bool shadow_decode_started = false;
  
  // For SwitchToLive
  bool pts_contiguous = false;
  uint64_t live_start_pts = 0;
  
  ControllerResult(bool s, const std::string& msg)
      : success(s), message(msg) {}
};

// PlayoutController is a thin adapter between gRPC and the domain engine.
// It delegates all operations to PlayoutEngine which contains the tested domain logic.
class PlayoutController {
 public:
  // Constructs controller with a reference to the domain engine
  explicit PlayoutController(std::shared_ptr<PlayoutEngine> engine);
  
  ~PlayoutController();
  
  // Disable copy and move
  PlayoutController(const PlayoutController&) = delete;
  PlayoutController& operator=(const PlayoutController&) = delete;
  
  // Start a new channel with the given configuration
  ControllerResult StartChannel(
      int32_t channel_id,
      const std::string& plan_handle,
      int32_t port,
      const std::optional<std::string>& uds_path = std::nullopt);
  
  // Stop a channel gracefully
  ControllerResult StopChannel(int32_t channel_id);
  
  // Load a preview asset into shadow decode mode (frame-indexed execution)
  // INV-FRAME-001: start_frame is the first frame index within asset (0-based)
  // INV-FRAME-002: frame_count is the exact number of frames to play
  // INV-FRAME-003: fps is provided as numerator/denominator for precision
  ControllerResult LoadPreview(
      int32_t channel_id,
      const std::string& asset_path,
      int64_t start_frame,
      int64_t frame_count,
      int32_t fps_numerator,
      int32_t fps_denominator);
  
  // Switch preview slot to live atomically
  ControllerResult SwitchToLive(int32_t channel_id);
  
  // Phase 8.1: live asset path after SwitchToLive (for stream TS source)
  std::optional<std::string> GetLiveAssetPath(int32_t channel_id);

  // Phase 8.4: Register/unregister callback to receive each rendered frame (for TS mux).
  void RegisterMuxFrameCallback(int32_t channel_id,
                                std::function<void(const buffer::Frame&)> callback);
  void UnregisterMuxFrameCallback(int32_t channel_id);

  // Phase 8.9: Register/unregister callback to receive each audio frame (for TS mux).
  void RegisterMuxAudioFrameCallback(int32_t channel_id,
                                     std::function<void(const buffer::AudioFrame&)> callback);
  void UnregisterMuxAudioFrameCallback(int32_t channel_id);

  // Phase 9.0: OutputBus/OutputSink methods
  // Attaches an output sink to the channel's OutputBus.
  // OB-001: If a sink is already attached, returns error (protocol violation).
  // Core must call DetachOutputSink first if replacement is needed.
  ControllerResult AttachOutputSink(int32_t channel_id,
                                    std::unique_ptr<output::IOutputSink> sink);

  // Detaches the output sink from the channel's OutputBus.
  // OB-003: Always succeeds. Core-owned decision.
  ControllerResult DetachOutputSink(int32_t channel_id);

  // Gets the OutputBus for a channel (for direct access if needed).
  output::OutputBus* GetOutputBus(int32_t channel_id);

  // Returns true if an output sink is attached to the channel's OutputBus.
  bool IsOutputSinkAttached(int32_t channel_id);

  // Connects the renderer to the OutputBus for frame routing.
  void ConnectRendererToOutputBus(int32_t channel_id);

  // Disconnects the renderer from the OutputBus.
  void DisconnectRendererFromOutputBus(int32_t channel_id);

  // Update the playout plan for an active channel
  ControllerResult UpdatePlan(
      int32_t channel_id,
      const std::string& plan_handle);
  
 private:
  // Domain engine that contains the tested implementation
  std::shared_ptr<PlayoutEngine> engine_;
};

}  // namespace retrovue::runtime

#endif  // RETROVUE_RUNTIME_PLAYOUT_CONTROLLER_H_

