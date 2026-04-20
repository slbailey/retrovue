// AIR vNext — preview BufferStore instances (video + audio).
//
// Per-source preview buffers hold channel-canonical frames and audio blocks
// emitted by a Normalizer. They are BufferStore archetype conformers in the
// preview role: sole writer is their dedicated Normalizer; sole consumer
// is the emission path (post-promotion) or a test harness.
//
// Contract (from BufferStore archetype):
//   - Sole writer: Normalizer.
//   - Bounded capacity: Pushes above capacity are refused as overflow.
//   - Frontier observable: front/back PTS, depth.
//   - Underflow observable: pops against empty return nullopt + event count.
//   - No peer-state admission: buffer does not read other buffers' state.
//   - No directive emission: buffer reports; others decide.
//
// First-slice scope: single-threaded. Thread-safety contract can be added
// in a later slice when the fill-path and consumer run on different threads.
//
// Vault references:
//   - BufferStore (archetype)
//   - Truth - Source Time Is Producer-Local, Channel Time Is Canonical

#ifndef RETROVUE_AIR_PREVIEW_BUFFER_HPP_
#define RETROVUE_AIR_PREVIEW_BUFFER_HPP_

#include <cstdint>
#include <deque>
#include <optional>

#include "frame_types.hpp"

namespace retrovue::air {

// Observability counters for a preview buffer.
struct PreviewBufferObservability {
  int64_t total_pushed = 0;
  int64_t total_popped = 0;
  int64_t overflow_count = 0;   // Pushes refused due to bound.
  int64_t underflow_count = 0;  // Pops against empty.
};

class VideoPreviewBuffer {
 public:
  explicit VideoPreviewBuffer(int capacity_frames)
      : capacity_(capacity_frames) {}

  // Capacity in frames.
  int Capacity() const { return capacity_; }

  // Current depth in frames.
  int Depth() const { return static_cast<int>(frames_.size()); }

  // Push a frame onto the back of the buffer. Returns true on accept,
  // false on refusal (overflow). Overflow increments the counter.
  bool Push(VideoFrame frame);

  // Pop the front frame. Returns nullopt on underflow (empty buffer);
  // underflow increments the counter.
  std::optional<VideoFrame> Pop();

  // Relative PTS of the front frame, if any.
  std::optional<int64_t> FrontPtsUsRelative() const;

  // Relative PTS of the back frame, if any.
  std::optional<int64_t> BackPtsUsRelative() const;

  // Observability snapshot (copy-by-value).
  PreviewBufferObservability Observability() const { return obs_; }

 private:
  int capacity_;
  std::deque<VideoFrame> frames_;
  PreviewBufferObservability obs_;
};

class AudioPreviewBuffer {
 public:
  explicit AudioPreviewBuffer(int capacity_blocks)
      : capacity_(capacity_blocks) {}

  int Capacity() const { return capacity_; }

  int Depth() const { return static_cast<int>(blocks_.size()); }

  bool Push(AudioBlock block);

  std::optional<AudioBlock> Pop();

  std::optional<int64_t> FrontPtsUsRelative() const;

  std::optional<int64_t> BackPtsUsRelative() const;

  PreviewBufferObservability Observability() const { return obs_; }

 private:
  int capacity_;
  std::deque<AudioBlock> blocks_;
  PreviewBufferObservability obs_;
};

}  // namespace retrovue::air

#endif  // RETROVUE_AIR_PREVIEW_BUFFER_HPP_
