// Readiness verdict model — canonical type surface for ReadinessController.
//
// Contracts:
//   docs/contracts/invariants/air/INV-VERDICT-BOUNDED-STATES-001.md
//   docs/contracts/invariants/air/INV-VERDICT-REASON-CLASS-BOUNDED-001.md
//   docs/contracts/invariants/air/INV-READINESS-SCOPE-INDEPENDENCE-001.md
//
// Phase 1 additive observer. Consumed by the evaluator, the observer, and
// contract tests. No production component other than the readiness module
// writes these types.

#ifndef RETROVUE_READINESS_READINESS_VERDICT_H_
#define RETROVUE_READINESS_READINESS_VERDICT_H_

#include <cstdint>
#include <functional>

#include "retrovue/runtime/PlayoutControl.h"

namespace retrovue::readiness {

// INV-VERDICT-BOUNDED-STATES-001: exactly three values.
enum class Verdict {
  kReady,
  kNotReady,
  kDegraded,
};

// INV-VERDICT-REASON-CLASS-BOUNDED-001: bounded reason-class set.
enum class ReasonClass {
  kNone,                          // companion to kReady
  kStartupNotPrimed,              // phase=kIdle|kBuffering or primed-false pre-ready
  kOutputPathNotLive,             // sink not attached while phase is running
  kShuttingDown,                  // phase=kStopping
  kErrorState,                    // phase=kError
  kSessionEnded,                  // terminal: SessionEnded(reason=error|lookahead_exhausted)
  kPostPrimedUnderflow,           // terminal: fatal underflow after first ready
  kAvPhaseOutOfTolerance,         // DEGRADED: A/V delta outside tolerance post-ready
  kFallbackEngagedPostStart,      // DEGRADED: fallback engaged after first ready
  kPrimedLostPostStart,           // DEGRADED: primed lost after first ready
  kNoObservability,               // scope signals cannot be observed
};

struct VerdictRecord {
  Verdict verdict = Verdict::kNotReady;
  ReasonClass reason = ReasonClass::kStartupNotPrimed;
  int64_t utc_ms = 0;
};

// Session-scope readiness input.
//
// Aggregates the signal set recorded in Readiness Signal Inventory §Recommended
// Phase 1 Minimal Set. Producer components continue to own their individual
// accessors; this snapshot type is the readiness authority's read model.
struct SessionReadinessSnapshot {
  runtime::PlayoutControl::RuntimePhase phase =
      runtime::PlayoutControl::RuntimePhase::kIdle;
  bool sink_attached = false;
  bool video_primed = false;
  bool audio_primed = false;
  bool av_delta_within_tolerance = false;
  bool fallback_engaged = false;
  bool session_ended_error = false;
  bool fatal_underflow_emitted = false;
  bool has_ever_been_ready = false;
  int64_t utc_ms = 0;
};

// Candidate-source-scope readiness input. Phase 1 surface — only the active
// source is observable; non-active candidates report NOT_READY with
// kNoObservability. Evaluated independently from the session snapshot
// (INV-READINESS-SCOPE-INDEPENDENCE-001).
struct CandidateSourceReadinessSnapshot {
  bool source_opened = false;
  bool per_source_primed = false;
  bool eof_signalled = false;
  bool is_active_source = false;
  int64_t utc_ms = 0;
};

// Transition event emitted by ReadinessObserver on every verdict change or
// reason-class change inside DEGRADED. INV-READINESS-OBSERVABLE-001.
struct TransitionEvent {
  Verdict from_verdict = Verdict::kNotReady;
  Verdict to_verdict = Verdict::kNotReady;
  ReasonClass reason = ReasonClass::kStartupNotPrimed;
  int64_t utc_ms = 0;
};

using OnTransitionCallback = std::function<void(const TransitionEvent&)>;

}  // namespace retrovue::readiness

#endif  // RETROVUE_READINESS_READINESS_VERDICT_H_
