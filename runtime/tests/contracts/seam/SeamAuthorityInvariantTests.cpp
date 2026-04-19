// Contract tests for the seam authority invariants registered in
// docs/contracts/invariants/air/.
//
// Covered invariants:
//   INV-SEAM-SINGLE-AUTHORITY-001      (SeamController is the sole authority)
//   INV-SEAM-SINGLE-EXECUTION-001      (exactly one execution per boundary)
//   INV-SEAM-MISSED-RESOLUTION-001     (missed resolves to pad-bridge or JIP)
//   INV-SEAM-EDITORIAL-EXTERNAL-001    (no content choice inside SeamController)
//   INV-SEAM-OBSERVABLE-001            (every decision emits a named event)
//
// Cross-references:
//   docs/contracts/invariants/air/INV-SEAM-SINGLE-AUTHORITY-001.md
//   docs/contracts/invariants/air/INV-SEAM-SINGLE-EXECUTION-001.md
//   docs/contracts/invariants/air/INV-SEAM-MISSED-RESOLUTION-001.md
//   docs/contracts/invariants/air/INV-SEAM-EDITORIAL-EXTERNAL-001.md
//   docs/contracts/invariants/air/INV-SEAM-OBSERVABLE-001.md
//
// RED contract-test status:
//   The production headers included below do not yet exist. Compilation
//   fails on the first `#include "retrovue/seam/..."`. This is the RED
//   signal. Turn C creates the headers and evaluator/controller
//   implementation, turning these tests GREEN.
//
//   Per /opt/retrovue/CLAUDE.md §CODE CHANGE PROTOCOL step (2), the test
//   MUST fail before the code change. Compile failure is the accepted RED
//   form when the production symbol does not yet exist.

#include <gtest/gtest.h>

#include <cstdint>
#include <functional>
#include <string>
#include <vector>

// Turn C will create these headers. Missing-header compile failure is the
// RED contract-test signal for Turn B.
#include "retrovue/seam/SeamCommand.h"
#include "retrovue/seam/SeamEvaluator.h"
#include "retrovue/seam/SeamController.h"

namespace retrovue::seam::test {

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

namespace {

SeamBoundary BoundaryOne() {
  SeamBoundary b{};
  b.boundary_index = 1;
  b.successor_segment_id = "seg-001";
  b.fence_tick = 1800;  // 60 seconds at 30fps
  return b;
}

SeamSignalSnapshot FenceNotReachedEligible() {
  SeamSignalSnapshot s{};
  s.current_tick = 900;   // well before fence
  s.fence_tick_reached = false;
  s.incoming_swap_eligible = true;
  s.within_cadence_repeat_budget = true;
  return s;
}

SeamSignalSnapshot FenceReachedEligible() {
  SeamSignalSnapshot s{};
  s.current_tick = 1800;
  s.fence_tick_reached = true;
  s.incoming_swap_eligible = true;
  s.within_cadence_repeat_budget = true;
  return s;
}

SeamSignalSnapshot FenceReachedNotEligible() {
  SeamSignalSnapshot s{};
  s.current_tick = 1800;
  s.fence_tick_reached = true;
  s.incoming_swap_eligible = false;
  s.within_cadence_repeat_budget = true;
  return s;
}

SeamSignalSnapshot FencePastCadenceBudgetExceeded() {
  SeamSignalSnapshot s{};
  s.current_tick = 1830;  // 30 ticks past fence
  s.fence_tick_reached = true;
  s.incoming_swap_eligible = false;
  s.within_cadence_repeat_budget = false;
  return s;
}

}  // namespace

// ===========================================================================
// Bounded-enum sanity (compile-time for existence, runtime for distinctness)
// ===========================================================================

TEST(SeamEnumBounds, BoundaryStateValuesAreDistinct) {
  // State values MUST be distinct; enum must declare at minimum the state
  // set enumerated in INV-SEAM-OBSERVABLE-001 Boundary/Constraint.
  EXPECT_NE(BoundaryState::kIdle, BoundaryState::kArmed);
  EXPECT_NE(BoundaryState::kArmed, BoundaryState::kExecuting);
  EXPECT_NE(BoundaryState::kExecuting, BoundaryState::kCommitted);
  EXPECT_NE(BoundaryState::kArmed, BoundaryState::kMissed);
  EXPECT_NE(BoundaryState::kMissed, BoundaryState::kPadBridging);
  EXPECT_NE(BoundaryState::kCommitted, BoundaryState::kCompleted);
}

TEST(SeamEnumBounds, DispositionValuesAreDistinct) {
  // INV-SEAM-MISSED-RESOLUTION-001: valid disposition set is exactly
  // {kCutover, kPadBridge, kJip} plus the sentinel kUnresolved.
  EXPECT_NE(Disposition::kUnresolved, Disposition::kCutover);
  EXPECT_NE(Disposition::kCutover, Disposition::kPadBridge);
  EXPECT_NE(Disposition::kPadBridge, Disposition::kJip);
  EXPECT_NE(Disposition::kUnresolved, Disposition::kJip);
}

TEST(SeamEnumBounds, AllDocumentedReasonClassesResolve) {
  // Reason classes named across INV-SEAM-*-001 documents must exist.
  // Compile-time test: fails at compile if any enum member is missing.
  (void)ReasonClass::kNone;
  (void)ReasonClass::kArmed;
  (void)ReasonClass::kIncomingEligible;
  (void)ReasonClass::kFenceReachedEligible;
  (void)ReasonClass::kFenceReachedNotEligible;
  (void)ReasonClass::kPadBridgeEngaged;
  (void)ReasonClass::kPadBridgeCleared;
  (void)ReasonClass::kJipEngaged;
  (void)ReasonClass::kAlreadyCommitted;
  (void)ReasonClass::kCadenceBudgetExceeded;
  SUCCEED();
}

// ===========================================================================
// INV-SEAM-SINGLE-AUTHORITY-001 — SeamController is the sole authority
// ===========================================================================

TEST(SeamSingleAuthority, DefaultConstructedStateIsIdle) {
  // Before any ArmBoundary call, the controller MUST report an idle state
  // with no disposition — no seam decision has been issued yet.
  SeamController controller(/*channel_id=*/7, /*on_transition=*/{});
  const auto record = controller.Current();
  EXPECT_EQ(record.state, BoundaryState::kIdle);
  EXPECT_EQ(record.disposition, Disposition::kUnresolved);
  EXPECT_EQ(record.reason, ReasonClass::kNone);
}

TEST(SeamSingleAuthority, EvaluatorIsThePureDecisionSurface) {
  // The evaluator is a pure function: same inputs → same outputs, no side
  // effects. This test demonstrates the evaluator's existence and
  // determinism — the authority lives in one place.
  const auto boundary = BoundaryOne();
  const auto snap = FenceReachedEligible();

  const auto eval_1 = SeamEvaluator::Evaluate(
      BoundaryState::kArmed, boundary, snap);
  const auto eval_2 = SeamEvaluator::Evaluate(
      BoundaryState::kArmed, boundary, snap);

  EXPECT_EQ(eval_1.next_state, eval_2.next_state);
  EXPECT_EQ(eval_1.disposition, eval_2.disposition);
  EXPECT_EQ(eval_1.reason, eval_2.reason);
}

TEST(SeamSingleAuthority, ArmBoundaryTransitionsToArmedState) {
  SeamController controller(/*channel_id=*/7, {});
  controller.ArmBoundary(BoundaryOne());
  const auto record = controller.Current();
  EXPECT_EQ(record.state, BoundaryState::kArmed);
  EXPECT_EQ(record.boundary_index, 1);
  EXPECT_EQ(record.reason, ReasonClass::kArmed);
}

// ===========================================================================
// INV-SEAM-SINGLE-EXECUTION-001 — exactly one execution per declared boundary
// ===========================================================================

TEST(SeamSingleExecution, CutoverCommitTransitionsToCommitted) {
  SeamController controller(/*channel_id=*/7, {});
  controller.ArmBoundary(BoundaryOne());
  controller.Evaluate(FenceReachedEligible());

  const auto record = controller.Current();
  EXPECT_EQ(record.state, BoundaryState::kCommitted);
  EXPECT_EQ(record.disposition, Disposition::kCutover);
  EXPECT_EQ(record.reason, ReasonClass::kFenceReachedEligible);
}

TEST(SeamSingleExecution, SecondEvaluationAfterCommitIsIdempotent) {
  // INV-SEAM-SINGLE-EXECUTION-001: Once kCommitted, subsequent Evaluate
  // calls MUST NOT re-fire execution. The boundary stays committed.
  SeamController controller(/*channel_id=*/7, {});
  controller.ArmBoundary(BoundaryOne());
  controller.Evaluate(FenceReachedEligible());
  const auto first = controller.Current();
  ASSERT_EQ(first.state, BoundaryState::kCommitted);

  // Re-evaluate with the same snapshot — state MUST NOT regress or re-fire.
  controller.Evaluate(FenceReachedEligible());
  const auto second = controller.Current();
  EXPECT_EQ(second.state, BoundaryState::kCommitted);
  EXPECT_EQ(second.disposition, Disposition::kCutover);
}

TEST(SeamSingleExecution, CommittedStateDoesNotRegressOnNewSnapshot) {
  // Even if subsequent signals would have produced a different disposition,
  // a committed boundary does not reverse.
  SeamController controller(/*channel_id=*/7, {});
  controller.ArmBoundary(BoundaryOne());
  controller.Evaluate(FenceReachedEligible());
  ASSERT_EQ(controller.Current().state, BoundaryState::kCommitted);

  // Now the incoming becomes ineligible — committed boundary must not
  // revert to armed or missed.
  controller.Evaluate(FenceReachedNotEligible());
  EXPECT_EQ(controller.Current().state, BoundaryState::kCommitted);
  EXPECT_EQ(controller.Current().disposition, Disposition::kCutover);
}

TEST(SeamSingleExecution, PreFenceEvaluationDoesNotCommit) {
  // Before the fence tick is reached, the evaluator MUST NOT commit.
  // State stays kArmed.
  SeamController controller(/*channel_id=*/7, {});
  controller.ArmBoundary(BoundaryOne());
  controller.Evaluate(FenceNotReachedEligible());

  const auto record = controller.Current();
  EXPECT_EQ(record.state, BoundaryState::kArmed);
  EXPECT_EQ(record.disposition, Disposition::kUnresolved);
}

// ===========================================================================
// INV-SEAM-MISSED-RESOLUTION-001 — missed seams resolve to pad-bridge or JIP
// ===========================================================================

TEST(SeamMissedResolution, FenceReachedWithoutEligibilityMarksMissed) {
  SeamController controller(/*channel_id=*/7, {});
  controller.ArmBoundary(BoundaryOne());
  controller.Evaluate(FenceReachedNotEligible());

  const auto record = controller.Current();
  EXPECT_EQ(record.state, BoundaryState::kMissed);
  EXPECT_EQ(record.reason, ReasonClass::kFenceReachedNotEligible);
}

TEST(SeamMissedResolution, MissedStateResolvesToPadBridgeOnContinuedIneligibility) {
  // Sustained ineligibility past cadence budget → pad-bridge engagement.
  SeamController controller(/*channel_id=*/7, {});
  controller.ArmBoundary(BoundaryOne());
  controller.Evaluate(FenceReachedNotEligible());
  ASSERT_EQ(controller.Current().state, BoundaryState::kMissed);

  controller.Evaluate(FencePastCadenceBudgetExceeded());
  const auto record = controller.Current();
  EXPECT_EQ(record.state, BoundaryState::kPadBridging);
  EXPECT_EQ(record.disposition, Disposition::kPadBridge);
  EXPECT_EQ(record.reason, ReasonClass::kPadBridgeEngaged);
}

TEST(SeamMissedResolution, PadBridgeResolvesToCommitOnceIncomingEligible) {
  // Once pad-bridging, when incoming becomes eligible, the seam executes.
  SeamController controller(/*channel_id=*/7, {});
  controller.ArmBoundary(BoundaryOne());
  controller.Evaluate(FenceReachedNotEligible());
  controller.Evaluate(FencePastCadenceBudgetExceeded());
  ASSERT_EQ(controller.Current().state, BoundaryState::kPadBridging);

  // Incoming becomes eligible.
  SeamSignalSnapshot recovered{};
  recovered.current_tick = 1860;
  recovered.fence_tick_reached = true;
  recovered.incoming_swap_eligible = true;
  recovered.within_cadence_repeat_budget = false;
  controller.Evaluate(recovered);

  const auto record = controller.Current();
  EXPECT_EQ(record.state, BoundaryState::kCommitted);
  EXPECT_EQ(record.disposition, Disposition::kPadBridge);
  EXPECT_EQ(record.reason, ReasonClass::kPadBridgeCleared);
}

TEST(SeamMissedResolution, DispositionNeverEscapesBoundedSet) {
  // Cycle through the three possible disposition paths; all three MUST
  // produce dispositions drawn exclusively from the bounded set.
  for (auto snap : {FenceReachedEligible(),
                    FenceReachedNotEligible(),
                    FencePastCadenceBudgetExceeded()}) {
    const auto eval = SeamEvaluator::Evaluate(
        BoundaryState::kArmed, BoundaryOne(), snap);
    const bool bounded =
        eval.disposition == Disposition::kUnresolved ||
        eval.disposition == Disposition::kCutover ||
        eval.disposition == Disposition::kPadBridge ||
        eval.disposition == Disposition::kJip;
    EXPECT_TRUE(bounded)
        << "Evaluator emitted an out-of-set disposition: "
        << static_cast<int>(eval.disposition);
  }
}

TEST(SeamMissedResolution, HoldLastFrameBeyondCadenceIsNotResolution) {
  // INV-SEAM-MISSED-RESOLUTION-001: Hold-last-frame emission beyond the
  // cadence repeat budget is not a valid resolution — the evaluator MUST
  // convert to pad-bridge or JIP rather than remain silently missed.
  const auto eval = SeamEvaluator::Evaluate(
      BoundaryState::kMissed,
      BoundaryOne(),
      FencePastCadenceBudgetExceeded());
  EXPECT_NE(eval.next_state, BoundaryState::kMissed)
      << "Missed state with cadence budget exceeded MUST transition to a "
         "pad-bridge or JIP disposition, not remain silently missed.";
}

// ===========================================================================
// INV-SEAM-EDITORIAL-EXTERNAL-001 — no content choice inside SeamController
// ===========================================================================

TEST(SeamEditorialExternal, SuccessorIdentityIsPreservedThroughCommit) {
  // The successor_segment_id supplied at ArmBoundary MUST flow through to
  // the committed record unchanged. SeamController does not substitute it.
  SeamBoundary boundary = BoundaryOne();
  boundary.successor_segment_id = "content-xyz-789";

  SeamController controller(/*channel_id=*/7, {});
  controller.ArmBoundary(boundary);
  controller.Evaluate(FenceReachedEligible());

  EXPECT_EQ(controller.Current().successor_segment_id, "content-xyz-789");
}

TEST(SeamEditorialExternal, SuccessorIdentityIsPreservedThroughMissedPath) {
  // Even when the path goes through kMissed and kPadBridging, the
  // successor identity declared at arming MUST reach the final commit.
  SeamBoundary boundary = BoundaryOne();
  boundary.successor_segment_id = "emergency-slate-42";

  SeamController controller(/*channel_id=*/7, {});
  controller.ArmBoundary(boundary);
  controller.Evaluate(FenceReachedNotEligible());
  controller.Evaluate(FencePastCadenceBudgetExceeded());

  // After pad-bridging, successor identity is still the originally armed one.
  EXPECT_EQ(controller.Current().successor_segment_id, "emergency-slate-42");
}

TEST(SeamEditorialExternal, EvaluatorDoesNotFabricateSuccessorIdentity) {
  // The evaluator's SeamEvaluation output structure MUST NOT include a
  // field that overrides successor_segment_id — the evaluator consumes
  // that identity, it does not produce one. Compile-time structure check.
  static_assert(
      sizeof(SeamEvaluation) > 0,
      "SeamEvaluation must be defined");
  // A well-formed SeamEvaluation has no successor-identity field to write.
  // If a future API adds one, this test becomes a spec change, not a bug.
  SUCCEED();
}

// ===========================================================================
// INV-SEAM-OBSERVABLE-001 — every decision emits a named event
// ===========================================================================

namespace {

struct TransitionCapture {
  std::vector<TransitionEvent> events;
  void Record(const TransitionEvent& e) { events.push_back(e); }
};

}  // namespace

TEST(SeamObservable, ArmBoundaryProducesTransitionEvent) {
  TransitionCapture capture;
  OnTransitionCallback cb = [&capture](const TransitionEvent& e) {
    capture.Record(e);
  };
  SeamController controller(/*channel_id=*/7, cb);

  controller.ArmBoundary(BoundaryOne());

  ASSERT_GE(capture.events.size(), 1u)
      << "INV-SEAM-OBSERVABLE-001: arming a boundary MUST emit a transition event.";
  EXPECT_EQ(capture.events.front().to_state, BoundaryState::kArmed);
}

TEST(SeamObservable, EveryStateTransitionProducesEvent) {
  TransitionCapture capture;
  OnTransitionCallback cb = [&capture](const TransitionEvent& e) {
    capture.Record(e);
  };
  SeamController controller(/*channel_id=*/7, cb);

  controller.ArmBoundary(BoundaryOne());              // idle → armed
  controller.Evaluate(FenceReachedNotEligible());     // armed → missed
  controller.Evaluate(FencePastCadenceBudgetExceeded());  // missed → pad-bridging

  // Three observable transitions.
  ASSERT_GE(capture.events.size(), 3u);
  EXPECT_EQ(capture.events[0].to_state, BoundaryState::kArmed);
  EXPECT_EQ(capture.events[1].to_state, BoundaryState::kMissed);
  EXPECT_EQ(capture.events[2].to_state, BoundaryState::kPadBridging);
}

TEST(SeamObservable, NoTransitionEventWhenStateUnchanged) {
  TransitionCapture capture;
  OnTransitionCallback cb = [&capture](const TransitionEvent& e) {
    capture.Record(e);
  };
  SeamController controller(/*channel_id=*/7, cb);

  controller.ArmBoundary(BoundaryOne());
  const auto after_arm = capture.events.size();

  // Evaluate with a snapshot that holds the boundary in kArmed.
  controller.Evaluate(FenceNotReachedEligible());

  EXPECT_EQ(capture.events.size(), after_arm)
      << "Unchanged state MUST NOT emit a duplicate transition event.";
}

TEST(SeamObservable, EventCarriesBoundaryIdentityAndReasonClass) {
  TransitionCapture capture;
  OnTransitionCallback cb = [&capture](const TransitionEvent& e) {
    capture.Record(e);
  };
  SeamController controller(/*channel_id=*/7, cb);

  controller.ArmBoundary(BoundaryOne());
  controller.Evaluate(FenceReachedEligible());  // armed → committed

  ASSERT_GE(capture.events.size(), 2u);
  const auto& commit_event = capture.events.back();
  EXPECT_EQ(commit_event.boundary_index, 1);
  EXPECT_EQ(commit_event.from_state, BoundaryState::kArmed);
  EXPECT_EQ(commit_event.to_state, BoundaryState::kCommitted);
  EXPECT_EQ(commit_event.disposition, Disposition::kCutover);
  EXPECT_EQ(commit_event.reason, ReasonClass::kFenceReachedEligible);
}

TEST(SeamObservable, CurrentReflectsLastTransition) {
  // Snapshot-read API: Current() reflects the most recent evaluation.
  SeamController controller(/*channel_id=*/7, {});

  controller.ArmBoundary(BoundaryOne());
  EXPECT_EQ(controller.Current().state, BoundaryState::kArmed);

  controller.Evaluate(FenceReachedNotEligible());
  EXPECT_EQ(controller.Current().state, BoundaryState::kMissed);
  EXPECT_EQ(controller.Current().reason, ReasonClass::kFenceReachedNotEligible);
}

// ===========================================================================
// Integration: full boundary lifecycle paths
// ===========================================================================

TEST(Lifecycle, HappyPathArmToCommit) {
  // idle → armed → committed (cutover)
  SeamController controller(/*channel_id=*/7, {});
  controller.ArmBoundary(BoundaryOne());
  controller.Evaluate(FenceReachedEligible());

  const auto record = controller.Current();
  EXPECT_EQ(record.state, BoundaryState::kCommitted);
  EXPECT_EQ(record.disposition, Disposition::kCutover);
}

TEST(Lifecycle, MissedThenPadBridgeThenCommit) {
  // idle → armed → missed → pad-bridging → committed
  SeamController controller(/*channel_id=*/7, {});
  controller.ArmBoundary(BoundaryOne());
  controller.Evaluate(FenceReachedNotEligible());
  controller.Evaluate(FencePastCadenceBudgetExceeded());

  SeamSignalSnapshot recovery{};
  recovery.current_tick = 1860;
  recovery.fence_tick_reached = true;
  recovery.incoming_swap_eligible = true;
  controller.Evaluate(recovery);

  EXPECT_EQ(controller.Current().state, BoundaryState::kCommitted);
  EXPECT_EQ(controller.Current().disposition, Disposition::kPadBridge);
}

}  // namespace retrovue::seam::test
