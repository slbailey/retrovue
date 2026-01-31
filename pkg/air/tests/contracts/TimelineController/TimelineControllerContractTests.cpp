// Phase 8 Contract Tests: TimelineController
// Tests per ScheduleManagerPhase8Contract.md

#include <gtest/gtest.h>
#include <memory>

#include "retrovue/timing/TimelineController.h"
#include "retrovue/timing/MasterClock.h"

namespace retrovue::tests {

// Test clock that allows manual time control
class TestClock : public timing::MasterClock {
 public:
  TestClock() : now_us_(0), epoch_us_(0), epoch_locked_(false) {}

  int64_t now_utc_us() const override { return now_us_; }
  double now_monotonic_s() const override { return now_us_ / 1'000'000.0; }
  int64_t scheduled_to_utc_us(int64_t pts_us) const override {
    return epoch_us_ + pts_us;
  }
  double drift_ppm() const override { return 0.0; }
  bool is_fake() const override { return true; }

  void set_epoch_utc_us(int64_t epoch_utc_us) override {
    epoch_us_ = epoch_utc_us;
    epoch_locked_ = true;
  }

  bool TrySetEpochOnce(int64_t epoch_utc_us,
                       EpochSetterRole role = EpochSetterRole::LIVE) override {
    if (role == EpochSetterRole::PREVIEW) return false;
    if (epoch_locked_) return false;
    epoch_us_ = epoch_utc_us;
    epoch_locked_ = true;
    return true;
  }

  void ResetEpochForNewSession() override {
    epoch_locked_ = false;
    epoch_us_ = 0;
  }

  bool IsEpochLocked() const override { return epoch_locked_; }
  int64_t get_epoch_utc_us() const override { return epoch_us_; }

  // Test helpers
  void SetNow(int64_t now_us) { now_us_ = now_us; }
  void AdvanceUs(int64_t delta_us) { now_us_ += delta_us; }

 private:
  int64_t now_us_;
  int64_t epoch_us_;
  bool epoch_locked_;
};

class TimelineControllerTest : public ::testing::Test {
 protected:
  void SetUp() override {
    clock_ = std::make_shared<TestClock>();
    clock_->SetNow(1'000'000'000'000);  // Start at 1 trillion µs (~11.5 days from epoch)

    timing::TimelineConfig config;
    config.frame_period_us = 33'333;  // 30fps
    config.tolerance_us = 33'333;
    config.late_threshold_us = 500'000;
    config.early_threshold_us = 500'000;
    config.catch_up_limit_us = 5'000'000;

    controller_ = std::make_unique<timing::TimelineController>(clock_, config);
  }

  std::shared_ptr<TestClock> clock_;
  std::unique_ptr<timing::TimelineController> controller_;
};

// ============================================================================
// P8-T001: Producer Emits MT Only
// ============================================================================
// This is an architectural test - verified by the fact that AdmitFrame
// takes media_time_us as input (MT) and outputs channel_time via out_ct_us.
// The producer never sees or computes CT.

TEST_F(TimelineControllerTest, P8_T001_ProducerEmitsMTOnly) {
  // The API signature enforces this: AdmitFrame(media_time_us, out_ct_us)
  // Producer provides MT, TimelineController provides CT.

  ASSERT_TRUE(controller_->StartSession());
  controller_->SetSegmentMapping(0, 1000000);  // CT=0 corresponds to MT=1000000

  int64_t media_time = 1000000;  // Producer's MT
  int64_t channel_time = 0;      // Will be assigned by controller

  auto result = controller_->AdmitFrame(media_time, channel_time);

  EXPECT_EQ(result, timing::AdmissionResult::ADMITTED);
  // Channel time was assigned by controller, not by producer
  EXPECT_EQ(channel_time, 33'333);  // First frame at CT=frame_period (CT_cursor starts at 0)
}

// ============================================================================
// P8-T002: Timeline Controller Assigns CT
// ============================================================================

TEST_F(TimelineControllerTest, P8_T002_TimelineControllerAssignsCT) {
  ASSERT_TRUE(controller_->StartSession());
  controller_->SetSegmentMapping(0, 0);  // 1:1 mapping for simplicity

  int64_t ct_out = -1;
  auto result = controller_->AdmitFrame(33'333, ct_out);

  EXPECT_EQ(result, timing::AdmissionResult::ADMITTED);
  EXPECT_EQ(ct_out, 33'333);  // CT assigned
  EXPECT_EQ(controller_->GetCTCursor(), 33'333);  // Cursor advanced
}

// ============================================================================
// P8-T003: CT Monotonicity Across Transition
// ============================================================================

TEST_F(TimelineControllerTest, P8_T003_CTMonotonicityAcrossTransition) {
  ASSERT_TRUE(controller_->StartSession());

  // Segment A: MT starts at 0
  controller_->SetSegmentMapping(0, 0);

  int64_t ct_out = 0;

  // Admit 3 frames from segment A
  EXPECT_EQ(controller_->AdmitFrame(33'333, ct_out), timing::AdmissionResult::ADMITTED);
  int64_t ct_a1 = ct_out;
  EXPECT_EQ(controller_->AdmitFrame(66'666, ct_out), timing::AdmissionResult::ADMITTED);
  int64_t ct_a2 = ct_out;
  EXPECT_EQ(controller_->AdmitFrame(99'999, ct_out), timing::AdmissionResult::ADMITTED);
  int64_t ct_a3 = ct_out;

  // Verify monotonicity within segment A
  EXPECT_LT(ct_a1, ct_a2);
  EXPECT_LT(ct_a2, ct_a3);

  // Transition to segment B
  // Segment B starts at CT = current cursor + frame_period
  // Segment B's MT starts at 5000000 (different asset position)
  int64_t ct_transition = controller_->GetCTCursor() + 33'333;
  controller_->SetSegmentMapping(ct_transition, 5000000);

  // First frame from segment B
  EXPECT_EQ(controller_->AdmitFrame(5000000, ct_out), timing::AdmissionResult::ADMITTED);
  int64_t ct_b1 = ct_out;

  // Verify monotonicity across transition
  EXPECT_GT(ct_b1, ct_a3);
  EXPECT_EQ(ct_b1, ct_a3 + 33'333);  // Exactly one frame period later
}

// ============================================================================
// P8-T004: Epoch Unchanged by Transition
// ============================================================================

TEST_F(TimelineControllerTest, P8_T004_EpochUnchangedByTransition) {
  ASSERT_TRUE(controller_->StartSession());
  int64_t epoch_at_start = controller_->GetEpoch();

  controller_->SetSegmentMapping(0, 0);

  int64_t ct_out = 0;
  controller_->AdmitFrame(33'333, ct_out);
  controller_->AdmitFrame(66'666, ct_out);

  // Transition
  controller_->SetSegmentMapping(controller_->GetCTCursor() + 33'333, 9999999);

  controller_->AdmitFrame(9999999, ct_out);
  controller_->AdmitFrame(9999999 + 33'333, ct_out);

  // Epoch unchanged
  EXPECT_EQ(controller_->GetEpoch(), epoch_at_start);
}

// ============================================================================
// P8-T005: Segment Mapping Independence
// ============================================================================

TEST_F(TimelineControllerTest, P8_T005_SegmentMappingIndependence) {
  ASSERT_TRUE(controller_->StartSession());

  // Segment A: MT=1000000000 (1000 seconds into asset)
  controller_->SetSegmentMapping(0, 1'000'000'000);

  int64_t ct_out = 0;
  controller_->AdmitFrame(1'000'000'000, ct_out);
  controller_->AdmitFrame(1'000'000'000 + 33'333, ct_out);
  int64_t ct_last_a = ct_out;

  // Segment B: MT=500000000 (500 seconds into DIFFERENT asset)
  // The key point: B's CT does NOT depend on A's MT
  // It depends only on CT_cursor (which is ct_last_a)
  int64_t ct_b_start = ct_last_a + 33'333;
  controller_->SetSegmentMapping(ct_b_start, 500'000'000);

  controller_->AdmitFrame(500'000'000, ct_out);
  int64_t ct_first_b = ct_out;

  // B's first frame CT is exactly one frame period after A's last frame
  EXPECT_EQ(ct_first_b, ct_last_a + 33'333);

  // B's CT does not reflect B's MT offset (500s) or A's MT offset (1000s)
  // It continues smoothly from the channel timeline
}

// ============================================================================
// P8-T006: Late Frame Rejection
// ============================================================================

TEST_F(TimelineControllerTest, P8_T006_LateFrameRejection) {
  ASSERT_TRUE(controller_->StartSession());
  controller_->SetSegmentMapping(0, 0);

  int64_t ct_out = 0;

  // Admit a few frames to advance the cursor
  controller_->AdmitFrame(33'333, ct_out);
  controller_->AdmitFrame(66'666, ct_out);
  controller_->AdmitFrame(99'999, ct_out);
  // CT_cursor is now at 99'999

  // Expected next CT is 99'999 + 33'333 = 133'332
  // late_threshold is 500'000
  // A frame with MT that maps to CT < 133'332 - 500'000 = -366'668 is too late

  // Try to admit a frame with MT=0 (way in the past)
  // This maps to CT=0, which is about 133'000 behind expected
  // That's within threshold, so it should still be admitted

  // To actually trigger rejection, we need MT that maps to CT more than 500ms behind
  // Let's advance the cursor more
  for (int i = 0; i < 20; i++) {
    controller_->AdmitFrame((4 + i) * 33'333, ct_out);
  }
  // CT_cursor is now at about 23 * 33'333 = 766'659

  // Expected next is 766'659 + 33'333 = 799'992
  // Late threshold: 799'992 - 500'000 = 299'992
  // MT=0 maps to CT=0, which is < 299'992, so should be rejected

  auto result = controller_->AdmitFrame(0, ct_out);
  EXPECT_EQ(result, timing::AdmissionResult::REJECTED_LATE);
}

// ============================================================================
// P8-T007: Early Frame Rejection
// ============================================================================

TEST_F(TimelineControllerTest, P8_T007_EarlyFrameRejection) {
  ASSERT_TRUE(controller_->StartSession());
  controller_->SetSegmentMapping(0, 0);

  int64_t ct_out = 0;

  // Admit first frame
  controller_->AdmitFrame(33'333, ct_out);
  // CT_cursor is now at 33'333

  // Expected next CT is 66'666
  // early_threshold is 500'000
  // A frame with MT that maps to CT > 66'666 + 500'000 = 566'666 is too early

  // Try to admit a frame with MT=1'000'000 (maps to CT=1'000'000)
  auto result = controller_->AdmitFrame(1'000'000, ct_out);
  EXPECT_EQ(result, timing::AdmissionResult::REJECTED_EARLY);
}

// ============================================================================
// P8-T008: Backpressure Does Not Slow Timeline
// ============================================================================

TEST_F(TimelineControllerTest, P8_T008_BackpressureDoesNotSlowTimeline) {
  ASSERT_TRUE(controller_->StartSession());
  controller_->SetSegmentMapping(0, 0);

  // The TimelineController is frame-driven, so CT only advances when frames
  // are admitted. This test verifies that the controller correctly tracks
  // lag when wall-clock advances without frame admission.

  int64_t ct_out = 0;

  // Admit first frame at wall-clock T0
  controller_->AdmitFrame(33'333, ct_out);
  EXPECT_EQ(controller_->GetCTCursor(), 33'333);

  // Advance wall-clock by 1 second without admitting frames
  clock_->AdvanceUs(1'000'000);

  // CT_cursor should NOT have advanced (frame-driven)
  EXPECT_EQ(controller_->GetCTCursor(), 33'333);

  // But lag should reflect the divergence
  int64_t lag = controller_->GetLag();
  EXPECT_GT(lag, 900'000);  // Should be about 1 second of lag
}

// ============================================================================
// P8-T009: Deterministic CT Assignment
// ============================================================================

TEST_F(TimelineControllerTest, P8_T009_DeterministicCTAssignment) {
  // Run the same sequence twice, verify identical CT assignments

  std::vector<int64_t> cts_run1;
  std::vector<int64_t> cts_run2;

  // First run
  {
    auto clock1 = std::make_shared<TestClock>();
    clock1->SetNow(1'000'000'000'000);
    timing::TimelineConfig config;
    config.frame_period_us = 33'333;
    timing::TimelineController ctrl1(clock1, config);

    ctrl1.StartSession();
    ctrl1.SetSegmentMapping(0, 100'000);

    int64_t ct = 0;
    for (int i = 0; i < 10; i++) {
      ctrl1.AdmitFrame(100'000 + i * 33'333, ct);
      cts_run1.push_back(ct);
    }
  }

  // Second run with same inputs
  {
    auto clock2 = std::make_shared<TestClock>();
    clock2->SetNow(1'000'000'000'000);  // Same start time
    timing::TimelineConfig config;
    config.frame_period_us = 33'333;
    timing::TimelineController ctrl2(clock2, config);

    ctrl2.StartSession();
    ctrl2.SetSegmentMapping(0, 100'000);  // Same mapping

    int64_t ct = 0;
    for (int i = 0; i < 10; i++) {
      ctrl2.AdmitFrame(100'000 + i * 33'333, ct);  // Same MTs
      cts_run2.push_back(ct);
    }
  }

  // Verify identical sequences
  ASSERT_EQ(cts_run1.size(), cts_run2.size());
  for (size_t i = 0; i < cts_run1.size(); i++) {
    EXPECT_EQ(cts_run1[i], cts_run2[i]) << "Mismatch at frame " << i;
  }
}

// ============================================================================
// P8-T010: Write Barrier Prevents Post-Switch Writes
// ============================================================================
// Note: Write barrier is enforced at the producer level, not in TimelineController.
// This test verifies that the controller correctly handles segment transitions
// where a new mapping supersedes the old one.

TEST_F(TimelineControllerTest, P8_T010_SegmentMappingSupersedes) {
  ASSERT_TRUE(controller_->StartSession());

  // Segment A
  controller_->SetSegmentMapping(0, 0);
  int64_t ct_out = 0;
  controller_->AdmitFrame(33'333, ct_out);

  // Transition: new segment mapping
  controller_->SetSegmentMapping(66'666, 5'000'000);

  // Old mapping is gone; frames must use new mapping
  // A frame with MT=0 would map incorrectly with the new mapping
  // MT=5'000'000 should map to CT=66'666
  auto result = controller_->AdmitFrame(5'000'000, ct_out);
  EXPECT_EQ(result, timing::AdmissionResult::ADMITTED);
  EXPECT_EQ(ct_out, 66'666);
}

// ============================================================================
// P8-T011: Underrun Pauses CT (Frame-Driven)
// ============================================================================

TEST_F(TimelineControllerTest, P8_T011_UnderrunPausesCT) {
  ASSERT_TRUE(controller_->StartSession());
  controller_->SetSegmentMapping(0, 0);

  int64_t ct_out = 0;

  // Admit one frame
  controller_->AdmitFrame(33'333, ct_out);
  int64_t ct_before_underrun = controller_->GetCTCursor();

  // Simulate underrun: wall-clock advances, no frames admitted
  clock_->AdvanceUs(500'000);  // 500ms passes

  // CT_cursor should NOT have advanced
  EXPECT_EQ(controller_->GetCTCursor(), ct_before_underrun);

  // Now admit next frame
  controller_->AdmitFrame(66'666, ct_out);

  // CT should advance from where it was, not jump to current wall-clock
  EXPECT_EQ(controller_->GetCTCursor(), ct_before_underrun + 33'333);
}

// ============================================================================
// P8-T012: Threshold Derivation from Buffer Config
// ============================================================================

TEST_F(TimelineControllerTest, P8_T012_ThresholdDerivation) {
  auto config = timing::TimelineConfig::FromFps(30.0, 5, 30);

  EXPECT_EQ(config.frame_period_us, 33'333);
  EXPECT_EQ(config.tolerance_us, 33'333);

  // late_threshold = min(500ms, 5 frames * 33.3ms) = min(500000, 166665) = 166665
  EXPECT_EQ(config.late_threshold_us, 166'665);

  // early_threshold = 30 frames * 33.3ms = 999990
  EXPECT_EQ(config.early_threshold_us, 999'990);
}

// ============================================================================
// Additional Tests
// ============================================================================

TEST_F(TimelineControllerTest, SessionMustBeActiveForAdmission) {
  // Without starting session, admission should fail
  int64_t ct_out = 0;
  auto result = controller_->AdmitFrame(33'333, ct_out);
  EXPECT_EQ(result, timing::AdmissionResult::REJECTED_NO_MAPPING);
}

TEST_F(TimelineControllerTest, MappingRequiredForAdmission) {
  ASSERT_TRUE(controller_->StartSession());
  // Session started but no mapping set

  int64_t ct_out = 0;
  auto result = controller_->AdmitFrame(33'333, ct_out);
  EXPECT_EQ(result, timing::AdmissionResult::REJECTED_NO_MAPPING);
}

TEST_F(TimelineControllerTest, CatchUpDetection) {
  ASSERT_TRUE(controller_->StartSession());
  controller_->SetSegmentMapping(0, 0);

  int64_t ct_out = 0;

  // Admit frame, then advance wall-clock significantly
  controller_->AdmitFrame(33'333, ct_out);
  clock_->AdvanceUs(2'000'000);  // 2 seconds

  EXPECT_TRUE(controller_->IsInCatchUp());
  EXPECT_GT(controller_->GetLag(), 1'900'000);
}

TEST_F(TimelineControllerTest, ShouldRestartOnExcessiveLag) {
  ASSERT_TRUE(controller_->StartSession());
  controller_->SetSegmentMapping(0, 0);

  int64_t ct_out = 0;
  controller_->AdmitFrame(33'333, ct_out);

  // Advance wall-clock beyond catch_up_limit
  clock_->AdvanceUs(6'000'000);  // 6 seconds > 5 second limit

  EXPECT_TRUE(controller_->ShouldRestartSession());
}

TEST_F(TimelineControllerTest, StatsTracking) {
  ASSERT_TRUE(controller_->StartSession());
  controller_->SetSegmentMapping(0, 0);

  int64_t ct_out = 0;

  // Admit some frames
  controller_->AdmitFrame(33'333, ct_out);
  controller_->AdmitFrame(66'666, ct_out);
  controller_->AdmitFrame(99'999, ct_out);

  auto stats = controller_->GetStats();
  EXPECT_EQ(stats.frames_admitted, 3);
  EXPECT_EQ(stats.frames_rejected_late, 0);
  EXPECT_EQ(stats.frames_rejected_early, 0);
}

}  // namespace retrovue::tests
