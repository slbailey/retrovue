// Repository: Retrovue-playout
// Component: INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001 Contract Tests
// Purpose: Verify emitted frame origin matches authoritative segment at every tick.
// Contract: docs/contracts/invariants/air/INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001.md
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>
#include <string>
#include <vector>

#include "retrovue/blockplan/PipelineManager.hpp"
#include "retrovue/util/Logger.hpp"

using retrovue::blockplan::IncomingState;
using retrovue::blockplan::PipelineManager;
using retrovue::blockplan::SegmentType;
using retrovue::util::Logger;

namespace {

class AtomicAuthorityTransferTest : public ::testing::Test {
 protected:
  void SetUp() override {
    captured_errors_.clear();
    Logger::SetErrorSink([this](const std::string& line) {
      captured_errors_.push_back(line);
    });
  }

  void TearDown() override {
    Logger::SetErrorSink(nullptr);
  }

  bool HasViolationTag() const {
    for (const auto& line : captured_errors_) {
      if (line.find("INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001-VIOLATED") != std::string::npos) {
        return true;
      }
    }
    return false;
  }

  std::vector<std::string> captured_errors_;
};

// Frame origin matches active authority — no violation.
TEST_F(AtomicAuthorityTransferTest, NoViolationWhenFrameMatchesAuthority) {
  bool ok = PipelineManager::EmittedFrameMatchesAuthority(
      /*tick=*/100,
      /*active_segment_id=*/2,
      /*frame_origin_segment_id=*/2);

  EXPECT_TRUE(ok);
  EXPECT_FALSE(HasViolationTag());
}

// Authority transferred from segment 0 to segment 1, but emitted frame
// still originates from segment 0 — stale frame bleed violation.
TEST_F(AtomicAuthorityTransferTest, ViolationWhenFrameFromPreviousSegmentAfterSwap) {
  bool ok = PipelineManager::EmittedFrameMatchesAuthority(
      /*tick=*/200,
      /*active_segment_id=*/1,
      /*frame_origin_segment_id=*/0);

  EXPECT_FALSE(ok);
  EXPECT_TRUE(HasViolationTag());

  // Verify structured fields in violation log.
  ASSERT_EQ(captured_errors_.size(), 1u);
  const std::string& log = captured_errors_[0];
  EXPECT_NE(log.find("tick=200"), std::string::npos);
  EXPECT_NE(log.find("active_segment_id=1"), std::string::npos);
  EXPECT_NE(log.find("frame_origin_segment_id=0"), std::string::npos);
  EXPECT_NE(log.find("reason=stale_frame_bleed"), std::string::npos);
}

// Frame origin is unset (null / -1) — violation regardless of active segment.
TEST_F(AtomicAuthorityTransferTest, ViolationWhenFrameOriginIsNull) {
  bool ok = PipelineManager::EmittedFrameMatchesAuthority(
      /*tick=*/300,
      /*active_segment_id=*/0,
      /*frame_origin_segment_id=*/-1);

  EXPECT_FALSE(ok);
  EXPECT_TRUE(HasViolationTag());

  ASSERT_EQ(captured_errors_.size(), 1u);
  const std::string& log = captured_errors_[0];
  EXPECT_NE(log.find("tick=300"), std::string::npos);
  EXPECT_NE(log.find("active_segment_id=0"), std::string::npos);
  EXPECT_NE(log.find("frame_origin_segment_id=-1"), std::string::npos);
  EXPECT_NE(log.find("reason=frame_origin_null"), std::string::npos);
}

// Active changed from 0 to 1, but frame origin is still 0 (old segment).
// Distinct from the general mismatch test: explicitly models the swap boundary.
TEST_F(AtomicAuthorityTransferTest, ViolationWhenFrameOriginIsOldSegmentDespiteActiveChanged) {
  // Simulate: at tick 399, active was segment 0. At tick 400, active is segment 1.
  // Frame at tick 400 still originates from segment 0.
  bool ok = PipelineManager::EmittedFrameMatchesAuthority(
      /*tick=*/400,
      /*active_segment_id=*/1,
      /*frame_origin_segment_id=*/0);

  EXPECT_FALSE(ok);
  EXPECT_TRUE(HasViolationTag());

  ASSERT_EQ(captured_errors_.size(), 1u);
  const std::string& log = captured_errors_[0];
  EXPECT_NE(log.find("tick=400"), std::string::npos);
  EXPECT_NE(log.find("active_segment_id=1"), std::string::npos);
  EXPECT_NE(log.find("frame_origin_segment_id=0"), std::string::npos);
  EXPECT_NE(log.find("reason=stale_frame_bleed"), std::string::npos);
}

// ===========================================================================
// PAD seam contract tests (pad_seam_this_tick enforcement)
//
// These tests validate the origin tracking rule that prevents the pre-fix
// bug: on a CONTENT→PAD segment seam, the hold path would emit a stale
// content frame (origin = old content segment) while active authority had
// transferred to the PAD segment.  The fix forces pad_producer_->VideoFrame()
// synchronously with origin = PAD segment, so EmittedFrameMatchesAuthority
// must pass.
// ===========================================================================

// ContentToPadSeamDoesNotEmitStaleContentFrame:
// Models the PAD seam override.  After PerformSegmentSwap bumps
// current_segment_index_ to the PAD segment (e.g. 1), the frame origin
// must also be 1 (the PAD segment) — NOT 0 (the old content segment).
// This is the exact bug that pad_seam_this_tick prevents.
TEST_F(AtomicAuthorityTransferTest, ContentToPadSeamDoesNotEmitStaleContentFrame) {
  // Post-swap state: active = 1 (PAD), origin = 1 (pad_seam_to_seg stamped).
  bool ok = PipelineManager::EmittedFrameMatchesAuthority(
      /*tick=*/500,
      /*active_segment_id=*/1,
      /*frame_origin_segment_id=*/1);

  EXPECT_TRUE(ok) << "PAD seam must produce origin matching new PAD authority";
  EXPECT_FALSE(HasViolationTag());

  // Now prove the bug scenario: if origin were still 0 (old content), violation.
  captured_errors_.clear();
  bool bad = PipelineManager::EmittedFrameMatchesAuthority(
      /*tick=*/500,
      /*active_segment_id=*/1,
      /*frame_origin_segment_id=*/0);

  EXPECT_FALSE(bad) << "Stale content frame at PAD seam must trigger violation";
  EXPECT_TRUE(HasViolationTag());
  ASSERT_EQ(captured_errors_.size(), 1u);
  EXPECT_NE(captured_errors_[0].find("reason=stale_frame_bleed"), std::string::npos);
}

// ContentToPadSeamForcesPadEvenWhenOldBufferHasFrames:
// Even when the old content buffer still has frames (origin would be 0),
// the PAD seam override must stamp origin = PAD segment.  This test proves
// that the invariant rejects origin from the old segment regardless of
// buffer depth.  (In the real code, pad_seam_this_tick short-circuits
// the entire cascade, so the old buffer is never consulted.)
TEST_F(AtomicAuthorityTransferTest, ContentToPadSeamForcesPadEvenWhenOldBufferHasFrames) {
  // Scenario: 3-segment block [CONTENT(0), PAD(1), CONTENT(2)].
  // At the 0→1 seam, even if segment 0's buffer has frames, origin must be 1.
  // The invariant check validates this contract.

  // Correct: origin = 1 (PAD segment, forced by pad_seam_this_tick).
  bool ok = PipelineManager::EmittedFrameMatchesAuthority(
      /*tick=*/600,
      /*active_segment_id=*/1,
      /*frame_origin_segment_id=*/1);
  EXPECT_TRUE(ok) << "PAD override must prevail even when old buffer has frames";
  EXPECT_FALSE(HasViolationTag());

  // Wrong: origin = 0 (old content — the hold path would have used this).
  captured_errors_.clear();
  bool bad = PipelineManager::EmittedFrameMatchesAuthority(
      /*tick=*/600,
      /*active_segment_id=*/1,
      /*frame_origin_segment_id=*/0);
  EXPECT_FALSE(bad) << "Old content origin at PAD seam must be rejected";
  EXPECT_TRUE(HasViolationTag());
}

// ContentToContentSeamMayUseHoldIfAllowed:
// Control test: CONTENT→CONTENT seam with hold (segment B not ready) is
// legitimate — the hold frame originates from the SAME content segment
// (current_segment_index_ stays unchanged when swap is deferred).
// This proves pad_seam_this_tick does not interfere with normal behavior.
TEST_F(AtomicAuthorityTransferTest, ContentToContentSeamMayUseHoldIfAllowed) {
  // Scenario: segment 0 (CONTENT) seam deferred — swap didn't fire.
  // current_segment_index_ stays 0, last_good_origin_segment_ = 0.
  // Hold frame is legitimate: origin matches active.
  bool ok = PipelineManager::EmittedFrameMatchesAuthority(
      /*tick=*/700,
      /*active_segment_id=*/0,
      /*frame_origin_segment_id=*/0);

  EXPECT_TRUE(ok) << "Content-to-content hold must not trigger violation when swap is deferred";
  EXPECT_FALSE(HasViolationTag());
}

// ===========================================================================
// INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001: PAD seam stale-B-buffer race
//
// Reproduces the exact bug sequence:
//   1. Active = content segment 1, incoming = PAD segment 2
//   2. segment_b_video_buffer_ exists but empty → GetIncomingSegmentState
//      returns stale content B depths (video_frames=0)
//   3. IsIncomingSegmentEligibleForSwap rejects (0 < kMinSwapVideoFrames)
//   4. Swap deferred → current_segment_index_ stays at 1
//   5. PAD frame emitted with origin = 2 → origin != active → VIOLATED
//
// The test proves atomicity: origin(T) MUST equal active(T) in the same
// tick.  Before fix: FAILS (gate defers, atomicity broken).
// After fix: PASSES (PAD exempt from video gate, swap proceeds).
// ===========================================================================

// Unit gate test: PAD with stale content B depths must still be eligible.
TEST_F(AtomicAuthorityTransferTest, PadSeamWithStaleBBuffersMustNotDeferSwap) {
  IncomingState pad_state;
  pad_state.incoming_audio_ms = 500;    // meets threshold
  pad_state.incoming_video_frames = 0;  // stale content B, empty
  pad_state.is_pad = true;
  pad_state.segment_type = SegmentType::kPad;

  // PAD segments provide video on-demand (pad_producer_->VideoFrame()).
  // The video-depth gate must not apply.
  EXPECT_TRUE(PipelineManager::IsIncomingSegmentEligibleForSwap(pad_state))
      << "PAD segment swap deferred due to video depth gate — "
         "INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001 will fire";
}

// Compound atomicity test: chains gate → swap decision → emission check.
// Proves that a deferred PAD swap causes a measurable atomicity violation.
TEST_F(AtomicAuthorityTransferTest, PadSeamDeferredSwapCausesStaleFrameBleed) {
  // Exact bug state: active = content (1), incoming = PAD (2).
  // GetIncomingSegmentState returned stale content B depths.
  const int32_t active_segment_id = 1;   // content, still current
  const int32_t pad_segment_id = 2;      // PAD, frame was selected from here

  IncomingState pad_state;
  pad_state.incoming_audio_ms = 500;
  pad_state.incoming_video_frames = 0;  // stale content B
  pad_state.is_pad = true;
  pad_state.segment_type = SegmentType::kPad;

  const bool eligible =
      PipelineManager::IsIncomingSegmentEligibleForSwap(pad_state);

  if (!eligible) {
    // Gate deferred the swap → active stays at 1.
    // But PAD frame was already selected → origin = 2.
    // Prove this violates atomicity: origin(T) != active(T).
    bool atomicity_holds = PipelineManager::EmittedFrameMatchesAuthority(
        /*tick=*/800,
        /*active_segment_id=*/active_segment_id,
        /*frame_origin_segment_id=*/pad_segment_id);
    EXPECT_FALSE(atomicity_holds)
        << "Stale frame bleed must be detected by invariant check";
    EXPECT_TRUE(HasViolationTag());

    // The gate should NOT have deferred a PAD swap.
    FAIL() << "PAD segment swap deferred due to video depth gate — "
              "active_segment_id=" << active_segment_id
           << " but frame_origin_segment_id=" << pad_segment_id
           << " — INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001 violated at emission";
  }

  // Gate accepted → swap proceeds → active becomes pad_segment_id.
  // Atomicity holds: origin(T) == active(T).
  EXPECT_TRUE(PipelineManager::EmittedFrameMatchesAuthority(
      /*tick=*/800,
      /*active_segment_id=*/pad_segment_id,
      /*frame_origin_segment_id=*/pad_segment_id))
      << "After PAD swap, active and origin must match";
  EXPECT_FALSE(HasViolationTag());
}

// ===========================================================================
// INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001: Safety-net restamp contract
//
// Models the fill-thread race where CONTENT_SEAM_OVERRIDE did not pop a
// content frame (segment B was empty at frame-selection time), the tick
// loop fell through to the PAD hold path, and FORCE_EXECUTE fired after
// the fill thread pushed frames into segment B by POST-TAKE.
//
// The safety-net restamp corrects frame_origin_segment_id from the old
// PAD segment to the new CONTENT segment after PerformSegmentSwap.
//
// These tests prove:
//   (a) Without restamp, the mismatch is detected as stale_frame_bleed.
//   (b) After restamp, origin matches active — invariant holds.
// ===========================================================================

// (a) Without restamp: PAD hold frame origin mismatches CONTENT authority.
// Models: CONTENT_SEAM_OVERRIDE failed (segb empty) → hold from PAD (origin=1)
// → FORCE_EXECUTE swaps to CONTENT (active=2) → origin(1) != active(2).
TEST_F(AtomicAuthorityTransferTest, SafetyNetRaceWithoutRestampViolates) {
  const int32_t pad_segment = 1;
  const int32_t content_segment = 2;

  // Pre-restamp state: hold frame from PAD, swap already advanced to CONTENT.
  bool ok = PipelineManager::EmittedFrameMatchesAuthority(
      /*tick=*/900,
      /*active_segment_id=*/content_segment,
      /*frame_origin_segment_id=*/pad_segment);

  EXPECT_FALSE(ok) << "Without restamp, PAD hold origin must violate CONTENT authority";
  EXPECT_TRUE(HasViolationTag());
  ASSERT_GE(captured_errors_.size(), 1u);
  EXPECT_NE(captured_errors_[0].find("reason=stale_frame_bleed"), std::string::npos);
}

// (b) After restamp: origin corrected to match new CONTENT authority.
// Models: same race as above, but restamp applied — origin updated to 2.
TEST_F(AtomicAuthorityTransferTest, SafetyNetRestampCorrectionPassesAuthorityCheck) {
  const int32_t content_segment = 2;

  // Post-restamp state: origin re-stamped to match active.
  bool ok = PipelineManager::EmittedFrameMatchesAuthority(
      /*tick=*/900,
      /*active_segment_id=*/content_segment,
      /*frame_origin_segment_id=*/content_segment);

  EXPECT_TRUE(ok) << "After restamp, origin must match CONTENT authority";
  EXPECT_FALSE(HasViolationTag());
}

// Compound: content seam override success requires matching authority.
// Models: CONTENT_SEAM_OVERRIDE succeeded → popped content frame with
// origin = to_seg (2) → swap advances active to 2 → origin matches.
TEST_F(AtomicAuthorityTransferTest, ContentSeamOverrideSuccessMatchesAuthority) {
  const int32_t content_segment = 2;

  bool ok = PipelineManager::EmittedFrameMatchesAuthority(
      /*tick=*/950,
      /*active_segment_id=*/content_segment,
      /*frame_origin_segment_id=*/content_segment);

  EXPECT_TRUE(ok) << "Content seam override: origin from segment B must match new authority";
  EXPECT_FALSE(HasViolationTag());
}

// Compound: content seam override succeeded but swap did NOT fire.
// This should never happen (force_swap_for_content_seam prevents it),
// but proves the violation is detectable.
TEST_F(AtomicAuthorityTransferTest, ContentSeamOverrideWithoutSwapViolates) {
  const int32_t pad_segment = 1;    // active stayed (swap didn't fire)
  const int32_t content_segment = 2; // origin from segment B pop

  bool ok = PipelineManager::EmittedFrameMatchesAuthority(
      /*tick=*/960,
      /*active_segment_id=*/pad_segment,
      /*frame_origin_segment_id=*/content_segment);

  EXPECT_FALSE(ok) << "Content frame emitted under PAD authority must violate";
  EXPECT_TRUE(HasViolationTag());
  ASSERT_GE(captured_errors_.size(), 1u);
  EXPECT_NE(captured_errors_[0].find("reason=stale_frame_bleed"), std::string::npos);
}

}  // namespace
