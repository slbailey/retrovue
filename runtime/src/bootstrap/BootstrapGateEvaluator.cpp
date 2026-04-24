// Bootstrap gate evaluator implementation.
//
// INV-BOOTSTRAP-CONTENT-ORIGIN-001: the gate opens only when both
// buffer fronts are populated, both depth floors are met, and the
// source-time delta between the two fronts is within one output-frame
// duration.

#include "retrovue/bootstrap/BootstrapGateEvaluator.h"

#include <cstdlib>

namespace retrovue::bootstrap {

GateState BootstrapGateEvaluator::Evaluate(const BootstrapSnapshot& snap) {
  if (snap.audio_front_src_pts_us < 0 || snap.video_front_src_pts_us < 0) {
    return GateState::kClosed;
  }
  if (snap.audio_depth_ms < snap.audio_floor_ms) {
    return GateState::kClosed;
  }
  if (snap.video_depth_frames < snap.video_floor_frames) {
    return GateState::kClosed;
  }
  const int64_t delta =
      std::llabs(snap.audio_front_src_pts_us - snap.video_front_src_pts_us);
  if (delta > snap.output_frame_duration_us) {
    return GateState::kClosed;
  }
  return GateState::kOpen;
}

}  // namespace retrovue::bootstrap
