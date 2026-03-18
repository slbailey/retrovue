// Repository: Retrovue-playout
// Component: ObservabilityLogger — LAW-OBS-001 through LAW-OBS-005 enforcement
// Purpose: Emit canonical AIR-INTENT-* and AIR-CLAMP-* log events with field
//          validation.  Violation conditions produce Logger::Error entries with
//          invariant ID tags so that contract tests can assert them via the
//          Logger::SetErrorSink / Logger::SetTestSink hooks.
// Contract: pkg/air/docs/contracts/laws/ObservabilityParityLaw.md
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_UTIL_OBSERVABILITY_LOGGER_HPP_
#define RETROVUE_UTIL_OBSERVABILITY_LOGGER_HPP_

#include <string>

namespace retrovue::util {

// ---------------------------------------------------------------------------
// LAW-OBS-001 / LAW-OBS-002 / LAW-OBS-003 / LAW-OBS-004
// ---------------------------------------------------------------------------

// LogIntentReceived — emit AIR-INTENT-RECEIVED.
//
// Violation enforcement:
//   LAW-OBS-001-VIOLATED  — rpc is empty (intent not observable)
//   LAW-OBS-002-VIOLATED  — correlation_id is empty
//   LAW-OBS-004-VIOLATED  — receipt_time_ms == 0 (timing evidence absent for timed RPCs)
void LogIntentReceived(
    const std::string& correlation_id,
    const std::string& rpc,
    int32_t            channel_id,
    int64_t            receipt_time_ms,
    const std::string& asset_path          = {},
    int64_t            start_frame         = 0,
    int64_t            frame_count         = 0,
    bool               rpc_requires_timing = false);

// LogIntentResponse — emit AIR-INTENT-RESPONSE.
//
// Violation enforcement:
//   LAW-OBS-003-VIOLATED  — correlation_id or result_code absent
//   LAW-OBS-004-VIOLATED  — completion_time_ms == 0 (timing evidence absent for timed RPCs)
void LogIntentResponse(
    const std::string& correlation_id,
    const std::string& rpc,
    int32_t            channel_id,
    bool               success,
    const std::string& result_code,
    const std::string& message,
    int64_t            completion_time_ms,
    bool               rpc_requires_timing = false);

// LogLoadPreviewEffective — emit AIR-LOADPREVIEW-EFFECTIVE.
void LogLoadPreviewEffective(
    const std::string& correlation_id,
    int32_t            channel_id,
    const std::string& asset_path,
    int64_t            effective_time_ms);

// LogSwitchToLiveEffective — emit AIR-SWITCHTOLIVE-EFFECTIVE.
void LogSwitchToLiveEffective(
    const std::string& correlation_id,
    int32_t            channel_id,
    int64_t            effective_time_ms);

// ---------------------------------------------------------------------------
// LAW-OBS-005
// ---------------------------------------------------------------------------

// LogClampStarted — emit AIR-CLAMP-STARTED.
// Violation: LAW-OBS-005-VIOLATED if channel_id==0, asset_path empty, or boundary_ms==0
void LogClampStarted(
    const std::string& correlation_id,
    int32_t            channel_id,
    const std::string& asset_path,
    int64_t            boundary_ms,
    const std::string& segment_correlation_id = {});

// LogClampActive — emit AIR-CLAMP-ACTIVE (heartbeat).
void LogClampActive(
    int32_t            channel_id,
    const std::string& asset_path,
    int64_t            boundary_ms,
    int64_t            clamp_duration_ms);

// LogClampEnded — emit AIR-CLAMP-ENDED.
// Violation: LAW-OBS-005-VIOLATED if channel_id==0, asset_path empty, or boundary_ms==0
void LogClampEnded(
    int32_t            channel_id,
    const std::string& asset_path,
    int64_t            boundary_ms,
    const std::string& next_correlation_id = {});

}  // namespace retrovue::util

#endif  // RETROVUE_UTIL_OBSERVABILITY_LOGGER_HPP_
