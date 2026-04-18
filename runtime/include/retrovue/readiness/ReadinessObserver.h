// Readiness observer — consumes snapshots, emits transitions.
//
// Contracts:
//   docs/contracts/invariants/air/INV-READINESS-OBSERVABLE-001.md
//   docs/contracts/invariants/air/INV-READINESS-SINGLE-OWNER-001.md
//
// Phase 1: additive observer. No runtime behaviour changes. The observer
// consumes existing signal-edge notifications, evaluates via
// ReadinessEvaluator, and emits a TransitionEvent on every verdict change
// and on every reason-class change inside DEGRADED.
//
// Thread-safety: single-threaded per channel. External synchronization
// required if invoked from multiple signal-edge threads concurrently.

#ifndef RETROVUE_READINESS_READINESS_OBSERVER_H_
#define RETROVUE_READINESS_READINESS_OBSERVER_H_

#include <cstdint>
#include <memory>

#include "retrovue/readiness/ReadinessVerdict.h"

namespace retrovue::telemetry {
class MetricsExporter;
}

namespace retrovue::readiness {

class ReadinessObserver {
 public:
  // `exporter` and `on_transition` are both optional. Phase 1 wires
  // `on_transition` for contract-test observation; production metrics
  // integration via `exporter` is intentionally deferred.
  explicit ReadinessObserver(
      int32_t channel_id,
      std::shared_ptr<telemetry::MetricsExporter> exporter = nullptr,
      OnTransitionCallback on_transition = {});

  ReadinessObserver(const ReadinessObserver&) = delete;
  ReadinessObserver& operator=(const ReadinessObserver&) = delete;

  // Evaluate the snapshot, emit a transition event if verdict or reason
  // class changed, and update Current().
  void Evaluate(const SessionReadinessSnapshot& snapshot);

  // Current verdict record. Reflects the most recent Evaluate() call, or
  // the initial sentinel (NOT_READY + kStartupNotPrimed, utc_ms=0) when no
  // Evaluate has occurred.
  [[nodiscard]] VerdictRecord Current() const;

 private:
  int32_t channel_id_;
  std::shared_ptr<telemetry::MetricsExporter> exporter_;
  OnTransitionCallback on_transition_;
  VerdictRecord current_;
};

}  // namespace retrovue::readiness

#endif  // RETROVUE_READINESS_READINESS_OBSERVER_H_
