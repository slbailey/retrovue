// AIR vNext — Segment fence-tick arithmetic contract tests.
//
// Validates INV-SEAM-FENCE-ARITHMETIC-001:
//   segment_end_utc_ms = block.start_utc_ms + sum(segments[0..N].duration_ms)
//                        (inclusive of segment N)
//   segment_fence_monotonic_us =
//       anchor_monotonic_us + (segment_end_utc_ms - anchor_utc_ms) * 1000
//
// Pure arithmetic tests — no media fixtures, no gRPC, no pipeline state.

#include <gtest/gtest.h>

#include <cstdint>
#include <vector>

#include "block.hpp"
#include "channel_canonical.hpp"
#include "segment.hpp"
#include "segment_fence.hpp"

namespace retrovue::air {
namespace {

// Build a Block with the given start time and segment durations.
// Each segment gets a synthetic id and a dummy asset_uri.
Block MakeBlock(int64_t start_utc_ms,
                std::initializer_list<int64_t> segment_durations_ms) {
  Block b;
  b.block_id = "test-block";
  b.start_utc_ms = start_utc_ms;
  int32_t idx = 0;
  int64_t cumulative = 0;
  for (int64_t d : segment_durations_ms) {
    Segment s;
    s.segment_id = "test-segment-" + std::to_string(idx);
    s.asset_uri = "/dev/null";
    s.asset_start_offset_ms = 0;
    s.duration_ms = d;
    s.segment_index = idx++;
    b.segments.push_back(s);
    cumulative += d;
  }
  b.end_utc_ms = start_utc_ms + cumulative;
  return b;
}

TEST(SegmentFenceTest, SingleSegmentEndUtcEqualsStartPlusDuration) {
  // INV-SEAM-FENCE-ARITHMETIC-001: segment_end_utc_ms = start + sum(0..0).
  const Block b = MakeBlock(1'000, {500});
  const auto end = SegmentEndUtcMs(b, 0);
  ASSERT_TRUE(end.has_value());
  EXPECT_EQ(*end, 1'500);
}

TEST(SegmentFenceTest, ThreeSegmentsAccumulateInclusively) {
  // Durations [100, 200, 300]. End of segment 0 = start + 100.
  // End of segment 1 = start + 100 + 200. End of segment 2 = start + 600.
  const Block b = MakeBlock(10'000, {100, 200, 300});

  const auto end0 = SegmentEndUtcMs(b, 0);
  const auto end1 = SegmentEndUtcMs(b, 1);
  const auto end2 = SegmentEndUtcMs(b, 2);

  ASSERT_TRUE(end0.has_value());
  ASSERT_TRUE(end1.has_value());
  ASSERT_TRUE(end2.has_value());
  EXPECT_EQ(*end0, 10'100);
  EXPECT_EQ(*end1, 10'300);
  EXPECT_EQ(*end2, 10'600);
  // Sanity: end of last segment equals block.end_utc_ms for a well-formed
  // block. This is not an invariant per se; it's a consistency check of
  // block construction.
  EXPECT_EQ(*end2, b.end_utc_ms);
}

TEST(SegmentFenceTest, FenceMonotonicAnchorConversion) {
  // Anchor: mono=1'000'000 us, utc=2'000 ms.
  // Segment ends at utc=5'000 ms (2s of wall time after anchor).
  // Expected monotonic fence: 1'000'000 + (5'000 - 2'000) * 1000
  //                         = 1'000'000 + 3'000'000 = 4'000'000 us.
  const Block b = MakeBlock(2'000, {3'000});
  const SessionAnchor anchor{.anchor_monotonic_us = 1'000'000,
                             .anchor_utc_ms = 2'000};
  const auto fence = SegmentFenceMonotonicUs(b, 0, anchor);
  ASSERT_TRUE(fence.has_value());
  EXPECT_EQ(*fence, 4'000'000);
}

TEST(SegmentFenceTest, FenceMonotonicPreservesRelativeOffsetsAcrossSegments) {
  // With anchor (mono=0, utc=0) and block.start=1000ms, three segments
  // of 100/200/300ms each. Monotonic fences should be at
  // (1000+100)*1000, (1000+300)*1000, (1000+600)*1000 us respectively.
  const Block b = MakeBlock(1'000, {100, 200, 300});
  const SessionAnchor anchor{.anchor_monotonic_us = 0, .anchor_utc_ms = 0};

  const auto f0 = SegmentFenceMonotonicUs(b, 0, anchor);
  const auto f1 = SegmentFenceMonotonicUs(b, 1, anchor);
  const auto f2 = SegmentFenceMonotonicUs(b, 2, anchor);
  ASSERT_TRUE(f0.has_value());
  ASSERT_TRUE(f1.has_value());
  ASSERT_TRUE(f2.has_value());
  EXPECT_EQ(*f0, 1'100'000);
  EXPECT_EQ(*f1, 1'300'000);
  EXPECT_EQ(*f2, 1'600'000);

  // Fences strictly increase across segments (implied by arithmetic; checked).
  EXPECT_LT(*f0, *f1);
  EXPECT_LT(*f1, *f2);
}

TEST(SegmentFenceTest, OutOfRangeSegmentIndexReturnsNullopt) {
  const Block b = MakeBlock(0, {100, 200});
  const SessionAnchor anchor{};
  EXPECT_FALSE(SegmentEndUtcMs(b, -1).has_value());
  EXPECT_FALSE(SegmentEndUtcMs(b, 2).has_value());
  EXPECT_FALSE(SegmentEndUtcMs(b, 99).has_value());
  EXPECT_FALSE(SegmentFenceMonotonicUs(b, -1, anchor).has_value());
  EXPECT_FALSE(SegmentFenceMonotonicUs(b, 2, anchor).has_value());
}

TEST(SegmentFenceTest, EmptyBlockReturnsNulloptForAllQueries) {
  Block b;
  b.start_utc_ms = 1'000;
  const SessionAnchor anchor{};
  EXPECT_FALSE(SegmentEndUtcMs(b, 0).has_value());
  EXPECT_FALSE(SegmentFenceMonotonicUs(b, 0, anchor).has_value());
  EXPECT_FALSE(BlockFinalFenceMonotonicUs(b, anchor).has_value());
  EXPECT_EQ(TotalSegmentDurationMs(b), 0);
}

TEST(SegmentFenceTest, BlockFinalFenceEqualsLastSegmentFence) {
  const Block b = MakeBlock(500, {100, 200, 300});
  const SessionAnchor anchor{.anchor_monotonic_us = 7'000'000,
                             .anchor_utc_ms = 500};
  const auto last = SegmentFenceMonotonicUs(b, 2, anchor);
  const auto final = BlockFinalFenceMonotonicUs(b, anchor);
  ASSERT_TRUE(last.has_value());
  ASSERT_TRUE(final.has_value());
  EXPECT_EQ(*last, *final);
}

TEST(SegmentFenceTest, TotalSegmentDurationMatchesBlockSpan) {
  // For a well-formed block, total segment duration should equal
  // end_utc_ms - start_utc_ms. This is a data-integrity check, not
  // INV-SEAM-FENCE-ARITHMETIC-001 itself.
  const Block b = MakeBlock(2'000, {400, 600, 1'000});
  EXPECT_EQ(TotalSegmentDurationMs(b), 2'000);
  EXPECT_EQ(b.end_utc_ms - b.start_utc_ms, 2'000);
}

// ---- C2.1: inter-block fence arithmetic -------------------------------

TEST(SegmentFenceTest, IsLastSegmentOfBlockIdentifiesFinalIndex) {
  const Block b = MakeBlock(0, {100, 200, 300});
  EXPECT_FALSE(IsLastSegmentOfBlock(b, 0));
  EXPECT_FALSE(IsLastSegmentOfBlock(b, 1));
  EXPECT_TRUE(IsLastSegmentOfBlock(b, 2));
  EXPECT_FALSE(IsLastSegmentOfBlock(b, 3));   // out of range
  EXPECT_FALSE(IsLastSegmentOfBlock(b, -1));  // negative
}

TEST(SegmentFenceTest, IsLastSegmentOfBlockHandlesSingleSegment) {
  const Block b = MakeBlock(0, {500});
  EXPECT_TRUE(IsLastSegmentOfBlock(b, 0));
}

TEST(SegmentFenceTest, IsLastSegmentOfBlockHandlesEmpty) {
  Block b;
  b.start_utc_ms = 0;
  EXPECT_FALSE(IsLastSegmentOfBlock(b, 0));
  EXPECT_FALSE(IsLastSegmentOfBlock(b, -1));
}

TEST(SegmentFenceTest, BlockFinalFenceEqualsSuccessorFirstSegmentStart) {
  // Inter-block fence continuity (well-formed schedule): if Block B
  // immediately follows Block A in the editorial timeline, then
  // A.end_utc_ms == B.start_utc_ms. The monotonic fence at A's final
  // segment equals the monotonic "start" of B, which in turn equals
  // B.segments[0]'s monotonic fence minus B.segments[0].duration_ms * 1000.
  //
  // This test establishes the arithmetic relationship that the C2 seam
  // mechanism depends on: A's final seam fence IS the moment B.segment[0]
  // begins playing.
  const Block a = MakeBlock(1'000, {300, 400, 500});  // ends at 2'200
  Block b = MakeBlock(2'200, {600, 700});              // starts at A's end
  const SessionAnchor anchor{.anchor_monotonic_us = 100'000'000,
                             .anchor_utc_ms = 1'000};

  const auto a_final = BlockFinalFenceMonotonicUs(a, anchor);
  const auto b_first_end = SegmentFenceMonotonicUs(b, 0, anchor);
  ASSERT_TRUE(a_final.has_value());
  ASSERT_TRUE(b_first_end.has_value());

  // a_final = monotonic at UTC 2200ms = 100'000'000 + 1200 * 1000 = 101'200'000
  EXPECT_EQ(*a_final, 101'200'000);
  // b_first_end = monotonic at UTC 2800ms = 100'000'000 + 1800 * 1000 = 101'800'000
  EXPECT_EQ(*b_first_end, 101'800'000);
  // Delta equals B.segments[0].duration_ms * 1000.
  EXPECT_EQ(*b_first_end - *a_final, 600 * 1000);
}

TEST(SegmentFenceTest, FencesStrictlyIncreaseAcrossBlockBoundary) {
  // Extension of the "fences strictly increase across segments" property
  // to the inter-block case. Anchor + well-formed A,B blocks; every
  // successive fence (A's internal + A's final + B's internal) is
  // strictly greater than its predecessor.
  const Block a = MakeBlock(0, {100, 200, 300});       // fences at 100, 300, 600
  const Block b = MakeBlock(600, {400, 500});          // fences at 1000, 1500
  const SessionAnchor anchor{.anchor_monotonic_us = 0, .anchor_utc_ms = 0};

  std::vector<int64_t> monotonic_fences;
  for (int32_t i = 0; i < 3; ++i) {
    monotonic_fences.push_back(*SegmentFenceMonotonicUs(a, i, anchor));
  }
  for (int32_t i = 0; i < 2; ++i) {
    monotonic_fences.push_back(*SegmentFenceMonotonicUs(b, i, anchor));
  }

  ASSERT_EQ(monotonic_fences.size(), 5u);
  for (std::size_t i = 1; i < monotonic_fences.size(); ++i) {
    EXPECT_LT(monotonic_fences[i - 1], monotonic_fences[i])
        << "fence regression at boundary " << i;
  }
  // Specific sanity: A's final fence == monotonic at UTC 600ms.
  EXPECT_EQ(monotonic_fences[2], 600 * 1000);
  // B's first fence == monotonic at UTC 1000ms.
  EXPECT_EQ(monotonic_fences[3], 1000 * 1000);
}

TEST(SegmentFenceTest, BlockBoundaryArithmeticUsesSessionAnchorConsistently) {
  // A subtle invariant: both Block A and Block B use the SAME session
  // anchor (established once at OnAir entry per AIR vNext). Arithmetic
  // must not require Block B to re-anchor. Verify by using a non-zero
  // anchor and checking that B's fences are derived from
  //   anchor_monotonic_us + (B.end_utc - anchor_utc_ms) * 1000
  // not from
  //   anchor_monotonic_us + B.start_relative * 1000
  const Block a = MakeBlock(5'000, {1'000});  // UTC 5000..6000
  const Block b = MakeBlock(6'000, {2'000});  // UTC 6000..8000
  const SessionAnchor anchor{.anchor_monotonic_us = 1'000'000'000,
                             .anchor_utc_ms = 5'000};

  // A's single segment fence = anchor_mono + (6000-5000)*1000 = 1'001'000'000
  EXPECT_EQ(*SegmentFenceMonotonicUs(a, 0, anchor), 1'001'000'000);
  // B's single segment fence = anchor_mono + (8000-5000)*1000 = 1'003'000'000
  EXPECT_EQ(*SegmentFenceMonotonicUs(b, 0, anchor), 1'003'000'000);
}

}  // namespace
}  // namespace retrovue::air
