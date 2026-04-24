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
#include "retrovue/readiness/ReadinessEvaluator.h"
#include "retrovue/readiness/ReadinessObserver.h"
#include "retrovue/readiness/ReadinessVerdict.h"
#include "retrovue/seam/SeamCommand.h"
#include "retrovue/seam/SeamController.h"
#include "retrovue/renderer/ProgramOutput.h"
#include "retrovue/runtime/ProgramFormat.h"
#include "retrovue/runtime/TimingLoop.h"
#include "retrovue/runtime/PlayoutControl.h"
#include "retrovue/telemetry/MetricsExporter.h"
#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/timing/MasterClock.h"
#include "retrovue/timing/TimelineController.h"
#include "retrovue/util/ObservabilityLogger.hpp"

#include <atomic>
#include <sstream>

namespace retrovue::runtime {

namespace {
  constexpr size_t kDefaultBufferSize = 60; // 60 frames (~2 seconds at 30fps)
  constexpr size_t kReadyDepth = 3; // Minimum buffer depth for ready state
  constexpr auto kReadyTimeout = std::chrono::seconds(2);
  // P11D-004: Minimum lead time (ms) between SwitchToLive receipt and target_boundary_time_ms.
  constexpr int64_t kMinPrefeedLeadTimeMs = 5000;
  
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

  // ORCH-SWITCH-SUCCESSOR-OBSERVED: True only after at least one real successor
  // video frame has been emitted by the encoder (routed through OutputBus and
  // accepted by encoder/mux). Pad frames do not count. Gates switch completion.
  std::atomic<bool> successor_video_emitted_{false};

  // P8-FILL-001/003: Content deficit (EOF before boundary) — fill with pad until switch
  std::atomic<bool> content_deficit_active_{false};
  int64_t deficit_start_ct_us_ = 0;
  int64_t deficit_boundary_ct_us_ = 0;
  std::string deficit_segment_id_;
  int64_t target_boundary_time_ms_ = 0;  // Set when switch scheduled (target_boundary_time_ms > 0)

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

  // Readiness observer — additive, observational only. Wired on
  // StartChannel, unregistered on StopChannel. Not consulted by any
  // playout decision. See docs/contracts/invariants/air/INV-READINESS-*.
  //
  // `readiness_control_box` is a lifetime-safety shim. The
  // CustomMetricsProvider lambda captures weak_ptr<ControlBox>; the box
  // holds the PlayoutControl* guarded by its own mutex. StopChannel
  // acquires the box mutex and nulls the pointer BEFORE state tear-down,
  // so any in-flight scrape either sees a valid control or sees null and
  // exits cleanly — no raw-pointer dereference after destruction.
  struct ReadinessControlBox {
    std::mutex mtx;
    PlayoutControl* control = nullptr;  // guarded by mtx
    // D+1: BlockPlan signal getter. Bound by playout_service when a BlockPlan
    // session starts; cleared when the session stops. Invoked under mtx so the
    // lifetime of the underlying PipelineManager is bracketed by the same
    // attach/detach mutex the ControlBox already uses for `control`.
    PlayoutEngine::BlockPlanSignalGetter blockplan_signal_getter;
  };
  std::shared_ptr<ReadinessControlBox> readiness_control_box;
  std::shared_ptr<readiness::ReadinessObserver> readiness_observer;
  std::string readiness_provider_name;
  std::shared_ptr<std::atomic<bool>> readiness_has_ever_been_ready;

  // Seam authority — additive, observational only. Wired on StartChannel,
  // unregistered on StopChannel. Not consulted by any playout decision.
  // See docs/contracts/invariants/air/INV-SEAM-*.md.
  //
  // Turn D scope: controller is constructed and its Current() record is
  // published as a Prometheus gauge. No ArmBoundary / Evaluate calls are
  // issued from production code in this turn — the controller stays in
  // kIdle until Turn D+1 adds the signal bridge (PipelineManager seam-
  // signal getter + per-boundary ArmBoundary wiring).
  std::shared_ptr<seam::SeamController> seam_controller;
  std::string seam_provider_name;

  // Option C bootstrap content-gate — Turn D observer-only metrics bridge.
  // The gate itself lives inside PipelineManager and is evaluated inline
  // on every tick during bootstrap. This ControlBox holds a getter that
  // captures the pipeline's BootstrapGateSnapshot accessor so an /metrics
  // scrape can surface the current state + kickoff event. Lifetime safety
  // is provided by the mutex: playout_service detaches the getter before
  // the pipeline is destroyed; any in-flight scrape either completes with
  // a valid getter or exits cleanly.
  struct BootstrapGateControlBox {
    std::mutex mtx;
    PlayoutEngine::BootstrapGateSnapshotGetter getter;  // guarded by mtx
  };
  std::shared_ptr<BootstrapGateControlBox> bootstrap_gate_control_box;
  std::string bootstrap_gate_provider_name;

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
  // Single-session: at most one instance. Capture id under lock, then stop
  // without holding it (StopChannel also acquires channels_mutex_).
  int32_t id = -1;
  {
    std::lock_guard<std::mutex> lock(channels_mutex_);
    if (control_surface_only_) {
      instance_.reset();
      return;
    }
    if (instance_) id = instance_->channel_id;
  }
  if (id != -1) {
    StopChannel(id);
  }
}

PlayoutEngine::PlayoutInstance* PlayoutEngine::FindInstanceLocked(int32_t channel_id) const {
  if (!instance_ || instance_->channel_id != channel_id) return nullptr;
  return instance_.get();
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
  if (instance_) {
    if (instance_->channel_id == channel_id) {
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
      instance_ = std::move(state);
      return EngineResult(true, "Channel " + std::to_string(channel_id) + " started (control surface only)");
    }
    
    // Create ring buffer
    state->ring_buffer = std::make_unique<buffer::FrameRingBuffer>(kDefaultBufferSize);

    // Create control state machine
    state->control = std::make_unique<PlayoutControl>();
    state->control->SetSessionOutputFps(
        retrovue::blockplan::DeriveRationalFPS(state->program_format.GetFrameRateAsDouble()));

    // Phase 9.0: Create OutputBus (contract-compliant, no control plane dependency)
    state->output_bus = std::make_unique<output::OutputBus>();

    // Phase 8: Create TimelineController for unified time authority
    timing::TimelineConfig timeline_config = timing::TimelineConfig::FromFps(
        state->program_format.GetFrameRateAsDouble(), 5, 30);
    state->timeline_controller = std::make_unique<timing::TimelineController>(
        master_clock_, timeline_config);

    // EPOCH OWNERSHIP (CANONICAL):
    // PlayoutEngine is the sole owner of epoch lifecycle.
    // Reset and set epoch BEFORE starting session - deterministic from the start.
    // Epoch is immutable during steady-state playout (Phase 10).
    if (master_clock_) {
      master_clock_->ResetEpochForNewSession();
      const int64_t epoch = master_clock_->now_utc_us();
      master_clock_->TrySetEpochOnce(epoch, timing::MasterClock::EpochSetterRole::LIVE);
      std::cout << "[PlayoutEngine] Epoch established: " << epoch << "us" << std::endl;
    }

    // Start timeline session (reads epoch from MasterClock)
    if (!state->timeline_controller->StartSession()) {
      return EngineResult(false, "Failed to start timeline session for channel " + std::to_string(channel_id));
    }
    std::cout << "[PlayoutEngine] Phase 8 TimelineController started for channel " << channel_id << std::endl;

    // Start control state machine
    const int64_t now = NowUtc(master_clock_);
    if (!state->control->BeginSession(MakeCommandId("start", channel_id), now)) {
      return EngineResult(false, "Failed to begin session for channel " + std::to_string(channel_id));
    }

    // BlockPlan mode owns actual producer lifecycle. StartChannel establishes only
    // the session shell, timing primitives, and output bus; it must not interpret
    // plan_handle as a media asset or begin playout before StartBlockPlanSession.
    state->control->OnBufferDepth(0, kDefaultBufferSize, NowUtc(master_clock_));

    // ========================================================================
    // Readiness observer wiring (additive, observational only).
    //
    // Contracts: docs/contracts/invariants/air/INV-READINESS-*.md,
    //            docs/contracts/invariants/air/INV-VERDICT-*.md.
    //
    // No playout decision consumes the verdict. The observer is fed via a
    // MetricsExporter CustomMetricsProvider (pull-based on /metrics scrape)
    // and via explicit snapshot calls at channel-lifecycle edges. Transitions
    // produce a structured log line. Phase 1: video/audio primed and A/V
    // phase signals are not available at this layer and are treated as
    // not-yet-observable; the readiness reason class reflects phase-derived
    // state only. Enriching the snapshot with PipelineManager-owned signals
    // is a follow-on step.
    // ========================================================================
    state->readiness_has_ever_been_ready = std::make_shared<std::atomic<bool>>(false);
    auto transition_cb = [channel_id](const readiness::TransitionEvent& ev) {
      std::cout << "[Readiness] channel=" << channel_id
                << " from=" << static_cast<int>(ev.from_verdict)
                << " to=" << static_cast<int>(ev.to_verdict)
                << " reason=" << static_cast<int>(ev.reason)
                << " utc_ms=" << ev.utc_ms << std::endl;
    };
    state->readiness_observer = std::make_shared<readiness::ReadinessObserver>(
        channel_id, metrics_exporter_, transition_cb);
    state->readiness_control_box =
        std::make_shared<PlayoutInstance::ReadinessControlBox>();
    {
      std::lock_guard<std::mutex> box_lock(state->readiness_control_box->mtx);
      state->readiness_control_box->control = state->control.get();
    }

    // Register a per-channel CustomMetricsProvider that emits two gauges on
    // /metrics scrape: retrovue_readiness_verdict{channel}, and
    // retrovue_readiness_reason_class{channel}. The provider also drives
    // observer.Evaluate() on each scrape so transitions are observable.
    std::weak_ptr<PlayoutInstance::ReadinessControlBox> box_weak =
        state->readiness_control_box;
    std::weak_ptr<readiness::ReadinessObserver> observer_weak =
        state->readiness_observer;
    std::weak_ptr<std::atomic<bool>> latch_weak =
        state->readiness_has_ever_been_ready;
    state->readiness_provider_name =
        "readiness_channel_" + std::to_string(channel_id);
    metrics_exporter_->RegisterCustomMetricsProvider(
        state->readiness_provider_name,
        [channel_id, box_weak, observer_weak, latch_weak]() -> std::string {
          auto box = box_weak.lock();
          auto obs = observer_weak.lock();
          auto latch = latch_weak.lock();
          if (!box || !obs || !latch) return "";

          readiness::SessionReadinessSnapshot snap{};
          readiness::PipelineSignals pipeline_signals;
          {
            std::lock_guard<std::mutex> box_lock(box->mtx);
            if (box->control == nullptr) return "";
            snap.phase = box->control->state();
            snap.sink_attached = box->control->IsSinkAttached();
            snap.fallback_engaged = box->control->IsInFallback();
            // D+1: if a BlockPlan signal getter is attached, query it under
            // the same mutex that brackets pipeline lifetime. If no getter
            // is attached, pipeline_signals.snapshot_valid remains false and
            // primed / av fields fall back to neutral stubs below.
            if (box->blockplan_signal_getter) {
              pipeline_signals = box->blockplan_signal_getter();
            }
          }
          if (pipeline_signals.snapshot_valid) {
            snap.video_primed = pipeline_signals.video_primed;
            snap.audio_primed = pipeline_signals.audio_primed;
            snap.av_delta_within_tolerance = pipeline_signals.av_within_tolerance;
          } else {
            // Phase-1 stubs: no BlockPlan layer attached yet.
            snap.video_primed = false;
            snap.audio_primed = false;
            snap.av_delta_within_tolerance = true;
          }
          snap.session_ended_error = false;
          snap.fatal_underflow_emitted = false;
          snap.has_ever_been_ready = latch->load(std::memory_order_acquire);
          snap.utc_ms = 0;

          obs->Evaluate(snap);
          const auto rec = obs->Current();
          if (rec.verdict == readiness::Verdict::kReady) {
            latch->store(true, std::memory_order_release);
          }

          std::ostringstream out;
          out << "# HELP retrovue_readiness_verdict Readiness verdict "
                 "(0=READY, 1=NOT_READY, 2=DEGRADED)\n";
          out << "# TYPE retrovue_readiness_verdict gauge\n";
          out << "retrovue_readiness_verdict{channel=\"" << channel_id << "\"} "
              << static_cast<int>(rec.verdict) << "\n";
          out << "# HELP retrovue_readiness_reason_class Readiness reason "
                 "class (numeric enum)\n";
          out << "# TYPE retrovue_readiness_reason_class gauge\n";
          out << "retrovue_readiness_reason_class{channel=\"" << channel_id
              << "\"} " << static_cast<int>(rec.reason) << "\n";
          return out.str();
        });

    // Seed the observer with the initial startup snapshot so any subsequent
    // scrape reflects the current session rather than the sentinel.
    {
      readiness::SessionReadinessSnapshot initial{};
      initial.phase = state->control->state();
      initial.sink_attached = state->control->IsSinkAttached();
      initial.fallback_engaged = state->control->IsInFallback();
      state->readiness_observer->Evaluate(initial);
    }

    // ========================================================================
    // Seam authority wiring (additive, observational only).
    //
    // Contracts: docs/contracts/invariants/air/INV-SEAM-*.md.
    //
    // Turn D scope: construct the per-channel SeamController, attach a
    // transition-log callback, and register a CustomMetricsProvider that
    // publishes the controller's current {state, disposition, reason} as
    // Prometheus gauges on /metrics scrape. No ArmBoundary or Evaluate
    // calls are issued from production flow in this turn; the controller
    // remains in kIdle until Turn D+1 adds the PipelineManager signal
    // bridge and the per-boundary ArmBoundary sites.
    // ========================================================================
    auto seam_transition_cb = [channel_id](const seam::TransitionEvent& ev) {
      std::cout << "[Seam] channel=" << channel_id
                << " boundary=" << ev.boundary_index
                << " from=" << static_cast<int>(ev.from_state)
                << " to=" << static_cast<int>(ev.to_state)
                << " disposition=" << static_cast<int>(ev.disposition)
                << " reason=" << static_cast<int>(ev.reason)
                << " utc_ms=" << ev.utc_ms << std::endl;
    };
    state->seam_controller = std::make_shared<seam::SeamController>(
        channel_id, seam_transition_cb);

    // Register a per-channel CustomMetricsProvider that emits three gauges
    // on /metrics scrape: retrovue_seam_state, retrovue_seam_disposition,
    // retrovue_seam_reason_class. The provider reads Current() — no
    // evaluator call on scrape since Turn D has no signal bridge.
    std::weak_ptr<seam::SeamController> seam_controller_weak =
        state->seam_controller;
    state->seam_provider_name =
        "seam_channel_" + std::to_string(channel_id);
    metrics_exporter_->RegisterCustomMetricsProvider(
        state->seam_provider_name,
        [channel_id, seam_controller_weak]() -> std::string {
          auto sc = seam_controller_weak.lock();
          if (!sc) return "";

          const auto rec = sc->Current();

          std::ostringstream out;
          out << "# HELP retrovue_seam_state Seam boundary state "
                 "(0=kIdle,1=kArmed,2=kExecuting,3=kCommitted,4=kMissed,"
                 "5=kPadBridging,6=kCompleted)\n";
          out << "# TYPE retrovue_seam_state gauge\n";
          out << "retrovue_seam_state{channel=\"" << channel_id << "\"} "
              << static_cast<int>(rec.state) << "\n";
          out << "# HELP retrovue_seam_disposition Seam disposition "
                 "(0=kUnresolved,1=kCutover,2=kPadBridge,3=kJip)\n";
          out << "# TYPE retrovue_seam_disposition gauge\n";
          out << "retrovue_seam_disposition{channel=\"" << channel_id
              << "\"} " << static_cast<int>(rec.disposition) << "\n";
          out << "# HELP retrovue_seam_reason_class Seam reason class "
                 "(numeric enum)\n";
          out << "# TYPE retrovue_seam_reason_class gauge\n";
          out << "retrovue_seam_reason_class{channel=\"" << channel_id
              << "\"} " << static_cast<int>(rec.reason) << "\n";
          return out.str();
        });

    // ========================================================================
    // Bootstrap content-gate wiring (Option C, Turn D — observer-only).
    //
    // Contracts: docs/contracts/invariants/air/INV-BOOTSTRAP-*.md.
    //
    // The gate lives inside PipelineManager and is evaluated on every
    // tick during bootstrap. This block wires a CustomMetricsProvider
    // that reads the gate snapshot via the attached getter and publishes
    // state + last-kickoff fields as Prometheus gauges. Turn D does not
    // influence emission; the existing phase-gate loop still controls
    // session start.
    // ========================================================================
    state->bootstrap_gate_control_box =
        std::make_shared<PlayoutInstance::BootstrapGateControlBox>();
    std::weak_ptr<PlayoutInstance::BootstrapGateControlBox>
        bootstrap_box_weak = state->bootstrap_gate_control_box;
    state->bootstrap_gate_provider_name =
        "bootstrap_gate_channel_" + std::to_string(channel_id);
    metrics_exporter_->RegisterCustomMetricsProvider(
        state->bootstrap_gate_provider_name,
        [channel_id, bootstrap_box_weak]() -> std::string {
          auto box = bootstrap_box_weak.lock();
          if (!box) return "";
          bootstrap::GateMetricsSnapshot snap{};
          {
            std::lock_guard<std::mutex> lk(box->mtx);
            if (!box->getter) return "";
            snap = box->getter();
          }
          std::ostringstream out;
          out << "# HELP retrovue_bootstrap_gate_state Bootstrap content-"
                 "gate state (0=kClosed, 1=kOpen)\n";
          out << "# TYPE retrovue_bootstrap_gate_state gauge\n";
          out << "retrovue_bootstrap_gate_state{channel=\"" << channel_id
              << "\"} " << static_cast<int>(snap.state) << "\n";
          out << "# HELP retrovue_bootstrap_gate_kickoff_fired 1 once the "
                 "bootstrap content gate has opened this session\n";
          out << "# TYPE retrovue_bootstrap_gate_kickoff_fired gauge\n";
          out << "retrovue_bootstrap_gate_kickoff_fired{channel=\""
              << channel_id << "\"} " << (snap.kickoff_fired ? 1 : 0)
              << "\n";
          out << "# HELP retrovue_bootstrap_gate_kickoff_tick Main-loop "
                 "tick index at which the bootstrap content gate opened "
                 "(-1 if not yet)\n";
          out << "# TYPE retrovue_bootstrap_gate_kickoff_tick gauge\n";
          out << "retrovue_bootstrap_gate_kickoff_tick{channel=\""
              << channel_id << "\"} "
              << (snap.kickoff_fired ? snap.last_kickoff.tick_index
                                      : int64_t{-1})
              << "\n";
          out << "# HELP retrovue_bootstrap_gate_kickoff_front_delta_us "
                 "Source-time delta between audio_buffer.front() and "
                 "video_buffer.front() at kickoff (microseconds; "
                 "segment-local, origin-corrected)\n";
          out << "# TYPE retrovue_bootstrap_gate_kickoff_front_delta_us "
                 "gauge\n";
          out << "retrovue_bootstrap_gate_kickoff_front_delta_us{channel="
                 "\""
              << channel_id << "\"} "
              << (snap.kickoff_fired ? snap.last_kickoff.front_delta_us
                                      : int64_t{0})
              << "\n";
          out << "# HELP retrovue_bootstrap_existing_gate_opened 1 once "
                 "EvaluateBootstrapPhaseGate phase_valid break has "
                 "fired this session\n";
          out << "# TYPE retrovue_bootstrap_existing_gate_opened gauge\n";
          out << "retrovue_bootstrap_existing_gate_opened{channel=\""
              << channel_id << "\"} "
              << (snap.existing_gate_opened ? 1 : 0) << "\n";
          out << "# HELP retrovue_bootstrap_existing_gate_front_delta_us "
                 "Source-time delta between audio and video buffer "
                 "fronts at the moment the existing phase gate opened "
                 "(microseconds; segment-local, origin-corrected). "
                 "Directly comparable to "
                 "retrovue_bootstrap_gate_kickoff_front_delta_us.\n";
          out << "# TYPE retrovue_bootstrap_existing_gate_front_delta_us "
                 "gauge\n";
          out << "retrovue_bootstrap_existing_gate_front_delta_us{channel="
                 "\""
              << channel_id << "\"} "
              << snap.existing_gate_front_delta_us << "\n";
          // Ordering code:
          //   -1 = new gate never opened (or hasn't yet) after existing
          //   0  = new gate was already open when existing gate opened
          //        (new opened first, same wait-loop iteration or earlier)
          //   N  = new gate opened N main-loop ticks AFTER existing gate
          //        (tick_index encodes the delay)
          int64_t new_vs_existing = -1;
          if (snap.kickoff_fired && snap.existing_gate_opened) {
            new_vs_existing = snap.new_gate_was_open_at_existing_open
                                  ? 0
                                  : std::max<int64_t>(
                                        0, snap.last_kickoff.tick_index);
          }
          out << "# HELP retrovue_bootstrap_new_vs_existing_ticks "
                 "Ordering of the new Option-C gate relative to the "
                 "existing phase gate. -1 = new has not opened; "
                 "0 = new opened first (or same wait-loop iteration); "
                 ">0 = new opened that many main-loop ticks AFTER the "
                 "existing gate.\n";
          out << "# TYPE retrovue_bootstrap_new_vs_existing_ticks "
                 "gauge\n";
          out << "retrovue_bootstrap_new_vs_existing_ticks{channel=\""
              << channel_id << "\"} " << new_vs_existing << "\n";
          return out.str();
        });

    // Submit ready metrics
    telemetry::ChannelMetrics metrics{};
    metrics.state = telemetry::ChannelState::BUFFERING;
    metrics.buffer_depth_frames = 0;
    metrics_exporter_->SubmitChannelMetrics(channel_id, metrics);
    
    // Store channel state
    instance_ = std::move(state);

    return EngineResult(true, "Channel " + std::to_string(channel_id) + " initialized for BlockPlan session");
  } catch (const std::exception& e) {
    return EngineResult(false, "Exception starting channel " + std::to_string(channel_id) + ": " + e.what());
  }
}

EngineResult PlayoutEngine::StopChannel(int32_t channel_id) {
  std::lock_guard<std::mutex> lock(channels_mutex_);

  auto* state = FindInstanceLocked(channel_id);
  if (!state) {
    // Idempotent success — broadcast systems favor safe, idempotent stop
    return EngineResult(true, "Channel " + std::to_string(channel_id) + " already stopped or unknown");
  }

  // Readiness observer teardown (additive, observational only).
  // Order:
  //   1. Null the ControlBox's PlayoutControl* under its own mutex.
  //      Any in-flight scrape holding the box mutex completes with a
  //      valid pointer; any scrape entering after sees null and exits.
  //   2. Unregister the CustomMetricsProvider so no new scrape fires.
  //   3. Proceed with normal teardown (state destruction happens at
  //      instance_.reset() later in this function).
  if (state->readiness_control_box) {
    std::lock_guard<std::mutex> box_lock(state->readiness_control_box->mtx);
    state->readiness_control_box->control = nullptr;
  }
  if (!state->readiness_provider_name.empty() && metrics_exporter_) {
    metrics_exporter_->UnregisterCustomMetricsProvider(
        state->readiness_provider_name);
  }

  // Seam authority teardown (additive, observational only). Turn D
  // scope: the provider captures a weak_ptr<SeamController>; the lambda
  // early-exits if lock() fails. Unregister here so no new scrape fires
  // during state destruction. The controller's shared_ptr on PlayoutInstance
  // is dropped naturally when state is destroyed at instance_.reset().
  if (!state->seam_provider_name.empty() && metrics_exporter_) {
    metrics_exporter_->UnregisterCustomMetricsProvider(
        state->seam_provider_name);
  }

  // Bootstrap gate teardown (additive, observational only). Same pattern
  // as readiness: null the getter under the box's mutex first, then
  // unregister the provider so no new scrape fires while state is torn
  // down. playout_service detaches the getter earlier as well — this is
  // a belt-and-braces guard in case StopChannel is called on a session
  // that never ran a BlockPlan detach.
  if (state->bootstrap_gate_control_box) {
    std::lock_guard<std::mutex> box_lock(
        state->bootstrap_gate_control_box->mtx);
    state->bootstrap_gate_control_box->getter = nullptr;
  }
  if (!state->bootstrap_gate_provider_name.empty() && metrics_exporter_) {
    metrics_exporter_->UnregisterCustomMetricsProvider(
        state->bootstrap_gate_provider_name);
  }

  if (control_surface_only_) {
    instance_.reset();
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

    // Phase 9.0: Detach any attached output sink
    // OB-003: DetachSink always succeeds, Core-owned decision
    if (state->output_bus) {
      state->output_bus->DetachSink();
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
    instance_.reset();

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

  auto* state = FindInstanceLocked(channel_id);
  if (!state) {
    return EngineResult(false, "Channel " + std::to_string(channel_id) + " not found");
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
  retrovue::blockplan::RationalFps fps_r = (fps_denominator > 0)
      ? retrovue::blockplan::RationalFps(fps_numerator, fps_denominator)
      : retrovue::blockplan::DeriveRationalFPS(state->program_format.GetFrameRateAsDouble());
  int64_t start_offset_ms = fps_r.DurationFromFramesUs(start_frame) / 1000;
  // frame_count is authoritative - no need to convert back to wall-clock time
  // (hard_stop_time_ms was deprecated, we use frame_count directly now)

  try {
    // Create preview producer config
    producers::file::ProducerConfig preview_config;
    preview_config.asset_uri = asset_path;
    preview_config.target_fps = fps_r;
    preview_config.stub_mode = false;
    preview_config.target_width = state->program_format.video.width;
    preview_config.target_height = state->program_format.video.height;
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
    // LAW-OBS-004: Log load preview effective timing.
    // TODO(LAW-OBS-002): correlation_id not propagated to PlayoutEngine::LoadPreview; cannot populate.
    retrovue::util::LogLoadPreviewEffective(
        /*correlation_id=*/"", channel_id, asset_path,
        std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count());
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
      auto* s = FindInstanceLocked(channel_id);
      if (!s) break;

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

        // P8-FILL-003: End content deficit fill when watcher completes switch
        EndContentDeficitFill(s);

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

        // INV-P8-SHADOW-PREROLL-SYNC: Align ct_cursor to the last buffered frame's MT.
        if (s->timeline_controller && video_depth > 0 && s->live_producer) {
          s->timeline_controller->AlignCursorToLastBufferedMT(s->live_producer->GetLastShadowVideoMT());
        }

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
      auto* s = FindInstanceLocked(channel_id);
      if (s) {
        s->switch_watcher_running.store(false);
      }
    }
    std::cerr << "[SwitchWatcher] INV-P8-SWITCH-READINESS: TIMEOUT after 10s" << std::endl;
  }).detach();
}

EngineResult PlayoutEngine::SwitchToLive(int32_t channel_id, int64_t target_boundary_time_ms, int64_t issued_at_time_ms) {
  std::unique_lock<std::mutex> lock(channels_mutex_);

  auto* state = FindInstanceLocked(channel_id);
  if (!state) {
    return EngineResult(false, "Channel " + std::to_string(channel_id) + " not found");
  }

  // P11C-003: INV-BOUNDARY-DECLARED-001 — log receipt of target boundary time
  if (target_boundary_time_ms > 0) {
    std::cout << "[PlayoutEngine] INV-BOUNDARY-DECLARED-001: SwitchToLive received with target_boundary_time_ms="
              << target_boundary_time_ms << std::endl;
  } else {
    std::cout << "[PlayoutEngine] INV-BOUNDARY-DECLARED-001: SwitchToLive received without target (legacy mode)" << std::endl;
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
    auto completion_time = std::chrono::steady_clock::now();
    result.switch_completion_time_ms = static_cast<int64_t>(
        std::chrono::duration_cast<std::chrono::milliseconds>(completion_time.time_since_epoch()).count());
    if (target_boundary_time_ms > 0 && metrics_exporter_) {
      int64_t delta_ms = result.switch_completion_time_ms - target_boundary_time_ms;
      const int64_t tolerance_ms = 33;
      if (delta_ms > tolerance_ms) {
        std::cout << "[PlayoutEngine] INV-BOUNDARY-TOLERANCE-001 VIOLATION: Switch completed " << delta_ms
                  << "ms late (target=" << target_boundary_time_ms << ", actual=" << result.switch_completion_time_ms
                  << ", tolerance=" << tolerance_ms << "ms)" << std::endl;
        metrics_exporter_->RecordSwitchBoundaryDelta(channel_id, delta_ms);
        metrics_exporter_->IncrementBoundaryViolations(channel_id);
      } else {
        std::cout << "[PlayoutEngine] INV-BOUNDARY-TOLERANCE-001: Switch on time (delta=" << delta_ms
                  << "ms, tolerance=" << tolerance_ms << "ms)" << std::endl;
        metrics_exporter_->RecordSwitchBoundaryDelta(channel_id, delta_ms);
      }
    }
    // LAW-OBS-004: Log switch effective timing.
    // TODO(LAW-OBS-002): correlation_id not propagated here; cannot populate.
    retrovue::util::LogSwitchToLiveEffective(
        /*correlation_id=*/"", channel_id, result.switch_completion_time_ms);
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
    auto completion_time = std::chrono::steady_clock::now();
    result.switch_completion_time_ms = static_cast<int64_t>(
        std::chrono::duration_cast<std::chrono::milliseconds>(completion_time.time_since_epoch()).count());
    if (target_boundary_time_ms > 0 && metrics_exporter_) {
      int64_t delta_ms = result.switch_completion_time_ms - target_boundary_time_ms;
      const int64_t tolerance_ms = 33;
      if (delta_ms > tolerance_ms) {
        std::cout << "[PlayoutEngine] INV-BOUNDARY-TOLERANCE-001 VIOLATION: Switch completed " << delta_ms
                  << "ms late (target=" << target_boundary_time_ms << ", actual=" << result.switch_completion_time_ms
                  << ", tolerance=" << tolerance_ms << "ms)" << std::endl;
        metrics_exporter_->RecordSwitchBoundaryDelta(channel_id, delta_ms);
        metrics_exporter_->IncrementBoundaryViolations(channel_id);
      } else {
        std::cout << "[PlayoutEngine] INV-BOUNDARY-TOLERANCE-001: Switch on time (delta=" << delta_ms
                  << "ms, tolerance=" << tolerance_ms << "ms)" << std::endl;
        metrics_exporter_->RecordSwitchBoundaryDelta(channel_id, delta_ms);
      }
    }
    // LAW-OBS-004: Log switch effective timing (auto-completed path).
    // TODO(LAW-OBS-002): correlation_id not propagated here; cannot populate.
    retrovue::util::LogSwitchToLiveEffective(
        /*correlation_id=*/"", channel_id, result.switch_completion_time_ms);
    return result;
  }

  if (!state->preview_producer) {
    EngineResult result(false, "No preview producer loaded for channel " + std::to_string(channel_id));
    result.result_code = ResultCode::kProtocolViolation;
    return result;
  }

  // P11D-001/004: Deadline-authoritative mode — schedule switch at target time
  if (target_boundary_time_ms > 0) {
    const int64_t now_us = NowUtc(master_clock_);
    const int64_t now_ms = now_us / 1000;
    // P11D-012: INV-LEADTIME-MEASUREMENT-001 — use issuance time for lead-time evaluation, not receipt time
    // This ensures RPC transport latency does not consume the lead time budget.
    const int64_t evaluation_time_ms = (issued_at_time_ms > 0) ? issued_at_time_ms : now_ms;
    const int64_t lead_time_ms = target_boundary_time_ms - evaluation_time_ms;
    // Log transport delta for clock skew detection
    if (issued_at_time_ms > 0) {
      const int64_t transport_delta_ms = now_ms - issued_at_time_ms;
      std::cout << "[SwitchToLive] INV-LEADTIME-MEASUREMENT-001: issued_at_time_ms=" << issued_at_time_ms
                << " receipt_time_ms=" << now_ms
                << " transport_delta_ms=" << transport_delta_ms
                << " lead_time_ms=" << lead_time_ms
                << " MIN_PREFEED_LEAD_TIME_MS=" << kMinPrefeedLeadTimeMs << std::endl;
      if (transport_delta_ms < -1000 || transport_delta_ms > 1000) {
        std::cout << "[SwitchToLive] WARN: Clock skew detected (transport_delta_ms=" << transport_delta_ms << ")" << std::endl;
      }
    } else {
      std::cout << "[SwitchToLive] AIR on receipt (legacy): air_now_ms=" << now_ms
                << " target_boundary_time_ms=" << target_boundary_time_ms
                << " lead_time_ms=" << lead_time_ms
                << " MIN_PREFEED_LEAD_TIME_MS=" << kMinPrefeedLeadTimeMs << std::endl;
    }
    if (lead_time_ms < kMinPrefeedLeadTimeMs) {
      std::cout << "[PlayoutEngine] INV-CONTROL-NO-POLL-001 VIOLATION: SwitchToLive received with insufficient lead time ("
                << lead_time_ms << " ms < " << kMinPrefeedLeadTimeMs << " ms required)" << std::endl;
      EngineResult result(false, "Insufficient prefeed lead time");
      result.result_code = ResultCode::kProtocolViolation;
      result.violation_reason = "Insufficient prefeed lead time";
      return result;
    }
    std::cout << "[PlayoutEngine] INV-SWITCH-DEADLINE-AUTHORITATIVE-001: Switch scheduled for " << target_boundary_time_ms << std::endl;
    state->target_boundary_time_ms_ = target_boundary_time_ms;  // P8-FILL-001: so OnLiveProducerEOF can compute boundary_ct
    lock.unlock();
    const int64_t target_us = target_boundary_time_ms * 1000;
    if (master_clock_) {
      master_clock_->WaitUntilUtcUs(target_us);
    } else {
      const auto now_sys = std::chrono::system_clock::now();
      const int64_t now_sys_us = std::chrono::duration_cast<std::chrono::microseconds>(now_sys.time_since_epoch()).count();
      const int64_t remaining_us = target_us - now_sys_us;
      if (remaining_us > 0) {
        std::this_thread::sleep_for(std::chrono::microseconds(remaining_us));
      }
    }
    lock.lock();
    state = FindInstanceLocked(channel_id);
    if (!state) {
      return EngineResult(false, "Channel " + std::to_string(channel_id) + " not found after wait");
    }
    if (!state->preview_producer) {
      return EngineResult(false, "No preview producer for channel " + std::to_string(channel_id) + " at deadline");
    }
    return ExecuteSwitchAtDeadline(channel_id, target_boundary_time_ms, lock);
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
              SpawnSwitchWatcher(channel_id, state);
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
            retrovue::blockplan::RationalFps fps_r = retrovue::blockplan::DeriveRationalFPS(state->program_format.GetFrameRateAsDouble());
            int64_t frame_period_us = fps_r.FrameDurationUs();
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
        // ORCH-SWITCH-SUCCESSOR-OBSERVED: Zero-content segment has no real frames;
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
      SpawnSwitchWatcher(channel_id, state);

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

    EndContentDeficitFill(state);

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

    // INV-P8-SHADOW-PREROLL-SYNC: Align ct_cursor to the last buffered frame's MT.
    if (state->timeline_controller && preview_depth_before > 0 && state->live_producer) {
      state->timeline_controller->AlignCursorToLastBufferedMT(state->live_producer->GetLastShadowVideoMT());
    }

    // ORCHESTRATION BOUNDARY:
    // This wait gates SwitchToLive RPC completion only.
    // It MUST NOT affect CT, epoch, frame pacing, or emission timing.
    // This is NOT a timing or pressure mechanism.
    constexpr auto kSuccessorEmitWaitTimeout = std::chrono::seconds(30);
    const auto wait_start = std::chrono::steady_clock::now();
    PlayoutInstance* state_ptr = state;
    while (!state_ptr->successor_video_emitted_.load(std::memory_order_acquire)) {
      lock.unlock();
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
      lock.lock();
      state_ptr = FindInstanceLocked(channel_id);
      if (!state_ptr) {
        return EngineResult(false, "Channel " + std::to_string(channel_id) + " lost during switch wait");
      }
      if (std::chrono::steady_clock::now() - wait_start > kSuccessorEmitWaitTimeout) {
        std::cerr << "[SwitchToLive] ORCH-SWITCH-SUCCESSOR-OBSERVED VIOLATION: timeout waiting for successor video emission" << std::endl;
        return EngineResult(false, "ORCH-SWITCH-SUCCESSOR-OBSERVED: timeout waiting for successor video emission");
      }
    }

    EngineResult result(true, "Switched to live for channel " + std::to_string(channel_id));
    result.pts_contiguous = true;
    result.live_start_pts = 0;  // Direct completion - no PTS alignment needed
    result.result_code = ResultCode::kOk;
    auto completion_time = std::chrono::steady_clock::now();
    result.switch_completion_time_ms = static_cast<int64_t>(
        std::chrono::duration_cast<std::chrono::milliseconds>(completion_time.time_since_epoch()).count());
    if (target_boundary_time_ms > 0 && metrics_exporter_) {
      int64_t delta_ms = result.switch_completion_time_ms - target_boundary_time_ms;
      const int64_t tolerance_ms = 33;
      if (delta_ms > tolerance_ms) {
        std::cout << "[PlayoutEngine] INV-BOUNDARY-TOLERANCE-001 VIOLATION: Switch completed " << delta_ms
                  << "ms late (target=" << target_boundary_time_ms << ", actual=" << result.switch_completion_time_ms
                  << ", tolerance=" << tolerance_ms << "ms)" << std::endl;
        metrics_exporter_->RecordSwitchBoundaryDelta(channel_id, delta_ms);
        metrics_exporter_->IncrementBoundaryViolations(channel_id);
      } else {
        std::cout << "[PlayoutEngine] INV-BOUNDARY-TOLERANCE-001: Switch on time (delta=" << delta_ms
                  << "ms, tolerance=" << tolerance_ms << "ms)" << std::endl;
        metrics_exporter_->RecordSwitchBoundaryDelta(channel_id, delta_ms);
      }
    }

    // LAW-OBS-004: Log switch effective timing (direct completion path).
    // TODO(LAW-OBS-002): correlation_id not propagated here; cannot populate.
    retrovue::util::LogSwitchToLiveEffective(
        /*correlation_id=*/"", channel_id, result.switch_completion_time_ms);
    return result;
  } catch (const std::exception& e) {
    EngineResult ex_result(false, "Exception switching to live for channel " + std::to_string(channel_id) + ": " + e.what());
    ex_result.result_code = ResultCode::kFailed;
    return ex_result;
  }
}

EngineResult PlayoutEngine::ExecuteSwitchAtDeadline(int32_t channel_id, int64_t target_boundary_time_ms,
                                                   std::unique_lock<std::mutex>& lock) {
  // P11D-001/002/003: Caller holds lock; execute switch at deadline regardless of readiness.
  PlayoutInstance* state = FindInstanceLocked(channel_id);
  if (!state) {
    return EngineResult(false, "Channel " + std::to_string(channel_id) + " not found");
  }
  if (!state->preview_producer) {
    return EngineResult(false, "No preview producer for channel " + std::to_string(channel_id));
  }

  // P8-FILL-003: End content deficit fill when switch executes
  EndContentDeficitFill(state);

  constexpr size_t kMinPreviewVideoDepth = 2;
  const bool is_shadow_mode = state->preview_producer->IsShadowDecodeMode();
  const bool shadow_ready = state->preview_producer->IsShadowDecodeReady();
  const size_t preview_video_depth = state->preview_ring_buffer ? state->preview_ring_buffer->Size() : 0;
  const bool live_eof = state->live_producer && state->live_producer->IsEOF();
  const bool preview_eof = state->preview_producer && state->preview_producer->IsEOF();
  const bool preview_eof_with_frames = preview_eof && preview_video_depth >= 1;
  const bool ready = (is_shadow_mode ? shadow_ready : true) &&
      (preview_video_depth >= kMinPreviewVideoDepth || live_eof || preview_eof_with_frames);

  if (!ready) {
    std::cout << "[PlayoutEngine] INV-SWITCH-DEADLINE-AUTHORITATIVE-001 VIOLATION: Switch executed at deadline but preview not ready. Using safety rails." << std::endl;
    // ==========================================================================
    // HYPOTHESIS TEST T2: Log buffer state when safety rail engages
    // ==========================================================================
    // H2 predicts: preview_audio_depth high, preview_video_depth low/zero
    // This confirms audio backpressure blocked video production before switch.
    const size_t preview_audio_depth = state->preview_ring_buffer ? state->preview_ring_buffer->AudioSize() : 0;
    const size_t preview_audio_capacity = state->preview_ring_buffer ? state->preview_ring_buffer->AudioCapacity() : 0;
    const size_t preview_video_capacity = state->preview_ring_buffer ? state->preview_ring_buffer->Capacity() : 0;
    std::cout << "[PlayoutEngine] HYPOTHESIS_TEST_T2: safety_rail=true "
              << "preview_video=" << preview_video_depth << "/" << preview_video_capacity
              << " preview_audio=" << preview_audio_depth << "/" << preview_audio_capacity
              << " (H2 predicts: audio_high, video_low)" << std::endl;
    if (preview_audio_depth > preview_video_depth * 3) {
      std::cout << "[PlayoutEngine] HYPOTHESIS_TEST_T2: AUDIO_IMBALANCE_DETECTED "
                << "(audio >> video*3, consistent with H1/H2)" << std::endl;
    }
    if (metrics_exporter_) {
      metrics_exporter_->IncrementSwitchDeadlineNotReady(channel_id);
    }
    if (state->program_output) {
      state->program_output->SetNoContentSegment(true);
    }
    std::cout << "[PlayoutEngine] Safety rails engaged for channel " << channel_id << std::endl;
    state->successor_video_emitted_.store(true, std::memory_order_release);
  }

  std::cout << "[PlayoutEngine] INV-SWITCH-DEADLINE-AUTHORITATIVE-001: Executing scheduled switch at " << target_boundary_time_ms
            << ", readiness=" << (ready ? "true" : "false") << std::endl;

  if (is_shadow_mode) {
    if (!shadow_ready) {
      // At deadline we still do handshake; preview may have cached frame by now or we rely on safety rails
      (void)0;
    }
    if (!state->timeline_controller) {
      int64_t last_emitted_pts = 0;
      if (state->program_output) {
        last_emitted_pts = state->program_output->GetLastEmittedPTS();
        if (last_emitted_pts > 0) {
          retrovue::blockplan::RationalFps fps_r = retrovue::blockplan::DeriveRationalFPS(state->program_format.GetFrameRateAsDouble());
          int64_t frame_period_us = fps_r.FrameDurationUs();
          state->preview_producer->AlignPTS(last_emitted_pts + frame_period_us);
        }
      }
    }
    if (state->live_producer && state->timeline_controller) {
      state->live_producer->SetWriteBarrier();
    }
    if (state->timeline_controller && !state->timeline_controller->IsMappingPending()) {
      state->timeline_controller->BeginSegmentFromPreview();
    }
    state->preview_producer->SetShadowDecodeMode(false);
    (void)state->preview_producer->FlushCachedFrameToBuffer();
    if (state->preview_producer->GetConfiguredFrameCount() == 0) {
      if (state->program_output) {
        state->program_output->SetNoContentSegment(true);
      }
      state->successor_video_emitted_.store(true, std::memory_order_release);
    }
  }

  size_t preview_depth_before = state->preview_ring_buffer ? state->preview_ring_buffer->Size() : 0;
  size_t preview_audio_depth = state->preview_ring_buffer ? state->preview_ring_buffer->AudioSize() : 0;

  state->successor_video_emitted_.store(ready ? false : true, std::memory_order_release);
  const int64_t first_pts_us = state->program_output ? state->program_output->GetFirstEmittedPTS() : 0;
  const int64_t last_pts_us = state->program_output ? state->program_output->GetLastEmittedPTS() : 0;

  MaybeRequestStop(state->live_producer.get());
  std::unique_ptr<producers::file::FileProducer> old_producer = std::move(state->live_producer);

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

  state->switch_in_progress = false;
  state->switch_target_asset.clear();
  state->switch_watcher_stop.store(true);

  std::cout << "[SwitchToLive] INV-SWITCH-DEADLINE-AUTHORITATIVE-001: COMPLETE "
            << "(video=" << preview_depth_before << ", audio=" << preview_audio_depth
            << ", asset=" << state->live_asset_path << ", safety_rail=" << (!ready ? "true" : "false") << ")" << std::endl;

  // INV-P8-SHADOW-PREROLL-SYNC: Align ct_cursor to the last buffered frame's MT.
  if (state->timeline_controller && preview_depth_before > 0 && state->live_producer) {
    state->timeline_controller->AlignCursorToLastBufferedMT(state->live_producer->GetLastShadowVideoMT());
  }

  // ORCHESTRATION BOUNDARY:
  // This wait gates SwitchToLive RPC completion only.
  // It MUST NOT affect CT, epoch, frame pacing, or emission timing.
  // This is NOT a timing or pressure mechanism.
  PlayoutInstance* state_ptr = state;
  constexpr auto kSuccessorEmitWaitTimeout = std::chrono::seconds(30);
  const auto wait_start = std::chrono::steady_clock::now();
  while (!state_ptr->successor_video_emitted_.load(std::memory_order_acquire)) {
    lock.unlock();
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    lock.lock();
    state_ptr = FindInstanceLocked(channel_id);
    if (!state_ptr) {
      return EngineResult(false, "Channel " + std::to_string(channel_id) + " lost during switch wait");
    }
    if (std::chrono::steady_clock::now() - wait_start > kSuccessorEmitWaitTimeout) {
      std::cerr << "[SwitchToLive] ORCH-SWITCH-SUCCESSOR-OBSERVED VIOLATION: timeout waiting for successor video emission" << std::endl;
      return EngineResult(false, "ORCH-SWITCH-SUCCESSOR-OBSERVED: timeout waiting for successor video emission");
    }
  }

  EngineResult result(true, "Switched to live for channel " + std::to_string(channel_id));
  result.pts_contiguous = true;
  result.live_start_pts = 0;
  result.result_code = ResultCode::kOk;
  // P11D-007: Return ACTUAL completion time (MasterClock when switch completed), not target
  result.switch_completion_time_ms = NowUtc(master_clock_) / 1000;
  // LAW-OBS-004: Log switch to live effective timing.
  // TODO(LAW-OBS-002): correlation_id not propagated to PlayoutEngine::SwitchToLive; cannot populate.
  retrovue::util::LogSwitchToLiveEffective(
      /*correlation_id=*/"", channel_id, result.switch_completion_time_ms);
  if (metrics_exporter_) {
    const int64_t actual_ms = result.switch_completion_time_ms;
    const int64_t delta_ms = actual_ms - target_boundary_time_ms;
    const int64_t tolerance_ms = 33;
    if (delta_ms > tolerance_ms) {
      std::cout << "[PlayoutEngine] INV-BOUNDARY-TOLERANCE-001 VIOLATION: Switch completed " << delta_ms
                << "ms late (target=" << target_boundary_time_ms << ", actual=" << actual_ms
                << ", tolerance=" << tolerance_ms << "ms)" << std::endl;
      metrics_exporter_->RecordSwitchBoundaryDelta(channel_id, delta_ms);
      metrics_exporter_->IncrementBoundaryViolations(channel_id);
    } else {
      std::cout << "[PlayoutEngine] INV-BOUNDARY-TOLERANCE-001: Switch on time (delta=" << delta_ms
                << "ms, tolerance=" << tolerance_ms << "ms)" << std::endl;
      metrics_exporter_->RecordSwitchBoundaryDelta(channel_id, delta_ms);
    }
  }
  return result;
}

std::optional<std::string> PlayoutEngine::GetLiveAssetPath(int32_t channel_id) {
  std::lock_guard<std::mutex> lock(channels_mutex_);
  auto* state = FindInstanceLocked(channel_id);
  if (!state)
    return std::nullopt;
  const std::string& path = state->live_asset_path;
  if (path.empty())
    return std::nullopt;
  return path;
}

void PlayoutEngine::RegisterMuxFrameCallback(int32_t channel_id,
                                             std::function<void(const buffer::Frame&)> callback) {
  std::lock_guard<std::mutex> lock(channels_mutex_);
  auto* state = FindInstanceLocked(channel_id);
  if (!state || !state->program_output)
    return;
  state->program_output->SetSideSink(std::move(callback));
}

void PlayoutEngine::UnregisterMuxFrameCallback(int32_t channel_id) {
  std::lock_guard<std::mutex> lock(channels_mutex_);
  auto* state = FindInstanceLocked(channel_id);
  if (!state || !state->program_output)
    return;
  state->program_output->ClearSideSink();
}

// Phase 8.9: Audio frame callback registration
void PlayoutEngine::RegisterMuxAudioFrameCallback(int32_t channel_id,
                                                  std::function<void(const buffer::AudioFrame&)> callback) {
  std::lock_guard<std::mutex> lock(channels_mutex_);
  auto* state = FindInstanceLocked(channel_id);
  if (!state || !state->program_output)
    return;
  state->program_output->SetAudioSideSink(std::move(callback));
}

void PlayoutEngine::UnregisterMuxAudioFrameCallback(int32_t channel_id) {
  std::lock_guard<std::mutex> lock(channels_mutex_);
  auto* state = FindInstanceLocked(channel_id);
  if (!state || !state->program_output)
    return;
  state->program_output->ClearAudioSideSink();
}

void PlayoutEngine::AttachBlockPlanSignalSource(
    int32_t channel_id, BlockPlanSignalGetter getter) {
  std::lock_guard<std::mutex> lock(channels_mutex_);
  auto* state = FindInstanceLocked(channel_id);
  if (!state || !state->readiness_control_box)
    return;
  auto& box = state->readiness_control_box;
  std::lock_guard<std::mutex> box_lock(box->mtx);
  box->blockplan_signal_getter = std::move(getter);
}

void PlayoutEngine::AttachBootstrapGateSource(
    int32_t channel_id, BootstrapGateSnapshotGetter getter) {
  std::lock_guard<std::mutex> lock(channels_mutex_);
  auto* state = FindInstanceLocked(channel_id);
  if (!state || !state->bootstrap_gate_control_box) {
    return;
  }
  auto& box = state->bootstrap_gate_control_box;
  std::lock_guard<std::mutex> box_lock(box->mtx);
  box->getter = std::move(getter);
}

void PlayoutEngine::DetachBootstrapGateSource(int32_t channel_id) {
  std::lock_guard<std::mutex> lock(channels_mutex_);
  auto* state = FindInstanceLocked(channel_id);
  if (!state || !state->bootstrap_gate_control_box) {
    return;
  }
  auto& box = state->bootstrap_gate_control_box;
  std::lock_guard<std::mutex> box_lock(box->mtx);
  box->getter = nullptr;
}

void PlayoutEngine::DetachBlockPlanSignalSource(int32_t channel_id) {
  std::lock_guard<std::mutex> lock(channels_mutex_);
  auto* state = FindInstanceLocked(channel_id);
  if (!state || !state->readiness_control_box)
    return;
  auto& box = state->readiness_control_box;
  std::lock_guard<std::mutex> box_lock(box->mtx);
  box->blockplan_signal_getter = nullptr;
}

EngineResult PlayoutEngine::UpdatePlan(
    int32_t channel_id,
    const std::string& plan_handle) {
  std::lock_guard<std::mutex> lock(channels_mutex_);

  auto* state = FindInstanceLocked(channel_id);
  if (!state) {
    return EngineResult(false, "Channel " + std::to_string(channel_id) + " not found");
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
    std::unique_ptr<output::IOutputSink> sink) {
  std::lock_guard<std::mutex> lock(channels_mutex_);

  auto* state = FindInstanceLocked(channel_id);
  if (!state) {
    return EngineResult(false, "Channel " + std::to_string(channel_id) + " not found");
  }

  if (!state->output_bus) {
    return EngineResult(false, "Channel " + std::to_string(channel_id) + " has no OutputBus");
  }

  // INV-P8-SUCCESSOR-OBSERVABILITY: Observer is wired at StartChannel (ProgramOutput).
  // No sink-specific callback; observation happens when ProgramOutput routes real frames.
  //
  // INV-P9-NO-BUS-REPLACEMENT: Always attach to existing bus (state->output_bus).
  // Bus is created once at StartChannel and never replaced.
  //
  // OB-001: If sink already attached, AttachSink returns error (protocol violation).
  // Core must call DetachSink first if replacement is needed.
  std::cout << "[AttachOutputSink] channel=" << channel_id
            << " bus=" << static_cast<void*>(state->output_bus.get())
            << " attaching to existing bus" << std::endl;
  auto result = state->output_bus->AttachSink(std::move(sink));
  std::cout << "[AttachOutputSink] channel=" << channel_id
            << " result=" << (result.success ? "OK" : "FAIL")
            << " sink_attached=" << state->output_bus->HasSink() << std::endl;
  return EngineResult(result.success, result.message);
}

EngineResult PlayoutEngine::DetachOutputSink(int32_t channel_id) {
  std::lock_guard<std::mutex> lock(channels_mutex_);

  auto* state = FindInstanceLocked(channel_id);
  if (!state) {
    return EngineResult(true, "Channel " + std::to_string(channel_id) + " not found (idempotent)");
  }

  if (!state->output_bus) {
    return EngineResult(true, "Channel " + std::to_string(channel_id) + " has no OutputBus (idempotent)");
  }

  // INV-P8-SUCCESSOR-OBSERVABILITY: Observer stays attached (owned by ProgramOutput).
  // Only cleared on StopChannel/EndSession.
  // OB-003: DetachSink always succeeds, Core-owned decision.
  auto result = state->output_bus->DetachSink();
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
  auto* state = FindInstanceLocked(channel_id);
  if (!state || !state->output_bus) {
    return false;
  }
  return state->output_bus->HasSink();
}

output::OutputBus* PlayoutEngine::GetOutputBus(int32_t channel_id) {
  std::lock_guard<std::mutex> lock(channels_mutex_);

  auto* state = FindInstanceLocked(channel_id);
  if (!state) {
    return nullptr;
  }

  return state->output_bus.get();
}

std::optional<ProgramFormat> PlayoutEngine::GetProgramFormat(int32_t channel_id) {
  std::lock_guard<std::mutex> lock(channels_mutex_);

  auto* state = FindInstanceLocked(channel_id);
  if (!state) {
    return std::nullopt;
  }

  return state->program_format;
}

void PlayoutEngine::FinalizeLiveOutput(int32_t channel_id) {
  std::lock_guard<std::mutex> lock(channels_mutex_);

  auto* state = FindInstanceLocked(channel_id);
  if (!state) {
    return;
  }

  // INV-P9-NO-BUS-REPLACEMENT: OutputBus is created once at StartChannel, never replaced.
  // Do NOT create a new bus here; use the existing one from channel state.
  if (!state->output_bus) {
    std::cout << "[FinalizeLiveOutput] channel=" << channel_id
              << " no OutputBus (control_surface_only or not yet started)" << std::endl;
    return;
  }

  if (state->program_output) {
    state->program_output->SetOutputBus(state->output_bus.get());
    bool attached = state->output_bus->HasSink();
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

  auto* state = FindInstanceLocked(channel_id);
  if (!state) {
    return;
  }

  if (state->program_output) {
    state->program_output->ClearOutputBus();
    std::cout << "[PlayoutEngine] Renderer disconnected from OutputBus for channel " << channel_id << std::endl;
  }
}

void PlayoutEngine::OnLiveProducerEOF(int32_t channel_id, const std::string& segment_id,
                                      int64_t ct_at_eof_us, int64_t frames_delivered) {
  // P8-EOF-002 INV-P8-SEGMENT-EOF-DISTINCT-001: EOF does NOT advance boundary; does NOT trigger switch.
  std::cout << "[PlayoutEngine] DECODER_EOF received segment=" << segment_id
            << " channel=" << channel_id
            << " ct_at_eof=" << ct_at_eof_us
            << " frames_delivered=" << frames_delivered
            << " (boundary remains at scheduled time)" << std::endl;

  std::lock_guard<std::mutex> lock(channels_mutex_);
  auto* state = FindInstanceLocked(channel_id);
  if (!state) return;
  if (!state->timeline_controller) return;

  int64_t boundary_ct_us = 0;
  if (state->target_boundary_time_ms_ > 0) {
    const int64_t epoch_us = state->timeline_controller->GetEpoch();
    boundary_ct_us = state->target_boundary_time_ms_ * 1000 - epoch_us;
  }
  if (boundary_ct_us <= 0 || ct_at_eof_us < boundary_ct_us) {
    StartContentDeficitFill(state, segment_id, ct_at_eof_us, boundary_ct_us > 0 ? boundary_ct_us : 0);
  }
}

void PlayoutEngine::StartContentDeficitFill(PlayoutInstance* state, const std::string& segment_id,
                                            int64_t eof_ct_us, int64_t boundary_ct_us) {
  if (state->content_deficit_active_.load(std::memory_order_acquire)) return;
  state->content_deficit_active_.store(true, std::memory_order_release);
  state->deficit_start_ct_us_ = eof_ct_us;
  state->deficit_boundary_ct_us_ = boundary_ct_us;
  state->deficit_segment_id_ = segment_id;
  const int64_t gap_ms = boundary_ct_us > 0 ? (boundary_ct_us - eof_ct_us) / 1000 : 0;
  std::cout << "[PlayoutEngine] CONTENT_DEFICIT_FILL_START segment=" << segment_id
            << " ct=" << eof_ct_us
            << " boundary_ct=" << boundary_ct_us
            << " gap_ms=" << gap_ms << std::endl;
}

void PlayoutEngine::EndContentDeficitFill(PlayoutInstance* state) {
  if (!state->content_deficit_active_.load(std::memory_order_acquire)) return;
  const int64_t now_ct = state->timeline_controller ? state->timeline_controller->GetCTCursor() : 0;
  const int64_t duration_ms = (now_ct - state->deficit_start_ct_us_) / 1000;
  std::cout << "[PlayoutEngine] CONTENT_DEFICIT_FILL_END segment=" << state->deficit_segment_id_
            << " duration_ms=" << duration_ms << std::endl;
  state->content_deficit_active_.store(false, std::memory_order_release);
  state->deficit_start_ct_us_ = 0;
  state->deficit_boundary_ct_us_ = 0;
  state->deficit_segment_id_.clear();
  state->target_boundary_time_ms_ = 0;
}

}  // namespace retrovue::runtime
