// Bootstrap content-gate command model — canonical type surface.
//
// Contracts:
//   docs/contracts/invariants/air/INV-BOOTSTRAP-CONTINUITY-001.md
//   docs/contracts/invariants/air/INV-BOOTSTRAP-CONTENT-PARKED-001.md
//   docs/contracts/invariants/air/INV-BOOTSTRAP-CONTENT-ORIGIN-001.md
//   docs/contracts/invariants/air/INV-BOOTSTRAP-KICKOFF-ATOMIC-001.md
//   docs/contracts/invariants/air/INV-BOOTSTRAP-PTS-CONTINUOUS-001.md
//
// Option C bootstrap content-gate extraction. Consumed by
// BootstrapGateEvaluator (pure), BootstrapContentGate (stateful), and
// contract tests. No production component other than BootstrapContentGate
// writes these types.

#ifndef RETROVUE_BOOTSTRAP_BOOTSTRAP_COMMAND_H_
#define RETROVUE_BOOTSTRAP_BOOTSTRAP_COMMAND_H_

#include <cstdint>
#include <functional>

namespace retrovue::bootstrap {

// The bootstrap content gate has exactly two states.
//   kClosed: emission path routes pad video + silence audio; no real
//            content is consumed from lookahead buffers.
//   kOpen:   emission path routes real audio and video from lookahead
//            buffers. Sticky — once opened, the gate remains open for
//            the remainder of the session.
enum class GateState {
  kClosed,
  kOpen,
};

// Per-state emission routing decision. Returned by BootstrapContentGate
// for the current state; consumed by the tick-loop enforcement surface
// to choose between pad/silence and real-content pop.
enum class EmissionDecision {
  kPadSilence,
  kRealContent,
};

// Per-evaluation snapshot supplied to BootstrapGateEvaluator. Source
// timestamps are microseconds on both streams so the evaluator may
// compare them directly.
//
// audio_front_src_pts_us / video_front_src_pts_us: the source-content
// timestamp of the sample or frame currently at the consumption front
// of the respective lookahead buffer. -1 indicates the buffer is empty.
//
// output_frame_duration_us: the tolerance window within which the two
// buffer-front source times MUST agree for the gate to open
// (INV-BOOTSTRAP-CONTENT-ORIGIN-001).
struct BootstrapSnapshot {
  int64_t tick_index = 0;
  int audio_depth_ms = 0;
  int audio_floor_ms = 0;
  int video_depth_frames = 0;
  int video_floor_frames = 0;
  int64_t audio_front_src_pts_us = -1;
  int64_t video_front_src_pts_us = -1;
  int output_frame_duration_us = 33367;
};

// Emitted once when the gate transitions kClosed -> kOpen
// (INV-BOOTSTRAP-KICKOFF-ATOMIC-001). Diagnostic fields only; this
// event MUST NOT carry any PTS-origin mutation directive
// (INV-BOOTSTRAP-PTS-CONTINUOUS-001).
struct KickoffEvent {
  int64_t tick_index = -1;
  int64_t audio_front_src_pts_us = -1;
  int64_t video_front_src_pts_us = -1;
  int64_t front_delta_us = 0;
};

using OnKickoffCallback = std::function<void(const KickoffEvent&)>;

// Off-thread observability snapshot consumed by a Prometheus
// CustomMetricsProvider. Produced by the getter that captures the
// pipeline's BootstrapContentGate state under the ControlBox mutex.
// Kept here (rather than inside PlayoutEngine) so PlayoutInterface.h can
// reference it without pulling the full engine header.
//
// Turn D scope: the snapshot carries BOTH gates' open moments so the
// Option C predicate can be compared head-to-head with the production
// phase-gate predicate in every live session:
//   - new gate:      BootstrapContentGate (Option C)
//   - existing gate: EvaluateBootstrapPhaseGate phase_valid break
// front_delta_us values are origin-corrected (segment-local microseconds).
struct GateMetricsSnapshot {
  // --- New gate (BootstrapContentGate / Option C) ---
  GateState state = GateState::kClosed;
  bool kickoff_fired = false;
  KickoffEvent last_kickoff{};

  // --- Existing gate (EvaluateBootstrapPhaseGate) ---
  bool existing_gate_opened = false;
  int64_t existing_gate_front_delta_us = 0;
  int existing_gate_audio_depth_ms = 0;
  int existing_gate_video_depth_frames = 0;

  // True iff the new gate was already kOpen at the moment the existing
  // gate opened. Together with last_kickoff.tick_index this yields the
  // ordering answer:
  //   new_was_open_at_existing_open == true  -> new opened BEFORE existing
  //   new_was_open_at_existing_open == false AND kickoff_fired AND
  //     last_kickoff.tick_index < 0          -> same wait-loop iteration
  //   kickoff_fired AND last_kickoff.tick_index >= 0
  //                                           -> new opened AFTER existing
  //                                              by last_kickoff.tick_index
  //                                              main-loop ticks
  bool new_gate_was_open_at_existing_open = false;
};

}  // namespace retrovue::bootstrap

#endif  // RETROVUE_BOOTSTRAP_BOOTSTRAP_COMMAND_H_
