# INV-BLOCK-WALLCLOCK-FENCE-001: Wall-Clock Authority for Block Boundaries

**Classification:** INVARIANT (Coordination — Broadcast-Grade)
**Owner:** PipelineManager / TickProducer
**Enforcement Phase:** Every block boundary in a BlockPlan session
**Depends on:** INV-TICK-GUARANTEED-OUTPUT, LAW-OUTPUT-LIVENESS, Clock Law (Layer 0)
**Supersedes:** INV-AIR-MEDIA-TIME-001 for block transition authority (see §Relationship)
**Created:** 2026-02-07
**Status:** Active

---

## Definition

Block transitions in a BlockPlan session MUST be driven by the wall-clock
schedule, not by content-time (CT) exhaustion or decoder completion events.

The OutputClock's wall-clock-paced tick sequence defines the authoritative
timeline for block boundaries.  When the wall clock reaches or passes a
scheduled block boundary, the A/B swap to the next producer MUST occur on
the next output tick — regardless of whether the current block's content
stream has been fully consumed, partially consumed, or has overrun.

Content time is tracked for diagnostics, telemetry, and as-run reporting.
It is never a gate, fence, or precondition for block transition.

---

## Scope

These invariants apply to:

- **Every scheduled block boundary** within a BlockPlan playout session.
- **The A/B producer swap** that executes the transition.
- **The relationship between OutputClock ticks and block schedule times.**

These invariants do NOT apply to:

- **Session boot** (the very first block, governed by
  INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT).
- **Segment transitions within a block** (governed by TickProducer's
  CT-threshold logic and INV-AIR-MEDIA-TIME).
- **Session teardown** (StopChannel terminates the session; no boundary
  applies).
- **Content-time tracking itself** — INV-AIR-MEDIA-TIME continues to
  govern how CT is measured; this contract governs what CT may influence.

---

## Definitions

| Term | Definition |
|------|------------|
| **Wall-clock boundary** | The absolute wall-clock instant at which a block is scheduled to end, as computed from the BlockPlan schedule (block start time + block duration). |
| **Fence tick** | The first OutputClock tick whose wall-clock time is ≥ the wall-clock boundary. This is the tick on which the A/B swap MUST occur. |
| **CT (content time)** | Decoded media time tracked by TickProducer during block execution, anchored to decoder PTS. |
| **CT exhaustion** | The event where decoded_media_time ≥ block_end_time, indicating the content stream for the current block has been fully consumed. |
| **BlockCompleted** | The event signaling that a block's execution has finished. Under this contract, BlockCompleted is a consequence of the fence tick, not a precondition for it. |
| **A/B swap** | The atomic switch from the current live TickProducer to the previewed next-block TickProducer. |
| **Truncation** | Early termination of a block's content stream because the wall-clock boundary arrived before CT exhaustion. Remaining content is discarded; it is not deferred or carried forward. |
| **Freeze/pad** | Emission of the last decoded frame (freeze) or black+silence (pad) because CT exhausted before the wall-clock boundary. Governed by INV-TICK-GUARANTEED-OUTPUT's fallback chain. |

---

## Invariants

### INV-BLOCK-WALLFENCE-001: Wall Clock Is Authoritative for Block Boundaries

> The decision to transition from block N to block N+1 MUST be derived
> solely from the wall-clock schedule.  The fence tick is determined by:
>
> ```
> fence_tick = first tick where OutputClock.now() >= block_N.start_time + block_N.duration
> ```
>
> No content-clock state — including but not limited to decoded_media_time,
> frames_decoded, decoder EOF, CT exhaustion, or BlockCompleted — may
> delay, defer, or prevent the A/B swap past the fence tick.
>
> The wall-clock boundary is computed once when the block is scheduled and
> is immutable for the lifetime of that block's execution.

**Why this invariant exists:**  When block transitions are gated on
content-clock events (decoder drain, EOF, CT threshold), variable tail
latency from codec flush, final-frame hold, and pipeline drain causes
BlockCompleted to fire 1–2 seconds after the scheduled wall-clock
boundary.  Because the next block cannot start until BlockCompleted fires,
the entire playout timeline shifts late, accumulating drift across every
boundary.  Wall-clock authority eliminates this class of drift by
definition: the boundary is a fixed point in time, not a consequence of
content processing.

---

### INV-BLOCK-WALLFENCE-002: Content Time Must Not Delay a Block Boundary

> If, at the fence tick, the current block's content time has NOT reached
> the scheduled block duration (i.e., `decoded_media_time < block_end_time`),
> the A/B swap MUST proceed anyway.
>
> The remaining content in the current block's decoder pipeline is
> abandoned.  No attempt is made to:
>
> - Flush remaining frames from the current decoder
> - Wait for the current decoder to reach EOF
> - Emit buffered-but-not-yet-rendered frames from the outgoing producer
> - Defer the swap until CT "catches up"
>
> The shortfall between decoded_media_time and block_end_time at the fence
> tick MUST be logged as a diagnostic (not a violation), recording the
> deficit in milliseconds.

**Why this invariant exists:**  Content underrun at a block boundary is a
production-quality issue (the asset was shorter than scheduled, or decode
was slower than real-time), but it is never a timing-correctness issue.
Delaying the boundary to accommodate the content clock converts a
bounded quality issue into an unbounded timing fault — every subsequent
block starts late, and the error accumulates across the session.
Truncation bounds the impact to one block.

---

### INV-BLOCK-WALLFENCE-003: Early CT Exhaustion Results in Freeze/Pad, Not Advancement

> If the current block's content time reaches or exceeds the scheduled
> block duration BEFORE the fence tick (i.e., `decoded_media_time >=
> block_end_time` but `OutputClock.now() < wall_clock_boundary`), the
> block boundary MUST NOT advance early.
>
> The current producer MUST continue to be the live producer until the
> fence tick.  During the interval between CT exhaustion and the fence
> tick, output MUST follow INV-TICK-GUARANTEED-OUTPUT's fallback chain:
>
> 1. **Freeze** — re-emit the last decoded frame
> 2. **Black** — emit pre-allocated black frame (if no last frame exists)
>
> The next block's producer MUST NOT be swapped in early to fill the gap.
> The next block's content starts at its scheduled wall-clock time, not
> when the previous block's content happens to end.

**Why this invariant exists:**  Early advancement would cause the next
block to start before its scheduled time, consuming content ahead of the
wall clock.  Over multiple boundaries, early blocks would accumulate a
forward drift, eventually exhausting the BlockPlan's content supply before
the session's scheduled end.  Worse, if the next block also finishes
early and advances early, the drift compounds geometrically.  Holding to
the wall-clock fence guarantees that block N+1 always starts at its
intended time, preserving the integrity of the entire schedule.

---

### INV-BLOCK-WALLFENCE-004: A/B Swap Executes on the Fence Tick

> The A/B swap from the current block's TickProducer to the next block's
> TickProducer MUST occur on the fence tick — the first output tick at
> or after the wall-clock boundary.
>
> Specifically:
>
> - The fence tick is identified by: `OutputClock.now() >= wall_clock_boundary`
> - On this tick, PipelineManager switches the live producer pointer
>   from the current block's TickProducer to the next block's TickProducer
> - The next block's TickProducer provides the frame for this tick
>   (primed frame per INV-BLOCK-PRIME-002, or live decode, or fallback)
> - The swap is atomic from the perspective of the output stream: the
>   fence tick emits exactly one frame from exactly one producer
>
> The swap MUST NOT be deferred to a "convenient" tick after the fence
> (e.g., waiting for a quiet moment, waiting for the next block's
> producer to signal readiness beyond kReady, or waiting for a keyframe).

**Why this invariant exists:**  Any deferral past the fence tick
introduces the same class of variable-latency drift that content-clock
gating causes.  The fence tick is the single deterministic point at which
the transition occurs.  Combined with INV-BLOCK-LOOKAHEAD-PRIMING (which
guarantees the next producer has a primed frame ready), the swap is both
timely and zero-cost.

---

### INV-BLOCK-WALLFENCE-005: BlockCompleted Is a Consequence, Not a Gate

> The BlockCompleted event (or its equivalent signal) MUST be emitted
> as a result of the A/B swap executing on the fence tick.  It MUST NOT
> be a precondition for the swap.
>
> The causal sequence is:
>
> 1. Fence tick arrives (wall clock ≥ boundary)
> 2. A/B swap executes (new producer becomes live)
> 3. BlockCompleted fires (previous block is now done)
>
> No component may wait for BlockCompleted before initiating or permitting
> the swap.  BlockCompleted is an after-the-fact notification for
> bookkeeping, telemetry, and as-run logging — it is not part of the
> transition's critical path.

**Why this invariant exists:**  In the pre-contract design, BlockCompleted
was emitted when the content clock reached the block end, and the swap
was gated on this event.  This created a circular dependency: the swap
waited for BlockCompleted, but BlockCompleted could only fire after the
content pipeline drained — which happened 1–2 seconds after the wall
clock had already passed the boundary.  Inverting the causality
(swap causes completion, not completion causes swap) breaks the cycle.

---

## Non-Goals

This contract explicitly does NOT address or require:

1. **Sub-tick boundary precision.**  Block boundaries align to the
   OutputClock tick grid (e.g., 33.3ms at 30fps).  This contract does
   not require sub-frame or sub-tick timing.  The fence tick is the
   first tick at or after the boundary; up to one tick period of
   quantization is expected and acceptable.

2. **Content-time accuracy within a block.**  INV-AIR-MEDIA-TIME
   remains authoritative for how CT is tracked during block execution
   (PTS-anchored, no cumulative drift, cadence-independent).  This
   contract does not alter CT tracking — only CT's authority over
   transitions.

3. **Schedule generation or block duration computation.**  Block
   durations and start times are computed by Core and delivered via
   the BlockPlan.  This contract assumes the schedule is correct; it
   does not validate or adjust it.

4. **Next-block readiness.**  Whether the next producer is primed
   (INV-BLOCK-LOOKAHEAD-PRIMING), unprimed, or in a degraded state
   (INV-BLOCK-PRIME-005) is orthogonal to this contract.  The fence
   fires regardless.  If the next producer is not ready, the fallback
   chain (INV-TICK-GUARANTEED-OUTPUT) provides the frame.

5. **Segment-internal transitions.**  Segment boundaries within a block
   are governed by CT thresholds (INV-AIR-MEDIA-TIME).  This contract
   applies only at block boundaries.

6. **PTS/DTS continuity at boundaries.**  PTS alignment across block
   boundaries is governed by INV-BOUNDARY-PTS-ALIGNMENT.  This contract
   governs *when* the swap happens; PTS contracts govern the *content*
   of the swap.

---

## Failure Modes

| Failure | Required Behavior | Governing Invariant |
|---------|-------------------|---------------------|
| CT < block duration at fence tick (content underrun) | Swap proceeds; shortfall logged as diagnostic; outgoing producer abandoned | WALLFENCE-002 |
| CT ≥ block duration before fence tick (content overrun / early finish) | Hold current producer; freeze/pad until fence tick; do NOT advance | WALLFENCE-003 |
| Next producer not in kReady at fence tick | Swap proceeds anyway; fallback chain provides frame (freeze or black) | WALLFENCE-004, INV-TICK-GUARANTEED-OUTPUT |
| Wall-clock boundary computation error (negative or zero duration) | Block rejected at schedule load time; never reaches execution | Outside scope (Core validation) |
| OutputClock stall (no ticks advancing) | Covered by LAW-OUTPUT-LIVENESS; wall-clock fence cannot fire if OutputClock is not ticking; liveness violation is upstream | LAW-OUTPUT-LIVENESS |
| BlockCompleted handler throws or hangs | Must not affect swap; BlockCompleted is post-swap, non-critical-path | WALLFENCE-005 |
| Fence tick coincides with segment boundary within block | Wall-clock fence takes precedence; segment transition is abandoned with the block | WALLFENCE-001 |

---

## Relationship to Existing Contracts

### INV-BLOCK-LOOKAHEAD-PRIMING (Coordination — Sibling)

Priming and the wall-clock fence solve **different halves** of the block
transition problem:

| Problem | Solution |
|---------|----------|
| **When** does the transition happen? | **This contract** — wall-clock fence (INV-BLOCK-WALLFENCE-001) |
| **How fast** is the first frame of the next block? | **Priming** — pre-decoded frame (INV-BLOCK-PRIME-001/002) |

Priming eliminates decode latency on the *incoming edge* of the new block.
The wall-clock fence eliminates completion-event latency on the *outgoing
edge* of the current block.  Neither can substitute for the other:

- **Priming without wall-clock fence:** The next block's first frame is
  ready instantly, but the system still waits 1–2 seconds for the current
  block's content clock to drain before asking for it.
- **Wall-clock fence without priming:** The swap fires on time, but the
  first frame of the new block may require a synchronous decode at the
  fence tick, risking a deadline miss.

Together, they guarantee that block transitions are both **timely**
(wall-clock fence) and **zero-cost** (priming).

### INV-AIR-MEDIA-TIME (Semantic — Partially Superseded)

INV-AIR-MEDIA-TIME-001 states: "Block completion MUST occur when
`decoded_media_time >= block_end_time`."  This contract **supersedes**
that rule for the specific case of block transition authority:

- **Before this contract:** CT exhaustion was the trigger for block
  completion, which was the trigger for the A/B swap.
- **After this contract:** The wall clock is the trigger for the A/B
  swap, which is the trigger for block completion.  CT exhaustion
  becomes a diagnostic observation, not a causal event.

INV-AIR-MEDIA-TIME-002 through 005 (no cumulative drift, fence alignment,
cadence independence, pad-is-never-primary) remain fully in force.  They
govern how CT is *tracked* during execution; this contract governs what
CT may *cause* at boundaries.

### INV-TICK-GUARANTEED-OUTPUT (Law — Parent)

This contract depends on INV-TICK-GUARANTEED-OUTPUT for two guarantees:

1. **Early CT exhaustion (WALLFENCE-003):** When CT runs out before the
   fence tick, the fallback chain (freeze → black) fills the gap.
2. **Next producer not ready (WALLFENCE-004):** If the swap fires but
   the next producer cannot provide a frame, the fallback chain provides
   continuity.

### INV-BOUNDARY-PTS-ALIGNMENT (Semantic — Downstream)

PTS alignment at block boundaries is orthogonal to swap timing.  The
wall-clock fence determines *when* the swap occurs; INV-BOUNDARY-PTS-
ALIGNMENT determines the PTS values carried by the first frame of the
new block.  Both must hold simultaneously.

### Clock Law (Layer 0 — Parent)

This contract is a direct refinement of the Clock Law ("MasterClock is
the only source of 'now'") applied to block boundaries.  The content
clock is not MasterClock and therefore must not be the source of "now"
for transition decisions.

| Contract | Relationship |
|----------|-------------|
| INV-BLOCK-LOOKAHEAD-PRIMING | Sibling: solves incoming-edge latency; this contract solves outgoing-edge authority |
| INV-AIR-MEDIA-TIME | Partially superseded: CT tracking unchanged; CT authority over transitions revoked |
| INV-TICK-GUARANTEED-OUTPUT | Parent: provides fallback for early-exhaustion and not-ready cases |
| INV-BOUNDARY-PTS-ALIGNMENT | Downstream: governs PTS content at boundaries; orthogonal to swap timing |
| INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT | Sibling: governs session boot; this contract governs subsequent block swaps |
| Clock Law (Layer 0) | Parent: wall clock as sole authority; this contract applies that law to block boundaries |
| LAW-OUTPUT-LIVENESS | Parent: output must flow continuously; wall-clock fence preserves liveness by never waiting on content drain |

---

## Required Tests

**File:** `pkg/air/tests/contracts/test_block_wallclock_fence.cpp`

| Test Name | Invariant(s) | Description |
|-----------|-------------|-------------|
| `FenceTickDeterminedByWallClock` | 001 | Verify the A/B swap fires on the first tick where OutputClock.now() ≥ boundary, independent of CT state. |
| `CTUnderrunDoesNotDelaySwap` | 002 | Set CT < block duration at fence tick; verify swap proceeds and shortfall is logged. |
| `CTUnderrunDiagnosticLogged` | 002 | Verify the CT deficit (in ms) is recorded in telemetry/log at the fence tick. |
| `EarlyCTDoesNotAdvanceBoundary` | 003 | Exhaust CT 500ms before fence tick; verify freeze/pad frames emitted until fence, not early swap. |
| `EarlyCTFreezesLastFrame` | 003 | Exhaust CT before fence; verify output is last-decoded-frame freeze (not black, not next-block content). |
| `SwapOccursExactlyOnFenceTick` | 004 | Verify the live producer pointer changes on the fence tick and not one tick before or after. |
| `SwapProceedsWithoutNextProducerReady` | 004 | Set next producer to not-ready at fence tick; verify swap fires and fallback chain provides frame. |
| `BlockCompletedFiresAfterSwap` | 005 | Verify BlockCompleted event timestamp is ≥ fence tick timestamp, and swap does not wait for it. |
| `BlockCompletedNotGateForSwap` | 005 | Suppress BlockCompleted handler; verify swap still occurs on fence tick. |
| `MultiBlockDriftAccumulation` | 001, 002 | Run 10+ block transitions with variable CT underrun; verify cumulative wall-clock drift is zero (within tick quantization). |
| `ScheduleIntegrityAcrossSession` | 001, 003 | Run a full session; verify every block starts within one tick period of its scheduled wall-clock time. |
| `FenceTakesPrecedenceOverSegmentBoundary` | 001 | Arrange fence tick to coincide with mid-block segment boundary; verify wall-clock fence wins. |
