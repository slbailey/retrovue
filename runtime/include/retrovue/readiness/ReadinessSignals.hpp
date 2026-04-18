// Readiness signals — neutral protocol struct shared between the BlockPlan
// layer (producer of values via PipelineManager::CaptureReadinessSignals)
// and the Readiness layer (consumer of values via the Turn D observer's
// CustomMetricsProvider lambda).
//
// Phase 1 additive. No hot-path code. Struct is POD-like; copy is cheap.
//
// Contracts:
//   docs/contracts/invariants/air/INV-READINESS-*.md
//   docs/contracts/invariants/air/INV-VERDICT-*.md
//   docs/contracts/invariants/air/INV-BOOTSTRAP-AV-PHASE-001.md (derivation basis)
//   docs/contracts/invariants/air/INV-FILL-AV-LEAD-CLAMP-001.md (tolerance source)

#ifndef RETROVUE_READINESS_READINESS_SIGNALS_HPP_
#define RETROVUE_READINESS_READINESS_SIGNALS_HPP_

namespace retrovue::readiness {

// A point-in-time snapshot of per-session BlockPlan signals that feed the
// readiness verdict. Populated by the BlockPlan execution engine on demand
// (e.g. from a CustomMetricsProvider scrape), consumed by ReadinessObserver.
//
// `snapshot_valid` is false when the producing layer cannot safely supply
// values (e.g. buffers not yet constructed, pipeline not yet started).
// Consumers MUST treat a `snapshot_valid == false` snapshot as "no
// observation available" and fall back to neutral stubs — matching the
// behaviour of a running session that has no BlockPlan layer attached yet.
struct PipelineSignals {
  bool snapshot_valid = false;     // true iff the fields below were read from real buffer state
  bool video_primed = false;       // VideoLookaheadBuffer::IsPrimed()
  bool audio_primed = false;       // AudioLookaheadBuffer::IsPrimed()
  int audio_depth_ms = 0;          // AudioLookaheadBuffer::DepthMs()
  int video_depth_frames = 0;      // VideoLookaheadBuffer::DepthFrames()
  int av_phase_tolerance_ms = 0;   // VideoLookaheadBuffer::AvPhaseToleranceMs()
  int av_delta_ms = 0;             // audio_depth_ms - video_time_ms_equiv (computed)
  bool av_within_tolerance = true; // |av_delta_ms| <= av_phase_tolerance_ms
};

}  // namespace retrovue::readiness

#endif  // RETROVUE_READINESS_READINESS_SIGNALS_HPP_
