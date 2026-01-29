// Repository: Retrovue-playout
// Component: Playout Interface
// Purpose: gRPC interface adapter that delegates to the domain engine.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_RUNTIME_PLAYOUT_INTERFACE_H_
#define RETROVUE_RUNTIME_PLAYOUT_INTERFACE_H_

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

// Forward declarations
class PlayoutEngine;
struct ProgramFormat;

// Result structure for interface operations
struct InterfaceResult {
  bool success;
  std::string message;
  
  // For LoadPreview
  bool shadow_decode_started = false;
  
  // For SwitchToLive
  bool pts_contiguous = false;
  uint64_t live_start_pts = 0;
  
  InterfaceResult(bool s, const std::string& msg)
      : success(s), message(msg) {}
};

// PlayoutInterface is a thin adapter between gRPC and the domain engine.
// It delegates all operations to PlayoutEngine which contains the tested domain logic.
class PlayoutInterface {
 public:
  // Constructs interface with a reference to the domain engine
  explicit PlayoutInterface(std::shared_ptr<PlayoutEngine> engine);
  
  ~PlayoutInterface();
  
  // Disable copy and move
  PlayoutInterface(const PlayoutInterface&) = delete;
  PlayoutInterface& operator=(const PlayoutInterface&) = delete;
  
  // Start a new channel with the given configuration
  InterfaceResult StartChannel(
      int32_t channel_id,
      const std::string& plan_handle,
      int32_t port,
      const std::optional<std::string>& uds_path = std::nullopt,
      const std::string& program_format_json = "");
  
  // Stop a channel gracefully
  InterfaceResult StopChannel(int32_t channel_id);
  
  // Load a preview asset into shadow decode mode
  InterfaceResult LoadPreview(
      int32_t channel_id,
      const std::string& asset_path,
      int64_t start_offset_ms = 0,
      int64_t hard_stop_time_ms = 0);
  
  // Switch preview slot to live atomically
  InterfaceResult SwitchToLive(int32_t channel_id);
  
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
  InterfaceResult AttachOutputSink(int32_t channel_id,
                                    std::unique_ptr<output::IOutputSink> sink,
                                    bool replace_existing = false);

  // Detaches the output sink from the channel's OutputBus.
  InterfaceResult DetachOutputSink(int32_t channel_id, bool force = false);

  // Gets the OutputBus for a channel (for direct access if needed).
  output::OutputBus* GetOutputBus(int32_t channel_id);

  // Gets the ProgramFormat for a channel.
  std::optional<ProgramFormat> GetProgramFormat(int32_t channel_id);

  // Returns true if an output sink is attached to the channel's OutputBus.
  bool IsOutputSinkAttached(int32_t channel_id);

  // Connects the renderer to the OutputBus for frame routing.
  void ConnectRendererToOutputBus(int32_t channel_id);

  // Disconnects the renderer from the OutputBus.
  void DisconnectRendererFromOutputBus(int32_t channel_id);

  // Update the playout plan for an active channel
  InterfaceResult UpdatePlan(
      int32_t channel_id,
      const std::string& plan_handle);
  
 private:
  // Domain engine that contains the tested implementation
  std::shared_ptr<PlayoutEngine> engine_;
};

}  // namespace retrovue::runtime

#endif  // RETROVUE_RUNTIME_PLAYOUT_INTERFACE_H_
