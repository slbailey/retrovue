// Bootstrap gate evaluator — pure predicate for Option C content gate.
//
// Implements INV-BOOTSTRAP-CONTENT-ORIGIN-001: the gate opens only when
// both lookahead buffers have reached their floor AND the source-content
// timestamps at the front of each buffer agree within one output-frame
// duration. No hidden state; same snapshot always yields the same result.

#ifndef RETROVUE_BOOTSTRAP_BOOTSTRAP_GATE_EVALUATOR_H_
#define RETROVUE_BOOTSTRAP_BOOTSTRAP_GATE_EVALUATOR_H_

#include "retrovue/bootstrap/BootstrapCommand.h"

namespace retrovue::bootstrap {

class BootstrapGateEvaluator {
 public:
  // Returns kOpen iff all preconditions are met; kClosed otherwise.
  static GateState Evaluate(const BootstrapSnapshot& snap);
};

}  // namespace retrovue::bootstrap

#endif  // RETROVUE_BOOTSTRAP_BOOTSTRAP_GATE_EVALUATOR_H_
