# INV-BLOCK-WALLCLOCK-FENCE-001: Deterministic Block Fence from Rational Timebase

**Classification:** INVARIANT (Coordination — Broadcast-Grade)
**Owner:** PipelineManager
**Enforcement Phase:** Every block boundary in a BlockPlan session
**Depends on:** INV-TICK-GUARANTEED-OUTPUT, LAW-OUTPUT-LIVENESS, Clock Law (Layer 0)
**Supersedes:** INV-AIR-MEDIA-TIME-001 for block transition authority (see Relationship)
**Created:** 2026-02-07
**Status:** Active

---

## Definition

Block transitions in a BlockPlan session MUST be driven by a precomputed
fence tick derived from the block's UTC schedule and the session's rational
output frame rate.  The fence tick is an absolute session frame index,
computed once at block-load time and immutable thereafter.

The A/B swap fires when `session_frame_index >= fence_tick`.  The fence
tick is the first tick owned by the NEXT block.  The swap occurs BEFORE
frame emission on that tick, so the fence tick's output frame comes from
the new block's producer.

Content time, decoder state, frame budget counters, and runtime clock
reads are never timing authority for block transitions.

---

## Scope

These invariants apply to:

- **Every scheduled block boundary** within a BlockPlan playout session.
- **The A/B producer swap** that executes the transition.
- **The mapping between UTC block schedules and session frame indices.**

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
| **Block interval** | A half-open UTC interval `[start_utc_ms, end_utc_ms)` owned by Core.  `start_utc_ms` is the first instant belonging to the block.  `end_utc_ms` is the first instant belonging to the next block. |
| **session_epoch_utc_ms** | The UTC millisecond timestamp captured once at session start.  Maps UTC schedule times to session-relative frame indices.  Immutable for the session lifetime. |
| **Rational output FPS** | The session's output frame rate expressed as an irreducible integer fraction `fps_num / fps_den`.  Standard broadcast rates: 24/1, 25/1, 30/1, 30000/1001, 24000/1001, 60000/1001, 60/1.  No floating-point representation is authoritative for fence computation. |
| **Scheduled presentation time** | The mathematical (not runtime-measured) wall-clock instant at which frame N would be presented: `spt(N) = session_epoch_utc_ms + N * 1000 * fps_den / fps_num` (milliseconds, rational arithmetic). |
| **fence_tick** | The first session frame index whose scheduled presentation time falls at or after the block's `end_utc_ms`.  Equivalently: `fence_tick = ceil(delta_ms * fps_num / (fps_den * 1000))` where `delta_ms = end_utc_ms - session_epoch_utc_ms`.  Integer form: `(delta_ms * fps_num + fps_den * 1000 - 1) / (fps_den * 1000)` (integer division, no floating point). |
| **Fence tick ownership** | The fence tick is the first tick of the NEXT block, not the last tick of the current block.  Block N owns ticks `[block_start_tick, fence_tick)`.  Block N+1 owns ticks starting at `fence_tick`. |
| **CT (content time)** | Decoded media time tracked by TickProducer during block execution, anchored to decoder PTS. |
| **BlockCompleted** | The event signaling that a block's execution has finished.  Under this contract, BlockCompleted is a consequence of the fence tick firing, not a precondition for it. |
| **A/B swap** | The atomic switch from the current live TickProducer to the next block's TickProducer.  Executes on the fence tick, before frame emission. |
| **Truncation** | Early termination of a block's content stream because the fence tick arrived before CT exhaustion.  Remaining content is discarded; it is not deferred or carried forward. |
| **Freeze/pad** | Emission of the last decoded frame (freeze) or black+silence (pad) because CT exhausted before the fence tick.  Governed by INV-TICK-GUARANTEED-OUTPUT's fallback chain. |

---

## Canonical Fence Formula

The fence tick for a block with `end_utc_ms` is:

```
delta_ms   = end_utc_ms - session_epoch_utc_ms
fence_tick = ceil(delta_ms * fps_num / (fps_den * 1000))
```

Integer form (no floating point):

```
fence_tick = (delta_ms * fps_num + fps_den * 1000 - 1) / (fps_den * 1000)
```

### Verification Table

| Output FPS | fps_num/fps_den | 30s block delta_ms=30000 | fence_tick |
|------------|-----------------|--------------------------|------------|
| 24         | 24/1            | 30000                    | 720        |
| 25         | 25/1            | 30000                    | 750        |
| 29.97      | 30000/1001      | 30000                    | 900        |
| 30         | 30/1            | 30000                    | 900        |
| 59.94      | 60000/1001      | 30000                    | 1799       |
| 60         | 60/1            | 30000                    | 1800       |

### INVALID Formula (Forbidden)

The ms-quantized formula `ceil(delta_ms / round(1000/fps))` is **forbidden**.
For 30fps: `round(1000/30) = 33`, and `ceil(30000/33) = 910 != 900`.
This formula inflates frame counts by ~1% and causes cumulative boundary
drift.  It MUST NOT appear in any fence computation path.

---

## Invariants

### INV-BLOCK-WALLFENCE-001: Rational Fence Tick Is Authoritative for Block Boundaries

> The decision to transition from block N to block N+1 MUST be derived
> solely from the precomputed fence tick.
>
> The fence tick is computed at block-load time using the rational formula:
>
> ```
> fence_tick = (delta_ms * fps_num + fps_den * 1000 - 1) / (fps_den * 1000)
> ```
>
> where `delta_ms = block.end_utc_ms - session_epoch_utc_ms`, and
> `fps_num`/`fps_den` are the session's rational output FPS.
>
> The fence tick is immutable after computation.  No content-clock state —
> including but not limited to decoded_media_time, frames_decoded, decoder
> EOF, CT exhaustion, remaining_block_frames reaching 0, or BlockCompleted —
> may delay, defer, or prevent the A/B swap past the fence tick.
>
> The fence tick MUST NOT be derived from:
> - `OutputClock.now()` or any runtime clock read
> - `ceil(delta_ms / FrameDurationMs())` or any ms-quantized formula
> - `remaining_block_frames == 0` (counting authority, not timing)
> - BlockCompleted timestamps
> - "end minus one frame" or "end minus epsilon" heuristics

**Why:** When block transitions are gated on content-clock events or
derived from ms-rounded arithmetic, variable tail latency and quantization
error cause 1-2 second cumulative drift per block boundary.  A precomputed
rational fence tick eliminates both drift sources by construction: the
boundary is a fixed integer index in the session's tick grid, computed
once from exact arithmetic.

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

**Why:** Content underrun at a block boundary is a production-quality
issue (the asset was shorter than scheduled, or decode was slower than
real-time), but it is never a timing-correctness issue.  Delaying the
boundary to accommodate the content clock converts a bounded quality
issue into an unbounded timing fault.  Truncation bounds the impact to
one block.

---

### INV-BLOCK-WALLFENCE-003: Early CT Exhaustion Results in Freeze/Pad, Not Advancement

> If the current block's content time reaches or exceeds the scheduled
> block duration BEFORE the fence tick, the block boundary MUST NOT
> advance early.
>
> The current producer MUST continue to be the live producer until the
> fence tick.  During the interval between CT exhaustion and the fence
> tick, output MUST follow INV-TICK-GUARANTEED-OUTPUT's fallback chain:
>
> 1. **Freeze** — re-emit the last decoded frame
> 2. **Black** — emit pre-allocated black frame (if no last frame exists)
>
> The next block's producer MUST NOT be swapped in early to fill the gap.
> The next block's content starts at its scheduled fence tick, not when
> the previous block's content happens to end.

**Why:** Early advancement causes the next block to start before its
scheduled time, consuming content ahead of the wall clock.  Over multiple
boundaries, early blocks accumulate forward drift, eventually exhausting
the BlockPlan's content supply.  Holding to the fence tick guarantees
that block N+1 always starts at its intended tick.

---

### INV-BLOCK-WALLFENCE-004: A/B Swap Executes on the Fence Tick Before Frame Emission

> The A/B swap from the current block's TickProducer to the next block's
> TickProducer MUST occur on the fence tick — the first session frame
> index at or past the precomputed fence value.
>
> Specifically:
>
> - The fence tick is identified by: `session_frame_index >= fence_tick`
>   (precomputed integer comparison, not a runtime clock read)
> - The swap occurs BEFORE frame emission on this tick
> - The next block's TickProducer provides the frame for this tick
>   (primed frame per INV-BLOCK-PRIME-002, or live decode, or fallback)
> - The swap is atomic from the perspective of the output stream: the
>   fence tick emits exactly one frame from exactly one producer
> - The fence tick belongs to the NEW block, not the old block
>
> The swap MUST NOT be deferred to a "convenient" tick after the fence.

**Why:** Any deferral past the fence tick introduces variable-latency
drift.  The fence tick is the single deterministic point at which the
transition occurs.  Combined with INV-BLOCK-LOOKAHEAD-PRIMING (which
guarantees the next producer has a primed frame ready), the swap is both
timely and zero-cost.

---

### INV-BLOCK-WALLFENCE-005: BlockCompleted Is a Consequence, Not a Gate

> The BlockCompleted event MUST be emitted as a result of the A/B swap
> executing on the fence tick.  It MUST NOT be a precondition for the swap.
>
> The causal sequence is:
>
> 1. `session_frame_index >= fence_tick` (precomputed comparison)
> 2. A/B swap executes before frame emission (new producer becomes live)
> 3. BlockCompleted fires (previous block is now done)
>
> No component may wait for BlockCompleted before initiating or permitting
> the swap.  BlockCompleted is an after-the-fact notification for
> bookkeeping, telemetry, and as-run logging — it is not part of the
> transition's critical path.

**Why:** In the pre-contract design, BlockCompleted was emitted when the
content clock reached the block end, and the swap was gated on this event.
This created a circular dependency: the swap waited for BlockCompleted,
but BlockCompleted could only fire after the content pipeline drained.
Inverting the causality breaks the cycle.

---

## Forbidden Patterns

The following patterns are explicitly prohibited.  Any code exhibiting
these patterns violates this contract:

| Pattern | Why Forbidden |
|---------|---------------|
| `OutputClock.now() >= wall_clock_boundary` as fence trigger | Runtime clock reads introduce jitter and are not the timing authority; fence_tick is precomputed. |
| `ceil(delta_ms / round(1000/fps))` or `ceil(delta_ms / FrameDurationMs())` | ms-quantized formula yields incorrect tick counts (e.g. 910 instead of 900 for 30fps/30s). |
| `remaining_block_frames == 0` as swap trigger | Frame budget is counting authority, not timing authority.  Budget reaching 0 is a verification of the fence, not the trigger. |
| BlockCompleted timestamp as timing truth | BlockCompleted is a consequence of the swap, fired after it. |
| `end_utc_ms - one_frame_ms` or any "end minus epsilon" heuristic | Half-open intervals eliminate this class of off-by-one entirely. |
| Floating-point FPS in fence computation | Only `fps_num`/`fps_den` integer fraction is authoritative. |

---

## Non-Goals

This contract explicitly does NOT address or require:

1. **Sub-tick boundary precision.**  Block boundaries align to the
   OutputClock tick grid.  Up to one tick period of quantization between
   `end_utc_ms` and the fence tick is expected and acceptable.

2. **Content-time accuracy within a block.**  INV-AIR-MEDIA-TIME
   remains authoritative for how CT is tracked during block execution.

3. **Schedule generation or block duration computation.**  Block
   intervals `[start_utc_ms, end_utc_ms)` are computed by Core and
   delivered via the BlockPlan.  This contract assumes the schedule is
   correct.

4. **Next-block readiness.**  Whether the next producer is primed
   (INV-BLOCK-LOOKAHEAD-PRIMING), unprimed, or in a degraded state
   (INV-BLOCK-PRIME-005) is orthogonal.  The fence fires regardless.
   If the next producer is not ready, the fallback chain
   (INV-TICK-GUARANTEED-OUTPUT) provides the frame.

5. **Segment-internal transitions.**  Segment boundaries within a block
   are governed by CT thresholds (INV-AIR-MEDIA-TIME).

6. **PTS/DTS continuity at boundaries.**  PTS alignment is governed by
   INV-BOUNDARY-PTS-ALIGNMENT.  This contract governs *when* the swap
   happens; PTS contracts govern the *content* of the swap.

7. **OutputClock pacing precision.**  OutputClock's real-time pacing
   (rational nanosecond deadlines) is a separate concern.  The fence
   tick is a schedule-derived integer; OutputClock paces real-time
   delivery of those ticks.

---

## Failure Modes

| Failure | Required Behavior | Governing Invariant |
|---------|-------------------|---------------------|
| CT < block duration at fence tick (content underrun) | Swap proceeds; shortfall logged as diagnostic; outgoing producer abandoned | WALLFENCE-002 |
| CT >= block duration before fence tick (early finish) | Hold current producer; freeze/pad until fence tick; do NOT advance | WALLFENCE-003 |
| Next producer not in kReady at fence tick | Swap proceeds anyway; fallback chain provides frame (freeze or black) | WALLFENCE-004, INV-TICK-GUARANTEED-OUTPUT |
| Wall-clock boundary computation error (negative or zero delta) | Block rejected at schedule load time; never reaches execution | Outside scope (Core validation) |
| OutputClock stall (no ticks advancing) | Covered by LAW-OUTPUT-LIVENESS; fence cannot fire if ticks are not advancing | LAW-OUTPUT-LIVENESS |
| BlockCompleted handler throws or hangs | Must not affect swap; BlockCompleted is post-swap, non-critical-path | WALLFENCE-005 |
| Fence tick coincides with segment boundary within block | Wall-clock fence takes precedence; segment transition is abandoned with the block | WALLFENCE-001 |

---

## Relationship to Existing Contracts

### INV-BLOCK-FRAME-BUDGET-AUTHORITY (Counting Authority — Sibling)

The fence and the frame budget are **two views of the same block boundary**:

| Concern | Authority |
|---------|-----------|
| **When** does the A/B swap fire? | Fence tick (this contract) — timing authority |
| **How many** frames does the block emit? | Frame budget (INV-FRAME-BUDGET) — counting authority |

The frame budget is derived from the fence: `budget = fence_tick - block_start_tick`.
By construction, the budget reaches 0 on the exact tick that
`session_frame_index == fence_tick`.  This convergence is an arithmetic
identity, not a runtime coincidence.  The fence triggers the swap; the
budget reaching 0 is a diagnostic verification that the fence and budget
agree.

### INV-BLOCK-LOOKAHEAD-PRIMING (Coordination — Sibling)

Priming and the fence solve **different halves** of the block transition:

| Problem | Solution |
|---------|----------|
| **When** does the transition happen? | Fence tick (this contract) |
| **How fast** is the first frame of the next block? | Priming (INV-BLOCK-PRIME-001/002) |

The fence tick is the tick on which the primed frame is consumed.
Priming ensures zero decode latency on that tick.  Neither substitutes
for the other.

### INV-AIR-MEDIA-TIME (Semantic — Partially Superseded)

INV-AIR-MEDIA-TIME-001 is **superseded** for block transition authority.
CT exhaustion becomes a diagnostic observation, not a causal event for
block boundaries.  INV-AIR-MEDIA-TIME-002 through 005 remain fully in
force for intra-block CT tracking.

### INV-TICK-GUARANTEED-OUTPUT (Law — Parent)

This contract depends on INV-TICK-GUARANTEED-OUTPUT for:
1. Early CT exhaustion (WALLFENCE-003): freeze/pad fills the gap.
2. Next producer not ready (WALLFENCE-004): fallback chain provides continuity.

### INV-BOUNDARY-PTS-ALIGNMENT (Semantic — Downstream)

PTS alignment is orthogonal to swap timing.  The fence determines *when*;
PTS contracts determine the *content*.

### Clock Law (Layer 0 — Parent)

This contract refines the Clock Law to block boundaries.  The content
clock is not MasterClock and must not be the source of "now" for
transition decisions.  The fence tick replaces runtime clock reads with
a precomputed schedule-derived value.

| Contract | Relationship |
|----------|-------------|
| INV-BLOCK-FRAME-BUDGET-AUTHORITY | Sibling: counting authority; budget derived from fence range |
| INV-BLOCK-LOOKAHEAD-PRIMING | Sibling: incoming-edge latency; fence is the tick where primed frame is consumed |
| INV-AIR-MEDIA-TIME | Partially superseded: CT tracking unchanged; CT authority over transitions revoked |
| INV-TICK-GUARANTEED-OUTPUT | Parent: provides fallback for early-exhaustion and not-ready cases |
| INV-BOUNDARY-PTS-ALIGNMENT | Downstream: governs PTS content at boundaries; orthogonal to swap timing |
| INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT | Sibling: governs session boot; this contract governs subsequent block swaps |
| Clock Law (Layer 0) | Parent: wall clock as sole authority; fence tick is the deterministic expression of that law |
| LAW-OUTPUT-LIVENESS | Parent: output must flow continuously; fence preserves liveness by never waiting on content drain |

---

## Required Tests

**File:** `pkg/air/tests/contracts/test_deterministic_fence.py`

| Test Name | Invariant(s) | Description |
|-----------|-------------|-------------|
| `test_exact_frame_count` | 001 | Verify rational fence formula yields exact tick counts for all standard broadcast FPS at multiple durations. |
| `test_invalid_formula_diverges` | 001 | Prove ms-quantized formula yields different (incorrect) results: ceil(30000/33) = 910 != 900. |
| `test_non_integer_fps_fence` | 001 | Verify fence for 29.97fps (30000/1001) and 23.976fps (24000/1001) at standard durations. |
| `test_fence_deterministic_same_inputs` | 001 | Same inputs always produce the same fence (immutability). |
| `test_fence_zero_for_nonpositive_delta` | 001 | Fence is 0 if delta_ms <= 0. |
| `test_last_old_block_tick` | 004 | For 30fps/30s: tick 899 < fence (no swap), tick 900 >= fence (swap fires). |
| `test_new_block_owns_fence_tick` | 004 | Fence tick belongs to the new block; new budget = next_fence - fence. |
| `test_consecutive_blocks_no_gap_no_overlap` | 004 | Back-to-back blocks: no tick owned by both or neither. |
| `test_convergence_by_construction` | 001 | Simulate tick-by-tick decrement; budget reaches exactly 0 when session_frame_index == fence_tick. |
| `test_three_block_sequence_30fps` | 001 | 3 consecutive 30s blocks: fences 900, 1800, 2700; budgets all 900. |
| `test_epoch_offset_does_not_affect_budget` | 001 | Block budgets are independent of session epoch value. |
