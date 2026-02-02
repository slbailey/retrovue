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

#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/playout_sinks/mpegts/EncoderPipeline.hpp"

#include <cerrno>
#include <cstring>

#if defined(__linux__) || defined(__APPLE__)
#include <unistd.h>
#endif

#if defined(__linux__)
#include <sys/socket.h>  // For send() with MSG_NOSIGNAL
#endif

// =========================================================================
// DEBUG INSTRUMENTATION - remove after diagnosis
// =========================================================================
enum class MuxBlockReason {
  NONE,
  WAITING_FOR_VIDEO,
  WAITING_FOR_PCR_TIME,
  READY_TO_EMIT
};

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

static bool DbgBootstrapWriteEnabled() {
  static bool checked = false;
  static bool value = false;
  if (!checked) {
    const char* env = std::getenv("RETROVUE_DBG_BOOTSTRAP_WRITE");
    value = (env && env[0] == '1');
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

// Helper to write to fd without SIGPIPE (used for magic string before namespace)
static ssize_t SafeWriteGlobal(int fd, const void* data, size_t len) {
#if defined(__linux__)
  return send(fd, data, len, MSG_NOSIGNAL);
#else
  return write(fd, data, len);
#endif
}

namespace retrovue::output {

MpegTSOutputSink::MpegTSOutputSink(
    int fd,
    const playout_sinks::mpegts::MpegTSPlayoutSinkConfig& config,
    const std::string& name)
    : fd_(fd),
      config_(config),
      name_(name),
      status_(SinkStatus::kIdle),
      stop_requested_(false),
      prebuffer_target_bytes_(0),
      prebuffering_(false) {
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

  // Create and open encoder pipeline
  encoder_ = std::make_unique<playout_sinks::mpegts::EncoderPipeline>(config_);
  if (!encoder_->open(config_, this, &MpegTSOutputSink::WriteToFdCallback)) {
    SetStatus(SinkStatus::kError, "Failed to open encoder pipeline");
    encoder_.reset();
    return false;
  }

  // ==========================================================================
  // INV-P8-IO-UDS-001: UDS must never block output on prebuffer thresholds
  // ==========================================================================
  // UDS is low-latency and local; prebuffer thresholds can prevent first bytes
  // from ever reaching the client if encoder/header gating stalls.
  //
  // Practical enforcement:
  // - Default prebuffer OFF for UDS
  // - If ever re-enabled, MUST flush on timeout (250ms) and/or client connect
  // - Never use thresholds > 9.4KB (50 TS packets) for any transport
  //
  // Phase 8 issues that make large prebuffers dangerous:
  // - Short clips and frequent producer switches reset prebuffer
  // - Header deferral (INV-P8-AUDIO-PRIME-001) delays first bytes
  // - CT resets on segment boundaries invalidate buffered data
  // ==========================================================================
  prebuffer_target_bytes_ = 0;
  prebuffering_.store(false, std::memory_order_release);
  encoder_->SetOutputTimingEnabled(true);  // Enable timing immediately
  std::cout << "[MpegTSOutputSink] Prebuffering DISABLED (INV-P8-IO-UDS-001)" << std::endl;

  // =========================================================================
  // INV-P10-PCR-PACED-MUX: Disable audio liveness injection
  // =========================================================================
  // With PCR-paced mux, producer audio is authoritative. Silence injection
  // would create competing audio sources, causing PTS discontinuities.
  // If audio queue is empty, the mux loop stalls (correct behavior).
  // =========================================================================
  encoder_->SetAudioLivenessEnabled(false);
  std::cout << "[MpegTSOutputSink] INV-P10-PCR-PACED-MUX: Silence injection DISABLED" << std::endl;

  // Start mux thread
  stop_requested_.store(false, std::memory_order_release);
  mux_thread_ = std::thread(&MpegTSOutputSink::MuxLoop, this);

  // =========================================================================
  // DEBUG: Socket sanity check - write magic string immediately
  // =========================================================================
  {
    const char magic[] = "TS_TEST\n";
    ssize_t n = SafeWriteGlobal(fd_, magic, sizeof(magic) - 1);
    if (n > 0) {
      std::cout << "[DBG-SOCKET] Magic string written (" << n << " bytes) fd=" << fd_ << std::endl;
    } else {
      std::cout << "[DBG-SOCKET] Magic string FAILED: errno=" << errno
                << " (" << strerror(errno) << ") fd=" << fd_ << std::endl;
    }
  }

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

  // Clear queues
  {
    std::lock_guard<std::mutex> lock(video_queue_mutex_);
    while (!video_queue_.empty()) video_queue_.pop();
  }
  {
    std::lock_guard<std::mutex> lock(audio_queue_mutex_);
    while (!audio_queue_.empty()) audio_queue_.pop();
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

  uint64_t v = dbg_video_frames_enqueued_.fetch_add(1, std::memory_order_relaxed) + 1;
  EnqueueVideoFrame(frame);

  auto now = std::chrono::steady_clock::now();
  auto since_hb = std::chrono::duration_cast<std::chrono::milliseconds>(
      now - dbg_enqueue_heartbeat_time_).count();
  if (since_hb >= 1000) {
    size_t vq = 0, aq = 0;
    {
      std::lock_guard<std::mutex> lk(video_queue_mutex_);
      vq = video_queue_.size();
    }
    {
      std::lock_guard<std::mutex> lk(audio_queue_mutex_);
      aq = audio_queue_.size();
    }
    uint64_t a = dbg_audio_frames_enqueued_.load(std::memory_order_relaxed);
    std::cout << "[DBG-ENQUEUE] v_enq=" << v << " a_enq=" << a
              << " vq_size=" << vq << " aq_size=" << aq << std::endl;
    dbg_enqueue_heartbeat_time_ = now;
  }
}

void MpegTSOutputSink::ConsumeAudio(const buffer::AudioFrame& audio_frame) {
  if (!IsRunning()) return;

  dbg_audio_frames_enqueued_.fetch_add(1, std::memory_order_relaxed);
  EnqueueAudioFrame(audio_frame);

  auto now = std::chrono::steady_clock::now();
  auto since_hb = std::chrono::duration_cast<std::chrono::milliseconds>(
      now - dbg_enqueue_heartbeat_time_).count();
  if (since_hb >= 1000) {
    size_t vq = 0, aq = 0;
    {
      std::lock_guard<std::mutex> lk(video_queue_mutex_);
      vq = video_queue_.size();
    }
    {
      std::lock_guard<std::mutex> lk(audio_queue_mutex_);
      aq = audio_queue_.size();
    }
    uint64_t v = dbg_video_frames_enqueued_.load(std::memory_order_relaxed);
    uint64_t a = dbg_audio_frames_enqueued_.load(std::memory_order_relaxed);
    std::cout << "[DBG-ENQUEUE] v_enq=" << v << " a_enq=" << a
              << " vq_size=" << vq << " aq_size=" << aq << std::endl;
    dbg_enqueue_heartbeat_time_ = now;
  }
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

  // DEBUG: Mux state tracking (logs only on state change)
  MuxBlockReason dbg_block_reason = MuxBlockReason::NONE;
  MuxBlockReason dbg_prev_block_reason = MuxBlockReason::NONE;
  auto dbg_log_state = [&](MuxBlockReason reason, const std::string& extra = "") {
    if (reason != dbg_prev_block_reason) {
      const char* reason_str = "UNKNOWN";
      switch (reason) {
        case MuxBlockReason::NONE: reason_str = "NONE"; break;
        case MuxBlockReason::WAITING_FOR_VIDEO: reason_str = "WAITING_FOR_VIDEO"; break;
        case MuxBlockReason::WAITING_FOR_PCR_TIME: reason_str = "WAITING_FOR_PCR_TIME"; break;
        case MuxBlockReason::READY_TO_EMIT: reason_str = "READY_TO_EMIT"; break;
      }
      std::cout << "[DBG-MUXSTATE] " << reason_str;
      if (!extra.empty()) std::cout << " " << extra;
      std::cout << std::endl;
      dbg_prev_block_reason = reason;
    }
  };

  std::cout << "[MpegTSOutputSink] INV-P10-PCR-PACED-MUX: Time-driven emission enabled" << std::endl;

  auto dbg_mux_heartbeat_time = std::chrono::steady_clock::now();
  auto dbg_bootstrap_write_time = std::chrono::steady_clock::now();

  while (!stop_requested_.load(std::memory_order_acquire) && fd_ >= 0) {
    // -----------------------------------------------------------------------
    // DBG-OUTPUT heartbeat: print once/sec even when no writes (mux stuck)
    // -----------------------------------------------------------------------
    auto now_heartbeat = std::chrono::steady_clock::now();
    auto since_hb = std::chrono::duration_cast<std::chrono::milliseconds>(
        now_heartbeat - dbg_mux_heartbeat_time).count();
    if (since_hb >= 1000) {
      auto since_last_write = std::chrono::duration_cast<std::chrono::milliseconds>(
          now_heartbeat - dbg_last_write_time_).count();
      std::cout << "[DBG-OUTPUT] bytes=" << dbg_bytes_written_.load(std::memory_order_relaxed)
                << " packets=" << dbg_packets_written_.load(std::memory_order_relaxed)
                << " ms_since_last_write=" << since_last_write << std::endl;
      dbg_mux_heartbeat_time = now_heartbeat;
    }

    // -----------------------------------------------------------------------
    // Step 1: Peek at next video frame to determine target emit time
    // -----------------------------------------------------------------------
    int64_t next_video_ct_us = -1;
    size_t vq_size = 0;
    size_t aq_size = 0;
    int64_t head_ct_us = -1;
    int64_t head_pts_us = -1;
    {
      std::lock_guard<std::mutex> lock(video_queue_mutex_);
      vq_size = video_queue_.size();
      if (!video_queue_.empty()) {
        next_video_ct_us = video_queue_.front().metadata.pts;
        head_ct_us = video_queue_.front().metadata.pts;
        head_pts_us = video_queue_.front().metadata.pts;
      }
    }
    {
      std::lock_guard<std::mutex> lock(audio_queue_mutex_);
      aq_size = audio_queue_.size();
    }

    if (next_video_ct_us < 0) {
      // No video available - wait briefly and retry
      // This is the ONLY place we sleep when queue is empty
      dbg_log_state(MuxBlockReason::WAITING_FOR_VIDEO,
          "vq=" + std::to_string(vq_size) + " aq=" + std::to_string(aq_size) +
          " head_ct=" + std::to_string(head_ct_us) +
          " head_pts=" + std::to_string(head_pts_us));
      if (DbgBootstrapWriteEnabled()) {
        auto since_bootstrap = std::chrono::duration_cast<std::chrono::milliseconds>(
            now_heartbeat - dbg_bootstrap_write_time).count();
        if (since_bootstrap >= 1000) {
          const char magic[] = "TS_TEST\n";
          ssize_t n = SafeWriteGlobal(fd_, magic, sizeof(magic) - 1);
          if (n > 0) {
            std::cout << "[DBG-BOOTSTRAP] Magic string repeat (" << n << " bytes) fd="
                      << fd_ << std::endl;
          }
          dbg_bootstrap_write_time = now_heartbeat;
        }
      }
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
      std::cout << "[MpegTSOutputSink] PCR-PACE: Timing initialized, ct_epoch_us="
                << ct_epoch_us << std::endl;
    }

    // -----------------------------------------------------------------------
    // Step 3: Wait until wall clock matches frame's CT (PCR pacing)
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

    if (now < target_wall && !NoPcrPacing()) {
      // Not yet time to emit - sleep until target
      auto wait_us = std::chrono::duration_cast<std::chrono::microseconds>(target_wall - now).count();
      dbg_log_state(MuxBlockReason::WAITING_FOR_PCR_TIME,
          "vq=" + std::to_string(vq_size) + " aq=" + std::to_string(aq_size) +
          " head_ct=" + std::to_string(head_ct_us) + " head_pts=" + std::to_string(head_pts_us) +
          " wait_us=" + std::to_string(wait_us));
      // INV-P10-PCR-PACED-MUX: Pacing wait (log first, then every 100)
      if (pacing_wait_count == 0) {
        std::cout << "[MpegTSOutputSink] INV-P10-PCR-PACED-MUX: Pacing started, first_wait="
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
    }

    if (stop_requested_.load(std::memory_order_acquire)) break;

    // -----------------------------------------------------------------------
    // Step 4: Dequeue and encode exactly ONE video frame
    // -----------------------------------------------------------------------
    dbg_log_state(MuxBlockReason::READY_TO_EMIT,
        "vq=" + std::to_string(vq_size) + " aq=" + std::to_string(aq_size) +
        " head_ct=" + std::to_string(head_ct_us) + " head_pts=" + std::to_string(head_pts_us));
    buffer::Frame frame;
    if (DequeueVideoFrame(&frame)) {
      video_emit_count++;

      const int64_t pts90k = (frame.metadata.pts * 90000) / 1'000'000;
      encoder_->encodeFrame(frame, pts90k);

      // INV-SWITCH-SUCCESSOR-EMISSION: Notify when a real (non-pad) video
      // frame has been emitted by the encoder. Pad frames do not count.
      const bool is_real_frame = (frame.metadata.asset_uri != "pad://black");
      if (is_real_frame && on_successor_video_emitted_) {
        on_successor_video_emitted_();
      }

      // INV-P10-PCR-PACED-MUX: Video emission summary (first, then every 100)
      if (video_emit_count == 1 || video_emit_count % 100 == 0) {
        std::cout << "[MpegTSOutputSink] INV-P10-PCR-PACED-MUX: Video emitted="
                  << video_emit_count << std::endl;
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
          }

          // INV-P10-PCR-PACED-MUX: Audio emission summary (first, then every 100)
          if (audio_emit_count == 1 || audio_emit_count % 100 == 0) {
            std::cout << "[MpegTSOutputSink] INV-P10-PCR-PACED-MUX: Audio emitted="
                      << audio_emit_count << std::endl;
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

// Helper to write to fd without SIGPIPE (uses send with MSG_NOSIGNAL on Linux)
static ssize_t SafeWrite(int fd, const void* data, size_t len) {
#if defined(__linux__)
  // Use send() with MSG_NOSIGNAL to avoid SIGPIPE on closed socket
  return send(fd, data, len, MSG_NOSIGNAL);
#else
  return write(fd, data, len);
#endif
}

int MpegTSOutputSink::WriteToFdCallback(void* opaque, uint8_t* buf, int buf_size) {
#if defined(__linux__) || defined(__APPLE__)
  auto* sink = static_cast<MpegTSOutputSink*>(opaque);
  if (!sink || sink->fd_ < 0) return -1;

  // Prebuffer phase: accumulate data until we have enough for smooth playback.
  // This absorbs encoder warmup bitrate spikes (fade-ins, etc.)
  if (sink->prebuffering_.load(std::memory_order_acquire)) {
    std::lock_guard<std::mutex> lock(sink->prebuffer_mutex_);

    // Add data to prebuffer
    sink->prebuffer_.insert(sink->prebuffer_.end(), buf, buf + buf_size);

    // Check if we've reached the target
    if (sink->prebuffer_.size() >= sink->prebuffer_target_bytes_) {
      // Write entire prebuffer to fd (handle EAGAIN/EINTR)
      const uint8_t* p = sink->prebuffer_.data();
      size_t remaining = sink->prebuffer_.size();
      while (remaining > 0) {
        ssize_t n = SafeWrite(sink->fd_, p, remaining);
        if (n < 0) {
          if (errno == EINTR) continue;  // Interrupted, retry
          if (errno == EAGAIN || errno == EWOULDBLOCK) {
            // Backpressure - brief sleep and retry
            std::this_thread::sleep_for(std::chrono::microseconds(100));
            continue;
          }
          sink->prebuffer_.clear();
          return -1;
        }
        if (n == 0) {
          sink->prebuffer_.clear();
          return -1;
        }
        remaining -= static_cast<size_t>(n);
        p += n;
      }

      sink->prebuffer_.clear();
      sink->prebuffer_.shrink_to_fit();  // Free memory
      sink->prebuffering_.store(false, std::memory_order_release);

      // P8-IO-001: Re-enable output timing now that prebuffer is flushed
      if (sink->encoder_) {
        sink->encoder_->SetOutputTimingEnabled(true);
      }
      std::cout << "[MpegTSOutputSink] Prebuffer flushed, output timing re-enabled" << std::endl;
    }

    return buf_size;  // Data accepted (buffered)
  }

  // Direct streaming mode: write all bytes (handle partial writes + EAGAIN/EINTR)
  const uint8_t* p = buf;
  size_t remaining = static_cast<size_t>(buf_size);
  while (remaining > 0) {
    ssize_t n = SafeWrite(sink->fd_, p, remaining);
    if (n < 0) {
      if (errno == EINTR) continue;  // Interrupted, retry
      if (errno == EAGAIN || errno == EWOULDBLOCK) {
        // Backpressure - brief sleep and retry
        std::this_thread::sleep_for(std::chrono::microseconds(100));
        continue;
      }
      // Real error (EPIPE, etc.)
      return -1;
    }
    if (n == 0) {
      // Connection closed
      return -1;
    }
    remaining -= static_cast<size_t>(n);
    p += n;

    // DEBUG: Track successful writes
    sink->dbg_bytes_written_.fetch_add(static_cast<uint64_t>(n), std::memory_order_relaxed);
    sink->dbg_last_write_time_ = std::chrono::steady_clock::now();
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
  }

  // DEBUG: Increment packet count and emit heartbeat (max 1/sec)
  sink->dbg_packets_written_.fetch_add(1, std::memory_order_relaxed);
  auto now = std::chrono::steady_clock::now();
  auto since_last_hb = std::chrono::duration_cast<std::chrono::milliseconds>(
      now - sink->dbg_output_heartbeat_time_).count();
  if (since_last_hb >= 1000) {
    auto since_last_write = std::chrono::duration_cast<std::chrono::milliseconds>(
        now - sink->dbg_last_write_time_).count();
    std::cout << "[DBG-OUTPUT] bytes_written=" << sink->dbg_bytes_written_.load()
              << " packets_written=" << sink->dbg_packets_written_.load()
              << " ms_since_last_write=" << since_last_write << std::endl;
    sink->dbg_output_heartbeat_time_ = now;
  }

  return buf_size;
#else
  (void)opaque;
  (void)buf;
  (void)buf_size;
  return -1;
#endif
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
