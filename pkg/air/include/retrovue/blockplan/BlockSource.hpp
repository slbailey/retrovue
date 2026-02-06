// Repository: Retrovue-playout
// Component: BlockSource
// Purpose: Encapsulates decoder lifecycle and frame-by-frame reading for a
//          single block. The engine owns time (tick counting); BlockSource
//          only decodes on demand.
// Contract Reference: PlayoutAuthorityContract.md (P3.1a)
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_BLOCKPLAN_BLOCK_SOURCE_HPP_
#define RETROVUE_BLOCKPLAN_BLOCK_SOURCE_HPP_

#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/RealTimeExecution.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"

namespace retrovue::decode {
class FFmpegDecoder;
struct DecoderConfig;
}  // namespace retrovue::decode

namespace retrovue::blockplan {

// =============================================================================
// BlockSource — Active source for ContinuousOutputExecutionEngine
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
// There is no EXHAUSTED state in BlockSource.  The engine manages the
// fence via source_ticks_ >= FramesPerBlock().
// =============================================================================

class BlockSource {
 public:
  enum class State { kEmpty, kReady };

  struct FrameData {
    buffer::Frame video;
    std::vector<buffer::AudioFrame> audio;  // 0-2 frames
    // P3.2: Metadata for seam verification
    std::string asset_uri;
    int64_t block_ct_ms = 0;  // CT before this frame's advance
  };

  BlockSource(int width, int height, double fps);
  ~BlockSource();

  // Assign a block.  Synchronous: probes assets, opens decoder, seeks.
  // Transitions: EMPTY → READY (always, even on probe failure).
  void AssignBlock(const FedBlock& block);

  // Try to decode the next frame for the current block position.
  // Non-blocking from the engine's perspective (decode is fast per-frame).
  // Returns FrameData if decoded, nullopt if decode failed (caller emits pad).
  // Advances internal segment position (block_ct_ms) by frame_duration_ms.
  // Does NOT track ticks — that's the engine's job.
  std::optional<FrameData> TryGetFrame();

  // Reset to EMPTY, releasing decoder and block state.
  void Reset();

  State GetState() const;
  const FedBlock& GetBlock() const;
  int64_t FramesPerBlock() const;
  bool HasDecoder() const;

 private:
  State state_ = State::kEmpty;
  FedBlock block_;
  int64_t frames_per_block_ = 0;

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
  int64_t frame_duration_ms_;
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_BLOCK_SOURCE_HPP_
