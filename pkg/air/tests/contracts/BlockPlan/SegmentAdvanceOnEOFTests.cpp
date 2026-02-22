// Repository: Retrovue-playout
// Component: Segment Advance on EOF Regression Tests
// Purpose: INV-BLOCK-WALLFENCE-003 — segment EOF must advance to next segment
//          (filler/pad), NOT loop back to episode start.
// Contract Reference: PlayoutAuthorityContract.md, INV-BLOCK-WALLFENCE-003
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <cstring>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

#include "retrovue/blockplan/AudioLookaheadBuffer.hpp"
#include "retrovue/blockplan/ITickProducer.hpp"
#include "retrovue/blockplan/TickProducer.hpp"
#include "retrovue/blockplan/VideoLookaheadBuffer.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"

namespace retrovue::blockplan::testing {
namespace {

// =============================================================================
// Helpers — reused from VideoLookaheadBufferTests
// =============================================================================

static buffer::Frame MakeVideoFrame(int width, int height, uint8_t y_fill) {
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

static buffer::AudioFrame MakeAudioFrame(int nb_samples) {
  buffer::AudioFrame frame;
  frame.sample_rate = buffer::kHouseAudioSampleRate;
  frame.channels = buffer::kHouseAudioChannels;
  frame.nb_samples = nb_samples;
  frame.data.resize(
      static_cast<size_t>(nb_samples * buffer::kHouseAudioChannels) *
      sizeof(int16_t), 0);
  return frame;
}

template <typename Pred>
static bool WaitFor(Pred pred, std::chrono::milliseconds timeout) {
  auto deadline = std::chrono::steady_clock::now() + timeout;
  while (!pred()) {
    if (std::chrono::steady_clock::now() > deadline) return false;
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
  return true;
}

// =============================================================================
// SegmentAdvanceMockProducer
//
// Simulates a 3-segment block (episode → filler → pad):
//   Phase 1: Returns episode_frames frames with asset_uri = "episode.mp4"
//   Phase 2: Returns nullopt for gap_frames calls (simulates EOF → boundary
//            advance while block_ct_ms increments)
//   Phase 3: Returns filler_frames frames with asset_uri = "filler.mp4"
//   Phase 4: Returns nullopt indefinitely (pad until fence)
//
// CRITICAL INVARIANT (INV-BLOCK-WALLFENCE-003):
//   After phase 1 exhausts, the mock NEVER returns "episode.mp4" again.
//   If the fill loop ever sees "episode.mp4" after exhaustion, the old
//   SeekToMs(0) EOF-loop bug has regressed.
// =============================================================================

class SegmentAdvanceMockProducer : public ITickProducer {
 public:
  SegmentAdvanceMockProducer(int width, int height, double input_fps,
                              int episode_frames, int gap_frames,
                              int filler_frames)
      : width_(width),
        height_(height),
        input_fps_(input_fps),
        episode_frames_(episode_frames),
        gap_frames_(gap_frames),
        filler_frames_(filler_frames) {
    frame_duration_ms_ =
        input_fps > 0.0 ? static_cast<int64_t>(1000.0 / input_fps) : 33;
  }

  void AssignBlock(const FedBlock& block) override { block_ = block; }

  std::optional<FrameData> TryGetFrame() override {
    if (has_primed_ && primed_frame_) {
      has_primed_ = false;
      return std::move(*primed_frame_);
    }

    std::lock_guard<std::mutex> lock(mutex_);
    call_count_++;

    // Phase 1: Episode content
    if (episode_emitted_ < episode_frames_) {
      episode_emitted_++;
      FrameData fd;
      fd.video = MakeVideoFrame(width_, height_, 0x20);
      fd.asset_uri = "episode.mp4";
      fd.block_ct_ms = (episode_emitted_ - 1) * frame_duration_ms_;
      fd.audio.push_back(MakeAudioFrame(1024));
      return fd;
    }

    // Phase 2: Gap (nullopt while boundary advances)
    if (gap_emitted_ < gap_frames_) {
      gap_emitted_++;
      return std::nullopt;
    }

    // Phase 3: Filler content
    if (filler_emitted_ < filler_frames_) {
      filler_emitted_++;
      int64_t filler_ct = episode_frames_ * frame_duration_ms_ +
                          gap_emitted_ * frame_duration_ms_ +
                          (filler_emitted_ - 1) * frame_duration_ms_;
      FrameData fd;
      fd.video = MakeVideoFrame(width_, height_, 0x40);
      fd.asset_uri = "filler.mp4";
      fd.block_ct_ms = filler_ct;
      fd.audio.push_back(MakeAudioFrame(1024));
      return fd;
    }

    // Phase 4: Pad (nullopt until fence)
    return std::nullopt;
  }

  void Reset() override {}
  State GetState() const override { return State::kReady; }
  const FedBlock& GetBlock() const override { return block_; }
  int64_t FramesPerBlock() const override {
    return episode_frames_ + gap_frames_ + filler_frames_;
  }
  bool HasDecoder() const override { return true; }
  RationalFps GetInputRationalFps() const override { return DeriveRationalFPS(input_fps_); }
  bool HasPrimedFrame() const override { return has_primed_; }

  const std::vector<SegmentBoundary>& GetBoundaries() const override {
    static const std::vector<SegmentBoundary> empty;
    return empty;
  }

  void SetPrimedFrame(FrameData fd) {
    primed_frame_ = std::move(fd);
    has_primed_ = true;
  }

  // Test observability
  int EpisodeEmitted() const { std::lock_guard<std::mutex> l(mutex_); return episode_emitted_; }
  int GapEmitted() const { std::lock_guard<std::mutex> l(mutex_); return gap_emitted_; }
  int FillerEmitted() const { std::lock_guard<std::mutex> l(mutex_); return filler_emitted_; }
  int CallCount() const { std::lock_guard<std::mutex> l(mutex_); return call_count_; }

 private:
  int width_;
  int height_;
  double input_fps_;
  int64_t frame_duration_ms_;
  int episode_frames_;
  int gap_frames_;
  int filler_frames_;

  mutable std::mutex mutex_;
  int episode_emitted_ = 0;
  int gap_emitted_ = 0;
  int filler_emitted_ = 0;
  int call_count_ = 0;

  FedBlock block_;
  bool has_primed_ = false;
  std::optional<FrameData> primed_frame_;
};

// =============================================================================
// TEST-WALLFENCE-003-001: Episode EOF advances to filler, not loop
//
// Scenario: 30-min block at 30fps.
//   Segment 0 (episode): 10 frames (simulating ~25 min episode exhaustion)
//   Gap: 3 nullopt calls (simulating boundary advance while block_ct_ms grows)
//   Segment 1 (filler): 10 frames
//
// Assertions:
//   1. Fill loop continues calling TryGetFrame after episode EOF (not permanent stop)
//   2. Filler frames appear in the buffer with asset_uri = "filler.mp4"
//   3. Episode frames NEVER reappear after exhaustion (no SeekToMs(0) regression)
// =============================================================================

TEST(SegmentAdvanceOnEOF, EpisodeEOFAdvancesToFiller) {
  constexpr int kWidth = 320;
  constexpr int kHeight = 240;
  constexpr double kFps = 30.0;
  constexpr int kEpisodeFrames = 10;
  constexpr int kGapFrames = 3;
  constexpr int kFillerFrames = 10;

  auto producer = std::make_unique<SegmentAdvanceMockProducer>(
      kWidth, kHeight, kFps, kEpisodeFrames, kGapFrames, kFillerFrames);
  auto* producer_ptr = producer.get();

  // Prime the first frame so VideoLookaheadBuffer::StartFilling succeeds.
  {
    FrameData primed;
    primed.video = MakeVideoFrame(kWidth, kHeight, 0x20);
    primed.asset_uri = "episode.mp4";
    primed.block_ct_ms = 0;
    primed.audio.push_back(MakeAudioFrame(1024));
    producer_ptr->SetPrimedFrame(std::move(primed));
  }

  // Create lookahead buffers.
  // Target depth must be large enough to hold all frames (episode + hold-last
  // gap + filler) without backpressure, since nothing pops during this test.
  VideoLookaheadBuffer vlb(50, 5);  // target=50, low_water=5
  AudioLookaheadBuffer alb(1000, buffer::kHouseAudioSampleRate,
                            buffer::kHouseAudioChannels, 333);

  std::atomic<bool> stop{false};
  vlb.StartFilling(producer_ptr, &alb, kFps, kFps, &stop);

  // Wait until filler frames have been produced.
  // The fill loop must NOT stop permanently at episode EOF.
  bool filler_produced = WaitFor(
      [&] { return producer_ptr->FillerEmitted() > 0; },
      std::chrono::milliseconds(2000));
  ASSERT_TRUE(filler_produced)
      << "INV-BLOCK-WALLFENCE-003 VIOLATION: Fill loop stopped permanently at "
         "episode EOF instead of continuing to call TryGetFrame. "
         "Episode emitted=" << producer_ptr->EpisodeEmitted()
      << " Gap emitted=" << producer_ptr->GapEmitted()
      << " Filler emitted=" << producer_ptr->FillerEmitted()
      << " Total calls=" << producer_ptr->CallCount();

  // Let the buffer fill a bit more.
  std::this_thread::sleep_for(std::chrono::milliseconds(100));

  // Stop fill thread.
  stop.store(true);
  vlb.StopFilling(false);

  // ASSERTION 1: Episode frames were all consumed.
  EXPECT_EQ(producer_ptr->EpisodeEmitted(), kEpisodeFrames);

  // ASSERTION 2: Gap frames were consumed (boundary advance happened).
  EXPECT_EQ(producer_ptr->GapEmitted(), kGapFrames);

  // ASSERTION 3: Filler frames were produced (segment advance worked).
  EXPECT_GT(producer_ptr->FillerEmitted(), 0)
      << "Filler frames must be produced after episode EOF";

  // ASSERTION 4: Pop frames from buffer and verify asset_uri transition.
  // The buffer should contain: episode frames → hold-last frames → filler frames.
  // Crucially: NO episode.mp4 frames may appear after the first filler.mp4 frame.
  bool seen_filler = false;
  int episode_count = 0;
  int filler_count = 0;
  int hold_last_count = 0;
  bool episode_after_filler = false;

  VideoBufferFrame vbf;
  while (vlb.TryPopFrame(vbf)) {
    if (vbf.was_decoded && vbf.asset_uri == "episode.mp4") {
      episode_count++;
      if (seen_filler) {
        episode_after_filler = true;
      }
    } else if (vbf.was_decoded && vbf.asset_uri == "filler.mp4") {
      filler_count++;
      seen_filler = true;
    } else if (!vbf.was_decoded) {
      hold_last_count++;
    }
  }

  EXPECT_GT(episode_count, 0) << "Must have episode frames in buffer";
  EXPECT_GT(filler_count, 0) << "Must have filler frames in buffer";
  EXPECT_FALSE(episode_after_filler)
      << "INV-BLOCK-WALLFENCE-003 REGRESSION: episode.mp4 frames appeared "
         "AFTER filler.mp4 — indicates SeekToMs(0) EOF-loop bug. "
         "episode_count=" << episode_count
      << " filler_count=" << filler_count
      << " hold_last_count=" << hold_last_count;
}

// =============================================================================
// TEST-WALLFENCE-003-002: Content gap does NOT permanently stop the fill loop
//
// Regression: Old `content_exhausted` flag was permanent — once set, the fill
// loop never called TryGetFrame again, preventing segment advancement.
// New `content_gap` flag re-evaluates every cycle.
//
// Scenario: Producer returns 5 frames, then 10 nullopts, then 5 more frames.
// The fill loop must continue calling TryGetFrame through the gap.
// =============================================================================

TEST(SegmentAdvanceOnEOF, ContentGapDoesNotPermanentlyStopFillLoop) {
  constexpr int kWidth = 320;
  constexpr int kHeight = 240;
  constexpr double kFps = 30.0;

  // 5 episode + 10 gap + 5 filler = simulates content → gap → content
  auto producer = std::make_unique<SegmentAdvanceMockProducer>(
      kWidth, kHeight, kFps, 5, 10, 5);
  auto* producer_ptr = producer.get();

  {
    FrameData primed;
    primed.video = MakeVideoFrame(kWidth, kHeight, 0x20);
    primed.asset_uri = "episode.mp4";
    primed.block_ct_ms = 0;
    primed.audio.push_back(MakeAudioFrame(1024));
    producer_ptr->SetPrimedFrame(std::move(primed));
  }

  VideoLookaheadBuffer vlb(50, 5);
  AudioLookaheadBuffer alb(1000, buffer::kHouseAudioSampleRate,
                            buffer::kHouseAudioChannels, 333);

  std::atomic<bool> stop{false};
  vlb.StartFilling(producer_ptr, &alb, kFps, kFps, &stop);

  // Wait for the fill loop to push through the gap and emit filler frames.
  bool filler_arrived = WaitFor(
      [&] { return producer_ptr->FillerEmitted() >= 3; },
      std::chrono::milliseconds(2000));

  stop.store(true);
  vlb.StopFilling(false);

  ASSERT_TRUE(filler_arrived)
      << "content_gap must NOT permanently stop the fill loop. "
         "Filler emitted=" << producer_ptr->FillerEmitted()
      << " Gap consumed=" << producer_ptr->GapEmitted()
      << " Total calls=" << producer_ptr->CallCount();

  // The fill loop must have made at least episode + gap + filler calls.
  EXPECT_GE(producer_ptr->CallCount(), 5 + 10 + 3);
}

// =============================================================================
// TEST-WALLFENCE-003-003: Hold-last frames bridge the gap between segments
//
// When TryGetFrame returns nullopt (content gap), the fill loop must push
// hold-last frames (was_decoded=false) to prevent buffer underflow.
// =============================================================================

TEST(SegmentAdvanceOnEOF, HoldLastFramesBridgeGap) {
  constexpr int kWidth = 320;
  constexpr int kHeight = 240;
  constexpr double kFps = 30.0;

  // 3 episode + 5 gap + 3 filler
  auto producer = std::make_unique<SegmentAdvanceMockProducer>(
      kWidth, kHeight, kFps, 3, 5, 3);
  auto* producer_ptr = producer.get();

  {
    FrameData primed;
    primed.video = MakeVideoFrame(kWidth, kHeight, 0x20);
    primed.asset_uri = "episode.mp4";
    primed.block_ct_ms = 0;
    primed.audio.push_back(MakeAudioFrame(1024));
    producer_ptr->SetPrimedFrame(std::move(primed));
  }

  VideoLookaheadBuffer vlb(30, 5);  // Larger buffer to capture all phases
  AudioLookaheadBuffer alb(1000, buffer::kHouseAudioSampleRate,
                            buffer::kHouseAudioChannels, 333);

  std::atomic<bool> stop{false};
  vlb.StartFilling(producer_ptr, &alb, kFps, kFps, &stop);

  // Wait for all phases to complete.
  bool all_done = WaitFor(
      [&] { return producer_ptr->FillerEmitted() >= 3; },
      std::chrono::milliseconds(2000));

  // Let buffer fill fully.
  std::this_thread::sleep_for(std::chrono::milliseconds(50));

  stop.store(true);
  vlb.StopFilling(false);

  ASSERT_TRUE(all_done);

  // Pop all frames and verify hold-last frames exist during the gap.
  int decoded_episode = 0;
  int decoded_filler = 0;
  int hold_last = 0;

  VideoBufferFrame vbf;
  while (vlb.TryPopFrame(vbf)) {
    if (vbf.was_decoded && vbf.asset_uri == "episode.mp4") decoded_episode++;
    else if (vbf.was_decoded && vbf.asset_uri == "filler.mp4") decoded_filler++;
    else if (!vbf.was_decoded) hold_last++;
  }

  EXPECT_GT(decoded_episode, 0) << "Must have decoded episode frames";
  EXPECT_GT(decoded_filler, 0) << "Must have decoded filler frames";
  EXPECT_GT(hold_last, 0)
      << "Must have hold-last frames bridging the gap between episode and filler. "
         "Without hold-last, buffer would underflow during segment transition.";
}

}  // namespace
}  // namespace retrovue::blockplan::testing
