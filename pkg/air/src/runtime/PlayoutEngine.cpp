// Repository: Retrovue-playout
// Component: Playout Engine Domain Implementation
// Purpose: Domain-level engine that manages channel lifecycle operations.
// Copyright (c) 2025 RetroVue

#include "retrovue/runtime/PlayoutEngine.h"

#include <cassert>
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <thread>

#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/output/IOutputSink.h"
#include "retrovue/output/MpegTSOutputSink.h"
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

  // Hypothesis: skip RequestStop when RETROVUE_NO_FORCE_STOP=1 to test if stop kills liveness
  void MaybeRequestStop(producers::IProducer* producer) {
    if (!producer) return;
    const char* e = std::getenv("RETROVUE_NO_FORCE_STOP");
    if (e && e[0] == '1') {
      std::cout << "[DBG] RETROVUE_NO_FORCE_STOP=1 skipping RequestStop" << std::endl;
      return;
    }
    producer->RequestStop();
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

  // Contract-level observability: AIR_AS_RUN_FRAME_RANGE (once per producer lifecycle end).
  void LogAirAsRunFrameRange(int32_t channel_id,
                             const std::string& segment_id,
                             const std::string& asset_path,
                             int64_t first_frame_emitted,
                             int64_t last_frame_emitted,
                             uint64_t frames_emitted,
                             int64_t first_pts_us,
                             int64_t last_pts_us,
                             const char* termination_reason) {
    std::cout << "[AIR_AS_RUN_FRAME_RANGE] channel_id=" << channel_id
              << " segment_id=" << segment_id
              << " asset_path=" << asset_path
              << " first_frame_emitted=" << first_frame_emitted
              << " last_frame_emitted=" << last_frame_emitted
              << " frames_emitted=" << frames_emitted
              << " first_pts_us=" << first_pts_us
              << " last_pts_us=" << last_pts_us
              << " termination_reason=" << termination_reason
              << std::endl;
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

  // INV-SWITCH-SUCCESSOR-EMISSION: True only after at least one real successor
  // video frame has been emitted by the encoder (routed through OutputBus and
  // accepted by encoder/mux). Pad frames do not count. Gates switch completion.
  std::atomic<bool> successor_video_emitted_{false};

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

    // INV-P8-SUCCESSOR-OBSERVABILITY: Wire observer before any segment may commit.
    // ProgramOutput notifies when first real successor video frame is routed.
    state->program_output->SetOutputBus(state->output_bus.get());
    PlayoutInstance* state_ptr = state.get();
    timing::TimelineController* tc = state->timeline_controller.get();
    state->program_output->SetOnSuccessorVideoEmitted([state_ptr, tc]() {
      state_ptr->successor_video_emitted_.store(true, std::memory_order_release);
      if (tc) tc->NotifySuccessorVideoEmitted();
    });
    state->timeline_controller->SetEmissionObserverAttached(true);

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

    // Contract-level observability: AIR_AS_RUN_FRAME_RANGE before stopping producer/output.
    if (state->live_producer) {
      auto stats = state->live_producer->GetAsRunFrameStats();
      if (stats && state->program_output) {
        const int64_t first_pts_us = state->program_output->GetFirstEmittedPTS();
        const int64_t last_pts_us = state->program_output->GetLastEmittedPTS();
        const int64_t last_frame = stats->start_frame + (stats->frames_emitted > 0
            ? static_cast<int64_t>(stats->frames_emitted) - 1 : 0);
        LogAirAsRunFrameRange(channel_id, "", stats->asset_path,
            stats->start_frame, last_frame, stats->frames_emitted,
            first_pts_us, last_pts_us, "STOP");
      }
    }

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
    int64_t start_frame,
    int64_t frame_count,
    int32_t fps_numerator,
    int32_t fps_denominator) {
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

  // ==========================================================================
  // INV-FRAME-001/002/003: Frame-indexed execution
  // ==========================================================================
  // Compute legacy time-based values for ProducerConfig (backward compatibility).
  // Direction: frame → time (never time → frame)
  double fps = (fps_denominator > 0)
      ? static_cast<double>(fps_numerator) / static_cast<double>(fps_denominator)
      : it->second->program_format.GetFrameRateAsDouble();
  int64_t start_offset_ms = (fps > 0) ? static_cast<int64_t>((start_frame * 1000.0) / fps) : 0;
  // frame_count is authoritative - no need to convert back to wall-clock time
  // (hard_stop_time_ms was deprecated, we use frame_count directly now)

  try {
    // Create preview producer config
    producers::file::ProducerConfig preview_config;
    preview_config.asset_uri = asset_path;
    preview_config.target_fps = fps;
    preview_config.stub_mode = false;
    preview_config.target_width = it->second->program_format.video.width;
    preview_config.target_height = it->second->program_format.video.height;
    // Frame-indexed execution (INV-FRAME-001/002)
    preview_config.start_frame = start_frame;
    preview_config.frame_count = frame_count;
    // Legacy fields for backward compatibility (computed from frame index)
    preview_config.start_offset_ms = start_offset_ms;
    preview_config.hard_stop_time_ms = 0;  // Deprecated: use frame_count instead

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
              << " (start_frame=" << start_frame << ", frame_count=" << frame_count
              << ", fps=" << fps_numerator << "/" << fps_denominator << ")" << std::endl;

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

// =============================================================================
// SpawnSwitchWatcher: Background thread for level-triggered auto-completion
// =============================================================================
// Called when SwitchToLive returns NOT_READY. The watcher polls buffer
// readiness and auto-completes the switch when conditions are met.
// This makes SwitchToLive level-triggered: Core doesn't need to keep polling.
void PlayoutEngine::SpawnSwitchWatcher(int32_t channel_id, PlayoutInstance* state) {
  constexpr int kPollIntervalMs = 50;

  // Guard: only spawn if not already running
  state->switch_watcher_stop.store(false);
  if (state->switch_watcher_running.exchange(true)) {
    // Already running - don't spawn duplicate
    return;
  }

  // ==========================================================================
  // INV-P8-SWITCHWATCHER-STOP-TARGET-001: Bind retirement target BEFORE watcher starts
  // ==========================================================================
  // Capture the producer that should be retired. This ensures we never call
  // RequestStop on the successor, even if commit-gen detection fires after swap.
  // The captured pointer is used for all retirement actions; live_producer is
  // never used for retirement decisions inside the watcher.
  // ==========================================================================
  producers::IProducer* producer_to_retire = state->live_producer.get();

  std::cout << "[SwitchWatcher] STARTED (channel=" << channel_id << ")" << std::endl;

  std::thread([this, channel_id, producer_to_retire]() mutable {
    bool did_complete = false;
    constexpr size_t kMinVideoDepth = 2;
    constexpr int kPollIntervalMs = 50;
    constexpr int kMaxPollAttempts = 200;  // 10 seconds max
    constexpr int kAudioLagWarnMs = 500;
    int audio_missing_polls = 0;
    bool audio_lag_warned = false;
    bool retirement_done = false;  // INV-P8-SWITCHWATCHER-STOP-TARGET-001: one-shot retirement
    auto start_time = std::chrono::steady_clock::now();

    for (int attempt = 0; attempt < kMaxPollAttempts; ++attempt) {
      std::this_thread::sleep_for(std::chrono::milliseconds(kPollIntervalMs));

      std::lock_guard<std::mutex> lock(channels_mutex_);
      auto it = channels_.find(channel_id);
      if (it == channels_.end() || !it->second) break;

      auto& s = it->second;
      if (s->switch_watcher_stop.load()) break;
      if (!s->switch_in_progress) break;

      buffer::FrameRingBuffer* active_buffer = s->preview_ring_buffer.get();
      size_t video_depth = active_buffer ? active_buffer->Size() : 0;
      size_t audio_depth = active_buffer ? active_buffer->AudioSize() : 0;

      // Segment commit detection (silent unless closing old producer)
      // INV-P8-SWITCHWATCHER-STOP-TARGET-001: Only trigger retirement BEFORE swap
      // and only on the bound producer_to_retire (never live_producer).
      bool commit_detected = false;
      if (s->timeline_controller) {
        uint64_t current_commit_gen = s->timeline_controller->GetSegmentCommitGeneration();
        if (current_commit_gen > s->last_seen_commit_gen) {
          commit_detected = true;
          s->last_seen_commit_gen = current_commit_gen;
          // INV-P8-SWITCHWATCHER-STOP-TARGET-001: Use bound target, not live_producer
          // Retirement is one-shot and targets the captured producer_to_retire
          if (!retirement_done && producer_to_retire) {
            MaybeRequestStop(producer_to_retire);
            retirement_done = true;
            std::cout << "[SwitchWatcher] INV-P8-STOP-TARGET: Retirement triggered "
                      << "(commit_gen edge)" << std::endl;
          }
        }
      }

      bool bootstrap_ready = commit_detected && (video_depth >= 1);
      bool live_producer_eof = s->live_producer && s->live_producer->IsEOF();
      bool preview_producer_eof = s->preview_producer && s->preview_producer->IsEOF();
      bool readiness_passed = (video_depth >= kMinVideoDepth);
      bool preview_eof_with_frames = preview_producer_eof && video_depth >= 1;

      // INV-P8-SWITCH-READINESS: Warn if audio missing too long (one-shot)
      if (video_depth >= kMinVideoDepth && audio_depth == 0) {
        audio_missing_polls++;
        if (!audio_lag_warned && (audio_missing_polls * kPollIntervalMs) >= kAudioLagWarnMs) {
          std::cerr << "[SwitchWatcher] INV-P8-SWITCH-READINESS: WARNING audio_missing_ms="
                    << (audio_missing_polls * kPollIntervalMs) << " (silence padding active)"
                    << std::endl;
          audio_lag_warned = true;
        }
      } else {
        audio_missing_polls = 0;
      }

      if (readiness_passed || bootstrap_ready || live_producer_eof || preview_eof_with_frames) {
        // INV-OUTPUT-READY-BEFORE-LIVE: Log once if sink not attached
        if (!IsOutputSinkAttachedLocked(channel_id)) {
          static bool sink_warn_logged = false;
          if (!sink_warn_logged) {
            std::cout << "[SwitchWatcher] INV-OUTPUT-READY-BEFORE-LIVE: "
                      << "committing without sink (late attach expected)" << std::endl;
            sink_warn_logged = true;
          }
        }

        // Redirect output to preview buffer
        if (!s->program_output || !s->preview_ring_buffer) {
          std::cerr << "[SwitchWatcher] INV-P8-SWITCH-READINESS: ABORT "
                    << "reason=" << (!s->program_output ? "NO_OUTPUT" : "NO_BUFFER")
                    << std::endl;
          continue;
        }

        // INV-P8-SWITCHWATCHER-STOP-TARGET-001: Use bound target, not live_producer
        // Retirement is one-shot and targets the captured producer_to_retire
        if (!retirement_done && producer_to_retire) {
          MaybeRequestStop(producer_to_retire);
          retirement_done = true;
          std::cout << "[SwitchWatcher] INV-P8-STOP-TARGET: Retirement triggered "
                    << "(readiness passed)" << std::endl;
        }

        // Capture PTS for as-run log before redirect (SetInputBuffer resets first_pts).
        const int64_t first_pts_us = s->program_output ? s->program_output->GetFirstEmittedPTS() : 0;
        const int64_t last_pts_us = s->program_output ? s->program_output->GetLastEmittedPTS() : 0;

        s->program_output->SetInputBuffer(s->preview_ring_buffer.get());
        std::swap(s->ring_buffer, s->preview_ring_buffer);

        auto old_producer = std::move(s->live_producer);
        s->live_producer = std::move(s->preview_producer);
        s->live_asset_path = s->preview_asset_path;
        s->preview_producer.reset();
        s->preview_asset_path.clear();

        // Contract-level observability: AIR_AS_RUN_FRAME_RANGE using retired producer (not live).
        if (old_producer) {
          auto stats = old_producer->GetAsRunFrameStats();
          if (stats) {
            const int64_t last_frame = stats->start_frame + (stats->frames_emitted > 0
                ? static_cast<int64_t>(stats->frames_emitted) - 1 : 0);
            LogAirAsRunFrameRange(channel_id, "", stats->asset_path,
                stats->start_frame, last_frame, stats->frames_emitted,
                first_pts_us, last_pts_us, "WATCHER_RETIRE");
          }
          std::thread([producer = std::move(old_producer)]() mutable {
            producer.reset();
          }).detach();
        }

        // ==========================================================================
        // INV-P8-SWITCHWATCHER-STOP-TARGET-001: Switch completes immediately after swap
        // ==========================================================================
        // The critical invariant is satisfied: retirement targeted producer_to_retire
        // (the pre-swap producer), not the successor. We complete the switch now.
        // ==========================================================================
        s->switch_in_progress = false;
        s->switch_target_asset.clear();
        s->switch_auto_completed = true;
        s->switch_watcher_running.store(false);

        auto elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - start_time).count();
        std::cout << "[SwitchWatcher] INV-P8-SWITCH-READINESS: COMPLETE "
                  << "(video=" << video_depth << ", audio=" << audio_depth
                  << ", elapsed_ms=" << elapsed_ms << ", asset=" << s->live_asset_path << ")"
                  << std::endl;
        did_complete = true;
        break;  // Exit loop; lock released
      }
    }

    // INV-FINALIZE-LIVE: Wire program_output to output_bus (late attach path)
    // Call after releasing channels_mutex_ to avoid deadlock.
    if (did_complete) {
      FinalizeLiveOutput(channel_id);
      return;
    }

    // Timeout - this is a potential invariant violation
    {
      std::lock_guard<std::mutex> lock(channels_mutex_);
      auto it = channels_.find(channel_id);
      if (it != channels_.end() && it->second) {
        it->second->switch_watcher_running.store(false);
      }
    }
    std::cerr << "[SwitchWatcher] INV-P8-SWITCH-READINESS: TIMEOUT after 10s" << std::endl;
  }).detach();
}

EngineResult PlayoutEngine::SwitchToLive(int32_t channel_id) {
  std::unique_lock<std::mutex> lock(channels_mutex_);

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
        } else {
          // Still waiting for shadow decode - silent return (polling is expected)
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
        // =========================================================================
        // INV-SWITCH-READINESS: Audio data NOT required for switch completion
        // =========================================================================
        // Audio may legitimately lag video due to epoch alignment (audio frames
        // are skipped until video epoch is established). Silence padding handles
        // the gap until real audio arrives.
        // =========================================================================

        if (preview_video_depth < kMinPreviewVideoDepth) {
          // =====================================================================
          // Phase 8 (INV-P8-EOF-SWITCH): Check if live or preview producer is at EOF
          // =====================================================================
          // When live producer reaches EOF, we MUST complete the switch regardless
          // of preview buffer depth. Blocking forever leads to infinite stall.
          //
          // INV-P8-PREVIEW-EOF: When preview producer hits EOF with any video frames,
          // complete with lower thresholds. Audio not required (silence padding used).
          bool live_producer_eof = state->live_producer && state->live_producer->IsEOF();
          bool preview_producer_eof = state->preview_producer && state->preview_producer->IsEOF();
          bool preview_eof_with_frames = preview_producer_eof && preview_video_depth >= 1;

          if (live_producer_eof) {
            std::cout << "[SwitchToLive] INV-P8-EOF-SWITCH: Live producer at EOF, "
                      << "forcing completion (video=" << preview_video_depth << ")" << std::endl;
            // Fall through to complete - don't return NOT_READY
          } else if (preview_eof_with_frames) {
            std::cout << "[SwitchToLive] INV-P8-PREVIEW-EOF: Preview producer at EOF, "
                      << "completing with available video (depth=" << preview_video_depth << ")" << std::endl;
            // Fall through to complete - don't return NOT_READY
          } else {
            // Still filling - spawn watcher if not already running, then return NOT_READY
            // BUG FIX: The watcher was only spawned in the first-time path, not here.
            // This caused NOT_READY to never transition to READY.
            if (!state->switch_watcher_running.load()) {
              SpawnSwitchWatcher(channel_id, state.get());
            }
            std::cout << "[SwitchToLive] INV-SWITCH-READINESS: NOT_READY "
                      << "(video=" << preview_video_depth << "/" << kMinPreviewVideoDepth
                      << ", audio=" << preview_audio_depth << ", waiting for video)" << std::endl;
            EngineResult result(false, "Switch in progress; awaiting video buffer fill (video="
                + std::to_string(preview_video_depth) + "/" + std::to_string(kMinPreviewVideoDepth) + ")");
            result.error_code = "NOT_READY_IN_PROGRESS";
            result.result_code = ResultCode::kNotReady;
            return result;
          }
        } else {
          // Buffer is ready - fall through to complete the switch
          std::cout << "[SwitchToLive] INV-SWITCH-READINESS: PASSED "
                    << "(video=" << preview_video_depth << "/" << kMinPreviewVideoDepth
                    << ", audio=" << preview_audio_depth << ")" << std::endl;
        }
      }
    }

    size_t preview_depth_before = state->preview_ring_buffer ? state->preview_ring_buffer->Size() : 0;

    // Phase 7 (P7-ARCH-003): Video readiness is a precondition to switching.
    // Never switch if preview buffer is empty - would cause renderer stall.
    // INV-SWITCH-READINESS: Audio data NOT required (silence padding used).
    constexpr size_t kMinPreviewVideoDepth = 2;   // At least 2 video frames

    size_t preview_audio_depth = state->preview_ring_buffer ?
        state->preview_ring_buffer->AudioSize() : 0;

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
        // Mark switch as in-progress (one-shot log)
        if (!state->switch_in_progress) {
          state->switch_in_progress = true;
          state->switch_target_asset = state->preview_asset_path;
          state->successor_video_emitted_.store(false, std::memory_order_release);
          std::cout << "[SwitchToLive] INV-P8-SWITCH-READINESS: NOT_READY "
                    << "(shadow_pending=true, asset=" << state->switch_target_asset << ")"
                    << std::endl;
        }
        EngineResult result(false, "Preview producer not ready - waiting for shadow decode");
        result.error_code = "NOT_READY_SHADOW_PENDING";
        result.result_code = ResultCode::kNotReady;
        return result;
      }

      // Legacy path: AlignPTS for systems without TimelineController (silent)
      int64_t target_next_pts = 0;
      if (!state->timeline_controller) {
        int64_t last_emitted_pts = 0;
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
        }
      }

      // =========================================================================
      // INV-P8-WRITE-BARRIER-BEFORE-SEGMENT: Set write barrier on live producer
      // BEFORE beginning new segment. This prevents live producer frames from
      // racing to AdmitFrame during the pending->committed window and either:
      //   (a) locking the mapping with wrong MT, or
      //   (b) being rejected as "late" after preview locks the mapping
      //
      // IMPORTANT:
      // Write barrier MUST be set before BeginSegmentFromPreview().
      // Segment ownership transfer requires exclusive writer semantics.
      // Reordering this reintroduces MT/CT race conditions.
      // =========================================================================
      if (state->live_producer && state->timeline_controller) {
        state->live_producer->SetWriteBarrier();
      }

      // BeginSegmentFromPreview (silent - internal step)
      if (state->timeline_controller) {
        if (!state->timeline_controller->IsMappingPending()) {
          state->timeline_controller->BeginSegmentFromPreview();
        }
      }

      // Disable shadow mode and flush cached frame
      state->preview_producer->SetShadowDecodeMode(false);

      // INV-P8-SHADOW-FLUSH: Flush cached frame to buffer
      if (!state->preview_producer->FlushCachedFrameToBuffer()) {
        std::cerr << "[SwitchToLive] INV-P8-SHADOW-FLUSH: VIOLATED "
                  << "(shadow_ready=true, flush_returned=false)" << std::endl;
      }

      // =========================================================================
      // INV-P8-ZERO-FRAME-BOOTSTRAP: Signal no-content segment to ProgramOutput
      // =========================================================================
      // When frame_count=0, no real content will ever arrive. We must tell
      // ProgramOutput to allow pad frames immediately (bypass CONTENT-BEFORE-PAD).
      // The first pad frame acts as "bootstrap frame" for encoder initialization.
      // =========================================================================
      if (state->preview_producer->GetConfiguredFrameCount() == 0) {
        if (state->program_output) {
          state->program_output->SetNoContentSegment(true);
          std::cout << "[PlayoutEngine] INV-P8-ZERO-FRAME-BOOTSTRAP: Zero-frame segment detected, "
                    << "CONTENT-BEFORE-PAD gate bypassed" << std::endl;
        }
        // INV-SWITCH-SUCCESSOR-EMISSION: Zero-content segment has no real frames;
        // allow switch completion without encoder emission (pad-only segment).
        state->successor_video_emitted_.store(true, std::memory_order_release);
      } else {
        // Reset for segments with real content
        if (state->program_output) {
          state->program_output->SetNoContentSegment(false);
        }
      }

      // Refresh depths and mark transition in-progress
      preview_depth_before = state->preview_ring_buffer ? state->preview_ring_buffer->Size() : 0;
      preview_audio_depth = state->preview_ring_buffer ? state->preview_ring_buffer->AudioSize() : 0;
      state->switch_in_progress = true;
      state->switch_target_asset = state->preview_asset_path;
      state->successor_video_emitted_.store(false, std::memory_order_release);
      state->last_seen_commit_gen = state->timeline_controller ?
          state->timeline_controller->GetSegmentCommitGeneration() : 0;

      // Spawn watcher for auto-completion
      SpawnSwitchWatcher(channel_id, state.get());

      // INV-P8-SWITCH-READINESS: NOT_READY (one-shot log, watcher handles completion)
      std::cout << "[SwitchToLive] INV-P8-SWITCH-READINESS: NOT_READY "
                << "(video=" << preview_depth_before << ", watcher_spawned=true)" << std::endl;
      EngineResult result(false, "Transition started; mapping locked, waiting for buffer to fill readiness threshold");
      result.error_code = "NOT_READY_TRANSITION_STARTED";
      result.result_code = ResultCode::kNotReady;
      return result;
    }

    if (preview_depth_before < kMinPreviewVideoDepth) {
      // Silent - watcher will handle completion
      EngineResult result(false, "SwitchToLive blocked: preview video not ready");
      result.error_code = "NOT_READY_VIDEO";
      result.result_code = ResultCode::kNotReady;
      return result;
    }

    // Direct completion path (immediate readiness)
    state->successor_video_emitted_.store(false, std::memory_order_release);

    // Capture PTS before redirect (SetInputBuffer resets first_pts).
    const int64_t first_pts_us = state->program_output ? state->program_output->GetFirstEmittedPTS() : 0;
    const int64_t last_pts_us = state->program_output ? state->program_output->GetLastEmittedPTS() : 0;

    MaybeRequestStop(state->live_producer.get());
    auto old_producer = std::move(state->live_producer);

    // Contract-level observability: AIR_AS_RUN_FRAME_RANGE using retired producer (not live).
    if (old_producer) {
      auto stats = old_producer->GetAsRunFrameStats();
      if (stats) {
        const int64_t last_frame = stats->start_frame + (stats->frames_emitted > 0
            ? static_cast<int64_t>(stats->frames_emitted) - 1 : 0);
        LogAirAsRunFrameRange(channel_id, "", stats->asset_path,
            stats->start_frame, last_frame, stats->frames_emitted,
            first_pts_us, last_pts_us, "RETIRE_REQUESTED");
      }
    }

    if (state->program_output && state->preview_ring_buffer) {
      state->program_output->SetInputBuffer(state->preview_ring_buffer.get());
    }

    std::swap(state->ring_buffer, state->preview_ring_buffer);

    state->live_producer = std::move(state->preview_producer);
    state->live_asset_path = state->preview_asset_path;
    state->preview_producer.reset();
    state->preview_asset_path.clear();

    if (old_producer) {
      std::thread([producer = std::move(old_producer)]() mutable {
        producer.reset();
      }).detach();
    }

    // Clear switch state
    state->switch_in_progress = false;
    state->switch_target_asset.clear();
    state->switch_watcher_stop.store(true);

    // INV-P8-SWITCH-READINESS: COMPLETE (direct path)
    std::cout << "[SwitchToLive] INV-P8-SWITCH-READINESS: COMPLETE "
              << "(video=" << preview_depth_before << ", audio=" << preview_audio_depth
              << ", asset=" << state->live_asset_path << ")" << std::endl;

    // INV-P8-SUCCESSOR-OBSERVABILITY: Do not return success until observer confirms
    // at least one real successor video frame routed. Completion ONLY via observer.
    constexpr auto kSuccessorEmitWaitTimeout = std::chrono::seconds(30);
    const auto wait_start = std::chrono::steady_clock::now();
    PlayoutInstance* state_ptr = state.get();
    while (!state_ptr->successor_video_emitted_.load(std::memory_order_acquire)) {
      lock.unlock();
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
      lock.lock();
      it = channels_.find(channel_id);
      if (it == channels_.end() || !it->second) {
        return EngineResult(false, "Channel " + std::to_string(channel_id) + " lost during switch wait");
      }
      state_ptr = it->second.get();
      if (std::chrono::steady_clock::now() - wait_start > kSuccessorEmitWaitTimeout) {
        std::cerr << "[SwitchToLive] INV-SWITCH-SUCCESSOR-EMISSION VIOLATION: timeout waiting for successor video emission" << std::endl;
        return EngineResult(false, "INV-SWITCH-SUCCESSOR-EMISSION: timeout waiting for successor video emission");
      }
    }

    EngineResult result(true, "Switched to live for channel " + std::to_string(channel_id));
    result.pts_contiguous = true;
    result.live_start_pts = 0;  // Direct completion - no PTS alignment needed
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

  // INV-P8-SUCCESSOR-OBSERVABILITY: Observer is wired at StartChannel (ProgramOutput).
  // No sink-specific callback; observation happens when ProgramOutput routes real frames.
  //
  // INV-P9-NO-BUS-REPLACEMENT: Always attach to existing bus (state->output_bus).
  // Bus is created once at StartChannel and never replaced.
  std::cout << "[AttachOutputSink] channel=" << channel_id
            << " bus=" << static_cast<void*>(state->output_bus.get())
            << " attaching to existing bus" << std::endl;
  auto result = state->output_bus->AttachSink(std::move(sink), replace_existing);
  std::cout << "[AttachOutputSink] channel=" << channel_id
            << " result=" << (result.success ? "OK" : "FAIL")
            << " sink_attached=" << state->output_bus->IsAttached() << std::endl;
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

  // INV-P8-SUCCESSOR-OBSERVABILITY: Observer stays attached (owned by ProgramOutput).
  // Only cleared on StopChannel/EndSession.
  auto result = state->output_bus->DetachSink(force);
  return EngineResult(result.success, result.message);
}

// NOTE: Do not call IsOutputSinkAttached() while holding channels_mutex_;
// use IsOutputSinkAttachedLocked() instead to avoid deadlock.
bool PlayoutEngine::IsOutputSinkAttached(int32_t channel_id) {
  std::lock_guard<std::mutex> lock(channels_mutex_);
  return IsOutputSinkAttachedLocked(channel_id);
}

bool PlayoutEngine::IsOutputSinkAttachedLocked(int32_t channel_id) const {
  // Caller must hold channels_mutex_
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

void PlayoutEngine::FinalizeLiveOutput(int32_t channel_id) {
  std::lock_guard<std::mutex> lock(channels_mutex_);

  auto it = channels_.find(channel_id);
  if (it == channels_.end() || !it->second) {
    return;
  }

  auto& state = it->second;

  // INV-P9-NO-BUS-REPLACEMENT: OutputBus is created once at StartChannel, never replaced.
  // Do NOT create a new bus here; use the existing one from channel state.
  if (!state->output_bus) {
    std::cout << "[FinalizeLiveOutput] channel=" << channel_id
              << " no OutputBus (control_surface_only or not yet started)" << std::endl;
    return;
  }

  if (state->program_output) {
    state->program_output->SetOutputBus(state->output_bus.get());
    bool attached = state->output_bus->IsAttached();
    std::cout << "[FinalizeLiveOutput] channel=" << channel_id
              << " bus=" << static_cast<void*>(state->output_bus.get())
              << " sink_attached=" << attached
              << " (INV-P9-SINK-LIVENESS: must remain true until Detach/Stop)" << std::endl;
  }
}

void PlayoutEngine::ConnectRendererToOutputBus(int32_t channel_id) {
  FinalizeLiveOutput(channel_id);
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

