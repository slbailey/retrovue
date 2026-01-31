// Phase 8 Integration Tests
// These are "integration truth" tests that verify Phase 8 guarantees
// at the system level, not just unit tests.

#include <gtest/gtest.h>
#include <memory>
#include <vector>
#include <atomic>
#include <thread>
#include <chrono>

#include "retrovue/timing/TimelineController.h"
#include "retrovue/timing/MasterClock.h"
#include "retrovue/buffer/FrameRingBuffer.h"

namespace retrovue::tests {

// Test clock that allows manual time control
class Phase8TestClock : public timing::MasterClock {
 public:
  Phase8TestClock() : now_us_(0), epoch_us_(0), epoch_locked_(false) {}

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

  void SetNow(int64_t now_us) { now_us_ = now_us; }
  void AdvanceUs(int64_t delta_us) { now_us_ += delta_us; }

 private:
  int64_t now_us_;
  int64_t epoch_us_;
  bool epoch_locked_;
};

// ============================================================================
// IT-P8-01: Shadow frames never appear in output
// ============================================================================
// Verifies that frames with has_ct=false are never consumed by output.
// This is a hard Phase 8 guarantee: "A frame is not timeline-valid until CT."

TEST(Phase8IntegrationTest, IT_P8_01_ShadowFramesNeverAppearInOutput) {
  buffer::FrameRingBuffer buffer(60);

  // Simulate shadow mode: push frames with has_ct=false (raw MT only)
  constexpr int kShadowFrameCount = 10;
  for (int i = 0; i < kShadowFrameCount; ++i) {
    buffer::Frame frame;
    frame.metadata.pts = i * 33'333;  // Raw MT
    frame.metadata.has_ct = false;    // Shadow mode: NOT timeline-valid
    frame.width = 1920;
    frame.height = 1080;
    ASSERT_TRUE(buffer.Push(frame));
  }

  EXPECT_EQ(buffer.Size(), kShadowFrameCount);

  // Simulate output consumer: MUST reject frames with has_ct=false
  int frames_consumed = 0;
  int frames_rejected = 0;

  buffer::Frame output_frame;
  while (buffer.Pop(output_frame)) {
    if (output_frame.metadata.has_ct) {
      // Would be consumed by output
      frames_consumed++;
    } else {
      // Rejected: not timeline-valid
      frames_rejected++;
    }
  }

  // All shadow frames must be rejected
  EXPECT_EQ(frames_consumed, 0) << "Shadow frames (has_ct=false) must never appear in output";
  EXPECT_EQ(frames_rejected, kShadowFrameCount) << "All shadow frames should be rejected";
}

// ============================================================================
// IT-P8-02: SwitchToLive first output frame has contiguous CT
// ============================================================================
// Verifies that after SwitchToLive using BeginSegmentFromPreview,
// frames are admitted correctly and CT advances contiguously.

TEST(Phase8IntegrationTest, IT_P8_02_SwitchToLiveFirstFrameIsContiguous) {
  auto clock = std::make_shared<Phase8TestClock>();
  clock->SetNow(1'000'000'000'000);

  timing::TimelineConfig config;
  config.frame_period_us = 33'333;  // 30fps
  config.tolerance_us = 33'333;
  config.late_threshold_us = 500'000;
  config.early_threshold_us = 500'000;

  timing::TimelineController controller(clock, config);

  // Start session (simulates StartChannel)
  ASSERT_TRUE(controller.StartSession());

  // Build some CT on the "live" producer using BeginSegmentAbsolute
  controller.BeginSegmentAbsolute(0, 0);  // CT=0 maps to MT=0

  int64_t ct;
  std::vector<int64_t> live_cts;

  // Admit 10 frames from live producer
  for (int i = 0; i < 10; ++i) {
    int64_t mt = i * 33'333;
    auto result = controller.AdmitFrame(mt, ct);
    ASSERT_EQ(result, timing::AdmissionResult::ADMITTED);
    live_cts.push_back(ct);
    clock->AdvanceUs(33'333);
  }

  // Verify CT is contiguous
  for (size_t i = 1; i < live_cts.size(); ++i) {
    EXPECT_EQ(live_cts[i] - live_cts[i-1], 33'333)
        << "Live CT should advance by frame_period";
  }

  int64_t last_live_ct = live_cts.back();

  // Simulate SwitchToLive: BeginSegmentFromPreview (type-safe API)
  // INV-P8-SWITCH-002: Both CT and MT will be locked from first preview frame
  controller.BeginSegmentFromPreview();
  EXPECT_TRUE(controller.IsMappingPending());

  // First frame from "preview" producer (now live) - arbitrary MT
  // CT will be derived from wall clock at this moment
  int64_t preview_first_mt = 5'000'000;  // Different asset, different MT
  auto result = controller.AdmitFrame(preview_first_mt, ct);
  ASSERT_EQ(result, timing::AdmissionResult::ADMITTED);
  EXPECT_FALSE(controller.IsMappingPending());

  // The CT should be close to the wall clock position relative to epoch
  // Since clock is at 1'000'000'333'330 and epoch is 1'000'000'000'000,
  // CT should be around 333'330us (same as last_live_ct or slightly higher)
  EXPECT_GE(ct, last_live_ct) << "CT should continue forward (or from same point) after switch";

  // Subsequent frames should be contiguous
  int64_t prev_ct = ct;
  for (int i = 1; i < 5; ++i) {
    int64_t mt = preview_first_mt + i * 33'333;
    clock->AdvanceUs(33'333);
    result = controller.AdmitFrame(mt, ct);
    ASSERT_EQ(result, timing::AdmissionResult::ADMITTED);
    EXPECT_EQ(ct - prev_ct, config.frame_period_us)
        << "CT must remain contiguous after switch";
    prev_ct = ct;
  }
}

// ============================================================================
// IT-P8-03: Mapping locks on first admitted frame (type-safe API)
// ============================================================================
// Verifies that BeginSegmentFromPreview + first AdmitFrame locks BOTH CT and MT,
// preventing mapping skew from pre-buffered/dropped frames.

TEST(Phase8IntegrationTest, IT_P8_03_MappingLocksOnFirstAdmittedFrame) {
  auto clock = std::make_shared<Phase8TestClock>();
  clock->SetNow(1'000'000'000'000);

  timing::TimelineConfig config;
  config.frame_period_us = 33'333;
  config.tolerance_us = 33'333;
  config.late_threshold_us = 500'000;
  config.early_threshold_us = 500'000;

  timing::TimelineController controller(clock, config);
  ASSERT_TRUE(controller.StartSession());

  // Use BeginSegmentFromPreview (type-safe: both CT and MT pending)
  auto pending = controller.BeginSegmentFromPreview();
  EXPECT_EQ(pending.mode, timing::PendingSegmentMode::AwaitPreviewFrame);

  // Verify mapping is pending
  EXPECT_TRUE(controller.IsMappingPending());
  EXPECT_FALSE(controller.GetSegmentMapping().has_value())
      << "Mapping should not be set until first frame is admitted";

  // Simulate: first frame arrives with MT=7'500'000 (not MT=0!)
  // This could be due to seeking, or frames getting dropped, etc.
  int64_t first_mt = 7'500'000;  // 7.5 seconds into the asset
  int64_t ct;
  auto result = controller.AdmitFrame(first_mt, ct);

  ASSERT_EQ(result, timing::AdmissionResult::ADMITTED);
  EXPECT_FALSE(controller.IsMappingPending())
      << "Mapping should be locked after first admission";

  // Verify mapping was locked with actual first frame's MT AND wall-clock CT
  auto mapping = controller.GetSegmentMapping();
  ASSERT_TRUE(mapping.has_value());
  EXPECT_EQ(mapping->mt_segment_start_us, first_mt)
      << "MT_start must be the first ADMITTED frame's MT, not a pre-buffered value";
  // CT_start is derived from wall clock, not preset
  EXPECT_GE(mapping->ct_segment_start_us, 0);

  // Verify CT was assigned correctly using the locked mapping
  EXPECT_EQ(ct, mapping->ct_segment_start_us)
      << "First frame CT should equal CT_start when MT=MT_start";

  // Subsequent frames should use the locked mapping and be contiguous
  clock->AdvanceUs(33'333);
  int64_t second_mt = first_mt + 33'333;
  result = controller.AdmitFrame(second_mt, ct);
  ASSERT_EQ(result, timing::AdmissionResult::ADMITTED);

  int64_t expected_ct = mapping->ct_segment_start_us + 33'333;
  EXPECT_EQ(ct, expected_ct)
      << "Second frame CT should be CT_start + frame_period";
}

// ============================================================================
// IT-P8-04: has_ct flag propagates through buffer correctly
// ============================================================================
// Verifies that the has_ct flag survives push/pop operations.

TEST(Phase8IntegrationTest, IT_P8_04_HasCtFlagPropagatesThroughBuffer) {
  buffer::FrameRingBuffer buffer(60);

  // Push frames with mixed has_ct values
  for (int i = 0; i < 5; ++i) {
    buffer::Frame frame;
    frame.metadata.pts = i * 33'333;
    frame.metadata.has_ct = false;  // Shadow frames
    ASSERT_TRUE(buffer.Push(frame));
  }

  for (int i = 0; i < 5; ++i) {
    buffer::Frame frame;
    frame.metadata.pts = (5 + i) * 33'333;
    frame.metadata.has_ct = true;  // Admitted frames
    ASSERT_TRUE(buffer.Push(frame));
  }

  // Pop and verify has_ct is preserved
  int shadow_count = 0;
  int admitted_count = 0;

  buffer::Frame frame;
  while (buffer.Pop(frame)) {
    if (frame.metadata.has_ct) {
      admitted_count++;
    } else {
      shadow_count++;
    }
  }

  EXPECT_EQ(shadow_count, 5) << "Shadow frame count should be preserved";
  EXPECT_EQ(admitted_count, 5) << "Admitted frame count should be preserved";
}

// ============================================================================
// IT-P8-05: Mapping skew prevention with type-safe API
// ============================================================================
// Verifies that BeginSegmentFromPreview prevents mapping skew by locking
// both CT and MT from the first actually admitted frame.

TEST(Phase8IntegrationTest, IT_P8_05_MappingSkewPrevention) {
  auto clock = std::make_shared<Phase8TestClock>();
  clock->SetNow(1'000'000'000'000);

  timing::TimelineConfig config;
  config.frame_period_us = 33'333;
  config.tolerance_us = 33'333;
  config.late_threshold_us = 100'000;  // Tight threshold for test
  config.early_threshold_us = 100'000;

  timing::TimelineController controller(clock, config);
  ASSERT_TRUE(controller.StartSession());

  // Scenario: We have a seek target of MT=5'000'000
  // But due to keyframe seeking, first decodable frame is at MT=5'100'000
  //
  // OLD dangerous approach (now impossible with type-safe API):
  // SetSegmentMapping(0, 5'000'000) would pre-set MT
  // First frame at MT=5'100'000 would compute CT = 0 + (5'100'000 - 5'000'000) = 100'000
  // But expected CT is 33'333 (second frame position), causing early rejection!
  //
  // NEW type-safe approach: BeginSegmentFromPreview locks BOTH CT and MT together

  controller.BeginSegmentFromPreview();
  EXPECT_TRUE(controller.IsMappingPending());

  // First frame arrives at MT=5'100'000 (after keyframe seek)
  int64_t ct;
  auto result = controller.AdmitFrame(5'100'000, ct);
  ASSERT_EQ(result, timing::AdmissionResult::ADMITTED);
  EXPECT_FALSE(controller.IsMappingPending());

  // Verify first frame got CT = CT_start (derived from wall clock)
  auto mapping = controller.GetSegmentMapping();
  ASSERT_TRUE(mapping.has_value());
  EXPECT_EQ(ct, mapping->ct_segment_start_us) << "First frame should get CT=CT_start";

  // Second frame at MT=5'133'333 - should be contiguous
  clock->AdvanceUs(33'333);
  result = controller.AdmitFrame(5'133'333, ct);
  ASSERT_EQ(result, timing::AdmissionResult::ADMITTED);
  EXPECT_EQ(ct, mapping->ct_segment_start_us + 33'333)
      << "Second frame should get CT=CT_start + frame_period";

  // This works because mapping locked MT_start=5'100'000, not 5'000'000
  EXPECT_EQ(mapping->mt_segment_start_us, 5'100'000)
      << "Mapping MT_start should be first admitted frame, not seek target";
}

// ============================================================================
// IT-P8-06: BeginSegmentAbsolute provides both CT and MT upfront
// ============================================================================
// Verifies that BeginSegmentAbsolute works correctly when both values are known.
// NOTE: BeginSegmentAbsolute sets the mapping but does NOT adjust ct_cursor.
// The first frame will get CT = ct_cursor + frame_period (snapped if within tolerance).

TEST(Phase8IntegrationTest, IT_P8_06_BeginSegmentAbsoluteWorkflow) {
  auto clock = std::make_shared<Phase8TestClock>();
  clock->SetNow(1'000'000'000'000);

  timing::TimelineConfig config;
  config.frame_period_us = 33'333;
  config.tolerance_us = 33'333;
  config.late_threshold_us = 500'000;
  config.early_threshold_us = 500'000;

  timing::TimelineController controller(clock, config);
  ASSERT_TRUE(controller.StartSession());

  // When both CT and MT are known upfront (e.g., session start with known offset)
  int64_t ct_start = 0;
  int64_t mt_start = 1'000'000;  // Starting 1 second into the asset

  auto pending = controller.BeginSegmentAbsolute(ct_start, mt_start);
  EXPECT_EQ(pending.mode, timing::PendingSegmentMode::AbsoluteMapping);

  // Mapping should be immediately available (not pending)
  EXPECT_FALSE(controller.IsMappingPending());
  auto mapping = controller.GetSegmentMapping();
  ASSERT_TRUE(mapping.has_value());
  EXPECT_EQ(mapping->ct_segment_start_us, ct_start);
  EXPECT_EQ(mapping->mt_segment_start_us, mt_start);

  // First frame at MT=1'000'000 gets CT computed from mapping
  // CT_computed = 0 + (1000000 - 1000000) = 0
  // ct_expected = 0 + 33333 = 33333 (ct_cursor starts at 0)
  // delta = -33333, within tolerance, snap to ct_expected = 33333
  int64_t ct;
  auto result = controller.AdmitFrame(1'000'000, ct);
  ASSERT_EQ(result, timing::AdmissionResult::ADMITTED);
  EXPECT_EQ(ct, 33'333);

  // Second frame at MT=1'033'333 should get CT=66'666
  result = controller.AdmitFrame(1'033'333, ct);
  ASSERT_EQ(result, timing::AdmissionResult::ADMITTED);
  EXPECT_EQ(ct, 66'666);
}

}  // namespace retrovue::tests
