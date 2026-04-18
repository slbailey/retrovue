// Readiness observer implementation.
//
// Phase 1 additive observer. Consumes snapshots via Evaluate(), computes a
// verdict through ReadinessEvaluator, and emits a TransitionEvent to the
// injected callback when the verdict or reason class changes.
//
// The observer does not mutate runtime state. It does not write to any
// signal-producing component. It does not spawn threads or register
// timers. Phase 1 leaves MetricsExporter integration unwired; the
// `exporter` parameter is accepted for forward compatibility.

#include "retrovue/readiness/ReadinessObserver.h"

#include <utility>

#include "retrovue/readiness/ReadinessEvaluator.h"

namespace retrovue::readiness {

ReadinessObserver::ReadinessObserver(
    int32_t channel_id,
    std::shared_ptr<telemetry::MetricsExporter> exporter,
    OnTransitionCallback on_transition)
    : channel_id_(channel_id),
      exporter_(std::move(exporter)),
      on_transition_(std::move(on_transition)),
      current_{Verdict::kNotReady, ReasonClass::kStartupNotPrimed, 0} {}

void ReadinessObserver::Evaluate(const SessionReadinessSnapshot& snapshot) {
  const VerdictRecord next = ReadinessEvaluator::EvaluateSession(snapshot);

  const bool changed = next.verdict != current_.verdict ||
                       next.reason != current_.reason;
  if (changed && on_transition_) {
    TransitionEvent event;
    event.from_verdict = current_.verdict;
    event.to_verdict = next.verdict;
    event.reason = next.reason;
    event.utc_ms = next.utc_ms;
    on_transition_(event);
  }

  current_ = next;
}

VerdictRecord ReadinessObserver::Current() const {
  return current_;
}

}  // namespace retrovue::readiness
