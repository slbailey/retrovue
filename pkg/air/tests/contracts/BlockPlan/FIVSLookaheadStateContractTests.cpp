// Repository: Retrovue-playout
// Component: FIVS Lookahead State Contract Tests
// Purpose: Prove compliance with INV-FIVS-LOOKAHEAD-STATE-001.
//          The fill loop must distinguish between:
//            - consumer_not_started: requested frame is invalid/unset
//            - consumer_active_decoder_behind: requested frame is valid,
//              highest_decoded_frame < consumer_requested_frame
//          Negative lookahead is decoder-behind, not bootstrap.
// Contract Reference: INV-FIVS-LOOKAHEAD-STATE-001
// Copyright (c) 2026 RetroVue

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <cstring>
#include <mutex>
#include <optional>
#include <thread>
#include <vector>

#include "retrovue/blockplan/ITickProducer.hpp"
#include "retrovue/blockplan/TickProducer.hpp"
#include "retrovue/blockplan/VideoBufferFrame.hpp"
#include "retrovue/blockplan/VideoLookaheadBuffer.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"

namespace retrovue::blockplan::testing {
namespace {

static buffer::Frame MakeVideoFrame(int width, int height, uint8_t y_fill = 0x10) {
  buffer::Frame frame;
  frame.width = width;
  frame.height = height;
  int y_size = width * height;
  int uv_size = (width / 2) * (height / 2);
  frame.data.resize(static_cast<size_t>(y_size + 2 * uv_size));
  std::memset(frame.data.data(), y_fill, static_cast<size_t>(y_size));
  std::memset(frame.data.data() + y_size, 0x80, static_cast<size_t>(2 * uv_size));
  return frame;
}

// Producer that sets source_frame_index on every frame.
// Configurable decode delay for timing-sensitive tests.
class StateTestProducer : public ITickProducer {
 public:
  StateTestProducer(int total_frames, std::chrono::microseconds decode_delay = {})
      : frames_remaining_(total_frames),
        total_frames_(total_frames),
        decode_delay_(decode_delay) {}

  void AssignBlock(const FedBlock& block) override { block_ = block; }

  std::optional<FrameData> TryGetFrame() override {
    std::lock_guard<std::mutex> lock(mutex_);
    if (frames_remaining_ <= 0) return std::nullopt;

    if (decode_delay_.count() > 0) {
      mutex_.unlock();
      std::this_thread::sleep_for(decode_delay_);
      mutex_.lock();
      if (frames_remaining_ <= 0) return std::nullopt;
    }

    frames_remaining_--;
    int64_t index = total_frames_ - frames_remaining_ - 1;

    FrameData fd;
    fd.video = MakeVideoFrame(64, 48, static_cast<uint8_t>(0x10 + (index % 200)));
    fd.asset_uri = "state_test.mp4";
    fd.block_ct_ms = index * 33;
    fd.source_frame_index = index;
    return fd;
  }

  void Reset() override {
    std::lock_guard<std::mutex> lock(mutex_);
    frames_remaining_ = 0;
  }

  State GetState() const override { return State::kReady; }
  const FedBlock& GetBlock() const override { return block_; }
  int64_t FramesPerBlock() const override { return total_frames_; }
  bool HasDecoder() const override { return true; }
  RationalFps GetInputRationalFps() const override { return FPS_30; }
  bool HasPrimedFrame() const override { return false; }
  const std::vector<SegmentBoundary>& GetBoundaries() const override {
    static const std::vector<SegmentBoundary> empty;
    return empty;
  }

 private:
  mutable std::mutex mutex_;
  int frames_remaining_;
  int total_frames_;
  FedBlock block_;
  std::chrono::microseconds decode_delay_;
};

template <typename Pred>
static bool WaitFor(Pred pred, std::chrono::milliseconds timeout) {
  auto deadline = std::chrono::steady_clock::now() + timeout;
  while (!pred()) {
    if (std::chrono::steady_clock::now() > deadline) return false;
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
  return true;
}

// ---------------------------------------------------------------------------
// Test 1 — Consumer unset → bootstrap/size fallback allowed
//
// INV-FIVS-LOOKAHEAD-STATE-001 R1: When consumer_requested_frame is
// unset (-1), size-based parking is the correct fallback.
//
// Start fill thread without calling UpdateConsumerPosition.
// The fill thread should fill to target_depth_frames_ then park.
// This is the ONLY situation where size-based parking is correct.
// ---------------------------------------------------------------------------
TEST(FIVSLookaheadStateContract, test_consumer_unset_allows_size_fallback) {
  const int target_depth = 15;
  const int lookahead_target = 10;
  VideoLookaheadBuffer buf(target_depth, 5, lookahead_target);
  StateTestProducer producer(500);
  std::atomic<bool> stop{false};

  // Do NOT call UpdateConsumerPosition — consumer stays at -1.
  buf.StartFilling(&producer, nullptr, FPS_30, FPS_30, &stop);

  // Fill thread should fill to target and park.
  ASSERT_TRUE(WaitFor(
      [&] { return buf.IndexedStoreSize() >= static_cast<size_t>(target_depth); },
      std::chrono::milliseconds(2000)))
      << "Fill thread did not fill to target_depth";

  // Wait a bit more to confirm it parked (not unbounded filling).
  std::this_thread::sleep_for(std::chrono::milliseconds(100));
  const size_t size_after_park = buf.IndexedStoreSize();

  // Store should be near target, not at hard cap.
  // Allow some slack (condvar timeout might let 1-2 extra through).
  EXPECT_LE(size_after_park, static_cast<size_t>(target_depth + 5))
      << "Fill thread should park near target when consumer is unset, not fill unboundedly";

  buf.StopFilling(true);
}

// ---------------------------------------------------------------------------
// Test 2 — Consumer valid, positive lookahead → park allowed
//
// INV-FIVS-LOOKAHEAD-STATE-001 R2: When consumer is valid and
// lookahead >= lookahead_target, the fill thread parks.
// ---------------------------------------------------------------------------
TEST(FIVSLookaheadStateContract, test_consumer_valid_positive_lookahead_parks) {
  const int lookahead_target = 10;
  VideoLookaheadBuffer buf(15, 5, lookahead_target);
  StateTestProducer producer(500);
  std::atomic<bool> stop{false};

  buf.StartFilling(&producer, nullptr, FPS_30, FPS_30, &stop);

  // Wait for initial fill.
  ASSERT_TRUE(WaitFor(
      [&] { return buf.IndexedStoreSize() >= 15u; },
      std::chrono::milliseconds(2000)));

  // Set consumer at 0. Lookahead = ~14 - 0 = 14 >= 10. Should park.
  buf.UpdateConsumerPosition(0);
  std::this_thread::sleep_for(std::chrono::milliseconds(200));

  const size_t size_after = buf.IndexedStoreSize();
  // Should not have decoded much more — fill thread parked.
  // (Might decode a few more due to condvar timing, but not hundreds.)
  EXPECT_LT(size_after, 50u)
      << "Fill thread should park when lookahead >= target, not decode unboundedly";

  buf.StopFilling(true);
}

// ---------------------------------------------------------------------------
// Test 3 — Consumer valid, small positive lookahead → burst decode
//
// INV-FIVS-LOOKAHEAD-STATE-001 R3: When consumer is valid and
// 0 <= lookahead < lookahead_target, the fill thread must burst-decode
// until the horizon is restored.
// ---------------------------------------------------------------------------
TEST(FIVSLookaheadStateContract, test_consumer_valid_small_lookahead_decodes) {
  const int lookahead_target = 10;
  VideoLookaheadBuffer buf(15, 5, lookahead_target);
  // 1ms decode delay — can decode 200+ frames in 200ms if awake.
  StateTestProducer producer(500, std::chrono::microseconds(1000));
  std::atomic<bool> stop{false};

  buf.StartFilling(&producer, nullptr, FPS_30, FPS_30, &stop);

  // Wait for initial fill to ~15 frames.
  ASSERT_TRUE(WaitFor(
      [&] { return buf.IndexedStoreSize() >= 15u; },
      std::chrono::milliseconds(2000)));

  // Set consumer at frame 10. Lookahead = ~14 - 10 = 4 < 10.
  // Fill thread must burst-decode to restore horizon.
  buf.UpdateConsumerPosition(10);
  std::this_thread::sleep_for(std::chrono::milliseconds(200));

  // After 200ms, fill thread should have decoded enough that
  // GetByIndex(10 + lookahead_target) succeeds.
  auto frame = buf.GetByIndex(10 + lookahead_target);
  EXPECT_TRUE(frame.has_value())
      << "INV-FIVS-LOOKAHEAD-STATE-001: Fill thread did not burst-decode "
      << "when lookahead was below target (small positive lookahead)";

  buf.StopFilling(true);
}

// ---------------------------------------------------------------------------
// Test 4 — Consumer valid, negative lookahead → MUST decode immediately
//
// INV-FIVS-LOOKAHEAD-STATE-001 R3, R4: When consumer is valid and
// lookahead < 0 (decoder behind), the fill thread must decode immediately.
// It must NOT fall back to size-based parking.
//
// THIS TEST PROVES THE BUG: With the buggy code, negative lookahead is
// treated as "consumer not started" → size fallback → fill thread parks
// (because store has >= target frames from initial fill) → GetByIndex
// returns nullopt.
//
// With the fix: negative lookahead correctly evaluates as la < target
// → fill thread wakes and burst-decodes → GetByIndex succeeds.
// ---------------------------------------------------------------------------
TEST(FIVSLookaheadStateContract, test_consumer_valid_negative_lookahead_decodes) {
  const int lookahead_target = 10;
  const int target_depth = 15;
  VideoLookaheadBuffer buf(target_depth, 5, lookahead_target);
  // 1ms decode delay: ~200 frames in 200ms if awake, 0 if parked.
  StateTestProducer producer(500, std::chrono::microseconds(1000));
  std::atomic<bool> stop{false};

  buf.StartFilling(&producer, nullptr, FPS_30, FPS_30, &stop);

  // Wait for fill thread to reach target depth. It parks here
  // (consumer unset → size fallback, which is correct per R1).
  ASSERT_TRUE(WaitFor(
      [&] { return buf.IndexedStoreSize() >= static_cast<size_t>(target_depth); },
      std::chrono::milliseconds(2000)))
      << "Fill thread did not fill to target";

  // Record what the fill thread decoded. LatestIndex is ~14.
  // Store has ~15 frames (>= target_depth_frames_).

  // Jump consumer to frame 30 — way past the decoder.
  // Lookahead = ~14 - 30 = -16 (deeply negative).
  // Store still has ~15 frames >= target_depth (15).
  //
  // BUG: `la < 0` triggers size fallback. Size (15) >= target (15).
  //      Predicate returns false. Fill thread stays parked.
  //
  // FIX: `la == kLookaheadConsumerUnknown` distinguishes states.
  //      la = -16 ≠ INT_MIN. `la < lookahead_target_` → -16 < 10 → true.
  //      Fill thread wakes and burst-decodes.
  buf.UpdateConsumerPosition(30);

  // Wait 300ms: enough for condvar timeout (100ms) + decode time.
  // If fill thread wakes: decodes from ~15 to ~270 in ~255ms.
  // If fill thread stays parked: LatestIndex stays at ~14.
  std::this_thread::sleep_for(std::chrono::milliseconds(300));

  // Check: did the fill thread decode past the consumer?
  auto frame = buf.GetByIndex(35);
  EXPECT_TRUE(frame.has_value())
      << "INV-FIVS-LOOKAHEAD-STATE-001 VIOLATED: Fill thread did not wake "
      << "after negative lookahead. store_size=" << buf.IndexedStoreSize()
      << ". The condvar predicate treated negative lookahead (decoder behind "
      << "consumer) as 'consumer not started' and fell back to size-based "
      << "parking. Size >= target → fill thread stayed parked → horizon "
      << "collapsed.";

  if (frame.has_value()) {
    EXPECT_EQ(frame->source_frame_index, 35);
  }

  buf.StopFilling(true);
}

}  // namespace
}  // namespace retrovue::blockplan::testing
