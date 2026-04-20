// AIR vNext — BootstrapContentGate contract tests.

#include <gtest/gtest.h>

#include "bootstrap_content_gate.hpp"

namespace retrovue::air {
namespace {

using Gate = BootstrapContentGate;
using Snap = Gate::ReadinessSnapshot;
using V = Gate::Verdict;

TEST(BootstrapContentGateTest, StartsNotFired) {
  Gate gate;
  EXPECT_FALSE(gate.HasFired());
  EXPECT_EQ(gate.Evaluations(), 0);
  EXPECT_EQ(gate.TicksToFire(), 0);
}

TEST(BootstrapContentGateTest, EmptySnapshotReturnsNotReady) {
  Gate gate;
  Snap s{};  // all zeros, decoder healthy by default
  EXPECT_EQ(gate.Evaluate(s), V::NotReady);
  EXPECT_FALSE(gate.HasFired());
}

TEST(BootstrapContentGateTest, BelowFloorReturnsNotReady) {
  Gate gate(Gate::Config{.min_video_frames = 30, .min_audio_blocks = 30});
  Snap s{.video_buffer_depth = 29, .audio_buffer_depth = 30, .decoder_healthy = true};
  EXPECT_EQ(gate.Evaluate(s), V::NotReady);

  Snap s2{.video_buffer_depth = 30, .audio_buffer_depth = 29, .decoder_healthy = true};
  EXPECT_EQ(gate.Evaluate(s2), V::NotReady);
  EXPECT_FALSE(gate.HasFired());
}

TEST(BootstrapContentGateTest, FiresWhenBothFloorsMet) {
  Gate gate(Gate::Config{.min_video_frames = 30, .min_audio_blocks = 30});
  Snap s{.video_buffer_depth = 30, .audio_buffer_depth = 30, .decoder_healthy = true};
  EXPECT_EQ(gate.Evaluate(s), V::Ready);
  EXPECT_TRUE(gate.HasFired());
  EXPECT_EQ(gate.TicksToFire(), 1);
}

TEST(BootstrapContentGateTest, DecoderFaultBlocksFire) {
  Gate gate(Gate::Config{.min_video_frames = 10, .min_audio_blocks = 10});
  Snap s{.video_buffer_depth = 100, .audio_buffer_depth = 100, .decoder_healthy = false};
  EXPECT_EQ(gate.Evaluate(s), V::NotReady);
  EXPECT_FALSE(gate.HasFired());

  // Recovers when decoder returns healthy.
  Snap s2{.video_buffer_depth = 100, .audio_buffer_depth = 100, .decoder_healthy = true};
  EXPECT_EQ(gate.Evaluate(s2), V::Ready);
  EXPECT_TRUE(gate.HasFired());
}

TEST(BootstrapContentGateTest, StickyAfterFiring) {
  Gate gate(Gate::Config{.min_video_frames = 10, .min_audio_blocks = 10});
  Snap good{.video_buffer_depth = 10, .audio_buffer_depth = 10, .decoder_healthy = true};
  EXPECT_EQ(gate.Evaluate(good), V::Ready);

  // Even if conditions regress, gate stays fired.
  Snap bad{.video_buffer_depth = 0, .audio_buffer_depth = 0, .decoder_healthy = false};
  EXPECT_EQ(gate.Evaluate(bad), V::Ready);
  EXPECT_EQ(gate.Evaluate(bad), V::Ready);
  EXPECT_TRUE(gate.HasFired());
}

TEST(BootstrapContentGateTest, CountsTicksToFireCorrectly) {
  Gate gate(Gate::Config{.min_video_frames = 5, .min_audio_blocks = 5});

  // 3 non-ready ticks, then a ready tick.
  Snap warming{.video_buffer_depth = 2, .audio_buffer_depth = 2, .decoder_healthy = true};
  EXPECT_EQ(gate.Evaluate(warming), V::NotReady);
  warming.video_buffer_depth = 3;
  warming.audio_buffer_depth = 3;
  EXPECT_EQ(gate.Evaluate(warming), V::NotReady);
  warming.video_buffer_depth = 4;
  warming.audio_buffer_depth = 4;
  EXPECT_EQ(gate.Evaluate(warming), V::NotReady);

  Snap ready{.video_buffer_depth = 5, .audio_buffer_depth = 5, .decoder_healthy = true};
  EXPECT_EQ(gate.Evaluate(ready), V::Ready);
  EXPECT_EQ(gate.TicksToFire(), 4);
  EXPECT_EQ(gate.Evaluations(), 4);
}

}  // namespace
}  // namespace retrovue::air
