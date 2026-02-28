# INV-NO-FRAME-AUTHORITY-VACUUM-001 (Swap-commit video precondition)

**Owner:** AIR
**Classification:** Enforcement evidence (derived)
**Parent invariant:** INV-CONTINUOUS-FRAME-AUTHORITY-001
**Architectural model:** [ADR-013 — Seam Resolution Model](../../../architecture/decisions/ADR-013-Seam-Resolution-Model.md)

## Derivation / Scope

This document defines the swap-commit video precondition — the mechanism by which `INV-CONTINUOUS-FRAME-AUTHORITY-001` is upheld at segment transition boundaries. It does not define an independent behavioral outcome. The outcome it serves — exactly one segment holds frame authority and can provide video at every tick — is defined by the parent invariant. ADR-013 Case B ("incoming segment is eligible") encodes the same semantic at the architectural level. This document specifies the eligibility gate that prevents authority transfer to a segment that cannot provide video.

## Purpose

Protects `LAW-LIVENESS` at the segment transition boundary. `INV-CONTINUOUS-FRAME-AUTHORITY-001` requires exactly one segment to hold frame authority and be capable of providing a video frame at every emission tick. This invariant enforces the precondition: a SEGMENT_TAKE MUST NOT be committed unless the incoming segment can provide video frames. Without this gate, authority transfers to a segment with video depth=0, creating a frame authority vacuum that manifests as black output.

## Behavioral Guarantee

A segment transition MUST NOT be committed unless the incoming segment can provide video frames for immediate emission. Content segments prove video capability via buffer depth. PAD segments prove video capability via on-demand production (`pad_producer_->VideoFrame()`). The swap eligibility gate MUST ensure the incoming segment can produce video; the mechanism of proof differs by segment type.

## Formal Definition

Let `TAKE(T)` be a SEGMENT_TAKE commit at tick `T`. Let `incoming(T)` be the segment receiving frame authority. Let `V(S)` be the video buffer depth in frames of segment `S`. Let `MIN_V` be the minimum swap-eligible video depth (shared across all segment types).

```
Precondition (tick-loop entry):
  BEFORE first emission tick:
    V(active) >= 1

Precondition (swap-commit):
  forall TAKE(T):
    V(incoming(T)) >= MIN_V

Postcondition (swap-commit):
  AFTER TAKE(T):
    active(T+1) = incoming(T)
    AND V(active(T+1)) >= 1
```

If the precondition is not satisfiable, the SEGMENT_TAKE MUST NOT be committed. The active segment retains authority. If the active segment also cannot provide frames, this is an `INV-CONTINUOUS-FRAME-AUTHORITY-001` violation — not a reason to bypass this precondition.

## Authority Model

The segment swap eligibility gate is the sole enforcement point. No emergency or forced swap path may transfer authority to a segment that cannot provide video. Content segments prove capability via buffer depth; PAD proves capability via on-demand production.

## Boundary / Constraints

- Content segments MUST satisfy minimum video buffer depth before swap eligibility.
- PAD segments provide video on-demand; the buffer-based video depth gate does not apply.
- All segment types MUST satisfy minimum audio depth for continuity at the seam.
- No fallback or emergency swap mechanism may transfer authority to a segment that cannot provide video.

## Violation Condition

Any of the following constitutes a violation:

- A SEGMENT_TAKE is committed while `V(incoming) < MIN_V`.
- The tick loop begins with `V(active) < 1`.
- A forced swap transfers authority to a segment with zero video frames.

Violations MUST be logged with tag `INV-NO-FRAME-AUTHORITY-VACUUM-001-VIOLATED`. The system MUST NOT silently emit black frames as a consequence of a frame authority vacuum; a violation MUST halt emission or trigger session-level error recovery rather than produce undefined output.

## Enforcement Surface

The segment swap eligibility evaluation. The video depth check MUST be applied at the same gate and with the same threshold as other swap preconditions, for all segment types uniformly.

## Non-Goals

- This invariant does not prescribe how video frames are produced or buffered.
- This invariant does not govern audio swap preconditions.
- This invariant does not define valid frame content (that is `LAW-DECODABILITY`).
- This invariant does not specify fill strategy, decode timing, or preroll duration.

## Derives From

`LAW-LIVENESS`, `LAW-SWITCHING`, `INV-CONTINUOUS-FRAME-AUTHORITY-001`

## Evidence Tests (required)

These tests remain mandatory coverage for the parent invariant `INV-CONTINUOUS-FRAME-AUTHORITY-001`. They validate the swap eligibility gate that prevents frame-authority vacuum at segment transitions.

- `pkg/air/tests/contracts/BlockPlan/NoFrameAuthorityVacuumContractTests.cpp` (SwapCommitVideoPreCondition: PadEligibleWithZeroVideoFramesBecauseOnDemand, PadWithSufficientVideoFramesEligible, ContentAndPadBothEligibleWhenDepthsSufficient, ContentWithZeroVideoFramesNotEligible, PadWithVideoButInsufficientAudioNotEligible)

## Enforcement Evidence

- `PipelineManager::IsIncomingSegmentEligibleForSwap` — Content: requires `audio >= MIN_A && video >= MIN_V`. PAD: requires `audio >= MIN_A` only (video on-demand).
- `PipelineManager::GetIncomingSegmentState` — `!is_pad` guard on content B branch ensures PAD segments use PAD-specific path even when stale content B buffers exist.
