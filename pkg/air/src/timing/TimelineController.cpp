// Repository: Retrovue-playout
// Component: Timeline Controller
// Purpose: Phase 8 unified timeline authority implementation.
// Copyright (c) 2025 RetroVue

#include "retrovue/timing/TimelineController.h"
#include "retrovue/timing/MasterClock.h"

#include <cassert>
#include <iostream>

namespace retrovue::timing {

TimelineController::TimelineController(std::shared_ptr<MasterClock> clock,
                                       TimelineConfig config)
    : clock_(std::move(clock)),
      config_(config) {
  if (!clock_) {
    throw std::invalid_argument("TimelineController requires a MasterClock");
  }
}

// ============================================================================
// Session Lifecycle
// ============================================================================

bool TimelineController::StartSession() {
  std::lock_guard<std::mutex> lock(mutex_);

  if (session_active_) {
    std::cerr << "[TimelineController] StartSession failed: session already active"
              << std::endl;
    return false;
  }

  // Establish epoch from current wall-clock time
  epoch_us_ = clock_->now_utc_us();
  ct_cursor_us_ = 0;
  segment_mapping_ = std::nullopt;
  session_active_ = true;
  was_in_catch_up_ = false;

  // Reset epoch in MasterClock for the new session
  clock_->ResetEpochForNewSession();
  clock_->TrySetEpochOnce(epoch_us_, MasterClock::EpochSetterRole::LIVE);

  std::cout << "[TimelineController] Session started, epoch=" << epoch_us_
            << "us, CT=0" << std::endl;

  return true;
}

void TimelineController::EndSession() {
  std::lock_guard<std::mutex> lock(mutex_);

  if (!session_active_) {
    return;
  }

  std::cout << "[TimelineController] Session ended, final CT=" << ct_cursor_us_
            << "us, frames_admitted=" << stats_.frames_admitted
            << ", rejected_late=" << stats_.frames_rejected_late
            << ", rejected_early=" << stats_.frames_rejected_early
            << std::endl;

  session_active_ = false;
  epoch_us_ = 0;
  ct_cursor_us_ = 0;
  segment_mapping_ = std::nullopt;
  pending_segment_ = std::nullopt;
}

bool TimelineController::IsSessionActive() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return session_active_;
}

// ============================================================================
// Segment Mapping (Type-Safe API - INV-P8-SWITCH-002)
// ============================================================================
// The segment mapping API is designed to make dangerous states unrepresentable.
// There is NO way to set CT without MT or vice versa.
// ============================================================================

PendingSegment TimelineController::BeginSegmentFromPreview() {
  std::lock_guard<std::mutex> lock(mutex_);

  // ==========================================================================
  // INV-P8-SWITCH-002: Preview-driven segment
  // ==========================================================================
  // The first preview frame will lock BOTH CT and MT together:
  //   CT_start = wall_clock_at_first_frame - epoch
  //   MT_start = first_frame_media_time
  //
  // This eliminates the dangerous state where CT is carried forward from
  // live while MT comes from preview - that mismatch caused "early" rejections.
  // ==========================================================================
  assert(!pending_segment_ && "Cannot begin new segment while one is pending");

  SegmentId id = next_segment_id_++;
  pending_segment_ = PendingSegment{id, PendingSegmentMode::AwaitPreviewFrame};
  segment_mapping_ = std::nullopt;  // Clear any existing mapping

  std::cout << "[TimelineController] Segment begun (preview-owned, id=" << id << "): "
            << "CT_start=<pending>, MT_start=<pending first frame>" << std::endl;

  return *pending_segment_;
}

PendingSegment TimelineController::BeginSegmentAbsolute(int64_t ct_start_us, int64_t mt_start_us) {
  std::lock_guard<std::mutex> lock(mutex_);

  // ==========================================================================
  // INV-P8-SWITCH-002: Absolute segment (both CT and MT provided together)
  // ==========================================================================
  // Both values MUST be provided - there is no partial specification.
  // This is used at session start or when both values are known upfront.
  //
  // Unlike BeginSegmentFromPreview, this does NOT adjust ct_cursor because
  // the caller is explicitly providing both CT and MT. The caller is
  // responsible for ensuring the values are correct for their use case.
  // ==========================================================================
  assert(!pending_segment_ && "Cannot begin new segment while one is pending");
  assert(ct_start_us >= 0 && "CT_start must be non-negative");
  assert(mt_start_us >= 0 && "MT_start must be non-negative");

  SegmentId id = next_segment_id_++;

  // Immediately resolve the mapping since both values are known
  segment_mapping_ = SegmentMapping{ct_start_us, mt_start_us};

  // NOTE: Do NOT adjust ct_cursor here. The caller provides an absolute mapping
  // and is responsible for ensuring CT_cursor is in the right position.
  // This maintains backwards compatibility with the old SetSegmentMapping behavior.

  std::cout << "[TimelineController] Segment begun (absolute, id=" << id << "): "
            << "CT_start=" << ct_start_us << "us, MT_start=" << mt_start_us << "us" << std::endl;

  return PendingSegment{id, PendingSegmentMode::AbsoluteMapping};
}

bool TimelineController::IsMappingPending() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return pending_segment_.has_value();
}

std::optional<PendingSegmentMode> TimelineController::GetPendingMode() const {
  std::lock_guard<std::mutex> lock(mutex_);
  if (pending_segment_) {
    return pending_segment_->mode;
  }
  return std::nullopt;
}

std::optional<SegmentMapping> TimelineController::GetSegmentMapping() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return segment_mapping_;
}

// ============================================================================
// INV-P8-SEGMENT-COMMIT: Explicit segment commit detection
// ============================================================================

bool TimelineController::HasSegmentCommitted() const {
  std::lock_guard<std::mutex> lock(mutex_);
  // Committed = mapping exists AND no pending segment AND segment ID is set
  return segment_mapping_.has_value() &&
         !pending_segment_.has_value() &&
         current_segment_id_ != 0;
}

SegmentId TimelineController::GetActiveSegmentId() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return current_segment_id_;
}

uint64_t TimelineController::GetSegmentCommitGeneration() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return segment_commit_generation_;
}

void TimelineController::SetEmissionObserverAttached(bool attached) {
  std::lock_guard<std::mutex> lock(mutex_);
  emission_observer_attached_ = attached;
}

void TimelineController::NotifySuccessorVideoEmitted() {
  std::lock_guard<std::mutex> lock(mutex_);
  if (!commit_pending_successor_emission_) return;
  commit_pending_successor_emission_ = false;
  segment_commit_generation_++;
  std::cout << "[TimelineController] INV-SWITCH-SUCCESSOR-EMISSION: Segment "
            << current_segment_id_ << " commit_gen=" << segment_commit_generation_
            << " (successor video emitted)" << std::endl;
}

// ============================================================================
// Frame Admission
// ============================================================================

AdmissionResult TimelineController::AdmitFrame(int64_t media_time_us,
                                                int64_t& out_ct_us) {
  std::lock_guard<std::mutex> lock(mutex_);

  if (!session_active_) {
    std::cerr << "[TimelineController] AdmitFrame failed: no active session"
              << std::endl;
    return AdmissionResult::REJECTED_NO_MAPPING;
  }

  // ==========================================================================
  // INV-P8-SWITCH-002: Lock mapping from first frame (preview-owned segments)
  // ==========================================================================
  // If a segment is pending in AwaitPreviewFrame mode, the first frame locks
  // BOTH CT and MT together. This ensures they describe the same instant.
  // ==========================================================================
  if (pending_segment_) {
    assert(pending_segment_->mode == PendingSegmentMode::AwaitPreviewFrame &&
           "AbsoluteMapping segments should not reach AdmitFrame while pending");

    // Lock both CT and MT from this first frame
    int64_t ct_start_us = clock_->now_utc_us() - epoch_us_;

    // INV-P8-SEGMENT-COMMIT: Record the segment ID before clearing pending
    SegmentId committed_segment_id = pending_segment_->id;

    std::cout << "[TimelineController] INV-P8-SWITCH-002: Mapping LOCKED from preview frame "
              << "(segment_id=" << committed_segment_id << "): "
              << "wall=" << clock_->now_utc_us() << "us, epoch=" << epoch_us_
              << "us, CT_start=" << ct_start_us << "us, MT_start=" << media_time_us << "us"
              << std::endl;

    segment_mapping_ = SegmentMapping{ct_start_us, media_time_us};

    // Critical: Set ct_cursor so that ct_expected = CT_start for this first frame.
    // ct_expected = ct_cursor + frame_period, so ct_cursor = CT_start - frame_period
    ct_cursor_us_ = ct_start_us - config_.frame_period_us;

    // Invariant check: both must be set together
    assert(segment_mapping_->ct_segment_start_us >= 0);
    assert(segment_mapping_->mt_segment_start_us >= 0);

    // INV-P8-SEGMENT-COMMIT: This segment now owns the timeline
    current_segment_id_ = committed_segment_id;

    // INV-P8-SUCCESSOR-OBSERVABILITY: commit_gen advances ONLY after observer confirms
    // at least one real successor video frame. Refuse to commit without observer.
    if (!emission_observer_attached_) {
      std::cerr << "[TimelineController] INV-P8-SUCCESSOR-OBSERVABILITY FATAL: Segment "
                << committed_segment_id << " commit attempted without observer. "
                << "Observer MUST be registered before segment may commit." << std::endl;
      std::abort();
    }
    commit_pending_successor_emission_ = true;

    // Clear pending state - segment is now active
    pending_segment_ = std::nullopt;

    std::cout << "[TimelineController] INV-P8-SEGMENT-COMMIT: Segment "
              << current_segment_id_ << " owns CT (commit_gen pending successor emission)"
              << std::endl;
  }

  if (!segment_mapping_) {
    std::cerr << "[TimelineController] AdmitFrame failed: no segment mapping"
              << std::endl;
    return AdmissionResult::REJECTED_NO_MAPPING;
  }

  // Step 1: Compute CT_frame using segment mapping
  int64_t ct_frame_us = segment_mapping_->MediaToChannel(media_time_us);

  // Step 2: Compute expected CT
  int64_t ct_expected_us = ct_cursor_us_ + config_.frame_period_us;

  // Step 3: Check admission window
  int64_t delta = ct_frame_us - ct_expected_us;

  // Check if within tolerance (snap to grid)
  if (std::abs(delta) <= config_.tolerance_us) {
    // ADMIT: snap to expected CT
    out_ct_us = ct_expected_us;
    ct_cursor_us_ = ct_expected_us;
    stats_.frames_admitted++;

    // Check for catch-up state
    int64_t lag = GetLagUnlocked();
    if (lag > stats_.max_lag_us) {
      stats_.max_lag_us = lag;
    }
    if (lag > 0 && !was_in_catch_up_) {
      was_in_catch_up_ = true;
      stats_.catch_up_events++;
      std::cout << "[TimelineController] CATCH-UP started, lag=" << (lag / 1000)
                << "ms" << std::endl;
    } else if (lag <= 0 && was_in_catch_up_) {
      was_in_catch_up_ = false;
      std::cout << "[TimelineController] CATCH-UP ended, CT synced with wall-clock"
                << std::endl;
    }

    return AdmissionResult::ADMITTED;
  }

  // Check if too late
  if (delta < -config_.late_threshold_us) {
    stats_.frames_rejected_late++;
    // Diagnostic moved to FileProducer (has producer identity and asset path)
    return AdmissionResult::REJECTED_LATE;
  }

  // Check if too early
  if (delta > config_.early_threshold_us) {
    stats_.frames_rejected_early++;
    // Diagnostic moved to FileProducer (has producer identity and asset path)
    return AdmissionResult::REJECTED_EARLY;
  }

  // Within thresholds but outside tolerance: still admit with computed CT
  // This handles the case where frames are slightly off but recoverable
  out_ct_us = ct_frame_us;
  ct_cursor_us_ = ct_frame_us;
  stats_.frames_admitted++;

  return AdmissionResult::ADMITTED;
}

// ============================================================================
// Timeline State
// ============================================================================

int64_t TimelineController::GetCTCursor() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return ct_cursor_us_;
}

int64_t TimelineController::GetEpoch() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return epoch_us_;
}

int64_t TimelineController::GetExpectedNextCT() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return ct_cursor_us_ + config_.frame_period_us;
}

int64_t TimelineController::GetSegmentMTStart() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return segment_mapping_ ? segment_mapping_->mt_segment_start_us : -1;
}

int64_t TimelineController::GetWallClockDeadline(int64_t ct_us) const {
  std::lock_guard<std::mutex> lock(mutex_);
  return epoch_us_ + ct_us;
}

// ============================================================================
// Catch-Up Detection
// ============================================================================

int64_t TimelineController::GetLagUnlocked() const {
  // Lag = W_now - (epoch + CT_cursor)
  // Positive = CT behind wall-clock
  int64_t w_now = clock_->now_utc_us();
  return w_now - (epoch_us_ + ct_cursor_us_);
}

bool TimelineController::IsInCatchUp() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return GetLagUnlocked() > 0;
}

int64_t TimelineController::GetLag() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return GetLagUnlocked();
}

bool TimelineController::ShouldRestartSession() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return GetLagUnlocked() > config_.catch_up_limit_us;
}

// ============================================================================
// Statistics
// ============================================================================

TimelineController::Stats TimelineController::GetStats() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return stats_;
}

void TimelineController::ResetStats() {
  std::lock_guard<std::mutex> lock(mutex_);
  stats_ = Stats{};
  was_in_catch_up_ = false;
}

}  // namespace retrovue::timing
