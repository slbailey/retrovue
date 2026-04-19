// Seam evaluator implementation.
//
// Implements the per-boundary state-transition table exercised by
// runtime/tests/contracts/seam/SeamAuthorityInvariantTests.cpp. Every
// branch here maps to at least one contract test that asserts the
// (next_state, disposition, reason) triple for its scenario.

#include "retrovue/seam/SeamEvaluator.h"

namespace retrovue::seam {

SeamEvaluation SeamEvaluator::Evaluate(BoundaryState current_state,
                                       const SeamBoundary& /*boundary*/,
                                       const SeamSignalSnapshot& snap) {
  switch (current_state) {
    case BoundaryState::kArmed:
      // Pre-fence: stay armed.
      if (!snap.fence_tick_reached) {
        return {BoundaryState::kArmed,
                Disposition::kUnresolved,
                ReasonClass::kArmed};
      }
      // Fence reached.
      if (snap.incoming_swap_eligible) {
        return {BoundaryState::kCommitted,
                Disposition::kCutover,
                ReasonClass::kFenceReachedEligible};
      }
      return {BoundaryState::kMissed,
              Disposition::kUnresolved,
              ReasonClass::kFenceReachedNotEligible};

    case BoundaryState::kMissed:
      // Late recovery: incoming became eligible after the miss.
      if (snap.incoming_swap_eligible) {
        return {BoundaryState::kCommitted,
                Disposition::kCutover,
                ReasonClass::kFenceReachedEligible};
      }
      // Cadence budget exhausted: engage pad-bridge per
      // INV-SEAM-MISSED-RESOLUTION-001 (hold-last-frame past the budget
      // is not a valid resolution).
      if (!snap.within_cadence_repeat_budget) {
        return {BoundaryState::kPadBridging,
                Disposition::kPadBridge,
                ReasonClass::kPadBridgeEngaged};
      }
      // Still missed, cadence budget not yet exhausted.
      return {BoundaryState::kMissed,
              Disposition::kUnresolved,
              ReasonClass::kFenceReachedNotEligible};

    case BoundaryState::kPadBridging:
      // Pad-bridge resolves once incoming becomes eligible. Disposition
      // stays kPadBridge to record the path the boundary took.
      if (snap.incoming_swap_eligible) {
        return {BoundaryState::kCommitted,
                Disposition::kPadBridge,
                ReasonClass::kPadBridgeCleared};
      }
      // Still pad-bridging.
      return {BoundaryState::kPadBridging,
              Disposition::kPadBridge,
              ReasonClass::kPadBridgeEngaged};

    case BoundaryState::kIdle:
    case BoundaryState::kExecuting:
    case BoundaryState::kCommitted:
    case BoundaryState::kCompleted:
    default:
      // Idle: controller arms via ArmBoundary(), not Evaluate().
      // Committed / Completed: terminal — SeamController short-circuits
      // before calling Evaluate (INV-SEAM-SINGLE-EXECUTION-001).
      return {current_state,
              Disposition::kUnresolved,
              ReasonClass::kNone};
  }
}

}  // namespace retrovue::seam
