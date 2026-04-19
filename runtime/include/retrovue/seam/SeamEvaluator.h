// Seam evaluator — pure function mapping (current state, boundary, signals)
// to the next seam decision.
//
// Contracts:
//   docs/contracts/invariants/air/INV-SEAM-SINGLE-AUTHORITY-001.md
//   docs/contracts/invariants/air/INV-SEAM-SINGLE-EXECUTION-001.md
//   docs/contracts/invariants/air/INV-SEAM-MISSED-RESOLUTION-001.md
//
// Sole decision surface for seam transitions. Stateless. No threads.
// No I/O. No locks. No side effects.

#ifndef RETROVUE_SEAM_SEAM_EVALUATOR_H_
#define RETROVUE_SEAM_SEAM_EVALUATOR_H_

#include "retrovue/seam/SeamCommand.h"

namespace retrovue::seam {

class SeamEvaluator {
 public:
  // Compute the next seam decision from the current state, the declared
  // boundary, and the per-tick signal snapshot. The returned evaluation
  // carries (next_state, disposition, reason) with disposition drawn from
  // the bounded set per INV-SEAM-MISSED-RESOLUTION-001.
  //
  // Callers (SeamController) are responsible for short-circuiting
  // terminal states (kCommitted, kCompleted) — the evaluator itself
  // returns the current state unchanged if invoked on those.
  static SeamEvaluation Evaluate(BoundaryState current_state,
                                 const SeamBoundary& boundary,
                                 const SeamSignalSnapshot& snap);
};

}  // namespace retrovue::seam

#endif  // RETROVUE_SEAM_SEAM_EVALUATOR_H_
