// AIR vNext — slice 5 contract test.
//
// Validates: FileSourceProducer decodes a real media file and feeds
// StandardNormalizer end-to-end into channel-canonical preview output.
//
// Test fixtures: /opt/retrovue/assets/SampleA.mp4 and SampleB.mp4.
// Both are ~30s 720x480 H.264 at 30000/1001 fps, AAC 48kHz stereo.
//
// Integration test uses a 720x480 channel canonical (matching the source
// resolution) so StandardNormalizer is effectively passthrough. Production
// channel canonical is 968x720 per cheers-24-7.yaml — that mismatch
// requires swscale, which is a deferred slice.
//
// Paths are injected via compile definitions from CMake. Override at
// runtime via AIR_VNEXT_TEST_MEDIA env var if needed.

#include <gtest/gtest.h>

#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <optional>
#include <string>

#include "channel_canonical.hpp"
#include "file_source_producer.hpp"
#include "preview_buffer.hpp"
#include "standard_normalizer.hpp"

namespace retrovue::air {
namespace {

std::string ResolveSampleA() {
  if (const char* env = std::getenv("AIR_VNEXT_TEST_MEDIA")) {
    return std::string(env);
  }
#ifdef AIR_VNEXT_SAMPLE_A_PATH
  return std::string(AIR_VNEXT_SAMPLE_A_PATH);
#else
  return "";
#endif
}

std::string ResolveSampleB() {
#ifdef AIR_VNEXT_SAMPLE_B_PATH
  return std::string(AIR_VNEXT_SAMPLE_B_PATH);
#else
  return "";
#endif
}

bool FixtureExists(const std::string& path) {
  std::ifstream f(path);
  return f.good();
}

// Channel canonical matching cheers-24-7.yaml: 968x720 NTSC, 48kHz stereo.
// Source (SampleA/B) is 720x480 at the same NTSC rate, so StandardNormalizer
// invokes swscale to rescale each frame from 720x480 to 968x720. This is
// the real-production shape.
ChannelCanonical ChannelCheers247() {
  return ChannelCanonical{
      .video = VideoCanonical{.width = 968,
                              .height = 720,
                              .frame_rate = {30000, 1001},
                              .pixel_format = PixelFormat::kYuv420p},
      .audio = AudioCanonical{.sample_rate = 48000, .channels = 2}};
}

// ---------------------------------------------------------------------------
// Open + stream info.
// ---------------------------------------------------------------------------

TEST(FileSourceProducer, OpensSampleAAndReportsStreamInfo) {
  const std::string path = ResolveSampleA();
  if (!FixtureExists(path)) {
    GTEST_SKIP() << "SampleA not found at " << path;
  }

  FileSourceProducer src({.file_path = path});
  ASSERT_TRUE(src.Prepare()) << "failed to open " << path;
  ASSERT_TRUE(src.Activate());

  EXPECT_TRUE(src.HasVideoStream());
  EXPECT_EQ(src.VideoWidth(), 720);
  EXPECT_EQ(src.VideoHeight(), 480);

  const Rational vr = src.VideoFrameRate();
  EXPECT_EQ(vr.num, 30000);
  EXPECT_EQ(vr.den, 1001);

  EXPECT_TRUE(src.HasAudioStream());
  EXPECT_EQ(src.AudioSampleRate(), 48000);
  EXPECT_EQ(src.AudioChannels(), 2);

  src.Retire();
}

TEST(FileSourceProducer, OpensSampleBAndReportsStreamInfo) {
  const std::string path = ResolveSampleB();
  if (!FixtureExists(path)) GTEST_SKIP() << "SampleB not found at " << path;

  FileSourceProducer src({.file_path = path});
  ASSERT_TRUE(src.Prepare());
  ASSERT_TRUE(src.Activate());

  EXPECT_EQ(src.VideoWidth(), 720);
  EXPECT_EQ(src.VideoHeight(), 480);
  EXPECT_EQ(src.AudioSampleRate(), 48000);
  EXPECT_EQ(src.AudioChannels(), 2);
}

// ---------------------------------------------------------------------------
// First video frame is well-formed: correct dimensions, correct payload
// size for YUV420P, non-negative source PTS.
// ---------------------------------------------------------------------------

TEST(FileSourceProducer, FirstVideoFrameIsYuv420pAndSized) {
  const std::string path = ResolveSampleA();
  if (!FixtureExists(path)) GTEST_SKIP();

  FileSourceProducer src({.file_path = path});
  ASSERT_TRUE(src.Prepare());
  ASSERT_TRUE(src.Activate());

  auto vf = src.PullVideo();
  ASSERT_TRUE(vf.has_value());
  EXPECT_EQ(vf->width, 720);
  EXPECT_EQ(vf->height, 480);

  const int y = 720 * 480;
  const int uv = (720 / 2) * (480 / 2);
  EXPECT_EQ(static_cast<int>(vf->data.size()), y + 2 * uv);

  // Source PTS should be non-negative for a well-formed container.
  EXPECT_GE(vf->source_pts_us, 0);
}

// ---------------------------------------------------------------------------
// Video source PTS advances monotonically across frames.
// ---------------------------------------------------------------------------

TEST(FileSourceProducer, VideoSourcePtsMonotonic) {
  const std::string path = ResolveSampleA();
  if (!FixtureExists(path)) GTEST_SKIP();

  FileSourceProducer src({.file_path = path});
  ASSERT_TRUE(src.Prepare());
  ASSERT_TRUE(src.Activate());

  int64_t prev = -1;
  for (int i = 0; i < 10; ++i) {
    auto vf = src.PullVideo();
    ASSERT_TRUE(vf.has_value()) << "i=" << i;
    EXPECT_GT(vf->source_pts_us, prev) << "i=" << i;
    prev = vf->source_pts_us;
  }
}

// ---------------------------------------------------------------------------
// Audio first block: sample rate, channel count, S16 interleaved size.
// ---------------------------------------------------------------------------

TEST(FileSourceProducer, FirstAudioBlockWellFormed) {
  const std::string path = ResolveSampleA();
  if (!FixtureExists(path)) GTEST_SKIP();

  FileSourceProducer src({.file_path = path});
  ASSERT_TRUE(src.Prepare());
  ASSERT_TRUE(src.Activate());

  auto ab = src.PullAudio();
  ASSERT_TRUE(ab.has_value());
  EXPECT_EQ(ab->sample_rate, 48000);
  EXPECT_EQ(ab->channels, 2);
  EXPECT_GT(ab->nb_samples, 0);
  EXPECT_EQ(static_cast<int>(ab->data.size()),
            ab->nb_samples * ab->channels);
  EXPECT_GE(ab->source_pts_us, 0);
}

// ---------------------------------------------------------------------------
// End-to-end: FileSource -> StandardNormalizer -> preview. The file's
// rate matches channel exactly (30000/1001, 48kHz), so Normalizer is
// effectively passthrough. Verifies the full stack wires correctly with
// real decoded media.
// ---------------------------------------------------------------------------

TEST(FileSourceProducerIntegration, FullPipelineToPreviewWithScaling) {
  const std::string path = ResolveSampleA();
  if (!FixtureExists(path)) GTEST_SKIP();

  auto canonical = ChannelCheers247();

  FileSourceProducer src({.file_path = path});
  ASSERT_TRUE(src.Prepare());
  ASSERT_TRUE(src.Activate());

  // Source: 720x480 @ 30000/1001. Channel: 968x720 @ 30000/1001.
  // Rate matches (passthrough cadence); resolution differs (swscale active).
  const Rational src_fr = src.VideoFrameRate();
  ASSERT_EQ(src_fr.num, canonical.video.frame_rate.num);
  ASSERT_EQ(src_fr.den, canonical.video.frame_rate.den);
  ASSERT_EQ(src.AudioSampleRate(), canonical.audio.sample_rate);
  ASSERT_EQ(src.VideoWidth(), 720);
  ASSERT_EQ(src.VideoHeight(), 480);

  StandardNormalizer norm(canonical, src_fr,
                          src.VideoWidth(), src.VideoHeight(),
                          src.AudioSampleRate(), &src,
                          {.source_pts_anchor_us = 0,
                           .channel_pts_anchor_us = 0},
                          /*samples_per_channel_audio_block=*/1601);
  VideoPreviewBuffer vp(/*capacity_frames=*/60);
  AudioPreviewBuffer ap(/*capacity_blocks=*/60);

  // Fill 30 channel frames (~1 second of NTSC video) through the pipeline.
  // Every frame coming out of the Normalizer must be at CHANNEL resolution
  // (968x720), not source resolution (720x480).
  const int ch_y = canonical.video.width * canonical.video.height;
  const int ch_uv = (canonical.video.width / 2) * (canonical.video.height / 2);
  const int ch_frame_bytes = ch_y + 2 * ch_uv;

  for (int k = 0; k < 30; ++k) {
    auto vf = norm.PullVideo();
    ASSERT_TRUE(vf.has_value()) << "channel frame k=" << k;
    EXPECT_EQ(vf->pts_us_relative,
              canonical.video.frame_rate.NthStepPtsUs(k))
        << "k=" << k;
    // Scaling contract: output payload is channel-canonical size.
    EXPECT_EQ(static_cast<int>(vf->data.size()), ch_frame_bytes)
        << "k=" << k << " (source was 720x480; should be scaled to "
        << canonical.video.width << "x" << canonical.video.height << ")";
    ASSERT_TRUE(vp.Push(*vf));
  }

  EXPECT_EQ(vp.Depth(), 30);
  ASSERT_TRUE(vp.FrontPtsUsRelative().has_value());
  EXPECT_EQ(*vp.FrontPtsUsRelative(), 0);
  ASSERT_TRUE(vp.BackPtsUsRelative().has_value());
  EXPECT_EQ(*vp.BackPtsUsRelative(),
            canonical.video.frame_rate.NthStepPtsUs(29));

  // Aspect preservation check: 720x480 source (aspect 1.5) into 968x720
  // channel (aspect 1.344). Width is the limiting dim, so the scaled
  // image fills the full channel width. Height is letterboxed — the top
  // and bottom rows of Y plane must be broadcast-black (0x10).
  //
  // Pop the front frame to inspect. (Preview still exposes its ability
  // to pop; this is testing the actual content.)
  auto inspect = vp.Pop();
  ASSERT_TRUE(inspect.has_value());
  const int dst_w = canonical.video.width;
  const int dst_h = canonical.video.height;
  // Top-left Y pixel must be black (letterbox bar).
  EXPECT_EQ(inspect->data[0], 0x10);
  // A Y pixel in the top row, offset in x, must also be black.
  EXPECT_EQ(inspect->data[dst_w / 2], 0x10);
  // Bottom row last pixel must be black.
  EXPECT_EQ(inspect->data[dst_w * dst_h - 1], 0x10);
  // U and V at top-left must be neutral chroma (0x80).
  const int ch_y_sz = dst_w * dst_h;
  EXPECT_EQ(inspect->data[ch_y_sz], 0x80);                           // U[0,0]
  EXPECT_EQ(inspect->data[ch_y_sz + (dst_w / 2) * (dst_h / 2)], 0x80);  // V[0,0]

  // Pull a few audio blocks and push into preview. Block PTS monotonic.
  int64_t prev_audio = -1;
  for (int b = 0; b < 5; ++b) {
    auto ab = norm.PullAudio();
    ASSERT_TRUE(ab.has_value()) << "audio block b=" << b;
    EXPECT_GT(ab->pts_us_relative, prev_audio);
    prev_audio = ab->pts_us_relative;
    ASSERT_TRUE(ap.Push(*ab));
  }
  EXPECT_EQ(ap.Depth(), 5);
}

}  // namespace
}  // namespace retrovue::air
