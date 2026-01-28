// Phase 6A.3 — ProgrammaticProducer: synthetic frames only; no ffmpeg, no file I/O.

#include "retrovue/producers/programmatic/ProgrammaticProducer.h"

#include <chrono>
#include <cmath>
#include <cstring>
#include <iostream>
#include <thread>

#include "retrovue/timing/MasterClock.h"

namespace retrovue::producers::programmatic
{

  namespace
  {
    constexpr int64_t kMicrosecondsPerSecond = 1'000'000;
  }

  ProgrammaticProducer::ProgrammaticProducer(
      const ProgrammaticProducerConfig& config,
      buffer::FrameRingBuffer& output_buffer,
      std::shared_ptr<timing::MasterClock> clock)
      : config_(config),
        output_buffer_(output_buffer),
        master_clock_(std::move(clock)),
        state_(State::STOPPED),
        stop_requested_(false),
        frames_produced_(0),
        frame_interval_us_(static_cast<int64_t>(std::round(kMicrosecondsPerSecond / config.target_fps))),
        next_pts_us_(0)
  {
  }

  ProgrammaticProducer::~ProgrammaticProducer()
  {
    stop();
  }

  bool ProgrammaticProducer::start()
  {
    State current = state_.load(std::memory_order_acquire);
    if (current != State::STOPPED)
      return false;

    state_.store(State::RUNNING, std::memory_order_release);
    stop_requested_.store(false, std::memory_order_release);
    frames_produced_.store(0, std::memory_order_release);
    next_pts_us_ = static_cast<int64_t>(config_.start_offset_ms) * 1000;

    producer_thread_ = std::make_unique<std::thread>(&ProgrammaticProducer::ProduceLoop, this);
    return true;
  }

  void ProgrammaticProducer::stop()
  {
    State current = state_.load(std::memory_order_acquire);

    if (!producer_thread_ || !producer_thread_->joinable())
    {
      if (current == State::STOPPED)
        return;
      state_.store(State::STOPPED, std::memory_order_release);
      return;
    }

    if (current != State::STOPPED)
    {
      state_.store(State::STOPPING, std::memory_order_release);
      stop_requested_.store(true, std::memory_order_release);
    }
    producer_thread_->join();
    producer_thread_.reset();
    state_.store(State::STOPPED, std::memory_order_release);
  }

  bool ProgrammaticProducer::isRunning() const
  {
    return state_.load(std::memory_order_acquire) == State::RUNNING;
  }

  uint64_t ProgrammaticProducer::GetFramesProduced() const
  {
    return frames_produced_.load(std::memory_order_acquire);
  }

  void ProgrammaticProducer::ProduceLoop()
  {
    while (!stop_requested_.load(std::memory_order_acquire))
    {
      if (state_.load(std::memory_order_acquire) != State::RUNNING)
      {
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
        continue;
      }

      // Phase 8.6: segment end = natural EOF only; hard_stop_time_ms not used to stop process.

      buffer::Frame frame;
      frame.width = config_.target_width;
      frame.height = config_.target_height;
      frame.metadata.pts = next_pts_us_;
      frame.metadata.dts = next_pts_us_;
      frame.metadata.duration = 1.0 / config_.target_fps;
      frame.metadata.asset_uri = config_.asset_uri;

      size_t data_size = static_cast<size_t>(config_.target_width * config_.target_height * 3 / 2);  // YUV420
      frame.data.resize(data_size, 0);

      if (output_buffer_.Push(frame))
      {
        frames_produced_.fetch_add(1, std::memory_order_relaxed);
        next_pts_us_ += frame_interval_us_;
      }

      if (master_clock_ && master_clock_->is_fake())
        std::this_thread::yield();
      else
        std::this_thread::sleep_for(
            std::chrono::microseconds(std::min<int64_t>(frame_interval_us_, 10000)));
    }

    state_.store(State::STOPPED, std::memory_order_release);
    std::cout << "[ProgrammaticProducer] Produce loop exited. Frames produced: "
              << frames_produced_.load(std::memory_order_acquire) << std::endl;
  }

}  // namespace retrovue::producers::programmatic
