// Repository: Retrovue-playout
// Component: BlackFrameProducer Implementation
// Purpose: Internal failsafe producer that outputs valid black video frames.
// Contract: docs/contracts/architecture/BlackFrameProducerContract.md
// Copyright (c) 2025 RetroVue

#include "retrovue/producers/black/BlackFrameProducer.h"

#include <chrono>
#include <cmath>
#include <cstring>
#include <iostream>
#include <thread>

#include "retrovue/timing/MasterClock.h"

namespace retrovue::producers::black {

namespace {
constexpr int64_t kMicrosecondsPerSecond = 1'000'000;

// YUV420 black pixel values
constexpr uint8_t kBlackY = 16;   // Luma (black in limited range)
constexpr uint8_t kBlackU = 128;  // Chroma U (neutral)
constexpr uint8_t kBlackV = 128;  // Chroma V (neutral)
}  // namespace

BlackFrameProducer::BlackFrameProducer(buffer::FrameRingBuffer& output_buffer,
                                       const runtime::ProgramFormat& format,
                                       std::shared_ptr<timing::MasterClock> clock,
                                       int64_t initial_pts_us)
    : format_(format),
      output_buffer_(output_buffer),
      master_clock_(std::move(clock)),
      state_(State::STOPPED),
      stop_requested_(false),
      frames_produced_(0),
      next_pts_us_(initial_pts_us) {
  // Extract video parameters from format
  target_width_ = format_.video.width > 0 ? format_.video.width : 1920;
  target_height_ = format_.video.height > 0 ? format_.video.height : 1080;
  target_fps_ = format_.GetFrameRateAsDouble();
  if (target_fps_ <= 0.0) {
    target_fps_ = 30.0;  // Default to 30fps if not specified
  }

  // Calculate frame interval in microseconds
  frame_interval_us_ = static_cast<int64_t>(
      std::round(static_cast<double>(kMicrosecondsPerSecond) / target_fps_));

  // Pre-allocate black frame data (YUV420 planar format)
  // Y plane: width * height bytes
  // U plane: (width/2) * (height/2) bytes
  // V plane: (width/2) * (height/2) bytes
  size_t y_size = static_cast<size_t>(target_width_ * target_height_);
  size_t uv_size = static_cast<size_t>((target_width_ / 2) * (target_height_ / 2));
  size_t total_size = y_size + (2 * uv_size);

  black_frame_data_.resize(total_size);

  // Fill Y plane with black luma value
  std::memset(black_frame_data_.data(), kBlackY, y_size);

  // Fill U plane with neutral chroma
  std::memset(black_frame_data_.data() + y_size, kBlackU, uv_size);

  // Fill V plane with neutral chroma
  std::memset(black_frame_data_.data() + y_size + uv_size, kBlackV, uv_size);
}

BlackFrameProducer::~BlackFrameProducer() {
  stop();
}

bool BlackFrameProducer::start() {
  State current = state_.load(std::memory_order_acquire);
  if (current != State::STOPPED) {
    return false;  // Already running or stopping
  }

  state_.store(State::RUNNING, std::memory_order_release);
  stop_requested_.store(false, std::memory_order_release);

  producer_thread_ = std::make_unique<std::thread>(&BlackFrameProducer::ProduceLoop, this);
  return true;
}

void BlackFrameProducer::stop() {
  State current = state_.load(std::memory_order_acquire);

  if (!producer_thread_ || !producer_thread_->joinable()) {
    if (current == State::STOPPED) {
      return;
    }
    state_.store(State::STOPPED, std::memory_order_release);
    return;
  }

  if (current != State::STOPPED) {
    state_.store(State::STOPPING, std::memory_order_release);
    stop_requested_.store(true, std::memory_order_release);
  }

  producer_thread_->join();
  producer_thread_.reset();
  state_.store(State::STOPPED, std::memory_order_release);
}

bool BlackFrameProducer::isRunning() const {
  return state_.load(std::memory_order_acquire) == State::RUNNING;
}

uint64_t BlackFrameProducer::GetFramesProduced() const {
  return frames_produced_.load(std::memory_order_acquire);
}

int64_t BlackFrameProducer::GetCurrentPts() const {
  return next_pts_us_.load(std::memory_order_acquire);
}

void BlackFrameProducer::SetInitialPts(int64_t pts_us) {
  next_pts_us_.store(pts_us, std::memory_order_release);
}

void BlackFrameProducer::ProduceLoop() {
  std::cout << "[BlackFrameProducer] Started. Format: " << target_width_ << "x"
            << target_height_ << " @ " << target_fps_ << " fps" << std::endl;

  while (!stop_requested_.load(std::memory_order_acquire)) {
    if (state_.load(std::memory_order_acquire) != State::RUNNING) {
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
      continue;
    }

    ProduceBlackFrame();

    // Respect timing - either real-time pacing or yield for fake clocks
    if (master_clock_ && master_clock_->is_fake()) {
      // In deterministic mode, just yield to allow test to advance time
      std::this_thread::yield();
    } else {
      // Real-time pacing: sleep for approximately one frame interval
      // Use shorter sleep to allow responsive stopping
      std::this_thread::sleep_for(
          std::chrono::microseconds(std::min<int64_t>(frame_interval_us_, 10000)));
    }
  }

  state_.store(State::STOPPED, std::memory_order_release);
  std::cout << "[BlackFrameProducer] Stopped. Frames produced: "
            << frames_produced_.load(std::memory_order_acquire) << std::endl;
}

void BlackFrameProducer::ProduceBlackFrame() {
  buffer::Frame frame;

  // Set frame dimensions
  frame.width = target_width_;
  frame.height = target_height_;

  // Set frame metadata
  int64_t pts = next_pts_us_.load(std::memory_order_acquire);
  frame.metadata.pts = pts;
  frame.metadata.dts = pts;
  frame.metadata.duration = 1.0 / target_fps_;
  frame.metadata.asset_uri = kAssetUri;

  // Copy pre-allocated black frame data
  frame.data = black_frame_data_;

  // Push to output buffer (may fail if buffer is full, which is expected)
  if (output_buffer_.Push(frame)) {
    frames_produced_.fetch_add(1, std::memory_order_relaxed);
    next_pts_us_.fetch_add(frame_interval_us_, std::memory_order_relaxed);
  }
}

}  // namespace retrovue::producers::black
