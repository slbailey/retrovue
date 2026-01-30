// Repository: Retrovue-playout
// Component: Deterministic Harness Contract Tests
// Purpose: Validates control-plane and continuity invariants using deterministic harness.
// Copyright (c) 2025 RetroVue
//
// These tests prove that AIR cannot "help itself" and strictly follows
// the dead-man fallback semantics defined in BlackFrameProducerContract.md.

#include <gtest/gtest.h>

#include "BaseContractTest.h"
#include "harness/deterministic/DeterministicTestHarness.h"
#include "harness/deterministic/FakeProducers.h"
#include "harness/deterministic/FrameSource.h"
#include "harness/deterministic/RecordingSink.h"
#include "timing/TestMasterClock.h"

namespace retrovue::tests::contracts {

using namespace harness::deterministic;

class DeterministicHarnessContractTest : public BaseContractTest {
 protected:
  [[nodiscard]] std::string DomainName() const override {
    return "DeterministicHarness";
  }

  [[nodiscard]] std::vector<std::string> CoveredRuleIds() const override {
    return {"DH_001", "DH_002", "DH_003", "DH_004", "DH_005",
            "INV_001", "INV_002", "INV_003", "INV_004", "INV_005"};
  }

  void SetUp() override {
    BaseContractTest::SetUp();
    harness_ = std::make_unique<DeterministicTestHarness>();
  }

  void TearDown() override {
    harness_.reset();
    BaseContractTest::TearDown();
  }

  std::unique_ptr<DeterministicTestHarness> harness_;
};

// ============================================================================
// INVARIANT 1: Fallback Semantics Must Be One-Way and Explicit
// ============================================================================
//
// Fallback (BlackFrameProducer) is a DEAD-MAN STATE:
// - AIR enters fallback ONLY when live producer underruns/exhausts
// - AIR does NOT enter fallback during planned transitions
// - Fallback is strictly reserved for loss-of-direction scenarios

// INV_001: Fallback is entered ONLY on producer exhaustion (underrun/EOF/end-PTS)
TEST_F(DeterministicHarnessContractTest, INV_001_FallbackOnlyOnProducerExhaustion) {
  const std::string kAssetPath = "test://finite-asset.mp4";
  const int64_t kFrameCount = 5;

  harness_->RegisterProducerSpec(kAssetPath, ProducerSpec::Finite(kFrameCount));
  harness_->Start();

  // Load and switch to live - this is a PLANNED transition
  ASSERT_TRUE(harness_->LoadPreview(kAssetPath));
  ASSERT_TRUE(harness_->SwitchToLive());

  // INVARIANT: Planned transition must NOT trigger fallback
  EXPECT_FALSE(harness_->IsInBlackFallback())
      << "INV_001: Planned SwitchToLive MUST NOT enter fallback";
  EXPECT_EQ(harness_->GetFallbackEntryCount(), 0u)
      << "INV_001: Fallback entry count must be 0 after planned transition";

  // Tick to produce live frames (still not exhausted)
  for (int i = 0; i < kFrameCount - 1; ++i) {
    harness_->TickProducers();
    harness_->AdvanceToNextFrame();
    EXPECT_FALSE(harness_->IsInBlackFallback())
        << "INV_001: Must not be in fallback while producer has frames (tick " << i << ")";
  }

  // Exhaust the producer
  harness_->TickProducers();  // Produces last frame
  harness_->AdvanceToNextFrame();
  harness_->TickProducers();  // Producer now exhausted, triggers fallback

  // INVARIANT: Fallback entered ONLY after producer exhaustion
  EXPECT_TRUE(harness_->IsInBlackFallback())
      << "INV_001: Fallback MUST be entered when producer exhausts";
  EXPECT_EQ(harness_->GetFallbackEntryCount(), 1u)
      << "INV_001: Fallback should have been entered exactly once";
}

// INV_001b: Planned transitions NEVER trigger fallback
TEST_F(DeterministicHarnessContractTest, INV_001b_PlannedTransitionsNeverTriggerFallback) {
  const std::string kAsset1 = "test://asset1.mp4";
  const std::string kAsset2 = "test://asset2.mp4";

  harness_->RegisterProducerSpec(kAsset1, ProducerSpec::Infinite());
  harness_->RegisterProducerSpec(kAsset2, ProducerSpec::Infinite());
  harness_->Start();

  // First planned transition
  ASSERT_TRUE(harness_->LoadPreview(kAsset1));
  ASSERT_TRUE(harness_->SwitchToLive());
  EXPECT_EQ(harness_->GetFallbackEntryCount(), 0u)
      << "INV_001b: First SwitchToLive must not trigger fallback";

  // Produce some frames
  for (int i = 0; i < 10; ++i) {
    harness_->TickProducers();
    harness_->AdvanceToNextFrame();
  }
  harness_->DrainBufferToSink();

  // Second planned transition (before first producer exhausts)
  ASSERT_TRUE(harness_->LoadPreview(kAsset2));
  ASSERT_TRUE(harness_->SwitchToLive());

  // INVARIANT: Second planned transition also must not trigger fallback
  EXPECT_EQ(harness_->GetFallbackEntryCount(), 0u)
      << "INV_001b: Planned producer switch MUST NOT trigger fallback";
  EXPECT_FALSE(harness_->IsInBlackFallback())
      << "INV_001b: Must not be in fallback after planned switch";

  // Verify we're still producing live frames
  harness_->TickProducers();
  harness_->DrainBufferToSink();
  EXPECT_GT(harness_->GetSink().CountLiveFrames(), 0u)
      << "INV_001b: Must still be producing live frames after planned switch";
}

// ============================================================================
// INVARIANT 2: Fallback Exit Requires Explicit Core Reassertion
// ============================================================================
//
// Once in fallback, AIR MUST remain there indefinitely until Core
// explicitly reasserts control via LoadPreview + SwitchToLive.

// INV_002: AIR remains in fallback forever without explicit commands
TEST_F(DeterministicHarnessContractTest, INV_002_FallbackPersistsIndefinitely) {
  const std::string kAssetPath = "test://exhausting-asset.mp4";

  harness_->RegisterProducerSpec(kAssetPath, ProducerSpec::Finite(3));
  harness_->Start();

  // Enter fallback via producer exhaustion
  ASSERT_TRUE(harness_->LoadPreview(kAssetPath));
  ASSERT_TRUE(harness_->SwitchToLive());

  for (int i = 0; i < 5; ++i) {
    harness_->TickProducers();
    harness_->AdvanceToNextFrame();
  }

  ASSERT_TRUE(harness_->IsInBlackFallback())
      << "Precondition: Must be in fallback after exhaustion";
  uint64_t entry_count_before = harness_->GetFallbackEntryCount();

  // Issue NO commands for an extended period
  // INVARIANT: AIR must NOT exit fallback on its own
  const int kIdleTicks = 1000;  // Large number to prove indefinite persistence
  for (int i = 0; i < kIdleTicks; ++i) {
    harness_->TickProducers();
    harness_->AdvanceToNextFrame();

    // Check every 100 ticks
    if (i % 100 == 0) {
      EXPECT_TRUE(harness_->IsInBlackFallback())
          << "INV_002: AIR MUST remain in fallback without commands (tick " << i << ")";
      EXPECT_EQ(harness_->GetFallbackEntryCount(), entry_count_before)
          << "INV_002: Fallback entry count must not change during idle";
    }
  }
  harness_->DrainBufferToSink();

  // Final assertions
  EXPECT_TRUE(harness_->IsInBlackFallback())
      << "INV_002: AIR MUST still be in fallback after " << kIdleTicks << " ticks";

  // Verify all frames after exhaustion are BLACK
  const auto& sink = harness_->GetSink();
  auto transition_idx = sink.FindFirstTransitionToBlack();
  ASSERT_TRUE(transition_idx.has_value());
  EXPECT_TRUE(sink.AssertOnlyBlackFramesAfter(transition_idx.value() - 1))
      << "INV_002: All frames after exhaustion MUST be BLACK";
}

// INV_002b: Fallback exit ONLY via explicit Core command (SwitchToLive)
TEST_F(DeterministicHarnessContractTest, INV_002b_FallbackExitOnlyViaExplicitCommand) {
  const std::string kExhaustingAsset = "test://short-asset.mp4";
  const std::string kRecoveryAsset = "test://recovery-asset.mp4";

  harness_->RegisterProducerSpec(kExhaustingAsset, ProducerSpec::Finite(2));
  harness_->RegisterProducerSpec(kRecoveryAsset, ProducerSpec::Infinite());
  harness_->Start();

  // Enter fallback
  ASSERT_TRUE(harness_->LoadPreview(kExhaustingAsset));
  ASSERT_TRUE(harness_->SwitchToLive());

  for (int i = 0; i < 5; ++i) {
    harness_->TickProducers();
    harness_->AdvanceToNextFrame();
  }

  ASSERT_TRUE(harness_->IsInBlackFallback());

  // LoadPreview alone must NOT exit fallback
  ASSERT_TRUE(harness_->LoadPreview(kRecoveryAsset));
  EXPECT_TRUE(harness_->IsInBlackFallback())
      << "INV_002b: LoadPreview alone MUST NOT exit fallback";

  // Explicit SwitchToLive command exits fallback
  ASSERT_TRUE(harness_->SwitchToLive());
  EXPECT_FALSE(harness_->IsInBlackFallback())
      << "INV_002b: SwitchToLive MUST exit fallback";

  // Verify new live frames from recovery producer
  harness_->TickProducers();
  harness_->DrainBufferToSink();

  bool found_recovery_frame = false;
  for (const auto& frame : harness_->GetSink().GetFrames()) {
    if (frame.producer_id == kRecoveryAsset) {
      found_recovery_frame = true;
      break;
    }
  }
  EXPECT_TRUE(found_recovery_frame)
      << "INV_002b: Recovery frames MUST appear after explicit reassertion";
}

// ============================================================================
// INVARIANT 3: End-PTS Clamp Triggers Fallback (Intentional Design)
// ============================================================================
//
// When end-PTS is reached before Core provides next segment:
// - Producer is considered exhausted (IsExhausted() returns true)
// - This triggers fallback entry
// - This is INTENTIONAL: end-PTS exhaustion = loss of direction = fallback

// INV_003: End-PTS clamp triggers fallback state
TEST_F(DeterministicHarnessContractTest, INV_003_EndPTSClampTriggersFallback) {
  const std::string kAssetPath = "test://clamped-asset.mp4";

  // Clamp at 5 frames
  const int64_t kClampFrames = 5;
  const int64_t kEndPtsUs = kClampFrames * kFrameIntervalUs;

  harness_->RegisterProducerSpec(kAssetPath, ProducerSpec::Clamped(kEndPtsUs));
  harness_->Start();

  ASSERT_TRUE(harness_->LoadPreview(kAssetPath));
  ASSERT_TRUE(harness_->SwitchToLive());

  // Initially not in fallback
  EXPECT_FALSE(harness_->IsInBlackFallback());

  // Tick until clamp is reached
  for (int i = 0; i < 20; ++i) {
    harness_->TickProducers();
    harness_->AdvanceToNextFrame();
  }

  // INVARIANT: End-PTS clamp MUST trigger fallback
  EXPECT_TRUE(harness_->IsInBlackFallback())
      << "INV_003: End-PTS clamp MUST trigger fallback (this is intentional design)";
  EXPECT_EQ(harness_->GetFallbackEntryCount(), 1u)
      << "INV_003: Fallback should be entered exactly once on end-PTS";

  harness_->DrainBufferToSink();
  const auto& sink = harness_->GetSink();

  // Verify no LIVE frames beyond boundary
  EXPECT_TRUE(sink.AssertNoLiveFramesBeyondPTS(kEndPtsUs))
      << "INV_003: No LIVE frames may exceed end-PTS boundary";

  // Verify BLACK frames appear after boundary
  EXPECT_GT(sink.CountBlackFrames(), 0u)
      << "INV_003: BLACK frames must appear after end-PTS";
}

// INV_003b: End-PTS fallback state is observable and accurate
TEST_F(DeterministicHarnessContractTest, INV_003b_EndPTSFallbackStateObservable) {
  const std::string kAssetPath = "test://clamped-observable.mp4";
  const int64_t kClampFrames = 3;
  const int64_t kEndPtsUs = kClampFrames * kFrameIntervalUs;

  harness_->RegisterProducerSpec(kAssetPath, ProducerSpec::Clamped(kEndPtsUs));
  harness_->Start();

  ASSERT_TRUE(harness_->LoadPreview(kAssetPath));
  ASSERT_TRUE(harness_->SwitchToLive());

  // Track state transitions
  bool was_in_fallback = false;
  int transition_tick = -1;

  for (int i = 0; i < 10; ++i) {
    harness_->TickProducers();
    harness_->AdvanceToNextFrame();

    bool is_now_in_fallback = harness_->IsInBlackFallback();
    if (!was_in_fallback && is_now_in_fallback) {
      transition_tick = i;
    }
    was_in_fallback = is_now_in_fallback;
  }

  // INVARIANT: Fallback state transition must be observable
  EXPECT_NE(transition_tick, -1)
      << "INV_003b: Fallback state transition MUST be observable via IsInFallback()";
  EXPECT_GE(transition_tick, static_cast<int>(kClampFrames) - 1)
      << "INV_003b: Transition should occur around end-PTS boundary";
}

// ============================================================================
// INVARIANT 4: AIR Cannot "Help Itself"
// ============================================================================
//
// AIR must NEVER:
// - Initiate transitions without commands
// - Exit fallback without commands
// - Resume live output without commands

// INV_004: AIR never initiates autonomous transitions
TEST_F(DeterministicHarnessContractTest, INV_004_NoAutonomousTransitions) {
  const std::string kClampedAsset = "test://clamped-content.mp4";
  const std::string kNextAsset = "test://next-content.mp4";

  const int64_t kEndPtsUs = 3 * kFrameIntervalUs;

  harness_->RegisterProducerSpec(kClampedAsset, ProducerSpec::Clamped(kEndPtsUs));
  harness_->RegisterProducerSpec(kNextAsset, ProducerSpec::Infinite());
  harness_->Start();

  // Load clamped producer
  ASSERT_TRUE(harness_->LoadPreview(kClampedAsset));
  ASSERT_TRUE(harness_->SwitchToLive());

  // Tick until clamp exhausted
  for (int i = 0; i < 10; ++i) {
    harness_->TickProducers();
    harness_->AdvanceToNextFrame();
  }
  harness_->DrainBufferToSink();

  ASSERT_TRUE(harness_->IsInBlackFallback());

  const auto& sink = harness_->GetSink();

  // INVARIANT: No frames from "next" producer should appear
  // AIR must NOT autonomously load or switch to any other content
  bool found_next_frame = false;
  for (const auto& frame : sink.GetFrames()) {
    if (frame.producer_id == kNextAsset) {
      found_next_frame = true;
      break;
    }
  }
  EXPECT_FALSE(found_next_frame)
      << "INV_004: AIR MUST NOT autonomously load or switch to other content";

  // All post-clamp frames must be BLACK
  auto transition_idx = sink.FindFirstTransitionToBlack();
  if (transition_idx.has_value()) {
    for (size_t i = transition_idx.value(); i < sink.FrameCount(); ++i) {
      EXPECT_EQ(sink.GetFrame(i).source, FrameSource::BLACK)
          << "INV_004: Post-clamp frame " << i << " MUST be BLACK";
    }
  }
}

// INV_004b: Extended autonomous operation test - prove AIR is completely passive
TEST_F(DeterministicHarnessContractTest, INV_004b_ExtendedAutonomousOperationProof) {
  const std::string kAssetPath = "test://finite-for-extended-test.mp4";

  harness_->RegisterProducerSpec(kAssetPath, ProducerSpec::Finite(5));
  harness_->Start();

  ASSERT_TRUE(harness_->LoadPreview(kAssetPath));
  ASSERT_TRUE(harness_->SwitchToLive());

  // Exhaust producer
  for (int i = 0; i < 10; ++i) {
    harness_->TickProducers();
    harness_->AdvanceToNextFrame();
  }

  ASSERT_TRUE(harness_->IsInBlackFallback());
  uint64_t entry_count = harness_->GetFallbackEntryCount();

  // Extended period with no commands - simulating "Core is slow/failed"
  const int kExtendedTicks = 10000;
  for (int i = 0; i < kExtendedTicks; ++i) {
    harness_->TickProducers();
    harness_->AdvanceToNextFrame();
  }

  // INVARIANTS after extended autonomous operation:
  // 1. Still in fallback
  EXPECT_TRUE(harness_->IsInBlackFallback())
      << "INV_004b: AIR MUST remain in fallback after " << kExtendedTicks << " ticks";

  // 2. Fallback entry count unchanged (no re-entry, no cycling)
  EXPECT_EQ(harness_->GetFallbackEntryCount(), entry_count)
      << "INV_004b: Fallback entry count MUST NOT change during autonomous operation";

  // 3. No unexpected state changes
  // (The fact that we're still here proves no exceptions/crashes/weird state)
}

// ============================================================================
// INVARIANT 5: Time and Threading Safety in Tests
// ============================================================================
//
// Tests must:
// - Not depend on wall-clock time
// - Use fully controllable MasterClock
// - Be deterministic and repeatable

// INV_005: Deterministic time control - clock is fully controllable
TEST_F(DeterministicHarnessContractTest, INV_005_DeterministicTimeControl) {
  harness_->RegisterProducerSpec("test://asset.mp4", ProducerSpec::Finite(10));
  harness_->SetInitialTimeUs(1'000'000'000);  // Start at 1 second
  harness_->Start();

  auto clock = harness_->GetClock();
  ASSERT_NE(clock, nullptr);

  // Verify initial time
  EXPECT_EQ(clock->now_utc_us(), 1'000'000'000)
      << "INV_005: Clock must start at configured time";

  // Verify time advances exactly as commanded
  harness_->AdvanceTimeUs(500'000);
  EXPECT_EQ(clock->now_utc_us(), 1'000'500'000)
      << "INV_005: Clock must advance exactly by commanded amount";

  harness_->AdvanceToNextFrame();
  EXPECT_EQ(clock->now_utc_us(), 1'000'500'000 + kFrameIntervalUs)
      << "INV_005: AdvanceToNextFrame must advance by exactly one frame interval";

  // Verify clock reports as fake (deterministic mode)
  EXPECT_TRUE(clock->is_fake())
      << "INV_005: Clock must report is_fake()=true in deterministic mode";
}

// INV_005b: Repeatable test execution
TEST_F(DeterministicHarnessContractTest, INV_005b_RepeatableExecution) {
  // Run the same scenario twice and verify identical results
  auto run_scenario = [this]() -> std::pair<size_t, size_t> {
    harness_ = std::make_unique<DeterministicTestHarness>();
    harness_->RegisterProducerSpec("test://repeatable.mp4", ProducerSpec::Finite(7));
    harness_->Start();

    harness_->LoadPreview("test://repeatable.mp4");
    harness_->SwitchToLive();

    for (int i = 0; i < 15; ++i) {
      harness_->TickProducers();
      harness_->AdvanceToNextFrame();
    }
    harness_->DrainBufferToSink();

    size_t live_count = harness_->GetSink().CountLiveFrames();
    size_t black_count = harness_->GetSink().CountBlackFrames();
    harness_.reset();
    return {live_count, black_count};
  };

  auto [live1, black1] = run_scenario();
  auto [live2, black2] = run_scenario();

  EXPECT_EQ(live1, live2)
      << "INV_005b: Live frame count must be identical across runs";
  EXPECT_EQ(black1, black2)
      << "INV_005b: Black frame count must be identical across runs";

  // Restore harness for teardown
  harness_ = std::make_unique<DeterministicTestHarness>();
}

// ============================================================================
// Original DH Tests (preserved for completeness)
// ============================================================================

// DH-001: Dead-Man Fallback on Underrun
TEST_F(DeterministicHarnessContractTest, DH_001_DeadManFallbackOnUnderrun) {
  const int64_t kFrameCount = 5;
  const std::string kAssetPath = "test://finite-asset-dh001.mp4";

  harness_->RegisterProducerSpec(kAssetPath, ProducerSpec::Finite(kFrameCount));
  harness_->Start();

  ASSERT_TRUE(harness_->LoadPreview(kAssetPath));
  ASSERT_TRUE(harness_->SwitchToLive());

  for (int i = 0; i < kFrameCount; ++i) {
    harness_->TickProducers();
    harness_->AdvanceToNextFrame();
  }
  harness_->DrainBufferToSink();

  for (int i = 0; i < 3; ++i) {
    harness_->TickProducers();
    harness_->AdvanceToNextFrame();
  }
  harness_->DrainBufferToSink();

  const auto& sink = harness_->GetSink();

  EXPECT_GT(sink.CountBlackFrames(), 0u)
      << "DH-001: Dead-man fallback MUST produce BLACK frames on underrun";
  EXPECT_TRUE(harness_->IsInBlackFallback())
      << "DH-001: Harness MUST report fallback state when producer exhausted";

  auto transition_idx = sink.FindFirstTransitionToBlack();
  EXPECT_TRUE(transition_idx.has_value())
      << "DH-001: There MUST be a LIVE->BLACK transition";

  if (transition_idx.has_value()) {
    EXPECT_EQ(transition_idx.value(), static_cast<size_t>(kFrameCount))
        << "DH-001: BLACK transition MUST occur immediately after last LIVE frame";
  }

  EXPECT_EQ(sink.CountLiveFrames(), static_cast<size_t>(kFrameCount))
      << "DH-001: Should have exactly " << kFrameCount << " LIVE frames";
}

// DH-002: No Autonomous Recovery
TEST_F(DeterministicHarnessContractTest, DH_002_NoAutonomousRecovery) {
  const int64_t kFrameCount = 3;
  const std::string kAssetPath = "test://exhausting-asset-dh002.mp4";

  harness_->RegisterProducerSpec(kAssetPath, ProducerSpec::Finite(kFrameCount));
  harness_->Start();

  ASSERT_TRUE(harness_->LoadPreview(kAssetPath));
  ASSERT_TRUE(harness_->SwitchToLive());

  for (int i = 0; i < kFrameCount; ++i) {
    harness_->TickProducers();
    harness_->AdvanceToNextFrame();
  }
  harness_->DrainBufferToSink();

  ASSERT_TRUE(harness_->IsInBlackFallback())
      << "Precondition: Must be in fallback state";

  const int kIdleTicks = 100;
  for (int i = 0; i < kIdleTicks; ++i) {
    harness_->TickProducers();
    harness_->AdvanceToNextFrame();
  }
  harness_->DrainBufferToSink();

  const auto& sink = harness_->GetSink();

  EXPECT_TRUE(harness_->IsInBlackFallback())
      << "DH-002: AIR MUST stay in BLACK fallback without explicit commands";

  auto transition_idx = sink.FindFirstTransitionToBlack();
  ASSERT_TRUE(transition_idx.has_value());

  EXPECT_TRUE(sink.AssertOnlyBlackFramesAfter(transition_idx.value() - 1))
      << "DH-002: All frames after exhaustion MUST be BLACK";

  size_t live_after_exhaustion = 0;
  for (size_t i = transition_idx.value(); i < sink.FrameCount(); ++i) {
    if (sink.GetFrame(i).source == FrameSource::LIVE_PRODUCER) {
      ++live_after_exhaustion;
    }
  }
  EXPECT_EQ(live_after_exhaustion, 0u)
      << "DH-002: No LIVE frames may appear during autonomous wait";
}

// DH-003: Recovery Only Via Explicit Reassertion
TEST_F(DeterministicHarnessContractTest, DH_003_RecoveryOnlyViaExplicitReassert) {
  const std::string kExhaustingAsset = "test://short-asset-dh003.mp4";
  const std::string kRecoveryAsset = "test://recovery-asset-dh003.mp4";

  harness_->RegisterProducerSpec(kExhaustingAsset, ProducerSpec::Finite(2));
  harness_->RegisterProducerSpec(kRecoveryAsset, ProducerSpec::Infinite());
  harness_->Start();

  ASSERT_TRUE(harness_->LoadPreview(kExhaustingAsset));
  ASSERT_TRUE(harness_->SwitchToLive());

  for (int i = 0; i < 5; ++i) {
    harness_->TickProducers();
    harness_->AdvanceToNextFrame();
  }
  harness_->DrainBufferToSink();

  ASSERT_TRUE(harness_->IsInBlackFallback())
      << "Precondition: Must be in fallback state";

  size_t frames_before_recovery = harness_->GetSink().FrameCount();

  ASSERT_TRUE(harness_->LoadPreview(kRecoveryAsset));
  ASSERT_TRUE(harness_->SwitchToLive());

  EXPECT_FALSE(harness_->IsInBlackFallback())
      << "DH-003: Explicit LoadPreview + SwitchToLive MUST exit BLACK fallback";

  for (int i = 0; i < 5; ++i) {
    harness_->TickProducers();
    harness_->AdvanceToNextFrame();
  }
  harness_->DrainBufferToSink();

  const auto& sink = harness_->GetSink();

  size_t new_live_frames = 0;
  for (size_t i = frames_before_recovery; i < sink.FrameCount(); ++i) {
    if (sink.GetFrame(i).source == FrameSource::LIVE_PRODUCER) {
      ++new_live_frames;
    }
  }

  EXPECT_GT(new_live_frames, 0u)
      << "DH-003: After explicit reassertion, new LIVE frames MUST appear";

  bool found_recovery_frame = false;
  for (size_t i = frames_before_recovery; i < sink.FrameCount(); ++i) {
    if (sink.GetFrame(i).producer_id == kRecoveryAsset) {
      found_recovery_frame = true;
      break;
    }
  }
  EXPECT_TRUE(found_recovery_frame)
      << "DH-003: Recovery frames MUST come from the new producer";
}

// DH-004: End-PTS Clamp Prevents Bleed
TEST_F(DeterministicHarnessContractTest, DH_004_EndPTSClampPreventsBleed) {
  const std::string kAssetPath = "test://clamped-asset-dh004.mp4";
  const int64_t kClampFrames = 5;
  const int64_t kEndPtsUs = kClampFrames * kFrameIntervalUs;

  harness_->RegisterProducerSpec(kAssetPath, ProducerSpec::Clamped(kEndPtsUs));
  harness_->Start();

  ASSERT_TRUE(harness_->LoadPreview(kAssetPath));
  ASSERT_TRUE(harness_->SwitchToLive());

  for (int i = 0; i < 20; ++i) {
    harness_->TickProducers();
    harness_->AdvanceToNextFrame();
  }
  harness_->DrainBufferToSink();

  const auto& sink = harness_->GetSink();

  EXPECT_TRUE(sink.AssertNoLiveFramesBeyondPTS(kEndPtsUs))
      << "DH-004: No LIVE frame may have PTS >= end_pts boundary";

  size_t live_count = sink.CountLiveFrames();
  EXPECT_GE(live_count, 4u)
      << "DH-004: Should have at least 4 LIVE frames before boundary";
  EXPECT_LE(live_count, static_cast<size_t>(kClampFrames))
      << "DH-004: Should have at most " << kClampFrames << " LIVE frames";

  EXPECT_GT(sink.CountBlackFrames(), 0u)
      << "DH-004: BLACK frames MUST appear after end_pts boundary";

  auto transition_idx = sink.FindFirstTransitionToBlack();
  EXPECT_TRUE(transition_idx.has_value())
      << "DH-004: There MUST be a LIVE->BLACK transition at the boundary";
}

// DH-005: End-PTS Does Not Trigger Autonomous Transitions
TEST_F(DeterministicHarnessContractTest, DH_005_EndPTSDoesNotTriggerTransitions) {
  const std::string kClampedAsset = "test://clamped-content-dh005.mp4";
  const std::string kNextAsset = "test://next-content-dh005.mp4";
  const int64_t kEndPtsUs = 3 * kFrameIntervalUs;

  harness_->RegisterProducerSpec(kClampedAsset, ProducerSpec::Clamped(kEndPtsUs));
  harness_->RegisterProducerSpec(kNextAsset, ProducerSpec::Infinite());
  harness_->Start();

  ASSERT_TRUE(harness_->LoadPreview(kClampedAsset));
  ASSERT_TRUE(harness_->SwitchToLive());

  for (int i = 0; i < 10; ++i) {
    harness_->TickProducers();
    harness_->AdvanceToNextFrame();
  }
  harness_->DrainBufferToSink();

  EXPECT_TRUE(harness_->IsInBlackFallback())
      << "DH-005: AIR MUST enter BLACK fallback when end_pts reached";

  const auto& sink = harness_->GetSink();

  bool found_next_frame = false;
  for (const auto& frame : sink.GetFrames()) {
    if (frame.producer_id == kNextAsset) {
      found_next_frame = true;
      break;
    }
  }
  EXPECT_FALSE(found_next_frame)
      << "DH-005: AIR must NOT autonomously load next content";

  auto transition_idx = sink.FindFirstTransitionToBlack();
  if (transition_idx.has_value()) {
    for (size_t i = transition_idx.value(); i < sink.FrameCount(); ++i) {
      EXPECT_EQ(sink.GetFrame(i).source, FrameSource::BLACK)
          << "DH-005: Post-clamp frame " << i << " MUST be BLACK, not from next content";
    }
  }

  EXPECT_EQ(sink.FrameCount(), 10u)
      << "DH-005: Should have total of 10 frames (3 LIVE + 7 BLACK)";
}

// PTS Monotonicity Invariant
TEST_F(DeterministicHarnessContractTest, DH_INVARIANT_PTSMonotonicity) {
  const std::string kAssetPath = "test://monotonic-test.mp4";

  harness_->RegisterProducerSpec(kAssetPath, ProducerSpec::Finite(10));
  harness_->Start();

  ASSERT_TRUE(harness_->LoadPreview(kAssetPath));
  ASSERT_TRUE(harness_->SwitchToLive());

  for (int i = 0; i < 15; ++i) {
    harness_->TickProducers();
    harness_->AdvanceToNextFrame();
  }
  harness_->DrainBufferToSink();

  const auto& sink = harness_->GetSink();

  EXPECT_TRUE(sink.AssertMonotonicPTS())
      << "INVARIANT: PTS MUST be strictly monotonically increasing across all frames";
}

}  // namespace retrovue::tests::contracts
