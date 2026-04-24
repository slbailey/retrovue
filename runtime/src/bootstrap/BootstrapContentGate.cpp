// Bootstrap content gate implementation.
//
// Owns the per-session kClosed -> kOpen transition and emits a single
// KickoffEvent when the transition fires. The transition is atomic and
// session-sticky (INV-BOOTSTRAP-KICKOFF-ATOMIC-001).

#include "retrovue/bootstrap/BootstrapContentGate.h"

#include <cstdlib>
#include <utility>

#include "retrovue/bootstrap/BootstrapGateEvaluator.h"

namespace retrovue::bootstrap {

BootstrapContentGate::BootstrapContentGate(OnKickoffCallback on_kickoff)
    : state_(GateState::kClosed), on_kickoff_(std::move(on_kickoff)) {}

void BootstrapContentGate::Evaluate(const BootstrapSnapshot& snap) {
  if (state_ == GateState::kOpen) return;

  const GateState next = BootstrapGateEvaluator::Evaluate(snap);
  if (next != GateState::kOpen) return;

  state_ = GateState::kOpen;
  if (on_kickoff_) {
    KickoffEvent event;
    event.tick_index = snap.tick_index;
    event.audio_front_src_pts_us = snap.audio_front_src_pts_us;
    event.video_front_src_pts_us = snap.video_front_src_pts_us;
    event.front_delta_us =
        std::llabs(snap.audio_front_src_pts_us - snap.video_front_src_pts_us);
    on_kickoff_(event);
  }
}

GateState BootstrapContentGate::State() const {
  return state_;
}

EmissionDecision BootstrapContentGate::Decision() const {
  return state_ == GateState::kOpen ? EmissionDecision::kRealContent
                                    : EmissionDecision::kPadSilence;
}

bool BootstrapContentGate::AllowContentConsumption() const {
  return state_ == GateState::kOpen;
}

}  // namespace retrovue::bootstrap
