// Seam command model — canonical type surface for SeamController.
//
// Contracts:
//   docs/contracts/invariants/air/INV-SEAM-SINGLE-AUTHORITY-001.md
//   docs/contracts/invariants/air/INV-SEAM-SINGLE-EXECUTION-001.md
//   docs/contracts/invariants/air/INV-SEAM-MISSED-RESOLUTION-001.md
//   docs/contracts/invariants/air/INV-SEAM-EDITORIAL-EXTERNAL-001.md
//   docs/contracts/invariants/air/INV-SEAM-OBSERVABLE-001.md
//
// Phase 1 SeamController extraction (ADR-006 step 2). Consumed by
// SeamEvaluator (pure), SeamController (stateful), and contract tests.
// No production component other than SeamController writes these types.

#ifndef RETROVUE_SEAM_SEAM_COMMAND_H_
#define RETROVUE_SEAM_SEAM_COMMAND_H_

#include <cstdint>
#include <functional>
#include <string>

namespace retrovue::seam {

// INV-SEAM-OBSERVABLE-001 §Boundary/Constraint: the per-boundary state set.
enum class BoundaryState {
  kIdle,          // no boundary armed yet (controller default)
  kArmed,         // boundary registered; waiting for fence tick
  kExecuting,     // reserved for mid-transition modelling (not currently emitted)
  kCommitted,     // disposition committed; terminal for this boundary
  kMissed,        // fence reached without eligibility; awaiting resolution
  kPadBridging,   // missed seam bridged by pad until incoming becomes eligible
  kCompleted,     // reserved for post-commit bookkeeping (not currently emitted)
};

// INV-SEAM-MISSED-RESOLUTION-001: valid disposition set is exactly
// {kCutover, kPadBridge, kJip} plus the sentinel kUnresolved.
enum class Disposition {
  kUnresolved,   // companion to pre-commit states
  kCutover,      // normal seam execution at fence with eligible incoming
  kPadBridge,    // missed seam → pad until incoming eligible → cutover
  kJip,          // missed seam → start incoming at offset (reserved; not emitted in Phase 1)
};

// INV-SEAM-OBSERVABLE-001 §Boundary/Constraint: bounded reason-class set.
enum class ReasonClass {
  kNone,                       // companion to kIdle
  kArmed,                      // boundary has been armed
  kIncomingEligible,           // reserved informational signal
  kFenceReachedEligible,       // commit reason: fence reached, incoming eligible
  kFenceReachedNotEligible,    // miss reason: fence reached, incoming not eligible
  kPadBridgeEngaged,           // pad-bridge activated after missed seam
  kPadBridgeCleared,           // pad-bridge committed after incoming became eligible
  kJipEngaged,                 // reserved: JIP path
  kAlreadyCommitted,           // reserved: committed-state sustain
  kCadenceBudgetExceeded,      // reserved: cadence-budget telemetry label
};

// A single declared segment boundary from the active block plan.
// SeamController consumes this; it does not author one.
struct SeamBoundary {
  int32_t boundary_index = -1;        // position in declared segment sequence
  std::string successor_segment_id;   // Core-declared successor identity (INV-SEAM-EDITORIAL-EXTERNAL-001)
  int64_t fence_tick = 0;             // declared fence position in tick units
};

// Per-tick signal input to the seam evaluator. Produced by the runtime's
// readiness + fence-tracking surface.
struct SeamSignalSnapshot {
  int64_t current_tick = 0;
  bool fence_tick_reached = false;
  bool incoming_swap_eligible = false;
  bool within_cadence_repeat_budget = false;
};

// Record of the seam decision's current state. Returned by SeamController::Current.
struct SeamDecisionRecord {
  BoundaryState state = BoundaryState::kIdle;
  Disposition disposition = Disposition::kUnresolved;
  ReasonClass reason = ReasonClass::kNone;
  int32_t boundary_index = -1;
  std::string successor_segment_id;
  int64_t utc_ms = 0;
};

// Pure evaluator output. Stateless. Successor identity is deliberately
// absent — the evaluator does not fabricate it (INV-SEAM-EDITORIAL-EXTERNAL-001).
struct SeamEvaluation {
  BoundaryState next_state = BoundaryState::kIdle;
  Disposition disposition = Disposition::kUnresolved;
  ReasonClass reason = ReasonClass::kNone;
};

// Transition event emitted by SeamController on every state, disposition,
// or reason change. INV-SEAM-OBSERVABLE-001.
struct TransitionEvent {
  int32_t boundary_index = -1;
  BoundaryState from_state = BoundaryState::kIdle;
  BoundaryState to_state = BoundaryState::kIdle;
  Disposition disposition = Disposition::kUnresolved;
  ReasonClass reason = ReasonClass::kNone;
  int64_t utc_ms = 0;
};

using OnTransitionCallback = std::function<void(const TransitionEvent&)>;

}  // namespace retrovue::seam

#endif  // RETROVUE_SEAM_SEAM_COMMAND_H_
