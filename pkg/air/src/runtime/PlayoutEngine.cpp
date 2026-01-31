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

  // Phase 8: Switch-in-progress guard and auto-completion (Option A)
  // When switch is armed, a detached watcher thread polls readiness and auto-completes.
  bool switch_in_progress = false;
  std::string switch_target_asset;  // Asset we're switching TO (for idempotency check)
  bool switch_auto_completed = false;  // Set when watcher auto-completes the switch
  std::atomic<bool> switch_watcher_stop{false};  // Signal watcher to exit
  std::atomic<bool> switch_watcher_running{false};  // Guard against double-spawn

  // INV-P8-SEGMENT-COMMIT-EDGE: Track last seen commit generation for edge detection
  // When commit_gen advances, a new segment has committed → close old segment.
  // This works across multiple switches (1st, 2nd, Nth).
  uint64_t last_seen_commit_gen = 0;

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
    // INV-P8-SWITCH-002: First frame locks BOTH CT and MT together.
    // At session start, CT_start will be very close to 0 (ms from epoch).
    if (state->timeline_controller) {
      auto pending = state->timeline_controller->BeginSegmentFromPreview();
      std::cout << "[PlayoutEngine] Phase 8: Segment begun (preview-owned, id=" << pending.id
                << "), CT and MT will lock on first frame" << std::endl;
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

    // Stop switch watcher thread if running (signal only, don't join to avoid deadlock)
    state->switch_watcher_stop.store(true);
    state->switch_in_progress = false;

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

  // ==========================================================================
  // Phase 8: CRITICAL GUARD - LoadPreview FORBIDDEN while switch is armed
  // ==========================================================================
  // INV-P8-SWITCH-ARMED: Once SwitchToLive() arms a transition, the preview
  // producer must not be replaced, reset, or reloaded. Doing so would:
  //   1. Destroy the preview producer currently filling buffers
  //   2. Clear accumulated buffer depth
  //   3. Reset readiness, preventing the switch from ever completing
  //
  // This is the authoritative state guard. Core also has a guard (SwitchState
  // enum) but Air enforces defense-in-depth.
  if (state->switch_in_progress) {
    std::cout << "[LoadPreview] REJECTED: switch already armed for asset '"
              << state->switch_target_asset << "' (INV-P8-SWITCH-ARMED)" << std::endl;
    EngineResult result(false, "LoadPreview forbidden while switch is armed");
    result.error_code = "SWITCH_ARMED";
    result.result_code = ResultCode::kRejectedBusy;  // Phase 8: Typed result
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
    // ==========================================================================
    // Phase 8: HARD ASSERTION - INV-P8-SWITCH-ARMED
    // ==========================================================================
    // This code path should NEVER be reached if switch_in_progress is true.
    // The guard at the start of LoadPreview() should have rejected the call.
    // If we get here with switch_in_progress=true, we have a logic bug.
    if (state->switch_in_progress) {
      std::cerr << "[LoadPreview] FATAL: INV-P8-SWITCH-ARMED violated! "
                << "Reached buffer/producer reset code while switch is armed. "
                << "This is a programming error." << std::endl;
      EngineResult fatal_result(false, "FATAL: INV-P8-SWITCH-ARMED violated");
      fatal_result.result_code = ResultCode::kProtocolViolation;
      return fatal_result;
    }

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
      EngineResult fail_result(false, "Failed to start preview producer for channel " + std::to_string(channel_id));
      fail_result.result_code = ResultCode::kFailed;
      return fail_result;
    }
    std::cout << "[LoadPreview] Preview producer STARTED - now filling buffer" << std::endl;

    EngineResult result(true, "Preview loaded for channel " + std::to_string(channel_id));
    result.shadow_decode_started = true;
    result.result_code = ResultCode::kOk;
    return result;
  } catch (const std::exception& e) {
    EngineResult ex_result(false, "Exception loading preview for channel " + std::to_string(channel_id) + ": " + e.what());
    ex_result.result_code = ResultCode::kFailed;
    return ex_result;
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

  // =========================================================================
  // Phase 8: Level-triggered SwitchToLive (Option A)
  // =========================================================================
  // IMPORTANT: This check MUST come before the preview_producer check!
  // After auto-complete, preview_producer is nullptr (moved to live_producer),
  // but switch_auto_completed is true. If we check preview_producer first,
  // we'd incorrectly return an error.
  if (state->switch_auto_completed) {
    std::cout << "[SwitchToLive] Switch was auto-completed by watcher" << std::endl;
    state->switch_auto_completed = false;  // Reset for next switch
    EngineResult result(true, "Switch auto-completed for channel " + std::to_string(channel_id));
    result.pts_contiguous = true;
    result.result_code = ResultCode::kOk;
    return result;
  }

  if (!state->preview_producer) {
    EngineResult result(false, "No preview producer loaded for channel " + std::to_string(channel_id));
    result.result_code = ResultCode::kProtocolViolation;
    return result;
  }

  try {
    // Per OutputSwitchingContract: hot-switch with pre-decoded readiness.
    // Preview producer has been filling preview_ring_buffer.
    // We redirect ProgramOutput to read from preview's buffer (already has frames).

    // =========================================================================
    // Phase 8: Switch-in-progress idempotency guard
    // =========================================================================
    // If a transition is already active for the same preview asset, check
    // readiness. If ready, fall through to complete. If not, return NOT_READY.
    // The watcher thread will auto-complete when ready, so Core doesn't need
    // to keep polling (though it can).
    if (state->switch_in_progress && state->switch_target_asset == state->preview_asset_path) {
      // Already transitioning to this asset.
      //
      // INV-P8-WRITE-BARRIER-DEFERRED: If switch was armed while waiting for shadow decode,
      // we need to check if shadow is now ready and execute the switch sequence.
      // The switch sequence (BeginSegmentFromPreview, disable shadow, flush, barrier)
      // was NOT executed on the first call - we only armed the switch.
      bool preview_still_in_shadow = state->preview_producer && state->preview_producer->IsShadowDecodeMode();
      if (preview_still_in_shadow) {
        // Switch was armed but switch sequence not executed yet.
        // Check if shadow is now ready.
        bool shadow_ready = state->preview_producer->IsShadowDecodeReady();
        if (shadow_ready) {
          // Shadow is ready! Fall through to execute the switch sequence.
          std::cout << "[SwitchToLive] Shadow now ready, executing deferred switch sequence"
                    << std::endl;
          // Don't return - fall through to the switch sequence at line ~684
        } else {
          // Still waiting for shadow decode
          std::cout << "[SwitchToLive] Still waiting for shadow decode (switch armed)" << std::endl;
          EngineResult result(false, "Switch armed; waiting for shadow decode");
          result.error_code = "NOT_READY_SHADOW_PENDING";
          result.result_code = ResultCode::kNotReady;
          return result;
        }
      } else {
        // Preview is not in shadow mode - switch sequence was already executed.
        // Check buffer depths for readiness.
        size_t preview_video_depth = state->preview_ring_buffer ? state->preview_ring_buffer->Size() : 0;
        size_t preview_audio_depth = state->preview_ring_buffer ? state->preview_ring_buffer->AudioSize() : 0;
        constexpr size_t kMinPreviewVideoDepth = 2;
        constexpr size_t kMinPreviewAudioDepth = 5;

        if (preview_video_depth < kMinPreviewVideoDepth || preview_audio_depth < kMinPreviewAudioDepth) {
          // =====================================================================
          // Phase 8 (INV-P8-EOF-SWITCH): Check if live or preview producer is at EOF
          // =====================================================================
          // When live producer reaches EOF, we MUST complete the switch regardless
          // of preview buffer depth. Blocking forever leads to infinite stall.
          //
          // INV-P8-PREVIEW-EOF: When preview producer hits EOF with any frames,
          // complete with lower thresholds. This handles short assets or edge cases.
          bool live_producer_eof = state->live_producer && state->live_producer->IsEOF();
          bool preview_producer_eof = state->preview_producer && state->preview_producer->IsEOF();
          bool preview_eof_with_frames = preview_producer_eof && preview_video_depth >= 1 && preview_audio_depth >= 1;

          if (live_producer_eof) {
            std::cout << "[SwitchToLive] INV-P8-EOF-SWITCH: Live producer at EOF, "
                      << "forcing completion (video=" << preview_video_depth
                      << ", audio=" << preview_audio_depth << ")" << std::endl;
            // Fall through to complete - don't return NOT_READY
          } else if (preview_eof_with_frames) {
            std::cout << "[SwitchToLive] INV-P8-PREVIEW-EOF: Preview producer at EOF, "
                      << "forcing completion with available frames (video=" << preview_video_depth
                      << ", audio=" << preview_audio_depth << ")" << std::endl;
            // Fall through to complete - don't return NOT_READY
          } else {
            // Still filling - return NOT_READY without verbose logging
            // Watcher thread will auto-complete when ready
            EngineResult result(false, "Switch in progress; awaiting buffer fill (video="
                + std::to_string(preview_video_depth) + "/" + std::to_string(kMinPreviewVideoDepth)
                + ", audio=" + std::to_string(preview_audio_depth) + "/" + std::to_string(kMinPreviewAudioDepth) + ")");
            result.error_code = "NOT_READY_IN_PROGRESS";
            result.result_code = ResultCode::kNotReady;  // Transient: don't panic, don't retry aggressively
            return result;
          }
        } else {
          // Buffer is ready - fall through to complete the switch
          std::cout << "[SwitchToLive] Transition ready, completing switch (video="
                    << preview_video_depth << ", audio=" << preview_audio_depth << ")" << std::endl;
        }
      }
    }

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

    // ==========================================================================
    // Phase 8 Shadow→Live Handshake (CANONICAL STATE MACHINE)
    // ==========================================================================
    // This ordering is CRITICAL and must not be changed without updating
    // the contract documentation. The sequence ensures the preview producer's
    // first frame locks the segment mapping, not a stale live frame.
    //
    // State machine steps:
    //   1. Exit shadow mode (conceptual - we're about to transition)
    //   2. Write barrier on old live producer (freeze writes, keeps decoding)
    //   3. BeginSegmentFromPreview() for new segment mapping
    //   4. Disable shadow for preview buffer (frames now enter buffer)
    //   5. Return NOT_READY (forces retry until buffer has enough)
    //   6. Preview frames lock mapping (first video frame sets BOTH CT and MT)
    //   7. Buffer fills, output flows immediately
    //   8. Retry SwitchToLive → readiness passes → switch (PTS contiguous)
    //
    // INV-P8-SWITCH-001: Mapping must be pending BEFORE preview fills
    // -----------------------------------------------------------------
    // If preview exits shadow and begins writing frames before
    // BeginSegmentFromPreview(), the mapping can lock against the wrong MT
    // (or never lock deterministically).
    //
    // Practical enforcement:
    // - SwitchToLive() must not disable shadow until BeginSegmentFromPreview succeeds
    // - If BeginSegmentFromPreview fails, keep preview in shadow and return error
    //
    // INV-P8-SWITCH-002: CT and MT must describe the same instant (TYPE-SAFE)
    // -----------------------------------------------------------------
    // The type-safe API makes it IMPOSSIBLE to create a pending segment with:
    //   - a carried-forward CT (from old live)
    //   - a preview-derived MT
    // That state literally cannot be represented in the type system.
    //
    // BeginSegmentFromPreview() creates a segment in AwaitPreviewFrame mode.
    // The first preview frame locks BOTH:
    //   - CT_start = wall_clock_at_admission - epoch
    //   - MT_start = first_frame_media_time
    // Both describe the EXACT moment the first preview frame was admitted,
    // preventing timeline skew that would reject all frames as "early".
    //
    // There is no API that allows setting CT without MT or vice versa.
    // ==========================================================================
    bool is_shadow_mode = state->preview_producer->IsShadowDecodeMode();
    if (is_shadow_mode) {
      // ==========================================================================
      // INV-P8-WRITE-BARRIER-DEFERRED: Don't barrier live until preview is ready
      // ==========================================================================
      // A producer that is required for switch readiness MUST be allowed to write
      // until readiness is achieved. If we set the write barrier before preview
      // has cached its first frame, we create a deadlock:
      //   - Live is barriered → can't feed timeline
      //   - Preview is seeking → can't feed timeline yet
      //   - CT stalls → subsequent frames rejected as "early"
      //
      // Fix: Check if preview is shadow decode ready (has cached first frame).
      // If not ready, return NOT_READY without touching write barrier or segment.
      // Live continues feeding the OLD segment until preview is truly ready.
      // ==========================================================================
      bool shadow_ready = state->preview_producer->IsShadowDecodeReady();
      if (!shadow_ready) {
        // Preview hasn't cached its first frame yet - don't proceed with barrier/segment
        // BUT we DO mark switch as in-progress to guard against LoadPreview (INV-P8-SWITCH-ARMED)
        // Live continues running with the old segment mapping
        if (!state->switch_in_progress) {
          state->switch_in_progress = true;
          state->switch_target_asset = state->preview_asset_path;
          std::cout << "[SwitchToLive] INV-P8-SWITCH-ARMED: Switch armed for "
                    << state->switch_target_asset << " (waiting for shadow decode)" << std::endl;
        }
        std::cout << "[SwitchToLive] INV-P8-WRITE-BARRIER-DEFERRED: Preview not ready "
                  << "(shadow_decode_ready=false), waiting for first frame to cache"
                  << std::endl;
        EngineResult result(false, "Preview producer not ready - waiting for shadow decode");
        result.error_code = "NOT_READY_SHADOW_PENDING";
        result.result_code = ResultCode::kNotReady;
        return result;
      }

      std::cout << "[SwitchToLive] Preview shadow decode ready, proceeding with switch"
                << std::endl;

      // Legacy path: AlignPTS for systems without TimelineController
      if (!state->timeline_controller) {
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
        if (target_next_pts > 0) {
          state->preview_producer->AlignPTS(target_next_pts);
          std::cout << "[SwitchToLive] Legacy PTS alignment: target=" << target_next_pts << std::endl;
        }
      }

      // Step 2: BeginSegmentFromPreview() - MUST happen before disabling shadow
      // INV-P8-SWITCH-001: Mapping must be pending before preview fills
      // INV-P8-SWITCH-002: Preview owns BOTH CT and MT (locked together on first frame)
      //
      // Critical insight: We cannot precompute CT_start because wall clock advances
      // between this call and when the first preview frame is admitted. By using
      // BeginSegmentFromPreview(), the first preview frame locks BOTH CT and MT
      // to values that describe the SAME instant.
      //
      // The type-safe API makes the dangerous state (CT from live, MT from preview)
      // literally unrepresentable - there's no way to set one without the other.
      if (state->timeline_controller) {
        // Idempotency: only begin segment if not already pending
        if (!state->timeline_controller->IsMappingPending()) {
          auto pending = state->timeline_controller->BeginSegmentFromPreview();
          std::cout << "[SwitchToLive] Step 2: BeginSegmentFromPreview() - segment_id="
                    << pending.id << ", mode=AwaitPreviewFrame (INV-P8-SWITCH-002)" << std::endl;
        } else {
          std::cout << "[SwitchToLive] Step 2: Segment already pending (idempotent)" << std::endl;
        }
      }

      // Step 3: Disable shadow mode - frames will now use the new segment mapping
      state->preview_producer->SetShadowDecodeMode(false);
      std::cout << "[SwitchToLive] Step 3: Shadow mode disabled" << std::endl;

      // Step 3a (INV-P8-SHADOW-FLUSH): Immediately flush cached frame to buffer.
      // This ensures the buffer has at least one frame for the readiness check,
      // eliminating the race between SwitchWatcher polling and producer thread waking.
      // Because we checked IsShadowDecodeReady() above, we KNOW there's a cached frame.
      if (state->preview_producer->FlushCachedFrameToBuffer()) {
        std::cout << "[SwitchToLive] Step 3a: Cached shadow frame flushed to buffer" << std::endl;
      } else {
        // This should not happen if IsShadowDecodeReady() was true
        std::cerr << "[SwitchToLive] WARNING: Flush failed despite shadow_decode_ready=true"
                  << std::endl;
      }

      // Step 4: Write barrier on live producer AFTER preview has locked the mapping
      // INV-P8-WRITE-BARRIER-DEFERRED: The flush above locked the new segment mapping.
      // NOW it's safe to barrier the old live producer - preview is feeding the timeline.
      if (state->live_producer && state->timeline_controller) {
        state->live_producer->SetWriteBarrier();
        std::cout << "[SwitchToLive] Step 4: Write barrier set on live producer "
                  << "(AFTER preview locked mapping)" << std::endl;
      }

      // Step 5: REFRESH depths after flush (fix stale values bug)
      // The depths captured at the start of SwitchToLive are now stale.
      preview_depth_before = state->preview_ring_buffer ? state->preview_ring_buffer->Size() : 0;
      preview_audio_depth = state->preview_ring_buffer ? state->preview_ring_buffer->AudioSize() : 0;
      std::cout << "[SwitchToLive] Step 5: Refreshed depths after flush (video="
                << preview_depth_before << ", audio=" << preview_audio_depth << ")" << std::endl;

      // Step 6: Mark transition as in-progress for idempotency guard
      state->switch_in_progress = true;
      state->switch_target_asset = state->preview_asset_path;

      // INV-P8-SEGMENT-COMMIT-EDGE: Capture current generation to detect when it advances
      state->last_seen_commit_gen = state->timeline_controller ?
          state->timeline_controller->GetSegmentCommitGeneration() : 0;

      // Step 7: Spawn watcher thread for level-triggered auto-completion (Option A)
      // The watcher polls readiness and auto-completes when conditions are met.
      // This makes SwitchToLive level-triggered: Core doesn't need to keep polling.
      // Guard: only spawn if not already running
      state->switch_watcher_stop.store(false);
      if (!state->switch_watcher_running.exchange(true)) {
        std::thread([this, channel_id]() {
          constexpr size_t kMinVideoDepth = 2;
          constexpr size_t kMinAudioDepth = 5;
          constexpr int kPollIntervalMs = 50;
          constexpr int kMaxPollAttempts = 200;  // 10 seconds max

          for (int attempt = 0; attempt < kMaxPollAttempts; ++attempt) {
            std::this_thread::sleep_for(std::chrono::milliseconds(kPollIntervalMs));

            std::lock_guard<std::mutex> lock(channels_mutex_);
            auto it = channels_.find(channel_id);
            if (it == channels_.end() || !it->second) break;

            auto& s = it->second;
            if (s->switch_watcher_stop.load()) break;
            if (!s->switch_in_progress) break;  // Already completed by another path

            // Check readiness
            size_t video_depth = s->preview_ring_buffer ? s->preview_ring_buffer->Size() : 0;
            size_t audio_depth = s->preview_ring_buffer ? s->preview_ring_buffer->AudioSize() : 0;

            // =========================================================================
            // INV-P8-SEGMENT-COMMIT-EDGE: Detect segment commit via generation counter
            // =========================================================================
            // In broadcast terms, "commit" is when the new segment locks its mapping and
            // becomes the authoritative owner of CT. At commit, the old segment is DEAD
            // and must be hard-closed immediately. This is separate from buffer readiness.
            //
            // We use a generation counter (not state) to detect commit EDGES:
            //   - Captures current gen at switch start
            //   - Detects when gen advances (commit happened)
            //   - Works for 1st, 2nd, Nth switches
            //
            // Invariant: One segment owns CT at any time. After commit:
            //   - New segment owns CT (mapping locked)
            //   - Old segment is dead (producer stopped, cannot emit to timeline)
            // =========================================================================
            bool commit_detected = false;
            if (s->timeline_controller) {
              uint64_t current_commit_gen = s->timeline_controller->GetSegmentCommitGeneration();
              if (current_commit_gen > s->last_seen_commit_gen) {
                // Commit edge detected - generation advanced
                commit_detected = true;
                s->last_seen_commit_gen = current_commit_gen;

                std::cout << "[SwitchWatcher] INV-P8-SEGMENT-COMMIT-EDGE: Segment "
                          << s->timeline_controller->GetActiveSegmentId()
                          << " committed (gen=" << current_commit_gen
                          << "), closing old segment" << std::endl;

                // Hard-close old segment: force-stop old producer immediately
                // (it already has write barrier, but this ensures clean shutdown)
                if (s->live_producer) {
                  s->live_producer->ForceStop();
                  std::cout << "[SwitchWatcher] Old producer force-stopped (segment closed)"
                            << std::endl;
                }
              }
            }

            // =========================================================================
            // INV-P9-BOOTSTRAP-READY: Readiness = commit + ≥1 video frame
            // =========================================================================
            // Phase 9 breaks the deadlock where output routing waits for deep buffering
            // but deep buffering requires output routing to proceed. At commit time,
            // the cached shadow frame has been flushed (INV-P9-FLUSH), so video_depth >= 1.
            //
            // Bootstrap readiness: commit detected AND at least 1 video frame.
            // Audio zero-frames is acceptable during bootstrap (§3.2 Phase 9 contract).
            // =========================================================================
            bool bootstrap_ready = commit_detected && (video_depth >= 1);
            if (bootstrap_ready) {
              std::cout << "[SwitchWatcher] INV-P9-BOOTSTRAP-READY: commit_gen="
                        << s->last_seen_commit_gen << ", video_depth=" << video_depth
                        << ", audio_depth=" << audio_depth << " → READY (bootstrap)"
                        << std::endl;
            }

            // =========================================================================
            // Phase 8 (INV-P8-EOF-SWITCH): EOF on live or preview forces switch completion
            // =========================================================================
            // When the live producer reaches EOF, the switch MUST complete immediately
            // regardless of preview buffer depth. Blocking on buffer depth when live
            // is exhausted causes infinite stall (nothing feeding the output).
            //
            // INV-P8-PREVIEW-EOF: When PREVIEW producer hits EOF with any frames available,
            // complete with lower thresholds (>=1 video, >=1 audio). This handles:
            //   - Very short preview assets
            //   - Preview that consumed too much during shadow mode (now fixed)
            // Some A/V hiccups are acceptable - they're better than indefinite stall.
            bool live_producer_eof = s->live_producer && s->live_producer->IsEOF();
            bool preview_producer_eof = s->preview_producer && s->preview_producer->IsEOF();
            bool readiness_passed = (video_depth >= kMinVideoDepth && audio_depth >= kMinAudioDepth);

            // INV-P8-PREVIEW-EOF: Lower thresholds when preview is at EOF
            bool preview_eof_with_frames = preview_producer_eof && video_depth >= 1 && audio_depth >= 1;

            if (live_producer_eof && !readiness_passed) {
              std::cout << "[SwitchWatcher] INV-P8-EOF-SWITCH: Live producer at EOF, "
                        << "forcing switch completion (video=" << video_depth
                        << ", audio=" << audio_depth << ")" << std::endl;
            }

            if (preview_eof_with_frames && !readiness_passed) {
              std::cout << "[SwitchWatcher] INV-P8-PREVIEW-EOF: Preview producer at EOF, "
                        << "forcing switch with available frames (video=" << video_depth
                        << ", audio=" << audio_depth << ")" << std::endl;
            }

            if (readiness_passed || bootstrap_ready || live_producer_eof || preview_eof_with_frames) {
              if (readiness_passed && !bootstrap_ready) {
                std::cout << "[SwitchWatcher] Readiness PASSED (steady-state: video=" << video_depth
                          << ", audio=" << audio_depth << "), auto-completing switch" << std::endl;
              }

              // === Auto-complete the switch (copy of completion logic) ===
              // Signal old producer to stop
              if (s->live_producer) {
                s->live_producer->ForceStop();
              }

              // Redirect ProgramOutput to preview buffer
              if (s->program_output && s->preview_ring_buffer) {
                s->program_output->SetInputBuffer(s->preview_ring_buffer.get());
              }

              // Swap buffer ownership
              std::swap(s->ring_buffer, s->preview_ring_buffer);

              // Promote preview producer to live
              auto old_producer = std::move(s->live_producer);
              s->live_producer = std::move(s->preview_producer);
              s->live_asset_path = s->preview_asset_path;
              s->preview_producer.reset();
              s->preview_asset_path.clear();

              // Clean up old producer in background
              if (old_producer) {
                std::thread([producer = std::move(old_producer)]() mutable {
                  producer.reset();
                }).detach();
              }

              // Mark completion and clear watcher flag
              s->switch_in_progress = false;
              s->switch_target_asset.clear();
              s->switch_auto_completed = true;
              s->switch_watcher_running.store(false);

              std::cout << "[SwitchWatcher] === AUTO-SWITCH COMPLETE ===" << std::endl;
              std::cout << "[SwitchWatcher] Now playing: " << s->live_asset_path << std::endl;
              return;  // Done
            }
          }
          // Timed out or cancelled - clear watcher flag
          {
            std::lock_guard<std::mutex> lock(channels_mutex_);
            auto it = channels_.find(channel_id);
            if (it != channels_.end() && it->second) {
              it->second->switch_watcher_running.store(false);
            }
          }
          std::cout << "[SwitchWatcher] Timed out or cancelled" << std::endl;
        }).detach();  // Detach immediately
      }

      // Step 8: Return NOT_READY - this is INTENTIONAL, not a failure
      // Core will retry after buffer fills. Include depth for visibility.
      std::cout << "[SwitchToLive] Step 8: NOT_READY - transition started, buffer filling "
                << "(video=" << preview_depth_before << ", audio=" << preview_audio_depth << ")"
                << std::endl;
      EngineResult result(false, "Transition started; mapping locked, waiting for buffer to fill readiness threshold");
      result.error_code = "NOT_READY_TRANSITION_STARTED";
      result.result_code = ResultCode::kNotReady;  // Transient: don't panic
      return result;
    }

    if (preview_depth_before < kMinPreviewVideoDepth) {
      std::cerr << "[SwitchToLive] BLOCKED: preview video not ready (depth="
                << preview_depth_before << ", required=" << kMinPreviewVideoDepth
                << ") - P7-ARCH-003" << std::endl;
      EngineResult result(false, "SwitchToLive blocked: preview video not ready");
      result.error_code = "NOT_READY_VIDEO";
      result.result_code = ResultCode::kNotReady;  // Transient: buffer still filling
      return result;
    }

    if (preview_audio_depth < kMinPreviewAudioDepth) {
      std::cerr << "[SwitchToLive] BLOCKED: preview audio not ready (depth="
                << preview_audio_depth << ", required=" << kMinPreviewAudioDepth
                << ") - P7-ARCH-003" << std::endl;
      EngineResult result(false, "SwitchToLive blocked: preview audio not ready");
      result.error_code = "NOT_READY_AUDIO";
      result.result_code = ResultCode::kNotReady;  // Transient: buffer still filling
      return result;
    }

    std::cout << "[SwitchToLive] Readiness check PASSED (video=" << preview_depth_before
              << ", audio=" << preview_audio_depth << ")" << std::endl;

    // Phase 8: Write barrier and BeginSegment already happened during shadow->live transition.
    // No need to repeat here.

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

    // Clear switch-in-progress guard and stop watcher thread
    state->switch_in_progress = false;
    state->switch_target_asset.clear();
    state->switch_watcher_stop.store(true);  // Signal watcher to exit
    // Note: Don't join here - watcher will exit on its own

    std::cout << "[SwitchToLive] === SWITCH COMPLETE ===" << std::endl;
    std::cout << "[SwitchToLive] Now playing: " << state->live_asset_path << std::endl;

    EngineResult result(true, "Switched to live for channel " + std::to_string(channel_id));
    result.pts_contiguous = true;
    result.live_start_pts = target_next_pts;
    result.result_code = ResultCode::kOk;

    return result;
  } catch (const std::exception& e) {
    EngineResult ex_result(false, "Exception switching to live for channel " + std::to_string(channel_id) + ": " + e.what());
    ex_result.result_code = ResultCode::kFailed;
    return ex_result;
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

