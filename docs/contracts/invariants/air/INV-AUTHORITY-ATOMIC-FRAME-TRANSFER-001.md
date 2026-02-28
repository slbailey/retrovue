# INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001 (Atomic frame-authority transfer)

**Owner:** AIR

## Purpose

Protects `LAW-LIVENESS` and `LAW-SWITCHING` at the emission boundary of an authority transfer. `INV-CONTINUOUS-FRAME-AUTHORITY-001` guarantees that exactly one segment holds frame authority at every tick. This invariant strengthens that guarantee: when authority transfers from segment A to segment B at tick T, the frame emitted at tick T MUST originate from segment B. A stale frame from segment A emitted after authority has transferred constitutes a one-frame bleed — a visible glitch where the encoder re-uses a previously decoded surface from a segment that is no longer authoritative. This invariant prevents that bleed.

## Behavioral Guarantee

When frame authority transfers from segment A to segment B at tick T, the frame emitted at tick T MUST originate from segment B. There MUST NOT exist any tick where the emitted frame originates from a segment that is not `active(T)`. A previously decoded surface from the old segment MUST NOT be reused after authority transfer. The encoder MUST NOT re-emit the last frame of a prior segment during the first tick of new authority.

## Formal Definition

Let `T` be any emission tick during a live session. Let `active(T)` be the segment currently holding frame authority at tick `T`. Let `origin(T)` be the segment that produced the frame emitted at tick `T`.

```
Invariant:
  forall T in session_ticks:
    origin(T) = active(T)

Transfer boundary:
  IF active(T) != active(T-1)
  THEN origin(T) MUST = active(T)
  AND  origin(T) MUST != active(T-1)

Prohibited conditions:
  NOT EXISTS T where:
    origin(T) != active(T)
  NOT EXISTS T where:
    active(T) != active(T-1) AND origin(T) = active(T-1)
```

The invariant is segment-type agnostic (CONTENT, PAD, FILLER, EMERGENCY, or any future classification) and transition-type agnostic (scheduled seam, forced switch, underrun recovery).

## Authority Model

The PipelineManager emission path is the sole enforcement point. Frame origin is determined at the moment a frame is selected for encoding. No other subsystem may inject, substitute, or replay a frame from a non-authoritative segment.

## Boundary / Constraints

- The frame emitted at every tick MUST originate from the segment that holds frame authority at that tick. No exceptions.
- When authority transfers at tick T, the frame at tick T MUST originate from the newly authoritative segment. Not the predecessor.
- A previously decoded video surface from a prior segment MUST NOT be reused after authority transfer, even if it is the most recent frame in the encoder's reference.
- This invariant applies regardless of segment type: content, pad, filler, emergency, synthetic, or any future segment classification.
- This invariant holds across all transition types: scheduled boundary, early termination, forced switch, and underrun recovery.
- The invariant operates at emission tick granularity. Sub-tick or field-level authority is not modeled.
- When `CONTENT_SEAM_OVERRIDE` fires (a genuine content frame was popped from segment B), `PerformSegmentSwap` MUST execute on the same tick. If the override fires but the swap does not, the emitted frame and the authority diverge — this MUST be logged as `INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001-VIOLATED` with `reason=content_seam_override_without_swap`.
- A segment swap MUST NOT commit at tick T if the frame emitted at tick T originates from the outgoing segment and no override path (`PAD_SEAM_OVERRIDE`, `CONTENT_SEAM_OVERRIDE`, `FORCE_EXECUTE`) is active. The swap MUST defer until a tick where the emitted frame originates from the incoming segment. This prevents a race where the incoming segment becomes eligible between v_src selection and POST-TAKE while the emitted frame still carries outgoing origin.
- The origin re-stamp safety net (`FORCE_EXECUTE_ORIGIN_RESTAMP_SAFETY_NET`) is permitted ONLY when ALL of the following hold: (1) `FORCE_EXECUTE_DUE_TO_FRAME_AUTHORITY` fired (active video depth is 0 and successor has video frames), (2) `CONTENT_SEAM_OVERRIDE` did NOT pop a content frame on this tick (segment B was empty at frame-selection time), (3) `PerformSegmentSwap` executed on this tick. The safety net MUST log at WARN level with tick, old origin, new origin, and `content_seam_override_attempted`. Any firing outside these conditions MUST be treated as a bug, not a feature.

## Violation Condition

Any of the following constitutes a violation:

- A frame is emitted at tick T where `origin(T) != active(T)`.
- Authority transfers from A to B at tick T, but the emitted frame at tick T originates from A.
- The frame origin segment ID is unset or invalid at any emission tick.
- The encoder re-emits the last decoded frame of segment A during the first tick where segment B is authoritative.

Violations MUST be logged with tag `INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001-VIOLATED`.

## Architectural Model

[ADR-013 — Seam Resolution Model](../../../architecture/decisions/ADR-013-Seam-Resolution-Model.md) formalizes the same-tick authority semantics that enforce this invariant. Cases A, B, and C define the allowed seam outcomes; the Race Handling Rule and Prohibited Behaviors constrain the swap decision to guarantee `origin(T) = active(T)`.

## Enforcement Surface

The PipelineManager emission path — specifically, the code that selects a video frame for encoding at each tick. The check occurs after the authority decision (which segment is active) and before the frame is committed to the encoder.

## Non-Goals

- This invariant does not prescribe how the incoming segment achieves readiness (that is `INV-CONTINUOUS-FRAME-AUTHORITY-001`).
- This invariant does not define valid frame content (that is `LAW-DECODABILITY`).
- This invariant does not govern audio continuity at transfer boundaries (that is `INV-AUDIO-CONTINUITY-NO-DROP`).
- This invariant does not define when authority transfer should occur — only that once it occurs, the emitted frame MUST match.
- This invariant does not prescribe swap mechanism internals or preroll strategy.

## Rationale (Broadcast Context)

In broadcast television, a routing switcher crosspoint change is instantaneous: the first frame after the switch originates from the new source. There is no "last frame hold" from the previous source after the crosspoint moves. If the switcher commits to source B at frame T, frame T comes from B. A software playout engine MUST enforce the same atomic transfer: the frame selection at tick T MUST reflect the authority decision at tick T, not a stale decode surface from tick T-1.

## Derives From

`LAW-LIVENESS`, `LAW-SWITCHING`

## Required Tests

- `pkg/air/tests/contracts/BlockPlan/AtomicAuthorityTransferContractTests.cpp` (AtomicAuthorityTransferTest: NoViolationWhenFrameMatchesAuthority, ViolationWhenFrameFromPreviousSegmentAfterSwap, ViolationWhenFrameOriginIsNull, ViolationWhenFrameOriginIsOldSegmentDespiteActiveChanged, ContentToPadSeamDoesNotEmitStaleContentFrame, ContentToPadSeamForcesPadEvenWhenOldBufferHasFrames, ContentToContentSeamMayUseHoldIfAllowed, PadSeamWithStaleBBuffersMustNotDeferSwap, PadSeamDeferredSwapCausesStaleFrameBleed, SafetyNetRaceWithoutRestampViolates, SafetyNetRestampCorrectionPassesAuthorityCheck, ContentSeamOverrideSuccessMatchesAuthority, ContentSeamOverrideWithoutSwapViolates)
- `pkg/air/tests/contracts/BlockPlan/ForceExecutePadToContentBleedContractTests.cpp` (ForceExecutePadToContentBleedTest: PadToContentSeamMustNotEmitStaleFrame)
- `pkg/air/tests/contracts/BlockPlan/NormalCascadeSeamBleedContractTests.cpp` (NormalCascadeSeamBleedTest: PadToContentSeamWithBufferedPadMustNotBleed)

## Enforcement Evidence

- `PipelineManager::EmittedFrameMatchesAuthority` — static check; returns false and emits `INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001-VIOLATED` via `Logger::Error` when `frame_origin_segment_id != active_segment_id` or `frame_origin_segment_id < 0`.
- **Wired at emission boundary:** Called in `PipelineManager::Run()` after the segment POST-TAKE section, where `current_segment_index_` reflects the tick's final authority state. Active for content (`kContentA`), hold/repeat, and PAD seam ticks. Skipped for block swaps (`take_b`) and non-seam pad/standby/contentB decisions (origin == -2).
- **PAD seam enforcement (`pad_seam_this_tick`):** Computed early in the tick loop after `take_segment` is determined. When the target segment is PAD, `pad_seam_this_tick = true` forces the highest-priority cascade branch: `chosen_video = &pad_producer_->VideoFrame()` with `frame_origin_segment_id = pad_seam_to_seg`. This override fires BEFORE all other cascade paths (cadence repeat, content pop, hold, underflow) — no branch can emit a stale content frame at a CONTENT→PAD seam. Logged as `PAD_SEAM_OVERRIDE`.
- **Frame-attached origin:** `VideoBufferFrame::segment_origin_id` stamped by `VideoLookaheadBuffer` fill thread from `SetSegmentOriginId`. Segment B buffers are stamped at creation in `EnsureIncomingBReadyForSeam` and `PerformSegmentSwap`. PAD seam path stamps `pad_seam_to_seg` directly. Hold/repeat paths use `last_good_origin_segment_` (state fallback).
- Contract tests (`AtomicAuthorityTransferTest`): 9 cases — match (no violation), stale frame bleed, null origin, old segment despite active changed, PAD seam correct origin, PAD seam rejects stale content origin, content-to-content hold deferred swap (control), PAD seam with stale B buffers must not defer swap, PAD seam deferred swap causes stale frame bleed (compound atomicity proof).
- **PAD seam stale-B-buffer fix:** `GetIncomingSegmentState` guards content B branch on `!is_pad` so PAD segments always use the PAD-specific path even when stale content B buffers exist. `IsIncomingSegmentEligibleForSwap` exempts PAD from the video-depth gate (PAD provides video on-demand via `pad_producer_->VideoFrame()`). SEGMENT POST-TAKE adds `force_swap_for_pad_seam` to prevent swap deferral when a PAD frame was already selected (`pad_seam_this_tick && decision == kPad`).
- **Content seam enforcement (`content_seam_override_this_tick`):** Symmetric to PAD seam enforcement. When `take_segment` targets a CONTENT segment and the active segment (PAD) has 0 buffered video, `EnsureIncomingBReadyForSeam` is promoted to run BEFORE frame selection (normally runs in POST-TAKE). The content seam override cascade branch pops a genuine content frame from `segment_b_video_buffer_`, ensuring `origin(T) = active(T)` at the emission boundary without post-hoc metadata correction. `force_swap_for_content_seam` in POST-TAKE ensures the swap proceeds after a content frame was emitted. Logged as `CONTENT_SEAM_OVERRIDE` and `FORCE_SWAP_FOR_CONTENT_SEAM`.
- **Force-execute origin re-stamp (safety net):** When `FORCE_EXECUTE_DUE_TO_FRAME_AUTHORITY` fires and the content seam override did NOT pop a content frame (fill-thread race: segment B was empty at frame-selection time but had frames pushed by POST-TAKE), `frame_origin_segment_id` and `last_good_origin_segment_` are re-stamped to `current_segment_index_` after `PerformSegmentSwap`. This is a defence-in-depth safety net — not the primary mechanism. Its firing indicates a fill-thread timing edge case. Logged as `FORCE_EXECUTE_ORIGIN_RESTAMP_SAFETY_NET`. Integration test: `ForceExecutePadToContentBleedTest::PadToContentSeamMustNotEmitStaleFrame` (block [CONTENT, PAD, CONTENT]).
- **v_src eligibility gate (normal cascade):** At segment seam ticks, the v_src selection for the normal cascade checks `IsIncomingSegmentEligibleForSwap` before reading from `segment_b_video_buffer_`. If the incoming segment is not eligible, v_src falls back to `video_buffer_` (active segment). This prevents the normal cascade from popping a frame with incoming origin when the swap will be deferred in POST-TAKE. Logged as `SEAM_VSRC_GATE`.
- **Frame-origin consistency gate (POST-TAKE):** After eligibility is evaluated in POST-TAKE, a deferral branch checks whether `frame_origin_segment_id == current_segment_index_` (outgoing) when no force flag is active. If so, the swap is deferred to the next tick — committing would advance `current_segment_index_` while the emitted frame carries outgoing origin, violating `origin(T) = active(T)`. This catches the race where the fill thread pushes enough audio between Phase 1 (v_src selection) and Phase 4 (POST-TAKE). Logged as `SEGMENT_SWAP_DEFERRED reason=frame_origin_gate`. Integration test: `NormalCascadeSeamBleedTest::PadToContentSeamWithBufferedPadMustNotBleed` (block [CONTENT, PAD, CONTENT]).
- **Derived enforcement evidence — PAD video readiness:** [INV-PAD-VIDEO-READINESS-001](INV-PAD-VIDEO-READINESS-001.md) specifies the PAD-specific eligibility rule that supports ADR-013 Case C (override commit for PAD transitions). PAD is exempt from the video buffer depth gate because it provides video on-demand; this ensures PAD seam overrides are never incorrectly deferred by a video-depth check. Tests: `PadVideoReadinessContractTests.cpp` (5 cases validating PAD eligibility).
