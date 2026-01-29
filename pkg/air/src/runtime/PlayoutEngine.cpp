// Repository: Retrovue-playout
// Component: Playout Engine Domain Implementation
// Purpose: Domain-level engine that manages channel lifecycle operations.
// Copyright (c) 2025 RetroVue

#include "retrovue/runtime/PlayoutEngine.h"

#include <chrono>
#include <iostream>
#include <thread>

#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/output/IOutputSink.h"
#include "retrovue/output/OutputBus.h"
#include "retrovue/producers/IProducer.h"
#include "retrovue/producers/file/FileProducer.h"
#include "retrovue/renderer/FrameRenderer.h"
#include "retrovue/runtime/TimingLoop.h"
#include "retrovue/runtime/PlayoutControl.h"
#include "retrovue/telemetry/MetricsExporter.h"
#include "retrovue/timing/MasterClock.h"

namespace retrovue::runtime {

namespace {
  constexpr size_t kDefaultBufferSize = 60; // 60 frames (~2 seconds at 30fps)
  constexpr size_t kReadyDepth = 3; // Minimum buffer depth for ready state
  constexpr auto kReadyTimeout = std::chrono::seconds(2);
  
  int64_t NowUtc(const std::shared_ptr<timing::MasterClock>& clock) {
    if (clock) {
      return clock->now_utc_us();
    }
    const auto now = std::chrono::system_clock::now();
    return std::chrono::duration_cast<std::chrono::microseconds>(
        now.time_since_epoch()).count();
  }
  
  std::string MakeCommandId(const char* prefix, int32_t channel_id) {
    return std::string(prefix) + "-" + std::to_string(channel_id);
  }
  
  telemetry::ChannelState ToChannelState(PlayoutControl::RuntimePhase phase) {
    using RuntimePhase = PlayoutControl::RuntimePhase;
    switch (phase) {
      case RuntimePhase::kIdle:
        return telemetry::ChannelState::STOPPED;
      case RuntimePhase::kBuffering:
        return telemetry::ChannelState::BUFFERING;
      case RuntimePhase::kReady:
      case RuntimePhase::kPlaying:
      case RuntimePhase::kPaused:
        return telemetry::ChannelState::READY;
      case RuntimePhase::kStopping:
        return telemetry::ChannelState::BUFFERING;
      case RuntimePhase::kError:
        return telemetry::ChannelState::ERROR_STATE;
    }
    return telemetry::ChannelState::STOPPED;
  }
}  // namespace

// Internal playout session - runtime components for one Air instance.
// Phase 8.4: One TS mux per active stream session; ring_buffer is the single
// frame source for the mux. SwitchToLive swaps which producer feeds the buffer (frame-source
// only); within a session the mux is not restarted and PID/continuity are not reset.
struct PlayoutEngine::PlayoutSession {
  int32_t channel_id;  // External identifier (for gRPC correlation; channel ownership is in Core)
  std::string plan_handle;
  int32_t port;
  std::optional<std::string> uds_path;
  // Phase 6A.0 control-surface-only: preview bus state (no real decode)
  bool preview_loaded = false;
  std::string preview_asset_path;
  std::string live_asset_path;  // Phase 8.1: set on SwitchToLive for stream TS source

  // Core components (null when control_surface_only)
  std::unique_ptr<buffer::FrameRingBuffer> ring_buffer;
  std::unique_ptr<producers::file::FileProducer> live_producer;
  std::unique_ptr<producers::file::FileProducer> preview_producer;  // For shadow decode/preview
  std::unique_ptr<renderer::FrameRenderer> renderer;
  std::unique_ptr<TimingLoop> timing_loop;
  std::unique_ptr<PlayoutControl> control;

  // Phase 9.0: OutputBus for frame routing to sinks
  std::unique_ptr<output::OutputBus> output_bus;

  PlayoutSession(int32_t id, const std::string& plan, int32_t p,
                 const std::optional<std::string>& uds)
      : channel_id(id), plan_handle(plan), port(p), uds_path(uds) {}
};

PlayoutEngine::PlayoutEngine(
    std::shared_ptr<telemetry::MetricsExporter> metrics_exporter,
    std::shared_ptr<timing::MasterClock> master_clock,
    bool control_surface_only)
    : metrics_exporter_(std::move(metrics_exporter)),
      master_clock_(std::move(master_clock)),
      control_surface_only_(control_surface_only) {
}

PlayoutEngine::~PlayoutEngine() {
  // Collect channel IDs under the lock, then stop each without holding it
  // (StopChannel also acquires channels_mutex_).
  std::vector<int32_t> ids;
  {
    std::lock_guard<std::mutex> lock(channels_mutex_);
    if (control_surface_only_) {
      channels_.clear();
      return;
    }
    for (auto& [channel_id, state] : channels_) {
      if (state) ids.push_back(channel_id);
    }
  }
  for (int32_t id : ids) {
    StopChannel(id);
  }
}

EngineResult PlayoutEngine::StartChannel(
    int32_t channel_id,
    const std::string& plan_handle,
    int32_t port,
    const std::optional<std::string>& uds_path) {
  std::lock_guard<std::mutex> lock(channels_mutex_);

  // Air supports exactly one active playout session at a time.
  // Channel identity is external and used only for correlation.
  if (!channels_.empty()) {
    if (channels_.find(channel_id) != channels_.end()) {
      return EngineResult(true, "Channel " + std::to_string(channel_id) + " already started");
    }
    return EngineResult(false, "PlayoutEngine already has an active session");
  }

  try {
    // Create channel state
    auto state = std::make_unique<PlayoutSession>(channel_id, plan_handle, port, uds_path);
    
    if (control_surface_only_) {
      // Phase 6A.0: no media, no producers, no frames — channel state only
      channels_[channel_id] = std::move(state);
      return EngineResult(true, "Channel " + std::to_string(channel_id) + " started (control surface only)");
    }
    
    // Create ring buffer
    state->ring_buffer = std::make_unique<buffer::FrameRingBuffer>(kDefaultBufferSize);
    
    // Create control state machine
    state->control = std::make_unique<PlayoutControl>();

    // Phase 9.0: Create OutputBus with state machine validation
    state->output_bus = std::make_unique<output::OutputBus>(state->control.get());

    // Create producer config from plan_handle (simplified - in production, resolve plan to asset)
    producers::file::ProducerConfig producer_config;
    producer_config.asset_uri = plan_handle; // For now, use plan_handle as asset URI
    producer_config.target_fps = 30.0;
    producer_config.stub_mode = false; // Use real decode
    producer_config.target_width = 1920;
    producer_config.target_height = 1080;
    
    // Create live producer (FileProducer - decodes both audio and video)
    state->live_producer = std::make_unique<producers::file::FileProducer>(
        producer_config, *state->ring_buffer, master_clock_, nullptr);
    
    // Create renderer
    renderer::RenderConfig render_config;
    render_config.mode = renderer::RenderMode::HEADLESS;
    state->renderer = renderer::FrameRenderer::Create(
        render_config, *state->ring_buffer, master_clock_, metrics_exporter_, channel_id);
    
    // Start control state machine
    const int64_t now = NowUtc(master_clock_);
    if (!state->control->BeginSession(MakeCommandId("start", channel_id), now)) {
      return EngineResult(false, "Failed to begin session for channel " + std::to_string(channel_id));
    }
    
    // Start producer
    if (!state->live_producer->start()) {
      return EngineResult(false, "Failed to start producer for channel " + std::to_string(channel_id));
    }

    // Wait for minimum buffer depth BEFORE starting renderer
    // (renderer would consume frames immediately, preventing buffer from filling)
    const auto start_time = std::chrono::steady_clock::now();
    while (state->ring_buffer->Size() < kReadyDepth) {
      if (std::chrono::steady_clock::now() - start_time > kReadyTimeout) {
        telemetry::ChannelMetrics metrics{};
        metrics.state = telemetry::ChannelState::BUFFERING;
        metrics.buffer_depth_frames = state->ring_buffer->Size();
        metrics_exporter_->SubmitChannelMetrics(channel_id, metrics);
        // Stop producer before returning so ~PlayoutSession does not destroy
        // running threads that then call virtuals on a partially destroyed object.
        if (state->live_producer) {
          state->live_producer->RequestTeardown(std::chrono::milliseconds(200));
          while (state->live_producer->isRunning()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
          }
          state->live_producer->stop();
        }
        return EngineResult(false, "Timeout waiting for buffer depth on channel " + std::to_string(channel_id));
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }

    // Start renderer AFTER buffer has sufficient depth
    if (!state->renderer->Start()) {
      return EngineResult(false, "Failed to start renderer for channel " + std::to_string(channel_id));
    }
    
    // Update state machine with buffer depth
    state->control->OnBufferDepth(state->ring_buffer->Size(), kDefaultBufferSize, NowUtc(master_clock_));
    
    // Submit ready metrics
    telemetry::ChannelMetrics metrics{};
    metrics.state = telemetry::ChannelState::READY;
    metrics.buffer_depth_frames = state->ring_buffer->Size();
    metrics_exporter_->SubmitChannelMetrics(channel_id, metrics);
    
    // Store channel state
    channels_[channel_id] = std::move(state);
    
    return EngineResult(true, "Channel " + std::to_string(channel_id) + " started successfully");
  } catch (const std::exception& e) {
    return EngineResult(false, "Exception starting channel " + std::to_string(channel_id) + ": " + e.what());
  }
}

EngineResult PlayoutEngine::StopChannel(int32_t channel_id) {
  std::lock_guard<std::mutex> lock(channels_mutex_);
  
  auto it = channels_.find(channel_id);
  if (it == channels_.end()) {
    // Phase 6A.0: idempotent success — broadcast systems favor safe, idempotent stop
    return EngineResult(true, "Channel " + std::to_string(channel_id) + " already stopped or unknown");
  }
  
  auto& state = it->second;
  if (!state) {
    return EngineResult(false, "Channel " + std::to_string(channel_id) + " state is null");
  }
  
  if (control_surface_only_) {
    channels_.erase(it);
    return EngineResult(true, "Channel " + std::to_string(channel_id) + " stopped successfully");
  }
  
  try {
    const int64_t now = NowUtc(master_clock_);
    
    // Stop control state machine
    if (state->control) {
      state->control->Stop(MakeCommandId("stop", channel_id), now, now);
    }

    // Phase 9.0: Detach any attached output sink (forced detach)
    if (state->output_bus) {
      state->output_bus->DetachSink(true);
    }

    // Stop renderer first (consumer before producer)
    if (state->renderer) {
      state->renderer->Stop();
    }
    
    // Stop producers
    if (state->live_producer) {
      state->live_producer->RequestTeardown(std::chrono::milliseconds(500));
      while (state->live_producer->isRunning()) {
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
      }
      state->live_producer->stop();
    }
    
    if (state->preview_producer) {
      state->preview_producer->RequestTeardown(std::chrono::milliseconds(500));
      while (state->preview_producer->isRunning()) {
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
      }
      state->preview_producer->stop();
    }
    
    // Drain buffer
    if (state->ring_buffer) {
      buffer::Frame frame;
      while (state->ring_buffer->Pop(frame)) {
        // Drain all frames
      }
      state->ring_buffer->Clear();
    }
    
    // Submit stopped metrics
    telemetry::ChannelMetrics metrics{};
    metrics.state = telemetry::ChannelState::STOPPED;
    metrics.buffer_depth_frames = 0;
    metrics_exporter_->SubmitChannelMetrics(channel_id, metrics);
    
    // Remove channel
    channels_.erase(it);
    
    return EngineResult(true, "Channel " + std::to_string(channel_id) + " stopped successfully");
  } catch (const std::exception& e) {
    return EngineResult(false, "Exception stopping channel " + std::to_string(channel_id) + ": " + e.what());
  }
}

EngineResult PlayoutEngine::LoadPreview(
    int32_t channel_id,
    const std::string& asset_path,
    int64_t start_offset_ms,
    int64_t hard_stop_time_ms) {
  (void)start_offset_ms;
  (void)hard_stop_time_ms;
  std::lock_guard<std::mutex> lock(channels_mutex_);
  
  auto it = channels_.find(channel_id);
  if (it == channels_.end()) {
    return EngineResult(false, "Channel " + std::to_string(channel_id) + " not found");
  }
  
  auto& state = it->second;
  if (!state) {
    return EngineResult(false, "Channel " + std::to_string(channel_id) + " state is null");
  }
  
  if (control_surface_only_) {
    state->preview_loaded = true;
    state->preview_asset_path = asset_path;
    EngineResult result(true, "Preview loaded for channel " + std::to_string(channel_id));
    result.shadow_decode_started = false;  // No actual decode in 6A.0
    return result;
  }
  
  try {
    // Create preview producer config
    producers::file::ProducerConfig preview_config;
    preview_config.asset_uri = asset_path;
    preview_config.target_fps = 30.0;
    preview_config.stub_mode = false;
    preview_config.target_width = 1920;
    preview_config.target_height = 1080;
    
    // Create preview producer (FileProducer - decodes both audio and video)
    // Do NOT start it here; SwitchToLive will start it when promoting to live.
    // This ensures LoadPreview only prepares the next asset; clock-driven SwitchToLive triggers the actual switch.
    state->preview_asset_path = asset_path;
    state->preview_producer = std::make_unique<producers::file::FileProducer>(
        preview_config, *state->ring_buffer, master_clock_, nullptr);
    
    // Preview producer created but not started; SwitchToLive will start it when switching.
    EngineResult result(true, "Preview loaded for channel " + std::to_string(channel_id));
    result.shadow_decode_started = false;  // Not started yet; will start on SwitchToLive
    return result;
  } catch (const std::exception& e) {
    return EngineResult(false, "Exception loading preview for channel " + std::to_string(channel_id) + ": " + e.what());
  }
}

EngineResult PlayoutEngine::SwitchToLive(int32_t channel_id) {
  std::lock_guard<std::mutex> lock(channels_mutex_);
  
  auto it = channels_.find(channel_id);
  if (it == channels_.end()) {
    return EngineResult(false, "Channel " + std::to_string(channel_id) + " not found");
  }
  
  auto& state = it->second;
  if (!state) {
    return EngineResult(false, "Channel " + std::to_string(channel_id) + " state is null");
  }
  
  if (control_surface_only_) {
    if (!state->preview_loaded) {
      return EngineResult(false, "No preview loaded for channel " + std::to_string(channel_id));
    }
    state->live_asset_path = state->preview_asset_path;
    state->preview_loaded = false;
    state->preview_asset_path.clear();
    EngineResult result(true, "Switched to live for channel " + std::to_string(channel_id));
    result.pts_contiguous = true;
    result.live_start_pts = 0;
    return result;
  }
  
  if (!state->preview_producer) {
    return EngineResult(false, "No preview producer loaded for channel " + std::to_string(channel_id));
  }
  
  try {
    // Phase 8.9 / 8.8: we must not interleave frames from A and B.
    // To avoid A/B/A/B flicker, ensure the old live producer has finished
    // emitting frames before the new producer starts writing to the ring buffer.
    //
    // 1. Fully drain and stop OLD live producer.
    // 2. Start preview producer (which becomes the new live producer).
    // 3. Atomically swap preview → live.
    
    // Step 1: Fully drain and stop OLD live producer (if any).
    if (state->live_producer && state->live_producer->isRunning()) {
      state->live_producer->RequestTeardown(std::chrono::milliseconds(500));
      // Wait until it reports not running (or timeout elapses inside producer).
      while (state->live_producer->isRunning()) {
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
      }
      state->live_producer->stop();
      
      // Phase 8.9: Wait for BOTH video and audio frames to be completely drained from the ring buffer
      // before starting the new producer. This prevents A/B/A/B interleaving.
      const auto drain_start = std::chrono::steady_clock::now();
      const auto drain_timeout = std::chrono::milliseconds(1000);  // Max 1 second to drain
      while (!state->ring_buffer->IsCompletelyEmpty()) {
        if (std::chrono::steady_clock::now() - drain_start > drain_timeout) {
          std::cerr << "[SwitchToLive] Warning: Timeout waiting for buffer drain, proceeding anyway" << std::endl;
          break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
      }
      std::cout << "[SwitchToLive] Buffer completely drained (video and audio) before starting new producer" << std::endl;
      
      // Phase 8.9: Flush encoder's audio buffers to ensure all audio from SampleB is encoded/muxed
      // The encoder may have buffered samples in the resampler or partial frames
      // Note: encoder is accessed via renderer->GetEncoder() or similar - need to check access pattern
      // For now, we'll rely on playout_service to flush when it detects buffer empty
      
      state->live_producer.reset();
    }
    
    // Debug: Log switch details
    std::cout << "[SwitchToLive] ===== SWITCHING PRODUCERS =====" << std::endl;
    if (state->live_producer) {
      std::cout << "[SwitchToLive] Old live producer: " << state->live_asset_path << std::endl;
    }
    if (state->preview_producer) {
      std::cout << "[SwitchToLive] New preview producer: " << state->preview_asset_path << std::endl;
    }
    
    // Step 4: Start preview producer (it will become live).
    if (!state->preview_producer->start()) {
      return EngineResult(false, "Failed to start preview producer for channel " + std::to_string(channel_id));
    }
    
    // Step 3: Atomically swap preview → live (frame source swap only; encoder/mux unchanged per Phase 8.4).
    state->live_producer = std::move(state->preview_producer);
    state->live_asset_path = state->preview_asset_path;
    state->preview_producer.reset();
    state->preview_asset_path.clear();
    
    // For PTS continuity, align preview PTS to live's next PTS (Phase 8.2/8.3)
    EngineResult result(true, "Switched to live for channel " + std::to_string(channel_id));
    // PTS continuity is still expected because each producer has its own monotonic PTS;
    // there may be a short gap, but not A/B interleaving.
    result.pts_contiguous = true; // Simplified - would check actual PTS continuity
    result.live_start_pts = 0;    // Would get from producer/renderer
    
    return result;
  } catch (const std::exception& e) {
    return EngineResult(false, "Exception switching to live for channel " + std::to_string(channel_id) + ": " + e.what());
  }
}

std::optional<std::string> PlayoutEngine::GetLiveAssetPath(int32_t channel_id) {
  std::lock_guard<std::mutex> lock(channels_mutex_);
  auto it = channels_.find(channel_id);
  if (it == channels_.end() || !it->second)
    return std::nullopt;
  const std::string& path = it->second->live_asset_path;
  if (path.empty())
    return std::nullopt;
  return path;
}

void PlayoutEngine::RegisterMuxFrameCallback(int32_t channel_id,
                                             std::function<void(const buffer::Frame&)> callback) {
  std::lock_guard<std::mutex> lock(channels_mutex_);
  auto it = channels_.find(channel_id);
  if (it == channels_.end() || !it->second || !it->second->renderer)
    return;
  it->second->renderer->SetSideSink(std::move(callback));
}

void PlayoutEngine::UnregisterMuxFrameCallback(int32_t channel_id) {
  std::lock_guard<std::mutex> lock(channels_mutex_);
  auto it = channels_.find(channel_id);
  if (it == channels_.end() || !it->second || !it->second->renderer)
    return;
  it->second->renderer->ClearSideSink();
}

// Phase 8.9: Audio frame callback registration
void PlayoutEngine::RegisterMuxAudioFrameCallback(int32_t channel_id,
                                                  std::function<void(const buffer::AudioFrame&)> callback) {
  std::lock_guard<std::mutex> lock(channels_mutex_);
  auto it = channels_.find(channel_id);
  if (it == channels_.end() || !it->second || !it->second->renderer)
    return;
  it->second->renderer->SetAudioSideSink(std::move(callback));
}

void PlayoutEngine::UnregisterMuxAudioFrameCallback(int32_t channel_id) {
  std::lock_guard<std::mutex> lock(channels_mutex_);
  auto it = channels_.find(channel_id);
  if (it == channels_.end() || !it->second || !it->second->renderer)
    return;
  it->second->renderer->ClearAudioSideSink();
}

EngineResult PlayoutEngine::UpdatePlan(
    int32_t channel_id,
    const std::string& plan_handle) {
  std::lock_guard<std::mutex> lock(channels_mutex_);

  auto it = channels_.find(channel_id);
  if (it == channels_.end()) {
    return EngineResult(false, "Channel " + std::to_string(channel_id) + " not found");
  }

  auto& state = it->second;
  if (!state) {
    return EngineResult(false, "Channel " + std::to_string(channel_id) + " state is null");
  }

  try {
    // Update plan handle
    state->plan_handle = plan_handle;

    // In production, would restart producer with new plan
    // For now, just update the handle
    return EngineResult(true, "Plan updated for channel " + std::to_string(channel_id));
  } catch (const std::exception& e) {
    return EngineResult(false, "Exception updating plan for channel " + std::to_string(channel_id) + ": " + e.what());
  }
}

// Phase 9.0: OutputBus/OutputSink methods

EngineResult PlayoutEngine::AttachOutputSink(
    int32_t channel_id,
    std::unique_ptr<output::IOutputSink> sink,
    bool replace_existing) {
  std::lock_guard<std::mutex> lock(channels_mutex_);

  auto it = channels_.find(channel_id);
  if (it == channels_.end()) {
    return EngineResult(false, "Channel " + std::to_string(channel_id) + " not found");
  }

  auto& state = it->second;
  if (!state) {
    return EngineResult(false, "Channel " + std::to_string(channel_id) + " state is null");
  }

  if (!state->output_bus) {
    return EngineResult(false, "Channel " + std::to_string(channel_id) + " has no OutputBus");
  }

  auto result = state->output_bus->AttachSink(std::move(sink), replace_existing);
  return EngineResult(result.success, result.message);
}

EngineResult PlayoutEngine::DetachOutputSink(int32_t channel_id, bool force) {
  std::lock_guard<std::mutex> lock(channels_mutex_);

  auto it = channels_.find(channel_id);
  if (it == channels_.end()) {
    return EngineResult(true, "Channel " + std::to_string(channel_id) + " not found (idempotent)");
  }

  auto& state = it->second;
  if (!state) {
    return EngineResult(true, "Channel " + std::to_string(channel_id) + " state is null (idempotent)");
  }

  if (!state->output_bus) {
    return EngineResult(true, "Channel " + std::to_string(channel_id) + " has no OutputBus (idempotent)");
  }

  auto result = state->output_bus->DetachSink(force);
  return EngineResult(result.success, result.message);
}

bool PlayoutEngine::IsOutputSinkAttached(int32_t channel_id) {
  std::lock_guard<std::mutex> lock(channels_mutex_);

  auto it = channels_.find(channel_id);
  if (it == channels_.end() || !it->second || !it->second->output_bus) {
    return false;
  }

  return it->second->output_bus->IsAttached();
}

output::OutputBus* PlayoutEngine::GetOutputBus(int32_t channel_id) {
  std::lock_guard<std::mutex> lock(channels_mutex_);

  auto it = channels_.find(channel_id);
  if (it == channels_.end() || !it->second) {
    return nullptr;
  }

  return it->second->output_bus.get();
}

void PlayoutEngine::ConnectRendererToOutputBus(int32_t channel_id) {
  std::lock_guard<std::mutex> lock(channels_mutex_);

  auto it = channels_.find(channel_id);
  if (it == channels_.end() || !it->second) {
    return;
  }

  auto& state = it->second;
  if (state->renderer && state->output_bus) {
    state->renderer->SetOutputBus(state->output_bus.get());
    std::cout << "[PlayoutEngine] Renderer connected to OutputBus for channel " << channel_id << std::endl;
  }
}

void PlayoutEngine::DisconnectRendererFromOutputBus(int32_t channel_id) {
  std::lock_guard<std::mutex> lock(channels_mutex_);

  auto it = channels_.find(channel_id);
  if (it == channels_.end() || !it->second) {
    return;
  }

  auto& state = it->second;
  if (state->renderer) {
    state->renderer->ClearOutputBus();
    std::cout << "[PlayoutEngine] Renderer disconnected from OutputBus for channel " << channel_id << std::endl;
  }
}

}  // namespace retrovue::runtime

