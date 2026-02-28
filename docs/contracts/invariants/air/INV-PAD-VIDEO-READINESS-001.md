# INV-PAD-VIDEO-READINESS-001 (PAD video readiness)

**Owner:** AIR
**Classification:** Enforcement evidence (derived)
**Parent invariants:** INV-CONTINUOUS-FRAME-AUTHORITY-001, INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001
**Architectural model:** [ADR-013 — Seam Resolution Model](../../../architecture/decisions/ADR-013-Seam-Resolution-Model.md)

## Derivation / Scope

This document defines the PAD-specific specialization of the swap eligibility gate. It does not define an independent behavioral outcome. The outcomes it serves — no frame-authority vacuum when PAD is the incoming segment (`INV-CONTINUOUS-FRAME-AUTHORITY-001`) and no stale frame bleed at CONTENT→PAD seams (`INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001`) — are defined by the parent invariants. ADR-013 Case C (override commit for PAD transitions) requires PAD to provide video on-demand; this document specifies the eligibility rule that makes that possible.

## Purpose

Strengthens `LAW-LIVENESS` and `INV-CONTINUOUS-FRAME-AUTHORITY-001` for the PAD segment type. PAD is a first-class TAKE-selectable source that produces black video and silent audio. PAD provides video on-demand via `pad_producer_->VideoFrame()` — a synchronous call that always returns a valid frame. PAD has no video buffer to fill, so the buffer-based video depth gate does not apply. PAD swap eligibility requires audio depth only.

## Behavioral Guarantee

PAD MUST be capable of providing a video frame on-demand at the moment of swap. PAD swap eligibility MUST require audio depth (for continuity at the seam) but MUST NOT require video buffer depth. The PAD producer MUST be in a state where it can produce video frames before PAD is swap-eligible.

## Formal Definition

Let `A(PAD)` be the PAD audio buffer depth in milliseconds. Let `MIN_A` be the minimum swap-eligible audio depth.

```
Precondition (PAD swap eligibility):
  swap_eligible(PAD) = true ONLY IF
    A(PAD) >= MIN_A
    AND pad_producer_ is capable of producing video frames

Precondition (PAD producer):
  PAD producer MUST be in a state where it can produce video frames
  BEFORE PAD is swap-eligible.
  A PAD producer that cannot produce frames (no block assigned,
  EMPTY state, or equivalent) MUST NOT be used as a fill source.
```

PAD swap eligibility MUST NOT require video buffer depth. The video-depth gate applies to content segments (which prove video capability via buffer depth) but not to PAD (which proves video capability via on-demand production).

## Authority Model

The PAD readiness evaluation is the sole enforcement point. PAD swap eligibility MUST be evaluated with the audio depth gate but exempt from the buffer-based video depth gate.

## Boundary / Constraints

- PAD swap eligibility MUST require audio depth for continuity at the seam.
- PAD swap eligibility MUST NOT require video buffer depth (PAD video is on-demand).
- A PAD producer with no block assigned, or in a state where it cannot produce frames, MUST NOT be used as a video source.
- Content segments continue to require both audio and video buffer depth.

## Violation Condition

Any of the following constitutes a violation:

- PAD swap eligibility is rejected due to video buffer depth when audio depth is sufficient and the PAD producer is capable.
- PAD producer is used as a video source while in a state that cannot produce frames.
- PAD swap is deferred at a CONTENT->PAD seam when a PAD frame was already selected, causing `INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001` stale_frame_bleed.

Violations MUST be logged with tag `INV-PAD-VIDEO-READINESS-001-VIOLATED`.

## Enforcement Surface

The PAD readiness evaluation in `IsIncomingSegmentEligibleForSwap` and `GetIncomingSegmentState`. PAD segments use the PAD-specific path in `GetIncomingSegmentState` (guarded by `!is_pad` on the content B branch). `IsIncomingSegmentEligibleForSwap` applies audio-only gate for PAD.

## Non-Goals

- This invariant does not prescribe the content of PAD video frames (that is `INV-PAD-PRODUCER`).
- This invariant does not govern non-PAD segment readiness.
- This invariant does not specify the fill thread implementation or scheduling.

## Derives From

`LAW-LIVENESS`, `INV-PAD-PRODUCER`, `INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001`

## Evidence Tests (required)

These tests remain mandatory coverage for the parent invariants `INV-CONTINUOUS-FRAME-AUTHORITY-001` and `INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001`. They validate the PAD-specific eligibility gate that prevents vacuum and stale frame bleed at PAD seam boundaries.

- `pkg/air/tests/contracts/BlockPlan/PadVideoReadinessContractTests.cpp` (PadVideoReadiness: PadEligibleWithZeroVideoFramesBecauseOnDemand, PadEligibleWithSufficientVideoAndAudio, PadAudioOnlySufficientBecauseVideoOnDemand, PadWithInsufficientAudioNotEligible, ContentStillRequiresVideoDepth)

## Enforcement Evidence

- `PipelineManager::IsIncomingSegmentEligibleForSwap` — PAD branch checks audio depth only; video depth gate skipped.
- `PipelineManager::GetIncomingSegmentState` — `!is_pad` guard on content B branch ensures PAD always uses PAD-specific path.
