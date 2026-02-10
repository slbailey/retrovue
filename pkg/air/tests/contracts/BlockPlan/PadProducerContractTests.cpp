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

}  // namespace
}  // namespace retrovue::blockplan::testing
