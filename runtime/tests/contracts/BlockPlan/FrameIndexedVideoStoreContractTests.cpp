// Repository: Retrovue-playout
// Component: FrameIndexedVideoStore (FIVS) Contract Tests
// Purpose: Prove compliance with frame_indexed_video_store.md §10.
//          12 tests matching the contract's required test matrix.
// Contract Reference: docs/contracts/playout/frame_indexed_video_store.md
// Copyright (c) 2026 RetroVue

#include <gtest/gtest.h>

#include <string>
#include <vector>

#include "retrovue/blockplan/FrameIndexedVideoStore.hpp"
#include "retrovue/blockplan/VideoBufferFrame.hpp"

namespace retrovue::blockplan::testing {
namespace {

// Helper: create a VideoBufferFrame with a given source_frame_index and
// a distinguishable payload (width encodes the index for verification).
static VideoBufferFrame MakeFrame(int64_t index) {
  VideoBufferFrame vbf;
  vbf.source_frame_index = index;
  vbf.was_decoded = true;
  vbf.block_ct_ms = index * 33;  // distinguishable per-frame
  vbf.video.width = static_cast<int>(index);  // encode index in width for verification
  vbf.video.height = 480;
  return vbf;
}

// =========================================================================
// §3/§4 Outcome A: test_retrieve_exact_frame
// Insert frame at index 5, Get(5) returns it.
// =========================================================================
TEST(FrameIndexedVideoStoreContract, test_retrieve_exact_frame) {
  FrameIndexedVideoStore store(200);
  store.Insert(MakeFrame(5), 5);

  const VideoBufferFrame* result = store.Get(5);
  ASSERT_NE(result, nullptr);
  EXPECT_EQ(result->source_frame_index, 5);
  EXPECT_EQ(result->video.width, 5);
}

// =========================================================================
// §4 Outcomes B/C: test_retrieve_missing_frame
// Get(99) on empty/sparse store returns nullptr.
// =========================================================================
TEST(FrameIndexedVideoStoreContract, test_retrieve_missing_frame) {
  FrameIndexedVideoStore store(200);
  // Empty store.
  EXPECT_EQ(store.Get(99), nullptr);

  // Sparse store (has index 5 but not 99).
  store.Insert(MakeFrame(5), 5);
  EXPECT_EQ(store.Get(99), nullptr);
  // Also verify Get(5) still works after miss.
  EXPECT_NE(store.Get(5), nullptr);
}

// =========================================================================
// §5 FIVS-ALIGN: test_no_future_frame_emission
// Get(N) never returns a frame with index > N.
// =========================================================================
TEST(FrameIndexedVideoStoreContract, test_no_future_frame_emission) {
  FrameIndexedVideoStore store(200);
  // Insert frames at indices 5, 10, 15.
  store.Insert(MakeFrame(5), 5);
  store.Insert(MakeFrame(10), 10);
  store.Insert(MakeFrame(15), 15);

  // Request index 7 (between 5 and 10). Must not return index 10.
  const VideoBufferFrame* result = store.Get(7);
  EXPECT_EQ(result, nullptr);  // 7 not stored — must be nullptr, not 10.

  // Request index 5. Must return exactly 5.
  result = store.Get(5);
  ASSERT_NE(result, nullptr);
  EXPECT_EQ(result->source_frame_index, 5);

  // Request index 3 (below all). Must not return any frame.
  result = store.Get(3);
  EXPECT_EQ(result, nullptr);
}

// =========================================================================
// §3/§4: test_decoder_ahead_frames_available
// Insert indices 0-10, Get(3) returns frame 3.
// =========================================================================
TEST(FrameIndexedVideoStoreContract, test_decoder_ahead_frames_available) {
  FrameIndexedVideoStore store(200);
  for (int64_t i = 0; i <= 10; ++i) {
    store.Insert(MakeFrame(i), i);
  }

  const VideoBufferFrame* result = store.Get(3);
  ASSERT_NE(result, nullptr);
  EXPECT_EQ(result->source_frame_index, 3);
  EXPECT_EQ(result->video.width, 3);
}

// =========================================================================
// §8: test_decoder_behind_frame_missing
// Insert 0-5, Get(10) returns nullptr.
// =========================================================================
TEST(FrameIndexedVideoStoreContract, test_decoder_behind_frame_missing) {
  FrameIndexedVideoStore store(200);
  for (int64_t i = 0; i <= 5; ++i) {
    store.Insert(MakeFrame(i), i);
  }

  EXPECT_EQ(store.Get(10), nullptr);
  EXPECT_EQ(store.Size(), 6u);  // no side effect on stored frames
}

// =========================================================================
// §3: test_out_of_order_insert_retrieve
// Insert 5, 2, 8, 1 — retrieve each by index.
// =========================================================================
TEST(FrameIndexedVideoStoreContract, test_out_of_order_insert_retrieve) {
  FrameIndexedVideoStore store(200);
  store.Insert(MakeFrame(5), 5);
  store.Insert(MakeFrame(2), 2);
  store.Insert(MakeFrame(8), 8);
  store.Insert(MakeFrame(1), 1);

  for (int64_t idx : {1, 2, 5, 8}) {
    const VideoBufferFrame* result = store.Get(idx);
    ASSERT_NE(result, nullptr) << "Missing frame at index " << idx;
    EXPECT_EQ(result->source_frame_index, idx);
  }
}

// =========================================================================
// §3: test_retrieval_does_not_remove_others
// Insert A=10, B=20, C=30. Get(B). A and C still retrievable.
// =========================================================================
TEST(FrameIndexedVideoStoreContract, test_retrieval_does_not_remove_others) {
  FrameIndexedVideoStore store(200);
  store.Insert(MakeFrame(10), 10);
  store.Insert(MakeFrame(20), 20);
  store.Insert(MakeFrame(30), 30);

  // Retrieve B.
  const VideoBufferFrame* b = store.Get(20);
  ASSERT_NE(b, nullptr);
  EXPECT_EQ(b->source_frame_index, 20);

  // A and C must still be present.
  EXPECT_NE(store.Get(10), nullptr);
  EXPECT_NE(store.Get(30), nullptr);
  EXPECT_EQ(store.Size(), 3u);
}

// =========================================================================
// §6: test_duplicate_index_policy
// Insert two frames at index 3; second replaces first.
// =========================================================================
TEST(FrameIndexedVideoStoreContract, test_duplicate_index_policy) {
  bool duplicate_fired = false;
  FrameIndexedVideoStore::Observer obs;
  obs.on_duplicate = [&](int64_t index) {
    EXPECT_EQ(index, 3);
    duplicate_fired = true;
  };

  FrameIndexedVideoStore store(200, obs);

  // First insert: block_ct_ms = 99 (first frame).
  VideoBufferFrame first = MakeFrame(3);
  first.block_ct_ms = 99;
  store.Insert(std::move(first), 3);

  // Second insert: block_ct_ms = 200 (replacement frame).
  VideoBufferFrame second = MakeFrame(3);
  second.block_ct_ms = 200;
  store.Insert(std::move(second), 3);

  EXPECT_TRUE(duplicate_fired);

  // Only one frame for index 3, and it's the replacement.
  const VideoBufferFrame* result = store.Get(3);
  ASSERT_NE(result, nullptr);
  EXPECT_EQ(result->block_ct_ms, 200);  // second frame
  EXPECT_EQ(store.Size(), 1u);
}

// =========================================================================
// §7: test_eviction_never_removes_requestable
// Set min_requestable, fill past capacity, verify min_requestable still present.
// =========================================================================
TEST(FrameIndexedVideoStoreContract, test_eviction_never_removes_requestable) {
  // Small capacity to trigger eviction.
  FrameIndexedVideoStore store(10);

  // Insert frames 0-19 (exceeds capacity of 10).
  for (int64_t i = 0; i < 20; ++i) {
    store.Insert(MakeFrame(i), i);
  }

  // Set min_requestable = 15; evict below.
  store.EvictBelow(15);

  // Frames 15-19 must still be present.
  for (int64_t i = 15; i < 20; ++i) {
    EXPECT_TRUE(store.Has(i)) << "Frame " << i << " should be present after EvictBelow(15)";
  }

  // Frames < 15 must be gone.
  for (int64_t i = 0; i < 15; ++i) {
    EXPECT_FALSE(store.Has(i)) << "Frame " << i << " should be evicted by EvictBelow(15)";
  }
}

// =========================================================================
// §7: test_retrieve_after_eviction_boundary
// Insert 100-200, set min_requestable=140, evict, verify boundary.
// =========================================================================
TEST(FrameIndexedVideoStoreContract, test_retrieve_after_eviction_boundary) {
  FrameIndexedVideoStore store(200);

  for (int64_t i = 100; i <= 200; ++i) {
    store.Insert(MakeFrame(i), i);
  }

  store.EvictBelow(140);

  // Frame 140 must be retrievable (boundary).
  const VideoBufferFrame* at_boundary = store.Get(140);
  ASSERT_NE(at_boundary, nullptr);
  EXPECT_EQ(at_boundary->source_frame_index, 140);

  // Frame 139 must NOT be retrievable (below boundary).
  EXPECT_EQ(store.Get(139), nullptr);

  // Frame 150 must be retrievable (above boundary).
  EXPECT_NE(store.Get(150), nullptr);

  // Frame 200 must be retrievable (highest).
  EXPECT_NE(store.Get(200), nullptr);
}

// =========================================================================
// §8: test_store_empty_returns_not_present
// Empty store, any Get returns nullptr.
// =========================================================================
TEST(FrameIndexedVideoStoreContract, test_store_empty_returns_not_present) {
  FrameIndexedVideoStore store(200);

  EXPECT_TRUE(store.Empty());
  EXPECT_EQ(store.Size(), 0u);
  EXPECT_EQ(store.Get(0), nullptr);
  EXPECT_EQ(store.Get(1), nullptr);
  EXPECT_EQ(store.Get(-1), nullptr);
  EXPECT_EQ(store.Get(999), nullptr);
  EXPECT_FALSE(store.Has(0));
}

// =========================================================================
// §9: test_observability_events
// Verify INSERT/HIT/MISS/EVICT/DUPLICATE callbacks fire.
// =========================================================================
TEST(FrameIndexedVideoStoreContract, test_observability_events) {
  int insert_count = 0;
  int hit_count = 0;
  int miss_count = 0;
  int evict_count = 0;
  int duplicate_count = 0;

  FrameIndexedVideoStore::Observer obs;
  obs.on_insert = [&](int64_t, size_t) { insert_count++; };
  obs.on_hit = [&](int64_t) { hit_count++; };
  obs.on_miss = [&](int64_t) { miss_count++; };
  obs.on_evict = [&](int64_t) { evict_count++; };
  obs.on_duplicate = [&](int64_t) { duplicate_count++; };

  FrameIndexedVideoStore store(200, obs);

  // INSERT event.
  store.Insert(MakeFrame(1), 1);
  EXPECT_EQ(insert_count, 1);

  // DUPLICATE event (re-insert at same index fires both duplicate + insert).
  store.Insert(MakeFrame(1), 1);
  EXPECT_EQ(duplicate_count, 1);
  EXPECT_EQ(insert_count, 2);  // insert fires on duplicate too

  // HIT event.
  store.Get(1);
  EXPECT_EQ(hit_count, 1);

  // MISS event.
  store.Get(99);
  EXPECT_EQ(miss_count, 1);

  // EVICT event.
  store.Insert(MakeFrame(5), 5);
  store.EvictBelow(5);
  EXPECT_GE(evict_count, 1);  // at least index 1 evicted
}

}  // namespace
}  // namespace retrovue::blockplan::testing
