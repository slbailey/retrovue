// AIR vNext — SeamController contract tests (C1.3).
//
// Validates the minimal intra-block seam lifecycle:
//
//   kObserving → kArmed (when fence within arm_window AND next ready)
//   kArmed     → kCommittedForTick (on next Tick while ready)
//   kCommittedForTick → kFiring (current_tick >= fence)
//   kFiring    → kComplete (MarkFired)
//
// Plus:
//   - INV-SEGMENT-SEAM-ARM-COMMIT-001: committed is sticky; Retract no-ops.
//   - Monotonicity: phase never regresses during Tick.
//   - Readiness regression after arm keeps controller in kArmed (not demoted).
//   - Firing is deterministic at target_tick (no re-evaluation at F).
//
// Also includes a minimal BlockRuntime-backed readiness check, to confirm
// the ownership contract: SeamController consumes `BlockRuntime::IsPrimed`
// via a callback; no queue-state ownership in the controller.

#include <gtest/gtest.h>

#include <atomic>
#include <memory>
#include <vector>

#include "block.hpp"
#include "block_runtime.hpp"
#include "channel_canonical.hpp"
#include "priming_pipeline.hpp"
#include "seam_controller.hpp"

namespace retrovue::air {
namespace {

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

Block MakeBlock(const std::string& block_id, int segment_count) {
  Block b;
  b.block_id = block_id;
  b.start_utc_ms = 0;
  b.end_utc_ms = segment_count * 1000;
  b.canonical = TestCanonical();
  for (int i = 0; i < segment_count; ++i) {
    Segment s;
    s.segment_id = block_id + ":" + std::to_string(i);
    s.asset_uri = "/dev/null";
    s.duration_ms = 1000;
    s.segment_index = i;
    b.segments.push_back(s);
  }
  return b;
}

SeamTarget IntraTarget(const std::string& block_id, int from_idx, int to_idx,
                       int64_t fence_us) {
  return SeamTarget{.from_block_id = block_id,
                    .from_segment_index = from_idx,
                    .to_block_id = block_id,
                    .to_segment_index = to_idx,
                    .fence_monotonic_us = fence_us,
                    .is_block_transition = false};
}

TEST(SeamControllerTest, InitialStateIsIdleWithNoTarget) {
  SeamController sc({}, [] { return false; });
  EXPECT_EQ(sc.Phase(), SeamPhase::kIdle);
  EXPECT_FALSE(sc.CurrentTarget().has_value());
  EXPECT_FALSE(sc.ShouldCommitAt(0));
}

TEST(SeamControllerTest, ObserveThenTickOutsideWindowStaysObserving) {
  SeamController sc(SeamConfig{.arm_window_us = 1'000'000},
                    [] { return true; });
  sc.ObserveSeam(IntraTarget("A", 0, 1, /*fence=*/5'000'000));
  EXPECT_EQ(sc.Phase(), SeamPhase::kObserving);

  // current=1_000_000; fence-current = 4_000_000 > arm_window → still observing.
  sc.Tick(1'000'000);
  EXPECT_EQ(sc.Phase(), SeamPhase::kObserving);
}

TEST(SeamControllerTest, ArmsWhenWindowOpenAndReady) {
  std::vector<SeamEvent> events;
  SeamController sc(SeamConfig{.arm_window_us = 1'000'000},
                    [] { return true; });
  sc.SetEventObserver([&](const SeamEvent& e) { events.push_back(e); });
  sc.ObserveSeam(IntraTarget("A", 0, 1, /*fence=*/5'000'000));

  // current=4_500_000; fence-current = 500_000 <= arm_window → arm.
  sc.Tick(4'500'000);
  EXPECT_EQ(sc.Phase(), SeamPhase::kArmed);
  ASSERT_EQ(events.size(), 1u);
  EXPECT_EQ(events[0].kind, SeamEventKind::kArmed);
  EXPECT_EQ(events[0].target.from_segment_index, 0);
  EXPECT_EQ(events[0].target.to_segment_index, 1);
  EXPECT_EQ(events[0].target.fence_monotonic_us, 5'000'000);
}

TEST(SeamControllerTest, DoesNotArmWhenNotReady) {
  std::atomic<bool> ready{false};
  std::vector<SeamEvent> events;
  SeamController sc(SeamConfig{.arm_window_us = 1'000'000},
                    [&] { return ready.load(); });
  sc.SetEventObserver([&](const SeamEvent& e) { events.push_back(e); });
  sc.ObserveSeam(IntraTarget("A", 0, 1, 5'000'000));

  sc.Tick(4'500'000);  // window open, but not ready
  EXPECT_EQ(sc.Phase(), SeamPhase::kObserving);
  EXPECT_EQ(events.size(), 0u);

  ready.store(true);
  sc.Tick(4'600'000);
  EXPECT_EQ(sc.Phase(), SeamPhase::kArmed);
  ASSERT_EQ(events.size(), 1u);
  EXPECT_EQ(events[0].kind, SeamEventKind::kArmed);
}

TEST(SeamControllerTest, ArmThenCommitOnNextTick) {
  std::vector<SeamEvent> events;
  SeamController sc(SeamConfig{.arm_window_us = 1'000'000},
                    [] { return true; });
  sc.SetEventObserver([&](const SeamEvent& e) { events.push_back(e); });
  sc.ObserveSeam(IntraTarget("A", 0, 1, 5'000'000));

  sc.Tick(4'500'000);
  ASSERT_EQ(sc.Phase(), SeamPhase::kArmed);

  sc.Tick(4'600'000);
  EXPECT_EQ(sc.Phase(), SeamPhase::kCommittedForTick);
  ASSERT_EQ(events.size(), 2u);
  EXPECT_EQ(events[1].kind, SeamEventKind::kCommitted);
  EXPECT_EQ(events[1].target.fence_monotonic_us, 5'000'000);
}

TEST(SeamControllerTest, CommitIsStickyDespiteReadinessRegression) {
  // INV-SEGMENT-SEAM-ARM-COMMIT-001: once committed, no re-evaluation at F.
  std::atomic<bool> ready{true};
  SeamController sc(SeamConfig{.arm_window_us = 1'000'000},
                    [&] { return ready.load(); });
  sc.ObserveSeam(IntraTarget("A", 0, 1, 5'000'000));
  sc.Tick(4'500'000);  // arm
  sc.Tick(4'600'000);  // commit
  ASSERT_EQ(sc.Phase(), SeamPhase::kCommittedForTick);

  // Readiness drops — should NOT demote.
  ready.store(false);
  sc.Tick(4'700'000);
  EXPECT_EQ(sc.Phase(), SeamPhase::kCommittedForTick);

  // Reach fence → fires.
  sc.Tick(5'000'000);
  EXPECT_EQ(sc.Phase(), SeamPhase::kFiring);
  EXPECT_TRUE(sc.ShouldCommitAt(5'000'000));
}

TEST(SeamControllerTest, FiresAtExactTargetTick) {
  SeamController sc({}, [] { return true; });
  sc.ObserveSeam(IntraTarget("A", 0, 1, /*fence=*/2'000'000));

  sc.Tick(1'500'000);  // observe → arm
  ASSERT_EQ(sc.Phase(), SeamPhase::kArmed);
  sc.Tick(1'600'000);  // arm → commit
  ASSERT_EQ(sc.Phase(), SeamPhase::kCommittedForTick);

  // One tick short of fence: still committed, not firing.
  sc.Tick(1'999'999);
  EXPECT_EQ(sc.Phase(), SeamPhase::kCommittedForTick);
  EXPECT_FALSE(sc.ShouldCommitAt(1'999'999));

  // Exactly at fence: fires.
  sc.Tick(2'000'000);
  EXPECT_EQ(sc.Phase(), SeamPhase::kFiring);
  EXPECT_TRUE(sc.ShouldCommitAt(2'000'000));
}

TEST(SeamControllerTest, MarkFiredEmitsExecutedAndGoesComplete) {
  std::vector<SeamEvent> events;
  SeamController sc({}, [] { return true; });
  sc.SetEventObserver([&](const SeamEvent& e) { events.push_back(e); });
  sc.ObserveSeam(IntraTarget("A", 0, 1, 1'000'000));

  sc.Tick(500'000);
  sc.Tick(600'000);
  sc.Tick(1'000'000);
  ASSERT_EQ(sc.Phase(), SeamPhase::kFiring);

  sc.MarkFired(1'000'001);
  EXPECT_EQ(sc.Phase(), SeamPhase::kComplete);
  ASSERT_GE(events.size(), 3u);
  EXPECT_EQ(events.back().kind, SeamEventKind::kExecuted);
  EXPECT_EQ(events.back().executed_at_tick_us, 1'000'001);
  EXPECT_EQ(events.back().target.from_segment_index, 0);
  EXPECT_EQ(events.back().target.to_segment_index, 1);
}

TEST(SeamControllerTest, RetractFromObservingEmitsDisarmed) {
  std::vector<SeamEvent> events;
  SeamController sc({}, [] { return false; });
  sc.SetEventObserver([&](const SeamEvent& e) { events.push_back(e); });
  sc.ObserveSeam(IntraTarget("A", 0, 1, 5'000'000));
  ASSERT_EQ(sc.Phase(), SeamPhase::kObserving);

  EXPECT_TRUE(sc.Retract("block_retired"));
  EXPECT_EQ(sc.Phase(), SeamPhase::kIdle);
  ASSERT_EQ(events.size(), 1u);
  EXPECT_EQ(events[0].kind, SeamEventKind::kDisarmed);
  EXPECT_EQ(events[0].reason, "block_retired");
}

TEST(SeamControllerTest, RetractFromArmedEmitsDisarmed) {
  std::vector<SeamEvent> events;
  SeamController sc({}, [] { return true; });
  sc.SetEventObserver([&](const SeamEvent& e) { events.push_back(e); });
  sc.ObserveSeam(IntraTarget("A", 0, 1, 1'000'000));
  sc.Tick(500'000);
  ASSERT_EQ(sc.Phase(), SeamPhase::kArmed);

  EXPECT_TRUE(sc.Retract("test_cancel"));
  EXPECT_EQ(sc.Phase(), SeamPhase::kIdle);
  ASSERT_EQ(events.size(), 2u);
  EXPECT_EQ(events[1].kind, SeamEventKind::kDisarmed);
}

TEST(SeamControllerTest, RetractAfterCommitIsNoop) {
  // Commit is sticky; Retract MUST NOT bypass it per
  // INV-SEGMENT-SEAM-ARM-COMMIT-001.
  SeamController sc({}, [] { return true; });
  sc.ObserveSeam(IntraTarget("A", 0, 1, 1'000'000));
  sc.Tick(500'000);
  sc.Tick(600'000);
  ASSERT_EQ(sc.Phase(), SeamPhase::kCommittedForTick);

  EXPECT_FALSE(sc.Retract("too_late"));
  EXPECT_EQ(sc.Phase(), SeamPhase::kCommittedForTick);
}

TEST(SeamControllerTest, PhaseNeverRegresses) {
  // Drive a full cycle and sample phase at every tick; never goes backwards.
  SeamController sc({}, [] { return true; });
  sc.ObserveSeam(IntraTarget("A", 0, 1, 2'000'000));

  std::vector<SeamPhase> samples;
  for (int64_t t = 0; t <= 2'000'000; t += 250'000) {
    sc.Tick(t);
    samples.push_back(sc.Phase());
  }
  for (std::size_t i = 1; i < samples.size(); ++i) {
    EXPECT_GE(static_cast<int>(samples[i]), static_cast<int>(samples[i - 1]))
        << "phase regressed at sample " << i;
  }
}

TEST(SeamControllerTest, ShouldCommitAtIsFalseUnlessFiring) {
  SeamController sc({}, [] { return true; });
  sc.ObserveSeam(IntraTarget("A", 0, 1, 1'000'000));
  EXPECT_FALSE(sc.ShouldCommitAt(0));

  sc.Tick(500'000);  // armed
  EXPECT_FALSE(sc.ShouldCommitAt(500'000));

  sc.Tick(600'000);  // committed
  EXPECT_FALSE(sc.ShouldCommitAt(600'000));

  sc.Tick(1'000'000);  // firing
  EXPECT_TRUE(sc.ShouldCommitAt(1'000'000));

  sc.MarkFired(1'000'000);  // complete
  EXPECT_FALSE(sc.ShouldCommitAt(1'000'001));
}

TEST(SeamControllerTest, ReadinessFromBlockRuntimeDrivesArming) {
  // Ownership contract: SeamController consumes BlockRuntime::IsPrimed via
  // callback. BlockRuntime is the state store; the controller only reads.
  BlockRuntime rt(MakeBlock("A", 3));
  EXPECT_EQ(rt.State(0), SegmentPrimeState::kRaw);
  EXPECT_EQ(rt.State(1), SegmentPrimeState::kRaw);

  std::vector<SeamEvent> events;
  SeamController sc(SeamConfig{.arm_window_us = 1'000'000},
                    [&rt] { return rt.IsPrimed(1); });
  sc.SetEventObserver([&](const SeamEvent& e) { events.push_back(e); });
  sc.ObserveSeam(IntraTarget("A", 0, 1, 5'000'000));

  // Segment 1 still raw → inside window, no arm.
  sc.Tick(4'500'000);
  EXPECT_EQ(sc.Phase(), SeamPhase::kObserving);
  EXPECT_EQ(events.size(), 0u);

  // Flip segment 1 to primed via BlockRuntime. (Normally PrimingPipeline
  // does this; tests bypass.) Primed payloads are not needed for the
  // readiness flag — SetState alone suffices for this test.
  rt.SetState(1, SegmentPrimeState::kPrimed);
  sc.Tick(4'600'000);
  EXPECT_EQ(sc.Phase(), SeamPhase::kArmed);
  ASSERT_EQ(events.size(), 1u);
  EXPECT_EQ(events[0].kind, SeamEventKind::kArmed);
}

// ---- C2.2: block-transition flag propagation ------------------------

TEST(SeamControllerTest, IntraBlockSeamReportsIsBlockTransitionFalse) {
  // Sanity: default intra-block target (from_block == to_block) carries
  // is_block_transition=false through all emitted events. This is the
  // happy-path contract that C1 relied on implicitly; C2.2 asserts it
  // directly.
  std::vector<SeamEvent> events;
  SeamController sc({}, [] { return true; });
  sc.SetEventObserver([&](const SeamEvent& e) { events.push_back(e); });
  sc.ObserveSeam(IntraTarget("A", 0, 1, 1'000'000));

  sc.Tick(500'000);     // observe → arm
  sc.Tick(600'000);     // arm → commit
  sc.Tick(1'000'000);   // commit → firing
  sc.MarkFired(1'000'000);

  ASSERT_EQ(events.size(), 3u);
  for (const auto& e : events) {
    EXPECT_FALSE(e.target.is_block_transition)
        << "intra-block seam event " << static_cast<int>(e.kind)
        << " unexpectedly reports is_block_transition=true";
  }
}

SeamTarget InterTarget(const std::string& from_block, int from_idx,
                       const std::string& to_block, int to_idx,
                       int64_t fence_us) {
  return SeamTarget{.from_block_id = from_block,
                    .from_segment_index = from_idx,
                    .to_block_id = to_block,
                    .to_segment_index = to_idx,
                    .fence_monotonic_us = fence_us,
                    .is_block_transition = true};
}

TEST(SeamControllerTest, InterBlockSeamPropagatesIsBlockTransitionOnExecuted) {
  // Primary C2.2 contract: when the caller constructs a SeamTarget with
  // is_block_transition=true, the kExecuted event carries that flag.
  std::vector<SeamEvent> events;
  SeamController sc({}, [] { return true; });
  sc.SetEventObserver([&](const SeamEvent& e) { events.push_back(e); });
  sc.ObserveSeam(InterTarget("A", 2, "B", 0, 1'000'000));

  sc.Tick(500'000);
  sc.Tick(600'000);
  sc.Tick(1'000'000);
  sc.MarkFired(1'000'000);

  ASSERT_GE(events.size(), 3u);
  const auto& executed = events.back();
  EXPECT_EQ(executed.kind, SeamEventKind::kExecuted);
  EXPECT_TRUE(executed.target.is_block_transition)
      << "kExecuted MUST carry is_block_transition=true for inter-block seams";
  // Full target identity survives the lifecycle.
  EXPECT_EQ(executed.target.from_block_id, "A");
  EXPECT_EQ(executed.target.from_segment_index, 2);
  EXPECT_EQ(executed.target.to_block_id, "B");
  EXPECT_EQ(executed.target.to_segment_index, 0);
}

TEST(SeamControllerTest, InterBlockFlagEchoedOnArmedAndCommittedToo) {
  // Extended contract per SeamTarget doc: the flag is echoed on every
  // event the controller emits, not only kExecuted. This lets observers
  // recognise an upcoming block transition in advance (e.g., for
  // preparing downstream counters).
  std::vector<SeamEvent> events;
  SeamController sc({}, [] { return true; });
  sc.SetEventObserver([&](const SeamEvent& e) { events.push_back(e); });
  sc.ObserveSeam(InterTarget("A", 2, "B", 0, 1'000'000));

  sc.Tick(500'000);
  sc.Tick(600'000);
  sc.Tick(1'000'000);
  sc.MarkFired(1'000'000);

  int armed_count = 0, committed_count = 0, executed_count = 0;
  for (const auto& e : events) {
    switch (e.kind) {
      case SeamEventKind::kArmed:
        EXPECT_TRUE(e.target.is_block_transition);
        ++armed_count;
        break;
      case SeamEventKind::kCommitted:
        EXPECT_TRUE(e.target.is_block_transition);
        ++committed_count;
        break;
      case SeamEventKind::kExecuted:
        EXPECT_TRUE(e.target.is_block_transition);
        ++executed_count;
        break;
      default:
        break;
    }
  }
  EXPECT_EQ(armed_count, 1);
  EXPECT_EQ(committed_count, 1);
  EXPECT_EQ(executed_count, 1);
}

TEST(SeamControllerTest, InterBlockRetractPreservesFlagOnDisarmed) {
  // Disarmed events emit for targets canceled from kObserving or kArmed.
  // The flag MUST be preserved on the disarmed event so a consumer
  // observing only event streams can tell what kind of seam was cancelled.
  std::vector<SeamEvent> events;
  SeamController sc({}, [] { return false; });
  sc.SetEventObserver([&](const SeamEvent& e) { events.push_back(e); });
  sc.ObserveSeam(InterTarget("A", 2, "B", 0, 5'000'000));

  ASSERT_TRUE(sc.Retract("test_cancel"));
  ASSERT_EQ(events.size(), 1u);
  EXPECT_EQ(events[0].kind, SeamEventKind::kDisarmed);
  EXPECT_TRUE(events[0].target.is_block_transition);
  EXPECT_EQ(events[0].target.to_block_id, "B");
}

TEST(SeamControllerTest, ResetAfterCompleteAllowsNewObserveSeam) {
  SeamController sc({}, [] { return true; });
  sc.ObserveSeam(IntraTarget("A", 0, 1, 1'000'000));
  sc.Tick(500'000);
  sc.Tick(600'000);
  sc.Tick(1'000'000);
  sc.MarkFired(1'000'000);
  ASSERT_EQ(sc.Phase(), SeamPhase::kComplete);

  sc.Reset();
  EXPECT_EQ(sc.Phase(), SeamPhase::kIdle);
  EXPECT_FALSE(sc.CurrentTarget().has_value());

  // Next seam can be observed.
  sc.ObserveSeam(IntraTarget("A", 1, 2, 2'000'000));
  EXPECT_EQ(sc.Phase(), SeamPhase::kObserving);
}

}  // namespace
}  // namespace retrovue::air
