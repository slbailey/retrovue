// Repository: Retrovue-playout
// Component: BlockPlan Executor Diagnostic Harness
// Purpose: Human-readable demonstration of correct executor behavior
// Contract Reference: docs/architecture/proposals/BlockLevelPlayoutAutonomy.md
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <iomanip>
#include <iostream>
#include <sstream>

#include "retrovue/blockplan/BlockPlanExecutor.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/BlockPlanValidator.hpp"
#include "ExecutorTestInfrastructure.hpp"

namespace retrovue::blockplan::testing {
namespace {

// =============================================================================
// Diagnostic Harness
// Produces human-readable output proving correct executor behavior
// =============================================================================

class ExecutorDiagnosticHarness : public ::testing::Test {
 protected:
  void SetUp() override {
    clock_ = std::make_unique<FakeClock>();
    assets_ = std::make_unique<FakeAssetSource>();
    sink_ = std::make_unique<RecordingSink>();
    executor_ = std::make_unique<BlockPlanExecutor>();
  }

  // Generate diagnostic output: one line per second
  std::string GenerateDiagnosticOutput(const std::vector<EmittedFrame>& frames,
                                        int64_t block_duration_ms) {
    std::ostringstream out;

    out << "\n";
    out << "╔══════════════════════════════════════════════════════════════╗\n";
    out << "║           BLOCKPLAN EXECUTOR DIAGNOSTIC OUTPUT               ║\n";
    out << "╠══════════════════════════════════════════════════════════════╣\n";
    out << "║  Block Duration: " << std::setw(5) << (block_duration_ms / 1000)
        << " seconds                                  ║\n";
    out << "║  Frame Rate: ~30 fps (33ms per frame)                        ║\n";
    out << "╚══════════════════════════════════════════════════════════════╝\n";
    out << "\n";

    // Group frames by second
    int64_t current_second = -1;
    int32_t last_segment = -1;
    bool last_was_pad = false;
    int frames_this_second = 0;
    int real_frames_this_second = 0;
    int pad_frames_this_second = 0;

    for (const auto& frame : frames) {
      int64_t frame_second = frame.ct_ms / 1000;

      if (frame_second != current_second) {
        // Print previous second if we have data
        if (current_second >= 0) {
          PrintSecondLine(out, current_second, current_second * 1000,
                          last_segment, last_was_pad,
                          real_frames_this_second, pad_frames_this_second);
        }

        // Start new second
        current_second = frame_second;
        frames_this_second = 0;
        real_frames_this_second = 0;
        pad_frames_this_second = 0;
      }

      frames_this_second++;
      if (frame.is_pad) {
        pad_frames_this_second++;
      } else {
        real_frames_this_second++;
      }

      last_segment = frame.segment_index;
      last_was_pad = frame.is_pad;
    }

    // Print final second
    if (current_second >= 0) {
      PrintSecondLine(out, current_second, current_second * 1000,
                      last_segment, last_was_pad,
                      real_frames_this_second, pad_frames_this_second);
    }

    out << "\n";
    out << "════════════════════════════════════════════════════════════════\n";
    out << "                    ▓▓▓ BLOCK COMPLETE ▓▓▓                      \n";
    out << "════════════════════════════════════════════════════════════════\n";

    return out.str();
  }

  void PrintSecondLine(std::ostringstream& out, int64_t second, int64_t ct_ms,
                       int32_t segment, bool is_pad,
                       int real_count, int pad_count) {
    out << "t=" << std::setw(2) << std::setfill('0') << second << "s"
        << " │ CT=" << std::setw(5) << std::setfill('0') << ct_ms
        << " │ SEG=" << segment
        << " │ ";

    if (pad_count > 0 && real_count == 0) {
      out << "░░░ PAD   ";
    } else if (pad_count > 0) {
      out << "█░░ MIXED ";
    } else {
      out << "███ REAL  ";
    }

    out << " │ frames: " << std::setw(2) << (real_count + pad_count)
        << " (real:" << std::setw(2) << real_count
        << " pad:" << std::setw(2) << pad_count << ")";

    // Mark segment transitions
    static int32_t prev_segment = -1;
    if (prev_segment != -1 && prev_segment != segment) {
      out << " ◄── SEGMENT TRANSITION";
    }
    prev_segment = segment;

    // Mark underrun start
    if (pad_count > 0 && real_count > 0) {
      out << " ◄── UNDERRUN START";
    } else if (pad_count > 0 && real_count == 0) {
      static bool first_full_pad = true;
      if (first_full_pad) {
        out << " ◄── PADDING CONTINUES";
        first_full_pad = false;
      }
    }

    out << "\n";
  }

  // Verify correctness programmatically
  struct VerificationResult {
    bool ct_starts_correctly;
    bool ct_monotonic;
    bool segment_transitions_at_boundary;
    bool underrun_produces_padding;
    bool stops_at_fence;
    std::string details;
  };

  VerificationResult VerifyExecution(const std::vector<EmittedFrame>& frames,
                                      int64_t expected_ct_start,
                                      int64_t segment_boundary_ct,
                                      int64_t underrun_start_ct,
                                      int64_t block_duration_ms) {
    VerificationResult result;
    std::ostringstream details;

    // 1. CT starts correctly
    result.ct_starts_correctly = !frames.empty() &&
                                  frames.front().ct_ms == expected_ct_start;
    details << "CT Start: " << (result.ct_starts_correctly ? "✓" : "✗")
            << " (expected=" << expected_ct_start
            << ", actual=" << (frames.empty() ? -1 : frames.front().ct_ms) << ")\n";

    // 2. CT is monotonic
    result.ct_monotonic = true;
    for (size_t i = 1; i < frames.size(); ++i) {
      if (frames[i].ct_ms <= frames[i-1].ct_ms) {
        result.ct_monotonic = false;
        details << "CT Monotonic: ✗ (violation at frame " << i << ")\n";
        break;
      }
    }
    if (result.ct_monotonic) {
      details << "CT Monotonic: ✓ (all " << frames.size() << " frames increasing)\n";
    }

    // 3. Segment transitions at boundary
    result.segment_transitions_at_boundary = true;
    for (size_t i = 1; i < frames.size(); ++i) {
      if (frames[i-1].segment_index != frames[i].segment_index) {
        // Transition should occur at or just after boundary
        if (frames[i].ct_ms < segment_boundary_ct) {
          result.segment_transitions_at_boundary = false;
          details << "Segment Transition: ✗ (too early at CT=" << frames[i].ct_ms << ")\n";
          break;
        }
      }
    }
    if (result.segment_transitions_at_boundary) {
      details << "Segment Transition: ✓ (at CT>=" << segment_boundary_ct << ")\n";
    }

    // 4. Underrun produces padding
    result.underrun_produces_padding = false;
    for (const auto& frame : frames) {
      if (frame.ct_ms >= underrun_start_ct && frame.is_pad) {
        result.underrun_produces_padding = true;
        break;
      }
    }
    details << "Underrun Padding: " << (result.underrun_produces_padding ? "✓" : "✗")
            << " (padding after CT=" << underrun_start_ct << ")\n";

    // 5. Stops at fence
    result.stops_at_fence = !frames.empty() &&
                            frames.back().ct_ms < block_duration_ms;
    details << "Fence Stop: " << (result.stops_at_fence ? "✓" : "✗")
            << " (last CT=" << (frames.empty() ? -1 : frames.back().ct_ms)
            << ", fence=" << block_duration_ms << ")\n";

    result.details = details.str();
    return result;
  }

  std::unique_ptr<FakeClock> clock_;
  std::unique_ptr<FakeAssetSource> assets_;
  std::unique_ptr<RecordingSink> sink_;
  std::unique_ptr<BlockPlanExecutor> executor_;
};

// =============================================================================
// DIAGNOSTIC TEST: 60-Second Block with Underrun
// =============================================================================

TEST_F(ExecutorDiagnosticHarness, SixtySecondBlockWithUnderrun) {
  // =========================================================================
  // SETUP: 60-second block with underrun in segment 1
  // =========================================================================
  constexpr int64_t kBlockStart = 0;
  constexpr int64_t kBlockDuration = 60000;  // 60 seconds
  constexpr int64_t kBlockEnd = kBlockStart + kBlockDuration;

  constexpr int64_t kSeg0Duration = 30000;   // 30 seconds allocated
  constexpr int64_t kSeg1Duration = 30000;   // 30 seconds allocated
  constexpr int64_t kSeg1AssetDuration = 20000;  // Only 20 seconds of content!

  // Register assets
  // Segment 0: Full 30-second asset
  assets_->RegisterSimpleAsset("segment0.mp4", kSeg0Duration, 33);
  // Segment 1: Only 20 seconds (will underrun by 10 seconds)
  assets_->RegisterSimpleAsset("segment1_short.mp4", kSeg1AssetDuration, 33);

  // Build block plan
  BlockPlan plan;
  plan.block_id = "DIAG-001";
  plan.channel_id = 1;
  plan.start_utc_ms = kBlockStart;
  plan.end_utc_ms = kBlockEnd;

  Segment seg0;
  seg0.segment_index = 0;
  seg0.asset_uri = "segment0.mp4";
  seg0.asset_start_offset_ms = 0;
  seg0.segment_duration_ms = kSeg0Duration;
  plan.segments.push_back(seg0);

  Segment seg1;
  seg1.segment_index = 1;
  seg1.asset_uri = "segment1_short.mp4";
  seg1.asset_start_offset_ms = 0;
  seg1.segment_duration_ms = kSeg1Duration;
  plan.segments.push_back(seg1);

  // Validate
  BlockPlanValidator validator(assets_->AsDurationFn());
  auto validation = validator.Validate(plan, kBlockStart);
  ASSERT_TRUE(validation.valid) << validation.detail;

  ValidatedBlockPlan validated{plan, validation.boundaries, kBlockStart};

  // Compute join (start at block beginning)
  auto join_result = JoinComputer::ComputeJoinParameters(validated, kBlockStart);
  ASSERT_TRUE(join_result.valid);

  // =========================================================================
  // EXECUTE
  // =========================================================================
  clock_->SetMs(kBlockStart);
  auto result = executor_->Execute(validated, join_result.params,
                                    clock_.get(), assets_.get(), sink_.get());

  ASSERT_EQ(result.exit_code, ExecutorExitCode::kSuccess);

  // =========================================================================
  // GENERATE DIAGNOSTIC OUTPUT
  // =========================================================================
  std::string diagnostic = GenerateDiagnosticOutput(sink_->Frames(), kBlockDuration);

  // Print to test output
  std::cout << diagnostic;

  // =========================================================================
  // VERIFICATION
  // =========================================================================
  auto verification = VerifyExecution(
      sink_->Frames(),
      0,                    // Expected CT start
      kSeg0Duration,        // Segment boundary at 30000ms
      kSeg0Duration + kSeg1AssetDuration,  // Underrun at 50000ms
      kBlockDuration        // Block fence at 60000ms
  );

  std::cout << "\n";
  std::cout << "╔══════════════════════════════════════════════════════════════╗\n";
  std::cout << "║                    VERIFICATION SUMMARY                      ║\n";
  std::cout << "╠══════════════════════════════════════════════════════════════╣\n";
  std::cout << verification.details;
  std::cout << "╚══════════════════════════════════════════════════════════════╝\n";

  // Assert all checks pass
  EXPECT_TRUE(verification.ct_starts_correctly);
  EXPECT_TRUE(verification.ct_monotonic);
  EXPECT_TRUE(verification.segment_transitions_at_boundary);
  EXPECT_TRUE(verification.underrun_produces_padding);
  EXPECT_TRUE(verification.stops_at_fence);
}

// =============================================================================
// DIAGNOSTIC TEST: Mid-Block Join
// =============================================================================

TEST_F(ExecutorDiagnosticHarness, MidBlockJoinDiagnostic) {
  // =========================================================================
  // SETUP: Join at 45 seconds into a 60-second block
  // =========================================================================
  constexpr int64_t kBlockStart = 0;
  constexpr int64_t kBlockDuration = 60000;
  constexpr int64_t kBlockEnd = kBlockStart + kBlockDuration;
  constexpr int64_t kJoinTime = 45000;  // Join 45 seconds in

  constexpr int64_t kSeg0Duration = 30000;
  constexpr int64_t kSeg1Duration = 30000;

  assets_->RegisterSimpleAsset("segment0.mp4", kSeg0Duration, 33);
  assets_->RegisterSimpleAsset("segment1.mp4", kSeg1Duration, 33);

  BlockPlan plan;
  plan.block_id = "DIAG-MID";
  plan.channel_id = 1;
  plan.start_utc_ms = kBlockStart;
  plan.end_utc_ms = kBlockEnd;

  plan.segments.push_back({0, "segment0.mp4", 0, kSeg0Duration});
  plan.segments.push_back({1, "segment1.mp4", 0, kSeg1Duration});

  BlockPlanValidator validator(assets_->AsDurationFn());
  auto validation = validator.Validate(plan, kBlockStart);
  ASSERT_TRUE(validation.valid);

  ValidatedBlockPlan validated{plan, validation.boundaries, kBlockStart};

  // Join mid-block at 45 seconds
  auto join_result = JoinComputer::ComputeJoinParameters(validated, kJoinTime);
  ASSERT_TRUE(join_result.valid);

  EXPECT_EQ(join_result.params.ct_start_ms, 45000);
  EXPECT_EQ(join_result.params.start_segment_index, 1);  // Should be in seg 1

  // Execute
  clock_->SetMs(kJoinTime);
  auto result = executor_->Execute(validated, join_result.params,
                                    clock_.get(), assets_.get(), sink_.get());

  ASSERT_EQ(result.exit_code, ExecutorExitCode::kSuccess);

  // Output
  std::cout << "\n";
  std::cout << "╔══════════════════════════════════════════════════════════════╗\n";
  std::cout << "║              MID-BLOCK JOIN DIAGNOSTIC (t=45s)               ║\n";
  std::cout << "╠══════════════════════════════════════════════════════════════╣\n";
  std::cout << "║  Block: 60 seconds, Join at: 45 seconds                      ║\n";
  std::cout << "║  Expected: Start in SEG=1, CT=45000, run until CT=60000      ║\n";
  std::cout << "╚══════════════════════════════════════════════════════════════╝\n";

  std::cout << GenerateDiagnosticOutput(sink_->Frames(), kBlockDuration);

  // Verify
  EXPECT_FALSE(sink_->Empty());
  EXPECT_EQ(sink_->FirstCtMs().value(), 45000);
  EXPECT_EQ(sink_->Frames().front().segment_index, 1);
  EXPECT_EQ(sink_->FramesFromSegment(0), 0u);  // No frames from seg 0
}

}  // namespace
}  // namespace retrovue::blockplan::testing
