# INV-BLOCK-FRAME-BUDGET-AUTHORITY: Frame Budget as Counting Authority

**Classification:** INVARIANT (Execution — Broadcast-Grade)
**Owner:** PipelineManager / TickProducer
**Enforcement Phase:** Every output tick within a BlockPlan session
**Depends on:** INV-TICK-GUARANTEED-OUTPUT, INV-BLOCK-WALLCLOCK-FENCE-001
**Created:** 2026-02-08
**Status:** Active

---

## Definition

AIR MUST track a per-block **remaining frame budget** (`remaining_block_frames`)
that counts how many output frames remain before the fence tick.  The budget is
a **counting authority** — it tracks how many frames a block owns.  It is NOT a
timing authority — it does not trigger block transitions.

The budget is derived from the fence:

```
remaining_block_frames = fence_tick - block_start_tick
```

where `fence_tick` is the precomputed rational fence (INV-BLOCK-WALLFENCE-001)
and `block_start_tick` is the session frame index at which the block becomes
live.  The budget is decremented by exactly 1 for every output frame emitted.

By construction, the budget reaches 0 on the exact tick that
`session_frame_index == fence_tick`.  This convergence is an arithmetic
identity, not a runtime coincidence.  The fence triggers the A/B swap
(timing authority); the budget reaching 0 is a **diagnostic verification**
that the fence and budget agree.

---

## Scope

These invariants apply to:

- **Every block** within a BlockPlan playout session.
- **The per-block frame counter** (`remaining_block_frames`).
- **The relationship between fence tick and frame count.**

These invariants do NOT apply to:

- **Block transition timing** — governed exclusively by INV-BLOCK-WALLFENCE-001.
- **Session boot** (the very first block, governed by
  INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT).
- **Segment transitions within a block** (governed by TickProducer's
  CT-threshold logic and INV-AIR-MEDIA-TIME).

---

## Definitions

| Term | Definition |
|------|------------|
| **Block frame budget** | The number of output frames a block owns: `fence_tick - block_start_tick`.  Derived from the rational fence computation (INV-BLOCK-WALLFENCE-001).  Immutable for the lifetime of the block. |
| **remaining_block_frames** | A per-block counter initialized to `fence_tick - block_start_tick` when the block becomes live, decremented by 1 on every emitted frame.  Reaches 0 when `session_frame_index == fence_tick`. |
| **fence_tick** | The first session frame index belonging to the next block, precomputed via the rational formula.  See INV-BLOCK-WALLFENCE-001. |
| **block_start_tick** | The session frame index at which the block becomes the live block.  For the first block, this is 0.  For subsequent blocks, this equals the previous block's fence_tick. |
| **Segment** | An internal composition unit within a block.  A block contains N segments (N >= 1).  Segments describe which media assets fill the block.  Segments have no authority over block timing or frame count. |
| **Segment exhaustion** | A segment's content has been fully consumed (decoder EOF, asset end, etc.).  This is a segment-level event, not a block-level event. |
| **Frame clamping** | The requirement that a segment consult `remaining_block_frames` before emitting, ensuring it never emits more frames than the budget allows. |
| **Convergence** | The property that `remaining_block_frames` reaches 0 on the exact tick that the fence fires.  This is guaranteed by arithmetic: the budget starts at `fence_tick - block_start_tick`, decrements once per tick, and `session_frame_index` increments once per tick. |

---

## Canonical Budget Formula

The frame budget for a block is derived from the fence:

```
block_start_tick       = session_frame_index at block activation
fence_tick             = ceil(delta_ms * fps_num / (fps_den * 1000))
remaining_block_frames = fence_tick - block_start_tick
```

### INVALID Formula (Forbidden)

The formula `block_duration_seconds * output_fps` is **forbidden** as a
budget source.  This formula uses floating-point multiplication and may
disagree with the integer fence computation by ±1 frame.  The budget MUST
be derived from the fence range, never from an independent duration × fps
calculation.

Similarly, `FramesPerBlock()` or any pre-rounded frame count is forbidden.
The budget is `fence_tick - block_start_tick`, full stop.

### Verification Table

| Output FPS | fps_num/fps_den | 30s block | fence_tick | block_start_tick | budget |
|------------|-----------------|-----------|------------|------------------|--------|
| 24         | 24/1            | 30000ms   | 720        | 0                | 720    |
| 25         | 25/1            | 30000ms   | 750        | 0                | 750    |
| 29.97      | 30000/1001      | 30000ms   | 900        | 0                | 900    |
| 30         | 30/1            | 30000ms   | 900        | 0                | 900    |
| 59.94      | 60000/1001      | 30000ms   | 1799       | 0                | 1799   |
| 60         | 60/1            | 30000ms   | 1800       | 0                | 1800   |

---

## Invariants

### INV-FRAME-BUDGET-001: Frame Budget Derived from Fence Range

> The block frame budget MUST be computed as:
>
>     remaining_block_frames = fence_tick - block_start_tick
>
> where `fence_tick` is the precomputed rational fence
> (INV-BLOCK-WALLFENCE-001) and `block_start_tick` is the session frame
> index at block activation.
>
> This value is computed once when the block becomes live and is immutable
> for the block's lifetime.
>
> The frame budget MUST NOT be derived from:
> - `block_duration_seconds * output_fps` (floating-point multiplication)
> - `FramesPerBlock()` or any pre-rounded frame count
> - `ceil(delta_ms / FrameDurationMs())` or any ms-quantized formula
> - Content time, decoded frame count, or any runtime measurement

**Why:** The budget must agree with the fence by construction.  If the
budget is computed independently from the fence (e.g., via `duration × fps`),
floating-point rounding can cause the budget and fence to disagree by
±1 frame.  Deriving the budget from the fence range eliminates this class
of error entirely: `fence_tick - block_start_tick` is exact integer
arithmetic that converges to 0 on the exact tick the fence fires.

---

### INV-FRAME-BUDGET-002: Explicit Remaining Frame Tracking

> AIR MUST maintain a per-block counter `remaining_block_frames` that is:
>
> 1. Initialized to `fence_tick - block_start_tick` when the block
>    becomes the active (live) block.
> 2. Decremented by exactly 1 for every output frame emitted by that
>    block's producer.
> 3. Never incremented, reset, or modified by any other operation.
>
> `remaining_block_frames` is the block's counting authority for how many
> frames remain.  It is NOT a timing authority — it does not trigger the
> A/B swap.  The fence tick (INV-BLOCK-WALLFENCE-001) is the sole timing
> authority.

**Why:** Explicit decrement tracking is O(1), monotonic, exact, and trivially
auditable: at any point, `remaining_block_frames` tells you precisely
how many frames the block has left to emit.  Its convergence to 0 at the
fence tick is a diagnostic verification that the system is correct.

---

### INV-FRAME-BUDGET-003: One Frame, One Decrement

> Every output frame emitted for a block MUST decrement
> `remaining_block_frames` by exactly 1.  This includes:
>
> - Real decoded frames from the segment's content
> - Freeze frames (last-frame hold from INV-TICK-GUARANTEED-OUTPUT)
> - Black frames (fallback from INV-TICK-GUARANTEED-OUTPUT)
>
> The decrement occurs regardless of the frame's source.  A freeze frame
> consumes one unit of block budget just as a real frame does.
>
> No frame may be emitted without decrementing.  No decrement may occur
> without emitting a frame.  The mapping is exactly 1:1.

**Why:** In broadcast, every frame slot in a block is accounted for,
regardless of content.  A block that shows 5 seconds of black still
consumed 150 frame slots (at 30fps).  Those frames are gone from the
block's budget.  Failing to count fallback frames would cause the budget
to disagree with the fence, breaking convergence.

---

### INV-FRAME-BUDGET-004: Budget Reaching Zero Is Verification, Not Trigger

> When `remaining_block_frames` reaches 0, this is a **diagnostic
> verification** that the fence tick has arrived.  It is NOT the trigger
> for the A/B swap.
>
> The causal sequence is:
>
>     session_frame_index >= fence_tick           (timing authority)
>       → A/B swap executes before frame emission (INV-BLOCK-WALLFENCE-004)
>       → BlockCompleted fires                    (INV-BLOCK-WALLFENCE-005)
>       → remaining_block_frames == 0             (verification)
>
> By construction, `remaining_block_frames` reaches 0 on the exact tick
> that `session_frame_index == fence_tick`, because:
>
>     budget_init = fence_tick - block_start_tick
>     ticks_elapsed = session_frame_index - block_start_tick
>     remaining = budget_init - ticks_elapsed
>              = fence_tick - session_frame_index
>
> When `session_frame_index == fence_tick`, `remaining == 0`.  This is
> an arithmetic identity.
>
> If `remaining_block_frames` is NOT 0 when the fence fires, or reaches 0
> before the fence fires, this is a contract violation indicating a bug
> in budget initialization or decrement logic — not a reason to override
> the fence.
>
> `remaining_block_frames == 0` MUST NOT be used as the swap trigger.
> The fence tick is the sole timing authority (INV-BLOCK-WALLFENCE-001).

**Why:** In the pre-contract design, `remaining_block_frames == 0` was the
swap trigger, which made the frame budget the timing authority.  This
created fragility: any error in budget computation (rounding, off-by-one,
FramesPerBlock() disagreeing with the fence) would cause the swap to fire
on the wrong tick.  By making the fence the sole timing authority and the
budget a verification, the system tolerates budget computation errors
gracefully — they become diagnostic assertions, not timing faults.

---

### INV-FRAME-BUDGET-005: Segments Must Consult Remaining Budget

> Before a segment emits a frame, it MUST verify that
> `remaining_block_frames > 0`.
>
> If `remaining_block_frames == 0`, the segment MUST NOT emit a frame,
> regardless of whether the segment has more content available.
>
> A segment's content length does not determine how many frames it may
> emit.  The block's remaining frame budget does.
>
> When a segment has content available but `remaining_block_frames == 0`,
> the content is abandoned (truncated).  It is not deferred to the next
> block, buffered, or carried forward.

**Why:** Segments are composition, not authority.  A segment may contain
a 45-second asset placed in a 30-second block.  Without the budget check,
the segment would emit 15 seconds of frames past the block boundary.
The budget check is the hard ceiling that prevents segment overrun
regardless of content length, content source, or segment count.

---

### INV-FRAME-BUDGET-006: Segment Exhaustion Does Not Cause Block Completion

> When a segment's content is fully consumed (decoder EOF, asset end,
> content-time threshold reached), and `remaining_block_frames > 0`,
> the block MUST NOT complete.
>
> Instead, one of the following MUST occur:
>
> 1. The next segment in the block begins producing frames, OR
> 2. If no next segment exists, the fallback chain
>    (INV-TICK-GUARANTEED-OUTPUT) fills the remaining frames
>    (freeze or black)
>
> In all cases, `remaining_block_frames` continues to decrement with
> each emitted frame (whether from the next segment or from fallback).
>
> There is no special case where segment exhaustion triggers block
> completion.  The fence tick is the only timing trigger; the frame
> budget is the only counting limit.

**Why:** In a multi-segment block (N >= 1), each segment boundary is an
internal transition, not a block boundary.  A commercial break block
might contain 4 segments (four 15-second spots in a 60-second block).
Each segment ending is routine; only the fence tick marks the block
boundary.  If segment exhaustion triggered block completion, the block
would end after the first 15-second spot, discarding the remaining three.

---

### INV-FRAME-BUDGET-007: No Negative Frame Budget

> No segment may emit a frame that causes `remaining_block_frames` to
> become negative (< 0).
>
> Since every emission decrements by exactly 1 (INV-FRAME-BUDGET-003),
> and the budget check occurs before emission (INV-FRAME-BUDGET-005),
> `remaining_block_frames` MUST satisfy:
>
>     remaining_block_frames >= 0  (at all times)
>
> A negative value indicates a violated invariant: either a frame was
> emitted without checking the budget, or the budget was decremented
> without emitting a frame.  Either case is a contract violation that
> MUST be logged and treated as a fatal error for the block.

**Why:** `remaining_block_frames` is a natural number counter.  It
starts at `fence_tick - block_start_tick` (positive) and decrements by
1 until it reaches 0.  It cannot go negative in a correct implementation
because the check in INV-FRAME-BUDGET-005 prevents emission at 0.
A negative value is a proof of bug, not an expected state.

---

## Forbidden Patterns

| Pattern | Why Forbidden |
|---------|---------------|
| `block_duration_seconds * output_fps` as budget source | May disagree with fence by ±1 frame due to floating-point rounding.  Budget must be `fence_tick - block_start_tick`. |
| `FramesPerBlock()` as budget source | Pre-rounded value; may disagree with rational fence computation. |
| `remaining_block_frames == 0` as swap trigger | Budget is counting authority, not timing authority.  The fence tick is the sole swap trigger. |
| Segment exhaustion triggering block completion | Segments are composition, not timing authority.  Only the fence tick ends a block. |
| Budget increment or reset mid-block | Budget is monotonically decreasing.  Any upward change is a contract violation. |
| `ceil(delta_ms / FrameDurationMs())` as budget | ms-quantized formula yields incorrect counts (INV-BLOCK-WALLFENCE-001 Forbidden Patterns). |

---

## Broadcast Industry Context

### Why Frame Counting, Not Timestamps

Professional broadcast automation systems universally use frame-accurate
event control.  The reasons are fundamental:

1. **Frames are discrete.**  Video output is quantized into frames.
   There is no "half frame" or "fractional frame."  A block that runs
   for 30 seconds at 30fps emits exactly 900 frames.  Frame counting
   maps 1:1 to the physical output.

2. **Timestamps are continuous and ambiguous.**  "Has 30 seconds
   elapsed?" depends on clock resolution, comparison semantics (< vs <=),
   and floating-point representation.  "Have 900 frames been emitted?"
   is a simple integer comparison with no ambiguity.

3. **Off-by-one errors are structural in timestamp math.**  Does the
   block end at `start + duration` or at `start + duration - one_frame`?
   Frame indexing eliminates this: the fence tick is computed once from
   rational arithmetic, and the budget is derived from the fence range.

4. **The output device counts frames.**  Whether the output is SDI,
   MPEG-TS, or HLS, the transport carries discrete frames.  Frame budget
   tracking matches the transport's own model.

### How This Maps to Professional Systems

| System | Mechanism |
|--------|-----------|
| Harris/Imagine Nexio | Frame-accurate event list with frame count per event |
| Grass Valley K2 | Frame-indexed clips with explicit in/out frame numbers |
| Evertz Mediator | Frame-accurate automation with per-event frame budgets |
| Blackmagic HyperDeck | Frame-counted record/playback with no timestamp gating |

---

## Non-Goals

This contract explicitly does NOT address or require:

### 1. Block Transition Timing

Block transition timing is governed exclusively by INV-BLOCK-WALLFENCE-001.
The frame budget does not determine *when* the swap fires.  The fence tick
determines when; the budget verifies that the frame count agrees.

### 2. Segment Count Logic

This contract makes zero assumptions about how many segments a block
contains.  A block may have 1 segment, 5 segments, or 100 segments.
The frame budget does not change based on segment count.

### 3. Content-Time Authority

Content time (decoded media time, PTS progression) is tracked for
diagnostics and as-run logging.  It has no authority over block
completion.  A block whose content runs short fills the remainder with
freeze/pad frames, each decrementing the budget.  A block whose content
runs long is truncated at the fence tick.

### 4. Segment Transition Logic

How AIR transitions between segments within a block (decoder teardown,
next-segment initialization, content-time tracking across segments) is
outside this contract's scope.

### 5. Off-By-One Heuristics

This contract does not use "end minus one frame" or "end minus epsilon"
comparisons.  The budget is `fence_tick - block_start_tick`.  The fence
tick is the first tick of the next block.  The block owns ticks
`[block_start_tick, fence_tick)`.  No epsilon adjustment is needed.

---

## Relationship to Existing Contracts

### INV-BLOCK-WALLCLOCK-FENCE-001 (Timing Authority — Sibling)

The fence and the frame budget are **two views of the same block boundary**:

| Concern | Authority |
|---------|-----------|
| **When** does the A/B swap fire? | Fence tick (INV-BLOCK-WALLFENCE-001) — timing authority |
| **How many** frames does the block emit? | Frame budget (this contract) — counting authority |

The budget is derived from the fence: `budget = fence_tick - block_start_tick`.
By construction, the budget reaches 0 on the exact tick that
`session_frame_index == fence_tick`.  This convergence is an arithmetic
identity, not a runtime coincidence.

The fence triggers the swap; the budget reaching 0 is a diagnostic
verification that the fence and budget agree.

### INV-BLOCK-LOOKAHEAD-PRIMING (Coordination — Sibling)

Priming and the budget solve **different aspects** of block transitions:

| Problem | Solution |
|---------|----------|
| **When** does the transition happen? | Fence tick (INV-BLOCK-WALLFENCE-001) |
| **How many** frames does the block emit? | Frame budget (this contract) |
| **How fast** is the first frame of the next block? | Priming (INV-BLOCK-PRIME-001/002) |

The budget does not govern priming; priming does not govern the budget.
Both are governed by the fence tick.

### INV-TICK-GUARANTEED-OUTPUT (Law — Parent)

This contract depends on INV-TICK-GUARANTEED-OUTPUT for the guarantee
that fallback frames (freeze, black) fill the gap when a segment
exhausts before the fence tick.  Every fallback frame decrements
`remaining_block_frames` just as a real frame does
(INV-FRAME-BUDGET-003).

### INV-AIR-MEDIA-TIME (Semantic — Orthogonal)

Content time tracking is unchanged.  CT tracks decoded media time for
diagnostics and segment transitions.  CT does not influence block
completion or frame budget.  INV-AIR-MEDIA-TIME governs segment-internal
behavior; INV-FRAME-BUDGET-AUTHORITY governs block-level frame counting.

| Contract | Relationship |
|----------|-------------|
| INV-BLOCK-WALLCLOCK-FENCE-001 | Sibling: timing authority; budget derived from fence range |
| INV-BLOCK-LOOKAHEAD-PRIMING | Sibling: incoming-edge latency; orthogonal to frame counting |
| INV-AIR-MEDIA-TIME | Orthogonal: CT tracking unchanged; CT has no authority over budget |
| INV-TICK-GUARANTEED-OUTPUT | Parent: provides fallback; fallback frames decrement budget |
| INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT | Sibling: governs session boot; this contract governs subsequent blocks |

---

## Required Tests

**File:** `pkg/air/tests/contracts/test_block_frame_budget.py`

| Test Name | Invariant(s) | Description |
|-----------|-------------|-------------|
| `test_budget_equals_fence_minus_start` | 001 | Verify `budget = fence_tick - block_start_tick` for multiple durations and frame rates |
| `test_budget_agrees_with_rational_fence` | 001 | Verify budget matches rational fence formula, not `duration * fps` |
| `test_remaining_decrements_by_one_per_frame` | 002, 003 | Emit N frames; verify `remaining_block_frames` decreases by exactly 1 per frame |
| `test_freeze_frames_decrement_budget` | 003 | Trigger content underrun; verify freeze frames decrement the budget |
| `test_black_frames_decrement_budget` | 003 | Trigger fallback to black; verify black frames decrement the budget |
| `test_budget_zero_at_fence_tick` | 004 | Simulate tick-by-tick decrement; verify budget reaches 0 exactly when session_frame_index == fence_tick |
| `test_budget_zero_is_verification_not_trigger` | 004 | Verify that the fence fires the swap, not budget == 0 |
| `test_convergence_by_construction` | 004 | Verify `remaining = fence_tick - session_frame_index` is an arithmetic identity |
| `test_segment_checks_budget_before_emit` | 005 | Set budget to 1; verify segment emits exactly 1 frame then stops |
| `test_segment_truncated_at_fence` | 005 | Place a 45s asset in a 30s block; verify exactly `fence_tick - block_start_tick` frames emitted |
| `test_segment_exhaustion_does_not_complete_block` | 006 | Exhaust a 10s segment in a 30s block; verify block continues with fallback/next-segment |
| `test_multi_segment_block_uses_single_budget` | 006 | Block with 3 segments; verify total frames emitted equals budget |
| `test_budget_never_negative` | 007 | Run a full block; assert `remaining_block_frames >= 0` after every emission |
| `test_block_a_and_b_have_independent_budgets` | 001, 002 | Two consecutive blocks with different durations; verify each has its own independent budget |
| `test_epoch_offset_does_not_affect_budget` | 001 | Block budgets are independent of session epoch value |

---

## Logging

Budget initialization:
```
[PipelineManager] INV-FRAME-BUDGET-001: Block %s loaded, remaining_block_frames=%d (fence_tick=%d, block_start_tick=%d)
```

Budget verification at fence:
```
[PipelineManager] INV-FRAME-BUDGET-004: Fence fired, remaining_block_frames=%d (expected 0)
```

Segment exhaustion within block (not a completion):
```
[TickProducer] INV-FRAME-BUDGET-006: Segment exhausted, remaining_block_frames=%d, continuing with next_segment|fallback
```

Budget violation (should never occur):
```
[PipelineManager] INV-FRAME-BUDGET-007 VIOLATION: Block %s remaining_block_frames=%d (negative), aborting block
```

Convergence violation (should never occur):
```
[PipelineManager] INV-FRAME-BUDGET-004 VIOLATION: Fence fired but remaining_block_frames=%d (expected 0), budget/fence disagreement
```
