// AIR vNext — IR2.1 structural block validation unit tests.
//
// Pure-function coverage of ValidateBlockStructure across all four
// reason codes, the happy path, and the nullptr reason_out contract.

#include <gtest/gtest.h>

#include <string>

#include "block.hpp"
#include "block_validation.hpp"
#include "channel_canonical.hpp"

namespace retrovue::air {
namespace {

Segment MakeSegment(const std::string& id, int32_t index, int64_t duration_ms,
                    const std::string& asset_uri = "/tmp/asset.mp4",
                    int64_t asset_start_offset_ms = 0) {
  Segment s;
  s.segment_id = id;
  s.asset_uri = asset_uri;
  s.asset_start_offset_ms = asset_start_offset_ms;
  s.duration_ms = duration_ms;
  s.segment_index = index;
  return s;
}

// Canonical structure populated so Block::canonical is intrinsically
// valid; not exercised by ValidateBlockStructure (IR2.2 territory),
// but present so call sites look like production blocks.
ChannelCanonical TestCanonical() {
  ChannelCanonical c;
  c.video.width = 968;
  c.video.height = 720;
  c.video.frame_rate = {30000, 1001};
  c.video.pixel_format = PixelFormat::kYuv420p;
  c.audio.sample_rate = 48000;
  c.audio.channels = 2;
  return c;
}

Block MakeValidBlock() {
  Block b;
  b.block_id = "A";
  b.start_utc_ms = 1'700'000'000'000LL;
  b.end_utc_ms = 1'700'000'000'000LL + 3000;
  b.canonical = TestCanonical();
  b.segments.push_back(MakeSegment("A:0", 0, 1000));
  b.segments.push_back(MakeSegment("A:1", 1, 1000));
  b.segments.push_back(MakeSegment("A:2", 2, 1000));
  return b;
}

TEST(BlockValidationTest, HappyPathAcceptsWellFormedBlock) {
  const Block b = MakeValidBlock();
  std::string reason = "should_not_be_touched";
  EXPECT_TRUE(ValidateBlockStructure(b, &reason));
  EXPECT_EQ(reason, "should_not_be_touched");
}

TEST(BlockValidationTest, HappyPathWithNullReasonOut) {
  const Block b = MakeValidBlock();
  EXPECT_TRUE(ValidateBlockStructure(b, nullptr));
}

TEST(BlockValidationTest, EmptySegmentsRejected) {
  Block b = MakeValidBlock();
  b.segments.clear();
  std::string reason;
  EXPECT_FALSE(ValidateBlockStructure(b, &reason));
  EXPECT_EQ(reason, "EMPTY_SEGMENTS");
}

TEST(BlockValidationTest, InvalidTimeWindowNonPositiveStart) {
  Block b = MakeValidBlock();
  b.start_utc_ms = 0;
  b.end_utc_ms = 3000;
  std::string reason;
  EXPECT_FALSE(ValidateBlockStructure(b, &reason));
  EXPECT_EQ(reason, "INVALID_TIME_WINDOW");
}

TEST(BlockValidationTest, InvalidTimeWindowNegativeStart) {
  Block b = MakeValidBlock();
  b.start_utc_ms = -1;
  b.end_utc_ms = 1000;
  std::string reason;
  EXPECT_FALSE(ValidateBlockStructure(b, &reason));
  EXPECT_EQ(reason, "INVALID_TIME_WINDOW");
}

TEST(BlockValidationTest, InvalidTimeWindowEndLeqStart) {
  Block b = MakeValidBlock();
  b.end_utc_ms = b.start_utc_ms;  // zero-width window
  std::string reason;
  EXPECT_FALSE(ValidateBlockStructure(b, &reason));
  EXPECT_EQ(reason, "INVALID_TIME_WINDOW");
}

TEST(BlockValidationTest, MalformedSegmentEmptyAssetUri) {
  Block b = MakeValidBlock();
  b.segments[1].asset_uri.clear();
  std::string reason;
  EXPECT_FALSE(ValidateBlockStructure(b, &reason));
  EXPECT_EQ(reason, "MALFORMED_SEGMENT");
}

TEST(BlockValidationTest, MalformedSegmentZeroDuration) {
  Block b = MakeValidBlock();
  b.segments[0].duration_ms = 0;
  std::string reason;
  EXPECT_FALSE(ValidateBlockStructure(b, &reason));
  EXPECT_EQ(reason, "MALFORMED_SEGMENT");
}

TEST(BlockValidationTest, MalformedSegmentNegativeDuration) {
  Block b = MakeValidBlock();
  b.segments[2].duration_ms = -100;
  std::string reason;
  EXPECT_FALSE(ValidateBlockStructure(b, &reason));
  EXPECT_EQ(reason, "MALFORMED_SEGMENT");
}

TEST(BlockValidationTest, MalformedSegmentNegativeAssetOffset) {
  Block b = MakeValidBlock();
  b.segments[1].asset_start_offset_ms = -1;
  std::string reason;
  EXPECT_FALSE(ValidateBlockStructure(b, &reason));
  EXPECT_EQ(reason, "MALFORMED_SEGMENT");
}

TEST(BlockValidationTest, MalformedSegmentIndexOutOfOrder) {
  Block b = MakeValidBlock();
  b.segments[2].segment_index = 5;  // should be 2
  std::string reason;
  EXPECT_FALSE(ValidateBlockStructure(b, &reason));
  EXPECT_EQ(reason, "MALFORMED_SEGMENT");
}

TEST(BlockValidationTest, DurationMismatchSumLessThanWindow) {
  Block b = MakeValidBlock();  // 3x1000 = 3000, window = 3000
  b.end_utc_ms += 500;          // window = 3500, sum still 3000
  std::string reason;
  EXPECT_FALSE(ValidateBlockStructure(b, &reason));
  EXPECT_EQ(reason, "DURATION_MISMATCH");
}

TEST(BlockValidationTest, DurationMismatchSumGreaterThanWindow) {
  Block b = MakeValidBlock();  // 3x1000 = 3000, window = 3000
  b.segments[0].duration_ms = 2000;  // sum = 4000, window = 3000
  std::string reason;
  EXPECT_FALSE(ValidateBlockStructure(b, &reason));
  EXPECT_EQ(reason, "DURATION_MISMATCH");
}

// Precedence: empty segments is caught before the window check even
// when both would fire. Documents the deterministic ordering in the
// header comment.
TEST(BlockValidationTest, EmptySegmentsTakesPrecedenceOverInvalidWindow) {
  Block b = MakeValidBlock();
  b.segments.clear();
  b.end_utc_ms = b.start_utc_ms;  // also invalid window
  std::string reason;
  EXPECT_FALSE(ValidateBlockStructure(b, &reason));
  EXPECT_EQ(reason, "EMPTY_SEGMENTS");
}

}  // namespace
}  // namespace retrovue::air
