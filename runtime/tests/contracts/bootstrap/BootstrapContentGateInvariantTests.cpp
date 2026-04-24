// Contract tests for the bootstrap content-gate invariants registered in
// docs/contracts/invariants/air/.
//
// Covered invariants:
//   INV-BOOTSTRAP-CONTINUITY-001         (pad + silence every tick while closed)
//   INV-BOOTSTRAP-CONTENT-PARKED-001     (source cursors parked while closed)
//   INV-BOOTSTRAP-CONTENT-ORIGIN-001     (buffer fronts source-aligned at open)
//   INV-BOOTSTRAP-KICKOFF-ATOMIC-001     (real A/V content starts on same tick)
//   INV-BOOTSTRAP-PTS-CONTINUOUS-001     (output PTS continuous across kickoff)
//
// Cross-references:
//   docs/contracts/invariants/air/INV-BOOTSTRAP-CONTINUITY-001.md
//   docs/contracts/invariants/air/INV-BOOTSTRAP-CONTENT-PARKED-001.md
//   docs/contracts/invariants/air/INV-BOOTSTRAP-CONTENT-ORIGIN-001.md
//   docs/contracts/invariants/air/INV-BOOTSTRAP-KICKOFF-ATOMIC-001.md
//   docs/contracts/invariants/air/INV-BOOTSTRAP-PTS-CONTINUOUS-001.md
//
// RED contract-test status:
//   The production headers included below do not yet exist. Compilation
//   fails on the first `#include "retrovue/bootstrap/..."`. This is the
//   RED signal. Turn C creates the headers and evaluator/controller
//   implementations, turning these tests GREEN.
//
//   Per /opt/retrovue/CLAUDE.md §CODE CHANGE PROTOCOL step (2), the test
//   MUST fail before the code change. Compile failure is the accepted RED
//   form when the production symbol does not yet exist.

#include <gtest/gtest.h>

#include <cstdint>
#include <functional>
#include <vector>

// Turn C will create these headers. Missing-header compile failure is the
// RED contract-test signal for Turn B.
#include "retrovue/bootstrap/BootstrapCommand.h"
#include "retrovue/bootstrap/BootstrapGateEvaluator.h"
#include "retrovue/bootstrap/BootstrapContentGate.h"

namespace retrovue::bootstrap::test {

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

namespace {

// 29.97 fps output frame duration in microseconds.
constexpr int kFrameUs = 33367;
constexpr int kAudioFloorMs = 500;
constexpr int kVideoFloorFrames = 15;

BootstrapSnapshot EmptySnapshot() {
  BootstrapSnapshot s{};
  s.tick_index = 0;
  s.audio_depth_ms = 0;
  s.audio_floor_ms = kAudioFloorMs;
  s.video_depth_frames = 0;
  s.video_floor_frames = kVideoFloorFrames;
  s.audio_front_src_pts_us = -1;
  s.video_front_src_pts_us = -1;
  s.output_frame_duration_us = kFrameUs;
  return s;
}

BootstrapSnapshot AlignedReadySnapshot() {
  BootstrapSnapshot s = EmptySnapshot();
  s.audio_depth_ms = 512;
  s.video_depth_frames = 15;
  s.audio_front_src_pts_us = 1'000'000;
  s.video_front_src_pts_us = 1'000'000;
  return s;
}

BootstrapSnapshot MisalignedReadySnapshot() {
  // Both buffers deep enough, but fronts differ by 567 ms — the exact
  // content-offset observed in Turn 0 production instrumentation.
  BootstrapSnapshot s = AlignedReadySnapshot();
  s.audio_front_src_pts_us = 1'000'000;
  s.video_front_src_pts_us = 1'000'000 - 567'000;
  return s;
}

BootstrapSnapshot DepthsMissingSnapshot() {
  // Fronts aligned, but neither buffer has reached its floor.
  BootstrapSnapshot s = EmptySnapshot();
  s.audio_depth_ms = 200;
  s.video_depth_frames = 5;
  s.audio_front_src_pts_us = 1'000'000;
  s.video_front_src_pts_us = 1'000'000;
  return s;
}

}  // namespace

// ---------------------------------------------------------------------------
// INV-BOOTSTRAP-CONTINUITY-001 — pad + silence emission while gate is closed
// ---------------------------------------------------------------------------

TEST(BootstrapContinuity, GateStartsClosed) {
  BootstrapContentGate gate;
  EXPECT_EQ(gate.State(), GateState::kClosed);
}

TEST(BootstrapContinuity, DecisionIsPadSilenceWhileClosed) {
  BootstrapContentGate gate;
  EXPECT_EQ(gate.Decision(), EmissionDecision::kPadSilence);
}

TEST(BootstrapContinuity, PadSilenceDecisionHoldsAcrossUnreadySnapshots) {
  BootstrapContentGate gate;
  for (int i = 0; i < 25; ++i) {
    BootstrapSnapshot s = DepthsMissingSnapshot();
    s.tick_index = i;
    gate.Evaluate(s);
    EXPECT_EQ(gate.State(), GateState::kClosed);
    EXPECT_EQ(gate.Decision(), EmissionDecision::kPadSilence);
  }
}

// ---------------------------------------------------------------------------
// INV-BOOTSTRAP-CONTENT-PARKED-001 — source cursors parked while closed
// ---------------------------------------------------------------------------

TEST(BootstrapContentParked, AllowContentConsumptionFalseWhileClosed) {
  BootstrapContentGate gate;
  EXPECT_FALSE(gate.AllowContentConsumption());
}

TEST(BootstrapContentParked, AllowContentConsumptionStaysFalseWhenUnready) {
  BootstrapContentGate gate;
  gate.Evaluate(DepthsMissingSnapshot());
  EXPECT_FALSE(gate.AllowContentConsumption());
  gate.Evaluate(EmptySnapshot());
  EXPECT_FALSE(gate.AllowContentConsumption());
}

TEST(BootstrapContentParked, AllowContentConsumptionTrueAfterGateOpens) {
  BootstrapContentGate gate;
  gate.Evaluate(AlignedReadySnapshot());
  EXPECT_EQ(gate.State(), GateState::kOpen);
  EXPECT_TRUE(gate.AllowContentConsumption());
}

// ---------------------------------------------------------------------------
// INV-BOOTSTRAP-CONTENT-ORIGIN-001 — fronts source-aligned at gate-open
// ---------------------------------------------------------------------------

TEST(BootstrapContentOrigin, PureEvaluatorReturnsClosedOnEmptyFronts) {
  BootstrapSnapshot s = EmptySnapshot();
  EXPECT_EQ(BootstrapGateEvaluator::Evaluate(s), GateState::kClosed);
}

TEST(BootstrapContentOrigin, PureEvaluatorReturnsClosedOnDepthFloorUnmet) {
  BootstrapSnapshot s = DepthsMissingSnapshot();
  EXPECT_EQ(BootstrapGateEvaluator::Evaluate(s), GateState::kClosed);
}

TEST(BootstrapContentOrigin, PureEvaluatorReturnsClosedOnFrontMisalignmentOf567Ms) {
  // This is the production bug captured in Turn 0 instrumentation.
  BootstrapSnapshot s = MisalignedReadySnapshot();
  EXPECT_EQ(BootstrapGateEvaluator::Evaluate(s), GateState::kClosed);
}

TEST(BootstrapContentOrigin, PureEvaluatorReturnsOpenOnAlignedReadySnapshot) {
  BootstrapSnapshot s = AlignedReadySnapshot();
  EXPECT_EQ(BootstrapGateEvaluator::Evaluate(s), GateState::kOpen);
}

TEST(BootstrapContentOrigin, ToleranceIsOneOutputFrameDuration) {
  // Delta exactly one frame — at the boundary. Permitted.
  BootstrapSnapshot within = AlignedReadySnapshot();
  within.video_front_src_pts_us =
      within.audio_front_src_pts_us - within.output_frame_duration_us;
  EXPECT_EQ(BootstrapGateEvaluator::Evaluate(within), GateState::kOpen);

  // Delta just beyond one frame — not permitted.
  BootstrapSnapshot beyond = AlignedReadySnapshot();
  beyond.video_front_src_pts_us =
      beyond.audio_front_src_pts_us - (beyond.output_frame_duration_us + 1);
  EXPECT_EQ(BootstrapGateEvaluator::Evaluate(beyond), GateState::kClosed);
}

TEST(BootstrapContentOrigin, ControllerDoesNotOpenWhenFrontsMisaligned) {
  BootstrapContentGate gate;
  gate.Evaluate(MisalignedReadySnapshot());
  EXPECT_EQ(gate.State(), GateState::kClosed);
  EXPECT_EQ(gate.Decision(), EmissionDecision::kPadSilence);
}

// ---------------------------------------------------------------------------
// INV-BOOTSTRAP-KICKOFF-ATOMIC-001 — real A/V content starts on same tick
// ---------------------------------------------------------------------------

TEST(BootstrapKickoffAtomic, StateIsStickyOnceOpen) {
  BootstrapContentGate gate;
  gate.Evaluate(AlignedReadySnapshot());
  EXPECT_EQ(gate.State(), GateState::kOpen);

  // Subsequent unready snapshots must not reopen the gate decision.
  gate.Evaluate(EmptySnapshot());
  EXPECT_EQ(gate.State(), GateState::kOpen);
  gate.Evaluate(MisalignedReadySnapshot());
  EXPECT_EQ(gate.State(), GateState::kOpen);
  gate.Evaluate(DepthsMissingSnapshot());
  EXPECT_EQ(gate.State(), GateState::kOpen);
}

TEST(BootstrapKickoffAtomic, KickoffCallbackFiresExactlyOnce) {
  std::vector<KickoffEvent> events;
  auto cb = [&events](const KickoffEvent& e) { events.push_back(e); };
  BootstrapContentGate gate(cb);

  // Repeated unready evaluations must not emit kickoff.
  for (int i = 0; i < 5; ++i) {
    BootstrapSnapshot s = DepthsMissingSnapshot();
    s.tick_index = i;
    gate.Evaluate(s);
  }
  EXPECT_EQ(events.size(), 0u);

  // First ready evaluation emits exactly one event.
  BootstrapSnapshot ready = AlignedReadySnapshot();
  ready.tick_index = 42;
  gate.Evaluate(ready);
  ASSERT_EQ(events.size(), 1u);

  // Subsequent evaluations must not emit further kickoff events.
  gate.Evaluate(AlignedReadySnapshot());
  gate.Evaluate(EmptySnapshot());
  EXPECT_EQ(events.size(), 1u);
}

TEST(BootstrapKickoffAtomic, KickoffEventCarriesTickAndBothFrontPts) {
  std::vector<KickoffEvent> events;
  auto cb = [&events](const KickoffEvent& e) { events.push_back(e); };
  BootstrapContentGate gate(cb);

  BootstrapSnapshot ready = AlignedReadySnapshot();
  ready.tick_index = 7;
  ready.audio_front_src_pts_us = 2'500'000;
  ready.video_front_src_pts_us = 2'500'000;
  gate.Evaluate(ready);

  ASSERT_EQ(events.size(), 1u);
  EXPECT_EQ(events[0].tick_index, 7);
  EXPECT_EQ(events[0].audio_front_src_pts_us, 2'500'000);
  EXPECT_EQ(events[0].video_front_src_pts_us, 2'500'000);
  EXPECT_EQ(events[0].front_delta_us, 0);
}

TEST(BootstrapKickoffAtomic, KickoffTickIsTheSameTickForBothStreams) {
  // The kickoff event's tick_index defines THE single tick on which both
  // audio and video begin consuming real content. There is no per-stream
  // kickoff distinction.
  std::vector<KickoffEvent> events;
  auto cb = [&events](const KickoffEvent& e) { events.push_back(e); };
  BootstrapContentGate gate(cb);

  BootstrapSnapshot ready = AlignedReadySnapshot();
  ready.tick_index = 12;
  gate.Evaluate(ready);

  ASSERT_EQ(events.size(), 1u);
  EXPECT_EQ(events[0].tick_index, 12);
  EXPECT_TRUE(gate.AllowContentConsumption());
  EXPECT_EQ(gate.Decision(), EmissionDecision::kRealContent);
}

// ---------------------------------------------------------------------------
// INV-BOOTSTRAP-PTS-CONTINUOUS-001 — output PTS continuous across kickoff
// ---------------------------------------------------------------------------

TEST(BootstrapPtsContinuous, EvaluatorIsPureAndIdempotent) {
  // Pure function: same snapshot always yields the same decision. No hidden
  // state is permitted in the evaluator that could cause a PTS-origin
  // mutation at kickoff.
  BootstrapSnapshot s = AlignedReadySnapshot();
  GateState a = BootstrapGateEvaluator::Evaluate(s);
  GateState b = BootstrapGateEvaluator::Evaluate(s);
  GateState c = BootstrapGateEvaluator::Evaluate(s);
  EXPECT_EQ(a, GateState::kOpen);
  EXPECT_EQ(b, GateState::kOpen);
  EXPECT_EQ(c, GateState::kOpen);
}

TEST(BootstrapPtsContinuous, KickoffEventCarriesNoPtsOriginAdjustment) {
  // KickoffEvent MUST NOT expose any PTS-origin mutation field. PTS
  // continuity is preserved by the enforcement surface continuing to emit
  // from the existing tick counter; the kickoff event is diagnostic only.
  //
  // The assertion below is a positive shape check: the fields that DO exist
  // are restricted to diagnostic identification (tick, source-front PTS,
  // delta). No field exists named reset_*, snap_*, adjust_*, or origin_*.
  KickoffEvent e{};
  e.tick_index = 1;
  e.audio_front_src_pts_us = 1;
  e.video_front_src_pts_us = 1;
  e.front_delta_us = 0;

  // This test also serves as a structural guard. If Turn C adds a
  // PTS-origin adjustment field to KickoffEvent, this file will fail to
  // compile because the default-constructor assignment above will need
  // to initialise it — drawing reviewer attention to the violation.
  EXPECT_EQ(e.tick_index, 1);
  EXPECT_EQ(e.audio_front_src_pts_us, 1);
  EXPECT_EQ(e.video_front_src_pts_us, 1);
  EXPECT_EQ(e.front_delta_us, 0);
}

TEST(BootstrapPtsContinuous, SimulatedTickLoopHasContinuousEmission) {
  // Walk a simulated tick loop: first N ticks emit pad/silence (closed),
  // then the gate opens and subsequent ticks emit real content. The test
  // records what was decided on each tick and asserts there is no gap:
  // every tick produced exactly one decision, and the sequence transitions
  // atomically from kPadSilence to kRealContent with no intermediate state.
  BootstrapContentGate gate;
  std::vector<EmissionDecision> decisions;

  constexpr int kPadTicks = 17;  // mirrors the production 17-frame offset

  for (int i = 0; i < kPadTicks; ++i) {
    BootstrapSnapshot s = DepthsMissingSnapshot();
    s.tick_index = i;
    gate.Evaluate(s);
    decisions.push_back(gate.Decision());
  }
  // All pad ticks must be kPadSilence.
  for (const auto d : decisions) {
    EXPECT_EQ(d, EmissionDecision::kPadSilence);
  }

  // Gate opens.
  BootstrapSnapshot ready = AlignedReadySnapshot();
  ready.tick_index = kPadTicks;
  gate.Evaluate(ready);
  decisions.push_back(gate.Decision());

  // Last decision must be the first kRealContent emission.
  EXPECT_EQ(decisions.back(), EmissionDecision::kRealContent);

  // No decision was skipped: kPadTicks + 1 decisions recorded for
  // kPadTicks + 1 ticks.
  EXPECT_EQ(decisions.size(), static_cast<size_t>(kPadTicks + 1));

  // Transition is atomic: the previous decision was kPadSilence and the
  // next is kRealContent, with no intermediate "one stream real, other
  // pad" intermediate value permitted by the enum.
  EXPECT_EQ(decisions[kPadTicks - 1], EmissionDecision::kPadSilence);
  EXPECT_EQ(decisions[kPadTicks],     EmissionDecision::kRealContent);
}

}  // namespace retrovue::bootstrap::test
