# INV-BLOCK-FRAME-BUDGET-AUTHORITY: Frame Budget as Authoritative Block Limit

**Classification:** INVARIANT (Execution — Broadcast-Grade)
**Owner:** PipelineManager / TickProducer
**Enforcement Phase:** Every output tick within a BlockPlan session
**Depends on:** INV-TICK-GUARANTEED-OUTPUT, INV-BLOCK-WALLCLOCK-FENCE-001
**Created:** 2026-02-08
**Status:** Active

---

## Problem Statement

A block is a scheduling primitive owned by Core.  Core assigns each block
an absolute start time and a fixed duration.  AIR's job is to execute that
block: emit exactly the right number of output frames, then stop.

The number of output frames a block owns is deterministic:

```
block_frame_budget = block_duration_seconds * output_fps
```

This is the block's **frame budget**.  It is the single authoritative limit
on how many frames a block may emit.  It is derived from the block's
duration and the session's output frame rate — both of which are fixed at
block creation time.

A block contains one or more segments (N >= 1, unknown at compile time).
Segments are internal composition: they describe which media assets fill the
block's time.  Segments are not timing authority.  The block is.

If block completion is driven by segment exhaustion instead of frame budget
exhaustion, several failure modes emerge:

- **Short segments:** A segment ends early, the system mistakes segment
  exhaustion for block exhaustion, and fires BlockCompleted with frames
  remaining in the budget.  The block emits fewer frames than scheduled.

- **Overrun segments:** A segment produces more frames than the remaining
  budget, and without a budget check, the block emits more frames than
  scheduled, stealing time from the next block.

- **Multi-segment blocks:** A block with N segments must transition between
  segments without firing BlockCompleted.  If segment completion and block
  completion share the same signal path, every segment boundary risks a
  spurious block completion.

- **Segment-count assumptions:** If the system assumes one segment per
  block (or any fixed N), blocks with a different segment count break.

The fix is to give the block an explicit frame counter that is the sole
authority over when the block ends.

---

## Definition

AIR MUST track a per-block **remaining frame budget** (`remaining_block_frames`)
that is initialized to the block's total frame budget and decremented by
exactly 1 for every output frame emitted.  Block completion is triggered
exclusively by this counter reaching zero.  No other signal — segment
exhaustion, content-time threshold, decoder EOF, or timestamp comparison —
may trigger block completion.

---

## Definitions

| Term | Definition |
|------|------------|
| **Block frame budget** | The exact number of output frames a block owns: `block_duration_seconds * output_fps`. This value is immutable for the lifetime of the block. |
| **remaining_block_frames** | A per-block counter initialized to `block_frame_budget` and decremented by 1 on every emitted frame. When it reaches 0, the block is complete. |
| **Segment** | An internal composition unit within a block. A block contains N segments (N >= 1). Segments describe which media assets fill the block. Segments have no authority over block timing. |
| **Segment exhaustion** | A segment's content has been fully consumed (decoder EOF, asset end, etc.). This is a segment-level event, not a block-level event. |
| **Block completion** | The event where `remaining_block_frames` reaches 0, triggering BlockCompleted. This is the only valid trigger for ending a block. |
| **Frame clamping** | The requirement that a segment consult `remaining_block_frames` before emitting, ensuring it never emits more frames than the budget allows. |

---

## Invariants

### INV-FRAME-BUDGET-001: Frame Budget Is the Single Authoritative Block Limit

> The block frame budget is the single authoritative limit on the number
> of output frames a block may emit.
>
>     block_frame_budget = block_duration_seconds * output_fps
>
> This value is computed once when the block is loaded and is immutable
> for the block's lifetime.  No other quantity — timestamp, content time,
> segment count, decoder state, or external signal — may override,
> extend, or reduce the frame budget.
>
> The frame budget determines:
> - How many frames the block will emit (exactly `block_frame_budget`)
> - When the block ends (when the last frame is emitted)
> - The wall-clock duration of the block (via OutputClock pacing)

**Why:** In broadcast, a block owns a precise time slot.  At 30fps, a
30-second block owns exactly 900 frames.  Not 899.  Not 901.  The frame
budget is the digital equivalent of the broadcast automation system's
frame-accurate event list.  Professional playout systems (Harris,
Grass Valley, Imagine, Evertz) count output frames, not timestamps, to
determine when events fire.  Frame counting is exact; timestamp comparison
introduces floating-point quantization, rounding ambiguity, and
off-by-one boundary conditions.

---

### INV-FRAME-BUDGET-002: Explicit Remaining Frame Tracking

> AIR MUST maintain a per-block counter `remaining_block_frames` that is:
>
> 1. Initialized to `block_frame_budget` when the block becomes the
>    active (live) block.
> 2. Decremented by exactly 1 for every output frame emitted by that
>    block's producer.
> 3. Never incremented, reset, or modified by any other operation.
>
> `remaining_block_frames` is the block's **single source of truth** for
> how many frames remain.  All decisions about block continuation or
> completion MUST consult this counter.

**Why:** Implicit tracking (inferring remaining frames from timestamps,
content time, or tick counts) is fragile.  It requires re-derivation on
every tick, is susceptible to floating-point drift, and conflates the
tracking of "how many frames have I emitted" with "what time is it now."
Explicit decrement tracking is O(1), monotonic, exact, and trivially
auditable: at any point, `remaining_block_frames` tells you precisely
how many frames the block has left to emit.

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
block's budget.  Failing to count fallback frames would allow a block
to overrun its budget whenever content underrun triggers freeze/pad,
creating the exact timing drift the frame budget exists to prevent.

---

### INV-FRAME-BUDGET-004: Zero Budget Triggers Block Completion

> When `remaining_block_frames` reaches 0:
>
> 1. The current block MUST end.  No further frames may be emitted
>    for this block.
> 2. BlockCompleted MUST fire exactly once.
> 3. The A/B swap to the next block's producer MUST occur.
>
> The sequence is:
>
>     remaining_block_frames reaches 0
>       → block is complete
>       → A/B swap executes (next producer becomes live)
>       → BlockCompleted fires (notification to Core)
>
> BlockCompleted MUST NOT fire when `remaining_block_frames > 0`.
> BlockCompleted MUST NOT fire more than once per block.
> No frame may be emitted for a block after its `remaining_block_frames`
> has reached 0.

**Why:** The frame budget is exact.  Block A owns frames
`[0 .. block_frame_budget - 1]`.  Frame `block_frame_budget` belongs to
block B.  If any frame is emitted after the budget reaches 0, it steals
a frame slot from the next block's budget, creating a cascading timing
error.  If BlockCompleted fires before the budget reaches 0, frames
remain unaccounted for, creating a gap.  The 1:1 correspondence between
"last frame emitted" and "BlockCompleted fires" is the fundamental
correctness guarantee.

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
> The block completes only when `remaining_block_frames` reaches 0.
>
> There is no special case where segment exhaustion triggers block
> completion.  The frame budget is the only trigger.

**Why:** In a multi-segment block (N >= 1), each segment boundary is an
internal transition, not a block boundary.  A commercial break block
might contain 4 segments (four 15-second spots in a 60-second block).
Each segment ending is routine; only the last frame of the block is
the block boundary.  If segment exhaustion triggered block completion,
the block would end after the first 15-second spot, discarding the
remaining three.  The frame budget makes this impossible: the block
continues (through subsequent segments or fallback) until all 1800
frames (60s at 30fps) have been emitted.

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
starts at `block_frame_budget` (positive) and decrements by 1 until
it reaches 0.  It cannot go negative in a correct implementation
because the check in INV-FRAME-BUDGET-005 prevents emission at 0.
A negative value is a proof of bug, not an expected state.  Detecting
it immediately prevents the error from propagating to subsequent blocks.

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
   Is the boundary inclusive or exclusive?  Every timestamp comparison
   must answer this question, and the answer is different for "last frame
   of this block" vs "first frame of next block."  Frame indexing
   eliminates this: block A owns `[0..899]`, block B owns `[900..1799]`.
   No overlap.  No gap.

4. **The output device counts frames.**  Whether the output is SDI,
   MPEG-TS, or HLS, the transport carries discrete frames.  Frame budget
   tracking matches the transport's own model.  Timestamp tracking
   requires conversion, which introduces quantization error.

### How This Maps to Professional Systems

| System | Mechanism |
|--------|-----------|
| Harris/Imagine Nexio | Frame-accurate event list with frame count per event |
| Grass Valley K2 | Frame-indexed clips with explicit in/out frame numbers |
| Evertz Mediator | Frame-accurate automation with per-event frame budgets |
| Blackmagic HyperDeck | Frame-counted record/playback with no timestamp gating |

All of these systems answer "when does this event end?" with "when the
frame count reaches the budget," not "when the clock reaches a timestamp."

---

## Non-Goals

This contract explicitly does NOT address or require:

### 1. Segment Count Logic

This contract makes zero assumptions about how many segments a block
contains.  A block may have 1 segment, 5 segments, or 100 segments.
The frame budget does not change based on segment count.  No code path
may branch on segment count for the purpose of block completion.

### 2. Timestamp-Based End Checks

This contract does not use `end_utc_ms`, `start_utc_ms`, content time,
wall-clock comparison, or any other timestamp to determine when a block
ends.  The relationship between frame budget and wall-clock time is
established by OutputClock pacing (each frame occupies `frame_duration_ms`
of wall time).  The frame budget does not consult the clock; the clock
paces the emission of frames that decrement the budget.

**Note:** INV-BLOCK-WALLCLOCK-FENCE-001 governs *when* the A/B swap
fires relative to the wall clock schedule.  This contract governs the
*counting mechanism* that determines how many frames a block owns.
The two are complementary:

- The wall-clock fence ensures the swap fires at the scheduled time.
- The frame budget ensures the block emits exactly the right number
  of frames.

When both are correctly implemented, the wall-clock fence fires on the
same tick that the frame budget reaches 0, because:

```
block_frame_budget = block_duration_seconds * output_fps
wall_clock_fence   = block_start + block_duration_seconds
last_frame_time    = block_start + (block_frame_budget * frame_duration)
                   = block_start + block_duration_seconds
                   = wall_clock_fence
```

They converge by construction.  The frame budget provides the discrete
counting mechanism; the wall-clock fence provides the absolute schedule
anchor.

### 3. Off-By-One Heuristics

This contract does not use "end minus one frame" or "end minus epsilon"
comparisons.  Frame indexing is zero-based: a block with budget 900
owns frames `[0..899]`.  The counter starts at 900, decrements to 0.
When it reaches 0, the block is done.  There is no "last frame" special
case, no "fence minus one" adjustment, no epsilon tolerance.

### 4. Content-Time Authority

Content time (decoded media time, PTS progression) is tracked for
diagnostics and as-run logging.  It has no authority over block
completion.  A block whose content runs short (CT < budget) fills the
remainder with freeze/pad frames, each of which decrements the budget.
A block whose content runs long (CT > budget) is truncated when the
budget reaches 0.  Content time does not extend or shorten the budget.

### 5. Segment Transition Logic

How AIR transitions between segments within a block (decoder teardown,
next-segment initialization, content-time tracking across segments) is
outside this contract's scope.  This contract only requires that every
segment consults `remaining_block_frames` before emitting and that
segment exhaustion does not trigger block completion.  The mechanics of
segment transition are governed by TickProducer's internal logic and
INV-AIR-MEDIA-TIME.

---

## Relationship to Existing Contracts

### INV-BLOCK-WALLCLOCK-FENCE-001 (Coordination — Sibling)

The wall-clock fence and the frame budget are **two views of the same
block boundary**, enforced through different mechanisms:

| Concern | Authority |
|---------|-----------|
| When does the A/B swap fire? | Wall-clock fence (absolute schedule time) |
| How many frames does the block emit? | Frame budget (discrete frame count) |

By construction, both should agree: a block with `block_frame_budget`
frames, paced at `frame_duration_ms` per frame, reaches budget 0 at
exactly the wall-clock fence time.  If they disagree, one of the
following is wrong:

- The frame budget was computed from incorrect duration or fps
- The wall-clock fence was computed from an incorrect epoch
- OutputClock pacing has drifted

In a correct system, the frame budget reaching 0 and the wall-clock
fence firing are the same event, observed through different lenses.

### INV-TICK-GUARANTEED-OUTPUT (Law — Parent)

This contract depends on INV-TICK-GUARANTEED-OUTPUT for the guarantee
that fallback frames (freeze, black) fill the gap when a segment
exhausts before the frame budget.  Every fallback frame decrements
`remaining_block_frames` just as a real frame does
(INV-FRAME-BUDGET-003).

### INV-AIR-MEDIA-TIME (Semantic — Orthogonal)

Content time tracking is unchanged.  CT tracks decoded media time for
diagnostics and segment transitions.  CT does not influence block
completion.  INV-AIR-MEDIA-TIME governs segment-internal behavior;
INV-FRAME-BUDGET-AUTHORITY governs block-level completion.

### INV-BLOCK-LOOKAHEAD-PRIMING (Coordination — Downstream)

When `remaining_block_frames` reaches 0 and the A/B swap fires, the
next block's producer must have a primed frame ready
(INV-BLOCK-PRIME-001/002).  Priming is triggered by the next block
being loaded, which happens before the current block's budget is
exhausted.  The frame budget does not govern priming; priming does not
govern the frame budget.

---

## Required Tests

**File:** `pkg/air/tests/contracts/test_block_frame_budget.py`

| Test Name | Invariant(s) | Description |
|-----------|-------------|-------------|
| `test_frame_budget_exactly_equals_duration_times_fps` | 001 | Verify `block_frame_budget = duration_s * fps` for multiple durations and frame rates |
| `test_remaining_decrements_by_one_per_frame` | 002, 003 | Emit N frames; verify `remaining_block_frames` decreases by exactly 1 per frame |
| `test_freeze_frames_decrement_budget` | 003 | Trigger content underrun; verify freeze frames decrement the budget |
| `test_black_frames_decrement_budget` | 003 | Trigger fallback to black; verify black frames decrement the budget |
| `test_block_completes_at_zero_budget` | 004 | Emit exactly `block_frame_budget` frames; verify BlockCompleted fires on the last frame |
| `test_no_completion_before_zero_budget` | 004 | Emit `block_frame_budget - 1` frames; verify BlockCompleted has NOT fired |
| `test_no_frames_after_zero_budget` | 004 | After budget reaches 0, verify no further frames are emitted for the block |
| `test_block_completed_fires_exactly_once` | 004 | Run a full block; verify BlockCompleted fires exactly once, not zero, not two |
| `test_segment_checks_budget_before_emit` | 005 | Set budget to 1; verify segment emits exactly 1 frame then stops |
| `test_segment_truncated_at_budget_zero` | 005 | Place a 45s asset in a 30s block; verify exactly 900 frames emitted (at 30fps) |
| `test_segment_exhaustion_does_not_complete_block` | 006 | Exhaust a 10s segment in a 30s block; verify block continues with fallback/next-segment |
| `test_multi_segment_block_uses_single_budget` | 006 | Block with 3 segments; verify total frames emitted equals `block_frame_budget`, not sum of segments |
| `test_budget_never_negative` | 007 | Run a full block; assert `remaining_block_frames >= 0` after every emission |
| `test_budget_immutable_after_init` | 001 | Verify `block_frame_budget` value does not change during block execution |
| `test_block_a_and_b_have_independent_budgets` | 001, 002 | Seed two blocks with different durations; verify each has its own independent budget |

---

## Logging

Budget initialization:
```
[PipelineManager] INV-FRAME-BUDGET-001: Block %s loaded, frame_budget=%d (duration_s=%.3f, fps=%.1f)
```

Block completion:
```
[PipelineManager] INV-FRAME-BUDGET-004: Block %s complete, remaining_block_frames=0, total_emitted=%d
```

Segment exhaustion within block (not a completion):
```
[TickProducer] INV-FRAME-BUDGET-006: Segment exhausted, remaining_block_frames=%d, continuing with next_segment|fallback
```

Budget violation (should never occur):
```
[PipelineManager] INV-FRAME-BUDGET-007 VIOLATION: Block %s remaining_block_frames=%d (negative), aborting block
```
