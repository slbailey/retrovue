# Test Matrix: AIR Frame Authority Invariants

**Scope:** Deterministic validation of frame authority invariants governing segment swap eligibility, video depth preconditions, and PAD readiness in the AIR playout engine.

**Authoritative inputs:**
- `docs/contracts/laws/LAW-LIVENESS.md`
- `docs/contracts/laws/LAW-SWITCHING.md`
- `docs/contracts/invariants/air/INV-CONTINUOUS-FRAME-AUTHORITY-001.md`
- `docs/contracts/invariants/air/INV-NO-FRAME-AUTHORITY-VACUUM-001.md`
- `docs/contracts/invariants/air/INV-PAD-VIDEO-READINESS-001.md`
- `docs/contracts/invariants/air/INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001.md`

**Test framework:** Google Test (GTest). All contract tests are C++.

**Test executable:** `blockplan_contract_tests` (defined in `pkg/air/CMakeLists.txt`)

**Run command:** `ctest --test-dir pkg/air/build -R blockplan_contract --output-on-failure`

---

## 1. Purpose

This matrix validates that the AIR segment swap mechanism upholds frame authority guarantees without depending on real-time progression, real media decoding, or encoder output. Every test maps to at least one invariant. Every invariant is covered by at least one test.

---

## 2. Deterministic Execution Model

| Constraint | Rule |
|---|---|
| **Clock** | No wall-clock reads. Tick values are injected as integer parameters. |
| **Media** | No ffmpeg, no file decoding. PadProducer generates synthetic black/silence. |
| **Encoder** | No encoding. Tests validate swap eligibility decisions, not output bytes. |
| **Logger** | `Logger::SetErrorSink` callback captures violation tags for assertion. |
| **State** | All state is constructed via public constructors and static helpers. No private member access. |

---

## 3. Fixtures and Test Doubles

### 3.1 Logger Capture

All frame authority contract tests use a logger capture fixture:

```cpp
class ContractTestBase : public ::testing::Test {
 protected:
  void SetUp() override {
    captured_errors_.clear();
    Logger::SetErrorSink([this](const std::string& line) {
      captured_errors_.push_back(line);
    });
  }
  void TearDown() override { Logger::SetErrorSink(nullptr); }

  bool HasViolationTag(const std::string& tag) const {
    for (const auto& line : captured_errors_) {
      if (line.find(tag) != std::string::npos) return true;
    }
    return false;
  }

  std::vector<std::string> captured_errors_;
};
```

### 3.2 IncomingState

Swap eligibility tests construct `IncomingState` directly:

```cpp
IncomingState state;
state.incoming_audio_ms = 500;
state.incoming_video_frames = 0;
state.is_pad = true;
state.segment_type = SegmentType::kPad;
```

### 3.3 PadProducer

PAD readiness tests construct `PadProducer` via its public constructor:

```cpp
PadProducer pp(/*width=*/1920, /*height=*/1080, /*fps=*/30, /*audio_channels=*/1);
```

---

## 4. Invariant Coverage

### INV-CONTINUOUS-FRAME-AUTHORITY-001

**Test file:** `pkg/air/tests/contracts/BlockPlan/FrameAuthorityVacuumContractTests.cpp`

| Test | Scenario | Expected |
|---|---|---|
| NoViolationWhenActiveHasFrames | Active video depth > 0, successor empty | No violation |
| ViolationWhenActiveEmptyNoIncoming | Active depth=0, no successor | Violation tag emitted |
| ViolationWhenActiveEmptySuccessorNotSeamReady | Active depth=0, successor depth=0 | Violation tag emitted |
| ViolationWhenActiveEmptySwapDeferredDespiteSeamReady | Active depth=0, successor seam-ready, swap deferred | Violation tag emitted |
| EnforcementAllowsDeferWhenActiveHasFrames | Active depth > 0 | Action = kDefer |
| EnforcementForceExecuteWhenSuccessorSeamReady | Active depth=0, successor has video | Action = kForceExecute |
| EnforcementExtendActiveWhenNoIncoming | Active depth=0, no incoming | Action = kExtendActive |
| EnforcementExtendActiveWhenSuccessorNotSeamReady | Active depth=0, successor depth=0 | Action = kExtendActive |

### INV-NO-FRAME-AUTHORITY-VACUUM-001

**Test file:** `pkg/air/tests/contracts/BlockPlan/NoFrameAuthorityVacuumContractTests.cpp`

| Test | Scenario | Expected |
|---|---|---|
| PadEligibleWithZeroVideoFramesBecauseOnDemand | PAD incoming with audio=500ms, video=0 | Swap eligible (PAD video on-demand) |
| PadWithSufficientVideoFramesEligible | PAD incoming with audio=500ms, video>=MIN_V | Swap eligible |
| ContentAndPadBothEligibleWhenDepthsSufficient | Content and PAD with audio=500ms, video=2 | Both eligible |
| ContentWithZeroVideoFramesNotEligible | Content with audio=500ms, video=0 | Swap not eligible |
| PadWithVideoButInsufficientAudioNotEligible | PAD with audio=100ms, video=2 | Swap not eligible (audio required) |

### INV-PAD-VIDEO-READINESS-001

**Test file:** `pkg/air/tests/contracts/BlockPlan/PadVideoReadinessContractTests.cpp`

| Test | Scenario | Expected |
|---|---|---|
| PadEligibleWithZeroVideoFramesBecauseOnDemand | PAD with audio=500ms, video=0 | Swap-eligible (video on-demand) |
| PadEligibleWithSufficientVideoAndAudio | PAD with audio>=MIN_A, video>=MIN_V | Swap-eligible |
| PadAudioOnlySufficientBecauseVideoOnDemand | PAD with audio=1000ms, video=0 | Swap-eligible (audio sufficient for PAD) |
| PadWithInsufficientAudioNotEligible | PAD with audio=100ms, video=5 | Not swap-eligible (audio required) |
| ContentStillRequiresVideoDepth | Content with audio=500ms, video=0 | Not swap-eligible |

### INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001

**Test file:** `pkg/air/tests/contracts/BlockPlan/AtomicAuthorityTransferContractTests.cpp`

| Test | Scenario | Expected |
|---|---|---|
| NoViolationWhenFrameMatchesAuthority | active=2, origin=2 | No violation |
| ViolationWhenFrameFromPreviousSegmentAfterSwap | active=1, origin=0 | Violation (stale_frame_bleed) |
| ViolationWhenFrameOriginIsNull | active=0, origin=-1 | Violation (frame_origin_null) |
| ViolationWhenFrameOriginIsOldSegmentDespiteActiveChanged | active=1, origin=0 at swap boundary | Violation (stale_frame_bleed) |
| ContentToPadSeamDoesNotEmitStaleContentFrame | PAD seam: active=1, origin=1 (correct) then origin=0 (wrong) | Pass then violation |
| ContentToPadSeamForcesPadEvenWhenOldBufferHasFrames | Old content buffer has frames, PAD override | PAD origin prevails |
| ContentToContentSeamMayUseHoldIfAllowed | Content hold deferred swap, active=0, origin=0 | No violation (hold legitimate) |
| PadSeamWithStaleBBuffersMustNotDeferSwap | PAD with stale B (audio=500, video=0, is_pad=true) | Swap eligible |
| PadSeamDeferredSwapCausesStaleFrameBleed | Compound: gate defers → active=1 but origin=2 → violation | FAIL before fix, PASS after |
| SafetyNetRaceWithoutRestampViolates | Fill-thread race: hold from PAD (origin=1), FORCE_EXECUTE swaps to CONTENT (active=2) | Violation (stale_frame_bleed) without restamp |
| SafetyNetRestampCorrectionPassesAuthorityCheck | Same race, restamp applied: origin corrected to 2 | No violation |
| ContentSeamOverrideSuccessMatchesAuthority | CONTENT_SEAM_OVERRIDE popped content frame, swap fires | No violation |
| ContentSeamOverrideWithoutSwapViolates | Content frame emitted but swap didn't fire (should never happen) | Violation (stale_frame_bleed) |

**Test file:** `pkg/air/tests/contracts/BlockPlan/ForceExecutePadToContentBleedContractTests.cpp`

| Test | Scenario | Expected |
|---|---|---|
| PadToContentSeamMustNotEmitStaleFrame | Block [CONTENT, PAD, CONTENT]; PAD→CONTENT via FORCE_EXECUTE | No stale_frame_bleed violation |

**Test file:** `pkg/air/tests/contracts/BlockPlan/NormalCascadeSeamBleedContractTests.cpp`

| Test | Scenario | Expected |
|---|---|---|
| PadToContentSeamWithBufferedPadMustNotBleed | Block [CONTENT(1500ms), PAD(200ms), CONTENT(1500ms)]; short PAD with buffered frames; normal cascade seam | No stale_frame_bleed violation |

---

## 5. Test Scenario: PAD Seam Stale-B-Buffer Race (Integration)

The following scenario deterministically reproduces the stale_frame_bleed bug at CONTENT->PAD seams. It validates `INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001`, `INV-NO-FRAME-AUTHORITY-VACUUM-001`, and `INV-PAD-VIDEO-READINESS-001` together.

**Bug scenario (before fix):**
1. Content segment 0 hits EOF, `take_segment` fires for segment 1->2 (PAD).
2. `pad_seam_this_tick=true` — frame selection picks `pad_producer_->VideoFrame()` with `frame_origin_segment_id=2`.
3. `GetIncomingSegmentState(2)` returns stale content B buffer depths (video_frames=0) instead of PAD path.
4. `IsIncomingSegmentEligibleForSwap` rejects (0 < kMinSegmentSwapVideoFrames=2) — swap deferred.
5. `current_segment_index_` stays at 1. Authority check: active=1, origin=2 — VIOLATED.

**Fix:**
1. `GetIncomingSegmentState`: Guard content B branch on `!is_pad` so PAD always uses PAD path.
2. `IsIncomingSegmentEligibleForSwap`: Exempt PAD from video-depth gate (audio only).
3. SEGMENT POST-TAKE: `force_swap_for_pad_seam` prevents deferral when PAD frame already selected.

**Test (compound atomicity proof — `PadSeamDeferredSwapCausesStaleFrameBleed`):**
1. Construct `IncomingState` with `is_pad=true`, `incoming_audio_ms=500`, `incoming_video_frames=0`.
2. Evaluate swap eligibility. If not eligible (before fix):
   - Call `EmittedFrameMatchesAuthority(tick=800, active=1, origin=2)`.
   - Proves violation fires (`reason=stale_frame_bleed`).
   - Test FAILs — gate should not have deferred PAD swap.
3. If eligible (after fix):
   - Swap proceeds, active becomes 2, origin=2.
   - `EmittedFrameMatchesAuthority(tick=800, active=2, origin=2)` passes.
   - No violation. Test passes.

## 6. Test Scenario: PAD→CONTENT Force-Execute Origin Bleed (Integration)

The following scenario reproduces the stale_frame_bleed bug at PAD→CONTENT seams via `FORCE_EXECUTE_DUE_TO_FRAME_AUTHORITY`. It validates `INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001`.

**Bug scenario (before fix):**
1. Block = [CONTENT(0), PAD(1), CONTENT(2)]. Content segment 0 hits EOF.
2. CONTENT→PAD seam: `pad_seam_this_tick=true`, `PAD_SEAM_OVERRIDE` fires. Swap to segment 1. `last_good_origin_segment_ = 1`.
3. During PAD: `PAD_B_VIDEO_BUFFER` has 0 frames (`first_frame_fail` — PAD has no decoder). Frames emitted via `pad_producer_->VideoFrame()` with `decision=kPad`, `frame_origin_segment_id=-2` (skip check).
4. PAD segment 1 hits seam. `pad_seam_this_tick=false` (target is CONTENT, not PAD).
5. Frame cascade: PAD buffer empty → `decision=kHold`, `frame_origin_segment_id = last_good_origin_segment_ = 1`.
6. Frame encoded (line 1892) with origin=1.
7. `FORCE_EXECUTE_DUE_TO_FRAME_AUTHORITY` fires: `active_video_depth=0`, successor has frames.
8. `PerformSegmentSwap` advances `current_segment_index_` from 1 to 2.
9. Post-swap check: `active_segment_id=2`, `frame_origin_segment_id=1` — VIOLATED.

**Fix (primary — CONTENT_SEAM_OVERRIDE):**
Symmetric to `PAD_SEAM_OVERRIDE`. At the PAD→CONTENT seam tick, `EnsureIncomingBReadyForSeam` is promoted to run BEFORE frame selection (normally POST-TAKE). The `CONTENT_SEAM_OVERRIDE` cascade branch pops a genuine content frame from `segment_b_video_buffer_` with `frame_origin_segment_id = content_seam_to_seg`. `force_swap_for_content_seam` ensures the swap proceeds. Logged as `CONTENT_SEAM_OVERRIDE` and `FORCE_SWAP_FOR_CONTENT_SEAM`.

**Fix (safety net — restamp):**
If the content seam override fails (segment B empty at frame-selection time due to fill-thread timing), `FORCE_EXECUTE_DUE_TO_FRAME_AUTHORITY` fires in POST-TAKE. After `PerformSegmentSwap`, `frame_origin_segment_id` and `last_good_origin_segment_` are re-stamped to `current_segment_index_`. Logged as `FORCE_EXECUTE_ORIGIN_RESTAMP_SAFETY_NET`. This is defence-in-depth, not the primary mechanism.

**Test (integration — `PadToContentSeamMustNotEmitStaleFrame`):**
1. Feed block [CONTENT(1500ms), PAD(500ms), CONTENT(1500ms)] to `PipelineManager`.
2. Run tick loop through all three segments.
3. Capture error logs via `Logger::SetErrorSink`.
4. Assert no `INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001-VIOLATED` with `reason=stale_frame_bleed`.
5. Before fix: FAILS (violation at PAD→CONTENT boundary). After fix: PASSES.
6. Expected mechanism: `CONTENT_SEAM_OVERRIDE` pops genuine content frame from segment B. `FORCE_SWAP_FOR_CONTENT_SEAM` drives the swap. No restamp needed.

## 7. Test Scenario: Normal Cascade PAD→CONTENT Seam Bleed (Integration)

The following scenario reproduces the stale_frame_bleed bug at PAD→CONTENT seams via the normal frame cascade. It validates `INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001`.

**Bug scenario (before fix):**
1. Block = [CONTENT(0), PAD(1), CONTENT(2)]. PAD segment is short (200ms).
2. CONTENT→PAD seam: `pad_seam_this_tick=true`, `PAD_SEAM_OVERRIDE` fires. Swap to segment 1.
3. During PAD: pad_b buffer still has pre-primed frames (`a_depth > 0`).
4. PAD segment 1 hits seam. `pad_seam_this_tick=false` (target is CONTENT, not PAD).
5. `CONTENT_SEAM_OVERRIDE` does not fire because `a_depth > 0` (PAD buffer has frames).
6. `FORCE_EXECUTE` does not fire because `active_video_depth > 0` (PAD buffer).
7. v_src selection: `take_segment && segment_b_video_buffer_` — B has at least 1 primed frame, so `v_src = segment_b_video_buffer_`. No eligibility check.
8. Normal cascade pops from B: `frame_origin_segment_id = 2` (incoming CONTENT).
9. POST-TAKE: B lacks 500ms audio → swap deferred. `current_segment_index_ = 1`.
10. Authority check: `origin(2) != active(1)` — VIOLATED.

**Fix (primary — v_src eligibility gate):**
At segment seam ticks, v_src checks `IsIncomingSegmentEligibleForSwap` before reading from `segment_b_video_buffer_`. If not eligible, v_src falls back to `video_buffer_` (active segment). The frame carries outgoing origin, swap defers, and `origin(T) = active(T)`.

**Fix (safety net — frame-origin consistency gate):**
In POST-TAKE, after eligibility is evaluated, a deferral branch checks whether `frame_origin_segment_id == current_segment_index_` (outgoing) when no force flag is active. If so, the swap defers. This catches the fill-thread race where B becomes eligible between v_src selection and POST-TAKE.

**Test (integration — `PadToContentSeamWithBufferedPadMustNotBleed`):**
1. Feed block [CONTENT(1500ms), PAD(200ms), CONTENT(1500ms)] to `PipelineManager`.
2. Run tick loop through all three segments.
3. Capture error logs via `Logger::SetErrorSink`.
4. Assert no `INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001-VIOLATED` with `reason=stale_frame_bleed`.
5. Before fix: FAILS (violation at PAD→CONTENT boundary). After fix: PASSES.
