// Repository: Retrovue-playout
// Component: Timeline Controller
// Purpose: Phase 8 unified timeline authority implementation.
// Copyright (c) 2025 RetroVue

#include "retrovue/timing/TimelineController.h"
#include "retrovue/timing/MasterClock.h"

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
  mapping_pending_ = false;
  pending_ct_start_us_ = 0;
}

bool TimelineController::IsSessionActive() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return session_active_;
}

// ============================================================================
// Segment Mapping
// ============================================================================

void TimelineController::SetSegmentMapping(int64_t ct_start_us, int64_t mt_start_us) {
  std::lock_guard<std::mutex> lock(mutex_);

  segment_mapping_ = SegmentMapping{ct_start_us, mt_start_us};
  mapping_pending_ = false;  // Clear pending state

  std::cout << "[TimelineController] Segment mapping set: CT_start=" << ct_start_us
            << "us, MT_start=" << mt_start_us << "us" << std::endl;
}

void TimelineController::BeginSegment(int64_t ct_start_us) {
  std::lock_guard<std::mutex> lock(mutex_);

  // Phase 8 §6.1: Begin segment with known CT, pending MT.
  // MT_start will be locked on first admitted frame.
  mapping_pending_ = true;
  pending_ct_start_us_ = ct_start_us;
  segment_mapping_ = std::nullopt;  // Clear any existing mapping

  std::cout << "[TimelineController] Segment begun (pending): CT_start=" << ct_start_us
            << "us, MT_start=<pending first frame>" << std::endl;
}

bool TimelineController::IsMappingPending() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return mapping_pending_;
}

std::optional<SegmentMapping> TimelineController::GetSegmentMapping() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return segment_mapping_;
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

  // Phase 8 §6.1: If mapping is pending, lock MT_start on first admission.
  // This ensures the mapping uses the actual first admitted frame's MT,
  // not a peeked/precomputed value that might be dropped.
  if (mapping_pending_) {
    segment_mapping_ = SegmentMapping{pending_ct_start_us_, media_time_us};
    mapping_pending_ = false;

    // Critical: Set ct_cursor so that ct_expected = CT_start for this first frame.
    // ct_expected = ct_cursor + frame_period, so ct_cursor = CT_start - frame_period
    ct_cursor_us_ = pending_ct_start_us_ - config_.frame_period_us;

    std::cout << "[TimelineController] Segment mapping LOCKED on first frame: CT_start="
              << pending_ct_start_us_ << "us, MT_start=" << media_time_us << "us" << std::endl;
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
    std::cerr << "[TimelineController] Frame REJECTED (late): MT=" << media_time_us
              << ", CT_computed=" << ct_frame_us
              << ", CT_expected=" << ct_expected_us
              << ", delta=" << delta << "us" << std::endl;
    return AdmissionResult::REJECTED_LATE;
  }

  // Check if too early
  if (delta > config_.early_threshold_us) {
    stats_.frames_rejected_early++;
    std::cerr << "[TimelineController] Frame REJECTED (early): MT=" << media_time_us
              << ", CT_computed=" << ct_frame_us
              << ", CT_expected=" << ct_expected_us
              << ", delta=" << delta << "us" << std::endl;
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
