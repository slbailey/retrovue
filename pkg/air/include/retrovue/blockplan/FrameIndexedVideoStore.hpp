// Repository: Retrovue-playout
// Component: FrameIndexedVideoStore (FIVS)
// Purpose: Indexed video frame store keyed by source_frame_index.
//          Replaces FIFO deque access pattern with O(1) lookup.
//          Passive data structure — does not decide which frame to emit.
// Contract Reference: docs/contracts/playout/frame_indexed_video_store.md
// Copyright (c) 2026 RetroVue

#ifndef RETROVUE_BLOCKPLAN_FRAME_INDEXED_VIDEO_STORE_HPP_
#define RETROVUE_BLOCKPLAN_FRAME_INDEXED_VIDEO_STORE_HPP_

#include <cstddef>
#include <cstdint>
#include <functional>
#include <optional>
#include <unordered_map>

#include "retrovue/blockplan/VideoBufferFrame.hpp"

namespace retrovue::blockplan {

// FrameIndexedVideoStore: a bounded, index-keyed store for decoded video frames.
//
// NOT internally synchronized. Caller (VideoLookaheadBuffer) provides locking.
//
// Contract: frame_indexed_video_store.md
//   - Storage by source_frame_index (one frame per index)
//   - Out-of-order insertion
//   - Non-destructive retrieval
//   - Duplicate policy: REPLACE
//   - Eviction: EvictBelow(min_requestable) removes only indices < min_requestable
//   - Capacity overflow: auto-evicts lowest index if lowest < latest - capacity
class FrameIndexedVideoStore {
 public:
  // Observer callbacks for diagnostics. All optional.
  struct Observer {
    std::function<void(int64_t index, size_t store_size)> on_insert;
    std::function<void(int64_t index)> on_hit;
    std::function<void(int64_t index)> on_miss;
    std::function<void(int64_t index)> on_evict;
    std::function<void(int64_t index)> on_duplicate;
  };

  explicit FrameIndexedVideoStore(size_t capacity = 200, Observer observer = {});

  // Insert frame at source_frame_index. Duplicate policy: REPLACE.
  // FIVS-DUPLICATE-POLICY: deterministic replacement.
  void Insert(VideoBufferFrame frame, int64_t source_frame_index);

  // Query presence without returning the frame.
  bool Has(int64_t index) const;

  // Retrieve frame by index. Returns nullptr if not present.
  // FIVS-ALIGN: never returns frame with index > requested.
  const VideoBufferFrame* Get(int64_t index) const;

  // Evict all frames with index < min_requestable.
  // FIVS-EVICTION-SAFETY: never removes a frame with index >= min_requestable.
  void EvictBelow(int64_t min_requestable);

  // Observability.
  size_t Size() const;
  int64_t LatestIndex() const;   // highest inserted index, or -1
  int64_t OldestIndex() const;   // lowest stored index, or -1
  bool Empty() const;

  void Clear();

  // FIVS-EVICTION-SAFETY: Set a floor below which auto-eviction will not remove.
  // Frames with index >= consumer_floor are protected from capacity-based eviction.
  // This prevents the fill thread from decoding past the consumer and evicting
  // frames the consumer still needs.
  void SetConsumerFloor(int64_t floor) { consumer_floor_ = floor; }
  int64_t ConsumerFloor() const { return consumer_floor_; }

 private:
  void AutoEvictIfNeeded();

  size_t capacity_;
  int64_t consumer_floor_ = -1;  // FIVS-EVICTION-SAFETY: auto-eviction floor
  Observer observer_;

  std::unordered_map<int64_t, VideoBufferFrame> frames_;

  // Track min/max for O(1) observability and eviction.
  int64_t latest_index_ = -1;
  int64_t oldest_index_ = -1;

  // Recompute oldest_index_ from the map (after eviction invalidates it).
  void RecomputeOldest();
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_FRAME_INDEXED_VIDEO_STORE_HPP_
