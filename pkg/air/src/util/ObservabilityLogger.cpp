// Repository: Retrovue-playout
// Component: ObservabilityLogger — LAW-OBS-001 through LAW-OBS-005 enforcement
// Copyright (c) 2025 RetroVue

#include "retrovue/util/ObservabilityLogger.hpp"

#include <chrono>
#include <sstream>


#include "retrovue/util/Logger.hpp"

namespace retrovue::util {

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

static int64_t NowMs() {
  using namespace std::chrono;
  return duration_cast<milliseconds>(
             system_clock::now().time_since_epoch())
      .count();
}

// ---------------------------------------------------------------------------
// LAW-OBS-001 / LAW-OBS-002 / LAW-OBS-004 — Intent received
// ---------------------------------------------------------------------------

void LogIntentReceived(
    const std::string& correlation_id,
    const std::string& rpc,
    int32_t            channel_id,
    int64_t            receipt_time_ms,
    const std::string& asset_path,
    int64_t            start_frame,
    int64_t            frame_count,
    bool               rpc_requires_timing) {

  // LAW-OBS-001: rpc must not be empty (intent must be named)
  if (rpc.empty()) {
    Logger::ErrorStructured(
        "LAW-OBS-001-VIOLATED: AIR-INTENT-RECEIVED emitted with empty rpc — "
        "intent is not observable",
        "LAW-OBS-001-VIOLATED",
        {{"channel_id", std::to_string(channel_id)}});
  }

  // LAW-OBS-002: correlation_id must be present
  if (correlation_id.empty()) {
    Logger::ErrorStructured(
        "LAW-OBS-002-VIOLATED: AIR-INTENT-RECEIVED emitted without correlation_id — "
        "intent cannot be correlated across Core and Air logs",
        "LAW-OBS-002-VIOLATED",
        {{"rpc", rpc}, {"channel_id", std::to_string(channel_id)}});
  }

  // LAW-OBS-004: receipt_time_ms required for timed RPCs
  if (rpc_requires_timing && receipt_time_ms == 0) {
    Logger::ErrorStructured(
        "LAW-OBS-004-VIOLATED: AIR-INTENT-RECEIVED emitted without receipt_time_ms — "
        "timing evidence absent for " + rpc,
        "LAW-OBS-004-VIOLATED",
        {{"rpc", rpc},
         {"channel_id", std::to_string(channel_id)},
         {"correlation_id", correlation_id}});
  }

  // Emit canonical event
  std::ostringstream oss;
  oss << "AIR-INTENT-RECEIVED"
      << " correlation_id=" << correlation_id
      << " rpc=" << rpc
      << " channel_id=" << channel_id
      << " receipt_time_ms=" << receipt_time_ms;
  if (!asset_path.empty()) {
    oss << " asset_path=" << asset_path
        << " start_frame=" << start_frame
        << " frame_count=" << frame_count;
  }
  Logger::Info(oss.str());
}

// ---------------------------------------------------------------------------
// LAW-OBS-003 / LAW-OBS-004 — Intent response
// ---------------------------------------------------------------------------

void LogIntentResponse(
    const std::string& correlation_id,
    const std::string& rpc,
    int32_t            channel_id,
    bool               success,
    const std::string& result_code,
    const std::string& message,
    int64_t            completion_time_ms,
    bool               rpc_requires_timing) {

  // LAW-OBS-003: correlation_id and result_code must be present
  if (correlation_id.empty()) {
    Logger::ErrorStructured(
        "LAW-OBS-003-VIOLATED: AIR-INTENT-RESPONSE emitted without correlation_id",
        "LAW-OBS-003-VIOLATED",
        {{"rpc", rpc}, {"channel_id", std::to_string(channel_id)}});
  }
  if (result_code.empty()) {
    Logger::ErrorStructured(
        "LAW-OBS-003-VIOLATED: AIR-INTENT-RESPONSE emitted without result_code",
        "LAW-OBS-003-VIOLATED",
        {{"rpc", rpc},
         {"channel_id", std::to_string(channel_id)},
         {"correlation_id", correlation_id}});
  }

  // LAW-OBS-004: completion_time_ms required for timed RPCs
  if (rpc_requires_timing && completion_time_ms == 0) {
    Logger::ErrorStructured(
        "LAW-OBS-004-VIOLATED: AIR-INTENT-RESPONSE emitted without completion_time_ms — "
        "timing evidence absent for " + rpc,
        "LAW-OBS-004-VIOLATED",
        {{"rpc", rpc},
         {"channel_id", std::to_string(channel_id)},
         {"correlation_id", correlation_id}});
  }

  // Emit canonical event
  std::ostringstream oss;
  oss << "AIR-INTENT-RESPONSE"
      << " correlation_id=" << correlation_id
      << " rpc=" << rpc
      << " channel_id=" << channel_id
      << " success=" << std::boolalpha << success
      << " result_code=" << result_code
      << " completion_time_ms=" << completion_time_ms;
  if (!message.empty()) {
    oss << " message=" << message;
  }
  Logger::Info(oss.str());
}

// ---------------------------------------------------------------------------
// Effective events
// ---------------------------------------------------------------------------

void LogLoadPreviewEffective(
    const std::string& correlation_id,
    int32_t            channel_id,
    const std::string& asset_path,
    int64_t            effective_time_ms) {
  std::ostringstream oss;
  oss << "AIR-LOADPREVIEW-EFFECTIVE"
      << " correlation_id=" << correlation_id
      << " channel_id=" << channel_id
      << " asset_path=" << asset_path
      << " effective_time_ms=" << effective_time_ms;
  Logger::Info(oss.str());
}

void LogSwitchToLiveEffective(
    const std::string& correlation_id,
    int32_t            channel_id,
    int64_t            effective_time_ms) {
  std::ostringstream oss;
  oss << "AIR-SWITCHTOLIVE-EFFECTIVE"
      << " correlation_id=" << correlation_id
      << " channel_id=" << channel_id
      << " effective_time_ms=" << effective_time_ms;
  Logger::Info(oss.str());
}

// ---------------------------------------------------------------------------
// LAW-OBS-005 — Clamp events
// ---------------------------------------------------------------------------

void LogClampStarted(
    const std::string& correlation_id,
    int32_t            channel_id,
    const std::string& asset_path,
    int64_t            boundary_ms,
    const std::string& segment_correlation_id) {

  bool violated = false;
  std::vector<std::pair<std::string, std::string>> fields = {
      {"correlation_id", correlation_id},
      {"channel_id", std::to_string(channel_id)},
      {"asset_path", asset_path},
      {"boundary_ms", std::to_string(boundary_ms)}};

  if (channel_id == 0 || asset_path.empty() || boundary_ms == 0) {
    violated = true;
    Logger::ErrorStructured(
        "LAW-OBS-005-VIOLATED: AIR-CLAMP-STARTED missing required fields — "
        "channel_id, asset_path, and boundary_ms are all mandatory",
        "LAW-OBS-005-VIOLATED",
        fields);
  }

  // Always emit the canonical event (even if violated, so the log is present)
  std::ostringstream oss;
  oss << "AIR-CLAMP-STARTED"
      << " correlation_id=" << correlation_id
      << " channel_id=" << channel_id
      << " asset_path=" << asset_path
      << " boundary_ms=" << boundary_ms;
  if (!segment_correlation_id.empty()) {
    oss << " segment_correlation_id=" << segment_correlation_id;
  }
  Logger::Info(oss.str());
}

void LogClampActive(
    int32_t            channel_id,
    const std::string& asset_path,
    int64_t            boundary_ms,
    int64_t            clamp_duration_ms) {
  std::ostringstream oss;
  oss << "AIR-CLAMP-ACTIVE"
      << " channel_id=" << channel_id
      << " asset_path=" << asset_path
      << " boundary_ms=" << boundary_ms
      << " clamp_duration_ms=" << clamp_duration_ms;
  Logger::Info(oss.str());
}

void LogClampEnded(
    int32_t            channel_id,
    const std::string& asset_path,
    int64_t            boundary_ms,
    const std::string& next_correlation_id) {

  if (channel_id == 0 || asset_path.empty() || boundary_ms == 0) {
    Logger::ErrorStructured(
        "LAW-OBS-005-VIOLATED: AIR-CLAMP-ENDED missing required fields — "
        "channel_id, asset_path, and boundary_ms are all mandatory",
        "LAW-OBS-005-VIOLATED",
        {{"channel_id", std::to_string(channel_id)},
         {"asset_path", asset_path},
         {"boundary_ms", std::to_string(boundary_ms)}});
  }

  std::ostringstream oss;
  oss << "AIR-CLAMP-ENDED"
      << " channel_id=" << channel_id
      << " asset_path=" << asset_path
      << " boundary_ms=" << boundary_ms;
  if (!next_correlation_id.empty()) {
    oss << " next_correlation_id=" << next_correlation_id;
  }
  Logger::Info(oss.str());
}

}  // namespace retrovue::util
