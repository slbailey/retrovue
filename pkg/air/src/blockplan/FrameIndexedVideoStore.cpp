// Repository: Retrovue-playout
// Component: FrameIndexedVideoStore (FIVS)
// Purpose: Indexed video frame store keyed by source_frame_index.
// Contract Reference: docs/contracts/playout/frame_indexed_video_store.md
// Copyright (c) 2026 RetroVue

#include "retrovue/blockplan/FrameIndexedVideoStore.hpp"

#include <algorithm>
#include <limits>

namespace retrovue::blockplan {

FrameIndexedVideoStore::FrameIndexedVideoStore(size_t capacity, Observer observer)
    : capacity_(capacity > 0 ? capacity : 200), observer_(std::move(observer)) {}

void FrameIndexedVideoStore::Insert(VideoBufferFrame frame, int64_t source_frame_index) {
  auto it = frames_.find(source_frame_index);
  if (it != frames_.end()) {
    // FIVS-DUPLICATE-POLICY: REPLACE existing frame.
    if (observer_.on_duplicate) {
      observer_.on_duplicate(source_frame_index);
    }
    it->second = std::move(frame);
  } else {
    // Capacity check before insertion.
    AutoEvictIfNeeded();

    frames_.emplace(source_frame_index, std::move(frame));

    // Update tracking.
    if (latest_index_ < 0 || source_frame_index > latest_index_) {
      latest_index_ = source_frame_index;
    }
    if (oldest_index_ < 0 || source_frame_index < oldest_index_) {
      oldest_index_ = source_frame_index;
    }
  }

  if (observer_.on_insert) {
    observer_.on_insert(source_frame_index, frames_.size());
  }
}

bool FrameIndexedVideoStore::Has(int64_t index) const {
  return frames_.count(index) > 0;
}

const VideoBufferFrame* FrameIndexedVideoStore::Get(int64_t index) const {
  // FIVS-ALIGN: only return a frame whose index == requested index.
  // By using exact-key lookup, we structurally guarantee no frame with
  // index > requested is ever returned.
  auto it = frames_.find(index);
  if (it != frames_.end()) {
    if (observer_.on_hit) {
      observer_.on_hit(index);
    }
    return &it->second;
  }
  if (observer_.on_miss) {
    observer_.on_miss(index);
  }
  return nullptr;
}

void FrameIndexedVideoStore::EvictBelow(int64_t min_requestable) {
  // FIVS-EVICTION-SAFETY: only remove frames with index < min_requestable.
  for (auto it = frames_.begin(); it != frames_.end(); ) {
    if (it->first < min_requestable) {
      if (observer_.on_evict) {
        observer_.on_evict(it->first);
      }
      it = frames_.erase(it);
    } else {
      ++it;
    }
  }

  // Update oldest_index_ after eviction.
  if (frames_.empty()) {
    oldest_index_ = -1;
    latest_index_ = -1;
  } else {
    RecomputeOldest();
  }
}

size_t FrameIndexedVideoStore::Size() const {
  return frames_.size();
}

int64_t FrameIndexedVideoStore::LatestIndex() const {
  return latest_index_;
}

int64_t FrameIndexedVideoStore::OldestIndex() const {
  return oldest_index_;
}

bool FrameIndexedVideoStore::Empty() const {
  return frames_.empty();
}

void FrameIndexedVideoStore::Clear() {
  frames_.clear();
  latest_index_ = -1;
  oldest_index_ = -1;
}

void FrameIndexedVideoStore::AutoEvictIfNeeded() {
  // Only auto-evict when at capacity and the lowest index is safely behind.
  if (frames_.size() < capacity_) return;
  if (oldest_index_ < 0 || latest_index_ < 0) return;

  // FIVS-EVICTION-SAFETY: Never evict frames the consumer still needs.
  // consumer_floor_ is set by UpdateConsumerPosition via SetConsumerFloor.
  if (consumer_floor_ >= 0 && oldest_index_ >= consumer_floor_) return;

  // Safety: only evict the oldest if it's more than capacity behind the latest.
  // This prevents evicting frames that may still be requestable.
  if (oldest_index_ < latest_index_ - static_cast<int64_t>(capacity_)) {
    auto it = frames_.find(oldest_index_);
    if (it != frames_.end()) {
      if (observer_.on_evict) {
        observer_.on_evict(oldest_index_);
      }
      frames_.erase(it);
      RecomputeOldest();
    }
  }
}

void FrameIndexedVideoStore::RecomputeOldest() {
  if (frames_.empty()) {
    oldest_index_ = -1;
    return;
  }
  int64_t min_idx = std::numeric_limits<int64_t>::max();
  for (const auto& [idx, _] : frames_) {
    if (idx < min_idx) min_idx = idx;
  }
  oldest_index_ = min_idx;
}

}  // namespace retrovue::blockplan
