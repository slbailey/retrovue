// Repository: Retrovue-playout
// Component: PadProducer Contract Tests
// Purpose: Verify INV-PAD-PRODUCER invariants: pre-allocation, correct
//          dimensions, house audio format, black/silence content, CRC32
//          stability, and asset URI sentinel.
// Contract Reference: INV-PAD-PRODUCER
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <cstdint>
#include <cstring>
#include <vector>

#include "retrovue/blockplan/PadProducer.hpp"
#include "retrovue/blockplan/SeamProofTypes.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"

namespace retrovue::blockplan::testing {
namespace {

// Standard FPS table for parameterized tests.
struct FPSEntry {
  int64_t fps_num;
  int64_t fps_den;
  const char* label;
};

static const FPSEntry kStandardFPS[] = {
    {24000, 1001, "23.976"},
    {24, 1, "24"},
    {25, 1, "25"},
    {30000, 1001, "29.97"},
    {30, 1, "30"},
    {60000, 1001, "59.94"},
    {60, 1, "60"},
};

// =============================================================================
// INV-PAD-PRODUCER-001: No per-tick allocation — pre-allocated frames.
// =============================================================================

TEST(PadProducerContract, VideoFrameIsPreallocated) {
  PadProducer pp(1920, 1080, 30, 1);
  const auto* ptr1 = pp.VideoFrame().data.data();
  const auto* ptr2 = pp.VideoFrame().data.data();
  EXPECT_EQ(ptr1, ptr2) << "VideoFrame must return the same pre-allocated buffer";
}

TEST(PadProducerContract, SilenceTemplateIsPreallocated) {
  PadProducer pp(1920, 1080, 30, 1);
  const auto* ptr1 = pp.SilenceTemplate().data.data();
  const auto* ptr2 = pp.SilenceTemplate().data.data();
  EXPECT_EQ(ptr1, ptr2) << "SilenceTemplate must return the same pre-allocated buffer";
}

// =============================================================================
// INV-PAD-PRODUCER-002: Correct video dimensions and audio house format.
// =============================================================================

struct ResolutionCase {
  int width;
  int height;
};

class PadProducerResolutionTest
    : public ::testing::TestWithParam<ResolutionCase> {};

TEST_P(PadProducerResolutionTest, VideoFrameCorrectSize) {
  auto [w, h] = GetParam();
  PadProducer pp(w, h, 30, 1);
  const auto& frame = pp.VideoFrame();
  size_t expected = static_cast<size_t>(w * h + 2 * (w / 2) * (h / 2));
  EXPECT_EQ(frame.data.size(), expected);
}

TEST_P(PadProducerResolutionTest, VideoFrameCorrectDimensions) {
  auto [w, h] = GetParam();
  PadProducer pp(w, h, 30, 1);
  const auto& frame = pp.VideoFrame();
  EXPECT_EQ(frame.width, w);
  EXPECT_EQ(frame.height, h);
}

INSTANTIATE_TEST_SUITE_P(
    Resolutions, PadProducerResolutionTest,
    ::testing::Values(
        ResolutionCase{640, 480},
        ResolutionCase{1280, 720},
        ResolutionCase{1920, 1080}
    ));

TEST(PadProducerContract, AudioMatchesHouseFormat) {
  PadProducer pp(1920, 1080, 30, 1);
  const auto& audio = pp.SilenceTemplate();
  EXPECT_EQ(audio.sample_rate, buffer::kHouseAudioSampleRate);
  EXPECT_EQ(audio.channels, buffer::kHouseAudioChannels);
  EXPECT_TRUE(audio.IsHouseFormat());
}

TEST(PadProducerContract, AudioSampleCountExact) {
  // For each standard FPS, verify the max samples per frame covers one tick.
  for (const auto& fps : kStandardFPS) {
    PadProducer pp(1920, 1080, fps.fps_num, fps.fps_den);
    int64_t sr = static_cast<int64_t>(buffer::kHouseAudioSampleRate);
    int expected = static_cast<int>(
        (sr * fps.fps_den + fps.fps_num - 1) / fps.fps_num);
    EXPECT_GE(pp.MaxSamplesPerFrame(), expected)
        << "MaxSamplesPerFrame insufficient for " << fps.label;
  }
}

TEST(PadProducerContract, AudioMaxSizeSufficient) {
  // Worst case: 23.976fps → ceil(48000 * 1001 / 24000) = 2002 samples.
  PadProducer pp(1920, 1080, 24000, 1001);
  const auto& audio = pp.SilenceTemplate();
  size_t min_bytes = static_cast<size_t>(pp.MaxSamplesPerFrame()) *
                     static_cast<size_t>(buffer::kHouseAudioChannels) *
                     sizeof(int16_t);
  EXPECT_GE(audio.data.size(), min_bytes)
      << "Audio data buffer must be large enough for max samples";
}

// =============================================================================
// INV-PAD-PRODUCER-003: Deterministic content (black video, silent audio).
// =============================================================================

TEST(PadProducerContract, VideoIsBlack) {
  PadProducer pp(1920, 1080, 30, 1);
  const auto& frame = pp.VideoFrame();
  const int y_size = 1920 * 1080;
  const int uv_size = (1920 / 2) * (1080 / 2);

  // Y plane: all 0x10 (broadcast black)
  for (int i = 0; i < y_size; i++) {
    ASSERT_EQ(frame.data[static_cast<size_t>(i)], 0x10)
        << "Y plane byte " << i << " is not broadcast black";
  }

  // U/V planes: all 0x80 (neutral chroma)
  for (int i = y_size; i < y_size + 2 * uv_size; i++) {
    ASSERT_EQ(frame.data[static_cast<size_t>(i)], 0x80)
        << "U/V plane byte " << i << " is not neutral chroma";
  }
}

TEST(PadProducerContract, AudioIsSilent) {
  PadProducer pp(1920, 1080, 30, 1);
  const auto& audio = pp.SilenceTemplate();
  for (size_t i = 0; i < audio.data.size(); i++) {
    ASSERT_EQ(audio.data[i], 0)
        << "Audio data byte " << i << " is not silent";
  }
}

TEST(PadProducerContract, CRC32Identical) {
  PadProducer pp(1920, 1080, 30, 1);
  uint32_t crc1 = pp.VideoCRC32();
  uint32_t crc2 = pp.VideoCRC32();
  EXPECT_EQ(crc1, crc2) << "VideoCRC32 must return identical value on repeated calls";
  EXPECT_NE(crc1, 0u) << "VideoCRC32 should be non-zero for a valid frame";
}

TEST(PadProducerContract, CRC32MatchesComputed) {
  PadProducer pp(1920, 1080, 30, 1);
  const auto& frame = pp.VideoFrame();
  size_t y_size = static_cast<size_t>(frame.width * frame.height);
  uint32_t computed = CRC32YPlane(frame.data.data(),
                                   std::min(y_size, frame.data.size()));
  EXPECT_EQ(pp.VideoCRC32(), computed)
      << "Cached CRC32 must match freshly computed CRC32";
}

// =============================================================================
// INV-PAD-PRODUCER-005: Asset URI sentinel.
// =============================================================================

TEST(PadProducerContract, AssetUriIsSentinel) {
  EXPECT_STREQ(PadProducer::kAssetUri, "internal://pad");
}

// =============================================================================
// PAD primes audio before emission: audio is primed before first video frame.
// PadProducer has no start() — it is ready after construction. No decoder.
// =============================================================================

TEST(PadProducerContract, AudioIsPrimedBeforeFirstVideoFrame) {
  PadProducer pp(640, 480, 30, 1);

  // PadProducer has no start(); construction is the only init. No decoder.
  // Before requesting any video frame: assert "audio depth" > 0 in the sense
  // of "at least one frame's worth of silence is available".
  const int max_samples = pp.MaxSamplesPerFrame();
  ASSERT_GT(max_samples, 0) << "PadProducer must expose at least one sample per frame (audio depth > 0)";

  buffer::AudioFrame& silence = pp.SilenceTemplate();
  const size_t min_bytes = static_cast<size_t>(max_samples) *
                          static_cast<size_t>(buffer::kHouseAudioChannels) *
                          sizeof(int16_t);
  ASSERT_GE(silence.data.size(), min_bytes)
      << "At least one silent audio packet must be available (pre-primed, not lazy)";

  // All samples must be silent (pre-filled zeros).
  for (size_t i = 0; i < silence.data.size(); i++) {
    ASSERT_EQ(silence.data[i], 0) << "PadProducer audio must be pre-primed silence (byte " << i << ")";
  }

  // Request first video frame.
  const buffer::Frame& video = pp.VideoFrame();
  ASSERT_FALSE(video.data.empty()) << "First video frame must be available";

  // Audio PTS <= video PTS. PadProducer does not set video metadata.pts (stays 0);
  // SilenceTemplate().pts_us is 0. So 0 <= 0. Pipeline stamps real PTS when emitting.
  const int64_t audio_pts_us = silence.pts_us;
  const int64_t video_pts = video.metadata.pts;
  EXPECT_LE(audio_pts_us, video_pts)
      << "Audio PTS must be <= video PTS (PadProducer: both 0; pipeline enforces ordering)";

  // Audio PTS monotonic across at least 3 "logical" frames: PadProducer returns
  // the same pre-allocated buffer every time (no lazy generation). Three calls
  // must return the same buffer; pipeline assigns monotonic PTS when emitting.
  const buffer::AudioFrame* p1 = &pp.SilenceTemplate();
  const buffer::AudioFrame* p2 = &pp.SilenceTemplate();
  const buffer::AudioFrame* p3 = &pp.SilenceTemplate();
  EXPECT_EQ(p1, p2) << "Silence must be pre-primed (same buffer every call, not lazily generated)";
  EXPECT_EQ(p2, p3) << "Silence must be pre-primed (same buffer every call, not lazily generated)";
  EXPECT_GE(pp.MaxSamplesPerFrame(), 1) << "At least one audio frame's worth of samples";

  // No "audio not primed" state: from construction we have silence ready and
  // never need a decoder. PadProducer has no decoder (it is a data source only).
  EXPECT_TRUE(silence.IsHouseFormat()) << "House format required for emission";
}

}  // namespace
}  // namespace retrovue::blockplan::testing
