// Repository: Retrovue-playout
// Component: Playout Engine Domain
// Purpose: Domain-level engine that manages channel lifecycle operations.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_RUNTIME_PLAYOUT_ENGINE_H_
#define RETROVUE_RUNTIME_PLAYOUT_ENGINE_H_

#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <optional>
#include <unordered_map>

namespace retrovue::timing {
class MasterClock;
}

namespace retrovue::telemetry {
class MetricsExporter;
}

namespace retrovue::runtime {

// Domain result structure
struct EngineResult {
  bool success;
  std::string message;
  
  // For LoadPreview
  bool shadow_decode_started = false;
  
  // For SwitchToLive
  bool pts_contiguous = false;
  uint64_t live_start_pts = 0;
  
  EngineResult(bool s, const std::string& msg)
      : success(s), message(msg) {}
};

// PlayoutEngine provides domain-level channel lifecycle management.
// This is the authoritative implementation that has been tested via contract tests.
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
      const std::optional<std::string>& uds_path = std::nullopt);
  
  EngineResult StopChannel(int32_t channel_id);
  
  EngineResult LoadPreview(
      int32_t channel_id,
      const std::string& asset_path,
      int64_t start_offset_ms = 0,
      int64_t hard_stop_time_ms = 0);
  
  EngineResult SwitchToLive(int32_t channel_id);
  
  // Phase 8.1: live asset path set after SwitchToLive (for stream TS source)
  std::optional<std::string> GetLiveAssetPath(int32_t channel_id);
  
  EngineResult UpdatePlan(
      int32_t channel_id,
      const std::string& plan_handle);
  
 private:
  std::shared_ptr<telemetry::MetricsExporter> metrics_exporter_;
  std::shared_ptr<timing::MasterClock> master_clock_;
  bool control_surface_only_;

  // Forward declaration for internal channel state
  struct ChannelState;
  
  // Channel management (thread-safe)
  mutable std::mutex channels_mutex_;
  std::unordered_map<int32_t, std::unique_ptr<ChannelState>> channels_;
};

}  // namespace retrovue::runtime

#endif  // RETROVUE_RUNTIME_PLAYOUT_ENGINE_H_

