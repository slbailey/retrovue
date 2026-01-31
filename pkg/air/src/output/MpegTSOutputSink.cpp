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

  // P8-IO-001: Enable prebuffering to accumulate initial data before writing to socket
  // This ensures VLC/clients see immediate data when they connect.
  // Target: ~64KB (enough for MPEG-TS header + initial video/audio packets)
  prebuffer_target_bytes_ = 64 * 1024;
  prebuffering_.store(true, std::memory_order_release);

  // P8-IO-001: Disable output timing during prebuffer phase to allow rapid filling
  encoder_->SetOutputTimingEnabled(false);
  std::cout << "[MpegTSOutputSink] Prebuffering enabled, target=" << prebuffer_target_bytes_ << " bytes" << std::endl;

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
  static int loop_count = 0;
  static int dequeue_success = 0;
  static int encode_calls = 0;

  // INV-P8-AUDIO-CT-001: Audio PTS must be derived from CT, not raw media time
  // Track CT-based audio timeline to keep audio in sync with video
  int64_t audio_ct_us = 0;  // CT-based audio PTS in microseconds
  bool audio_ct_initialized = false;

  while (!stop_requested_.load(std::memory_order_acquire) && fd_ >= 0) {
    bool processed_any = false;
    loop_count++;

    // Process video frame
    buffer::Frame frame;
    if (DequeueVideoFrame(&frame)) {
      dequeue_success++;
      if (dequeue_success <= 5 || dequeue_success % 100 == 0) {
        std::cout << "[MpegTSOutputSink] MuxLoop dequeued #" << dequeue_success
                  << " (loop=" << loop_count << ")" << std::endl;
      }

      // INV-P8-AUDIO-CT-001: Initialize audio CT from first video frame
      if (!audio_ct_initialized) {
        audio_ct_us = frame.metadata.pts;
        audio_ct_initialized = true;
        std::cout << "[MpegTSOutputSink] Audio CT initialized from video: " << audio_ct_us << "us" << std::endl;
      }

      // Frame.metadata.pts is in microseconds; encoder expects 90kHz.
      const int64_t pts90k = (frame.metadata.pts * 90000) / 1'000'000;
      encoder_->encodeFrame(frame, pts90k);
      encode_calls++;
      if (encode_calls <= 5 || encode_calls % 100 == 0) {
        std::cout << "[MpegTSOutputSink] MuxLoop encoded #" << encode_calls << std::endl;
      }
      processed_any = true;
      had_frames_ = true;
    }

    // Process audio frame
    buffer::AudioFrame audio_frame;
    static int audio_dequeue_count = 0;
    if (DequeueAudioFrame(&audio_frame)) {
      audio_dequeue_count++;

      // INV-P8-AUDIO-CT-001: Derive audio PTS from CT, not raw media time
      // audio_ct_us tracks our position in CT timeline
      // Increment by audio frame duration after encoding
      const int64_t audio_pts90k = (audio_ct_us * 90000) / 1'000'000;

      if (audio_dequeue_count <= 5 || audio_dequeue_count % 100 == 0) {
        std::cout << "[MpegTSOutputSink] MuxLoop audio dequeued #" << audio_dequeue_count
                  << " raw_pts_us=" << audio_frame.pts_us
                  << " ct_pts_us=" << audio_ct_us << std::endl;
      }

      encoder_->encodeAudioFrame(audio_frame, audio_pts90k);

      // Advance audio CT by frame duration: (samples * 1000000) / sample_rate
      if (audio_frame.sample_rate > 0) {
        audio_ct_us += (static_cast<int64_t>(audio_frame.nb_samples) * 1'000'000) / audio_frame.sample_rate;
      }

      processed_any = true;
      had_frames_ = true;
    }

    // Detect producer switch: if we had frames before but now both queues are empty,
    // flush encoder buffers to ensure all audio from previous producer is encoded.
    if (had_frames_ && !processed_any) {
      bool video_empty, audio_empty;
      {
        std::lock_guard<std::mutex> lock(video_queue_mutex_);
        video_empty = video_queue_.empty();
      }
      {
        std::lock_guard<std::mutex> lock(audio_queue_mutex_);
        audio_empty = audio_queue_.empty();
      }

      if (video_empty && audio_empty) {
        empty_iterations_++;
        // Wait several iterations to confirm it's a real switch, not a brief gap
        if (empty_iterations_ >= 10) {  // ~50ms at 5ms sleep intervals
          encoder_->flushAudio();
          had_frames_ = false;
          empty_iterations_ = 0;
        }
      } else {
        empty_iterations_ = 0;
      }
    } else {
      empty_iterations_ = 0;
    }

    if (!processed_any) {
      std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
  }
  std::cout << "[MpegTSOutputSink] MuxLoop exiting, stop_requested=" << stop_requested_.load()
            << " fd=" << fd_ << std::endl;
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
