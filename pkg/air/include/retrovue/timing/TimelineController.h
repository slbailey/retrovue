// Repository: Retrovue-playout
// Component: Timeline Controller
// Purpose: Phase 8 unified timeline authority - single owner of channel time (CT).
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_TIMING_TIMELINE_CONTROLLER_H_
#define RETROVUE_TIMING_TIMELINE_CONTROLLER_H_

#include <atomic>
#include <cstdint>
#include <memory>
#include <mutex>
#include <optional>

namespace retrovue::timing {

class MasterClock;

// Phase 8 Contract: Frame admission result
enum class AdmissionResult {
  ADMITTED,       // Frame accepted, CT assigned
  REJECTED_LATE,  // Frame too far behind CT_cursor
  REJECTED_EARLY, // Frame too far ahead of CT_cursor
  REJECTED_NO_MAPPING  // No segment mapping active
};

// =============================================================================
// INV-P8-SWITCH-002: Type-safe pending segment modes
// =============================================================================
// These types make it IMPOSSIBLE to create a pending segment with:
//   - a carried-forward CT (from old live)
//   - a preview-derived MT
// That state literally cannot be represented.
// =============================================================================

// Pending segment mode - determines how CT and MT are resolved
enum class PendingSegmentMode {
  AwaitPreviewFrame,   // Preview will define BOTH MT and CT (common case)
  AbsoluteMapping      // Both CT and MT provided together upfront (rare)
};

// Unique segment identifier for tracking
using SegmentId = uint64_t;

// Pending segment state - opaque handle returned to caller
struct PendingSegment {
  SegmentId id;
  PendingSegmentMode mode;
};

// Phase 8 Contract: Segment mapping for MT -> CT conversion
struct SegmentMapping {
  int64_t ct_segment_start_us;  // CT when this segment began output
  int64_t mt_segment_start_us;  // MT of first admitted frame from this segment

  // Convert media time to channel time using this mapping
  int64_t MediaToChannel(int64_t mt_us) const {
    return ct_segment_start_us + (mt_us - mt_segment_start_us);
  }
};

// Phase 8 Contract: Frame with media time (input to TimelineController)
struct MediaFrame {
  int64_t media_time_us;  // MT: position in source asset
  // Other frame data would be here (pixels, audio samples, etc.)
  // For now, we only need the timing metadata
};

// Phase 8 Contract: Frame with assigned channel time (output from TimelineController)
struct AdmittedFrame {
  int64_t channel_time_us;  // CT: assigned position in channel timeline
  int64_t media_time_us;    // MT: original media position (for provenance)
  // Other frame data would be here
};

// Configuration for admission thresholds
struct TimelineConfig {
  int64_t tolerance_us = 33'333;        // Snap-to-grid tolerance (1 frame at 30fps)
  int64_t late_threshold_us = 500'000;  // Max late before rejection (500ms)
  int64_t early_threshold_us = 500'000; // Max early before rejection (500ms)
  int64_t catch_up_limit_us = 5'000'000; // Max CT lag before session restart (5s)
  int64_t frame_period_us = 33'333;     // Frame period (1/fps in microseconds)

  // Derive from fps
  static TimelineConfig FromFps(double fps, int target_depth = 5, int max_depth = 30) {
    TimelineConfig cfg;
    cfg.frame_period_us = static_cast<int64_t>(1'000'000.0 / fps);
    cfg.tolerance_us = cfg.frame_period_us;
    cfg.late_threshold_us = std::min(static_cast<int64_t>(500'000), static_cast<int64_t>(target_depth) * cfg.frame_period_us);
    cfg.early_threshold_us = static_cast<int64_t>(max_depth) * cfg.frame_period_us;
    return cfg;
  }
};

// TimelineController: Phase 8 unified timeline authority
//
// Responsibilities (from ScheduleManagerPhase8Contract):
// - Own CT_cursor (the current channel time position)
// - Compute and store epoch at session start
// - Accept frames with MT metadata from producers
// - Assign CT to each admitted frame using the segment mapping
// - Reject frames whose computed CT falls outside the admission window
// - Advance CT_cursor by one frame period per admitted frame (frame-driven model)
//
// The TimelineController is the ONLY component that may assign CT values.
// Producers emit MT only; they are "time-blind" to the channel timeline.
class TimelineController {
 public:
  explicit TimelineController(std::shared_ptr<MasterClock> clock,
                               TimelineConfig config = TimelineConfig());
  ~TimelineController() = default;

  // Disable copy/move
  TimelineController(const TimelineController&) = delete;
  TimelineController& operator=(const TimelineController&) = delete;

  // ========================================================================
  // Session Lifecycle
  // ========================================================================

  // Starts a new session, establishing epoch from current wall-clock time.
  // CT_cursor is set to 0. Clears any existing segment mapping.
  // Returns false if a session is already active.
  bool StartSession();

  // Ends the current session. Clears all timeline state.
  // Safe to call even if no session is active.
  void EndSession();

  // Returns true if a session is currently active.
  bool IsSessionActive() const;

  // ========================================================================
  // Segment Mapping (Type-Safe API - INV-P8-SWITCH-002)
  // ========================================================================
  // The segment mapping API is designed to make dangerous states unrepresentable.
  // There are exactly TWO ways to begin a segment:
  //
  // 1. BeginSegmentFromPreview() - Preview defines BOTH CT and MT
  //    Used during segment switching. The first preview frame locks the mapping.
  //    CT = wall_clock_at_first_frame - epoch
  //    MT = first_frame_media_time
  //
  // 2. BeginSegmentAbsolute(ct, mt) - Both CT and MT provided together
  //    Used at session start or when both values are known upfront.
  //    CT and MT must be provided together - partial specification is impossible.
  //
  // The OLD APIs (SetSegmentMapping, BeginSegment, BeginSegmentPending) are
  // DELETED because they allowed partial specification which caused timeline bugs.
  // ========================================================================

  // Case 1: Preview-driven segment (common case during switching)
  // Preview will define BOTH MT and CT when first frame arrives.
  // Returns a handle to the pending segment for tracking.
  PendingSegment BeginSegmentFromPreview();

  // Case 2: Absolute segment (session start, or when both values known)
  // BOTH CT and MT must be provided together - no partial state possible.
  // Returns a handle to the segment for tracking.
  PendingSegment BeginSegmentAbsolute(int64_t ct_start_us, int64_t mt_start_us);

  // Returns true if a segment mapping is pending (awaiting preview frame).
  bool IsMappingPending() const;

  // Returns the current pending segment mode, or nullopt if not pending.
  std::optional<PendingSegmentMode> GetPendingMode() const;

  // Returns the current segment mapping, or nullopt if none set.
  std::optional<SegmentMapping> GetSegmentMapping() const;

  // ========================================================================
  // INV-P8-SEGMENT-COMMIT: Explicit segment commit detection
  // ========================================================================
  // In broadcast terms, "commit" is when a pending segment locks its mapping
  // and becomes the authoritative owner of the timeline. At commit:
  //   - The new segment owns CT
  //   - The old segment is dead (must be closed)
  //   - Switch orchestration can proceed
  // ========================================================================

  // Returns true if a segment has committed (mapping locked, not pending).
  // NOTE: This is STATE, not EDGE. For edge detection, use GetSegmentCommitGeneration().
  bool HasSegmentCommitted() const;

  // Returns the ID of the currently active (committed) segment.
  // Returns 0 if no segment is active.
  SegmentId GetActiveSegmentId() const;

  // INV-P8-SEGMENT-COMMIT-EDGE: Generation counter for commit edge detection.
  // Increments exactly once each time a segment commits (mapping locks).
  // Use this to detect commit EDGES across multiple switches:
  //   if (current_gen > last_seen_gen) { /* commit happened */ }
  // This works for 1st, 2nd, Nth switches.
  uint64_t GetSegmentCommitGeneration() const;

  // ORCH-SWITCH-SUCCESSOR-OBSERVED: Segment commit is not observable until at
  // least one real successor video frame has been emitted by the encoder.
  // When mapping locks we set commit_pending_successor_emission_; commit_gen
  // advances only when this is called (from sink after encoding a real frame).
  //
  // =========================================================================
  // Phase 10 Compliance: DIAGNOSTIC-ONLY
  // =========================================================================
  // This method is DIAGNOSTIC-ONLY.
  // It MUST NOT:
  //   - gate segment switching
  //   - influence CT, epoch, or admission
  //   - be consulted for readiness, pacing, or selection
  // Sink callbacks MUST NOT become timing or control authority.
  // =========================================================================
  void RecordSuccessorEmissionDiagnostic();

  // When true, commit_gen advances only after RecordSuccessorEmissionDiagnostic().
  // When false (e.g. tests with no sink), commit_gen advances when mapping locks.
  void SetEmissionObserverAttached(bool attached);

  // ========================================================================
  // Frame Admission (Core Phase 8 Operation)
  // ========================================================================

  // Attempts to admit a frame with the given media time.
  // On success (ADMITTED), returns the assigned channel time in out_ct_us.
  // On failure, out_ct_us is undefined.
  //
  // This is the central Phase 8 operation:
  // 1. Compute CT_frame using segment mapping
  // 2. Check admission window (late_threshold, early_threshold)
  // 3. If admitted: assign CT, advance CT_cursor
  // 4. If rejected: log reason, do not advance CT_cursor
  AdmissionResult AdmitFrame(int64_t media_time_us, int64_t& out_ct_us);

  // ========================================================================
  // Timeline State (Read-Only)
  // ========================================================================

  // Returns the current CT cursor position in microseconds.
  int64_t GetCTCursor() const;

  // Returns the epoch (wall-clock time corresponding to CT=0).
  int64_t GetEpoch() const;

  // Returns the expected CT for the next frame (CT_cursor + frame_period).
  int64_t GetExpectedNextCT() const;

  // Returns the current segment's MT start (for diagnostics).
  // Returns -1 if no segment mapping is active.
  int64_t GetSegmentMTStart() const;

  // Returns the wall-clock deadline for a given CT position.
  int64_t GetWallClockDeadline(int64_t ct_us) const;

  // ========================================================================
  // Catch-Up Detection (Phase 8 Section 5.6)
  // ========================================================================

  // Returns true if we are in catch-up mode (CT behind wall-clock).
  bool IsInCatchUp() const;

  // Returns the current lag: W_now - (epoch + CT_cursor).
  // Positive = CT is behind wall-clock (catch-up needed).
  // Negative = CT is ahead of wall-clock (normal/buffered).
  int64_t GetLag() const;

  // Returns true if lag exceeds catch_up_limit (session should restart).
  bool ShouldRestartSession() const;

  // ========================================================================
  // INV-FRAME-003: Frame-Indexed CT Computation (for padding)
  // ========================================================================
  // CT derives from frame index, never the inverse. This method computes CT
  // for a given frame index relative to a known starting CT.
  // Used by structural padding (BlackFrameProducer) to assign CT to black frames.
  // ========================================================================

  // Computes CT for a given frame index, relative to a start CT.
  // ct = start_ct + (frame_index * frame_period_us)
  // This is the ONLY correct way to compute CT for padding frames.
  int64_t ComputeCTFromFrameIndex(int64_t start_ct_us, int64_t frame_index) const {
    return start_ct_us + (frame_index * config_.frame_period_us);
  }

  // Returns the frame period (1/fps) in microseconds.
  int64_t GetFramePeriodUs() const { return config_.frame_period_us; }

  // ========================================================================
  // INV-P8-SHADOW-PREROLL-SYNC: Advance CT cursor for pre-buffered frames
  // ========================================================================
  // During shadow preroll, frames are pushed to the buffer without going
  // through AdmitFrame, so ct_cursor doesn't advance. After the switch,
  // when the mapping is locked and we know how many frames were pre-buffered,
  // call this to sync ct_cursor to account for those frames.
  //
  // This allows the producer to continue adding frames sequentially without
  // getting REJECTED_EARLY for being "ahead" of where ct_cursor thinks we are.
  //
  // Example: Shadow preroll buffered 60 frames. After switch:
  //   ct_cursor = CT_start - frame_period (expects frame 0)
  //   AdvanceCursorForPreBufferedFrames(60)
  //   ct_cursor = CT_start + 59*frame_period (expects frame 60)
  // ========================================================================
  void AdvanceCursorForPreBufferedFrames(size_t frame_count);

  // ========================================================================
  // Statistics
  // ========================================================================

  struct Stats {
    uint64_t frames_admitted = 0;
    uint64_t frames_rejected_late = 0;
    uint64_t frames_rejected_early = 0;
    uint64_t catch_up_events = 0;      // Times we entered catch-up mode
    int64_t max_lag_us = 0;            // Worst lag observed
  };

  Stats GetStats() const;
  void ResetStats();

 private:
  // Internal helper - computes lag without taking mutex (caller must hold it)
  int64_t GetLagUnlocked() const;

  std::shared_ptr<MasterClock> clock_;
  TimelineConfig config_;

  mutable std::mutex mutex_;

  // Session state
  bool session_active_ = false;
  int64_t epoch_us_ = 0;
  int64_t ct_cursor_us_ = 0;

  // Active segment mapping (set when segment is locked)
  std::optional<SegmentMapping> segment_mapping_;

  // ==========================================================================
  // INV-P8-SWITCH-002: Type-safe pending segment state
  // ==========================================================================
  // The pending_segment_ holds the pending state. Its mode determines behavior:
  //   - AwaitPreviewFrame: Both CT and MT locked from first preview frame
  //   - AbsoluteMapping: Already resolved (segment_mapping_ is set)
  //
  // There is NO state where CT is set but MT is pending. That's the bug we fixed.
  // ==========================================================================
  std::optional<PendingSegment> pending_segment_;
  SegmentId next_segment_id_ = 1;

  // INV-P8-SEGMENT-COMMIT: Track the currently active (committed) segment
  SegmentId current_segment_id_ = 0;  // 0 = no active segment

  // INV-P8-SEGMENT-COMMIT-EDGE: Generation counter for commit edge detection
  // Increments exactly once per commit. Allows detecting commit edges across
  // multiple switches (1st, 2nd, Nth).
  //
  // PHASE 10 GUARD: This is DIAGNOSTIC / ORCHESTRATION SEQUENCE ONLY.
  // It MUST NOT gate switching, admission, pacing, CT, or epoch.
  // Used solely to trigger predecessor retirement after successor emission.
  uint64_t segment_commit_generation_ = 0;

  // ORCH-SWITCH-SUCCESSOR-OBSERVED: Commit gen does not advance until sink has
  // emitted at least one real (non-pad) video frame after mapping lock.
  bool commit_pending_successor_emission_ = false;
  bool emission_observer_attached_ = false;

  // Statistics
  Stats stats_;
  bool was_in_catch_up_ = false;  // For detecting catch-up transitions
};

}  // namespace retrovue::timing

#endif  // RETROVUE_TIMING_TIMELINE_CONTROLLER_H_
