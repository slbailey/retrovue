// Repository: Retrovue-playout
// Component: MpegTSOutputSink Implementation
// Purpose: Concrete output sink that encodes frames to MPEG-TS over UDS/TCP.
// Copyright (c) 2025 RetroVue

#include "retrovue/output/MpegTSOutputSink.h"

#include <chrono>
#include <cstdlib>
#include <iostream>
#include <thread>
#include <unordered_map>
#include <unordered_set>

#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/playout_sinks/mpegts/EncoderPipeline.hpp"
#include "retrovue/telemetry/MetricsExporter.h"

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

  // Create SocketSink for non-blocking byte transport
  socket_sink_ = std::make_unique<SocketSink>(fd_, name_ + "-socket");

  // Create and open encoder pipeline
  encoder_ = std::make_unique<playout_sinks::mpegts::EncoderPipeline>(config_);
  if (!encoder_->open(config_, this, &MpegTSOutputSink::WriteToFdCallback)) {
    SetStatus(SinkStatus::kError, "Failed to open encoder pipeline");
    encoder_.reset();
    socket_sink_.reset();
    return false;
  }

  encoder_->SetOutputTimingEnabled(true);  // Enable timing immediately

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

  // P9-OPT-002: Report steady-state inactive to metrics
  if (metrics_exporter_) {
    metrics_exporter_->SetSteadyStateActive(channel_id_, false);
  }

  SetStatus(SinkStatus::kStopped, "Stopped");
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

  std::cout << "[MpegTSOutputSink] INV-P10-PCR-PACED-MUX: Time-driven emission enabled" << std::endl;

  while (!stop_requested_.load(std::memory_order_acquire) && fd_ >= 0) {
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

    // INV-P9-TS-EMISSION-LIVENESS (P1-MS-006): Log violation once if 500ms elapsed without first TS
    if (timing_initialized) {
      auto now_viol = std::chrono::steady_clock::now();
      int64_t elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
          now_viol - wall_epoch).count();
      if (elapsed_ms >= 500 && dbg_bytes_written_.load(std::memory_order_relaxed) == 0) {
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

    if (next_video_ct_us < 0) {
      // No video available - wait briefly and retry
      std::this_thread::sleep_for(std::chrono::milliseconds(1));
      continue;
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
    // INV-P9-STEADY-001 / P9-CORE-002: PCR-paced wait
    // =========================================================================
    // Only wait when:
    //   1. pcr_paced_active_ is true (steady-state entered)
    //   2. NoPcrPacing() environment variable is not set
    //   3. Current time is before target time
    //
    // If now >= target_wall, the frame's CT is already in the past (late frame).
    // This indicates the producer is not keeping up with real-time decode.
    // We emit immediately but track this for diagnostics.
    // =========================================================================
    int64_t actual_wait_us = 0;
    bool is_late_frame = (now >= target_wall);
    if (is_late_frame && pcr_paced_active_.load(std::memory_order_acquire)) {
      late_frame_count++;
    }

    if (pcr_paced_active_.load(std::memory_order_acquire) && !NoPcrPacing() && !is_late_frame) {
      // Not yet time to emit - sleep until target
      auto wait_us = std::chrono::duration_cast<std::chrono::microseconds>(target_wall - now).count();
      actual_wait_us = wait_us;
      total_pacing_wait_us += wait_us;

      // INV-P10-PCR-PACED-MUX: Pacing wait (log first only)
      if (pacing_wait_count == 0) {
        std::cout << "[MpegTSOutputSink] INV-P9-STEADY-001: PCR-paced mux active, first_wait="
                  << wait_us << "us" << std::endl;
      }
      pacing_wait_count++;

      // Sleep in small increments to check stop_requested
      while (std::chrono::steady_clock::now() < target_wall) {
        if (stop_requested_.load(std::memory_order_acquire)) break;
        auto remaining = std::chrono::duration_cast<std::chrono::microseconds>(
            target_wall - std::chrono::steady_clock::now());
        if (remaining.count() > 5000) {
          std::this_thread::sleep_for(std::chrono::milliseconds(5));
        } else if (remaining.count() > 0) {
          std::this_thread::sleep_for(remaining);
        } else {
          break;
        }
      }

      // P9-OPT-002: Record mux CT wait time for histogram (sample every 30 frames)
      if (metrics_exporter_ && (pacing_wait_count % 30) == 1) {
        double wait_ms = static_cast<double>(actual_wait_us) / 1000.0;
        metrics_exporter_->RecordMuxCTWaitMs(channel_id_, wait_ms);
      }
    }

    if (stop_requested_.load(std::memory_order_acquire)) break;

    // =========================================================================
    // INV-P9-STEADY-008: Stall when audio queue empty in steady-state
    // =========================================================================
    // When silence injection is disabled (steady-state), video MUST NOT advance
    // without audio. If audio queue is empty, mux STALLS until audio arrives.
    // This ensures A/V sync and prevents video-only emission.
    // =========================================================================
    if (silence_injection_disabled_.load(std::memory_order_acquire)) {
      // Check if audio is available for this video frame's CT
      int64_t audio_available_ct_us = -1;
      {
        std::lock_guard<std::mutex> lock(audio_queue_mutex_);
        if (!audio_queue_.empty()) {
          audio_available_ct_us = audio_queue_.front().pts_us;
        }
      }

      // If no audio available and we need audio (audio_ct <= video_ct), stall
      if (audio_available_ct_us < 0) {
        // No audio at all - stall
        static int stall_log_counter = 0;
        if (stall_log_counter++ % 100 == 0) {
          std::cout << "[MpegTSOutputSink] INV-P9-STEADY-008: Mux STALLING - audio queue empty"
                    << " (video waits with audio)"
                    << " vq_size=" << vq_size
                    << " video_ct_us=" << next_video_ct_us
                    << std::endl;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
        continue;  // Retry - don't emit video without audio
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

        // Log warning if all frames are late (producer not keeping up)
        if (late_frame_count == kPacingLogInterval) {
          std::cout << "[MpegTSOutputSink] P9-CORE-002-WARNING: All " << kPacingLogInterval
                    << " frames arrived late (CT already past). Producer may not be keeping up with real-time."
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
      encoder_->encodeFrame(frame, pts90k);

      // INV-SWITCH-SUCCESSOR-EMISSION: Notify when a real (non-pad) video
      // frame has been emitted by the encoder. Pad frames do not count.
      const bool is_real_frame = (frame.metadata.asset_uri != "pad://black");
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

          const int64_t audio_pts90k = (audio_frame.pts_us * 90000) / 1'000'000;
          encoder_->encodeAudioFrame(audio_frame, audio_pts90k);

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

    // -----------------------------------------------------------------------
    // INV-TRANSPORT-CONTINUOUS: No timing reset on queue underflow
    // -----------------------------------------------------------------------
    // Queue underflow is a transient condition, not a segment boundary.
    // Timing calibration (wall_epoch, ct_epoch_us) is immutable after first frame.
    // Segment transitions are invisible to the transport layer.
    // See: RULE-MUX-001, RULE-MUX-002, INV-NO-LOCAL-EPOCHS
    // -----------------------------------------------------------------------
  }

  std::cout << "[MpegTSOutputSink] MuxLoop exiting, video_emitted=" << video_emit_count
            << " audio_emitted=" << audio_emit_count << std::endl;
}

void MpegTSOutputSink::EnqueueVideoFrame(const buffer::Frame& frame) {
  std::lock_guard<std::mutex> lock(video_queue_mutex_);
  if (video_queue_.size() >= kMaxVideoQueueSize) {
    video_queue_.pop();  // Drop oldest frame
    std::cout << "[DBG-DROP] video_drop=1 reason=QUEUE_FULL vq_size="
              << video_queue_.size() << std::endl;
  }
  video_queue_.push(frame);
}

void MpegTSOutputSink::EnqueueAudioFrame(const buffer::AudioFrame& audio_frame) {
  std::lock_guard<std::mutex> lock(audio_queue_mutex_);
  if (audio_queue_.size() >= kMaxAudioQueueSize) {
    audio_queue_.pop();  // Drop oldest frame
    std::cout << "[DBG-DROP] audio_drop=1 reason=QUEUE_FULL aq_size="
              << audio_queue_.size() << std::endl;
  }
  audio_queue_.push(audio_frame);
}

bool MpegTSOutputSink::DequeueVideoFrame(buffer::Frame* out) {
  if (!out) return false;
  std::lock_guard<std::mutex> lock(video_queue_mutex_);
  if (video_queue_.empty()) return false;
  *out = std::move(video_queue_.front());
  video_queue_.pop();
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

  // Emit bytes via non-blocking SocketSink (SS-001, SS-002)
  bool accepted = sink->socket_sink_->TryConsumeBytes(
      reinterpret_cast<const uint8_t*>(buf),
      static_cast<size_t>(buf_size));

  // Track telemetry
  if (accepted) {
    sink->dbg_bytes_written_.fetch_add(
        static_cast<uint64_t>(buf_size), std::memory_order_relaxed);
  }
  sink->dbg_last_write_time_ = std::chrono::steady_clock::now();

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

}  // namespace retrovue::output
