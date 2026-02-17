// Repository: Retrovue-playout
// Component: Segment Transition Contract Tests
// Purpose: Verifies TransitionType deserialization from proto and fade frame
//          count calculations. Contract: SegmentTransitionContract.md.
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <cmath>
#include <string>
#include <vector>

#include "playout.pb.h"
#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"

namespace retrovue::blockplan::testing {
namespace {

// =============================================================================
// Helper: build a proto BlockSegment with transition fields set
// =============================================================================
static retrovue::playout::BlockSegment MakeProtoSegment(
    int32_t index,
    const std::string& asset_uri,
    int64_t offset_ms,
    int64_t duration_ms,
    retrovue::playout::TransitionType t_in,
    uint32_t t_in_ms,
    retrovue::playout::TransitionType t_out,
    uint32_t t_out_ms) {
  retrovue::playout::BlockSegment seg;
  seg.set_segment_index(index);
  seg.set_asset_uri(asset_uri);
  seg.set_asset_start_offset_ms(offset_ms);
  seg.set_segment_duration_ms(duration_ms);
  seg.set_transition_in(t_in);
  seg.set_transition_in_duration_ms(t_in_ms);
  seg.set_transition_out(t_out);
  seg.set_transition_out_duration_ms(t_out_ms);
  return seg;
}

// =============================================================================
// Helper: build a proto BlockPlan and convert to FedBlock via the same
// logic as ProtoToBlock in playout_service.cpp
// =============================================================================
static FedBlock ProtoBlockToFedBlock(const retrovue::playout::BlockPlan& proto) {
  FedBlock block;
  block.block_id = proto.block_id();
  block.channel_id = proto.channel_id();
  block.start_utc_ms = proto.start_utc_ms();
  block.end_utc_ms = proto.end_utc_ms();

  for (const auto& seg : proto.segments()) {
    FedBlock::Segment s;
    s.segment_index = seg.segment_index();
    s.asset_uri = seg.asset_uri();
    s.asset_start_offset_ms = seg.asset_start_offset_ms();
    s.segment_duration_ms = seg.segment_duration_ms();
    s.segment_type = static_cast<SegmentType>(seg.segment_type());
    s.event_id = seg.event_id();
    // Transition fields (INV-TRANSITION-001..005: SegmentTransitionContract.md)
    s.transition_in = static_cast<TransitionType>(seg.transition_in());
    s.transition_in_duration_ms = seg.transition_in_duration_ms();
    s.transition_out = static_cast<TransitionType>(seg.transition_out());
    s.transition_out_duration_ms = seg.transition_out_duration_ms();
    block.segments.push_back(s);
  }
  return block;
}

// =============================================================================
// Helper: compute fade frame count (mirrors TickProducer logic)
// =============================================================================
static int64_t FadeFrameCount(uint32_t duration_ms, double fps) {
  return static_cast<int64_t>(
      std::ceil(static_cast<double>(duration_ms) * fps / 1000.0));
}

// =============================================================================
// TRANS-001: Default proto values are TRANSITION_NONE
// =============================================================================
TEST(SegmentTransitionTest, DefaultProtoValuesAreNone) {
  retrovue::playout::BlockSegment seg;
  seg.set_segment_index(0);
  seg.set_asset_uri("/media/ep.mkv");
  seg.set_segment_duration_ms(30000);

  // Default enum value in proto3 is 0 = TRANSITION_NONE
  EXPECT_EQ(seg.transition_in(), retrovue::playout::TRANSITION_NONE);
  EXPECT_EQ(seg.transition_out(), retrovue::playout::TRANSITION_NONE);
  EXPECT_EQ(seg.transition_in_duration_ms(), 0u);
  EXPECT_EQ(seg.transition_out_duration_ms(), 0u);
}

// =============================================================================
// TRANS-002: TRANSITION_FADE fields round-trip through proto serialization
// =============================================================================
TEST(SegmentTransitionTest, FadeFieldsRoundTripProto) {
  retrovue::playout::BlockPlan plan;
  plan.set_block_id("blk-test");
  plan.set_channel_id(1);
  plan.set_start_utc_ms(1_000_000_000LL);
  plan.set_end_utc_ms(1_001_800_000LL);

  auto* seg = plan.add_segments();
  seg->set_segment_index(0);
  seg->set_asset_uri("/media/ep01.mkv");
  seg->set_asset_start_offset_ms(0);
  seg->set_segment_duration_ms(600_000);
  seg->set_transition_in(retrovue::playout::TRANSITION_FADE);
  seg->set_transition_in_duration_ms(500);
  seg->set_transition_out(retrovue::playout::TRANSITION_FADE);
  seg->set_transition_out_duration_ms(500);

  // Serialize and deserialize
  std::string serialized;
  ASSERT_TRUE(plan.SerializeToString(&serialized));

  retrovue::playout::BlockPlan plan2;
  ASSERT_TRUE(plan2.ParseFromString(serialized));

  ASSERT_EQ(plan2.segments_size(), 1);
  const auto& seg2 = plan2.segments(0);
  EXPECT_EQ(seg2.transition_in(), retrovue::playout::TRANSITION_FADE);
  EXPECT_EQ(seg2.transition_in_duration_ms(), 500u);
  EXPECT_EQ(seg2.transition_out(), retrovue::playout::TRANSITION_FADE);
  EXPECT_EQ(seg2.transition_out_duration_ms(), 500u);
}

// =============================================================================
// TRANS-003: Proto → FedBlock deserialization maps transition fields correctly
// =============================================================================
TEST(SegmentTransitionTest, ProtoToFedBlockMapsTransitionFields) {
  retrovue::playout::BlockPlan plan;
  plan.set_block_id("blk-trans-test");
  plan.set_channel_id(1);
  plan.set_start_utc_ms(0);
  plan.set_end_utc_ms(1_800_000);

  // Segment 0: second-class, fade-out
  *plan.add_segments() = MakeProtoSegment(
      0, "/media/ep.mkv", 0, 600_000,
      retrovue::playout::TRANSITION_NONE, 0,
      retrovue::playout::TRANSITION_FADE, 500);

  // Segment 1: filler (no transitions)
  auto* filler = plan.add_segments();
  filler->set_segment_index(1);
  filler->set_segment_type(retrovue::playout::SEGMENT_TYPE_FILLER);
  filler->set_segment_duration_ms(100_000);

  // Segment 2: second-class, fade-in
  *plan.add_segments() = MakeProtoSegment(
      2, "/media/ep.mkv", 600_000, 1_100_000,
      retrovue::playout::TRANSITION_FADE, 500,
      retrovue::playout::TRANSITION_NONE, 0);

  FedBlock block = ProtoBlockToFedBlock(plan);

  ASSERT_EQ(block.segments.size(), 3u);

  // Segment 0: no in, fade out
  EXPECT_EQ(block.segments[0].transition_in, TransitionType::kNone);
  EXPECT_EQ(block.segments[0].transition_in_duration_ms, 0u);
  EXPECT_EQ(block.segments[0].transition_out, TransitionType::kFade);
  EXPECT_EQ(block.segments[0].transition_out_duration_ms, 500u);

  // Segment 1: no transitions (filler)
  EXPECT_EQ(block.segments[1].transition_in, TransitionType::kNone);
  EXPECT_EQ(block.segments[1].transition_out, TransitionType::kNone);

  // Segment 2: fade in, no out
  EXPECT_EQ(block.segments[2].transition_in, TransitionType::kFade);
  EXPECT_EQ(block.segments[2].transition_in_duration_ms, 500u);
  EXPECT_EQ(block.segments[2].transition_out, TransitionType::kNone);
  EXPECT_EQ(block.segments[2].transition_out_duration_ms, 0u);
}

// =============================================================================
// TRANS-004: FedBlock → BlockPlan (FedBlockToBlockPlan) propagates transitions
// =============================================================================
TEST(SegmentTransitionTest, FedBlockToBlockPlanPropagatesTransitions) {
  FedBlock fed;
  fed.block_id = "blk-fed";
  fed.channel_id = 1;
  fed.start_utc_ms = 0;
  fed.end_utc_ms = 1_000_000;

  FedBlock::Segment s0;
  s0.segment_index = 0;
  s0.asset_uri = "/media/ep.mkv";
  s0.asset_start_offset_ms = 0;
  s0.segment_duration_ms = 1_000_000;
  s0.segment_type = SegmentType::kContent;
  s0.transition_in = TransitionType::kFade;
  s0.transition_in_duration_ms = 750;
  s0.transition_out = TransitionType::kFade;
  s0.transition_out_duration_ms = 750;
  fed.segments.push_back(s0);

  BlockPlan plan = FedBlockToBlockPlan(fed);

  ASSERT_EQ(plan.segments.size(), 1u);
  EXPECT_EQ(plan.segments[0].transition_in, TransitionType::kFade);
  EXPECT_EQ(plan.segments[0].transition_in_duration_ms, 750u);
  EXPECT_EQ(plan.segments[0].transition_out, TransitionType::kFade);
  EXPECT_EQ(plan.segments[0].transition_out_duration_ms, 750u);
}

// =============================================================================
// TRANS-005: Fade frame count calculation — ceil(duration_ms * fps / 1000)
// =============================================================================
TEST(SegmentTransitionTest, FadeFrameCountCalcAt30fps) {
  // 500ms at 30fps = ceil(500 * 30 / 1000) = ceil(15.0) = 15
  EXPECT_EQ(FadeFrameCount(500, 30.0), 15LL);
}

TEST(SegmentTransitionTest, FadeFrameCountCalcAt2997fps) {
  // 500ms at 29.97fps = ceil(500 * 29.97 / 1000) = ceil(14.985) = 15
  EXPECT_EQ(FadeFrameCount(500, 29.97), 15LL);
}

TEST(SegmentTransitionTest, FadeFrameCountCalcAt25fps) {
  // 500ms at 25fps = ceil(500 * 25 / 1000) = ceil(12.5) = 13
  EXPECT_EQ(FadeFrameCount(500, 25.0), 13LL);
}

TEST(SegmentTransitionTest, FadeFrameCountCalcAt60fps) {
  // 500ms at 60fps = ceil(500 * 60 / 1000) = ceil(30.0) = 30
  EXPECT_EQ(FadeFrameCount(500, 60.0), 30LL);
}

TEST(SegmentTransitionTest, FadeFrameCountCalcCustomDuration) {
  // 333ms at 30fps = ceil(333 * 30 / 1000) = ceil(9.99) = 10
  EXPECT_EQ(FadeFrameCount(333, 30.0), 10LL);
}

TEST(SegmentTransitionTest, FadeFrameCountCalcZero) {
  // 0ms = 0 frames (no fade)
  EXPECT_EQ(FadeFrameCount(0, 30.0), 0LL);
}

TEST(SegmentTransitionTest, FadeFrameCountCalcLargeDuration) {
  // 1000ms at 24fps = ceil(1000 * 24 / 1000) = 24
  EXPECT_EQ(FadeFrameCount(1000, 24.0), 24LL);
}

// =============================================================================
// TRANS-006: TransitionType enum wire values match proto enum values
// =============================================================================
TEST(SegmentTransitionTest, TransitionTypeEnumValuesMatchProto) {
  // kNone = 0 = TRANSITION_NONE
  EXPECT_EQ(static_cast<int>(TransitionType::kNone),
            static_cast<int>(retrovue::playout::TRANSITION_NONE));
  // kFade = 1 = TRANSITION_FADE
  EXPECT_EQ(static_cast<int>(TransitionType::kFade),
            static_cast<int>(retrovue::playout::TRANSITION_FADE));
}

// =============================================================================
// TRANS-007: Proto field numbers don't conflict — field 7 is absent in BlockSegment
// =============================================================================
TEST(SegmentTransitionTest, ProtoFieldNumbersAreCorrect) {
  // Transition fields use 8, 9, 10, 11 — no conflict with existing 1-6.
  // We verify by checking the reflection descriptor.
  const auto* desc = retrovue::playout::BlockSegment::descriptor();
  ASSERT_NE(desc, nullptr);

  EXPECT_NE(desc->FindFieldByNumber(8), nullptr) << "transition_in field 8 missing";
  EXPECT_NE(desc->FindFieldByNumber(9), nullptr) << "transition_in_duration_ms field 9 missing";
  EXPECT_NE(desc->FindFieldByNumber(10), nullptr) << "transition_out field 10 missing";
  EXPECT_NE(desc->FindFieldByNumber(11), nullptr) << "transition_out_duration_ms field 11 missing";

  // Field 7 should not exist in BlockSegment (gap preserved)
  EXPECT_EQ(desc->FindFieldByNumber(7), nullptr) << "field 7 should be absent in BlockSegment";
}

}  // namespace
}  // namespace retrovue::blockplan::testing
