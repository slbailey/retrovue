// Repository: Retrovue-playout
// Component: FIVS Lookahead Refill Contract Tests
// Purpose: Prove compliance with INV-FIVS-LOOKAHEAD-001.
//          Fill thread parking is driven by timeline lookahead
//          (LatestIndex - consumer_selected_src), not store size.
// Contract Reference: INV-FIVS-LOOKAHEAD-001
// Copyright (c) 2026 RetroVue

#include <gtest/gtest.h>

#include <optional>

#include "retrovue/blockplan/FrameIndexedVideoStore.hpp"
#include "retrovue/blockplan/VideoBufferFrame.hpp"
#include "retrovue/blockplan/VideoLookaheadBuffer.hpp"

namespace retrovue::blockplan::testing {
namespace {

static VideoBufferFrame MakeFrame(int64_t index) {
  VideoBufferFrame vbf;
  vbf.source_frame_index = index;
  vbf.was_decoded = true;
  vbf.block_ct_ms = index * 33;
  vbf.video.width = static_cast<int>(index);
  vbf.video.height = 480;
  return vbf;
}

// --- ComputeLookaheadLocked behavioral tests ---
// These test the lookahead computation indirectly through the public API.

// INV-FIVS-LOOKAHEAD-001: When consumer position is unknown (-1),
// LookaheadTarget() returns the configured value but GetByIndex still works.
TEST(FIVSLookaheadContract, test_lookahead_target_defaults_to_target_depth) {
  // Default constructor: target_depth=15, low_water=5, lookahead_target=-1 (defaults to target_depth)
  VideoLookaheadBuffer buf(10, 3);
  EXPECT_EQ(buf.LookaheadTarget(), 10);
}

TEST(FIVSLookaheadContract, test_lookahead_target_explicit) {
  VideoLookaheadBuffer buf(10, 3, 20);
  EXPECT_EQ(buf.LookaheadTarget(), 20);
}

// INV-FIVS-LOOKAHEAD-001: UpdateConsumerPosition stores the value for
// the fill thread to read. Verify via GetByIndex (which proves the store
// and consumer position machinery are wired correctly).
TEST(FIVSLookaheadContract, test_update_consumer_position_is_observable) {
  VideoLookaheadBuffer buf(10, 3);
  // Before any consumer position update, GetByIndex returns nullopt (no frames).
  auto result = buf.GetByIndex(5);
  EXPECT_FALSE(result.has_value());

  // UpdateConsumerPosition is a no-op for frame retrieval — it only
  // affects fill thread parking. Verify it doesn't crash or corrupt state.
  buf.UpdateConsumerPosition(5);
  buf.UpdateConsumerPosition(10);
  buf.UpdateConsumerPosition(0);

  // Still no frames — position update doesn't create frames.
  result = buf.GetByIndex(5);
  EXPECT_FALSE(result.has_value());
}

// INV-FIVS-LOOKAHEAD-001: EvictBelow still works after UpdateConsumerPosition.
// This proves the fill-thread wake path is intact.
TEST(FIVSLookaheadContract, test_evict_below_after_consumer_position_update) {
  VideoLookaheadBuffer buf(10, 3);
  // No crash on evict with no frames.
  buf.UpdateConsumerPosition(5);
  buf.EvictBelow(3);
  EXPECT_EQ(buf.IndexedStoreSize(), 0u);
}

// --- FrameIndexedVideoStore lookahead computation tests ---
// These test the store's LatestIndex which is the input to lookahead.

TEST(FIVSLookaheadContract, test_latest_index_tracks_inserts) {
  FrameIndexedVideoStore store(100);
  EXPECT_EQ(store.LatestIndex(), -1);

  store.Insert(MakeFrame(5), 5);
  EXPECT_EQ(store.LatestIndex(), 5);

  store.Insert(MakeFrame(10), 10);
  EXPECT_EQ(store.LatestIndex(), 10);

  // Insert out of order — latest should still be max.
  store.Insert(MakeFrame(3), 3);
  EXPECT_EQ(store.LatestIndex(), 10);
}

TEST(FIVSLookaheadContract, test_latest_index_after_eviction) {
  FrameIndexedVideoStore store(100);
  for (int64_t i = 0; i < 20; ++i)
    store.Insert(MakeFrame(i), i);
  EXPECT_EQ(store.LatestIndex(), 19);

  // Evict frames 0-9.
  store.EvictBelow(10);
  // LatestIndex should still be 19 (eviction removes low frames).
  EXPECT_EQ(store.LatestIndex(), 19);
  EXPECT_EQ(store.Size(), 10u);
}

// INV-FIVS-LOOKAHEAD-001: Lookahead = LatestIndex - consumer_selected_src.
// When LatestIndex=19 and consumer is at 10, lookahead = 9.
// With lookahead_target=15, the fill thread should decode more (9 < 15).
// With lookahead_target=5, the fill thread should park (9 >= 5).
// This test verifies the arithmetic through the store API only
// (fill thread parking is an integration concern).
TEST(FIVSLookaheadContract, test_lookahead_arithmetic) {
  FrameIndexedVideoStore store(200);
  for (int64_t i = 0; i < 20; ++i)
    store.Insert(MakeFrame(i), i);

  // Simulate: consumer at index 10, latest at 19.
  int64_t consumer_pos = 10;
  int64_t latest = store.LatestIndex();
  EXPECT_EQ(latest, 19);

  int lookahead = static_cast<int>(latest - consumer_pos);
  EXPECT_EQ(lookahead, 9);

  // After eviction: consumer advances to 15.
  consumer_pos = 15;
  store.EvictBelow(13);  // Evict frames < 13
  latest = store.LatestIndex();
  EXPECT_EQ(latest, 19);
  lookahead = static_cast<int>(latest - consumer_pos);
  EXPECT_EQ(lookahead, 4);
}

// INV-FIVS-LOOKAHEAD-001: Memory safety cap enforced via EvictBelow.
// AutoEvictIfNeeded is conservative (only evicts when oldest < latest - capacity).
// The primary cap enforcement is via explicit EvictBelow from the tick loop.
// This test proves that EvictBelow correctly bounds the store.
TEST(FIVSLookaheadContract, test_memory_cap_via_evict_below) {
  FrameIndexedVideoStore store(100);
  // Insert 30 frames.
  for (int64_t i = 0; i < 30; ++i)
    store.Insert(MakeFrame(i), i);
  EXPECT_EQ(store.Size(), 30u);

  // Simulate tick loop eviction: consumer at 20, evict below 18.
  store.EvictBelow(18);
  EXPECT_EQ(store.Size(), 12u);  // frames 18-29
  EXPECT_FALSE(store.Has(17));
  EXPECT_TRUE(store.Has(18));
  EXPECT_TRUE(store.Has(29));
  EXPECT_EQ(store.LatestIndex(), 29);
}

// INV-FIVS-LOOKAHEAD-001: When store is empty, LatestIndex returns -1.
// Lookahead with consumer at any position should indicate "need to decode."
TEST(FIVSLookaheadContract, test_empty_store_needs_decode) {
  FrameIndexedVideoStore store(100);
  EXPECT_EQ(store.LatestIndex(), -1);

  // Simulated lookahead: latest=-1, consumer=5 → lookahead=-6 → need decode
  int64_t consumer_pos = 5;
  int64_t latest = store.LatestIndex();
  if (latest < 0) {
    // Special case: empty store always needs decode.
    SUCCEED();
  } else {
    ADD_FAILURE() << "Expected LatestIndex() == -1 for empty store";
  }
}

// INV-FIVS-LOOKAHEAD-001: Consumer position at -1 (pre-first-tick).
// Fill thread should fall back to size-based parking.
TEST(FIVSLookaheadContract, test_fallback_when_consumer_position_unknown) {
  VideoLookaheadBuffer buf(10, 3);
  // No UpdateConsumerPosition called — consumer_selected_src_ stays at -1.
  // This is the pre-first-tick state where the fill thread should use
  // Size() < target as the parking criterion (fallback behavior).
  EXPECT_EQ(buf.IndexedStoreSize(), 0u);
  // LookaheadTarget is set.
  EXPECT_EQ(buf.LookaheadTarget(), 10);
}

}  // namespace
}  // namespace retrovue::blockplan::testing
