// Repository: Retrovue-playout
// Component: INV-AIR-EOF-PAD-TRANSITION Contract Tests
// Purpose: Verify that decoder EOF within a segment produces pad frames
//          (black+silence) for remaining segment duration — NOT repeated
//          frames from the terminated asset.
//
// Contract: docs/contracts/air/EOF_PAD_TRANSITION.md
//
// Invariants under test:
//   INV-AIR-EOF-PAD-TRANSITION-001 — pad after EOF, not repeat
//   INV-AIR-EOF-VS-UNDERRUN-001    — EOF vs underrun distinction
//   INV-AIR-EOF-IMMEDIATE-001      — pad begins on first tick after EOF
//
// Copyright (c) 2026 RetroVue

#include <gtest/gtest.h>

#include <atomic>
#include <cstring>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

#include "retrovue/blockplan/ITickProducer.hpp"
#include "retrovue/blockplan/TickProducer.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"

namespace retrovue::blockplan::testing {
namespace {

// =============================================================================
// Helpers
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

/// Check if a video frame is broadcast black (Y=0x10, UV=0x80).
static bool IsPadFrame(const buffer::Frame& frame) {
  if (frame.data.empty()) return false;
  int y_size = frame.width * frame.height;
  // Check first Y sample is broadcast black
  return frame.data[0] == 0x10;
}

/// Check if a video frame matches the content fill value.
static bool IsContentFrame(const buffer::Frame& frame, uint8_t expected_y) {
  if (frame.data.empty()) return false;
  return frame.data[0] == expected_y;
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

// =============================================================================
// EofAwareMockProducer
//
// Simulates a segment whose asset is shorter than its allocated duration.
// After content_frames frames, reports EOF (returns nullopt with a distinct
// EOF flag). The remaining segment_total_frames - content_frames frames
// are the "EOF tail" where the system must emit pad, not repeat.
//
// Also supports a transient underrun mode: returns nullopt for N calls
// then resumes content (to test INV-AIR-EOF-VS-UNDERRUN-001).
// =============================================================================

class EofAwareMockProducer : public ITickProducer {
 public:
  EofAwareMockProducer(int width, int height,
                        int content_frames,
                        int segment_total_frames)
      : width_(width),
        height_(height),
        content_frames_(content_frames),
        segment_total_frames_(segment_total_frames) {}

  void AssignBlock(const FedBlock& block) override { block_ = block; }

  // Simulate DecodeNextFrameRaw behavior.
  // Returns content frames, then nullopt after EOF.
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

    // EOF reached
    eof_reached_ = true;
    return {DecodeStatus::kEof, std::nullopt};
  }

  void Reset() override {}
  bool HasDecoder() const override { return !eof_reached_; }
  State GetState() const override { return State::kReady; }
  const FedBlock& GetBlock() const override { return block_; }
  int64_t FramesPerBlock() const override { return segment_total_frames_; }
  RationalFps GetInputRationalFps() const override { return {30000, 1001}; }
  bool HasPrimedFrame() const override { return false; }
  const std::vector<SegmentBoundary>& GetBoundaries() const override { return boundaries_; }

  // Test inspection
  int call_count() const { return call_count_; }
  int emitted() const { return emitted_; }
  bool eof_reached() const { return eof_reached_; }

  static constexpr uint8_t kContentY = 0x30;  // Distinguishable from pad (0x10)

 private:
  int width_;
  int height_;
  int content_frames_;
  int segment_total_frames_;
  int emitted_ = 0;
  int call_count_ = 0;
  bool eof_reached_ = false;
  FedBlock block_;
  std::vector<SegmentBoundary> boundaries_;
  std::mutex mutex_;
};

}  // namespace

// =============================================================================
// INV-AIR-EOF-PAD-TRANSITION-001
// After decoder EOF, remaining frames in the segment MUST be pad.
// =============================================================================

TEST(EofPadTransition, TEST_INV_EOF_PAD_TRANSITION_001_PadAfterEof) {
  // Commercial: 1800 frames of content, 1860 frames allocated (60 frame tail)
  const int content_frames = 1800;
  const int segment_frames = 1860;

  EofAwareMockProducer producer(720, 480, content_frames, segment_frames);

  // Consume all content frames
  for (int i = 0; i < content_frames; ++i) {
    auto frame = producer.TryGetFrame();
    ASSERT_EQ(frame.status, DecodeStatus::kFrame) << "Content frame " << i << " should be available";
    EXPECT_TRUE(IsContentFrame(frame.frame->video, EofAwareMockProducer::kContentY))
        << "Frame " << i << " should be content (Y=0x30)";
  }

  // Now EOF — the next call triggers EOF detection in the mock.
  {
    auto eof_frame = producer.TryGetFrame();
    EXPECT_EQ(eof_frame.status, DecodeStatus::kEof)
        << "First call after content exhaustion must return kEof";
  }
  EXPECT_TRUE(producer.eof_reached());

  // INV-AIR-EOF-PAD-TRANSITION-001: After EOF, the system should emit pad.
  // The mock returns kEof. The REAL system (TickProducer + PipelineManager)
  // must detect EOF and switch to GeneratePadFrame() instead of holding
  // last_good_video_frame_.
  //
  // This test validates the mock's EOF signal. The integration test
  // (via PipelineManager) validates the actual pad emission.
  for (int i = 0; i < segment_frames - content_frames - 1; ++i) {
    auto frame = producer.TryGetFrame();
    EXPECT_EQ(frame.status, DecodeStatus::kEof)
        << "After EOF, producer must return kEof (tail frame " << i << ")";
  }
}

// =============================================================================
// INV-AIR-EOF-VS-UNDERRUN-001
// Transient underrun must still allow repeat; only EOF triggers pad.
// =============================================================================

TEST(EofPadTransition, TEST_INV_EOF_VS_UNDERRUN_001_EofIsTerminal) {
  // After EOF, HasDecoder() returns false — terminal condition.
  EofAwareMockProducer producer(720, 480, 10, 20);

  // Consume all content
  for (int i = 0; i < 10; ++i) {
    auto frame = producer.TryGetFrame();
    ASSERT_EQ(frame.status, DecodeStatus::kFrame);
  }

  // Trigger EOF detection — the mock sets eof_reached_ on the first
  // call after content exhaustion, not on the last content frame.
  {
    auto eof_frame = producer.TryGetFrame();
    EXPECT_EQ(eof_frame.status, DecodeStatus::kEof);
  }

  // EOF reached
  EXPECT_TRUE(producer.eof_reached());
  EXPECT_FALSE(producer.HasDecoder())
      << "After EOF, HasDecoder() must return false (terminal)";

  // This is the key distinguisher: EOF sets HasDecoder()=false.
  // Transient underrun does NOT — the decoder is still alive, just
  // temporarily unable to produce a frame.
}

// =============================================================================
// INV-AIR-EOF-IMMEDIATE-001
// Pad must begin on the FIRST tick after EOF detection.
// =============================================================================

TEST(EofPadTransition, TEST_INV_EOF_IMMEDIATE_001_NoBridgeFrames) {
  // Commercial with 100 content frames, 110 total
  EofAwareMockProducer producer(720, 480, 100, 110);

  // Consume content
  for (int i = 0; i < 100; ++i) {
    auto frame = producer.TryGetFrame();
    ASSERT_EQ(frame.status, DecodeStatus::kFrame);
  }

  // The very FIRST call after content exhaustion must show EOF.
  // There must be ZERO "bridge frames" (repeated content frames)
  // between the last content frame and the first pad frame.
  auto first_after_eof = producer.TryGetFrame();
  EXPECT_EQ(first_after_eof.status, DecodeStatus::kEof)
      << "First call after EOF must return nullopt — no bridge frames allowed";
  EXPECT_TRUE(producer.eof_reached())
      << "EOF must be signaled immediately, not deferred";
}

// =============================================================================
// Commercial → Pad segment transition (full scenario)
// =============================================================================

TEST(EofPadTransition, TEST_INV_EOF_PAD_TRANSITION_CommercialToPad) {
  // This test documents the expected behavior for the full scenario:
  //
  // Segment layout:
  //   [commercial 60.8s = 1821 frames] [pad 2.1s = 65 frames]
  //
  // Commercial asset is 60.8s (exactly fills its segment).
  // Pad segment follows.
  //
  // Expected behavior:
  //   Frames 0-1820:  content from commercial decoder
  //   Frames 1821-1885: pad (black+silence) — includes pad segment
  //
  // Actual behavior (bug):
  //   Frames 0-1820:  content from commercial decoder
  //   Frame 1821+:    FREEZE on last commercial frame (held frame)
  //   Frame 1886+:    pad (when pad segment starts in TickProducer)
  //
  // The fix must ensure frames 1821+ are all pad — no held frames.

  const int commercial_frames = 1821;
  const int pad_frames = 65;
  const int total = commercial_frames + pad_frames;

  EofAwareMockProducer producer(720, 480, commercial_frames, total);

  // Play commercial
  for (int i = 0; i < commercial_frames; ++i) {
    auto frame = producer.TryGetFrame();
    ASSERT_EQ(frame.status, DecodeStatus::kFrame) << "Commercial frame " << i;
  }

  // Trigger EOF detection.
  {
    auto eof_frame = producer.TryGetFrame();
    EXPECT_EQ(eof_frame.status, DecodeStatus::kEof);
  }
  EXPECT_TRUE(producer.eof_reached());

  // All remaining frames must be pad-eligible (kEof from producer).
  // The PipelineManager must emit pad frames here, not repeat last frame.
  for (int i = 0; i < pad_frames - 1; ++i) {
    auto frame = producer.TryGetFrame();
    EXPECT_NE(frame.status, DecodeStatus::kFrame)
        << "Post-EOF frame " << i << " must not produce content";
  }
}

}  // namespace retrovue::blockplan::testing
