// Repository: Retrovue-playout
// Component: FIVS Decode Horizon Contract Tests
// Purpose: Prove compliance with INV-FIVS-HORIZON.
//          The decoder must maintain:
//            highest_decoded_frame >= consumer_requested_frame + lookahead_target
//          Violations cause frame repetition, freeze/jump, and negative frame_gap.
// Contract Reference: INV-FIVS-HORIZON
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

// Helper: create a video Frame with given dimensions.
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

// =============================================================================
// HorizonProducer — ITickProducer that sets source_frame_index on every frame.
//
// Unlike MockTickProducer, this producer stamps each frame with a monotonic
// source_frame_index so FIVS inserts work (the guard is index >= 0).
// =============================================================================
class HorizonProducer : public ITickProducer {
 public:
  HorizonProducer(int total_frames, std::chrono::microseconds decode_delay = {})
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
    fd.asset_uri = "horizon_test.mp4";
    fd.block_ct_ms = index * 33;
    fd.source_frame_index = index;  // Critical: enables FIVS insert
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

// Helper: poll until condition is true (with timeout).
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
// Test 1 — Horizon Maintenance
//
// INV-FIVS-HORIZON: highest_decoded_frame >= requested_frame + lookahead_target
//
// Start the fill thread, let it decode ahead, then simulate the tick loop
// advancing consumer_selected_src. At each step, verify the horizon holds
// by checking that GetByIndex(requested) returns the exact frame.
// ---------------------------------------------------------------------------
TEST(FIVSHorizonContract, test_horizon_maintenance) {
  const int lookahead_target = 10;
  const int total_frames = 200;
  VideoLookaheadBuffer buf(15, 5, lookahead_target);
  HorizonProducer producer(total_frames);
  std::atomic<bool> stop{false};

  buf.StartFilling(&producer, nullptr, FPS_30, FPS_30, &stop);

  // Wait for fill thread to decode at least lookahead_target frames.
  ASSERT_TRUE(WaitFor(
      [&] { return buf.IndexedStoreSize() >= static_cast<size_t>(lookahead_target); },
      std::chrono::milliseconds(2000)))
      << "Fill thread did not decode " << lookahead_target << " frames in time";

  // Simulate tick loop: advance consumer from 0 to 50.
  // At each step, the fill thread should have maintained the horizon.
  int horizon_violations = 0;
  for (int64_t consumer_pos = 0; consumer_pos < 50; ++consumer_pos) {
    buf.UpdateConsumerPosition(consumer_pos);

    // Give fill thread a moment to respond to the new consumer position.
    std::this_thread::sleep_for(std::chrono::milliseconds(5));

    // INV-FIVS-HORIZON: the frame at consumer_pos must be available.
    auto frame = buf.GetByIndex(consumer_pos);
    if (!frame.has_value()) {
      horizon_violations++;
      ADD_FAILURE()
          << "INV-FIVS-HORIZON violated: GetByIndex(" << consumer_pos
          << ") returned nullopt. store_size=" << buf.IndexedStoreSize();
    } else {
      EXPECT_EQ(frame->source_frame_index, consumer_pos);
    }

    // Evict behind the consumer (as PipelineManager does).
    if (consumer_pos > 2)
      buf.EvictBelow(consumer_pos - 2);
  }

  EXPECT_EQ(horizon_violations, 0)
      << "INV-FIVS-HORIZON: " << horizon_violations
      << " frames missed — decoder did not stay ahead of consumer";

  buf.StopFilling(true);
}

// ---------------------------------------------------------------------------
// Test 2 — No Consumer Starvation
//
// INV-FIVS-HORIZON: Under sustained decode, store.GetByIndex(requested)
// must never return nullopt when the decoder is keeping up.
//
// Simulate decode under load: producer has a small decode delay, consumer
// advances at ~30fps. The fill thread must burst-decode to maintain the
// horizon. Every GetByIndex must succeed.
// ---------------------------------------------------------------------------
TEST(FIVSHorizonContract, test_no_consumer_starvation) {
  const int lookahead_target = 10;
  const int total_frames = 300;
  // 500us decode delay (~2000fps capacity, well above 30fps).
  VideoLookaheadBuffer buf(15, 5, lookahead_target);
  HorizonProducer producer(total_frames, std::chrono::microseconds(500));
  std::atomic<bool> stop{false};

  buf.StartFilling(&producer, nullptr, FPS_30, FPS_30, &stop);

  // Wait for initial fill.
  ASSERT_TRUE(WaitFor(
      [&] { return buf.IndexedStoreSize() >= static_cast<size_t>(lookahead_target); },
      std::chrono::milliseconds(2000)))
      << "Fill thread did not reach lookahead_target in time";

  // Consumer advances at ~30fps (33ms per frame) for 100 frames.
  int starvation_count = 0;
  for (int64_t consumer_pos = 0; consumer_pos < 100; ++consumer_pos) {
    buf.UpdateConsumerPosition(consumer_pos);

    auto frame = buf.GetByIndex(consumer_pos);
    if (!frame.has_value()) {
      starvation_count++;
    } else {
      // Must be the exact frame, not a stale/previous frame.
      EXPECT_EQ(frame->source_frame_index, consumer_pos)
          << "GetByIndex returned wrong frame at consumer_pos=" << consumer_pos;
    }

    if (consumer_pos > 2)
      buf.EvictBelow(consumer_pos - 2);

    // Simulate tick interval (~33ms for 30fps).
    std::this_thread::sleep_for(std::chrono::milliseconds(33));
  }

  EXPECT_EQ(starvation_count, 0)
      << "INV-FIVS-HORIZON: consumer starved " << starvation_count
      << " times — fill thread did not maintain decode horizon";

  buf.StopFilling(true);
}

// ---------------------------------------------------------------------------
// Test 3 — Negative Gap Detection
//
// INV-FIVS-HORIZON: frame_gap >= 0 must always hold.
// Any negative gap means the decoder is behind the consumer.
//
// Use a producer with very few frames (decoder exhausts content).
// Consumer advances past the decoder's highest frame. Verify:
// 1. frame_gap goes negative.
// 2. GetByIndex returns nullopt (store miss = horizon failure).
// ---------------------------------------------------------------------------
TEST(FIVSHorizonContract, test_negative_gap_detection) {
  const int lookahead_target = 10;
  const int total_frames = 20;  // Only 20 frames available.
  VideoLookaheadBuffer buf(15, 5, lookahead_target);
  HorizonProducer producer(total_frames);
  std::atomic<bool> stop{false};

  buf.StartFilling(&producer, nullptr, FPS_30, FPS_30, &stop);

  // Wait for all 20 frames to be decoded.
  ASSERT_TRUE(WaitFor(
      [&] { return buf.IndexedStoreSize() >= 20u; },
      std::chrono::milliseconds(2000)))
      << "Fill thread did not decode all 20 frames";

  // Consumer at frame 5: frame_gap = 19 - 5 = 14 >= lookahead_target. OK.
  buf.UpdateConsumerPosition(5);
  {
    auto frame = buf.GetByIndex(5);
    ASSERT_TRUE(frame.has_value()) << "Frame 5 should exist";
    EXPECT_EQ(frame->source_frame_index, 5);
  }

  // Consumer at frame 19: frame_gap = 19 - 19 = 0. Border case.
  buf.UpdateConsumerPosition(19);
  {
    auto frame = buf.GetByIndex(19);
    ASSERT_TRUE(frame.has_value()) << "Frame 19 should exist (highest decoded)";
  }

  // Consumer at frame 20: frame_gap = 19 - 20 = -1. Negative gap.
  // This is a horizon failure — decoder ran out of content.
  buf.UpdateConsumerPosition(20);
  {
    auto frame = buf.GetByIndex(20);
    EXPECT_FALSE(frame.has_value())
        << "INV-FIVS-HORIZON: GetByIndex(20) should return nullopt "
        << "when decoder has only decoded up to frame 19 (negative frame_gap)";
  }

  // Consumer at frame 25: frame_gap = 19 - 25 = -6. Deeply negative.
  buf.UpdateConsumerPosition(25);
  {
    auto frame = buf.GetByIndex(25);
    EXPECT_FALSE(frame.has_value())
        << "INV-FIVS-HORIZON: GetByIndex(25) should return nullopt "
        << "(decoder behind by 6 frames)";
  }

  buf.StopFilling(true);
}

// ---------------------------------------------------------------------------
// Test 4 — Negative Lookahead Wake (proves the fix for INV-FIVS-HORIZON)
//
// This test reproduces the exact production failure:
//   1. Fill thread parks after filling to lookahead_target.
//   2. Consumer jumps ahead of the decoder (lookahead goes negative).
//   3. Store still has >= target_depth_frames_ frames from the burst.
//
// BUG (before fix): The condvar predicate treats negative lookahead as
// "consumer not started" and falls back to size-based parking. Since
// size >= target, the predicate returns false → fill thread stays parked
// → gap grows unboundedly → freeze/jump playback.
//
// FIX: Predicate distinguishes "consumer not started" (INT_MIN sentinel)
// from "decoder behind consumer" (negative int). Negative lookahead
// correctly evaluates as la < lookahead_target → fill thread wakes.
//
// The test uses a 1ms decode delay so the fill thread can't instantly
// decode everything, but 200ms is plenty of time to decode 30+ frames
// if the fill thread wakes.
// ---------------------------------------------------------------------------
TEST(FIVSHorizonContract, test_negative_lookahead_wake) {
  const int lookahead_target = 10;
  const int target_depth = 15;
  const int total_frames = 500;
  // 1ms decode delay: fill thread can decode ~200 frames in 200ms if awake,
  // but 0 frames if parked.
  VideoLookaheadBuffer buf(target_depth, 5, lookahead_target);
  HorizonProducer producer(total_frames, std::chrono::microseconds(1000));
  std::atomic<bool> stop{false};

  buf.StartFilling(&producer, nullptr, FPS_30, FPS_30, &stop);

  // Step 1: Let fill thread decode to target. It will park when
  // lookahead >= lookahead_target (pre-first-tick fallback: size >= target).
  ASSERT_TRUE(WaitFor(
      [&] { return buf.IndexedStoreSize() >= static_cast<size_t>(target_depth); },
      std::chrono::milliseconds(2000)))
      << "Fill thread did not fill to target_depth";

  // Record what the fill thread has decoded so far.
  // LatestIndex is ~14 (0-based, target_depth=15 frames).
  // Store has ~15 frames.

  // Step 2: Jump consumer far past the decoder.
  // Consumer at frame 30, but decoder only reached ~14.
  // Lookahead = ~14 - 30 = -16 (deeply negative).
  // Store still has 15 frames (>= target_depth_frames_).
  buf.UpdateConsumerPosition(30);

  // Step 3: Wait for condvar timeout (100ms) + decode time.
  // If the fill thread wakes correctly, it burst-decodes from ~15 to ~40+
  // in about 25ms (25 frames at 1ms each).
  // Total wait: 200ms is generous.
  std::this_thread::sleep_for(std::chrono::milliseconds(300));

  // Step 4: Check if the fill thread decoded past the consumer.
  // With the bug: fill thread is still parked at frame ~14.
  //   GetByIndex(35) returns nullopt.
  // With the fix: fill thread burst-decoded to frame 40+.
  //   GetByIndex(35) returns the frame.
  auto frame = buf.GetByIndex(35);
  EXPECT_TRUE(frame.has_value())
      << "INV-FIVS-HORIZON: Fill thread did not wake after negative lookahead. "
      << "store_size=" << buf.IndexedStoreSize()
      << " — condvar predicate likely fell back to size-based parking "
      << "instead of recognizing negative lookahead as 'decoder behind consumer'";

  if (frame.has_value()) {
    EXPECT_EQ(frame->source_frame_index, 35);
  }

  buf.StopFilling(true);
}

}  // namespace
}  // namespace retrovue::blockplan::testing
