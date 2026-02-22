// Repository: Retrovue-playout
// Component: BlackFrameProducer
// Purpose: Internal failsafe producer that outputs valid black video frames.
// Contract: docs/contracts/architecture/BlackFrameProducerContract.md
// Copyright (c) 2025 RetroVue
//
// DEPRECATED for BlockPlan live playout.
// BlockPlan sessions use PadProducer (INV-PAD-PRODUCER) as the TAKE-selectable
// pad source, replacing BlackFrameProducer's failsafe role.  PadProducer provides
// both black video and silent audio through the same commitment path as content.
// This component remains active for legacy (non-BlockPlan) playout sessions
// where it serves as the dead-man failsafe on the ProducerBus live bus.

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
#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"

namespace retrovue::timing {
class MasterClock;
}

namespace retrovue::producers::black {

// BlackFrameProducer outputs valid black video frames for two purposes:
//
// 1. FAILSAFE MODE (unbounded): When live producer underruns, Air switches to
//    BlackFrameProducer until Core reasserts control. Duration is unbounded.
//
// 2. STRUCTURAL PADDING MODE (bounded): When Core specifies padding_frames,
//    the producer emits exactly that many frames and stops. Used for grid
//    reconciliation and frame-accurate editorial boundaries.
//
// Per the contract (BlackFrameProducerContract.md):
// - Produces valid black frames at the PlayoutInstance's ProgramFormat
// - Produces no audio (silence)
// - PTS/DTS advance monotonically
// - INV-PAD-EXACT-COUNT: When executing structural padding, emits exactly
//   the specified frame count, no more, no less.
//
// This producer runs its own thread and writes to a FrameRingBuffer.
// It respects MasterClock for timing (real-time pacing in production,
// deterministic in tests).
//
// DEPRECATED for BlockPlan live playout.  BlockPlan sessions use PadProducer
// (INV-PAD-PRODUCER) — a session-lifetime, zero-allocation, TAKE-selectable
// source that provides both black video and silent audio.  PadProducer
// participates in TAKE source selection at the commitment point rather than
// running as an independent threaded producer on a bus.
// Retained for legacy (non-BlockPlan) ProducerBus failsafe path.
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
  void RequestStop() override;
  bool IsStopped() const override;

  // Returns the number of black frames produced.
  uint64_t GetFramesProduced() const;

  // Returns the current PTS (what the next frame will have).
  int64_t GetCurrentPts() const;

  // Sets the PTS for the next frame (for continuity when entering fallback).
  // Must be called before start() or while stopped.
  void SetInitialPts(int64_t pts_us);

  // ==========================================================================
  // INV-PAD-EXACT-COUNT: Structural Padding Support
  // ==========================================================================
  // Sets the target frame count for structural padding.
  // When set (>= 0), the producer stops after emitting exactly this many frames.
  // When -1 (default), the producer runs indefinitely (failsafe mode).
  // Must be called before start().
  void SetTargetFrameCount(int64_t frame_count);

  // Returns the target frame count (-1 if unbounded/failsafe mode).
  int64_t GetTargetFrameCount() const;

  // Returns true if structural padding is complete (all frames emitted).
  // Only meaningful when target_frame_count >= 0.
  bool IsPaddingComplete() const;

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
  retrovue::blockplan::RationalFps target_fps_r_ = retrovue::blockplan::FPS_30;
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

  // INV-PAD-EXACT-COUNT: Target frame count for structural padding
  // -1 = unbounded (failsafe mode), >= 0 = bounded (structural padding)
  std::atomic<int64_t> target_frame_count_;

  // Producer thread
  std::unique_ptr<std::thread> producer_thread_;

  // Pre-allocated black frame data (YUV420)
  std::vector<uint8_t> black_frame_data_;
};

}  // namespace retrovue::producers::black

#endif  // RETROVUE_PRODUCERS_BLACK_BLACK_FRAME_PRODUCER_H_
