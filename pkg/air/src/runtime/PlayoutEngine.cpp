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
#include "retrovue/renderer/ProgramOutput.h"
#include "retrovue/runtime/ProgramFormat.h"
#include "retrovue/runtime/TimingLoop.h"
#include "retrovue/runtime/PlayoutControl.h"
#include "retrovue/telemetry/MetricsExporter.h"
#include "retrovue/timing/MasterClock.h"
#include "retrovue/timing/TimelineController.h"

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
struct PlayoutEngine::PlayoutInstance {
  int32_t channel_id;  // External identifier (for gRPC correlation; channel ownership is in Core)
  std::string plan_handle;
  int32_t port;
  std::optional<std::string> uds_path;
  ProgramFormat program_format;  // Canonical per-channel signal format (fixed for instance lifetime)
  // Phase 6A.0 control-surface-only: preview bus state (no real decode)
  bool preview_loaded = false;
  std::string preview_asset_path;
  std::string live_asset_path;  // Phase 8.1: set on SwitchToLive for stream TS source

  // Core components (null when control_surface_only)
  std::unique_ptr<buffer::FrameRingBuffer> ring_buffer;
  std::unique_ptr<buffer::FrameRingBuffer> preview_ring_buffer;  // Separate buffer for preview pre-fill
  std::unique_ptr<producers::file::FileProducer> live_producer;
  std::unique_ptr<producers::file::FileProducer> preview_producer;  // For shadow decode/preview
  std::unique_ptr<renderer::ProgramOutput> program_output;
  std::unique_ptr<TimingLoop> timing_loop;
  std::unique_ptr<PlayoutControl> control;

  // Phase 9.0: OutputBus for frame routing to sinks
  std::unique_ptr<output::OutputBus> output_bus;

  // Phase 8: Timeline Controller for unified time authority
  std::unique_ptr<timing::TimelineController> timeline_controller;

  PlayoutInstance(int32_t id, const std::string& plan, int32_t p,
                 const std::optional<std::string>& uds, const ProgramFormat& format)
      : channel_id(id), plan_handle(plan), port(p), uds_path(uds), program_format(format) {}
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
    const std::optional<std::string>& uds_path,
    const std::string& program_format_json) {
  std::lock_guard<std::mutex> lock(channels_mutex_);

  // Air supports exactly one active playout session at a time.
  // Channel identity is external and used only for correlation.
  if (!channels_.empty()) {
    if (channels_.find(channel_id) != channels_.end()) {
      return EngineResult(true, "Channel " + std::to_string(channel_id) + " already started");
    }
    return EngineResult(false, "PlayoutEngine already has an active session");
  }

  // Parse and validate ProgramFormat before creating any resources
  if (program_format_json.empty()) {
    return EngineResult(false, "program_format_json is required");
  }
  
  auto program_format_opt = ProgramFormat::FromJson(program_format_json);
  if (!program_format_opt) {
    return EngineResult(false, "Failed to parse or validate program_format_json");
  }
  
  const ProgramFormat& program_format = *program_format_opt;
  if (!program_format.IsValid()) {
    return EngineResult(false, "ProgramFormat validation failed");
  }

  try {
    // Create channel state with validated ProgramFormat
    auto state = std::make_unique<PlayoutInstance>(channel_id, plan_handle, port, uds_path, program_format);
    
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

    // Phase 8: Create TimelineController for unified time authority
    timing::TimelineConfig timeline_config = timing::TimelineConfig::FromFps(
        state->program_format.GetFrameRateAsDouble(), 5, 30);
    state->timeline_controller = std::make_unique<timing::TimelineController>(
        master_clock_, timeline_config);

    // Start timeline session
    if (!state->timeline_controller->StartSession()) {
      return EngineResult(false, "Failed to start timeline session for channel " + std::to_string(channel_id));
    }
    std::cout << "[PlayoutEngine] Phase 8 TimelineController started for channel " << channel_id << std::endl;

    // Phase 7 (INV-P7-001): Epoch is established by first live producer.
    // The first live producer will set epoch = playback_start - first_frame_pts
    // via TrySetEpochOnce(). Subsequent producers (preview) will be blocked.
    // Note: ResetEpochForNewSession() is called in StopChannel(), not here,
    // so epoch persists across the channel session.

    // Create producer config from ProgramFormat (canonical signal format)
    producers::file::ProducerConfig producer_config;
    producer_config.asset_uri = plan_handle; // For now, use plan_handle as asset URI
    producer_config.target_fps = state->program_format.GetFrameRateAsDouble();
    producer_config.stub_mode = false; // Use real decode
    producer_config.target_width = state->program_format.video.width;
    producer_config.target_height = state->program_format.video.height;
    
    // Create live producer (FileProducer - decodes both audio and video)
    // Phase 8: Pass TimelineController for unified timeline authority
    state->live_producer = std::make_unique<producers::file::FileProducer>(
        producer_config, *state->ring_buffer, master_clock_, nullptr,
        state->timeline_controller.get());
    
    // Create program output
    renderer::RenderConfig render_config;
    render_config.mode = renderer::RenderMode::HEADLESS;
    state->program_output = renderer::ProgramOutput::Create(
        render_config, *state->ring_buffer, master_clock_, metrics_exporter_, channel_id);
    
    // Start control state machine
    const int64_t now = NowUtc(master_clock_);
    if (!state->control->BeginSession(MakeCommandId("start", channel_id), now)) {
      return EngineResult(false, "Failed to begin session for channel " + std::to_string(channel_id));
    }

    // Phase 8: Begin segment BEFORE starting producer.
    // MT_start will be locked on first admitted frame (prevents mapping skew).
    if (state->timeline_controller) {
      state->timeline_controller->BeginSegment(0);
      std::cout << "[PlayoutEngine] Phase 8: Segment begun, CT=0, MT pending first frame" << std::endl;
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
        // Stop producer before returning so ~PlayoutInstance does not destroy
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

    // Phase 8: Segment mapping was begun before producer start (BeginSegment).
    // MT_start was locked on first admitted frame automatically.

    // Start program output AFTER buffer has sufficient depth
    if (!state->program_output->Start()) {
      return EngineResult(false, "Failed to start program output for channel " + std::to_string(channel_id));
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

    // Stop program output first (consumer before producer)
    if (state->program_output) {
      state->program_output->Stop();
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

    // Phase 8: End timeline session
    if (state->timeline_controller) {
      state->timeline_controller->EndSession();
      std::cout << "[PlayoutEngine] Phase 8 TimelineController session ended for channel "
                << channel_id << std::endl;
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

    // Phase 7: Reset epoch for next session
    // This allows a fresh epoch to be established when the channel restarts.
    if (master_clock_) {
      master_clock_->ResetEpochForNewSession();
    }

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
    preview_config.target_fps = it->second->program_format.GetFrameRateAsDouble();
    preview_config.stub_mode = false;
    preview_config.target_width = it->second->program_format.video.width;
    preview_config.target_height = it->second->program_format.video.height;
    // Phase 6: Enable mid-segment join (seek)
    preview_config.start_offset_ms = start_offset_ms;
    preview_config.hard_stop_time_ms = hard_stop_time_ms;

    // Create separate preview buffer for pre-fill (no interleaving with live)
    bool created_new = false;
    if (!state->preview_ring_buffer) {
      state->preview_ring_buffer = std::make_unique<buffer::FrameRingBuffer>(kDefaultBufferSize);
      created_new = true;
    } else {
      state->preview_ring_buffer->Clear();
    }
    std::cout << "[LoadPreview] Preview buffer " << (created_new ? "created" : "cleared")
              << " (capacity=" << kDefaultBufferSize << ")" << std::endl;

    // Create preview producer writing to its own buffer
    // Phase 8: Pass TimelineController (will be used after shadow mode is disabled)
    state->preview_asset_path = asset_path;
    state->preview_producer = std::make_unique<producers::file::FileProducer>(
        preview_config, *state->preview_ring_buffer, master_clock_, nullptr,
        state->timeline_controller.get());

    std::cout << "[LoadPreview] Created preview producer for: " << asset_path
              << " (seek=" << start_offset_ms << "ms)" << std::endl;

    // Phase 7 (INV-P7-004): Enable shadow decode mode BEFORE starting.
    // This prevents the preview producer from resetting the master clock epoch.
    state->preview_producer->SetShadowDecodeMode(true);

    // Start preview producer to fill its buffer (shadow decode)
    if (!state->preview_producer->start()) {
      std::cerr << "[LoadPreview] FAILED to start preview producer!" << std::endl;
      return EngineResult(false, "Failed to start preview producer for channel " + std::to_string(channel_id));
    }
    std::cout << "[LoadPreview] Preview producer STARTED - now filling buffer" << std::endl;

    EngineResult result(true, "Preview loaded for channel " + std::to_string(channel_id));
    result.shadow_decode_started = true;
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
    // Per OutputSwitchingContract: hot-switch with pre-decoded readiness.
    // Preview producer has been filling preview_ring_buffer.
    // We redirect ProgramOutput to read from preview's buffer (already has frames).

    std::cout << "[SwitchToLive] === SWITCH START ===" << std::endl;
    std::cout << "[SwitchToLive] Old live: " << state->live_asset_path << std::endl;
    std::cout << "[SwitchToLive] New preview: " << state->preview_asset_path << std::endl;

    size_t old_buffer_depth = state->ring_buffer ? state->ring_buffer->Size() : 0;
    size_t preview_depth_before = state->preview_ring_buffer ? state->preview_ring_buffer->Size() : 0;
    bool preview_running = state->preview_producer && state->preview_producer->isRunning();

    std::cout << "[SwitchToLive] Old buffer depth: " << old_buffer_depth << " frames" << std::endl;
    std::cout << "[SwitchToLive] Preview buffer depth: " << preview_depth_before << " frames" << std::endl;
    std::cout << "[SwitchToLive] Preview producer running: " << (preview_running ? "YES" : "NO") << std::endl;

    // Phase 7 (P7-ARCH-003): Readiness is a precondition to switching.
    // Never switch if preview buffer is empty - would cause renderer stall.
    // Check BOTH video AND audio readiness to prevent A/V desync at boundary.
    constexpr size_t kMinPreviewVideoDepth = 2;   // At least 2 video frames
    constexpr size_t kMinPreviewAudioDepth = 5;   // ~100ms audio at typical rates

    size_t preview_audio_depth = state->preview_ring_buffer ?
        state->preview_ring_buffer->AudioSize() : 0;

    std::cout << "[SwitchToLive] Preview audio depth: " << preview_audio_depth << " frames" << std::endl;

    // Phase 7: If preview is still in shadow mode, prepare it for buffer filling.
    // This must happen BEFORE readiness check so that retries get aligned frames.
    bool is_shadow_mode = state->preview_producer->IsShadowDecodeMode();
    if (is_shadow_mode) {
      // Calculate target PTS for alignment (same logic as Step 4, but done early)
      int64_t last_emitted_pts = 0;
      int64_t target_next_pts = 0;
      if (state->program_output) {
        last_emitted_pts = state->program_output->GetLastEmittedPTS();
        if (last_emitted_pts > 0) {
          double fps = state->program_format.GetFrameRateAsDouble();
          int64_t frame_period_us = static_cast<int64_t>(1'000'000.0 / fps);
          target_next_pts = last_emitted_pts + frame_period_us;
        }
      }

      // Phase 8: If TimelineController is active, it owns CT assignment.
      // AlignPTS is bypassed - TimelineController.BeginSegment handles continuity.
      // This prevents two systems "aligning" in different layers.
      if (state->timeline_controller) {
        // Phase 8 path: TimelineController owns CT continuity
        std::cout << "[SwitchToLive] Phase 8: Skipping AlignPTS (TimelineController owns CT)"
                  << std::endl;
      } else if (target_next_pts > 0) {
        // Legacy path: AlignPTS for systems without TimelineController
        state->preview_producer->AlignPTS(target_next_pts);
        std::cout << "[SwitchToLive] Legacy PTS alignment: target=" << target_next_pts << std::endl;
      }

      // Phase 8: CRITICAL - Set write barrier on live producer BEFORE BeginSegment.
      // This prevents the live producer from emitting frames that would incorrectly
      // lock the segment mapping. Only the preview producer should lock the new mapping.
      if (state->live_producer && state->timeline_controller) {
        state->live_producer->SetWriteBarrier();
        std::cout << "[SwitchToLive] Phase 8: Write barrier set on live producer" << std::endl;
      }

      // Phase 8: Begin new segment in TimelineController
      // CT_start = current CT cursor + frame_period (for seamless continuity)
      // MT_start = locked on first admitted frame (prevents mapping skew)
      if (state->timeline_controller) {
        int64_t ct_cursor = state->timeline_controller->GetCTCursor();
        double fps = state->program_format.GetFrameRateAsDouble();
        int64_t frame_period_us = static_cast<int64_t>(1'000'000.0 / fps);
        int64_t ct_segment_start = ct_cursor + frame_period_us;
        state->timeline_controller->BeginSegment(ct_segment_start);
        std::cout << "[SwitchToLive] Phase 8 segment begun: CT_start="
                  << ct_segment_start << "us, MT pending first frame" << std::endl;
      }

      // Clear any pre-filled frames (they have wrong PTS)
      if (state->preview_ring_buffer) {
        state->preview_ring_buffer->Clear();
        std::cout << "[SwitchToLive] Cleared preview buffer (was shadow mode)" << std::endl;
      }

      // Disable shadow mode - producer will now fill buffer with aligned frames
      state->preview_producer->SetShadowDecodeMode(false);
      std::cout << "[SwitchToLive] Shadow mode disabled, buffer will now fill" << std::endl;

      // Return NOT_READY - buffer is empty, Core will retry
      EngineResult result(false, "SwitchToLive blocked: preview preparing (shadow->live transition)");
      result.error_code = "NOT_READY_PREPARING";
      return result;
    }

    if (preview_depth_before < kMinPreviewVideoDepth) {
      std::cerr << "[SwitchToLive] BLOCKED: preview video not ready (depth="
                << preview_depth_before << ", required=" << kMinPreviewVideoDepth
                << ") - P7-ARCH-003" << std::endl;
      EngineResult result(false, "SwitchToLive blocked: preview video not ready");
      result.error_code = "NOT_READY_VIDEO";
      return result;
    }

    if (preview_audio_depth < kMinPreviewAudioDepth) {
      std::cerr << "[SwitchToLive] BLOCKED: preview audio not ready (depth="
                << preview_audio_depth << ", required=" << kMinPreviewAudioDepth
                << ") - P7-ARCH-003" << std::endl;
      EngineResult result(false, "SwitchToLive blocked: preview audio not ready");
      result.error_code = "NOT_READY_AUDIO";
      return result;
    }

    std::cout << "[SwitchToLive] Readiness check PASSED (video=" << preview_depth_before
              << ", audio=" << preview_audio_depth << ")" << std::endl;

    // Step 1: Signal old Live producer to stop (non-blocking).
    // Per Phase 7: Do NOT block on join() - old producer may be stuck in buffer backoff.
    // Instead, signal stop and let it die naturally. The unique_ptr will be released
    // after we move preview_producer to live_producer.
    if (state->live_producer) {
      std::cout << "[SwitchToLive] Signaling old live producer to stop (non-blocking)..." << std::endl;
      state->live_producer->ForceStop();  // Sets stop_requested_ immediately
      // Do NOT call stop() here - it blocks on join() and can deadlock
      // The old producer will be released when we assign preview_producer to live_producer
    }

    // Step 2: Redirect ProgramOutput to read from preview's buffer.
    // Per contract: no draining - old buffer frames are discarded.
    if (state->program_output && state->preview_ring_buffer) {
      std::cout << "[SwitchToLive] Redirecting ProgramOutput to preview buffer" << std::endl;
      state->program_output->SetInputBuffer(state->preview_ring_buffer.get());
    }

    // Step 3: Swap buffer ownership. After this:
    // - ring_buffer owns what was preview's buffer (ProgramOutput now reads this)
    // - preview_ring_buffer owns the old buffer (will be cleared on next LoadPreview)
    std::swap(state->ring_buffer, state->preview_ring_buffer);

    // Step 4: Phase 7 PTS Continuity - Log alignment info for diagnostics.
    // Note: AlignPTS was already called when transitioning from shadow mode (above).
    // This just logs the final values for debugging.
    int64_t last_emitted_pts = 0;
    int64_t target_next_pts = 0;
    if (state->program_output) {
      last_emitted_pts = state->program_output->GetLastEmittedPTS();
      if (last_emitted_pts > 0) {
        double fps = state->program_format.GetFrameRateAsDouble();
        int64_t frame_period_us = static_cast<int64_t>(1'000'000.0 / fps);
        target_next_pts = last_emitted_pts + frame_period_us;
        std::cout << "[SwitchToLive] Phase 7 PTS alignment: last_pts=" << last_emitted_pts
                  << " target_next_pts=" << target_next_pts
                  << " frame_period=" << frame_period_us << "us" << std::endl;
      }
    }

    // Step 5: Promote preview producer to live.
    // Move old producer to temporary so destructor doesn't block the switch.
    // The old producer's destructor calls stop() which joins the thread - we do this
    // in a background thread to avoid blocking the switch.
    auto old_producer = std::move(state->live_producer);
    state->live_producer = std::move(state->preview_producer);
    state->live_asset_path = state->preview_asset_path;
    state->preview_producer.reset();
    state->preview_asset_path.clear();

    // Clean up old producer in background thread to avoid blocking
    if (old_producer) {
      std::thread([producer = std::move(old_producer)]() mutable {
        // Destructor will call stop() which joins the thread
        producer.reset();
      }).detach();
    }

    std::cout << "[SwitchToLive] === SWITCH COMPLETE ===" << std::endl;
    std::cout << "[SwitchToLive] Now playing: " << state->live_asset_path << std::endl;

    EngineResult result(true, "Switched to live for channel " + std::to_string(channel_id));
    result.pts_contiguous = true;
    result.live_start_pts = target_next_pts;

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
  if (it == channels_.end() || !it->second || !it->second->program_output)
    return;
  it->second->program_output->SetSideSink(std::move(callback));
}

void PlayoutEngine::UnregisterMuxFrameCallback(int32_t channel_id) {
  std::lock_guard<std::mutex> lock(channels_mutex_);
  auto it = channels_.find(channel_id);
  if (it == channels_.end() || !it->second || !it->second->program_output)
    return;
  it->second->program_output->ClearSideSink();
}

// Phase 8.9: Audio frame callback registration
void PlayoutEngine::RegisterMuxAudioFrameCallback(int32_t channel_id,
                                                  std::function<void(const buffer::AudioFrame&)> callback) {
  std::lock_guard<std::mutex> lock(channels_mutex_);
  auto it = channels_.find(channel_id);
  if (it == channels_.end() || !it->second || !it->second->program_output)
    return;
  it->second->program_output->SetAudioSideSink(std::move(callback));
}

void PlayoutEngine::UnregisterMuxAudioFrameCallback(int32_t channel_id) {
  std::lock_guard<std::mutex> lock(channels_mutex_);
  auto it = channels_.find(channel_id);
  if (it == channels_.end() || !it->second || !it->second->program_output)
    return;
  it->second->program_output->ClearAudioSideSink();
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

std::optional<ProgramFormat> PlayoutEngine::GetProgramFormat(int32_t channel_id) {
  std::lock_guard<std::mutex> lock(channels_mutex_);

  auto it = channels_.find(channel_id);
  if (it == channels_.end() || !it->second) {
    return std::nullopt;
  }

  return it->second->program_format;
}

void PlayoutEngine::ConnectRendererToOutputBus(int32_t channel_id) {
  std::lock_guard<std::mutex> lock(channels_mutex_);

  auto it = channels_.find(channel_id);
  if (it == channels_.end() || !it->second) {
    return;
  }

  auto& state = it->second;
  if (state->program_output && state->output_bus) {
    state->program_output->SetOutputBus(state->output_bus.get());
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
  if (state->program_output) {
    state->program_output->ClearOutputBus();
    std::cout << "[PlayoutEngine] Renderer disconnected from OutputBus for channel " << channel_id << std::endl;
  }
}

}  // namespace retrovue::runtime

