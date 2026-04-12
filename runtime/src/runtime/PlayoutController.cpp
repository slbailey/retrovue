// Repository: Retrovue-playout
// Component: Playout Controller Implementation
// Purpose: High-level controller that orchestrates channel lifecycle operations.
// Copyright (c) 2025 RetroVue

#include "retrovue/runtime/PlayoutController.h"

#include "retrovue/output/IOutputSink.h"
#include "retrovue/output/OutputBus.h"
#include "retrovue/runtime/PlayoutEngine.h"

namespace retrovue::runtime {

PlayoutController::PlayoutController(std::shared_ptr<PlayoutEngine> engine)
    : engine_(std::move(engine)) {
}

PlayoutController::~PlayoutController() = default;

ControllerResult PlayoutController::StartChannel(
    int32_t channel_id,
    const std::string& plan_handle,
    int32_t port,
    const std::optional<std::string>& uds_path) {
  // Delegate to domain engine
  auto result = engine_->StartChannel(channel_id, plan_handle, port, uds_path);
  ControllerResult controller_result(result.success, result.message);
  return controller_result;
}

ControllerResult PlayoutController::StopChannel(int32_t channel_id) {
  // Delegate to domain engine
  auto result = engine_->StopChannel(channel_id);
  return ControllerResult(result.success, result.message);
}

ControllerResult PlayoutController::LoadPreview(
    int32_t channel_id,
    const std::string& asset_path,
    int64_t start_offset_ms,
    int64_t hard_stop_time_ms) {
  // Delegate to domain engine
  auto result = engine_->LoadPreview(channel_id, asset_path, start_offset_ms, hard_stop_time_ms);
  ControllerResult controller_result(result.success, result.message);
  controller_result.shadow_decode_started = result.shadow_decode_started;
  return controller_result;
}

ControllerResult PlayoutController::SwitchToLive(int32_t channel_id) {
  // Delegate to domain engine
  auto result = engine_->SwitchToLive(channel_id);
  ControllerResult controller_result(result.success, result.message);
  controller_result.pts_contiguous = result.pts_contiguous;
  controller_result.live_start_pts = result.live_start_pts;
  return controller_result;
}

std::optional<std::string> PlayoutController::GetLiveAssetPath(int32_t channel_id) {
  return engine_->GetLiveAssetPath(channel_id);
}

void PlayoutController::RegisterMuxFrameCallback(int32_t channel_id,
                                                 std::function<void(const buffer::Frame&)> callback) {
  engine_->RegisterMuxFrameCallback(channel_id, std::move(callback));
}

void PlayoutController::UnregisterMuxFrameCallback(int32_t channel_id) {
  engine_->UnregisterMuxFrameCallback(channel_id);
}

// Phase 8.9: Audio frame callback registration
void PlayoutController::RegisterMuxAudioFrameCallback(int32_t channel_id,
                                                      std::function<void(const buffer::AudioFrame&)> callback) {
  engine_->RegisterMuxAudioFrameCallback(channel_id, std::move(callback));
}

void PlayoutController::UnregisterMuxAudioFrameCallback(int32_t channel_id) {
  engine_->UnregisterMuxAudioFrameCallback(channel_id);
}

ControllerResult PlayoutController::UpdatePlan(
    int32_t channel_id,
    const std::string& plan_handle) {
  // Delegate to domain engine
  auto result = engine_->UpdatePlan(channel_id, plan_handle);
  return ControllerResult(result.success, result.message);
}

// Phase 9.0: OutputBus/OutputSink methods
ControllerResult PlayoutController::AttachOutputSink(
    int32_t channel_id,
    std::unique_ptr<output::IOutputSink> sink) {
  auto result = engine_->AttachOutputSink(channel_id, std::move(sink));
  return ControllerResult(result.success, result.message);
}

ControllerResult PlayoutController::DetachOutputSink(int32_t channel_id) {
  auto result = engine_->DetachOutputSink(channel_id);
  return ControllerResult(result.success, result.message);
}

output::OutputBus* PlayoutController::GetOutputBus(int32_t channel_id) {
  return engine_->GetOutputBus(channel_id);
}

bool PlayoutController::IsOutputSinkAttached(int32_t channel_id) {
  return engine_->IsOutputSinkAttached(channel_id);
}

void PlayoutController::ConnectRendererToOutputBus(int32_t channel_id) {
  engine_->ConnectRendererToOutputBus(channel_id);
}

void PlayoutController::DisconnectRendererFromOutputBus(int32_t channel_id) {
  engine_->DisconnectRendererFromOutputBus(channel_id);
}

}  // namespace retrovue::runtime

