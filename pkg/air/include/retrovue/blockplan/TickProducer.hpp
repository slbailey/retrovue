// Repository: Retrovue-playout
// Component: TickProducer
// Purpose: Encapsulates decoder lifecycle and frame-by-frame reading for a
//          single block. The engine owns time (tick counting); TickProducer
//          only decodes on demand.
//          Implements both IProducer (system-wide identity) and ITickProducer
//          (tick-driven methods for PipelineManager).
// Contract Reference: PlayoutAuthorityContract.md (P3.1a)
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_BLOCKPLAN_TICK_PRODUCER_HPP_
#define RETROVUE_BLOCKPLAN_TICK_PRODUCER_HPP_

#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/ITickProducer.hpp"
#include "retrovue/blockplan/RealAssetSource.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/producers/IProducer.h"

namespace retrovue::decode {
class FFmpegDecoder;
struct DecoderConfig;
}  // namespace retrovue::decode

namespace retrovue::blockplan {

// =============================================================================
// TickProducer — Active source for PipelineManager
//
// Dual inheritance:
//   retrovue::producers::IProducer  — system-wide producer identity
//   retrovue::blockplan::ITickProducer — tick-driven methods
//
// State machine:
//   EMPTY  →  READY  (AssignBlock)
//   READY  →  EMPTY  (Reset)
//
// EMPTY: No block assigned.  TryGetFrame() returns nullopt.
// READY: Block assigned.  Decoder may or may not be open (probe/open
//        failure → no decoder).  TryGetFrame() tries decode, returns
//        FrameData or nullopt.
//
// There is no EXHAUSTED state in TickProducer.  The engine manages the
// fence via live_ticks_ >= FramesPerBlock().
//
// IProducer semantics:
//   start()  — sets running_=true, clears stop_requested_. Returns true.
//   stop()   — calls Reset(), sets running_=false.
//   isRunning() — returns running_.
//   RequestStop() — sets stop_requested_=true.
//   IsStopped() — returns !running_.
//   start() is unconditional — does NOT depend on having a block assigned.
//   Readiness is GetState() == kReady (separate from running).
// =============================================================================

struct FrameData {
  buffer::Frame video;
  std::vector<buffer::AudioFrame> audio;  // 0-2 frames
  // P3.2: Metadata for seam verification
  std::string asset_uri;
  int64_t block_ct_ms = 0;  // CT before this frame's advance
};

class TickProducer : public producers::IProducer,
                     public ITickProducer {
 public:
  using State = ITickProducer::State;

  TickProducer(int width, int height, double fps);
  ~TickProducer() override;

  // --- ITickProducer ---
  void AssignBlock(const FedBlock& block) override;
  std::optional<FrameData> TryGetFrame() override;
  void Reset() override;
  State GetState() const override;
  const FedBlock& GetBlock() const override;
  int64_t FramesPerBlock() const override;
  bool HasDecoder() const override;
  double GetInputFPS() const override;

  // INV-BLOCK-PRIME-001/006: Decode first frame into held slot.
  // Called by ProducerPreloader::Worker after AssignBlock completes.
  void PrimeFirstFrame();

  // --- IProducer ---
  bool start() override;
  void stop() override;
  bool isRunning() const override;
  void RequestStop() override;
  bool IsStopped() const override;
  std::optional<producers::AsRunFrameStats> GetAsRunFrameStats() const override;

  // RequestStop flag — PipelineManager reads this to respect cooperative stop.
  bool IsStopRequested() const { return stop_requested_; }

 private:
  State state_ = State::kEmpty;
  FedBlock block_;
  int64_t frames_per_block_ = 0;

  // IProducer lifecycle
  bool running_ = false;
  bool stop_requested_ = false;

  // Decode state
  std::unique_ptr<decode::FFmpegDecoder> decoder_;
  std::string current_asset_uri_;
  int64_t next_frame_offset_ms_ = 0;
  realtime::RealAssetSource assets_;
  bool decoder_ok_ = false;

  // Segment boundary tracking
  ValidatedBlockPlan validated_;
  std::vector<SegmentBoundary> boundaries_;
  int32_t current_segment_index_ = 0;
  int64_t block_ct_ms_ = 0;

  int width_;
  int height_;
  double output_fps_;                     // Output fps (exact, for frames_per_block)
  int64_t frame_duration_ms_;            // Output frame duration (for fence/frames_per_block)
  double input_fps_ = 0.0;              // Detected input FPS (0 = unknown)
  int64_t input_frame_duration_ms_ = 0;  // Content advance per decode (matches input cadence)

  // INV-BLOCK-PRIME-001: Held first frame from PrimeFirstFrame().
  std::optional<FrameData> primed_frame_;
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_TICK_PRODUCER_HPP_
