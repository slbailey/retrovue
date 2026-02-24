// Repository: Retrovue-playout
// Component: MpegTSOutputSink Implementation
// Purpose: Concrete output sink that encodes frames to MPEG-TS over UDS/TCP.
// Copyright (c) 2025 RetroVue

#include "retrovue/output/MpegTSOutputSink.h"

#include <chrono>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <iostream>
#include <thread>
#include <unistd.h>
#include <unordered_map>
#include <unordered_set>

#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/playout_sinks/mpegts/EncoderPipeline.hpp"
#include "retrovue/telemetry/MetricsExporter.h"
#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/RationalFps.hpp"

static bool NoPcrPacing() {
  static bool checked = false;
  static bool value = false;
  if (!checked) {
    const char* env = std::getenv("RETROVUE_NO_PCR_PACING");
    value = (env && env[0] == '1');
    if (value) {
      std::cout << "[DBG-PACING] RETROVUE_NO_PCR_PACING=1: pacing DISABLED" << std::endl;
    }
    checked = true;
  }
  return value;
}


// INV-P9-BOOT-LIVENESS: Sink attach time per instance (keyed by this) for first-TS latency log
static std::unordered_map<void*, std::chrono::steady_clock::time_point> g_sink_attach_time;
static std::mutex g_sink_attach_mutex;

// INV-P9-AUDIO-LIVENESS: Header write time (us since epoch) per sink for first-audio log
static std::unordered_map<void*, int64_t> g_header_write_time_us;
static std::mutex g_header_write_mutex;

// INV-P9-TS-EMISSION-LIVENESS: PCR-PACE init time per sink for 500ms deadline (P1-MS-004/005/006)
static std::unordered_map<void*, std::chrono::steady_clock::time_point> g_pcr_pace_init_time;
static std::mutex g_pcr_pace_init_mutex;
static std::unordered_set<void*> g_ts_emission_violation_logged;

namespace retrovue::output {

MpegTSOutputSink::MpegTSOutputSink(
    int fd,
    const playout_sinks::mpegts::MpegTSPlayoutSinkConfig& config,
    const std::string& name)
    : fd_(fd),
      config_(config),
      name_(name),
      status_(SinkStatus::kIdle),
      stop_requested_(false) {
}

// Test seam: constructor with injected encoder
MpegTSOutputSink::MpegTSOutputSink(
    int fd,
    const playout_sinks::mpegts::MpegTSPlayoutSinkConfig& config,
    std::unique_ptr<playout_sinks::mpegts::EncoderPipeline> encoder,
    const std::string& name)
    : fd_(fd),
      config_(config),
      name_(name),
      status_(SinkStatus::kIdle),
      stop_requested_(false),
      encoder_(std::move(encoder)) {
}

MpegTSOutputSink::~MpegTSOutputSink() {
  Stop();
}

bool MpegTSOutputSink::Start() {
  SinkStatus expected = SinkStatus::kIdle;
  if (!status_.compare_exchange_strong(expected, SinkStatus::kStarting)) {
    return false;
  }

  if (fd_ < 0) {
    SetStatus(SinkStatus::kError, "Invalid file descriptor");
    return false;
  }

  // =========================================================================
  // INV-SOCKET-NONBLOCK: Enforce non-blocking mode on the socket fd.
  // =========================================================================
  // SocketSink uses poll()+send() in its writer thread. If the fd is blocking,
  // send() can block indefinitely, stalling the writer thread, filling the
  // internal buffer, and triggering a false "slow consumer" detach.
  //
  // This invariant MUST be enforced at the ownership boundary, not assumed.
  // =========================================================================
  {
    int flags = fcntl(fd_, F_GETFL, 0);
    if (flags < 0) {
      std::cerr << "[MpegTSOutputSink] INV-SOCKET-NONBLOCK VIOLATION: fcntl(F_GETFL) failed: "
                << strerror(errno) << std::endl;
      SetStatus(SinkStatus::kError, "Failed to get socket flags");
      return false;
    }
    if (!(flags & O_NONBLOCK)) {
      if (fcntl(fd_, F_SETFL, flags | O_NONBLOCK) < 0) {
        std::cerr << "[MpegTSOutputSink] INV-SOCKET-NONBLOCK VIOLATION: fcntl(F_SETFL) failed: "
                  << strerror(errno) << std::endl;
        SetStatus(SinkStatus::kError, "Failed to set socket O_NONBLOCK");
        return false;
      }
      std::cout << "[MpegTSOutputSink] INV-SOCKET-NONBLOCK: Set O_NONBLOCK on fd=" << fd_ << std::endl;
    }
  }

  // Create SocketSink for non-blocking byte transport
  socket_sink_ = std::make_unique<SocketSink>(fd_, name_ + "-socket");

  // =========================================================================
  // INV-LIVENESS-SEPARATION: Configure throttling instead of immediate detach
  // =========================================================================
  // Downstream backpressure (consumer not draining) should cause THROTTLING,
  // not immediate connection termination. This allows temporary stalls to
  // recover without losing the viewer.
  // =========================================================================
  socket_sink_->SetDetachOnOverflow(false);  // Throttle instead of detach

  // Set throttle callback to track downstream backpressure state
  socket_sink_->SetThrottleCallback([this](bool throttle_active) {
    if (throttle_active) {
      std::cout << "[MpegTSOutputSink] INV-LIVENESS-SEPARATION: "
                << "Downstream backpressure detected (throttling ON) - "
                << "this is consumer slowness, NOT upstream starvation" << std::endl;
      SetStatus(SinkStatus::kBackpressure, "Consumer backpressure");
    } else {
      std::cout << "[MpegTSOutputSink] INV-LIVENESS-SEPARATION: "
                << "Downstream backpressure cleared (throttling OFF)" << std::endl;
      SetStatus(SinkStatus::kRunning, "Running");
    }
  });

  // LAW-OUTPUT-LIVENESS: Set detach callback for catastrophic failures only
  // This only fires if buffer COMPLETELY fills and detach_on_overflow is re-enabled
  socket_sink_->SetDetachCallback([this](const std::string& reason) {
    std::cout << "[MpegTSOutputSink] Sink detached (slow consumer): " << reason << std::endl;
    // Signal mux loop to exit cleanly (prevents zombie thread + liveness spam)
    stop_requested_.store(true, std::memory_order_release);
    // Use kDetached (not kError) - consumer failure is distinct from internal error
    SetStatus(SinkStatus::kDetached, "Transport detached: " + reason);
  });

  // Create and open encoder pipeline
  // Test seam: if encoder was injected via constructor, use it; otherwise create new one
  if (!encoder_) {
    encoder_ = std::make_unique<playout_sinks::mpegts::EncoderPipeline>(config_);
  }
  if (!encoder_->open(config_, this, &MpegTSOutputSink::WriteToFdCallback)) {
    SetStatus(SinkStatus::kError, "Failed to open encoder pipeline");
    encoder_.reset();
    socket_sink_.reset();
    return false;
  }

  // =========================================================================
  // INV-BOOT-FAST-EMIT: Disable encoder timing during boot for immediate output
  // =========================================================================
  // Encoder timing (GateOutputTiming) is DISABLED at startup to ensure
  // immediate TS emission. It will be disabled permanently once steady-state
  // is entered (MuxLoop owns pacing authority).
  // =========================================================================
  encoder_->SetOutputTimingEnabled(false);
  std::cout << "[MpegTSOutputSink] INV-BOOT-FAST-EMIT: Encoder output timing DISABLED for fast boot" << std::endl;

  // =========================================================================
  // INV-P9-IMMEDIATE-OUTPUT: Keep audio liveness ENABLED at startup
  // =========================================================================
  // Professional broadcast systems output decodable content immediately.
  // At startup, we emit pad frames + silence until real content is ready.
  // Silence injection is only disabled AFTER real audio is confirmed flowing.
  // This prevents MuxLoop stalls when audio queue is empty at startup.
  // =========================================================================
  encoder_->SetAudioLivenessEnabled(true);
  std::cout << "[MpegTSOutputSink] INV-P9-IMMEDIATE-OUTPUT: Silence injection ENABLED (until real audio flows)" << std::endl;

  // INV-TS-CONTINUITY: Initialize null packets for transport continuity
  InitNullPackets();
  std::cout << "[MpegTSOutputSink] INV-TS-CONTINUITY: Null packet emission ENABLED" << std::endl;

  // Start mux thread
  stop_requested_.store(false, std::memory_order_release);
  mux_thread_ = std::thread(&MpegTSOutputSink::MuxLoop, this);

  {
    std::lock_guard<std::mutex> lock(g_sink_attach_mutex);
    g_sink_attach_time[this] = std::chrono::steady_clock::now();
  }
  SetStatus(SinkStatus::kRunning, "Started");
  return true;
}

void MpegTSOutputSink::Stop() {
  SinkStatus current = status_.load(std::memory_order_acquire);
  if (current == SinkStatus::kIdle || current == SinkStatus::kStopped) {
    return;
  }

  SetStatus(SinkStatus::kStopping, "Stopping");

  // Signal thread to stop
  stop_requested_.store(true, std::memory_order_release);

  // Wait for thread to finish
  if (mux_thread_.joinable()) {
    mux_thread_.join();
  }

  // Close encoder
  if (encoder_) {
    encoder_->close();
    encoder_.reset();
  }

  // Close SocketSink
  if (socket_sink_) {
    socket_sink_->Close();
    socket_sink_.reset();
  }

  // Clear queues
  {
    std::lock_guard<std::mutex> lock(video_queue_mutex_);
    while (!video_queue_.empty()) video_queue_.pop();
  }
  {
    std::lock_guard<std::mutex> lock(audio_queue_mutex_);
    while (!audio_queue_.empty()) audio_queue_.pop();
  }

  // Clear INV-P9-TS-EMISSION-LIVENESS state so next Start() gets fresh deadline
  {
    std::lock_guard<std::mutex> lock(g_pcr_pace_init_mutex);
    g_pcr_pace_init_time.erase(this);
    g_ts_emission_violation_logged.erase(this);
  }

  // INV-P9-STEADY-001: Reset steady-state flags so next Start() can detect entry again
  steady_state_entered_.store(false, std::memory_order_release);
  pcr_paced_active_.store(false, std::memory_order_release);

  // INV-P9-STEADY-008: Reset silence injection disabled flag for next session
  silence_injection_disabled_.store(false, std::memory_order_release);

  // INV-BOOT-FAST-EMIT: Reset boot window flag for next session
  boot_fast_emit_active_.store(true, std::memory_order_release);

  // P9-OPT-002: Report steady-state inactive to metrics
  if (metrics_exporter_) {
    metrics_exporter_->SetSteadyStateActive(channel_id_, false);
  }

  // Close forensic dump if enabled
  DisableForensicDump();

  SetStatus(SinkStatus::kStopped, "Stopped");
}

// =============================================================================
// Forensic TS Tap
// =============================================================================

void MpegTSOutputSink::EnableForensicDump(const std::string& path) {
  // LAW-OUTPUT-LIVENESS: Use O_NONBLOCK to prevent filesystem stalls from blocking callback
  int fd = ::open(path.c_str(), O_CREAT | O_WRONLY | O_TRUNC | O_NONBLOCK, 0644);
  if (fd >= 0) {
    forensic_fd_ = fd;
    forensic_enabled_.store(true, std::memory_order_release);
    std::cout << "[MpegTSOutputSink] Forensic dump enabled (O_NONBLOCK): " << path << std::endl;
  } else {
    std::cerr << "[MpegTSOutputSink] Failed to open forensic dump: " << path
              << " (errno=" << errno << ")" << std::endl;
  }
}

void MpegTSOutputSink::DisableForensicDump() {
  forensic_enabled_.store(false, std::memory_order_release);
  if (forensic_fd_ >= 0) {
    ::close(forensic_fd_);
    forensic_fd_ = -1;
    std::cout << "[MpegTSOutputSink] Forensic dump disabled" << std::endl;
  }
}

bool MpegTSOutputSink::IsRunning() const {
  SinkStatus s = status_.load(std::memory_order_acquire);
  return s == SinkStatus::kRunning || s == SinkStatus::kBackpressure;
}

SinkStatus MpegTSOutputSink::GetStatus() const {
  return status_.load(std::memory_order_acquire);
}

void MpegTSOutputSink::ConsumeVideo(const buffer::Frame& frame) {
  if (!IsRunning()) return;
  EnqueueVideoFrame(frame);
}

void MpegTSOutputSink::ConsumeAudio(const buffer::AudioFrame& audio_frame) {
  if (!IsRunning()) return;
  EnqueueAudioFrame(audio_frame);
}

void MpegTSOutputSink::SetStatusCallback(SinkStatusCallback callback) {
  std::lock_guard<std::mutex> lock(status_mutex_);
  status_callback_ = std::move(callback);
}

std::string MpegTSOutputSink::GetName() const {
  return name_;
}

void MpegTSOutputSink::SetOnSuccessorVideoEmitted(OnSuccessorVideoEmittedCallback callback) {
  on_successor_video_emitted_ = std::move(callback);
}

void MpegTSOutputSink::SetMetricsExporter(std::shared_ptr<telemetry::MetricsExporter> metrics, int32_t channel_id) {
  metrics_exporter_ = std::move(metrics);
  channel_id_ = channel_id;
}

void MpegTSOutputSink::MuxLoop() {
  std::cout << "[MpegTSOutputSink] MuxLoop starting, fd=" << fd_ << std::endl;

  // =========================================================================
  // INV-BOOT-FAST-EMIT: Boot window for immediate TS emission
  // =========================================================================
  // For fast channel join, bypass all pacing during the boot window.
  // This ensures PAT/PMT and initial frames reach the consumer immediately.
  // =========================================================================
  auto boot_window_start = std::chrono::steady_clock::now();
  boot_fast_emit_active_.store(true, std::memory_order_release);
  std::cout << "[MpegTSOutputSink] INV-BOOT-FAST-EMIT: Boot window active for "
            << kBootFastEmitWindowMs << "ms (immediate TS emission)" << std::endl;

  // =========================================================================
  // INV-P10-PCR-PACED-MUX: Time-driven emission, not availability-driven
  // =========================================================================
  // The mux loop emits frames at their scheduled CT, not as fast as possible.
  // This prevents buffer oscillation and ensures smooth playback.
  //
  // Algorithm:
  // 1. Peek at next video frame to get its CT
  // 2. Wait until wall clock matches that CT
  // 3. Dequeue and encode exactly one video frame
  // 4. Dequeue and encode all audio with CT <= video CT
  // 5. Repeat
  //
  // Forbidden patterns:
  // - No draining loops ("while queue not empty")
  // - No burst writes
  // - No adaptive speed-up/slow-down
  // - No dropping frames
  // =========================================================================

  // Pacing state
  bool timing_initialized = false;
  std::chrono::steady_clock::time_point wall_epoch;
  int64_t ct_epoch_us = 0;

  // =========================================================================
  // INV-TICK-GUARANTEED-OUTPUT: Bounded pre-timing wait
  // =========================================================================
  // Wait at most 500ms for first real frame before initializing timing
  // synthetically and emitting black frames. Broadcast output ALWAYS flows.
  // =========================================================================
  constexpr int64_t kPreTimingWaitWindowMs = 500;
  std::chrono::steady_clock::time_point pre_timing_wait_start;
  bool pre_timing_wait_started = false;
  bool pre_timing_wait_expired = false;

  // Diagnostic counters (per-instance, not static)
  int video_emit_count = 0;
  int audio_emit_count = 0;
  int pacing_wait_count = 0;

  // =========================================================================
  // INV-P9-STEADY-001 / P9-CORE-002: PCR-paced mux instrumentation
  // =========================================================================
  // Track dequeue intervals and CT vs wall clock deltas to prove pacing.
  // Log periodically (every N frames) to avoid log spam.
  // =========================================================================
  std::chrono::steady_clock::time_point last_dequeue_time;
  bool last_dequeue_time_valid = false;
  int64_t total_pacing_wait_us = 0;
  int64_t min_dequeue_interval_us = INT64_MAX;
  int64_t max_dequeue_interval_us = 0;
  int64_t sum_dequeue_interval_us = 0;
  int64_t sum_ct_wall_delta_us = 0;
  constexpr int kPacingLogInterval = 30;  // Log every 30 frames (~1 second at 30fps)
  int late_frame_count = 0;  // Frames that arrived after their CT (no wait needed)

  // =========================================================================
  // INV-TICK-GUARANTEED-OUTPUT: Every output tick emits exactly one frame
  // =========================================================================
  // This invariant is STRUCTURALLY ENFORCED. No conditional can skip emission.
  // Fallback chain: real → freeze (last frame) → black (pre-allocated)
  //
  // CONTINUITY > CORRECTNESS: Dead air is never acceptable.
  // A wrong frame is a production issue. No frame is a system failure.
  //
  // This block MUST appear ABOVE all: pacing logic, CT comparisons,
  // buffer health checks, and diagnostic checks.
  // =========================================================================

  // One-tick duration from session rational (INV-FPS-RESAMPLE). Prefer fps_num/fps_den when set.
  retrovue::blockplan::RationalFps session_fps(0, 1);
  if (config_.fps_num > 0 && config_.fps_den > 0) {
    session_fps = retrovue::blockplan::RationalFps(config_.fps_num, config_.fps_den);
  }
  if (!session_fps.IsValid()) {
    session_fps = retrovue::blockplan::DeriveRationalFPS(config_.target_fps);
  }
  if (!session_fps.IsValid()) {
    session_fps = retrovue::blockplan::FPS_30;
  }
  const int64_t frame_duration_us = session_fps.FrameDurationUs();

  // Pre-allocate black fallback frame ONCE (no allocation in hot path)
  buffer::Frame prealloc_black_frame;
  {
    prealloc_black_frame.width = config_.target_width;
    prealloc_black_frame.height = config_.target_height;
    prealloc_black_frame.metadata.pts = 0;  // Will be set per-emit
    prealloc_black_frame.metadata.dts = 0;
    prealloc_black_frame.metadata.duration = session_fps.FrameDurationSec();
    prealloc_black_frame.metadata.asset_uri = "fallback://black";
    prealloc_black_frame.metadata.has_ct = true;

    const int y_size = config_.target_width * config_.target_height;
    const int uv_size = (config_.target_width / 2) * (config_.target_height / 2);
    prealloc_black_frame.data.resize(static_cast<size_t>(y_size + 2 * uv_size));
    std::memset(prealloc_black_frame.data.data(), 16, static_cast<size_t>(y_size));
    std::memset(prealloc_black_frame.data.data() + y_size, 128, static_cast<size_t>(2 * uv_size));
  }

  // Last emitted frame for freeze mode
  buffer::Frame last_emitted_frame;
  bool have_last_frame = false;
  int64_t fallback_frame_count = 0;
  int64_t last_fallback_pts_us = 0;
  bool in_fallback_mode = false;

  // =========================================================================
  // INV-FALLBACK-001: Upstream starvation detection
  // =========================================================================
  // Initialize last real frame time to now. This prevents immediate fallback
  // at startup - we give upstream time to deliver the first frame.
  // =========================================================================
  last_real_frame_dequeue_time_ = std::chrono::steady_clock::now();

  std::cout << "[MpegTSOutputSink] INV-TICK-GUARANTEED-OUTPUT: Unconditional emission enabled" << std::endl;
  std::cout << "[MpegTSOutputSink] INV-P10-PCR-PACED-MUX: Time-driven emission enabled" << std::endl;

  while (!stop_requested_.load(std::memory_order_acquire) && fd_ >= 0) {
    // =========================================================================
    // INV-BOOT-FAST-EMIT: Check and update boot window state
    // =========================================================================
    // During boot window: emit frames immediately, skip timing checks
    // After boot window: normal pacing operation
    // =========================================================================
    bool in_boot_window = boot_fast_emit_active_.load(std::memory_order_acquire);
    if (in_boot_window) {
      auto boot_elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
          std::chrono::steady_clock::now() - boot_window_start).count();
      if (boot_elapsed_ms >= kBootFastEmitWindowMs) {
        boot_fast_emit_active_.store(false, std::memory_order_release);
        in_boot_window = false;
        std::cout << "[MpegTSOutputSink] INV-BOOT-FAST-EMIT: Boot window expired after "
                  << boot_elapsed_ms << "ms, switching to normal pacing" << std::endl;
      }
    }

    // -----------------------------------------------------------------------
    // Step 1: Peek at next video frame to determine target emit time
    // -----------------------------------------------------------------------
    int64_t next_video_ct_us = -1;
    size_t vq_size = 0;
    size_t aq_size = 0;
    {
      std::lock_guard<std::mutex> lock(video_queue_mutex_);
      vq_size = video_queue_.size();
      if (!video_queue_.empty()) {
        next_video_ct_us = video_queue_.front().metadata.pts;
      }
    }
    {
      std::lock_guard<std::mutex> lock(audio_queue_mutex_);
      aq_size = audio_queue_.size();
    }

    // =========================================================================
    // INV-TS-CONTINUITY: Emit null packets if encoder is not producing output
    // =========================================================================
    // This check runs every loop iteration. If the encoder hasn't written TS
    // bytes recently (e.g., due to internal buffering), emit null packets to
    // maintain transport continuity. This prevents EOF detection by consumers.
    // =========================================================================
    EmitNullPacketsIfNeeded();

    // =========================================================================
    // INV-LIVENESS-SEPARATION: SPLIT upstream vs downstream liveness detection
    // =========================================================================
    // TWO INDEPENDENT failure modes - MUST NOT be conflated:
    //
    // A) DOWNSTREAM STALL: SocketSink can't deliver bytes to kernel
    //    - Caused by: Core not draining the UNIX socket
    //    - Response: Log diagnostic, throttle if needed, DO NOT enter fallback
    //
    // B) UPSTREAM STARVATION: No frames arriving from producer
    //    - Caused by: Decoder stall, producer issue, segment gap
    //    - Response: Enter fallback mode (emit pad/freeze frames)
    //
    // Previous code CONFLATED these by using GetLastAcceptedTime() for both!
    // =========================================================================
    {
      // Skip all checks if sink is detached (already a terminal state)
      if (socket_sink_ && socket_sink_->IsDetached()) {
        // Sink already detached - no point checking liveness
      } else {
        auto now_check = std::chrono::steady_clock::now();
        bool has_emitted_ts = dbg_bytes_enqueued_.load(std::memory_order_relaxed) > 0;

        // =====================================================================
        // DOWNSTREAM STALL DETECTOR (consumer not draining)
        // =====================================================================
        // This checks if the SOCKET CONSUMER (Core) is draining bytes.
        // A stall here means backpressure, NOT upstream starvation.
        // This MUST NOT trigger fallback mode.
        // =====================================================================
        if (has_emitted_ts && socket_sink_) {
          auto last_accept = socket_sink_->GetLastAcceptedTime();
          int64_t downstream_idle_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
              now_check - last_accept).count();

          if (downstream_idle_ms >= kDownstreamStallThresholdMs) {
            // Only log once per second to avoid spam
            static thread_local int64_t last_downstream_log_ms = 0;
            if (downstream_idle_ms > last_downstream_log_ms + 1000) {
              uint64_t bytes_enq = socket_sink_->GetBytesEnqueued();
              uint64_t bytes_del = socket_sink_->GetBytesDelivered();
              size_t buf_size = socket_sink_->GetCurrentBufferSize();
              size_t buf_cap = socket_sink_->GetBufferCapacity();

              std::cout << "[MpegTSOutputSink] DOWNSTREAM STALL: "
                        << "no socket progress for " << downstream_idle_ms << "ms "
                        << "(consumer not draining)"
                        << " bytes_enqueued=" << bytes_enq
                        << " bytes_delivered=" << bytes_del
                        << " buffer_size=" << buf_size
                        << " capacity=" << buf_cap
                        << " vq=" << vq_size
                        << " aq=" << aq_size
                        << std::endl;
              last_downstream_log_ms = downstream_idle_ms;
            }
          }
        }

        // =====================================================================
        // UPSTREAM STARVATION DETECTOR (no frames from producer)
        // =====================================================================
        // This checks if real frames are being DEQUEUED from the queue.
        // If frames aren't arriving, this MAY trigger fallback mode.
        // NOTE: Fallback decision is made separately below (INV-FALLBACK-001)
        // =====================================================================
        if (timing_initialized) {
          int64_t upstream_idle_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
              now_check - last_real_frame_dequeue_time_).count();

          if (upstream_idle_ms >= kUpstreamStarvationThresholdMs && vq_size == 0) {
            // Only log periodically (actual fallback entry is logged elsewhere)
            static thread_local int64_t last_upstream_log_ms = 0;
            if (upstream_idle_ms > last_upstream_log_ms + 1000) {
              std::cout << "[MpegTSOutputSink] UPSTREAM STARVATION: "
                        << "no real frames dequeued for " << upstream_idle_ms << "ms "
                        << "(producer may be starved or stalled)"
                        << " vq=" << vq_size
                        << " aq=" << aq_size
                        << std::endl;
              last_upstream_log_ms = upstream_idle_ms;
            }
          }
        }
      }
    }

    // INV-P9-TS-EMISSION-LIVENESS (P1-MS-006): Log violation once if 500ms elapsed without first TS
    if (timing_initialized) {
      auto now_viol = std::chrono::steady_clock::now();
      int64_t elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
          now_viol - wall_epoch).count();
      if (elapsed_ms >= 500 && dbg_bytes_enqueued_.load(std::memory_order_relaxed) == 0) {
        bool already_logged = false;
        {
          std::lock_guard<std::mutex> lock(g_pcr_pace_init_mutex);
          already_logged = (g_ts_emission_violation_logged.count(this) > 0);
          if (!already_logged) g_ts_emission_violation_logged.insert(this);
        }
        if (!already_logged) {
          const char* reason = "unknown";
          if (aq_size == 0 && vq_size > 0) reason = "audio";
          else if (vq_size == 0 && aq_size > 0) reason = "video";
          else if (vq_size == 0 && aq_size == 0) reason = "encoder";
          std::cout << "[MpegTSOutputSink] INV-P9-TS-EMISSION-LIVENESS VIOLATION: No TS after "
                    << static_cast<int>(elapsed_ms) << "ms, blocking_reason=" << reason
                    << ", vq=" << vq_size << ", aq=" << aq_size << std::endl;
        }
      }
    }

    // =========================================================================
    // INV-TICK-GUARANTEED-OUTPUT: Fallback chain with grace window
    // =========================================================================
    // INV-FALLBACK-001: Fallback mode ONLY engages after confirmed upstream
    // starvation. A momentary empty queue does NOT trigger fallback.
    //
    // Grace window: If timing is initialized and queue is empty, wait for
    // kFallbackGraceWindowUs before entering fallback. During grace window,
    // emit null packets to maintain transport continuity.
    //
    // This prevents false fallback triggers from:
    // - Transient queue empty (producer briefly slower than consumer)
    // - Pacing delays causing queue check to see empty
    // - Encoder blocking while frames are in transit
    // =========================================================================
    if (next_video_ct_us < 0) {
      // Queue is empty - check if we should enter fallback or wait

      // =====================================================================
      // INV-FALLBACK-001: Grace window check (only after timing initialized)
      // =====================================================================
      if (timing_initialized && !in_fallback_mode) {
        auto now_grace = std::chrono::steady_clock::now();
        int64_t since_last_real_us = std::chrono::duration_cast<std::chrono::microseconds>(
            now_grace - last_real_frame_dequeue_time_).count();

        if (since_last_real_us < kFallbackGraceWindowUs) {
          // Within grace window - emit null packets and retry, don't enter fallback
          // INV-TS-CONTINUITY-001: Null packets maintain transport independently
          EmitNullPacketsIfNeeded();
          std::this_thread::sleep_for(std::chrono::milliseconds(5));
          continue;  // Retry - frame may arrive
        }
        // Grace window expired - upstream is confirmed starved, proceed to fallback
        std::cout << "[MpegTSOutputSink] INV-FALLBACK-001: Grace window expired ("
                  << (since_last_real_us / 1000) << "ms since last real frame), "
                  << "entering fallback mode" << std::endl;
      }

      // No real frame available - use fallback chain
      if (!timing_initialized) {
        // =====================================================================
        // INV-TICK-GUARANTEED-OUTPUT: Bounded pre-timing wait
        // =====================================================================
        // Wait briefly for first real frame, then initialize timing synthetically
        // and emit black frames. Broadcast output ALWAYS flows after arming.
        // =====================================================================

        // Start the wait timer on first iteration
        if (!pre_timing_wait_started) {
          pre_timing_wait_started = true;
          pre_timing_wait_start = std::chrono::steady_clock::now();
          std::cout << "[MpegTSOutputSink] INV-TICK-GUARANTEED-OUTPUT: "
                    << "Starting bounded pre-timing wait (window=" << kPreTimingWaitWindowMs << "ms)"
                    << std::endl;
        }

        // Check if wait window has expired
        auto now_wait = std::chrono::steady_clock::now();
        int64_t wait_elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            now_wait - pre_timing_wait_start).count();

        if (wait_elapsed_ms < kPreTimingWaitWindowMs) {
          // Still within wait window - emit null packets to maintain transport
          // INV-TS-CONTINUITY: Null packets during pre-timing wait prevent EOF
          EmitNullPackets();
          std::this_thread::sleep_for(std::chrono::milliseconds(20));
          continue;
        }

        // Wait window expired - initialize timing synthetically
        if (!pre_timing_wait_expired) {
          pre_timing_wait_expired = true;
          std::cout << "[MpegTSOutputSink] INV-TICK-GUARANTEED-OUTPUT: "
                    << "Pre-timing wait expired after " << wait_elapsed_ms << "ms. "
                    << "Initializing synthetic timing and emitting black frames. "
                    << "Output must flow (professional playout behavior)." << std::endl;

          // Synthetic timing initialization
          wall_epoch = now_wait;
          ct_epoch_us = 0;  // Synthetic epoch starts at 0
          timing_initialized = true;

          {
            std::lock_guard<std::mutex> lock(g_pcr_pace_init_mutex);
            g_pcr_pace_init_time[this] = wall_epoch;
          }

          std::cout << "[MpegTSOutputSink] PCR-PACE: Timing initialized (synthetic), ct_epoch_us=0"
                    << std::endl;
        }

        // Fall through to emit black frame (timing now initialized)
      }

      // Log transition to fallback mode (once)
      if (!in_fallback_mode) {
        in_fallback_mode = true;
        std::cout << "[MpegTSOutputSink] INV-TICK-GUARANTEED-OUTPUT: "
                  << "Entering fallback mode (no real frames), "
                  << "source=" << (have_last_frame ? "freeze" : "black") << std::endl;
      }

      // Calculate PTS for fallback frame
      auto now_fb = std::chrono::steady_clock::now();
      int64_t fallback_pts_us;
      if (fallback_frame_count == 0) {
        int64_t wall_elapsed_us = std::chrono::duration_cast<std::chrono::microseconds>(
            now_fb - wall_epoch).count();
        fallback_pts_us = ct_epoch_us + wall_elapsed_us;
      } else {
        fallback_pts_us = last_fallback_pts_us + frame_duration_us;
      }

      // Select fallback frame: freeze (last) → black (pre-allocated)
      buffer::Frame fallback_frame;
      const char* fallback_source;
      if (have_last_frame) {
        // FREEZE: Re-emit last frame
        fallback_frame = last_emitted_frame;
        fallback_frame.metadata.pts = fallback_pts_us;
        fallback_frame.metadata.dts = fallback_pts_us;
        fallback_frame.metadata.asset_uri = "freeze://last";
        fallback_source = "freeze";
      } else {
        // BLACK: Use pre-allocated fallback
        fallback_frame = prealloc_black_frame;
        fallback_frame.metadata.pts = fallback_pts_us;
        fallback_frame.metadata.dts = fallback_pts_us;
        fallback_source = "black";
      }

      // UNCONDITIONAL EMISSION - This line ALWAYS executes in fallback mode
      const int64_t pts90k = (fallback_pts_us * 90000) / 1'000'000;
      std::cout << "[MpegTSOutputSink] Encoder received frame: real=no pts=" << fallback_pts_us
                << " (" << fallback_source << ")" << std::endl;
      encoder_->encodeFrame(fallback_frame, pts90k);

      fallback_frame_count++;
      last_fallback_pts_us = fallback_pts_us;
      video_emit_count++;

      // Log periodically
      if (fallback_frame_count == 1 || fallback_frame_count % 30 == 0) {
        std::cout << "[MpegTSOutputSink] INV-TICK-GUARANTEED-OUTPUT: "
                  << "Fallback frame #" << fallback_frame_count
                  << " (" << fallback_source << ") at PTS=" << fallback_pts_us << "us" << std::endl;
      }

      // Pacing sleep
      std::this_thread::sleep_for(std::chrono::microseconds(frame_duration_us));
      continue;
    }

    // Real frame available - reset fallback state
    if (in_fallback_mode) {
      std::cout << "[MpegTSOutputSink] INV-TICK-GUARANTEED-OUTPUT: "
                << "Exiting fallback mode, real frames available "
                << "(emitted " << fallback_frame_count << " fallback frames)" << std::endl;
      in_fallback_mode = false;
      fallback_frame_count = 0;
      // INV-FALLBACK-005: Reset timestamp to prevent immediate re-entry
      last_real_frame_dequeue_time_ = std::chrono::steady_clock::now();
    }

    // -----------------------------------------------------------------------
    // Step 2: Initialize timing on first frame
    // -----------------------------------------------------------------------
    if (!timing_initialized) {
      wall_epoch = std::chrono::steady_clock::now();
      ct_epoch_us = next_video_ct_us;
      timing_initialized = true;
      {
        std::lock_guard<std::mutex> lock(g_pcr_pace_init_mutex);
        g_pcr_pace_init_time[this] = wall_epoch;
      }

      // =====================================================================
      // CT-DOMAIN-SANITY: Log clock values at timing initialization
      // =====================================================================
      auto now_steady = std::chrono::steady_clock::now();
      auto now_system = std::chrono::system_clock::now();
      int64_t steady_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
          now_steady.time_since_epoch()).count();
      int64_t system_us = std::chrono::duration_cast<std::chrono::microseconds>(
          now_system.time_since_epoch()).count();
      int64_t wall_epoch_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
          wall_epoch.time_since_epoch()).count();
      std::cout << "[CT-DOMAIN-SANITY] Timing init: "
                << "steady_ns=" << steady_ns
                << " system_us=" << system_us
                << " wall_epoch_ns=" << wall_epoch_ns
                << " ct_epoch_us=" << ct_epoch_us
                << " frame_ct_us=" << next_video_ct_us
                << " (wall_epoch is STEADY, ct_epoch is FRAME_CT)" << std::endl;

      // HARD ASSERT: CT should be small (relative to session start), not a Unix timestamp
      // A Unix timestamp in 2026 would be ~1.77 trillion microseconds
      // CT should be < 24 hours = 86400 * 1e6 = 86.4 billion us
      constexpr int64_t kMaxReasonableCT = 86'400'000'000LL;  // 24 hours in us
      if (std::abs(ct_epoch_us) > kMaxReasonableCT) {
        std::cerr << "[CT-DOMAIN-SANITY] FATAL: ct_epoch_us=" << ct_epoch_us
                  << " exceeds 24h - likely clock domain mismatch!" << std::endl;
        // Don't crash in release, but log loudly
      }

      std::cout << "[MpegTSOutputSink] PCR-PACE: Timing initialized, ct_epoch_us="
                << ct_epoch_us << std::endl;
      std::cout << "[MpegTSOutputSink] INV-P9-TS-EMISSION-LIVENESS: PCR-PACE initialized, deadline=500ms" << std::endl;

      // =====================================================================
      // INV-P9-STEADY-001: Steady-state entry detection
      // =====================================================================
      // Entry conditions:
      //   1. Sink attached (we're in MuxLoop, so Start() succeeded)
      //   2. Buffer depth >= kSteadyStateMinDepth (we have at least one video frame)
      //   3. Timing epoch established (timing_initialized = true now)
      //
      // This is DETECTION ONLY (P9-CORE-001). Behavior changes come in later tasks.
      // =====================================================================
      if (!steady_state_entered_.load(std::memory_order_acquire)) {
        steady_state_entered_.store(true, std::memory_order_release);
        pcr_paced_active_.store(true, std::memory_order_release);

        // =====================================================================
        // INV-P9-STEADY-007: Enable Producer CT Authoritative mode
        // =====================================================================
        // In steady-state, muxer must use producer-provided timestamps directly.
        // No local CT counters. No PTS rebasing. No offset calculation.
        // =====================================================================
        if (encoder_) {
          encoder_->SetProducerCTAuthoritative(true);
          // ===================================================================
          // INV-P9-STEADY-PACING: MuxLoop is now the sole timing authority
          // ===================================================================
          // CRITICAL: Disable encoder's GateOutputTiming to prevent conflicting
          // timing gates. MuxLoop has wall_epoch set at first frame dequeue.
          // GateOutputTiming has output_timing_anchor_wall_ set at first encode.
          // These anchors differ, causing frames to pass MuxLoop (appear "late")
          // but block in GateOutputTiming (appear "early") - resulting in
          // multi-second TS emission gaps despite continuous frame input.
          // ===================================================================
          encoder_->SetOutputTimingEnabled(false);
        }

        // =====================================================================
        // INV-P9-IMMEDIATE-OUTPUT: Do NOT disable silence injection yet
        // =====================================================================
        // Silence injection remains ENABLED until real audio is confirmed.
        // This ensures decodable output (pad + silence) from the first frame.
        // The transition to producer-authoritative audio happens when the
        // first real audio packet is emitted (see audio emit path below).
        // =====================================================================
        // silence_injection_disabled_ stays false until real audio flows

        // Log with evidence fields for contract verification and testing
        std::cout << "[MpegTSOutputSink] INV-P9-STEADY-STATE: entered"
                  << " sink=" << name_
                  << " ct_epoch_us=" << ct_epoch_us
                  << " vq_depth=" << vq_size
                  << " aq_depth=" << aq_size
                  << " wall_epoch_us=" << std::chrono::duration_cast<std::chrono::microseconds>(
                         wall_epoch.time_since_epoch()).count()
                  << " silence_injection=ENABLED_UNTIL_REAL_AUDIO"
                  << std::endl;

        // P9-OPT-002: Report steady-state active to metrics
        if (metrics_exporter_) {
          metrics_exporter_->SetSteadyStateActive(channel_id_, true);
        }
      }
    }

    // -----------------------------------------------------------------------
    // Step 3: Wait until wall clock matches frame's CT (PCR pacing)
    // -----------------------------------------------------------------------
    // INV-P9-STEADY-001 / P9-CORE-002: Output owns pacing authority.
    // Wait is ONLY performed when pcr_paced_active_ is true.
    // -----------------------------------------------------------------------
    int64_t ct_delta_us = next_video_ct_us - ct_epoch_us;

    // INV-P10-CT-DISCONTINUITY: Detect and handle CT jumps (e.g., from queue drops)
    // If the frame's CT is significantly ahead of expected (> 1 second), reset timing.
    // This prevents the mux loop from waiting forever when CTs jump due to queue drops.
    constexpr int64_t kCtDiscontinuityThresholdUs = 1'000'000;  // 1 second
    auto now = std::chrono::steady_clock::now();
    int64_t wall_elapsed_us = std::chrono::duration_cast<std::chrono::microseconds>(now - wall_epoch).count();
    int64_t expected_ct_us = ct_epoch_us + wall_elapsed_us;
    int64_t ct_jump_us = next_video_ct_us - expected_ct_us;

    if (ct_jump_us > kCtDiscontinuityThresholdUs) {
      std::cout << "[MpegTSOutputSink] INV-P10-CT-DISCONTINUITY: CT jumped ahead by "
                << (ct_jump_us / 1000) << "ms, resetting timing anchor" << std::endl;
      wall_epoch = now;
      ct_epoch_us = next_video_ct_us;
      ct_delta_us = 0;  // Emit immediately after reset
    }

    auto target_wall = wall_epoch + std::chrono::microseconds(ct_delta_us);

    // =========================================================================
    // INV-P9-STEADY-001 / P9-CORE-002: PCR timing (OBSERVATIONAL ONLY)
    // =========================================================================
    // Timing is now OBSERVATIONAL, not a gate. We emit first, pace after.
    // This ensures INV-TICK-GUARANTEED-OUTPUT: nothing can prevent emission.
    //
    // Structure: Emit → Track early/late → Sleep remainder of period (post-emit)
    // Old structure (RETIRED): Wait until CT → Emit
    //
    // INV-BOOT-FAST-EMIT: Skip timing instrumentation during boot window.
    // During boot, all frames are emitted immediately without tracking.
    // =========================================================================
    int64_t timing_delta_us = std::chrono::duration_cast<std::chrono::microseconds>(now - target_wall).count();

    // Skip timing instrumentation during boot window - just emit as fast as possible
    if (!in_boot_window) {
      // INV-LATE-FRAME-THRESHOLD: Only count as late if significantly past target (>2ms)
      // Sub-millisecond "lateness" is scheduling jitter, not a real problem
      bool is_late_frame = (timing_delta_us > kLateFrameThresholdUs);

      // OBSERVATIONAL: Track late frames (does NOT gate emission)
      if (is_late_frame && pcr_paced_active_.load(std::memory_order_acquire)) {
        late_frame_count++;
        // Log periodically if falling behind
        if (late_frame_count == 1 || late_frame_count % 30 == 0) {
          std::cout << "[MpegTSOutputSink] INV-P9-STEADY-001: Frame late by "
                    << (timing_delta_us / 1000) << "ms (observational, emission continues)"
                    << " late_count=" << late_frame_count << std::endl;
        }
      }

      // OBSERVATIONAL: Track early frames for metrics (no wait here, pacing is post-emit)
      // A frame is "early" if it's more than threshold BEFORE its target time
      // Frames within the threshold window are considered "on-time"
      bool is_early_frame = (timing_delta_us < -kLateFrameThresholdUs);
      if (is_early_frame && pcr_paced_active_.load(std::memory_order_acquire)) {
        int64_t early_us = -timing_delta_us;
        total_pacing_wait_us += early_us;  // Track how much we'll need to pace
        pacing_wait_count++;

        // Log first early frame to confirm pacing is active
        if (pacing_wait_count == 1) {
          std::cout << "[MpegTSOutputSink] INV-P9-STEADY-001: PCR timing active, first_frame_early="
                    << early_us << "us (post-emission pacing enabled)" << std::endl;
        }

        // P9-OPT-002: Record timing delta for histogram (sample every 30 frames)
        if (metrics_exporter_ && (pacing_wait_count % 30) == 1) {
          double delta_ms = static_cast<double>(early_us) / 1000.0;
          metrics_exporter_->RecordMuxCTWaitMs(channel_id_, delta_ms);
        }
      }
    }

    if (stop_requested_.load(std::memory_order_acquire)) break;

    // =========================================================================
    // LAW-OUTPUT-LIVENESS: Transport MUST continue even if audio unavailable
    // =========================================================================
    // A/V sync is a content-plane concern. Transport liveness is non-negotiable.
    // If audio queue is empty, video proceeds alone - this preserves:
    // - Continuous TS packet emission
    // - PCR advancement (embedded in video packets)
    // - PAT/PMT cadence
    // - Late-joiner discoverability
    // Audio emission loop (below) gracefully handles empty queue by emitting
    // no audio frames for this iteration. Content may have transient silence.
    // =========================================================================
    if (silence_injection_disabled_.load(std::memory_order_acquire)) {
      bool audio_empty = false;
      {
        std::lock_guard<std::mutex> lock(audio_queue_mutex_);
        audio_empty = audio_queue_.empty();
      }
      if (audio_empty) {
        // Log audio underrun but DO NOT stall - transport must continue
        static int underrun_log_counter = 0;
        if (underrun_log_counter++ % 100 == 0) {
          std::cout << "[MpegTSOutputSink] LAW-OUTPUT-LIVENESS: Audio queue empty, "
                    << "video proceeding (transport continuous)"
                    << " vq_size=" << vq_size
                    << " video_ct_us=" << next_video_ct_us
                    << std::endl;
        }
        // Fall through - emit video without audio for this frame
      }
    }

    // =========================================================================
    // P9-CORE-002 Instrumentation: Dequeue interval and CT vs wall clock delta
    // =========================================================================
    auto dequeue_time = std::chrono::steady_clock::now();
    int64_t ct_wall_delta_us = std::chrono::duration_cast<std::chrono::microseconds>(
        dequeue_time - target_wall).count();
    sum_ct_wall_delta_us += ct_wall_delta_us;

    if (last_dequeue_time_valid) {
      int64_t dequeue_interval_us = std::chrono::duration_cast<std::chrono::microseconds>(
          dequeue_time - last_dequeue_time).count();
      sum_dequeue_interval_us += dequeue_interval_us;
      if (dequeue_interval_us < min_dequeue_interval_us) {
        min_dequeue_interval_us = dequeue_interval_us;
      }
      if (dequeue_interval_us > max_dequeue_interval_us) {
        max_dequeue_interval_us = dequeue_interval_us;
      }
    }
    last_dequeue_time = dequeue_time;
    last_dequeue_time_valid = true;

    // -----------------------------------------------------------------------
    // Step 4: Dequeue and encode exactly ONE video frame
    // -----------------------------------------------------------------------
    buffer::Frame frame;
    if (DequeueVideoFrame(&frame)) {
      video_emit_count++;

      // =====================================================================
      // P9-CORE-002 Instrumentation: Log pacing metrics every N frames
      // =====================================================================
      // Proves pacing is working:
      // - avg_dequeue_interval_us: Should be ~33333us at 30fps
      // - min/max: Should be within reasonable bounds (no bursts)
      // - avg_ct_wall_delta_us: How accurately we hit the target CT
      // - total_pacing_wait_us: Cumulative time spent waiting (proves we wait)
      // =====================================================================
      if (video_emit_count % kPacingLogInterval == 0 && video_emit_count > 0) {
        int64_t avg_dequeue_interval_us = sum_dequeue_interval_us / (kPacingLogInterval - 1);
        int64_t avg_ct_wall_delta_us = sum_ct_wall_delta_us / kPacingLogInterval;
        std::cout << "[MpegTSOutputSink] P9-CORE-002-PACING: "
                  << "emit_count=" << video_emit_count
                  << " avg_dequeue_interval_us=" << avg_dequeue_interval_us
                  << " min_dequeue_interval_us=" << min_dequeue_interval_us
                  << " max_dequeue_interval_us=" << max_dequeue_interval_us
                  << " avg_ct_wall_delta_us=" << avg_ct_wall_delta_us
                  << " total_pacing_wait_us=" << total_pacing_wait_us
                  << " late_frames=" << late_frame_count
                  << " pcr_paced_active=" << (pcr_paced_active_.load(std::memory_order_acquire) ? 1 : 0)
                  << std::endl;

        // Log warning if MAJORITY of frames are significantly late (producer not keeping up)
        // NOTE: "late" here means > kLateFrameThresholdUs (2ms), not just 1us late
        if (late_frame_count > kPacingLogInterval * 0.8) {  // >80% late
          std::cout << "[MpegTSOutputSink] P9-CORE-002-WARNING: " << late_frame_count << "/" << kPacingLogInterval
                    << " frames arrived >2ms late. Producer may not be keeping up with real-time."
                    << " (downstream_backpressure=" << (socket_sink_ && socket_sink_->IsThrottling() ? "YES" : "no") << ")"
                    << std::endl;
        }

        // Reset for next interval
        min_dequeue_interval_us = INT64_MAX;
        max_dequeue_interval_us = 0;
        sum_dequeue_interval_us = 0;
        sum_ct_wall_delta_us = 0;
        late_frame_count = 0;
      }

      const int64_t pts90k = (frame.metadata.pts * 90000) / 1'000'000;
      const bool is_real_frame = (frame.metadata.asset_uri.find("pad://") == std::string::npos &&
                                  frame.metadata.asset_uri.find("starvation://") == std::string::npos &&
                                  frame.metadata.asset_uri.find("internal://black") == std::string::npos);

      // =====================================================================
      // LATENESS-DECOMPOSITION: Log timing breakdown at encoder handoff
      // =====================================================================
      // Log every 30 frames to avoid spam but catch patterns
      static int lateness_log_counter = 0;
      if (++lateness_log_counter % 30 == 1) {
        auto now_handoff = std::chrono::steady_clock::now();
        int64_t wall_elapsed_handoff_us = std::chrono::duration_cast<std::chrono::microseconds>(
            now_handoff - wall_epoch).count();
        int64_t frame_ct_us = frame.metadata.pts;
        int64_t lateness_vs_epoch_us = frame_ct_us - ct_epoch_us - wall_elapsed_handoff_us;

        std::cout << "[LATENESS-DECOMPOSITION] frame#" << lateness_log_counter
                  << " frame_ct_us=" << frame_ct_us
                  << " ct_epoch_us=" << ct_epoch_us
                  << " ct_delta_us=" << (frame_ct_us - ct_epoch_us)
                  << " wall_elapsed_us=" << wall_elapsed_handoff_us
                  << " lateness_us=" << lateness_vs_epoch_us
                  << " (negative=early, positive=late)" << std::endl;

        // SANITY: frame_ct should be close to ct_epoch + wall_elapsed (within a few seconds)
        if (std::abs(lateness_vs_epoch_us) > 5'000'000) {  // > 5 seconds drift
          std::cerr << "[LATENESS-DECOMPOSITION] WARNING: " << (lateness_vs_epoch_us / 1000)
                    << "ms drift - possible clock domain issue!" << std::endl;
        }
      }

      std::cout << "[MpegTSOutputSink] Encoder received frame: real=" << (is_real_frame ? "yes" : "no")
                << " pts=" << frame.metadata.pts
                << " asset=" << frame.metadata.asset_uri << std::endl;
      encoder_->encodeFrame(frame, pts90k);

      // INV-TICK-GUARANTEED-OUTPUT: Save last emitted frame for freeze fallback
      last_emitted_frame = frame;
      have_last_frame = true;

      // ORCH-SWITCH-SUCCESSOR-OBSERVED: Notify when a real (non-pad) video
      // frame has been emitted by the encoder. Pad frames do not count.
      if (is_real_frame && on_successor_video_emitted_) {
        on_successor_video_emitted_();
      }

      // ---------------------------------------------------------------------
      // Step 5: Dequeue and encode all audio with CT <= video CT
      // ---------------------------------------------------------------------
      // Audio should be emitted up to (and slightly beyond) the video frame's CT
      // to ensure audio leads slightly for lip sync
      int64_t audio_cutoff_ct_us = frame.metadata.pts;

      buffer::AudioFrame audio_frame;
      int audio_batch = 0;
      while (true) {
        // Peek at next audio frame
        int64_t next_audio_ct_us = -1;
        {
          std::lock_guard<std::mutex> lock(audio_queue_mutex_);
          if (!audio_queue_.empty()) {
            next_audio_ct_us = audio_queue_.front().pts_us;
          }
        }

        if (next_audio_ct_us < 0 || next_audio_ct_us > audio_cutoff_ct_us) {
          // No more audio, or audio is ahead of video - stop
          break;
        }

        // Dequeue and encode this audio frame
        if (DequeueAudioFrame(&audio_frame)) {
          audio_emit_count++;
          audio_batch++;

          // INV-AUDIO-PTS-HOUSE-CLOCK-001: Derive PTS from sample clock, not content pts_us
          const int64_t audio_pts90k = (audio_samples_emitted_ * 90000) / buffer::kHouseAudioSampleRate;
          encoder_->encodeAudioFrame(audio_frame, audio_pts90k);
          audio_samples_emitted_ += audio_frame.nb_samples;

          // INV-P9-AUDIO-LIVENESS: Log when audio stream goes live (first audio packet after header)
          if (audio_emit_count == 1) {
            int64_t header_write_time = 0;
            {
              std::lock_guard<std::mutex> lock(g_header_write_mutex);
              auto it = g_header_write_time_us.find(this);
              if (it != g_header_write_time_us.end()) header_write_time = it->second;
            }
            std::cout << "[MpegTSOutputSink] INV-P9-AUDIO-LIVENESS: Audio stream live, first_audio_pts="
                      << audio_frame.pts_us << ", header_write_time=" << header_write_time << std::endl;

            // =====================================================================
            // INV-P9-IMMEDIATE-OUTPUT: Transition to producer-authoritative audio
            // =====================================================================
            // Now that real audio is flowing, disable silence injection.
            // From this point, if audio queue is empty, MuxLoop will stall
            // (correct behavior once real audio is established).
            // =====================================================================
            silence_injection_disabled_.store(true, std::memory_order_release);
            if (encoder_) {
              encoder_->SetAudioLivenessEnabled(false);
            }
            std::cout << "[MpegTSOutputSink] INV-P9-IMMEDIATE-OUTPUT: Real audio confirmed, "
                      << "silence injection DISABLED (producer audio authoritative)" << std::endl;
          }

        }
      }
    }

    // =========================================================================
    // INV-NO-SINK-PACING: Sink does NOT pace - ProgramOutput owns pacing
    // =========================================================================
    // REMOVED: Post-emit pacing loop that blocked to throttle output rate.
    //
    // Rationale: CONTINUITY > CORRECTNESS. The sink's job is to emit frames
    // as fast as they arrive. ProgramOutput already paces frame release at
    // real-time rate. Any blocking in the sink risks output stalls.
    //
    // Transport continuity (null packets) is handled by EmitNullPacketsIfNeeded()
    // at the top of the loop - it runs every iteration without blocking.
    // =========================================================================

    // -----------------------------------------------------------------------
    // INV-TRANSPORT-CONTINUOUS: No timing reset on queue underflow
    // -----------------------------------------------------------------------
    // Queue underflow is a transient condition, not a segment boundary.
    // Timing calibration (wall_epoch, ct_epoch_us) is immutable after first frame.
    // Segment transitions are invisible to the transport layer.
    // See: RULE-MUX-001, RULE-MUX-002, INV-NO-LOCAL-EPOCHS
    // -----------------------------------------------------------------------
  }

  // =========================================================================
  // INV-SINK-NO-IMPLICIT-EOF: Exit reason logging
  // =========================================================================
  // Determine why MuxLoop is exiting and log appropriately.
  // Allowed exits: stop_requested_ set (explicit Stop/Detach)
  // Violation: fd_ < 0 without stop_requested_ (implicit termination)
  // =========================================================================
  const bool explicit_stop = stop_requested_.load(std::memory_order_acquire);
  const bool fd_invalid = (fd_ < 0);

  if (explicit_stop) {
    std::cout << "[MpegTSOutputSink] MuxLoop exiting (explicit stop), video_emitted=" << video_emit_count
              << " audio_emitted=" << audio_emit_count
              << " fallback_frames=" << fallback_frame_count
              << " null_packets=" << null_packets_emitted_.load(std::memory_order_relaxed) << std::endl;
  } else if (fd_invalid) {
    std::cerr << "[MpegTSOutputSink] INV-SINK-NO-IMPLICIT-EOF VIOLATION: "
              << "mux loop exiting without explicit stop (reason=fd_invalid), "
              << "video_emitted=" << video_emit_count
              << " audio_emitted=" << audio_emit_count
              << " fallback_frames=" << fallback_frame_count << std::endl;
  } else {
    std::cerr << "[MpegTSOutputSink] INV-SINK-NO-IMPLICIT-EOF VIOLATION: "
              << "mux loop exiting without explicit stop (reason=unknown), "
              << "video_emitted=" << video_emit_count
              << " audio_emitted=" << audio_emit_count
              << " fallback_frames=" << fallback_frame_count << std::endl;
  }
}

void MpegTSOutputSink::EnqueueVideoFrame(const buffer::Frame& frame) {
  std::lock_guard<std::mutex> lock(video_queue_mutex_);
  if (video_queue_.size() >= kMaxVideoQueueSize) {
    video_queue_.pop();  // Drop oldest frame - VIOLATION of Phase 10 posture
    uint64_t total_dropped = video_frames_dropped_.fetch_add(1, std::memory_order_relaxed) + 1;
    // INV-P10-FRAME-DROP-POLICY: Sink overflow drop is a contract violation.
    // Correct behavior: backpressure propagates upstream to throttle decode.
    // This drop is an emergency overload rail, not routine flow control.
    std::cout << "[MpegTSOutputSink] INV-P10-FRAME-DROP-POLICY VIOLATION: "
              << "video_drop=1 queue_depth=" << video_queue_.size()
              << " max=" << kMaxVideoQueueSize
              << " total_dropped=" << total_dropped
              << " frame_ct=" << frame.metadata.pts
              << std::endl;
  }
  video_queue_.push(frame);
}

void MpegTSOutputSink::EnqueueAudioFrame(const buffer::AudioFrame& audio_frame) {
  std::lock_guard<std::mutex> lock(audio_queue_mutex_);
  if (audio_queue_.size() >= kMaxAudioQueueSize) {
    audio_queue_.pop();  // Drop oldest frame - VIOLATION of Phase 10 posture
    uint64_t total_dropped = audio_frames_dropped_.fetch_add(1, std::memory_order_relaxed) + 1;
    // INV-P10-FRAME-DROP-POLICY: Sink overflow drop is a contract violation.
    // Correct behavior: backpressure propagates upstream to throttle decode.
    // This drop is an emergency overload rail, not routine flow control.
    std::cout << "[MpegTSOutputSink] INV-P10-FRAME-DROP-POLICY VIOLATION: "
              << "audio_drop=1 queue_depth=" << audio_queue_.size()
              << " max=" << kMaxAudioQueueSize
              << " total_dropped=" << total_dropped
              << " frame_ct=" << audio_frame.pts_us
              << std::endl;
  }
  audio_queue_.push(audio_frame);
}

bool MpegTSOutputSink::DequeueVideoFrame(buffer::Frame* out) {
  if (!out) return false;
  std::lock_guard<std::mutex> lock(video_queue_mutex_);
  if (video_queue_.empty()) return false;
  *out = std::move(video_queue_.front());
  video_queue_.pop();
  // =========================================================================
  // INV-FALLBACK-003: Update timestamp ONLY when real frame is dequeued
  // =========================================================================
  // This timestamp is used to determine upstream starvation. It must reflect
  // actual frame availability, not enqueue time or peek time.
  // =========================================================================
  last_real_frame_dequeue_time_ = std::chrono::steady_clock::now();
  return true;
}

bool MpegTSOutputSink::DequeueAudioFrame(buffer::AudioFrame* out) {
  if (!out) return false;
  std::lock_guard<std::mutex> lock(audio_queue_mutex_);
  if (audio_queue_.empty()) return false;
  *out = std::move(audio_queue_.front());
  audio_queue_.pop();
  return true;
}

int MpegTSOutputSink::WriteToFdCallback(void* opaque, uint8_t* buf, int buf_size) {
  auto* sink = static_cast<MpegTSOutputSink*>(opaque);
  if (!sink || !sink->socket_sink_) return -1;

  // Forensic tap: mirror bytes before socket (non-blocking, passive)
  if (sink->forensic_enabled_.load(std::memory_order_acquire)) {
    ssize_t w = ::write(sink->forensic_fd_, buf, static_cast<size_t>(buf_size));
    (void)w;  // Forensic only — ignore errors, never block
  }

  // Emit bytes via SocketSink's bounded buffer + writer thread
  // LAW-OUTPUT-LIVENESS: SocketSink detaches slow consumers on buffer overflow
  // No packet drops; overflow triggers connection close
  bool enqueued = sink->socket_sink_->TryConsumeBytes(
      reinterpret_cast<const uint8_t*>(buf),
      static_cast<size_t>(buf_size));

  // Track attempt time (diagnostic only)
  sink->dbg_last_attempt_time_ = std::chrono::steady_clock::now();

  if (enqueued) {
    // Bytes enqueued to buffer; writer thread will deliver to kernel
    // INV-HONEST-LIVENESS-METRICS: "Delivered" time is tracked by SocketSink
    sink->dbg_bytes_enqueued_.fetch_add(
        static_cast<uint64_t>(buf_size), std::memory_order_relaxed);
    // INV-TS-CONTINUITY: Track last successful TS write for null packet injection
    sink->MarkTsWritten();
  } else {
    // Sink closed or detached (slow consumer)
    sink->dbg_bytes_dropped_.fetch_add(
        static_cast<uint64_t>(buf_size), std::memory_order_relaxed);

    // Check if sink was detached (slow consumer)
    if (sink->socket_sink_->IsDetached()) {
      // Sink detached - return error to stop FFmpeg output
      // Channel continues; future consumers can attach
      return -1;
    }
  }

  // INV-P9-BOOT-LIVENESS: Log when first decodable TS packet is emitted after sink attach
  if (sink->dbg_packets_written_.load(std::memory_order_relaxed) == 0) {
    auto now_wall = std::chrono::system_clock::now();
    auto now_steady = std::chrono::steady_clock::now();
    int64_t wall_time_us = std::chrono::duration_cast<std::chrono::microseconds>(
        now_wall.time_since_epoch()).count();
    {
      std::lock_guard<std::mutex> lock(g_header_write_mutex);
      g_header_write_time_us[sink] = wall_time_us;
    }
    int latency_ms = 0;
    {
      std::lock_guard<std::mutex> lock(g_sink_attach_mutex);
      auto it = g_sink_attach_time.find(sink);
      if (it != g_sink_attach_time.end()) {
        latency_ms = static_cast<int>(
            std::chrono::duration_cast<std::chrono::milliseconds>(now_steady - it->second).count());
      }
    }
    std::cout << "[MpegTSOutputSink] INV-P9-BOOT-LIVENESS: First decodable TS emitted at wall_time="
              << wall_time_us << ", latency_ms=" << latency_ms << std::endl;
    // INV-P9-TS-EMISSION-LIVENESS (P1-MS-005): Log success when first TS within 500ms of PCR-PACE init
    {
      std::lock_guard<std::mutex> lock(g_pcr_pace_init_mutex);
      auto it = g_pcr_pace_init_time.find(sink);
      if (it != g_pcr_pace_init_time.end()) {
        int elapsed_pcr_ms = static_cast<int>(
            std::chrono::duration_cast<std::chrono::milliseconds>(
                now_steady - it->second).count());
        if (elapsed_pcr_ms <= 500) {
          std::cout << "[MpegTSOutputSink] INV-P9-TS-EMISSION-LIVENESS: First TS emitted at "
                    << elapsed_pcr_ms << "ms (OK)" << std::endl;
        }
      }
    }
  }

  // Track packet count for violation detection
  sink->dbg_packets_written_.fetch_add(1, std::memory_order_relaxed);

  // Always return buf_size - SocketSink absorbed any backpressure (SS-002)
  return buf_size;
}

void MpegTSOutputSink::SetStatus(SinkStatus status, const std::string& message) {
  status_.store(status, std::memory_order_release);

  SinkStatusCallback callback;
  {
    std::lock_guard<std::mutex> lock(status_mutex_);
    callback = status_callback_;
  }

  if (callback) {
    callback(status, message);
  }
}

// =========================================================================
// INV-TS-CONTINUITY: Null packet emission for transport continuity
// =========================================================================
// Null packets (PID 0x1FFF) are the broadcast standard for maintaining
// constant bitrate and transport continuity during content gaps.
//
// TS Null Packet format (188 bytes):
//   Byte 0:     0x47 (sync byte)
//   Byte 1:     0x1F (TEI=0, PUSI=0, priority=0, PID[12:8]=0x1F)
//   Byte 2:     0xFF (PID[7:0]=0xFF, giving PID=0x1FFF)
//   Byte 3:     0x10 (scrambling=00, adaptation=01, continuity=0)
//   Bytes 4-187: 0xFF (stuffing bytes)
// =========================================================================
void MpegTSOutputSink::InitNullPackets() {
  if (null_packets_initialized_) return;

  // Initialize cluster of null packets
  for (size_t i = 0; i < kNullPacketClusterSize; ++i) {
    uint8_t* pkt = null_packet_cluster_ + (i * kTsPacketSize);

    // TS header for null packet
    pkt[0] = 0x47;  // Sync byte
    pkt[1] = 0x1F;  // PID high bits (0x1FFF >> 8)
    pkt[2] = 0xFF;  // PID low bits (0x1FFF & 0xFF)
    pkt[3] = 0x10;  // Adaptation=01 (payload only), continuity=0

    // Fill payload with stuffing bytes
    std::memset(pkt + 4, 0xFF, kTsPacketSize - 4);
  }

  null_packets_initialized_ = true;
}

void MpegTSOutputSink::EmitNullPackets() {
  if (!null_packets_initialized_ || !socket_sink_) return;

  // Emit null packet cluster directly to socket sink
  bool enqueued = socket_sink_->TryConsumeBytes(
      null_packet_cluster_,
      kTsPacketSize * kNullPacketClusterSize);

  if (enqueued) {
    null_packets_emitted_.fetch_add(kNullPacketClusterSize, std::memory_order_relaxed);
    // Update timestamp - null packets count as TS output
    MarkTsWritten();
  }
  // Note: If not enqueued, buffer is full - don't spam, just skip this cycle
}

void MpegTSOutputSink::MarkTsWritten() {
  auto now = std::chrono::steady_clock::now();
  int64_t now_us = std::chrono::duration_cast<std::chrono::microseconds>(
      now.time_since_epoch()).count();
  last_ts_write_time_us_.store(now_us, std::memory_order_release);
}

void MpegTSOutputSink::EmitNullPacketsIfNeeded() {
  if (!null_packets_initialized_ || !socket_sink_) return;

  int64_t last_write_us = last_ts_write_time_us_.load(std::memory_order_acquire);
  if (last_write_us == 0) return;  // Not yet initialized

  auto now = std::chrono::steady_clock::now();
  int64_t now_us = std::chrono::duration_cast<std::chrono::microseconds>(
      now.time_since_epoch()).count();
  int64_t gap_us = now_us - last_write_us;

  // If gap exceeds threshold, emit null packets to maintain transport continuity
  if (gap_us > kNullPacketIntervalUs) {
    EmitNullPackets();
  }
}

}  // namespace retrovue::output
