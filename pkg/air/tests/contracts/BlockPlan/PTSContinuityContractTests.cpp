// Repository: Retrovue-playout
// Component: PTS Continuity Contract Tests
// Purpose: Verify PTS/DTS continuity across block boundaries
// Contract Reference: INV-PTS-MONOTONIC, INV-PTS-CONTINUOUS, INV-CT-UNCHANGED, INV-NO-MID-BLOCK-PTS-JUMP
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <cstdint>
#include <vector>

namespace retrovue::blockplan::testing {
namespace {

// Frame duration for emission (33ms ≈ 30fps)
static constexpr int64_t kFrameDurationMs = 33;

// =============================================================================
// PTS Recording Sink
// Simulates the PTS offset logic from RealTimeEncoderSink to verify correctness
// =============================================================================

class PTSRecordingSink {
 public:
  struct RecordedFrame {
    int64_t ct_ms;           // Content Time (resets per block)
    int64_t pts_90k;         // PTS in 90kHz units (should be monotonic across session)
    std::string block_id;    // Which block this frame belongs to
    int32_t frame_index;     // Frame index within block
  };

  PTSRecordingSink() = default;

  // Emit a frame with CT and block context
  // This replicates the PTS calculation from RealTimeEncoderSink
  void EmitFrame(int64_t ct_ms, const std::string& block_id) {
    // Handle block transitions (CT reset)
    if (last_ct_ms_ >= 0 && ct_ms < last_ct_ms_) {
      // CT dropped - block transition, adjust PTS offset
      // BUG: This was: pts_offset_90k_ = (last_ct_ms_ + kFrameDurationMs) * 90;
      // Should be: pts_offset_90k_ += (last_ct_ms_ + kFrameDurationMs) * 90;
      pts_offset_90k_ += (last_ct_ms_ + kFrameDurationMs) * 90;
    }
    last_ct_ms_ = ct_ms;

    // Compute PTS in 90kHz units
    int64_t pts_90k = ct_ms * 90 + pts_offset_90k_;

    RecordedFrame frame;
    frame.ct_ms = ct_ms;
    frame.pts_90k = pts_90k;
    frame.block_id = block_id;
    frame.frame_index = static_cast<int32_t>(frames_.size());
    frames_.push_back(frame);
  }

  const std::vector<RecordedFrame>& Frames() const { return frames_; }
  size_t FrameCount() const { return frames_.size(); }
  bool Empty() const { return frames_.empty(); }
  void Clear() {
    frames_.clear();
    pts_offset_90k_ = 0;
    last_ct_ms_ = -1;
  }

  // INV-PTS-MONOTONIC: PTS never decreases within a session
  bool AllPtsMonotonic() const {
    for (size_t i = 1; i < frames_.size(); ++i) {
      if (frames_[i].pts_90k <= frames_[i - 1].pts_90k) {
        return false;
      }
    }
    return true;
  }

  // INV-PTS-CONTINUOUS: PTS advances by expected frame duration (no gaps/jumps)
  // Tolerance: allow ±1 tick for rounding
  bool AllPtsContinuous(int64_t expected_delta_90k = kFrameDurationMs * 90) const {
    for (size_t i = 1; i < frames_.size(); ++i) {
      int64_t actual_delta = frames_[i].pts_90k - frames_[i - 1].pts_90k;
      // Allow exactly expected delta (no discontinuity)
      if (actual_delta != expected_delta_90k) {
        return false;
      }
    }
    return true;
  }

  // INV-CT-UNCHANGED: CT resets to 0 at block boundaries (verify CT behavior)
  bool CtResetsAtBlockBoundaries() const {
    std::string last_block_id;
    for (const auto& frame : frames_) {
      if (!last_block_id.empty() && frame.block_id != last_block_id) {
        // Block transition detected
        // CT should be small (near 0) at block start
        if (frame.ct_ms >= kFrameDurationMs * 2) {
          return false;  // CT didn't reset properly
        }
      }
      last_block_id = frame.block_id;
    }
    return true;
  }

  // INV-NO-MID-BLOCK-PTS-JUMP: No unexpected PTS jumps within a single block
  bool NoPtsJumpsWithinBlock(int64_t max_allowed_delta_90k = kFrameDurationMs * 90 * 2) const {
    for (size_t i = 1; i < frames_.size(); ++i) {
      if (frames_[i].block_id == frames_[i - 1].block_id) {
        int64_t delta = frames_[i].pts_90k - frames_[i - 1].pts_90k;
        if (delta > max_allowed_delta_90k || delta <= 0) {
          return false;
        }
      }
    }
    return true;
  }

  // Get PTS at block boundary
  std::pair<int64_t, int64_t> GetPtsAtBlockBoundary(const std::string& block_id) const {
    int64_t first_pts = -1;
    int64_t last_pts = -1;
    for (const auto& frame : frames_) {
      if (frame.block_id == block_id) {
        if (first_pts < 0) first_pts = frame.pts_90k;
        last_pts = frame.pts_90k;
      }
    }
    return {first_pts, last_pts};
  }

 private:
  std::vector<RecordedFrame> frames_;
  int64_t pts_offset_90k_ = 0;
  int64_t last_ct_ms_ = -1;
};

// =============================================================================
// Buggy PTS Sink (replicates the bug for verification)
// =============================================================================

class BuggyPTSRecordingSink {
 public:
  struct RecordedFrame {
    int64_t ct_ms;
    int64_t pts_90k;
    std::string block_id;
  };

  void EmitFrame(int64_t ct_ms, const std::string& block_id) {
    // BUG: Uses = instead of += (this is the actual bug in the code)
    if (last_ct_ms_ >= 0 && ct_ms < last_ct_ms_) {
      pts_offset_90k_ = (last_ct_ms_ + kFrameDurationMs) * 90;  // BUG!
    }
    last_ct_ms_ = ct_ms;
    int64_t pts_90k = ct_ms * 90 + pts_offset_90k_;

    frames_.push_back({ct_ms, pts_90k, block_id});
  }

  const std::vector<RecordedFrame>& Frames() const { return frames_; }
  void Clear() {
    frames_.clear();
    pts_offset_90k_ = 0;
    last_ct_ms_ = -1;
  }

  bool AllPtsMonotonic() const {
    for (size_t i = 1; i < frames_.size(); ++i) {
      if (frames_[i].pts_90k <= frames_[i - 1].pts_90k) {
        return false;
      }
    }
    return true;
  }

 private:
  std::vector<RecordedFrame> frames_;
  int64_t pts_offset_90k_ = 0;
  int64_t last_ct_ms_ = -1;
};

// =============================================================================
// Test Fixture
// =============================================================================

class PTSContinuityTest : public ::testing::Test {
 protected:
  void SetUp() override {
    sink_ = std::make_unique<PTSRecordingSink>();
    buggy_sink_ = std::make_unique<BuggyPTSRecordingSink>();
  }

  // Simulate a block with given duration
  void SimulateBlock(PTSRecordingSink* sink, const std::string& block_id,
                     int64_t block_duration_ms) {
    for (int64_t ct_ms = 0; ct_ms < block_duration_ms; ct_ms += kFrameDurationMs) {
      sink->EmitFrame(ct_ms, block_id);
    }
  }

  void SimulateBlock(BuggyPTSRecordingSink* sink, const std::string& block_id,
                     int64_t block_duration_ms) {
    for (int64_t ct_ms = 0; ct_ms < block_duration_ms; ct_ms += kFrameDurationMs) {
      sink->EmitFrame(ct_ms, block_id);
    }
  }

  std::unique_ptr<PTSRecordingSink> sink_;
  std::unique_ptr<BuggyPTSRecordingSink> buggy_sink_;
};

// =============================================================================
// A. SINGLE BLOCK TESTS (Baseline)
// =============================================================================

// -----------------------------------------------------------------------------
// TEST-PTS-001: Single block has monotonic PTS
// INV-PTS-MONOTONIC: PTS never decreases within a session
// -----------------------------------------------------------------------------
TEST_F(PTSContinuityTest, SingleBlockHasMonotonicPts) {
  constexpr int64_t kBlockDuration = 5000;  // 5 seconds

  SimulateBlock(sink_.get(), "BLOCK-1", kBlockDuration);

  EXPECT_TRUE(sink_->AllPtsMonotonic());
  EXPECT_GT(sink_->FrameCount(), 100u);  // ~152 frames for 5s at 30fps
}

// -----------------------------------------------------------------------------
// TEST-PTS-002: Single block has continuous PTS
// INV-PTS-CONTINUOUS: PTS advances by frame duration
// -----------------------------------------------------------------------------
TEST_F(PTSContinuityTest, SingleBlockHasContinuousPts) {
  constexpr int64_t kBlockDuration = 5000;

  SimulateBlock(sink_.get(), "BLOCK-1", kBlockDuration);

  EXPECT_TRUE(sink_->AllPtsContinuous());
}

// =============================================================================
// B. TWO BLOCK TESTS (Verify transition)
// =============================================================================

// -----------------------------------------------------------------------------
// TEST-PTS-003: Two consecutive blocks maintain PTS monotonicity
// INV-PTS-MONOTONIC across block boundary
// This is the primary test that would fail with the bug
// -----------------------------------------------------------------------------
TEST_F(PTSContinuityTest, TwoBlocksMaintainPtsMonotonicity) {
  constexpr int64_t kBlockDuration = 5000;

  SimulateBlock(sink_.get(), "BLOCK-1", kBlockDuration);
  SimulateBlock(sink_.get(), "BLOCK-2", kBlockDuration);

  EXPECT_TRUE(sink_->AllPtsMonotonic())
      << "PTS should be monotonically increasing across block boundary";

  // Verify we have frames from both blocks
  auto [block1_first, block1_last] = sink_->GetPtsAtBlockBoundary("BLOCK-1");
  auto [block2_first, block2_last] = sink_->GetPtsAtBlockBoundary("BLOCK-2");

  EXPECT_GT(block2_first, block1_last)
      << "First PTS of BLOCK-2 (" << block2_first << ") should be > last PTS of BLOCK-1 ("
      << block1_last << ")";
}

// -----------------------------------------------------------------------------
// TEST-PTS-004: Two blocks maintain PTS continuity (no gaps)
// INV-PTS-CONTINUOUS: PTS advances smoothly across block boundary
// -----------------------------------------------------------------------------
TEST_F(PTSContinuityTest, TwoBlocksMaintainPtsContinuity) {
  constexpr int64_t kBlockDuration = 5000;

  SimulateBlock(sink_.get(), "BLOCK-1", kBlockDuration);
  SimulateBlock(sink_.get(), "BLOCK-2", kBlockDuration);

  EXPECT_TRUE(sink_->AllPtsContinuous())
      << "PTS should advance by exactly frame duration across all frames";
}

// -----------------------------------------------------------------------------
// TEST-PTS-005: CT resets at block boundary
// INV-CT-UNCHANGED: CT is block-relative (resets to 0)
// -----------------------------------------------------------------------------
TEST_F(PTSContinuityTest, CtResetsAtBlockBoundary) {
  constexpr int64_t kBlockDuration = 5000;

  SimulateBlock(sink_.get(), "BLOCK-1", kBlockDuration);
  SimulateBlock(sink_.get(), "BLOCK-2", kBlockDuration);

  EXPECT_TRUE(sink_->CtResetsAtBlockBoundaries())
      << "CT should reset to ~0 at block boundaries";
}

// =============================================================================
// C. THREE BLOCK TESTS (Verify accumulation)
// =============================================================================

// -----------------------------------------------------------------------------
// TEST-PTS-006: Three consecutive blocks maintain PTS monotonicity
// This catches the bug where PTS resets on the third block
// The bug: pts_offset = X (not +=) means third block starts at same offset as second
// -----------------------------------------------------------------------------
TEST_F(PTSContinuityTest, ThreeBlocksMaintainPtsMonotonicity) {
  constexpr int64_t kBlockDuration = 5000;

  SimulateBlock(sink_.get(), "BLOCK-1", kBlockDuration);
  SimulateBlock(sink_.get(), "BLOCK-2", kBlockDuration);
  SimulateBlock(sink_.get(), "BLOCK-3", kBlockDuration);

  EXPECT_TRUE(sink_->AllPtsMonotonic())
      << "PTS must be monotonically increasing across all three blocks";

  // Verify PTS values are properly accumulated
  auto [block1_first, block1_last] = sink_->GetPtsAtBlockBoundary("BLOCK-1");
  auto [block2_first, block2_last] = sink_->GetPtsAtBlockBoundary("BLOCK-2");
  auto [block3_first, block3_last] = sink_->GetPtsAtBlockBoundary("BLOCK-3");

  // Each block's first PTS should be greater than previous block's last PTS
  EXPECT_GT(block2_first, block1_last);
  EXPECT_GT(block3_first, block2_last);

  // Block 3's first PTS should be approximately 2x block duration after block 1's first PTS
  int64_t expected_block3_start = 2 * kBlockDuration * 90;  // ~900000 ticks
  EXPECT_GT(block3_first, expected_block3_start - 90 * kFrameDurationMs)
      << "Block 3 first PTS (" << block3_first << ") should be near " << expected_block3_start;
}

// -----------------------------------------------------------------------------
// TEST-PTS-007: Three blocks maintain PTS continuity
// -----------------------------------------------------------------------------
TEST_F(PTSContinuityTest, ThreeBlocksMaintainPtsContinuity) {
  constexpr int64_t kBlockDuration = 5000;

  SimulateBlock(sink_.get(), "BLOCK-1", kBlockDuration);
  SimulateBlock(sink_.get(), "BLOCK-2", kBlockDuration);
  SimulateBlock(sink_.get(), "BLOCK-3", kBlockDuration);

  EXPECT_TRUE(sink_->AllPtsContinuous());
}

// =============================================================================
// D. BUG VERIFICATION TESTS
// These tests demonstrate that the buggy implementation fails
// =============================================================================

// -----------------------------------------------------------------------------
// TEST-PTS-BUG-001: Demonstrate buggy implementation fails on two blocks
// This test EXPECTS the buggy sink to fail (documents the bug)
// -----------------------------------------------------------------------------
TEST_F(PTSContinuityTest, BuggyImplementationFailsOnTwoBlocks) {
  constexpr int64_t kBlockDuration = 5000;

  SimulateBlock(buggy_sink_.get(), "BLOCK-1", kBlockDuration);
  SimulateBlock(buggy_sink_.get(), "BLOCK-2", kBlockDuration);

  // The buggy implementation should still pass for two blocks
  // because the first transition correctly sets the offset
  EXPECT_TRUE(buggy_sink_->AllPtsMonotonic())
      << "Bug may not manifest with just two blocks";
}

// -----------------------------------------------------------------------------
// TEST-PTS-BUG-002: Demonstrate buggy implementation fails on three blocks
// This is the key test - the bug causes PTS to overlap/decrease on block 3
// -----------------------------------------------------------------------------
TEST_F(PTSContinuityTest, BuggyImplementationFailsOnThreeBlocks) {
  constexpr int64_t kBlockDuration = 5000;

  SimulateBlock(buggy_sink_.get(), "BLOCK-1", kBlockDuration);
  SimulateBlock(buggy_sink_.get(), "BLOCK-2", kBlockDuration);
  SimulateBlock(buggy_sink_.get(), "BLOCK-3", kBlockDuration);

  // The buggy implementation should FAIL on three blocks
  // because the offset is overwritten (not accumulated) on the third block
  EXPECT_FALSE(buggy_sink_->AllPtsMonotonic())
      << "Buggy implementation should fail PTS monotonicity on third block";
}

// =============================================================================
// E. NO MID-BLOCK JUMP TESTS
// =============================================================================

// -----------------------------------------------------------------------------
// TEST-PTS-008: No unexpected PTS jumps within a single block
// INV-NO-MID-BLOCK-PTS-JUMP
// -----------------------------------------------------------------------------
TEST_F(PTSContinuityTest, NoPtsJumpsWithinBlock) {
  constexpr int64_t kBlockDuration = 5000;

  SimulateBlock(sink_.get(), "BLOCK-1", kBlockDuration);
  SimulateBlock(sink_.get(), "BLOCK-2", kBlockDuration);
  SimulateBlock(sink_.get(), "BLOCK-3", kBlockDuration);

  EXPECT_TRUE(sink_->NoPtsJumpsWithinBlock());
}

// =============================================================================
// F. EDGE CASES
// =============================================================================

// -----------------------------------------------------------------------------
// TEST-PTS-009: Very short blocks still maintain continuity
// -----------------------------------------------------------------------------
TEST_F(PTSContinuityTest, ShortBlocksMaintainContinuity) {
  // Blocks shorter than 1 second
  constexpr int64_t kShortBlockDuration = 200;  // ~6 frames

  for (int i = 1; i <= 10; ++i) {
    SimulateBlock(sink_.get(), "BLOCK-" + std::to_string(i), kShortBlockDuration);
  }

  EXPECT_TRUE(sink_->AllPtsMonotonic());
  EXPECT_TRUE(sink_->AllPtsContinuous());
}

// -----------------------------------------------------------------------------
// TEST-PTS-010: Many blocks maintain continuity (stress test)
// -----------------------------------------------------------------------------
TEST_F(PTSContinuityTest, ManyBlocksMaintainContinuity) {
  constexpr int64_t kBlockDuration = 1000;  // 1 second blocks
  constexpr int kNumBlocks = 20;

  for (int i = 1; i <= kNumBlocks; ++i) {
    SimulateBlock(sink_.get(), "BLOCK-" + std::to_string(i), kBlockDuration);
  }

  EXPECT_TRUE(sink_->AllPtsMonotonic());
  EXPECT_TRUE(sink_->AllPtsContinuous());

  // Verify final PTS is approximately correct
  // Note: Each block's last frame is at ct_ms < block_duration, so there's
  // accumulated rounding. Allow tolerance of 2 frames per block.
  int64_t expected_final_pts = kNumBlocks * kBlockDuration * 90;  // 90kHz
  int64_t actual_final_pts = sink_->Frames().back().pts_90k;

  // Should be within 2 frames per block (rounding accumulation)
  EXPECT_NEAR(actual_final_pts, expected_final_pts, kNumBlocks * kFrameDurationMs * 90 * 2);
}

}  // namespace
}  // namespace retrovue::blockplan::testing
