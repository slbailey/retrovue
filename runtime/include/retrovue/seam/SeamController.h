// Seam controller — stateful per-channel owner of seam-decision state.
//
// Contracts:
//   docs/contracts/invariants/air/INV-SEAM-SINGLE-AUTHORITY-001.md
//   docs/contracts/invariants/air/INV-SEAM-SINGLE-EXECUTION-001.md
//   docs/contracts/invariants/air/INV-SEAM-OBSERVABLE-001.md
//
// Phase 1 ADR-006 step 2: SeamController is the sole authority for
// seam-decision state transitions. It consumes snapshots via Evaluate(),
// delegates the decision to SeamEvaluator (pure), and emits a
// TransitionEvent on every state / disposition / reason change.
//
// Thread-safety: single-threaded per channel. External synchronization
// required if invoked from multiple signal-edge threads concurrently.

#ifndef RETROVUE_SEAM_SEAM_CONTROLLER_H_
#define RETROVUE_SEAM_SEAM_CONTROLLER_H_

#include <cstdint>

#include "retrovue/seam/SeamCommand.h"

namespace retrovue::seam {

class SeamController {
 public:
  // `on_transition` is optional. Phase 1 wires it for contract-test
  // observation; production metrics integration is additive.
  explicit SeamController(int32_t channel_id,
                          OnTransitionCallback on_transition = {});

  SeamController(const SeamController&) = delete;
  SeamController& operator=(const SeamController&) = delete;

  // Arm a declared boundary for tracking. Transitions the controller's
  // state from kIdle to kArmed and emits a transition event. Successor
  // identity from the boundary is preserved through the subsequent
  // lifecycle (INV-SEAM-EDITORIAL-EXTERNAL-001).
  void ArmBoundary(const SeamBoundary& boundary);

  // Evaluate the current boundary against a new signal snapshot.
  // Short-circuits on terminal states (kCommitted, kCompleted) per
  // INV-SEAM-SINGLE-EXECUTION-001 — no re-evaluation after commit.
  // Emits a transition event if state, disposition, or reason changed.
  void Evaluate(const SeamSignalSnapshot& snap);

  // Current decision record. Reflects the most recent ArmBoundary/Evaluate
  // call, or the default {kIdle, kUnresolved, kNone} sentinel if neither
  // has occurred.
  [[nodiscard]] SeamDecisionRecord Current() const;

 private:
  void EmitIfChanged(const SeamDecisionRecord& prev,
                     const SeamDecisionRecord& next);

  int32_t channel_id_;
  OnTransitionCallback on_transition_;
  SeamBoundary active_boundary_;
  SeamDecisionRecord current_;
};

}  // namespace retrovue::seam

#endif  // RETROVUE_SEAM_SEAM_CONTROLLER_H_
