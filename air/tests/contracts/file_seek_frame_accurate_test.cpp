// AIR vNext — FileSourceProducer::SeekFrameAccurate contract test (C1.4d).
//
// Validates INV-SEAM-LATE-SUCCESSOR-JIP-001's frame-accuracy contract at
// the primitive level: after SeekFrameAccurate(offset_ms), the FIRST
// emitted video frame MUST have source_pts_us >= offset_ms * 1000.
//
// Distinguishing from keyframe-close: a passing test proves the decoder
// consumed and discarded frames between the landed keyframe and the
// target, not merely that it seeked. Target offsets are chosen to land
// between keyframes in SampleA's GOP structure; if the test ever passed
// without forward decode-and-discard, it would mean the keyframe
// happened to align with the target (unlikely for arbitrary offsets).

#include <gtest/gtest.h>

#include <cstdlib>
#include <filesystem>
#include <string>

#include "file_source_producer.hpp"

namespace retrovue::air {
namespace {

std::string ResolveSampleA() {
  if (const char* env = std::getenv("AIR_VNEXT_TEST_MEDIA")) return env;
#ifdef AIR_VNEXT_SAMPLE_A_PATH
  return AIR_VNEXT_SAMPLE_A_PATH;
#else
  return "";
#endif
}

std::unique_ptr<FileSourceProducer> OpenSampleA() {
  const std::string asset = ResolveSampleA();
  if (!std::filesystem::exists(asset)) return nullptr;
  auto src = std::make_unique<FileSourceProducer>(
      FileSourceProducer::Config{.file_path = asset});
  if (!src->Prepare()) return nullptr;
  if (!src->Activate()) return nullptr;
  return src;
}

TEST(FileSeekFrameAccurateTest, FirstFrameIsAtOrAfterTarget500ms) {
  auto src = OpenSampleA();
  if (!src) GTEST_SKIP() << "SampleA not available";

  const int64_t target_ms = 500;
  ASSERT_TRUE(src->SeekFrameAccurate(target_ms));

  auto vf = src->PullVideo();
  ASSERT_TRUE(vf.has_value())
      << "frame-accurate seek should leave at least one frame queued";
  EXPECT_GE(vf->source_pts_us, target_ms * 1000)
      << "first post-seek frame PTS is before target — forward discard failed "
         "(landed on keyframe without decode-forward)";
}

TEST(FileSeekFrameAccurateTest, FirstFrameIsCloseToTarget1500ms) {
  // SampleA is ~30s; 1500ms is comfortably in the middle. Target lies
  // between keyframes for typical H.264 encoding (GOP ~1-2s), so the
  // landed keyframe is likely earlier than target — the discard loop
  // is genuinely exercised.
  auto src = OpenSampleA();
  if (!src) GTEST_SKIP() << "SampleA not available";

  const int64_t target_ms = 1500;
  ASSERT_TRUE(src->SeekFrameAccurate(target_ms));

  auto vf = src->PullVideo();
  ASSERT_TRUE(vf.has_value());
  EXPECT_GE(vf->source_pts_us, target_ms * 1000);
  // Upper bound: first at-or-after frame should be within one video
  // frame period (33.37ms @ 30000/1001 fps) of the target. Any larger
  // gap indicates stream discontinuity or a decode issue.
  EXPECT_LT(vf->source_pts_us, (target_ms + 100) * 1000)
      << "first post-seek frame is more than 100ms past target — "
         "unexpected gap at discard loop exit";
}

TEST(FileSeekFrameAccurateTest, SubsequentFramesContinueMonotonically) {
  // Post-seek PullVideo MUST return frames in strictly-increasing PTS
  // order starting from the target-satisfying frame. Catches bugs where
  // the discard loop accidentally skips past the target or leaves the
  // queue in a broken state.
  auto src = OpenSampleA();
  if (!src) GTEST_SKIP() << "SampleA not available";

  const int64_t target_ms = 2000;
  ASSERT_TRUE(src->SeekFrameAccurate(target_ms));

  int64_t last_pts = -1;
  int pulled = 0;
  for (int i = 0; i < 10; ++i) {
    auto vf = src->PullVideo();
    if (!vf.has_value()) break;
    if (i == 0) {
      EXPECT_GE(vf->source_pts_us, target_ms * 1000);
    }
    EXPECT_GT(vf->source_pts_us, last_pts) << "PTS regression at frame " << i;
    last_pts = vf->source_pts_us;
    ++pulled;
  }
  EXPECT_GE(pulled, 5) << "expected at least 5 frames after seek";
}

TEST(FileSeekFrameAccurateTest, ZeroOffsetLandsAtAssetStart) {
  // Edge case: offset = 0. Forward discard should be a no-op; first
  // frame's PTS should be near 0.
  auto src = OpenSampleA();
  if (!src) GTEST_SKIP() << "SampleA not available";

  ASSERT_TRUE(src->SeekFrameAccurate(0));

  auto vf = src->PullVideo();
  ASSERT_TRUE(vf.has_value());
  EXPECT_GE(vf->source_pts_us, 0);
  EXPECT_LT(vf->source_pts_us, 100 * 1000)
      << "offset=0 should land within 100ms of asset start";
}

TEST(FileSeekFrameAccurateTest, FailsGracefullyInWrongLifecycle) {
  const std::string asset = ResolveSampleA();
  if (!std::filesystem::exists(asset)) {
    GTEST_SKIP() << "SampleA not available";
  }
  FileSourceProducer src(FileSourceProducer::Config{.file_path = asset});
  // Not Prepared yet → SeekTo should fail → SeekFrameAccurate returns false.
  EXPECT_FALSE(src.SeekFrameAccurate(500));
}

}  // namespace
}  // namespace retrovue::air
