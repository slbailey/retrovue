// Bootstrap content gate — stateful Option C controller.
//
// Wraps BootstrapGateEvaluator with per-session state. The gate starts
// closed and emits pad/silence; on the first snapshot that satisfies the
// evaluator's predicate it transitions to open, fires an OnKickoffCallback
// once, and remains open for the remainder of the session.
//
// Contracts:
//   INV-BOOTSTRAP-CONTINUITY-001      (pad + silence while closed)
//   INV-BOOTSTRAP-CONTENT-PARKED-001  (no real-content consumption while closed)
//   INV-BOOTSTRAP-CONTENT-ORIGIN-001  (fronts aligned at kickoff)
//   INV-BOOTSTRAP-KICKOFF-ATOMIC-001  (single atomic transition)
//   INV-BOOTSTRAP-PTS-CONTINUOUS-001  (no PTS-origin mutation at kickoff)

#ifndef RETROVUE_BOOTSTRAP_BOOTSTRAP_CONTENT_GATE_H_
#define RETROVUE_BOOTSTRAP_BOOTSTRAP_CONTENT_GATE_H_

#include "retrovue/bootstrap/BootstrapCommand.h"

namespace retrovue::bootstrap {

class BootstrapContentGate {
 public:
  explicit BootstrapContentGate(OnKickoffCallback on_kickoff = {});

  // Evaluate the content-gate predicate against a fresh snapshot.
  // Sticky: once the gate has opened, subsequent calls are a no-op.
  void Evaluate(const BootstrapSnapshot& snap);

  // Observational state surface consumed by the tick-loop enforcement.
  GateState State() const;
  EmissionDecision Decision() const;
  bool AllowContentConsumption() const;

 private:
  GateState state_;
  OnKickoffCallback on_kickoff_;
};

}  // namespace retrovue::bootstrap

#endif  // RETROVUE_BOOTSTRAP_BOOTSTRAP_CONTENT_GATE_H_
