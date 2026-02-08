# INV-BLOCK-LOOKAHEAD-PRIMING: Look-Ahead Priming at Block Boundaries

**Classification:** INVARIANT (Coordination)
**Owner:** ProducerPreloader / TickProducer / PipelineManager
**Enforcement Phase:** Every block boundary in a BlockPlan session
**Depends on:** INV-TICK-GUARANTEED-OUTPUT, INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT, INV-BLOCK-WALLCLOCK-FENCE-001
**Created:** 2026-02-07
**Status:** Active

---

## Definition

When a TickProducer is prepared for the next block (via ProducerPreloader),
the first video frame and its associated audio MUST be decoded into memory
**before** the producer signals readiness.  The fence tick's call to
`TryGetFrame()` — the first call after the A/B swap — MUST return this
pre-decoded frame without invoking the decoder.

The fence tick is the first tick of the next block
(INV-BLOCK-WALLFENCE-004).  Priming ensures that the frame emitted on the
fence tick has zero decode latency: it was already decoded during the
previous block's execution, using the look-ahead window between block load
and fence tick arrival.

---

## Scope

These invariants apply to every A/B block swap within a BlockPlan playout
session.  They do not apply to:

- **Session boot** (the very first block, governed by
  INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT).
- **Legacy Phase8AirProducer paths** (not part of BlockPlan).
- **Segment transitions within a block** (governed by TickProducer's
  CT-threshold logic; no priming required).

---

## Definitions

| Term | Definition |
|------|------------|
| **Fence tick** | The first session frame index belonging to the next block, precomputed via rational formula (INV-BLOCK-WALLFENCE-001).  The A/B swap executes on this tick, before frame emission. |
| **Primed frame** | The first video frame (and associated audio) of the next block, decoded into memory before the fence tick arrives.  Consumed on the fence tick's `TryGetFrame()` call. |
| **Priming window** | The interval between the next block's TickProducer completing `AssignBlock()` and the fence tick arriving.  Priming must complete within this window. |
| **Fence tick emission** | The frame emitted on the fence tick.  This frame comes from the NEW block's producer (after A/B swap).  If priming succeeded, it is the primed frame.  If priming failed, it falls through to live decode or fallback. |

---

## Invariants

### INV-BLOCK-PRIME-001: Decoder Readiness Before Fence Tick

> When the ProducerPreloader worker completes preparation of a
> TickProducer for the next block, the producer MUST hold a decoded
> video frame (and its associated audio samples) in memory.  The
> TickProducer MUST NOT transition to `State::kReady` until either:
>
> (a) the first frame has been successfully decoded and stored, or
> (b) priming has failed and the failure has been recorded
>     (see INV-BLOCK-PRIME-005).
>
> The readiness signal (`IsReady() == true` / `TakeSource()` returning
> non-null) MUST NOT be observable by PipelineManager until this
> condition is satisfied.

**Why this invariant exists:**  Today, `AssignBlock()` opens and seeks
the decoder but does not decode.  The decode cost is paid on the first
`TryGetFrame()` call after the A/B swap — on the fence tick that must
emit the boundary frame.  For assets requiring long keyframe searches,
this decode can exceed the frame-period budget (33ms at 30fps), causing
the OutputClock deadline to be missed.  Pre-decoding eliminates this
variable-latency operation from the fence tick.

---

### INV-BLOCK-PRIME-002: Zero Deadline Work at Fence Tick

> The first call to `TryGetFrame()` on the fence tick — the first call
> after the A/B swap to the new block's producer — MUST return the
> primed frame from memory.  It MUST NOT invoke
> `decoder_->DecodeFrameToBuffer()` or any other I/O or codec operation
> to produce this frame.
>
> The wall-clock cost of the fence tick's `TryGetFrame()` MUST be
> bounded by memory access and metadata copy — no file I/O, no demuxing,
> no decoding.

**Why this invariant exists:**  Every output tick has an identical
real-time budget (one frame period).  The fence tick is not special — it
has the same deadline as every other tick.  If the first frame of the
new block requires a synchronous decode on the fence tick, the worst-case
latency is unbounded (depends on codec, container, keyframe distance).
This invariant guarantees that the fence tick's cost is deterministic
and equivalent to a steady-state repeat tick.

---

### INV-BLOCK-PRIME-003: No Duplicate Decoding

> The primed frame MUST be consumed exactly once.  After the fence tick's
> `TryGetFrame()` returns the primed frame, the decoder's read position
> MUST be immediately past that frame.  The second and subsequent calls
> to `TryGetFrame()` MUST resume normal sequential decoding from the
> decoder's current position.
>
> The primed frame MUST NOT be decoded a second time.  The decoder
> MUST NOT be rewound, re-seeked, or re-opened to reproduce the
> primed frame.

**Why this invariant exists:**  Double-decoding wastes CPU budget that
is needed for steady-state decoding.  Worse, if the decoder is
re-seeked to reproduce the first frame, the second seek may land on a
different keyframe (container-dependent), producing a different frame
or advancing the position incorrectly — causing either a duplicate or
a skip in the output stream.  Exactly-once consumption preserves both
correctness and efficiency.

---

### INV-BLOCK-PRIME-004: No Impact on Steady-State Cadence

> After the primed frame is consumed on the fence tick, the cadence gate
> (decode-budget accumulator in PipelineManager) and the frame-repeat
> pattern MUST behave identically to a block that was not primed.
>
> Priming MUST NOT:
>
> - Alter the cadence ratio
> - Reset or bias the decode-budget accumulator
> - Insert or skip a decode tick
> - Change the deterministic repeat pattern (e.g., DDDDR for 23.976->30)
>
> The primed frame MUST be treated as satisfying a decode decision
> when `should_decode == true`.  It MUST NOT cause an additional
> decode on the subsequent tick.
>
> The cadence state established at the start of the new block MUST be
> derived solely from the block's input FPS and the channel's output
> FPS, as if priming did not exist.

**Why this invariant exists:**  The cadence gate produces a deterministic
decode/repeat pattern that distributes repeated frames evenly across
the output timeline (3:2 pulldown for 23.976->30fps).  Any perturbation
at the block boundary — an extra decode, a missing repeat, a biased
accumulator — creates a visible judder at every block transition.
Priming is an optimization of *when* the first decode occurs, not a
change to *how many* decodes occur.

---

### INV-BLOCK-PRIME-005: Priming Failure Degrades Safely

> If priming fails for any reason (decode error, corrupt container,
> unsupported codec, asset not found, I/O timeout), the TickProducer
> MUST still transition to `State::kReady`.
>
> On failure:
>
> - The primed-frame slot MUST be empty (no partial or corrupt frame).
> - The fence tick's `TryGetFrame()` MUST fall through to the normal
>   decode path (attempting a live decode) or return `nullopt`
>   (triggering pad via INV-TICK-GUARANTEED-OUTPUT's fallback chain).
> - PipelineManager MUST NOT distinguish between a primed producer and
>   an unprimed producer at swap time.  The A/B swap MUST proceed
>   identically in both cases.
>
> Priming failure MUST NOT:
>
> - Prevent the TickProducer from reaching `State::kReady`
> - Prevent the A/B swap from occurring at the fence tick
> - Stall the PipelineManager main loop
> - Leave the TickProducer in an intermediate state between kEmpty
>   and kReady

**Why this invariant exists:**  INV-TICK-GUARANTEED-OUTPUT requires
every tick to emit a frame (real, freeze, or black).  If a priming
failure could block the readiness signal or prevent the A/B swap,
PipelineManager would be unable to transition to the next block at the
fence tick, violating INV-BLOCK-WALLFENCE-004.  Safe degradation means:
priming is best-effort; the fence tick always fires on schedule; the
worst case without priming is identical to the current behavior
(synchronous first-frame decode on the fence tick, or pad if that also
fails).

---

### INV-BLOCK-PRIME-006: Priming is Event-Driven

> The priming step MUST execute as a direct continuation of
> `AssignBlock()` completion on the ProducerPreloader worker thread.
> It MUST NOT be triggered by:
>
> - A timer or periodic poll
> - A check from the PipelineManager main loop
> - A separate thread or task queue
> - A wall-clock deadline
>
> The sequence on the worker thread MUST be:
>
> 1. `AssignBlock()` completes (probe, validate, open, seek)
> 2. Priming executes (decode first frame into held buffer)
> 3. Result is published (readiness becomes observable)
>
> Steps 1-3 are sequential and atomic from the perspective of
> PipelineManager: it observes only the final result, never an
> intermediate state.

**Why this invariant exists:**  Polling introduces non-deterministic
latency — the priming window between `AssignBlock()` completion and
the fence tick is finite and variable.  An event-driven model uses
100% of the available window.  A poll-based model wastes up to one
poll interval per boundary.

---

### INV-BLOCK-PRIME-007: Primed Frame Metadata Integrity

> The primed frame MUST carry identical metadata to what a normal
> `TryGetFrame()` decode would have produced for the same decoder
> position:
>
> - `video.metadata.pts` — decoder-reported PTS (microseconds)
> - `asset_uri` — the first segment's asset path
> - `block_ct_ms` — content time before frame advance (0 for first
>   frame of block)
> - `audio` — all audio samples associated with the video frame
>
> The primed frame MUST include all audio samples that would have
> been emitted by a normal decode of that frame.  Priming MUST NOT
> split audio across ticks or defer audio emission to the next decode.
>
> Priming MUST NOT alter, synthesize, or omit any field of `FrameData`.

**Why this invariant exists:**  SeamProof verification, PTS alignment
(INV-BOUNDARY-PTS-ALIGNMENT), as-run frame stats, and the PTS-anchored
media time tracking in `TryGetFrame()` all depend on frame metadata
accuracy.  If the primed frame carried synthetic or incomplete metadata,
downstream consumers would either produce incorrect diagnostics or
compute incorrect content-time positions for the remainder of the block.

---

## Constraints

### C1: No New Threads

Priming MUST execute on the existing ProducerPreloader worker thread.
No additional threads, thread pools, or async task queues are permitted.

### C2: No New Timers

Priming MUST NOT introduce wall-clock timers, deadlines, or sleeps.
The priming step runs to completion as fast as the decoder allows.

### C3: No Buffering Redesign

Priming holds exactly one frame.  There is no ring buffer, no
multi-frame read-ahead queue, and no prefetch depth parameter.  The
held frame is consumed on the fence tick's `TryGetFrame()` and never
replenished by the priming mechanism.

### C4: Transparent to PipelineManager

PipelineManager's fence logic, A/B swap, cadence initialization, and
tick loop MUST NOT contain priming-aware branches.  The optimization
is entirely internal to TickProducer — PipelineManager calls
`TryGetFrame()` and receives a frame, unaware of whether it was primed
or decoded on demand.

---

## Failure Modes

| Failure | Required Behavior | Governing Invariant |
|---------|-------------------|---------------------|
| Decode error on prime | kReady with empty slot; fence tick's TryGetFrame falls through to live decode or pad | PRIME-005 |
| Asset not found | kReady with empty slot; TryGetFrame returns nullopt (pad) | PRIME-005 |
| Preloader cancelled before prime completes | No result published; PipelineManager loads from queue (existing fallback) | PRIME-005 |
| Corrupt first frame | Discard; empty slot; fall through to live decode | PRIME-005, PRIME-007 |
| Primed frame has wrong PTS | Contract violation (PRIME-007); must be detected by test | PRIME-007 |
| Priming completes after fence tick | Fence fires regardless (INV-BLOCK-WALLFENCE-004); late prime is discarded; live decode or pad on fence tick | PRIME-005, WALLFENCE-004 |

---

## Relationship to Existing Contracts

### INV-BLOCK-WALLCLOCK-FENCE-001 (Timing Authority — Sibling)

Priming and the fence solve **different halves** of the block transition:

| Problem | Solution |
|---------|----------|
| **When** does the transition happen? | Fence tick (INV-BLOCK-WALLFENCE-001) |
| **How fast** is the first frame of the next block? | Priming (this contract) |

The fence tick is the tick on which the primed frame is consumed.
Priming ensures zero decode latency on that tick.  Neither substitutes
for the other.  The fence fires regardless of priming status
(INV-BLOCK-WALLFENCE-004); priming is best-effort optimization.

### INV-BLOCK-FRAME-BUDGET-AUTHORITY (Counting Authority — Sibling)

The frame budget tracks how many frames the block emits.  The primed
frame is the first frame emitted for the new block and decrements
that block's budget.  Priming does not alter the budget count or
the budget's derivation from the fence range.

### INV-TICK-GUARANTEED-OUTPUT (Law — Parent)

Every tick emits; priming failure falls through to this guarantee.
The fallback chain (freeze → black) provides the frame on the fence
tick if priming failed and live decode also fails.

### INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT (Session Boot — Sibling)

Session boot is governed by INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT.
Priming governs subsequent block swaps.  The first block is not primed
(there is no preceding block to prime from).

### INV-BOUNDARY-PTS-ALIGNMENT (Content — Downstream)

The primed frame's PTS must satisfy boundary alignment requirements.
This is a content constraint, not a timing constraint.

| Contract | Relationship |
|----------|-------------|
| INV-BLOCK-WALLCLOCK-FENCE-001 | Sibling: timing authority; fence tick is when primed frame is consumed |
| INV-BLOCK-FRAME-BUDGET-AUTHORITY | Sibling: counting authority; primed frame is first budget decrement for new block |
| INV-TICK-GUARANTEED-OUTPUT | Parent: every tick emits; priming failure falls through to this guarantee |
| INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT | Sibling: governs session boot; priming governs subsequent block swaps |
| INV-BOUNDARY-PTS-ALIGNMENT | Downstream: primed frame's PTS must satisfy boundary alignment |
| INV-BLOCKPLAN-SEGMENT-PAD-TO-CT | Orthogonal: segment-internal underruns are padded; priming is block-boundary only |

---

## Required Tests

**File:** `pkg/air/tests/blockplan/test_block_lookahead_priming.cpp`

| Test Name | Invariant(s) | Description |
|-----------|-------------|-------------|
| `PrimedFrameAvailableBeforeReady` | 001 | After preload completes, the TickProducer holds a decoded frame before kReady is signaled. |
| `FirstTryGetFrameReturnsWithoutDecode` | 002 | Fence tick's TryGetFrame returns a frame; verify no decoder invocation occurred during the call. |
| `PrimedFrameConsumedExactlyOnce` | 003 | Fence tick's TryGetFrame returns the primed frame; next TryGetFrame returns the *next* sequential frame. |
| `DecoderPositionCorrectAfterPrime` | 003 | After primed frame consumed on fence tick, decoder read position is at frame 2 of the segment (frame 1 was primed). |
| `CadenceUnaffectedByPriming` | 004 | For 23.976->30fps, the decode/repeat pattern across a primed block boundary matches the pattern of a non-primed block. |
| `CadenceAccumulatorNotBiased` | 004 | After primed frame consumption on fence tick, decode_budget is identical to what it would be without priming. |
| `PrimeFailureStillReachesReady` | 005 | Inject decode failure at prime time; TickProducer still reaches kReady. |
| `PrimeFailureFallsThrough` | 005 | After failed prime, fence tick's TryGetFrame attempts live decode (or returns nullopt for pad). |
| `PrimeFailureDoesNotStallSwap` | 005 | PipelineManager A/B swap proceeds identically on fence tick whether priming succeeded or failed. |
| `PrimingExecutesAfterAssignBlock` | 006 | Priming runs as direct continuation of AssignBlock on preloader thread (no poll, no timer). |
| `PrimedFramePtsMatchesNormalDecode` | 007 | Primed frame's video.metadata.pts equals what a normal TryGetFrame decode would produce. |
| `PrimedFrameMetadataComplete` | 007 | Primed FrameData has correct asset_uri, block_ct_ms, and audio samples. |
| `PipelineManagerUnaware` | C4 | PipelineManager code path is identical for primed and unprimed producers (no priming-aware branches). |
