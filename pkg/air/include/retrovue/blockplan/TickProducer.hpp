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
#include <deque>
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
  bool HasPrimedFrame() const override;
  const std::vector<SegmentBoundary>& GetBoundaries() const override;

  void SetInterruptFlags(const ITickProducer::InterruptFlags&) override;

  // INV-BLOCK-PRIME-001/006: Decode first frame into held slot.
  // Called by ProducerPreloader::Worker after AssignBlock completes.
  void PrimeFirstFrame();

  // INV-AUDIO-PRIME-001: Decode first frame + enough audio to meet threshold.
  // Calls PrimeFirstFrame internally, then continues decoding until audio
  // depth accumulated in primed_frame_.audio >= min_audio_prime_ms.
  // Additional video frames are buffered internally and returned by
  // subsequent TryGetFrame() calls (non-blocking, before live decode).
  //
  // Returns: {met_threshold, actual_depth_ms}.
  //   met_threshold: true if audio depth >= min_audio_prime_ms (or <= 0).
  //   actual_depth_ms: accumulated audio in ms (0 if no primed frame).
  struct PrimeResult {
    bool met_threshold = false;
    int actual_depth_ms = 0;
  };
  PrimeResult PrimeFirstTick(int min_audio_prime_ms);

  // Segment identity when this producer is built for a single-segment mini plan.
  // Set by SeamPreparer so seam frame math uses the parent block's segment index.
  void SetLogicalSegmentIndex(int32_t index);

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
  ITickProducer::InterruptFlags interrupt_flags_;
  std::string current_asset_uri_;
  int64_t next_frame_offset_ms_ = 0;
  realtime::RealAssetSource assets_;
  bool decoder_ok_ = false;

  // Segment boundary tracking
  ValidatedBlockPlan validated_;
  std::vector<SegmentBoundary> boundaries_;
  int32_t current_segment_index_ = 0;
  int32_t logical_segment_index_ = 0;  // Parent block segment index (SetLogicalSegmentIndex)
  int64_t block_ct_ms_ = 0;

  int width_;
  int height_;
  double output_fps_;                     // Output fps (exact, for frames_per_block)
  int64_t frame_duration_ms_;            // Output frame duration (for fence/frames_per_block)
  double input_fps_ = 0.0;              // Detected input FPS (0 = unknown)
  int64_t input_frame_duration_ms_ = 0;  // Content advance per decode (matches input cadence)

  // INV-BLOCK-PRIME-001: Held first frame from PrimeFirstFrame().
  // Audio vector contains only this frame's own decoded audio (0-2 frames).
  // Subsequent frames' audio stays with their FrameData in buffered_frames_.
  std::optional<FrameData> primed_frame_;

  // INV-AUDIO-PRIME-001: Buffered frames from PrimeFirstTick audio priming.
  // TryGetFrame returns these (FIFO) after primed_frame_, before live decode.
  // Each frame retains its own decoded audio.
  std::deque<FrameData> buffered_frames_;

  // Planned PAD segment support — pre-allocated pad frames (black+silence).
  // Constructed once in AssignBlock if block contains PAD segments.
  bool has_pad_segments_ = false;
  buffer::Frame pad_video_frame_;
  int pad_audio_samples_per_frame_ = 0;

  void InitPadFrames();
  std::optional<FrameData> GeneratePadFrame();

  // Decode-only frame advancement.  Advances the decoder exactly one frame,
  // extracts pending audio, advances CT based on decoded PTS.
  // Does NOT inspect or mutate primed_frame_ or buffered_frames_.
  // Returns nullopt on EOF, decode failure, or decoder_ok_ == false.
  // For PAD segments: returns GeneratePadFrame() (no decode needed).
  std::optional<FrameData> DecodeNextFrameRaw();

  // REMOVED: AdvanceToNextSegment() — reactive segment advancement replaced by
  // eager overlap via SeamPreparer.  See INV-SEAM-SEG-001..006.

  // INV-PTS-ANCHOR-RESET: First decoded PTS (ms) of the current segment.
  // Set to -1 on segment switch / reset; captured from the first decoded
  // frame.  PTS anchoring uses (decoded_pts_ms - seg_first_pts_ms_) as the
  // relative offset, so a new segment's PTS origin cannot corrupt the
  // snapped block_ct_ms_.
  int64_t seg_first_pts_ms_ = -1;

  // Monotonic counter: incremented each time a segment decoder is opened.
  // Logged for correlation across segment transitions.
  int32_t open_generation_ = 0;
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_TICK_PRODUCER_HPP_
