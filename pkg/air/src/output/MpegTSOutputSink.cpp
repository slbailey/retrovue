// Repository: Retrovue-playout
// Component: MpegTSOutputSink Implementation
// Purpose: Concrete output sink that encodes frames to MPEG-TS over UDS/TCP.
// Copyright (c) 2025 RetroVue

#include "retrovue/output/MpegTSOutputSink.h"

#include <chrono>
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

void MpegTSOutputSink::MuxLoop() {
  while (!stop_requested_.load(std::memory_order_acquire) && fd_ >= 0) {
    bool processed_any = false;

    // Process video frame
    buffer::Frame frame;
    if (DequeueVideoFrame(&frame)) {
      // Frame.metadata.pts is in microseconds; encoder expects 90kHz.
      const int64_t pts90k = (frame.metadata.pts * 90000) / 1'000'000;
      encoder_->encodeFrame(frame, pts90k);
      processed_any = true;
      had_frames_ = true;
    }

    // Process audio frame
    buffer::AudioFrame audio_frame;
    if (DequeueAudioFrame(&audio_frame)) {
      // AudioFrame.pts_us is in microseconds; encoder expects 90kHz.
      const int64_t audio_pts90k = (audio_frame.pts_us * 90000) / 1'000'000;
      encoder_->encodeAudioFrame(audio_frame, audio_pts90k);
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
}

void MpegTSOutputSink::EnqueueVideoFrame(const buffer::Frame& frame) {
  std::lock_guard<std::mutex> lock(video_queue_mutex_);
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
