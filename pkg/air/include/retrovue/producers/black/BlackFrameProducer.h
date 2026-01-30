// Repository: Retrovue-playout
// Component: BlackFrameProducer
// Purpose: Internal failsafe producer that outputs valid black video frames.
// Contract: docs/contracts/architecture/BlackFrameProducerContract.md
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_PRODUCERS_BLACK_BLACK_FRAME_PRODUCER_H_
#define RETROVUE_PRODUCERS_BLACK_BLACK_FRAME_PRODUCER_H_

#include <atomic>
#include <cstdint>
#include <memory>
#include <mutex>
#include <thread>

#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/producers/IProducer.h"
#include "retrovue/runtime/ProgramFormat.h"

namespace retrovue::timing {
class MasterClock;
}

namespace retrovue::producers::black {

// BlackFrameProducer is an internal failsafe producer that outputs valid
// black video frames when the live producer underruns.
//
// Per the contract (BlackFrameProducerContract.md):
// - Produces valid black frames at the PlayoutInstance's ProgramFormat
// - Produces no audio (silence)
// - PTS/DTS advance monotonically
// - Is NOT content and NOT scheduled
// - Used only when live producer runs out of frames
//
// This producer runs its own thread and writes to a FrameRingBuffer.
// It respects MasterClock for timing (real-time pacing in production,
// deterministic in tests).
class BlackFrameProducer : public retrovue::producers::IProducer {
 public:
  // Constructs a BlackFrameProducer with the given program format.
  // output_buffer: Ring buffer to write black frames to
  // format: Program format defining width, height, frame rate
  // clock: MasterClock for timing (nullable for tests)
  // initial_pts_us: Starting PTS in microseconds (for continuity)
  BlackFrameProducer(buffer::FrameRingBuffer& output_buffer,
                     const runtime::ProgramFormat& format,
                     std::shared_ptr<timing::MasterClock> clock = nullptr,
                     int64_t initial_pts_us = 0);

  ~BlackFrameProducer() override;

  // Disable copy and move
  BlackFrameProducer(const BlackFrameProducer&) = delete;
  BlackFrameProducer& operator=(const BlackFrameProducer&) = delete;

  // IProducer interface
  bool start() override;
  void stop() override;
  bool isRunning() const override;

  // Returns the number of black frames produced.
  uint64_t GetFramesProduced() const;

  // Returns the current PTS (what the next frame will have).
  int64_t GetCurrentPts() const;

  // Sets the PTS for the next frame (for continuity when entering fallback).
  // Must be called before start() or while stopped.
  void SetInitialPts(int64_t pts_us);

  // Sentinel asset_uri used by BlackFrameProducer.
  // Used by sinks/tests to identify black frames.
  static constexpr const char* kAssetUri = "internal://black";

 private:
  enum class State { STOPPED, RUNNING, STOPPING };

  // Main production loop (runs in producer thread).
  void ProduceLoop();

  // Generates a single black frame.
  void ProduceBlackFrame();

  // Program format (immutable after construction)
  runtime::ProgramFormat format_;
  int target_width_;
  int target_height_;
  double target_fps_;
  int64_t frame_interval_us_;

  // Output buffer reference
  buffer::FrameRingBuffer& output_buffer_;

  // Clock for timing
  std::shared_ptr<timing::MasterClock> master_clock_;

  // State management
  std::atomic<State> state_;
  std::atomic<bool> stop_requested_;
  std::atomic<uint64_t> frames_produced_;
  std::atomic<int64_t> next_pts_us_;

  // Producer thread
  std::unique_ptr<std::thread> producer_thread_;

  // Pre-allocated black frame data (YUV420)
  std::vector<uint8_t> black_frame_data_;
};

}  // namespace retrovue::producers::black

#endif  // RETROVUE_PRODUCERS_BLACK_BLACK_FRAME_PRODUCER_H_
