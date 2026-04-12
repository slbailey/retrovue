// Repository: Retrovue-playout
// Component: Real-System EOF→Pad Contract Tests
// Purpose: Expose current invariant violations using REAL VideoLookaheadBuffer.
//
// Contract: docs/contracts/air/DECODE_RESULT_MODEL.md
//           docs/contracts/air/EOF_PAD_TRANSITION.md
//
// These tests MUST FAIL under the current implementation.
// They become passing once the DecodeResult model is implemented.
//
// Invariants tested against REAL system:
//   INV-AIR-EOF-NON-REPEATABLE-001 — kEof must not repeat, must pad
//   INV-AIR-EOF-VS-UNDERRUN-001    — system must distinguish the two
//   INV-AIR-EOF-IMMEDIATE-001      — pad on first tick after EOF
//
// Copyright (c) 2026 RetroVue

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
// Helpers
// =============================================================================

static constexpr RationalFps FPS_30 = {30000, 1001};

static buffer::Frame MakeVideoFrame(int width, int height, uint8_t y_fill) {
  buffer::Frame frame;
  frame.width = width;
  frame.height = height;
  int y_size = width * height;
  int uv_size = (width / 2) * (height / 2);
  frame.data.resize(static_cast<size_t>(y_size + 2 * uv_size));
  std::memset(frame.data.data(), y_fill, static_cast<size_t>(y_size));
  std::memset(frame.data.data() + y_size, 0x80,
              static_cast<size_t>(2 * uv_size));
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

static bool IsPadFrame(const buffer::Frame& f) {
  if (f.data.empty()) return false;
  // Broadcast black: Y=0x10
  return f.data[0] == 0x10;
}

static bool IsContentFrame(const buffer::Frame& f, uint8_t expected_y) {
  if (f.data.empty()) return false;
  return f.data[0] == expected_y;
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
// EofMockProducer
//
// Produces content_frames_ real frames, then returns nullopt permanently
// (simulating decoder EOF). decoder_ok_ goes false on EOF.
// This is how the REAL TickProducer behaves on segment exhaustion.
//
// CRITICAL: This mock uses the CURRENT interface (std::optional<FrameData>).
// It does NOT use DecodeResult. It exposes the real system's limitation.
// =============================================================================

static constexpr uint8_t kContentY = 0x30;

class EofMockProducer : public ITickProducer {
 public:
  EofMockProducer(int width, int height, int content_frames)
      : width_(width), height_(height), content_frames_(content_frames) {}

  void AssignBlock(const FedBlock& block) override { block_ = block; }

  DecodeResult TryGetFrame() override {
    std::lock_guard<std::mutex> lock(mutex_);
    call_count_++;

    if (emitted_ < content_frames_) {
      emitted_++;
      FrameData fd;
      fd.video = MakeVideoFrame(width_, height_, kContentY);
      fd.asset_uri = "commercial.mp4";
      fd.block_ct_ms = static_cast<int64_t>(emitted_ - 1) * 33;
      fd.source_frame_index = emitted_ - 1;
      fd.audio.push_back(MakeAudioFrame(1024));
      return {DecodeStatus::kFrame, std::move(fd)};
    }

    // EOF: terminal for this segment.
    eof_ = true;
    return {DecodeStatus::kEof, std::nullopt};
  }

  void Reset() override {}
  State GetState() const override { return State::kReady; }
  const FedBlock& GetBlock() const override { return block_; }
  int64_t FramesPerBlock() const override { return content_frames_ + 20; }
  bool HasDecoder() const override { return !eof_; }
  // IsSegmentEof removed — replaced by in-band DecodeResult
  RationalFps GetInputRationalFps() const override { return FPS_30; }
  bool HasPrimedFrame() const override { return has_primed_; }
  bool HasAudioStream() const override { return false; }
  const std::vector<SegmentBoundary>& GetBoundaries() const override {
    return boundaries_;
  }

  void SetPrimedFrame(FrameData fd) {
    primed_frame_ = std::move(fd);
    has_primed_ = true;
  }

  // Test inspection
  int emitted() const { std::lock_guard<std::mutex> l(mutex_); return emitted_; }
  int call_count() const { std::lock_guard<std::mutex> l(mutex_); return call_count_; }
  bool eof() const { std::lock_guard<std::mutex> l(mutex_); return eof_; }

 private:
  int width_;
  int height_;
  int content_frames_;
  int emitted_ = 0;
  int call_count_ = 0;
  bool eof_ = false;
  bool has_primed_ = false;
  std::optional<FrameData> primed_frame_;
  FedBlock block_;
  std::vector<SegmentBoundary> boundaries_;
  mutable std::mutex mutex_;
};

}  // namespace

// =============================================================================
// TEST_FAIL_CurrentSystem_RepeatsFrameAfterEOF
//
// INV-AIR-EOF-NON-REPEATABLE-001 VIOLATION (EXPECTED):
//
// Current behavior: After decoder EOF, the fill loop holds the last
// decoded frame (was_decoded=false, content Y=0x30). The buffer
// contains held content frames, NOT pad frames (Y=0x10).
//
// Correct behavior: After EOF, buffer must contain pad frames only.
//
// This test MUST FAIL under the current system.
// =============================================================================

TEST(EofPadRealSystem, TEST_FAIL_CurrentSystem_RepeatsFrameAfterEOF) {
  constexpr int kWidth = 320;
  constexpr int kHeight = 240;
  constexpr int kContentFrames = 10;

  auto producer = std::make_unique<EofMockProducer>(kWidth, kHeight, kContentFrames);
  auto* producer_ptr = producer.get();

  // Prime first frame.
  {
    FrameData primed;
    primed.video = MakeVideoFrame(kWidth, kHeight, kContentY);
    primed.asset_uri = "commercial.mp4";
    primed.block_ct_ms = 0;
    primed.source_frame_index = 0;
    primed.audio.push_back(MakeAudioFrame(1024));
    producer_ptr->SetPrimedFrame(std::move(primed));
  }

  // Buffer large enough to hold content + EOF tail without backpressure.
  VideoLookaheadBuffer vlb(50, 5);
  AudioLookaheadBuffer alb(1000, buffer::kHouseAudioSampleRate,
                            buffer::kHouseAudioChannels, 333);

  std::atomic<bool> stop{false};
  vlb.StartFilling(producer_ptr, &alb, FPS_30, FPS_30, &stop);

  // Wait for EOF to be reached.
  bool eof_reached = WaitFor(
      [&] { return producer_ptr->eof(); },
      std::chrono::milliseconds(2000));
  ASSERT_TRUE(eof_reached) << "Producer must reach EOF within timeout";

  // Let fill loop run a bit after EOF so it pushes hold-last frames.
  std::this_thread::sleep_for(std::chrono::milliseconds(200));

  // Stop fill.
  stop.store(true);
  vlb.StopFilling(false);

  // Pop ALL frames from buffer.
  int content_count = 0;
  int held_content_count = 0;  // was_decoded=false but content Y
  int pad_count = 0;
  bool seen_eof_tail = false;

  VideoBufferFrame vbf;
  while (vlb.TryPopFrame(vbf)) {
    if (vbf.was_decoded && IsContentFrame(vbf.video, kContentY)) {
      content_count++;
    } else if (!vbf.was_decoded && IsContentFrame(vbf.video, kContentY)) {
      // This is a HELD content frame — the fill loop repeated the last
      // decoded frame instead of emitting pad.
      held_content_count++;
      seen_eof_tail = true;
    } else if (IsPadFrame(vbf.video)) {
      pad_count++;
      seen_eof_tail = true;
    }
  }

  // We expect content_count == kContentFrames (the real decoded frames).
  EXPECT_GE(content_count, 1) << "Must have at least some decoded frames";

  // INV-AIR-EOF-NON-REPEATABLE-001:
  // After EOF, ALL frames in the buffer must be pad (Y=0x10).
  // Held content frames (Y=0x30, was_decoded=false) are a VIOLATION.
  EXPECT_EQ(held_content_count, 0)
      << "INV-AIR-EOF-NON-REPEATABLE-001 VIOLATION: "
      << held_content_count << " held content frames found after EOF. "
      << "These are repeated last-frame copies (freeze frame). "
      << "Expected: 0 held content, only pad frames after EOF. "
      << "(content=" << content_count
      << " held=" << held_content_count
      << " pad=" << pad_count << ")";

  EXPECT_GT(pad_count, 0)
      << "INV-AIR-EOF-NON-REPEATABLE-001 VIOLATION: "
      << "Zero pad frames found after EOF. Expected pad frames (Y=0x10) "
      << "for the remaining segment duration.";
}

// =============================================================================
// TEST_FAIL_CurrentSystem_CannotDistinguishUnderrunVsEOF
//
// INV-AIR-EOF-VS-UNDERRUN-001 VIOLATION (EXPECTED):
//
// Current behavior: Both underrun and EOF return nullopt. The fill loop
// handles both identically: hold last frame. There is no distinction.
//
// Correct behavior: Underrun → hold last. EOF → pad.
//
// This test demonstrates that the two cases produce identical buffer
// output, which is incorrect.
// =============================================================================

TEST(EofPadRealSystem, TEST_FAIL_CurrentSystem_CannotDistinguishUnderrunVsEOF) {
  constexpr int kWidth = 320;
  constexpr int kHeight = 240;
  constexpr int kContentFrames = 5;

  // Case A: EOF after 5 frames.
  auto producer_eof = std::make_unique<EofMockProducer>(kWidth, kHeight, kContentFrames);
  auto* eof_ptr = producer_eof.get();
  {
    FrameData primed;
    primed.video = MakeVideoFrame(kWidth, kHeight, kContentY);
    primed.asset_uri = "commercial.mp4";
    primed.block_ct_ms = 0;
    primed.source_frame_index = 0;
    primed.audio.push_back(MakeAudioFrame(1024));
    eof_ptr->SetPrimedFrame(std::move(primed));
  }

  VideoLookaheadBuffer vlb_eof(50, 5);
  AudioLookaheadBuffer alb_eof(1000, buffer::kHouseAudioSampleRate,
                                buffer::kHouseAudioChannels, 333);
  std::atomic<bool> stop_eof{false};
  vlb_eof.StartFilling(eof_ptr, &alb_eof, FPS_30, FPS_30, &stop_eof);

  WaitFor([&] { return eof_ptr->eof(); }, std::chrono::milliseconds(2000));
  std::this_thread::sleep_for(std::chrono::milliseconds(200));
  stop_eof.store(true);
  vlb_eof.StopFilling(false);

  // Case B: Underrun after 5 frames (same mock — EOF is indistinguishable).
  // We use the same producer type because that's the point: the current
  // system cannot tell the difference. Both produce the same buffer output.

  // Count held frames in EOF case.
  int eof_held = 0;
  int eof_pad = 0;
  {
    VideoBufferFrame vbf;
    bool past_content = false;
    while (vlb_eof.TryPopFrame(vbf)) {
      if (!vbf.was_decoded) {
        past_content = true;
        if (IsContentFrame(vbf.video, kContentY)) eof_held++;
        else if (IsPadFrame(vbf.video)) eof_pad++;
      }
    }
  }

  // INV-AIR-EOF-VS-UNDERRUN-001:
  // EOF case should have ONLY pad frames after content.
  // Underrun case should have ONLY held frames after content.
  // If both cases produce the same type of frame (held content),
  // the system cannot distinguish them → violation.
  bool system_distinguishes = (eof_pad > 0 && eof_held == 0);
  EXPECT_TRUE(system_distinguishes)
      << "INV-AIR-EOF-VS-UNDERRUN-001 VIOLATION: "
      << "EOF case produced " << eof_held << " held content frames and "
      << eof_pad << " pad frames. For correct behavior, EOF must produce "
      << "ONLY pad frames (0 held, >0 pad). "
      << "Current system treats EOF identically to underrun.";
}

// =============================================================================
// TEST_FAIL_CurrentSystem_EOFDoesNotProduceImmediatePad
//
// INV-AIR-EOF-IMMEDIATE-001 VIOLATION (EXPECTED):
//
// Current behavior: The first frame after EOF in the buffer is a held
// content frame (repeated last decoded frame), not a pad frame.
//
// Correct behavior: The first frame after EOF must be pad (Y=0x10).
// =============================================================================

TEST(EofPadRealSystem, TEST_FAIL_CurrentSystem_EOFDoesNotProduceImmediatePad) {
  constexpr int kWidth = 320;
  constexpr int kHeight = 240;
  constexpr int kContentFrames = 10;

  auto producer = std::make_unique<EofMockProducer>(kWidth, kHeight, kContentFrames);
  auto* producer_ptr = producer.get();
  {
    FrameData primed;
    primed.video = MakeVideoFrame(kWidth, kHeight, kContentY);
    primed.asset_uri = "commercial.mp4";
    primed.block_ct_ms = 0;
    primed.source_frame_index = 0;
    primed.audio.push_back(MakeAudioFrame(1024));
    producer_ptr->SetPrimedFrame(std::move(primed));
  }

  VideoLookaheadBuffer vlb(50, 5);
  AudioLookaheadBuffer alb(1000, buffer::kHouseAudioSampleRate,
                            buffer::kHouseAudioChannels, 333);
  std::atomic<bool> stop{false};
  vlb.StartFilling(producer_ptr, &alb, FPS_30, FPS_30, &stop);

  WaitFor([&] { return producer_ptr->eof(); }, std::chrono::milliseconds(2000));
  std::this_thread::sleep_for(std::chrono::milliseconds(200));
  stop.store(true);
  vlb.StopFilling(false);

  // Find the FIRST non-decoded frame after all decoded content.
  // This is the first frame in the "EOF tail."
  VideoBufferFrame vbf;
  bool past_content = false;
  buffer::Frame first_eof_frame;
  bool found_first_eof = false;

  while (vlb.TryPopFrame(vbf)) {
    if (vbf.was_decoded) {
      continue;  // Skip decoded content frames.
    }
    // First non-decoded frame after content.
    if (!found_first_eof) {
      first_eof_frame = vbf.video;
      found_first_eof = true;
      break;
    }
  }

  ASSERT_TRUE(found_first_eof)
      << "Must find at least one non-decoded frame after content";

  // INV-AIR-EOF-IMMEDIATE-001:
  // The FIRST frame after EOF must be pad (Y=0x10).
  // If it's content (Y=0x30), the system is holding the last frame.
  EXPECT_TRUE(IsPadFrame(first_eof_frame))
      << "INV-AIR-EOF-IMMEDIATE-001 VIOLATION: "
      << "First frame after EOF is NOT pad. Y[0]="
      << static_cast<int>(first_eof_frame.data[0])
      << " (expected 0x10 for pad, got 0x"
      << std::hex << static_cast<int>(first_eof_frame.data[0]) << std::dec
      << "). The system is repeating the last commercial frame.";
}

}  // namespace retrovue::blockplan::testing
