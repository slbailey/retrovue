// Repository: Retrovue-playout
// Component: MpegTSOutputSink Implementation
// Purpose: Concrete output sink that encodes frames to MPEG-TS over UDS/TCP.
// Copyright (c) 2025 RetroVue

#include "retrovue/output/MpegTSOutputSink.h"

#include <chrono>
#include <iostream>
#include <thread>

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
      had_frames_(false),
      empty_iterations_(0),
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
  static int consume_count = 0;
  consume_count++;
  if (consume_count <= 5 || consume_count % 100 == 0) {
    std::cout << "[MpegTSOutputSink] ConsumeVideo #" << consume_count
              << " running=" << (IsRunning() ? "yes" : "no")
              << " status=" << static_cast<int>(GetStatus()) << std::endl;
  }
  if (!IsRunning()) return;
  EnqueueVideoFrame(frame);
}

void MpegTSOutputSink::ConsumeAudio(const buffer::AudioFrame& audio_frame) {
  static int consume_audio_count = 0;
  consume_audio_count++;
  if (consume_audio_count <= 5 || consume_audio_count % 100 == 0) {
    std::cout << "[MpegTSOutputSink] ConsumeAudio #" << consume_audio_count
              << " running=" << (IsRunning() ? "yes" : "no")
              << " pts_us=" << audio_frame.pts_us << std::endl;
  }
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

  std::cout << "[MpegTSOutputSink] INV-P10-PCR-PACED-MUX: Time-driven emission enabled" << std::endl;

  while (!stop_requested_.load(std::memory_order_acquire) && fd_ >= 0) {
    // -----------------------------------------------------------------------
    // Step 1: Peek at next video frame to determine target emit time
    // -----------------------------------------------------------------------
    int64_t next_video_ct_us = -1;
    {
      std::lock_guard<std::mutex> lock(video_queue_mutex_);
      if (!video_queue_.empty()) {
        next_video_ct_us = video_queue_.front().metadata.pts;
      }
    }

    if (next_video_ct_us < 0) {
      // No video available - wait briefly and retry
      // This is the ONLY place we sleep when queue is empty
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
    auto target_wall = wall_epoch + std::chrono::microseconds(ct_delta_us);
    auto now = std::chrono::steady_clock::now();

    if (now < target_wall) {
      // Not yet time to emit - sleep until target
      auto wait_us = std::chrono::duration_cast<std::chrono::microseconds>(target_wall - now).count();
      if (pacing_wait_count < 5 || pacing_wait_count % 100 == 0) {
        std::cout << "[MpegTSOutputSink] PCR-PACE: Waiting " << wait_us
                  << "us for frame CT=" << next_video_ct_us << std::endl;
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
    buffer::Frame frame;
    if (DequeueVideoFrame(&frame)) {
      video_emit_count++;

      const int64_t pts90k = (frame.metadata.pts * 90000) / 1'000'000;
      encoder_->encodeFrame(frame, pts90k);

      if (video_emit_count <= 5 || video_emit_count % 100 == 0) {
        std::cout << "[MpegTSOutputSink] PCR-PACE: Emitted video #" << video_emit_count
                  << " CT=" << frame.metadata.pts << "us pts90k=" << pts90k << std::endl;
      }

      had_frames_ = true;

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

          if (audio_emit_count <= 5 || audio_emit_count % 100 == 0) {
            std::cout << "[MpegTSOutputSink] PCR-PACE: Emitted audio #" << audio_emit_count
                      << " CT=" << audio_frame.pts_us << "us" << std::endl;
          }
        }
      }
    }

    // -----------------------------------------------------------------------
    // Step 6: Detect producer switch (empty queues after having frames)
    // -----------------------------------------------------------------------
    bool video_empty, audio_empty;
    {
      std::lock_guard<std::mutex> lock(video_queue_mutex_);
      video_empty = video_queue_.empty();
    }
    {
      std::lock_guard<std::mutex> lock(audio_queue_mutex_);
      audio_empty = audio_queue_.empty();
    }

    if (had_frames_ && video_empty && audio_empty) {
      empty_iterations_++;
      // Wait several iterations to confirm it's a real switch
      if (empty_iterations_ >= 3) {  // ~100ms at 33ms per frame
        encoder_->flushAudio();
        had_frames_ = false;
        empty_iterations_ = 0;
        // Reset timing for next segment
        timing_initialized = false;
        std::cout << "[MpegTSOutputSink] PCR-PACE: Segment ended, timing reset" << std::endl;
      }
    } else {
      empty_iterations_ = 0;
    }
  }

  std::cout << "[MpegTSOutputSink] MuxLoop exiting, video_emitted=" << video_emit_count
            << " audio_emitted=" << audio_emit_count << std::endl;
}

void MpegTSOutputSink::EnqueueVideoFrame(const buffer::Frame& frame) {
  std::lock_guard<std::mutex> lock(video_queue_mutex_);
  static int enqueue_count = 0;
  if (enqueue_count < 5 || enqueue_count % 100 == 0) {
    std::cout << "[MpegTSOutputSink] EnqueueVideoFrame #" << enqueue_count
              << " queue_size=" << video_queue_.size() << std::endl;
  }
  enqueue_count++;
  if (video_queue_.size() >= kMaxVideoQueueSize) {
    video_queue_.pop();  // Drop oldest frame
  }
  video_queue_.push(frame);
}

void MpegTSOutputSink::EnqueueAudioFrame(const buffer::AudioFrame& audio_frame) {
  std::lock_guard<std::mutex> lock(audio_queue_mutex_);
  if (audio_queue_.size() >= kMaxAudioQueueSize) {
    audio_queue_.pop();  // Drop oldest frame
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
