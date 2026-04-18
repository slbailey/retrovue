// Repository: Retrovue-playout
// Component: LAW-AIR-009A First-IDR-From-Content Contract Tests
// Purpose: Prove that the content-before-pad gate in PipelineManager::Run()
//          suppresses pad emission until a real content frame has been committed.
//          This gate ensures the encoder's first IDR comes from real content,
//          not pad — without it, VLC cannot decode the initial stream.
//
//          The gate's logic (PipelineManager.cpp ~line 3010):
//            should_skip_tick = (decision is kPad/kStandby)
//                            && (!first_real_frame_committed)
//                            && (live has decoder)
//
//          first_real_frame_committed flips to true when decision is
//          kContentA/kContentB/kRepeat/kHold.
//
// Contract Reference: LAW-AIR-009A, air_truth_canonical_v2.md §1.8
// Copyright (c) 2026 RetroVue

#include <gtest/gtest.h>

namespace retrovue::blockplan::testing {
namespace {

// TakeDecision is defined in PipelineManager.cpp (file-local). Replicate the
// values here for gate-logic testing. These MUST match the production enum.
// If the production enum changes, this test will need updating — which is
// intentional: any change to TakeDecision should be reviewed for gate impact.
enum class TakeDecision { kContentA, kContentB, kRepeat, kHold, kStandby, kPad };

// Replicate the exact gate logic from PipelineManager::Run() as a pure function.
// This is a 1:1 copy of the boolean conditions at ~line 3010-3021.
// Inputs are the same variables the production code uses.
struct ContentBeforePadGateInput {
  TakeDecision decision = TakeDecision::kPad;
  bool first_real_frame_committed = false;
  bool live_has_decoder = true;
};

bool ShouldSkipTick(const ContentBeforePadGateInput& in) {
  // Line 3009-3016: skip when pad/standby, no real frame yet, decoder exists.
  bool should_skip = false;
  if ((in.decision == TakeDecision::kPad || in.decision == TakeDecision::kStandby) &&
      !in.first_real_frame_committed && in.live_has_decoder) {
    // In production this also checks decoder_might_produce; here we assume true
    // (worst case: decoder could produce content, so gate should suppress pad).
    should_skip = true;
  }
  // Line 3018-3021: pad-only / probe-failed (no decoder) never skip.
  if ((in.decision == TakeDecision::kPad || in.decision == TakeDecision::kStandby) &&
      !in.live_has_decoder) {
    should_skip = false;
  }
  return should_skip;
}

bool IsFirstRealFrame(TakeDecision decision) {
  // Line 3022-3027: these decisions flip first_real_frame_committed to true.
  return decision == TakeDecision::kContentA ||
         decision == TakeDecision::kContentB ||
         decision == TakeDecision::kRepeat ||
         decision == TakeDecision::kHold;
}

// ============================================================================
// Test 1: Pad suppressed before first content frame
// The core invariant: when the encoder has not yet received a real frame,
// pad decisions are skipped (tick continues without encode).
// ============================================================================
TEST(FirstIdrFromContent, PadSuppressedBeforeFirstContent) {
  ContentBeforePadGateInput in;
  in.decision = TakeDecision::kPad;
  in.first_real_frame_committed = false;
  in.live_has_decoder = true;

  EXPECT_TRUE(ShouldSkipTick(in))
      << "Pad must be suppressed before first real content frame (gate active)";

  // Standby also suppressed.
  in.decision = TakeDecision::kStandby;
  EXPECT_TRUE(ShouldSkipTick(in))
      << "Standby must be suppressed before first real content frame";
}

// ============================================================================
// Test 2: Content frame passes through (not suppressed)
// Content decisions are never skipped — they ARE the first real frame.
// ============================================================================
TEST(FirstIdrFromContent, ContentFrameNotSuppressed) {
  ContentBeforePadGateInput in;
  in.first_real_frame_committed = false;
  in.live_has_decoder = true;

  in.decision = TakeDecision::kContentA;
  EXPECT_FALSE(ShouldSkipTick(in))
      << "Content (A) must never be suppressed by the gate";

  in.decision = TakeDecision::kContentB;
  EXPECT_FALSE(ShouldSkipTick(in))
      << "Content (B) must never be suppressed by the gate";

  // Content decisions flip the committed flag.
  EXPECT_TRUE(IsFirstRealFrame(TakeDecision::kContentA));
  EXPECT_TRUE(IsFirstRealFrame(TakeDecision::kContentB));
  EXPECT_TRUE(IsFirstRealFrame(TakeDecision::kRepeat));
  EXPECT_TRUE(IsFirstRealFrame(TakeDecision::kHold));
}

// ============================================================================
// Test 3: After first content frame, pad is allowed
// Once first_real_frame_committed is true, the gate is permanently open.
// ============================================================================
TEST(FirstIdrFromContent, PadAllowedAfterFirstContent) {
  ContentBeforePadGateInput in;
  in.decision = TakeDecision::kPad;
  in.first_real_frame_committed = true;  // Content was committed on a prior tick.
  in.live_has_decoder = true;

  EXPECT_FALSE(ShouldSkipTick(in))
      << "Pad must be allowed after first real content frame has been committed";
}

// ============================================================================
// Test 4: No-decoder blocks bypass the gate (pad allowed immediately)
// Pad-only or probe-failed blocks have no decoder. Content will never arrive,
// so suppressing pad would stall output indefinitely.
// ============================================================================
TEST(FirstIdrFromContent, NoDecoderBypassesGate) {
  ContentBeforePadGateInput in;
  in.decision = TakeDecision::kPad;
  in.first_real_frame_committed = false;
  in.live_has_decoder = false;  // No decoder — pad-only block.

  EXPECT_FALSE(ShouldSkipTick(in))
      << "Pad-only blocks (no decoder) must bypass the content-before-pad gate";
}

// ============================================================================
// Test 5: Gate suppression is exclusive to pad/standby decisions
// Content, repeat, and hold decisions are never suppressed regardless of
// first_real_frame_committed state.
// ============================================================================
TEST(FirstIdrFromContent, OnlyPadAndStandbySuppressed) {
  ContentBeforePadGateInput in;
  in.first_real_frame_committed = false;
  in.live_has_decoder = true;

  // These should NOT be suppressed.
  in.decision = TakeDecision::kContentA;
  EXPECT_FALSE(ShouldSkipTick(in));

  in.decision = TakeDecision::kContentB;
  EXPECT_FALSE(ShouldSkipTick(in));

  in.decision = TakeDecision::kRepeat;
  EXPECT_FALSE(ShouldSkipTick(in));

  in.decision = TakeDecision::kHold;
  EXPECT_FALSE(ShouldSkipTick(in));

  // These SHOULD be suppressed.
  in.decision = TakeDecision::kPad;
  EXPECT_TRUE(ShouldSkipTick(in));

  in.decision = TakeDecision::kStandby;
  EXPECT_TRUE(ShouldSkipTick(in));
}

// ============================================================================
// Test 6: The gate is a one-shot latch
// Once first_real_frame_committed flips to true, it never reverts.
// Simulating the sequence: pad (suppressed) → content (committed) → pad (allowed).
// ============================================================================
TEST(FirstIdrFromContent, GateIsOneShotLatch) {
  bool committed = false;

  // Tick 1: pad decision, not committed → suppressed.
  {
    ContentBeforePadGateInput in;
    in.decision = TakeDecision::kPad;
    in.first_real_frame_committed = committed;
    in.live_has_decoder = true;
    EXPECT_TRUE(ShouldSkipTick(in)) << "Tick 1: pad suppressed";
  }

  // Tick 2: content decision → committed flips.
  committed = IsFirstRealFrame(TakeDecision::kContentA);
  EXPECT_TRUE(committed);

  // Tick 3: pad decision, now committed → allowed.
  {
    ContentBeforePadGateInput in;
    in.decision = TakeDecision::kPad;
    in.first_real_frame_committed = committed;
    in.live_has_decoder = true;
    EXPECT_FALSE(ShouldSkipTick(in)) << "Tick 3: pad allowed after content committed";
  }

  // Tick 4: another pad → still allowed (latch is permanent).
  {
    ContentBeforePadGateInput in;
    in.decision = TakeDecision::kStandby;
    in.first_real_frame_committed = committed;
    in.live_has_decoder = true;
    EXPECT_FALSE(ShouldSkipTick(in)) << "Tick 4: standby allowed (latch permanent)";
  }
}

}  // namespace
}  // namespace retrovue::blockplan::testing
