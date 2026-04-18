// Readiness evaluator implementation.
//
// Implements the Session Scope Matrix and Candidate Source Scope Matrix
// from the vault note "Readiness Verdict Derivation Matrix". Every branch
// in this file has a corresponding row in that matrix and is exercised by
// runtime/tests/contracts/readiness/ReadinessInvariantTests.cpp.

#include "retrovue/readiness/ReadinessEvaluator.h"

namespace retrovue::readiness {

namespace {

using Phase = runtime::PlayoutControl::RuntimePhase;

// Does the phase indicate "session is not currently in a running state" —
// i.e. startup, shutdown, or error. These phases dominate positive signals.
bool PhaseIsNonRunning(Phase p) {
  return p == Phase::kIdle ||
         p == Phase::kBuffering ||
         p == Phase::kStopping ||
         p == Phase::kError;
}

ReasonClass StartupOrShutdownReason(Phase p) {
  switch (p) {
    case Phase::kError:
      return ReasonClass::kErrorState;
    case Phase::kStopping:
      return ReasonClass::kShuttingDown;
    case Phase::kIdle:
    case Phase::kBuffering:
    default:
      return ReasonClass::kStartupNotPrimed;
  }
}

}  // namespace

VerdictRecord ReadinessEvaluator::EvaluateSession(
    const SessionReadinessSnapshot& snap) {
  // Precedence 1: terminal events outrank everything.
  if (snap.fatal_underflow_emitted) {
    return {Verdict::kNotReady, ReasonClass::kPostPrimedUnderflow, snap.utc_ms};
  }
  if (snap.session_ended_error) {
    return {Verdict::kNotReady, ReasonClass::kSessionEnded, snap.utc_ms};
  }

  // Precedence 2: phase-non-running outranks positive signals.
  if (PhaseIsNonRunning(snap.phase)) {
    return {Verdict::kNotReady, StartupOrShutdownReason(snap.phase), snap.utc_ms};
  }

  // Precedence 3: output-path liveness.
  if (!snap.sink_attached) {
    return {Verdict::kNotReady, ReasonClass::kOutputPathNotLive, snap.utc_ms};
  }

  // Precedence 4 (only reached with phase in {kReady, kPlaying, kPaused} and
  // sink attached): evaluate correctness-adjacent conditions.
  //
  // Before first READY, any unmet precondition keeps the session NOT_READY
  // with the startup reason. This prevents emitting DEGRADED during the
  // startup window.
  const bool primed_both = snap.video_primed && snap.audio_primed;
  const bool any_concern = snap.fallback_engaged ||
                           !snap.av_delta_within_tolerance ||
                           !primed_both;

  if (!snap.has_ever_been_ready) {
    if (any_concern) {
      return {Verdict::kNotReady, ReasonClass::kStartupNotPrimed, snap.utc_ms};
    }
    return {Verdict::kReady, ReasonClass::kNone, snap.utc_ms};
  }

  // Precedence 5: DEGRADED when any correctness concern is active after
  // first READY. Ordering here is deterministic but not load-bearing for
  // Phase 1 (no test case activates two concerns simultaneously).
  if (snap.fallback_engaged) {
    return {Verdict::kDegraded, ReasonClass::kFallbackEngagedPostStart,
            snap.utc_ms};
  }
  if (!snap.av_delta_within_tolerance) {
    return {Verdict::kDegraded, ReasonClass::kAvPhaseOutOfTolerance,
            snap.utc_ms};
  }
  if (!primed_both) {
    return {Verdict::kDegraded, ReasonClass::kPrimedLostPostStart, snap.utc_ms};
  }

  // Precedence 6: all preconditions satisfied.
  return {Verdict::kReady, ReasonClass::kNone, snap.utc_ms};
}

VerdictRecord ReadinessEvaluator::EvaluateCandidate(
    const CandidateSourceReadinessSnapshot& snap) {
  // Phase 1 minimal surface: Phase 1 can only observe the active source.
  // Non-active sources report NOT_READY with kNoObservability. This tracks
  // the deferred scope note in Readiness Verdict Derivation Matrix
  // §Candidate Source Scope Matrix.
  if (!snap.is_active_source) {
    return {Verdict::kNotReady, ReasonClass::kNoObservability, snap.utc_ms};
  }
  if (!snap.source_opened || !snap.per_source_primed || snap.eof_signalled) {
    return {Verdict::kNotReady, ReasonClass::kNoObservability, snap.utc_ms};
  }
  return {Verdict::kReady, ReasonClass::kNone, snap.utc_ms};
}

}  // namespace retrovue::readiness
