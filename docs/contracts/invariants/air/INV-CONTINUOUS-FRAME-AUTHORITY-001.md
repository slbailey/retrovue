# INV-CONTINUOUS-FRAME-AUTHORITY-001 (No frame-authority vacuum)

**Owner:** AIR

## Purpose

Protects `LAW-LIVENESS` and `LAW-SWITCHING` at the frame level. A continuous encoder model requires exactly one authoritative video source at every emission tick. If authority transfers between segments without overlap, a vacuum exists where no segment can provide a frame. The encoder falls back to stale or undefined data, producing a visible glitch. This invariant prevents that vacuum.

## Behavioral Guarantee

At every emission tick during a live session, exactly one segment MUST hold frame authority and MUST be able to provide a valid video frame. Frame authority MUST transfer from the outgoing segment to the incoming segment atomically. There MUST NOT exist any tick where no segment is authoritative. Multiple segments MAY be seam-ready simultaneously; exactly one segment MUST be authoritative at any given tick.

## Formal Definition

Let `T` be any emission tick during a live session. Let `active(T)` be the segment currently holding frame authority at tick `T`. Let `successor(T)` be the segment selected by the swap mechanism as the next candidate for authority transfer at tick `T`.

```
Invariant:
  forall T in session_ticks:
    active(T) != NULL
    AND active(T).can_provide_video_frame(T) = true

Transfer precondition:
  IF NOT active(T).can_provide_video_frame(T)
  THEN successor(T) MUST satisfy seam_ready(successor(T)) = true AT T

Seam-ready (video):
  seam_ready(S) = true IFF S.can_provide_video_frame(T) = true
  No audio precondition is imposed by this invariant.
```

A segment is seam-ready when it can provide a valid video frame on the next emission tick without additional decode or fill latency. Seam-readiness is a video-only predicate for the purposes of this invariant; audio continuity is governed separately by `INV-AUDIO-CONTINUITY-NO-DROP`.

Note: a common symptom of an active segment losing the ability to provide a video frame is video buffer depth reaching zero, but the normative trigger is `can_provide_video_frame(T)`, not any specific buffer metric.

## Authority Model

The segment swap mechanism within the playout engine is the sole authority for frame-authority transfer. No other subsystem may revoke, split, or defer frame authority independently.

## Boundary / Constraints

- Exactly one segment MUST hold frame authority at every emission tick. Not zero. Not two.
- When the active segment cannot provide a video frame, the successor segment MUST already be seam-ready.
- A swap deferral MUST NOT occur when the active segment cannot provide a video frame. Deferring a swap while the active segment cannot provide a frame is a violation.
- Multiple segments MAY be seam-ready concurrently. Seam-readiness is not exclusive. Authority is exclusive.
- This invariant applies regardless of segment type: content, pad, emergency, synthetic, overlay, or any future segment classification.
- The invariant holds across all transition types: scheduled boundary, early termination, forced switch, and underrun recovery.

## Violation Condition

Any of the following constitutes a violation:

- An emission tick occurs where no segment holds frame authority.
- A swap is deferred while the active segment cannot provide a video frame.
- The incoming segment is selected as authoritative before it satisfies seam-ready conditions.
- Two segments simultaneously hold frame authority at the same tick.

Violations MUST be logged with tag `INV-CONTINUOUS-FRAME-AUTHORITY-001-VIOLATED`.

## Enforcement Surface

The playout engine's segment swap decision path. Specifically, the branch that evaluates whether to execute or defer a segment transition at each emission tick.

## Non-Goals

- This invariant does not prescribe preroll duration or buffering strategy.
- This invariant does not define what constitutes valid frame content (that is `LAW-DECODABILITY`).
- This invariant does not govern audio continuity (that is `INV-AUDIO-CONTINUITY-NO-DROP`).
- This invariant does not impose audio preconditions on seam-readiness.
- This invariant does not specify how seam-readiness is achieved, only that it MUST be achieved before authority transfer.
- This invariant does not define scheduling-level segment ordering or selection.

## Rationale (Broadcast Context)

In broadcast television, the transmission chain never emits dead air. Routing switchers, master control, and automation systems guarantee that exactly one source feeds the encoder at all times. A switch is a crosspoint change, not a gap. The encoder is never source-starved. This invariant applies the same principle to a software playout engine: the continuous encoder model MUST have an authoritative video source at every tick, regardless of what is transitioning behind it.

## Derives From

`LAW-LIVENESS`, `LAW-SWITCHING`

## Required Tests

- `pkg/air/tests/contracts/BlockPlan/FrameAuthorityVacuumContractTests.cpp` (FrameAuthorityVacuumTest: NoViolationWhenActiveHasFrames, ViolationWhenActiveEmptyNoIncoming, ViolationWhenActiveEmptySuccessorNotSeamReady, ViolationWhenActiveEmptySwapDeferredDespiteSeamReady)

## Architectural Model

[ADR-013 — Seam Resolution Model](../../../architecture/decisions/ADR-013-Seam-Resolution-Model.md) formalizes the seam resolution semantics that enforce this invariant. The Frame-Authority Vacuum Exception in ADR-013 defines the last-resort forced swap that prevents vacuum when the active segment is depleted.

## Enforcement Evidence

- `PipelineManager::CheckFrameAuthorityVacuum` — static check each tick; returns false and logs `INV-CONTINUOUS-FRAME-AUTHORITY-001-VIOLATED` when `active(T) == NULL` or `active(T).can_provide_video_frame(T) == false` without a seam-ready successor.
- **Cascade actions:** `FrameAuthorityAction` enum (`kDefer`, `kForceExecute`, `kExtendActive`) in `PipelineManager.hpp` governs the response when a vacuum is detected — force-execute promotes the successor, extend-active holds the current segment, defer is prohibited when active cannot provide a frame.
- **Wired at emission boundary:** Called in `PipelineManager::Run()` tick loop after segment authority decision and before frame commit to encoder. Applies to all segment types (content, PAD, filler) and all transition types (scheduled seam, forced switch, underrun recovery).
- Contract tests: `FrameAuthorityVacuumContractTests.cpp` — 4 violation cases (active empty no incoming, active empty successor not seam-ready, swap deferred despite seam-ready, dual authority) and 4 enforcement cases (active has frames, successor seam-ready, force-execute fires, extend-active holds).
- **Derived enforcement evidence — swap-commit video precondition:** [INV-NO-FRAME-AUTHORITY-VACUUM-001](INV-NO-FRAME-AUTHORITY-VACUUM-001.md) defines the swap eligibility gate that prevents authority transfer to a segment that cannot provide video. Content segments require minimum video buffer depth; PAD segments require audio depth only (video is on-demand). Tests: `NoFrameAuthorityVacuumContractTests.cpp` (5 cases validating the eligibility gate).
- **Derived enforcement evidence — PAD video readiness:** [INV-PAD-VIDEO-READINESS-001](INV-PAD-VIDEO-READINESS-001.md) specifies the PAD-specific eligibility rule: PAD is exempt from the video buffer depth gate because it provides video on-demand. Tests: `PadVideoReadinessContractTests.cpp` (5 cases validating PAD eligibility).
