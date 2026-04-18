// Repository: Retrovue-playout
// Component: LAW-AIR-005 TAKE Cascade Priority Contract Tests
// Purpose: Prove the TAKE frame-selection cascade evaluates in correct priority:
//            (1) PAD_SEAM_OVERRIDE       (highest)
//            (2) CONTENT_SEAM_OVERRIDE
//            (3) CADENCE_REPEAT
//            (4) NORMAL_ADVANCE          (includes VSRC gate)
//            (5) BLOCK_FENCE
//            (6) SEGMENT_SEAM_HOLD
//            (7) GENUINE_UNDERFLOW
//            (8) PRIMED_NO_DECODER
//            (9) NOT_PRIMED              (lowest / fallthrough)
//          Each test verifies its tier fires AND lower-priority tiers do not.
// Contract Reference: LAW-AIR-005, air_truth_canonical_v2.md §1.7
// Method: Calls SelectCascadeBranch() directly with constructed inputs.
//         No session bring-up, no bootstrap, no encoder, no socket.
// Copyright (c) 2026 RetroVue

#include <gtest/gtest.h>
#include "retrovue/blockplan/PipelineManager.hpp"

using retrovue::blockplan::CascadeBranch;
using retrovue::blockplan::SelectCascadeBranch;

namespace retrovue::blockplan::testing {
namespace {

// Helper: call SelectCascadeBranch with named parameters for readability.
struct CascadeInputs {
  bool pad_seam_this_tick = false;
  bool content_seam_override_this_tick = false;
  bool content_seam_pop_succeeded = false;
  bool is_cadence_repeat = false;
  bool should_advance_video = false;
  bool v_src_non_null = false;
  bool take_b = false;
  bool take_segment = false;
  bool has_last_good_video_frame = false;
  bool a_was_primed = false;
  bool live_has_decoder = false;

  CascadeBranch Select() const {
    return SelectCascadeBranch(
        pad_seam_this_tick,
        content_seam_override_this_tick,
        content_seam_pop_succeeded,
        is_cadence_repeat,
        should_advance_video,
        v_src_non_null,
        take_b,
        take_segment,
        has_last_good_video_frame,
        a_was_primed,
        live_has_decoder);
  }
};

// ============================================================================
// Test 1: PadSeamOverride_HasHighestPriority
// When pad_seam_this_tick is true, branch 1 fires regardless of what
// lower-priority conditions are also true.
// ============================================================================
TEST(TakeCascadePriority, PadSeamOverride_HasHighestPriority) {
  CascadeInputs in;
  in.pad_seam_this_tick = true;

  // All lower-priority conditions also true — branch 1 must still win.
  in.content_seam_override_this_tick = true;
  in.content_seam_pop_succeeded = true;
  in.is_cadence_repeat = true;
  in.should_advance_video = true;
  in.v_src_non_null = true;
  in.take_b = true;
  in.take_segment = true;
  in.has_last_good_video_frame = true;
  in.a_was_primed = true;
  in.live_has_decoder = true;

  EXPECT_EQ(in.Select(), CascadeBranch::kPadSeamOverride)
      << "PAD_SEAM_OVERRIDE must fire when pad_seam_this_tick is true, "
         "even when all lower-priority conditions are also true";
}

// ============================================================================
// Test 2: ContentSeamOverride_OverridesVsrcGate
// When content_seam fires (branch 2), it must preempt the normal advance
// path (branch 4) where the VSRC gate operates.
// ============================================================================
TEST(TakeCascadePriority, ContentSeamOverride_OverridesVsrcGate) {
  CascadeInputs in;
  in.content_seam_override_this_tick = true;
  in.content_seam_pop_succeeded = true;

  // Branch 4 conditions also true (VSRC gate would select incoming buffer).
  in.should_advance_video = true;
  in.v_src_non_null = true;

  // Branches 3, 5, 6, 7, 8 conditions also true for exhaustive suppression proof.
  in.is_cadence_repeat = true;   // branch 3 — but branch 2 is higher priority
  in.take_b = true;              // branch 5
  in.take_segment = true;        // branch 6 (with has_last_good)
  in.has_last_good_video_frame = true;
  in.a_was_primed = true;        // branches 7, 8
  in.live_has_decoder = true;

  // Branch 1 is OFF (pad_seam_this_tick = false).
  EXPECT_EQ(in.Select(), CascadeBranch::kContentSeamOverride)
      << "CONTENT_SEAM_OVERRIDE must fire when content_seam and pop succeeded, "
         "preempting VSRC gate (branch 4) and all lower branches";

  // Prove branch 4 (VSRC gate / normal advance) would have fired if branch 2 were off.
  in.content_seam_override_this_tick = false;
  in.content_seam_pop_succeeded = false;
  in.is_cadence_repeat = false;  // disable branch 3 to isolate branch 4
  EXPECT_EQ(in.Select(), CascadeBranch::kNormalAdvance)
      << "With content seam override disabled and cadence repeat off, "
         "branch 4 (VSRC gate / normal advance) must fire";
}

// ============================================================================
// Test 3: VsrcGate_OverridesNormalPath
// Branch 4 (NormalAdvance) fires when should_advance_video && v_src are true.
// This is the path where the VSRC gate operates. It must preempt branches 5-9.
// ============================================================================
TEST(TakeCascadePriority, VsrcGate_OverridesNormalPath) {
  CascadeInputs in;
  in.should_advance_video = true;
  in.v_src_non_null = true;

  // All lower-priority conditions also true.
  in.take_b = true;
  in.take_segment = true;
  in.has_last_good_video_frame = true;
  in.a_was_primed = true;
  in.live_has_decoder = true;

  // Branches 1, 2, 3 are OFF.
  EXPECT_EQ(in.Select(), CascadeBranch::kNormalAdvance)
      << "Branch 4 (NormalAdvance / VSRC gate) must fire when "
         "should_advance_video && v_src, preempting branches 5-9";

  // Prove that without branch 4 conditions, branch 5 (kBlockFence) would fire.
  in.should_advance_video = false;
  in.v_src_non_null = false;
  EXPECT_EQ(in.Select(), CascadeBranch::kBlockFence)
      << "With branch 4 disabled, branch 5 (kBlockFence) must fire";
}

// ============================================================================
// Test 4: NormalPath_ContentThenFreezeThenPad
// When no seam overrides, no cadence repeat, no advance, no fence, no segment
// seam — the cascade falls through to branches 7, 8, 9 based on priming state.
// This tests the normal fallback chain: content → hold → pad.
// ============================================================================
TEST(TakeCascadePriority, NormalPath_ContentThenFreezeThenPad) {
  // Sub-case A: Branch 4 fires (content from normal advance).
  {
    CascadeInputs in;
    in.should_advance_video = true;
    in.v_src_non_null = true;
    EXPECT_EQ(in.Select(), CascadeBranch::kNormalAdvance)
        << "Normal path sub-case A: content advance";
  }

  // Sub-case B: Branch 7 fires (genuine underflow — primed + decoder).
  // This is the "hold/freeze" equivalent in the original chain.
  {
    CascadeInputs in;
    in.a_was_primed = true;
    in.live_has_decoder = true;
    EXPECT_EQ(in.Select(), CascadeBranch::kGenuineUnderflow)
        << "Normal path sub-case B: primed with decoder = genuine underflow";
  }

  // Sub-case C: Branch 8 fires (primed, no decoder — pad).
  {
    CascadeInputs in;
    in.a_was_primed = true;
    in.live_has_decoder = false;
    EXPECT_EQ(in.Select(), CascadeBranch::kPrimedNoDecoder)
        << "Normal path sub-case C: primed without decoder = pad";
  }

  // Sub-case D: Branch 9 fires (not primed at all — pad).
  {
    CascadeInputs in;
    // Everything false.
    EXPECT_EQ(in.Select(), CascadeBranch::kNotPrimed)
        << "Normal path sub-case D: nothing set = not primed = pad";
  }

  // Priority ordering within the fallback chain:
  // Branch 7 must beat branch 8 when both conditions overlap.
  {
    CascadeInputs in;
    in.a_was_primed = true;
    in.live_has_decoder = true;
    EXPECT_EQ(in.Select(), CascadeBranch::kGenuineUnderflow)
        << "Branch 7 (primed+decoder) must beat branch 8 (primed only)";
    in.live_has_decoder = false;
    EXPECT_EQ(in.Select(), CascadeBranch::kPrimedNoDecoder)
        << "Without decoder, branch 8 fires instead of branch 7";
  }
}

// ============================================================================
// Test 5: PadOverride_SuppressesContentOverride
// When both pad_seam_this_tick AND content_seam conditions are true,
// branch 1 (pad) must fire and branch 2 (content) must NOT.
// This is the critical suppression test for the highest-priority override.
// ============================================================================
TEST(TakeCascadePriority, PadOverride_SuppressesContentOverride) {
  CascadeInputs in;
  // Both tier 1 and tier 2 conditions are true.
  in.pad_seam_this_tick = true;
  in.content_seam_override_this_tick = true;
  in.content_seam_pop_succeeded = true;

  EXPECT_EQ(in.Select(), CascadeBranch::kPadSeamOverride)
      << "When both PAD seam and CONTENT seam conditions are true, "
         "PAD seam (branch 1) must suppress CONTENT seam (branch 2)";

  // Prove that if pad_seam were off, content seam would win.
  in.pad_seam_this_tick = false;
  EXPECT_EQ(in.Select(), CascadeBranch::kContentSeamOverride)
      << "With pad seam disabled, content seam override must fire";
}

// ============================================================================
// Additional priority tests: verify every adjacent pair in the chain.
// ============================================================================

TEST(TakeCascadePriority, Branch2_Beats_Branch3) {
  CascadeInputs in;
  in.content_seam_override_this_tick = true;
  in.content_seam_pop_succeeded = true;
  in.is_cadence_repeat = true;
  EXPECT_EQ(in.Select(), CascadeBranch::kContentSeamOverride);
}

TEST(TakeCascadePriority, Branch3_Beats_Branch4) {
  CascadeInputs in;
  in.is_cadence_repeat = true;
  in.should_advance_video = true;
  in.v_src_non_null = true;
  EXPECT_EQ(in.Select(), CascadeBranch::kCadenceRepeat);
}

TEST(TakeCascadePriority, Branch4_Beats_Branch5) {
  CascadeInputs in;
  in.should_advance_video = true;
  in.v_src_non_null = true;
  in.take_b = true;
  EXPECT_EQ(in.Select(), CascadeBranch::kNormalAdvance);
}

TEST(TakeCascadePriority, Branch5_Beats_Branch6) {
  CascadeInputs in;
  in.take_b = true;
  in.take_segment = true;
  in.has_last_good_video_frame = true;
  EXPECT_EQ(in.Select(), CascadeBranch::kBlockFence);
}

TEST(TakeCascadePriority, Branch6_Beats_Branch7) {
  CascadeInputs in;
  in.take_segment = true;
  in.has_last_good_video_frame = true;
  in.a_was_primed = true;
  in.live_has_decoder = true;
  EXPECT_EQ(in.Select(), CascadeBranch::kSegmentSeamHold);
}

TEST(TakeCascadePriority, Branch7_Beats_Branch8) {
  CascadeInputs in;
  in.a_was_primed = true;
  in.live_has_decoder = true;
  EXPECT_EQ(in.Select(), CascadeBranch::kGenuineUnderflow);
  in.live_has_decoder = false;
  EXPECT_EQ(in.Select(), CascadeBranch::kPrimedNoDecoder);
}

TEST(TakeCascadePriority, Branch8_Beats_Branch9) {
  CascadeInputs in;
  in.a_was_primed = true;
  EXPECT_EQ(in.Select(), CascadeBranch::kPrimedNoDecoder);
  in.a_was_primed = false;
  EXPECT_EQ(in.Select(), CascadeBranch::kNotPrimed);
}

// Content seam requires pop to succeed — if pop fails, branch 2 does not fire.
TEST(TakeCascadePriority, ContentSeam_PopFailure_FallsThrough) {
  CascadeInputs in;
  in.content_seam_override_this_tick = true;
  in.content_seam_pop_succeeded = false;  // Pop failed
  in.is_cadence_repeat = true;
  EXPECT_EQ(in.Select(), CascadeBranch::kCadenceRepeat)
      << "Content seam with failed pop must fall through to branch 3";
}

}  // namespace
}  // namespace retrovue::blockplan::testing
