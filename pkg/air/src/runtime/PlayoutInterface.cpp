// Repository: Retrovue-playout
// Component: Playout Interface Implementation
// Purpose: gRPC interface adapter that delegates to the domain engine.
// Copyright (c) 2025 RetroVue

#include "retrovue/runtime/PlayoutInterface.h"

#include "retrovue/output/IOutputSink.h"
#include "retrovue/output/OutputBus.h"
#include "retrovue/runtime/PlayoutEngine.h"
#include "retrovue/runtime/ProgramFormat.h"

namespace retrovue::runtime {

// InterfaceResult constructor - must be in cpp because ResultCode is forward-declared
InterfaceResult::InterfaceResult(bool s, const std::string& msg)
    : success(s), message(msg), result_code(ResultCode::kUnspecified) {}

PlayoutInterface::PlayoutInterface(std::shared_ptr<PlayoutEngine> engine)
    : engine_(std::move(engine)) {
}

PlayoutInterface::~PlayoutInterface() = default;

InterfaceResult PlayoutInterface::StartChannel(
    int32_t channel_id,
    const std::string& plan_handle,
    int32_t port,
    const std::optional<std::string>& uds_path,
    const std::string& program_format_json) {
  // Delegate to domain engine
  auto result = engine_->StartChannel(channel_id, plan_handle, port, uds_path, program_format_json);
  InterfaceResult interface_result(result.success, result.message);
  return interface_result;
}

InterfaceResult PlayoutInterface::StopChannel(int32_t channel_id) {
  // Delegate to domain engine
  auto result = engine_->StopChannel(channel_id);
  return InterfaceResult(result.success, result.message);
}

InterfaceResult PlayoutInterface::LoadPreview(
    int32_t channel_id,
    const std::string& asset_path,
    int64_t start_frame,
    int64_t frame_count,
    int32_t fps_numerator,
    int32_t fps_denominator) {
  // Delegate to domain engine (frame-indexed execution INV-FRAME-001/002/003)
  auto result = engine_->LoadPreview(channel_id, asset_path, start_frame, frame_count, fps_numerator, fps_denominator);
  InterfaceResult interface_result(result.success, result.message);
  interface_result.shadow_decode_started = result.shadow_decode_started;
  interface_result.result_code = result.result_code;  // Phase 8: Forward typed result
  return interface_result;
}

InterfaceResult PlayoutInterface::SwitchToLive(int32_t channel_id) {
  // Delegate to domain engine
  auto result = engine_->SwitchToLive(channel_id);
  InterfaceResult interface_result(result.success, result.message);
  interface_result.pts_contiguous = result.pts_contiguous;
  interface_result.live_start_pts = result.live_start_pts;
  interface_result.result_code = result.result_code;  // Phase 8: Forward typed result
  return interface_result;
}

std::optional<std::string> PlayoutInterface::GetLiveAssetPath(int32_t channel_id) {
  return engine_->GetLiveAssetPath(channel_id);
}

void PlayoutInterface::RegisterMuxFrameCallback(int32_t channel_id,
                                                 std::function<void(const buffer::Frame&)> callback) {
  engine_->RegisterMuxFrameCallback(channel_id, std::move(callback));
}

void PlayoutInterface::UnregisterMuxFrameCallback(int32_t channel_id) {
  engine_->UnregisterMuxFrameCallback(channel_id);
}

// Phase 8.9: Audio frame callback registration
void PlayoutInterface::RegisterMuxAudioFrameCallback(int32_t channel_id,
                                                      std::function<void(const buffer::AudioFrame&)> callback) {
  engine_->RegisterMuxAudioFrameCallback(channel_id, std::move(callback));
}

void PlayoutInterface::UnregisterMuxAudioFrameCallback(int32_t channel_id) {
  engine_->UnregisterMuxAudioFrameCallback(channel_id);
}

InterfaceResult PlayoutInterface::UpdatePlan(
    int32_t channel_id,
    const std::string& plan_handle) {
  // Delegate to domain engine
  auto result = engine_->UpdatePlan(channel_id, plan_handle);
  return InterfaceResult(result.success, result.message);
}

// Phase 9.0: OutputBus/OutputSink methods
InterfaceResult PlayoutInterface::AttachOutputSink(
    int32_t channel_id,
    std::unique_ptr<output::IOutputSink> sink,
    bool replace_existing) {
  auto result = engine_->AttachOutputSink(channel_id, std::move(sink), replace_existing);
  return InterfaceResult(result.success, result.message);
}

InterfaceResult PlayoutInterface::DetachOutputSink(int32_t channel_id, bool force) {
  auto result = engine_->DetachOutputSink(channel_id, force);
  return InterfaceResult(result.success, result.message);
}

output::OutputBus* PlayoutInterface::GetOutputBus(int32_t channel_id) {
  return engine_->GetOutputBus(channel_id);
}

std::optional<ProgramFormat> PlayoutInterface::GetProgramFormat(int32_t channel_id) {
  return engine_->GetProgramFormat(channel_id);
}

bool PlayoutInterface::IsOutputSinkAttached(int32_t channel_id) {
  return engine_->IsOutputSinkAttached(channel_id);
}

void PlayoutInterface::ConnectRendererToOutputBus(int32_t channel_id) {
  engine_->ConnectRendererToOutputBus(channel_id);
}

void PlayoutInterface::DisconnectRendererFromOutputBus(int32_t channel_id) {
  engine_->DisconnectRendererFromOutputBus(channel_id);
}

}  // namespace retrovue::runtime
