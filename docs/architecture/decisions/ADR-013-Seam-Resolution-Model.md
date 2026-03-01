# Seam Resolution Model — Same-Tick Authority Semantics

**Status:** Accepted
**Date:** 2026-02-28
**Owner:** AIR (PipelineManager emission path)
**Enforces:** INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001, INV-CONTINUOUS-FRAME-AUTHORITY-001

## Authority Model

**active(T):** The segment holding frame authority at emission tick T.
Represented by the segment index after all swap decisions for tick T have resolved.

**origin(T):** The segment that produced the frame emitted at tick T.
Determined at frame selection time; immutable after encode.

**seam tick:** A tick where the playout schedule indicates a segment boundary has been reached.
The engine must decide whether to transfer authority to the next segment.

## Same-Tick Authority Rule

A segment swap is authoritative in the tick it commits.

If a swap commits at tick T, then active(T) = incoming segment.
The frame emitted at tick T MUST originate from the incoming segment: origin(T) = active(T).

If the frame emitted at tick T originates from the outgoing segment, the swap MUST NOT
commit at tick T. The swap defers to a subsequent tick.

This rule holds unconditionally. There is no grace period, no one-frame hold, and no
post-encode origin correction for the normal or override paths.

## Allowed Seam Outcomes

At a seam tick, exactly one of the following outcomes occurs. There is no fourth case.

**Case A — Defer.** The incoming segment is not ready for swap, or the emitted frame
originates from the active (outgoing) segment. The swap does not commit. active(T) remains
unchanged. origin(T) = active(T). The seam re-evaluates on the next tick.

**Case B — Normal commit.** The incoming segment is eligible, the emitted frame originates
from the incoming segment, and no override path is active. The swap commits.
active(T) = incoming. origin(T) = active(T).

**Case C — Override commit.** An explicit override path selects a frame from the incoming
segment and forces the swap to commit on the same tick. The override path determines both
the frame source and the swap decision atomically. active(T) = incoming.
origin(T) = active(T). Override paths exist for PAD transitions (synthetic frame, forced
swap) and CONTENT transitions from PAD (preemptive pop, forced swap).

## Race Handling Rule

If the incoming segment's eligibility changes between frame selection and the swap
decision (due to asynchronous buffer filling), the swap decision MUST still respect the
frame that was already selected and encoded.

If the emitted frame originated from the outgoing segment, the swap defers — regardless
of whether the incoming segment became eligible after frame selection.

If the emitted frame originated from the incoming segment (via an override path with a
paired force flag), the swap commits — the override path guarantees consistency.

## Frame-Authority Vacuum Exception

When the active segment cannot provide any video frame (depleted) and the incoming segment
has video available but is not fully eligible (e.g., insufficient audio depth), a forced
swap may execute to prevent a frame-authority vacuum. This exception serves
INV-CONTINUOUS-FRAME-AUTHORITY-001.

In this case, the emitted frame may carry outgoing origin (a hold or repeat from the
depleted segment). The forced swap advances authority to the incoming segment. Post-swap
origin correction is permitted ONLY under this exception, because the alternative — no
authority transfer — produces a liveness violation. This is the sole case where post-encode
origin mutation is allowed.

This exception is a last resort. The override paths (Case C) are the primary mechanisms
for authority transfer and do not require origin correction.

## Prohibited Behaviors

1. Emitting a frame from the incoming segment without committing the swap on the same tick.
2. Committing a swap when the emitted frame originated from the outgoing segment
   (except under the frame-authority vacuum exception).
3. Post-encode origin mutation outside the frame-authority vacuum exception.
4. Any seam outcome not covered by Case A, B, or C above.

## Invariant Enforcement Surface

The enforcement point is the emission path. After all swap decisions resolve for tick T,
the engine verifies origin(T) = active(T). A mismatch is logged as a violation of
INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001. The seam resolution model must conform to the
invariant; the invariant is never weakened to accommodate seam logic.

---

## Evaluation of Existing Mechanisms

### Conformance

| Mechanism | Model Case | Conforms? | Notes |
|---|---|---|---|
| PAD seam override (CONTENT to PAD) | C | Yes | Selects synthetic PAD frame + forces swap atomically |
| CONTENT seam override (PAD to CONTENT) | C | Yes | Pops incoming content frame + forces swap atomically |
| v_src eligibility gate | A/B | Yes | Ensures frame selection matches anticipated swap decision |
| Frame-origin consistency gate | A | Yes | Defers swap when frame carries outgoing origin |
| Normal eligible swap | B | Yes | Frame from incoming, swap commits |
| Normal ineligible deferral | A | Yes | Frame from active, swap deferred |

### Frame-Authority Vacuum Exception

| Mechanism | Conforms? | Notes |
|---|---|---|
| FORCE_EXECUTE + origin restamp | Yes (exception) | Sole permitted post-encode origin mutation |

### Redundancy Analysis

The v_src eligibility gate and the frame-origin consistency gate enforce the same
semantic: do not commit a swap when the emitted frame carries outgoing origin. They
operate at different phases of the tick:

- The eligibility gate prevents wrong-source selection at frame selection time (proactive).
- The consistency gate catches the fill-thread race at swap decision time (reactive).

Both are necessary. The eligibility gate handles the common case. The consistency gate
handles the race where eligibility changes between frame selection and swap decision.
Neither subsumes the other. No simplification is available without accepting a coverage gap.

### Safety-Net Restamp Assessment

The FORCE_EXECUTE origin restamp remains necessary under this model. It covers the
frame-authority vacuum exception — a case where the active segment is depleted, the
override paths failed to obtain a frame from the incoming segment (fill-thread timing),
and the forced swap must execute to prevent liveness violation. The restamp is the only
mechanism that reconciles origin after a forced swap when the frame carries stale origin.

Removing the restamp would require one of:
1. Guaranteeing that CONTENT_SEAM_OVERRIDE always succeeds (impossible: fill-thread timing).
2. Accepting a liveness violation instead of a forced swap (unacceptable).
3. Re-encoding the frame (unacceptable: violates single-encode-per-tick).

**Recommendation:** Retain the restamp. It is the correct mechanism for its exception case.
Mark it clearly as the sole permitted post-encode origin mutation, governed by the
frame-authority vacuum exception defined in this model.
