// Readiness evaluator — pure function mapping snapshot → verdict.
//
// Contracts:
//   docs/contracts/invariants/air/INV-READINESS-SINGLE-OWNER-001.md
//   docs/contracts/invariants/air/INV-READINESS-NOT-BYTE-INFERRED-001.md
//   docs/contracts/invariants/air/INV-READINESS-SCOPE-INDEPENDENCE-001.md
//
// Sole authority surface for the verdict. Derivation matrix in
// docs (vault): 07_problems/Readiness Verdict Derivation Matrix.md.
//
// Stateless. No threads. No I/O. No locks. No side effects.

#ifndef RETROVUE_READINESS_READINESS_EVALUATOR_H_
#define RETROVUE_READINESS_READINESS_EVALUATOR_H_

#include "retrovue/readiness/ReadinessVerdict.h"

namespace retrovue::readiness {

class ReadinessEvaluator {
 public:
  // Session-scope verdict. Precedence: terminal > phase-non-running >
  // output-path > NOT_READY > DEGRADED > READY.
  static VerdictRecord EvaluateSession(const SessionReadinessSnapshot& snap);

  // Candidate-source-scope verdict. Phase 1 surface: non-active sources
  // report NOT_READY + kNoObservability; active sources evaluate against
  // opened + primed + eof signals.
  static VerdictRecord EvaluateCandidate(
      const CandidateSourceReadinessSnapshot& snap);
};

}  // namespace retrovue::readiness

#endif  // RETROVUE_READINESS_READINESS_EVALUATOR_H_
