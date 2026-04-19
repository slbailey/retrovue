// Seam controller implementation.
//
// Phase 1 ADR-006 step 2. Stateful per-channel owner of the seam-decision
// state machine. Delegates per-tick decisions to SeamEvaluator (pure) and
// emits a TransitionEvent on every (state, disposition, reason) change.
//
// Terminal states (kCommitted, kCompleted) are sticky: Evaluate() short-
// circuits without calling the evaluator, guaranteeing exactly-one
// execution per declared boundary (INV-SEAM-SINGLE-EXECUTION-001).

#include "retrovue/seam/SeamController.h"

#include <utility>

#include "retrovue/seam/SeamEvaluator.h"

namespace retrovue::seam {

SeamController::SeamController(int32_t channel_id,
                               OnTransitionCallback on_transition)
    : channel_id_(channel_id),
      on_transition_(std::move(on_transition)),
      active_boundary_{},
      current_{} {}

void SeamController::ArmBoundary(const SeamBoundary& boundary) {
  const SeamDecisionRecord prev = current_;

  active_boundary_ = boundary;
  current_.state = BoundaryState::kArmed;
  current_.disposition = Disposition::kUnresolved;
  current_.reason = ReasonClass::kArmed;
  current_.boundary_index = boundary.boundary_index;
  current_.successor_segment_id = boundary.successor_segment_id;
  // utc_ms left at 0 in Phase 1; a clock injection is a later enrichment.

  EmitIfChanged(prev, current_);
}

void SeamController::Evaluate(const SeamSignalSnapshot& snap) {
  // INV-SEAM-SINGLE-EXECUTION-001: terminal states are sticky. A
  // committed boundary does not re-evaluate; its disposition survives
  // until the next ArmBoundary.
  if (current_.state == BoundaryState::kCommitted ||
      current_.state == BoundaryState::kCompleted) {
    return;
  }

  const SeamEvaluation eval =
      SeamEvaluator::Evaluate(current_.state, active_boundary_, snap);

  const SeamDecisionRecord prev = current_;
  current_.state = eval.next_state;
  current_.disposition = eval.disposition;
  current_.reason = eval.reason;
  // boundary_index and successor_segment_id are preserved from the
  // armed boundary — INV-SEAM-EDITORIAL-EXTERNAL-001.

  EmitIfChanged(prev, current_);
}

SeamDecisionRecord SeamController::Current() const {
  return current_;
}

void SeamController::EmitIfChanged(const SeamDecisionRecord& prev,
                                   const SeamDecisionRecord& next) {
  if (!on_transition_) return;

  const bool changed = prev.state != next.state ||
                       prev.disposition != next.disposition ||
                       prev.reason != next.reason;
  if (!changed) return;

  TransitionEvent event;
  event.boundary_index = next.boundary_index;
  event.from_state = prev.state;
  event.to_state = next.state;
  event.disposition = next.disposition;
  event.reason = next.reason;
  event.utc_ms = next.utc_ms;
  on_transition_(event);
}

}  // namespace retrovue::seam
