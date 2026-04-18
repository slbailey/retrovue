// Contract tests for the readiness verdict invariants registered in
// docs/contracts/invariants/air/.
//
// Covered invariants:
//   INV-READINESS-SINGLE-OWNER-001         (single evaluator authority surface)
//   INV-READINESS-NOT-BYTE-INFERRED-001    (READY is not bytes-flowing)
//   INV-READINESS-OBSERVABLE-001           (transitions produce events)
//   INV-READINESS-SCOPE-INDEPENDENCE-001   (session vs candidate scope)
//   INV-VERDICT-BOUNDED-STATES-001         (three-state verdict)
//   INV-VERDICT-REASON-CLASS-BOUNDED-001   (bounded reason-class set)
//
// Cross-references:
//   docs/contracts/invariants/air/INV-READINESS-SINGLE-OWNER-001.md
//   docs/contracts/invariants/air/INV-READINESS-NOT-BYTE-INFERRED-001.md
//   docs/contracts/invariants/air/INV-READINESS-OBSERVABLE-001.md
//   docs/contracts/invariants/air/INV-READINESS-SCOPE-INDEPENDENCE-001.md
//   docs/contracts/invariants/air/INV-VERDICT-BOUNDED-STATES-001.md
//   docs/contracts/invariants/air/INV-VERDICT-REASON-CLASS-BOUNDED-001.md
//
// RED contract-test status:
//   The production headers included below do not yet exist. Compilation
//   fails on the first `#include "retrovue/readiness/..."`. This is the
//   RED signal. Turn C creates the headers and the evaluator implementation,
//   turning these tests GREEN.
//
//   Per /opt/retrovue/CLAUDE.md §CODE CHANGE PROTOCOL step (2), the test
//   MUST fail before the code change. Compile failure is the accepted RED
//   form when the production symbol does not yet exist.

#include <gtest/gtest.h>

#include <cstdint>
#include <functional>
#include <memory>
#include <vector>

#include "retrovue/runtime/PlayoutControl.h"

// Turn C will create these headers. Missing-header compile failure is the
// RED contract-test signal for Turn B.
#include "retrovue/readiness/ReadinessVerdict.h"
#include "retrovue/readiness/ReadinessEvaluator.h"
#include "retrovue/readiness/ReadinessObserver.h"

namespace retrovue::readiness::test {

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

namespace {

SessionReadinessSnapshot HealthySnapshot() {
  SessionReadinessSnapshot s{};
  s.phase = runtime::PlayoutControl::RuntimePhase::kPlaying;
  s.sink_attached = true;
  s.video_primed = true;
  s.audio_primed = true;
  s.av_delta_within_tolerance = true;
  s.fallback_engaged = false;
  s.session_ended_error = false;
  s.fatal_underflow_emitted = false;
  s.has_ever_been_ready = true;
  s.utc_ms = 1000;
  return s;
}

}  // namespace

// ===========================================================================
// INV-VERDICT-BOUNDED-STATES-001 — verdict has exactly three states
// ===========================================================================

TEST(VerdictBoundedStates, EnumValuesAreDistinct) {
  // The verdict set MUST be exactly {READY, NOT_READY, DEGRADED}. This test
  // fails to compile if the enum is missing any of the three, and fails at
  // runtime if any two collapse to the same value.
  EXPECT_NE(Verdict::kReady, Verdict::kNotReady);
  EXPECT_NE(Verdict::kReady, Verdict::kDegraded);
  EXPECT_NE(Verdict::kNotReady, Verdict::kDegraded);
}

TEST(VerdictBoundedStates, NoObservabilityReportsNotReady) {
  // A scope whose signals cannot currently be observed MUST be reported as
  // NOT_READY with a bounded reason class, not as a novel / absent value.
  CandidateSourceReadinessSnapshot cand{};
  cand.source_opened = false;
  cand.per_source_primed = false;
  cand.eof_signalled = false;
  cand.is_active_source = false;
  cand.utc_ms = 1000;

  const auto record = ReadinessEvaluator::EvaluateCandidate(cand);
  EXPECT_EQ(record.verdict, Verdict::kNotReady);
  EXPECT_EQ(record.reason, ReasonClass::kNoObservability);
}

// ===========================================================================
// INV-VERDICT-REASON-CLASS-BOUNDED-001 — reason classes are bounded
// ===========================================================================

TEST(VerdictReasonClassBounded, AllDocumentedReasonClassesResolve) {
  // Every reason class named in docs/contracts/invariants/air/
  // INV-VERDICT-REASON-CLASS-BOUNDED-001.md must exist in the enum.
  // Compile fails if any is missing.
  (void)ReasonClass::kNone;
  (void)ReasonClass::kStartupNotPrimed;
  (void)ReasonClass::kOutputPathNotLive;
  (void)ReasonClass::kShuttingDown;
  (void)ReasonClass::kErrorState;
  (void)ReasonClass::kSessionEnded;
  (void)ReasonClass::kPostPrimedUnderflow;
  (void)ReasonClass::kAvPhaseOutOfTolerance;
  (void)ReasonClass::kFallbackEngagedPostStart;
  (void)ReasonClass::kPrimedLostPostStart;
  (void)ReasonClass::kNoObservability;
  SUCCEED();
}

TEST(VerdictReasonClassBounded, ReadyCarriesNoneReasonClass) {
  // A READY verdict carries the distinguished kNone reason class, per the
  // Boundary/Constraint note that unqualified READY uses the no-reason
  // designator.
  const auto record = ReadinessEvaluator::EvaluateSession(HealthySnapshot());
  ASSERT_EQ(record.verdict, Verdict::kReady);
  EXPECT_EQ(record.reason, ReasonClass::kNone);
}

// ===========================================================================
// INV-READINESS-SINGLE-OWNER-001 — single evaluator authority surface
// ===========================================================================

TEST(ReadinessSingleOwner, EvaluatorIsTheSoleAuthoritySurface) {
  // The evaluator surface is the single call consumers may use to derive a
  // verdict from the snapshot signal set. This test documents that the
  // public API exposes exactly the session and candidate entry points.
  auto session_record = ReadinessEvaluator::EvaluateSession(HealthySnapshot());
  CandidateSourceReadinessSnapshot cand{};
  cand.source_opened = true;
  cand.per_source_primed = true;
  cand.eof_signalled = false;
  cand.is_active_source = true;
  cand.utc_ms = 1000;
  auto cand_record = ReadinessEvaluator::EvaluateCandidate(cand);

  // Both call paths produce a VerdictRecord with a bounded verdict value.
  EXPECT_TRUE(session_record.verdict == Verdict::kReady ||
              session_record.verdict == Verdict::kNotReady ||
              session_record.verdict == Verdict::kDegraded);
  EXPECT_TRUE(cand_record.verdict == Verdict::kReady ||
              cand_record.verdict == Verdict::kNotReady ||
              cand_record.verdict == Verdict::kDegraded);
}

// ===========================================================================
// INV-READINESS-NOT-BYTE-INFERRED-001 — READY is not bytes-flowing
// ===========================================================================

TEST(ReadinessNotByteInferred, SinkAttachedAlonInsufficientForReady) {
  // Sink attached + phase=kPlaying but primed=false: byte-path liveness
  // is present, READY MUST NOT fire.
  auto snap = HealthySnapshot();
  snap.video_primed = false;
  snap.audio_primed = false;
  snap.has_ever_been_ready = false;

  const auto record = ReadinessEvaluator::EvaluateSession(snap);
  EXPECT_NE(record.verdict, Verdict::kReady)
      << "INV-READINESS-NOT-BYTE-INFERRED-001: READY MUST require primed "
         "state; byte-path liveness alone is not sufficient.";
}

TEST(ReadinessNotByteInferred, AvPhaseOutOfToleranceForbidsReadyDespiteByteFlow) {
  // Bytes flowing (sink attached, phase kPlaying, primed true) but A/V
  // delta outside tolerance: READY MUST NOT fire pre-first-READY.
  auto snap = HealthySnapshot();
  snap.av_delta_within_tolerance = false;
  snap.has_ever_been_ready = false;

  const auto record = ReadinessEvaluator::EvaluateSession(snap);
  EXPECT_NE(record.verdict, Verdict::kReady)
      << "INV-READINESS-NOT-BYTE-INFERRED-001: READY MUST require A/V phase "
         "within tolerance; byte flow alone is not sufficient.";
}

// ===========================================================================
// INV-READINESS-SCOPE-INDEPENDENCE-001 — session vs candidate scopes
// ===========================================================================

TEST(ReadinessScopeIndependence, SessionReadyDoesNotImplyCandidateReady) {
  // A READY session verdict MUST NOT force any candidate source to be READY.
  const auto session_record =
      ReadinessEvaluator::EvaluateSession(HealthySnapshot());
  ASSERT_EQ(session_record.verdict, Verdict::kReady);

  // A candidate that is not opened must report NOT_READY independent of the
  // session's verdict.
  CandidateSourceReadinessSnapshot cand{};
  cand.source_opened = false;
  cand.per_source_primed = false;
  cand.eof_signalled = false;
  cand.is_active_source = false;
  cand.utc_ms = 1000;

  const auto cand_record = ReadinessEvaluator::EvaluateCandidate(cand);
  EXPECT_EQ(cand_record.verdict, Verdict::kNotReady);
}

TEST(ReadinessScopeIndependence, NotReadyCandidateDoesNotForceSessionNotReady) {
  // A NOT_READY candidate MUST NOT be consulted when computing session
  // verdict. Session derives from session-scope snapshot inputs only.
  const auto session_record =
      ReadinessEvaluator::EvaluateSession(HealthySnapshot());
  EXPECT_EQ(session_record.verdict, Verdict::kReady);
}

// ===========================================================================
// Derivation matrix coverage
// (docs/contracts/invariants/air/* + Readiness Verdict Derivation Matrix)
// ===========================================================================

TEST(DerivationMatrix, HealthySteadyStateYieldsReady) {
  const auto record = ReadinessEvaluator::EvaluateSession(HealthySnapshot());
  EXPECT_EQ(record.verdict, Verdict::kReady);
  EXPECT_EQ(record.reason, ReasonClass::kNone);
}

TEST(DerivationMatrix, StartupBufferingYieldsNotReady) {
  auto snap = HealthySnapshot();
  snap.phase = runtime::PlayoutControl::RuntimePhase::kBuffering;
  snap.video_primed = false;
  snap.audio_primed = false;
  snap.has_ever_been_ready = false;

  const auto record = ReadinessEvaluator::EvaluateSession(snap);
  EXPECT_EQ(record.verdict, Verdict::kNotReady);
  EXPECT_EQ(record.reason, ReasonClass::kStartupNotPrimed);
}

TEST(DerivationMatrix, IdleYieldsNotReady) {
  auto snap = HealthySnapshot();
  snap.phase = runtime::PlayoutControl::RuntimePhase::kIdle;
  snap.sink_attached = false;
  snap.video_primed = false;
  snap.audio_primed = false;
  snap.has_ever_been_ready = false;

  const auto record = ReadinessEvaluator::EvaluateSession(snap);
  EXPECT_EQ(record.verdict, Verdict::kNotReady);
  EXPECT_EQ(record.reason, ReasonClass::kStartupNotPrimed);
}

TEST(DerivationMatrix, SinkDetachedWhilePlayingYieldsNotReady) {
  auto snap = HealthySnapshot();
  snap.sink_attached = false;

  const auto record = ReadinessEvaluator::EvaluateSession(snap);
  EXPECT_EQ(record.verdict, Verdict::kNotReady);
  EXPECT_EQ(record.reason, ReasonClass::kOutputPathNotLive);
}

TEST(DerivationMatrix, StoppingYieldsNotReady) {
  auto snap = HealthySnapshot();
  snap.phase = runtime::PlayoutControl::RuntimePhase::kStopping;

  const auto record = ReadinessEvaluator::EvaluateSession(snap);
  EXPECT_EQ(record.verdict, Verdict::kNotReady);
  EXPECT_EQ(record.reason, ReasonClass::kShuttingDown);
}

TEST(DerivationMatrix, ErrorPhaseYieldsNotReady) {
  auto snap = HealthySnapshot();
  snap.phase = runtime::PlayoutControl::RuntimePhase::kError;

  const auto record = ReadinessEvaluator::EvaluateSession(snap);
  EXPECT_EQ(record.verdict, Verdict::kNotReady);
  EXPECT_EQ(record.reason, ReasonClass::kErrorState);
}

TEST(DerivationMatrix, SessionEndedErrorYieldsNotReadyTerminal) {
  auto snap = HealthySnapshot();
  snap.session_ended_error = true;

  const auto record = ReadinessEvaluator::EvaluateSession(snap);
  EXPECT_EQ(record.verdict, Verdict::kNotReady);
  EXPECT_EQ(record.reason, ReasonClass::kSessionEnded);
}

TEST(DerivationMatrix, FatalUnderflowYieldsNotReadyTerminal) {
  auto snap = HealthySnapshot();
  snap.fatal_underflow_emitted = true;

  const auto record = ReadinessEvaluator::EvaluateSession(snap);
  EXPECT_EQ(record.verdict, Verdict::kNotReady);
  EXPECT_EQ(record.reason, ReasonClass::kPostPrimedUnderflow);
}

TEST(DerivationMatrix, AvDriftAfterFirstReadyYieldsDegraded) {
  auto snap = HealthySnapshot();
  snap.av_delta_within_tolerance = false;
  // has_ever_been_ready = true from healthy base — mid-session drift.

  const auto record = ReadinessEvaluator::EvaluateSession(snap);
  EXPECT_EQ(record.verdict, Verdict::kDegraded);
  EXPECT_EQ(record.reason, ReasonClass::kAvPhaseOutOfTolerance);
}

TEST(DerivationMatrix, FallbackAfterFirstReadyYieldsDegraded) {
  auto snap = HealthySnapshot();
  snap.fallback_engaged = true;

  const auto record = ReadinessEvaluator::EvaluateSession(snap);
  EXPECT_EQ(record.verdict, Verdict::kDegraded);
  EXPECT_EQ(record.reason, ReasonClass::kFallbackEngagedPostStart);
}

TEST(DerivationMatrix, PrimedLostAfterFirstReadyYieldsDegraded) {
  auto snap = HealthySnapshot();
  snap.video_primed = false;  // primed was true during first READY

  const auto record = ReadinessEvaluator::EvaluateSession(snap);
  EXPECT_EQ(record.verdict, Verdict::kDegraded);
  EXPECT_EQ(record.reason, ReasonClass::kPrimedLostPostStart);
}

// ===========================================================================
// Precedence (Readiness Verdict Derivation Matrix §Precedence Rules)
// ===========================================================================

TEST(Precedence, TerminalEventOutranksDegradedConcern) {
  auto snap = HealthySnapshot();
  snap.fatal_underflow_emitted = true;
  snap.av_delta_within_tolerance = false;  // would otherwise be DEGRADED

  const auto record = ReadinessEvaluator::EvaluateSession(snap);
  EXPECT_EQ(record.verdict, Verdict::kNotReady);
  EXPECT_EQ(record.reason, ReasonClass::kPostPrimedUnderflow);
}

TEST(Precedence, PhaseNonRunningOutranksPositiveSignals) {
  auto snap = HealthySnapshot();
  snap.phase = runtime::PlayoutControl::RuntimePhase::kStopping;
  // All other preconditions remain satisfied; phase still wins.

  const auto record = ReadinessEvaluator::EvaluateSession(snap);
  EXPECT_EQ(record.verdict, Verdict::kNotReady);
  EXPECT_EQ(record.reason, ReasonClass::kShuttingDown);
}

TEST(Precedence, OutputPathLossOutranksCorrectnessConcern) {
  auto snap = HealthySnapshot();
  snap.sink_attached = false;
  snap.av_delta_within_tolerance = false;

  const auto record = ReadinessEvaluator::EvaluateSession(snap);
  EXPECT_EQ(record.verdict, Verdict::kNotReady);
  EXPECT_EQ(record.reason, ReasonClass::kOutputPathNotLive);
}

TEST(Precedence, NotReadyOutranksDegraded) {
  auto snap = HealthySnapshot();
  snap.phase = runtime::PlayoutControl::RuntimePhase::kStopping;
  snap.fallback_engaged = true;

  const auto record = ReadinessEvaluator::EvaluateSession(snap);
  EXPECT_EQ(record.verdict, Verdict::kNotReady);
}

TEST(Precedence, DegradedOutranksReadyWhenCorrectnessConcernActive) {
  auto snap = HealthySnapshot();
  snap.av_delta_within_tolerance = false;  // concern active after first ready

  const auto record = ReadinessEvaluator::EvaluateSession(snap);
  EXPECT_NE(record.verdict, Verdict::kReady);
  EXPECT_EQ(record.verdict, Verdict::kDegraded);
}

// ===========================================================================
// INV-READINESS-OBSERVABLE-001 — observer emits transition events
// ===========================================================================

namespace {

// Captures observer transition emissions for assertion. Injected via the
// observer's on_transition callback parameter.
struct TransitionCapture {
  std::vector<TransitionEvent> events;
  void Record(const TransitionEvent& e) { events.push_back(e); }
};

}  // namespace

TEST(ReadinessObservable, VerdictChangeProducesTransitionEvent) {
  TransitionCapture capture;
  OnTransitionCallback cb = [&capture](const TransitionEvent& e) {
    capture.Record(e);
  };

  ReadinessObserver observer(/*channel_id=*/42, /*exporter=*/nullptr, cb);

  // First evaluation: NOT_READY (not primed) → first transition.
  auto snap = HealthySnapshot();
  snap.video_primed = false;
  snap.audio_primed = false;
  snap.has_ever_been_ready = false;
  observer.Evaluate(snap);

  // Second evaluation: healthy → READY → transition.
  observer.Evaluate(HealthySnapshot());

  ASSERT_GE(capture.events.size(), 1u)
      << "INV-READINESS-OBSERVABLE-001: a verdict change MUST emit a "
         "transition event.";
  const auto& last = capture.events.back();
  EXPECT_EQ(last.to_verdict, Verdict::kReady);
}

TEST(ReadinessObservable, NoTransitionEventWhenVerdictUnchanged) {
  TransitionCapture capture;
  OnTransitionCallback cb = [&capture](const TransitionEvent& e) {
    capture.Record(e);
  };

  ReadinessObserver observer(/*channel_id=*/42, /*exporter=*/nullptr, cb);

  // Evaluate healthy twice; verdict does not change on the second call.
  observer.Evaluate(HealthySnapshot());
  const auto first_count = capture.events.size();
  observer.Evaluate(HealthySnapshot());

  EXPECT_EQ(capture.events.size(), first_count)
      << "Unchanged verdict MUST NOT emit duplicate transition events.";
}

TEST(ReadinessObservable, ReasonClassChangeWithinDegradedIsObservable) {
  TransitionCapture capture;
  OnTransitionCallback cb = [&capture](const TransitionEvent& e) {
    capture.Record(e);
  };

  ReadinessObserver observer(/*channel_id=*/42, /*exporter=*/nullptr, cb);

  // Enter DEGRADED via A/V phase drift.
  auto s1 = HealthySnapshot();
  s1.av_delta_within_tolerance = false;
  observer.Evaluate(s1);

  // Still DEGRADED, different reason class (fallback engaged).
  auto s2 = HealthySnapshot();
  s2.fallback_engaged = true;
  observer.Evaluate(s2);

  // Per INV-READINESS-OBSERVABLE-001: reason-class change inside DEGRADED
  // MUST emit a transition event even when the outer verdict is unchanged.
  ASSERT_GE(capture.events.size(), 2u)
      << "Reason-class change within DEGRADED MUST emit a transition event.";
}

TEST(ReadinessObservable, CurrentReflectsLastEvaluation) {
  // Current() is the snapshot read API; after Evaluate it MUST reflect the
  // verdict that was just computed.
  ReadinessObserver observer(/*channel_id=*/42, /*exporter=*/nullptr, {});

  observer.Evaluate(HealthySnapshot());
  EXPECT_EQ(observer.Current().verdict, Verdict::kReady);

  auto bad = HealthySnapshot();
  bad.sink_attached = false;
  observer.Evaluate(bad);
  EXPECT_EQ(observer.Current().verdict, Verdict::kNotReady);
  EXPECT_EQ(observer.Current().reason, ReasonClass::kOutputPathNotLive);
}

}  // namespace retrovue::readiness::test
