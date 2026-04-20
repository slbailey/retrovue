// AIR vNext — SeamController implementation.
//
// See seam_controller.hpp for scope. Per INV-SEGMENT-SEAM-ARM-COMMIT-001,
// once the controller reaches kCommittedForTick the fence tick is locked
// and the seam must execute; subsequent readiness changes MUST NOT demote
// state.

#include "seam_controller.hpp"

#include <cassert>
#include <chrono>
#include <utility>

namespace retrovue::air {

namespace {

int64_t NowMonoUs() {
  return std::chrono::duration_cast<std::chrono::microseconds>(
             std::chrono::steady_clock::now().time_since_epoch())
      .count();
}

}  // namespace

const char* ToString(SeamPhase p) {
  switch (p) {
    case SeamPhase::kIdle:             return "idle";
    case SeamPhase::kObserving:        return "observing";
    case SeamPhase::kArmed:            return "armed";
    case SeamPhase::kCommittedForTick: return "committed_for_tick";
    case SeamPhase::kFiring:           return "firing";
    case SeamPhase::kComplete:         return "complete";
  }
  return "?";
}

const char* ToString(SeamEventKind k) {
  switch (k) {
    case SeamEventKind::kArmed:     return "seam.armed";
    case SeamEventKind::kDisarmed:  return "seam.disarmed";
    case SeamEventKind::kCommitted: return "seam.committed";
    case SeamEventKind::kExecuted:  return "seam.executed";
  }
  return "?";
}

SeamController::SeamController(SeamConfig cfg, NextSegmentReadyFn next_ready)
    : cfg_(cfg), next_ready_(std::move(next_ready)) {}

void SeamController::SetEventObserver(SeamEventObserver obs) {
  observer_ = std::move(obs);
}

void SeamController::Emit(const SeamEvent& ev) {
  if (observer_) observer_(ev);
}

void SeamController::ObserveSeam(SeamTarget target) {
  assert(phase_ == SeamPhase::kIdle || phase_ == SeamPhase::kComplete);
  target_ = std::move(target);
  phase_ = SeamPhase::kObserving;
}

bool SeamController::Retract(const std::string& reason) {
  if (phase_ != SeamPhase::kObserving && phase_ != SeamPhase::kArmed) {
    // Commit is sticky. Retract is a no-op from kCommittedForTick onward.
    return false;
  }
  SeamEvent ev{.kind = SeamEventKind::kDisarmed,
               .mono_us = NowMonoUs(),
               .target = target_.value_or(SeamTarget{}),
               .reason = reason};
  phase_ = SeamPhase::kIdle;
  target_.reset();
  Emit(ev);
  return true;
}

void SeamController::Tick(int64_t current_tick_us) {
  // Monotonic progression; each Tick can advance at most one step.
  // (Multiple conditions hitting in a single Tick still advance one step
  // per call — the encode loop calls Tick every frame, so sub-ms latency
  // from arm→commit is fine.)
  if (!target_.has_value()) return;

  const int64_t fence = target_->fence_monotonic_us;

  switch (phase_) {
    case SeamPhase::kIdle:
    case SeamPhase::kComplete:
      return;

    case SeamPhase::kObserving: {
      const bool window_open = (fence - current_tick_us) <= cfg_.arm_window_us;
      const bool ready = next_ready_ ? next_ready_() : false;
      if (window_open && ready) {
        phase_ = SeamPhase::kArmed;
        Emit({.kind = SeamEventKind::kArmed,
              .mono_us = NowMonoUs(),
              .target = *target_});
      }
      return;
    }

    case SeamPhase::kArmed: {
      // Commit on next Tick after arm, provided readiness still holds.
      // Readiness regression does NOT demote; the controller stays armed.
      const bool ready = next_ready_ ? next_ready_() : false;
      if (ready) {
        phase_ = SeamPhase::kCommittedForTick;
        Emit({.kind = SeamEventKind::kCommitted,
              .mono_us = NowMonoUs(),
              .target = *target_});
      }
      return;
    }

    case SeamPhase::kCommittedForTick:
      if (current_tick_us >= fence) phase_ = SeamPhase::kFiring;
      return;

    case SeamPhase::kFiring:
      // Waits for MarkFired(). No auto-advance.
      return;
  }
}

bool SeamController::ShouldCommitAt(int64_t /*current_tick_us*/) const {
  return phase_ == SeamPhase::kFiring;
}

void SeamController::MarkFired(int64_t current_tick_us) {
  assert(phase_ == SeamPhase::kFiring);
  if (phase_ != SeamPhase::kFiring) return;
  SeamEvent ev{.kind = SeamEventKind::kExecuted,
               .mono_us = NowMonoUs(),
               .target = *target_,
               .executed_at_tick_us = current_tick_us};
  phase_ = SeamPhase::kComplete;
  Emit(ev);
}

void SeamController::Reset() {
  phase_ = SeamPhase::kIdle;
  target_.reset();
}

}  // namespace retrovue::air
