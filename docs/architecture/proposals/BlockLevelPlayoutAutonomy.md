# Block-Level Playout Autonomy

> **Document Type:** Exploratory Proposal
> **Status:** Draft — Invariant-Preserving
> **Relationship:** Refines execution layer; does not replace Phase 8, 11, or 12

---

## Preamble

This document captures an **exploratory but invariant-preserving** architectural direction for block-level playout autonomy.

**Constraints observed:**
- No existing invariants are modified, deleted, or reinterpreted
- No existing contracts are marked obsolete
- All existing Phase 8, Phase 11, and Phase 12 documentation remains authoritative
- This work is additive only

**What this proposal is:**
- An execution-layer refinement
- A change in granularity of enforcement, not authority
- A simplification of coordination frequency between Core and AIR

**What this proposal is not:**
- A replacement for existing phases
- A change to the authority model
- A rejection of existing invariants

---

## 1. Invariant Preservation Map

This section maps each core invariant from the current system to the proposed BlockPlan model, demonstrating preservation.

### 1.1 Epoch Immutability

**Invariant:** INV-P8-005 (Epoch immutability)

**Current enforcement:**
Epoch established at session start via first frame's CT anchor. TimelineController holds epoch for session lifetime. No mechanism exists to refresh or recalibrate epoch mid-session. Drift beyond tolerance triggers session termination.

**BlockPlan enforcement:**
Identical. First BlockPlan includes `epoch_utc` field. AIR establishes epoch once and advances CT using local monotonic clock. Drift beyond tolerance triggers session restart, not correction.

**Status:** Unchanged

**Notes:** The enforcement mechanism is identical; only the delivery vehicle changes (BlockPlan.epoch_utc vs. StartChannel RPC).

---

### 1.2 Single-Writer CT

**Invariant:** LAW-CT-SINGLE-WRITER

**Current enforcement:**
AIR's TimelineController is the exclusive writer of Content Time. Core never modifies CT. CT advances monotonically based on frame emission. All CT reads go through TimelineController.

**BlockPlan enforcement:**
Identical. CT remains AIR-internal with no external writes. The BlockPlan model strengthens this invariant by removing per-segment RPCs that could theoretically introduce timing confusion.

**Status:** Unchanged

---

### 1.3 Monotonic Timeline

**Invariant:** INV-P8-TIMELINE-MONOTONIC (CT never decreases)

**Current enforcement:**
TimelineController enforces monotonic CT advancement. EncoderPipeline's EnforceMonotonicDts() prevents DTS regression. Frame emission order matches CT order. No mechanism allows CT to jump backward.

**BlockPlan enforcement:**
Identical. Epoch refresh is explicitly forbidden as it would cause discontinuity. Dynamic drift correction is rejected because it would introduce non-determinism. Monotonicity is preserved by design.

**Status:** Unchanged

---

### 1.4 Authority Separation (Core vs AIR)

**Invariant:** Phase 11 Authority Model (Core owns schedule, AIR owns execution)

**Current enforcement:**
- Core: Schedule, EPG, segment selection, LoadPreview/SwitchToLive commands
- AIR: CT, frame timing, encoding, muxing, output
- Boundary: Per-segment RPCs (LoadPreview, SwitchToLive) at each transition

**BlockPlan enforcement:**
- Core: Schedule, EPG, block composition, BlockPlan delivery, lookahead maintenance
- AIR: CT, frame timing, encoding, muxing, output, within-block transition execution
- Boundary: Per-block delivery (BlockPlan RPC) at block boundaries only

**Status:** Unchanged

**Notes:** Authority assignment is unchanged. Authority exercise frequency changes: Core exercises scheduling authority once per block instead of once per segment. The boundary between authorities becomes coarser-grained but the separation is preserved.

---

### 1.5 Teardown Safety

**Invariant:** Phase 12 Lifecycle (TEARDOWN_SAFE states, transient protection)

**Current enforcement:**
- 6-state boundary machine (PLANNED → PRELOAD_ISSUED → SWITCH_SCHEDULED → SWITCH_ISSUED → LIVE → complete)
- Teardown deferral during transient states
- FAILED_TERMINAL as absorbing state
- Startup convergence for infeasible boundaries

**BlockPlan enforcement:**
- 2-state model (executing block, waiting for next block)
- Teardown safe when between blocks or at block fence
- Block failure = session failure (terminal)
- No startup convergence needed (no boundaries to evaluate)

**Status:** Preserved, enforced at different granularity

**Notes:** The guarantee (safe teardown, no partial state) is preserved. The mechanism simplifies because block-level granularity has fewer transient states.

---

### 1.6 Determinism Guarantees

**Invariant:** Same inputs produce same outputs (implicit in broadcast-grade correctness)

**Current enforcement:**
- Frame-indexed execution (INV-FRAME-001/002/003)
- CT computed from epoch + monotonic elapsed
- No wall-clock polling during execution
- No adaptive speed adjustments

**BlockPlan enforcement:**
Identical, with explicit reinforcement:
- No NTP polling, no CT adjustment, no playback speed changes
- Once delivered, BlockPlan is immutable
- Determinism favored over dynamic recovery

**Status:** Unchanged

---

### 1.7 Summary Table

| Invariant | Status | Granularity Change |
|-----------|--------|-------------------|
| Epoch immutability | Unchanged | None |
| Single-writer CT | Unchanged | None |
| Monotonic timeline | Unchanged | None |
| Authority separation | Unchanged | Block vs. segment handoff |
| Teardown safety | Preserved | Block-level state machine |
| Determinism guarantees | Unchanged | Reinforced by block immutability |

**No invariants are out of scope** — all categories are explicitly preserved.

---

## 2. Minimal BlockPlan Semantics

This section defines the smallest possible BlockPlan that exercises absolute wall-clock fences, epoch establishment, and autonomous execution.

### 2.1 Required Fields

```
MinimalBlockPlan {
    // Identity
    block_id: string          // Unique identifier
    channel_id: int32         // Channel for session correlation

    // Timing (absolute wall clock, UTC)
    start_utc_ms: int64       // Block start time (milliseconds since Unix epoch)
    end_utc_ms: int64         // Block end time (hard fence)

    // Content (single segment)
    asset_uri: string         // File path to media asset
    asset_start_offset_ms: int64   // Where block begins within asset
    asset_duration_ms: int64  // Total asset duration (for bounds checking)
}
```

**Field count:** 7 required fields.

**Explicit omissions:**
- No `segments[]` array — single segment inlined
- No `block_type` — irrelevant for minimal test
- No `next_block` — lookahead defined separately

---

### 2.2 Execution Phases

```
PHASE 1: RECEIVE (Core → AIR, single RPC)
─────────────────────────────────────────
1. Core computes MinimalBlockPlan
2. Core sends MinimalBlockPlan to AIR via gRPC
3. AIR validates structure and join parameters
4. AIR acknowledges receipt (success/failure)

   ┌─────────────────────────────────────┐
   │ CORE INVOLVEMENT ENDS HERE         │
   │ No further RPCs until block ends   │
   └─────────────────────────────────────┘


PHASE 2: ESTABLISH EPOCH (AIR-internal)
───────────────────────────────────────
5. AIR records epoch_wall_ms, epoch_monotonic, fence_wall_ms
6. AIR computes initial CT based on join time
7. AIR logs epoch establishment


PHASE 3: EXECUTE (AIR-internal, autonomous)
───────────────────────────────────────────
8. AIR opens asset, seeks to computed offset
9. Loop: decode → compute CT → encode → emit → check fence
10. Fence check every frame


PHASE 4: FENCE (AIR-internal)
─────────────────────────────
11. AIR stops frame emission at fence instant
12. AIR logs block completion
13. Session ends (single-block) or transitions (multi-block)
```

---

### 2.3 Failure Conditions

| Condition | Detection Point | Response | Exit Code |
|-----------|-----------------|----------|-----------|
| Asset not found | Phase 1 | Reject BlockPlan | `ASSET_MISSING` |
| Asset unreadable | Phase 3 | Terminate session | `ASSET_ERROR` |
| Decode error | Phase 3 | Terminate session | `DECODE_ERROR` |
| Duration mismatch | Phase 1 | Reject BlockPlan | `INVALID_DURATION` |
| Fence before EOF | Phase 4 | Normal (truncate) | `COMPLETE_TRUNCATED` |
| EOF before fence | Phase 3 | Emit black until fence | `COMPLETE_PADDED` |
| Clock drift > tolerance | Phase 3 | Terminate session | `DRIFT_EXCEEDED` |

**No recovery logic:** Any failure in Phase 3 terminates the session.

---

### 2.4 Success Criteria

The minimal BlockPlan proves autonomous execution if:

| Criterion | Validation |
|-----------|------------|
| No RPCs during execution | Zero Core↔AIR traffic in Phase 3 |
| Epoch established exactly once | Single epoch log line per session |
| Fence enforced at correct wall time | Logged wall time ≤ fence + tolerance |
| CT monotonic | All emitted PTS values strictly increasing |
| Deterministic output | Same inputs → same byte-identical output |

---

## 3. Mid-Block Viewer Join

This section defines semantics for viewers joining after block start.

### 3.1 Join Time Classification

```
        Block Timeline (wall clock)

   ─────┬─────────────────────────┬─────
        │      VALID JOIN ZONE    │
   start_utc                  end_utc
        │                         │
   WAIT                        PROTOCOL
   ZONE                        VIOLATION
```

| Join Time (T) | Classification | AIR Response |
|---------------|----------------|--------------|
| T < start_utc | **EARLY** | Wait until start_utc, begin at asset_start_offset_ms |
| start_utc ≤ T < end_utc | **MID_BLOCK** | Compute offset, begin immediately |
| T ≥ end_utc | **STALE_BLOCK_FROM_CORE** | Return error; Core must retry |

---

### 3.2 STALE_BLOCK_FROM_CORE

**Critical distinction:** The viewer does not select blocks — Core does. Therefore, receiving a block where `T_join >= end_utc` is a **protocol violation by Core**, not a valid "late join" scenario.

```
CONDITION:
  T_receipt_ms >= end_utc_ms

CLASSIFICATION:
  This is NOT: "viewer joined too late"
  This IS: "Core sent a block that is no longer active"

ROOT CAUSES:
  1. Core/AIR clock skew
  2. Core bug (sent previous block instead of current)
  3. Network delay (block valid when sent, stale on arrival)

SEVERITY: Protocol violation

AIR RESPONSE:
  1. Do NOT attempt playback
  2. Return error: STALE_BLOCK_FROM_CORE
  3. Log at WARNING level with staleness_ms
  4. Core must retry with correct active block
```

---

### 3.3 Start Offset Computation

```
INPUTS:
  T_join_ms             = current wall clock at receipt
  start_utc_ms          = block start time
  end_utc_ms            = block end time
  asset_start_offset_ms = where block begins in asset
  asset_duration_ms     = total asset length

COMPUTATION:

  // Detect stale block (protocol violation)
  IF T_join_ms >= end_utc_ms:
      RETURN ERROR: STALE_BLOCK_FROM_CORE

  // Early join: wait for block start
  IF T_join_ms < start_utc_ms:
      wait_ms = start_utc_ms - T_join_ms
      effective_offset_ms = asset_start_offset_ms
      ct_start_us = 0

  // Mid-block join: compute offset
  ELSE:
      wait_ms = 0
      block_elapsed_ms = T_join_ms - start_utc_ms
      effective_offset_ms = asset_start_offset_ms + block_elapsed_ms
      ct_start_us = block_elapsed_ms * 1000

  // Validate offset bounds
  IF effective_offset_ms >= asset_duration_ms:
      RETURN ERROR: OFFSET_EXCEEDS_ASSET

  RETURN { valid: true, wait_ms, effective_offset_ms, ct_start_us }
```

---

### 3.4 Epoch Invariant

**Critical:** `epoch_wall_ms` is always `start_utc_ms`, regardless of join time.

This ensures CT is computed relative to block start, not join time. A mid-join viewer at T+15min sees CT=900s, matching what an early-join viewer would see at that same wall-clock instant.

---

### 3.5 Valid vs Invalid Join Conditions

```
VALID JOIN (all must be true):
  ├─ T_join_ms < end_utc_ms                    // Block not ended
  ├─ effective_offset_ms < asset_duration_ms   // Offset within asset
  └─ asset exists and is readable              // Asset accessible

INVALID JOIN CONDITIONS:
  │ Condition              │ Code                     │ Severity  │
  ├────────────────────────┼──────────────────────────┼───────────┤
  │ T_join >= end_utc      │ STALE_BLOCK_FROM_CORE    │ Violation │
  │ offset >= asset_dur    │ OFFSET_EXCEEDS_ASSET     │ Error     │
  │ asset not found        │ ASSET_MISSING            │ Error     │
  │ end_utc <= start_utc   │ INVALID_BLOCK_TIMING     │ Error     │
```

---

### 3.6 Invariant Statement

```
INV-BLOCKPLAN-FRESHNESS:

  Core MUST send a BlockPlan where end_utc_ms > T_receipt_ms.

  Rationale: The viewer does not select blocks; Core does. If AIR
  receives a block that has already ended, this indicates a protocol
  violation, not normal viewer behavior.

  Enforcement: AIR rejects stale blocks with STALE_BLOCK_FROM_CORE.
  Recovery: Core must retry with the correct currently-active block.
```

---

## 4. Two-Block Lookahead

This section defines the minimal lookahead model for continuous playback across block boundaries.

### 4.1 Block Queue Structure

```
AIR Block Queue (max capacity: 2)

┌─────────────────────────────┬───────────────────────────────┐
│  SLOT 0: EXECUTING          │  SLOT 1: PENDING              │
│  (current block)            │  (next block / lookahead)     │
└─────────────────────────────┴───────────────────────────────┘
```

At fence transition, pending promotes to executing, and the slot opens for the next lookahead delivery.

---

### 4.2 Core's Delivery Obligations

**Obligation 1: Session Initialization**
```
WHEN: Session start
WHAT: Core MUST deliver TWO blocks:
  - Block N: Currently-active block (may require mid-join offset)
  - Block N+1: Next block (lookahead)
```

**Obligation 2: Lookahead Maintenance**
```
WHEN: After AIR transitions to a new block
WHAT: Core MUST deliver next-next block before deadline

DEADLINE: Block N+2 must arrive before Block N+1.end_utc - LOOKAHEAD_MARGIN
```

**Obligation 3: Block Contiguity**
```
INVARIANT: Each block's start_utc MUST equal previous block's end_utc

  Block N:   [start=T+0,  end=T+30]
  Block N+1: [start=T+30, end=T+60]   ✓ contiguous
```

---

### 4.3 AIR's Queueing Rules

**Rule 1: Maximum Queue Depth**
```
AIR maintains at most 2 blocks:
  - Slot 0: Currently executing
  - Slot 1: Pending (lookahead)
```

**Rule 2: Acceptance Criteria**
```
AIR ACCEPTS a block if ALL conditions are true:
  - block.end_utc > T_receipt           (not stale)
  - block.start_utc == queue.tail.end_utc OR queue.empty (contiguous)
  - block.block_id not in queue          (no duplicates)
  - queue.size < 2                       (capacity available)
  - asset exists and readable            (content available)
```

**Rule 3: Rejection Responses**
```
  │ Condition Failed           │ Error Code              │
  ├────────────────────────────┼─────────────────────────┤
  │ block.end_utc <= T_receipt │ STALE_BLOCK_FROM_CORE   │
  │ start_utc != prev.end_utc  │ BLOCK_NOT_CONTIGUOUS    │
  │ block_id already queued    │ DUPLICATE_BLOCK         │
  │ queue.size >= 2            │ QUEUE_FULL              │
```

---

### 4.4 Fence Transition Semantics

```
DEFINITION: The fence is the exact wall-clock instant when one block
ends and the next begins.

  fence_instant = executing_block.end_utc

TRANSITION (at fence_instant):

  IF pending block exists:
    1. Promote pending to executing
    2. Reset CT to 0 (block-relative)
    3. Seek to new block's asset
    4. Continue emission

  IF pending block is MISSING:
    1. Terminate session immediately
    2. Return: LOOKAHEAD_EXHAUSTED
    3. No filler, no waiting, no recovery
```

---

### 4.5 Failure: Lookahead Exhausted

```
SCENARIO: Core fails to deliver Block N+1 before Block N's fence

AIR RESPONSE:
  1. STOP frame emission (after last frame of Block N)
  2. Do NOT emit black frames or filler
  3. Do NOT wait for late delivery
  4. Log ERROR: "[FENCE-FATAL] LOOKAHEAD_EXHAUSTED"
  5. Set session state = TERMINATED
  6. Return to Core: LOOKAHEAD_EXHAUSTED

NO RECOVERY:
  - AIR does NOT wait for late block
  - AIR does NOT emit filler
  - AIR does NOT poll Core
  - Binary outcome: execute or terminate
```

---

### 4.6 Failure: Late Block Arrival

```
CASE A: Arrives BEFORE fence (acceptable)
  Block is accepted, transition proceeds normally.
  Log WARNING if arrival was within LOOKAHEAD_MARGIN.

CASE B: Arrives AFTER fence (rejected)
  Session already terminated due to missing lookahead.
  Late block rejected: STALE_BLOCK_FROM_CORE or SESSION_TERMINATED.
```

---

### 4.7 State Machine

```
SESSION STATES:

  INITIALIZING ──[receive 2 blocks]──► EXECUTING
                                           │
       ┌───[fence + pending exists]────────┤
       │                                   │
       ▼                                   │
  EXECUTING ◄──────────────────────────────┘
       │
       └───[fence + NO pending]──► TERMINATED


QUEUE DEPTH:
  Depth 0: Invalid (cannot execute)
  Depth 1: Executing (need lookahead soon)
  Depth 2: Healthy (executing + pending)
```

---

### 4.8 Protocol Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                    TWO-BLOCK LOOKAHEAD PROTOCOL                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  CORE OBLIGATIONS:                                              │
│    1. Deliver 2 blocks at session start                         │
│    2. Deliver next block before (current.end - MARGIN)          │
│    3. Ensure blocks are contiguous                              │
│    4. Never send stale blocks                                   │
│                                                                 │
│  AIR GUARANTEES:                                                │
│    1. Execute blocks in order without Core interaction          │
│    2. Transition at exact fence instant                         │
│    3. Terminate cleanly if lookahead exhausted                  │
│    4. Never emit filler/black as recovery                       │
│                                                                 │
│  FAILURE MODES (binary):                                        │
│    • Missing lookahead at fence → TERMINATE                     │
│    • Stale block received → REJECT                              │
│    • Non-contiguous block → REJECT                              │
│    • Asset error → TERMINATE                                    │
│                                                                 │
│  NO RECOVERY:                                                   │
│    • No waiting for late blocks                                 │
│    • No filler substitution                                     │
│    • No retry logic                                             │
│    • No "best effort" degradation                               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. Multi-Segment Blocks

This section defines how multiple segments compose within a single block.

### 5.1 Segment Structure

```
BlockPlan {
    block_id: string
    channel_id: int32
    start_utc_ms: int64
    end_utc_ms: int64

    // Multi-segment content
    segments: [
        {
            segment_index: int32       // 0-based, execution order
            asset_uri: string
            asset_start_offset_ms: int64
            segment_duration_ms: int64 // Allocated time for this segment
        },
        ...
    ]
}
```

---

### 5.2 Duration Invariant

```
INV-BLOCKPLAN-DURATION-SUM:

  block_duration_ms = end_utc_ms - start_utc_ms

  sum_of_segments = Σ segment[i].segment_duration_ms

  REQUIRED: block_duration_ms == sum_of_segments

  ENFORCEMENT: AIR rejects BlockPlan if durations do not match.
  ERROR CODE: SEGMENT_DURATION_MISMATCH
```

**Example:**
```
Block: [start=T+0, end=T+1800000]  // 30 minutes

Segments:
  [0] duration=600000   (10 min)
  [1] duration=300000   ( 5 min)
  [2] duration=900000   (15 min)
  ─────────────────────────────
  Sum: 1800000 ✓
```

---

### 5.3 Segment Execution Order

```
RULE: Segments execute in segment_index order (0, 1, 2, ...).

INVARIANT: segment_index values MUST be contiguous starting from 0.

  Valid:   [0, 1, 2, 3]
  Invalid: [0, 2, 3]      // gap
  Invalid: [1, 2, 3]      // doesn't start at 0

ENFORCEMENT: AIR validates on BlockPlan receipt.
ERROR CODE: INVALID_SEGMENT_INDEX
```

---

### 5.4 CT-Based Segment Timing

Segment boundaries are derived from Content Time, not wall clock or RPCs.

```
DERIVATION:

  segment[0].start_ct_ms = 0
  segment[0].end_ct_ms   = segment[0].segment_duration_ms

  segment[i].start_ct_ms = segment[i-1].end_ct_ms
  segment[i].end_ct_ms   = segment[i].start_ct_ms + segment[i].segment_duration_ms

EXAMPLE (3 segments):

  CT (ms):    0         600000    900000         1800000
              │           │         │               │
              ├───seg[0]──┼──seg[1]─┼────seg[2]─────┤
              │  10 min   │  5 min  │    15 min     │
```

**Segment Boundary Table:**
```
  │ Index │ start_ct_ms │ end_ct_ms │ Duration │
  ├───────┼─────────────┼───────────┼──────────┤
  │   0   │      0      │  600000   │  10 min  │
  │   1   │   600000    │  900000   │   5 min  │
  │   2   │   900000    │ 1800000   │  15 min  │
```

---

### 5.5 Segment Transition (AIR-Internal)

```
TRIGGER: CT reaches segment[i].end_ct_ms

TRANSITION SEQUENCE (entirely within AIR):
  1. Stop decoding from segment[i].asset
  2. Close segment[i] asset handle
  3. Open segment[i+1].asset
  4. Seek to segment[i+1].asset_start_offset_ms
  5. Continue decoding
  6. CT continues advancing (no reset)

CRITICAL: No pause, no RPC, no notification to Core.

The transition is invisible to Core. From Core's perspective,
the block is a single opaque execution unit.
```

---

### 5.6 Segment Underrun

**Definition:** Asset EOF occurs before segment's allocated CT window ends.

```
SCENARIO:
  segment[1].segment_duration_ms = 300000  (5 min allocated)
  segment[1].asset actual length = 280000  (4:40 actual)

  CT reaches 280000 within segment[1], but asset EOF.
  20 seconds remain in segment[1]'s allocation.

AIR RESPONSE:
  1. Continue emitting pad frames (black video, silence audio)
  2. CT continues advancing normally
  3. At CT = segment[1].end_ct_ms, transition to segment[2]
  4. Segment[2] starts at its scheduled CT boundary

INVARIANT: INV-BLOCKPLAN-SEGMENT-PAD-TO-CT
  Segment boundaries are HARD CT boundaries.
  If asset EOF occurs before segment[i].end_ct_ms, AIR MUST pad
  output until CT reaches segment[i].end_ct_ms, then transition.
```

**Timing Diagram (Underrun):**
```
  segment[1] allocation: CT 600000 → 900000 (5 min)
  segment[1] asset EOF:  CT 880000 (4:40 actual)

  CT (ms):  600000          880000              900000
              │               │                    │
              ├───asset───────┼───pad─────────────┤
              │   content     │   (20 sec)        │
                              ↑                    ↑
                           asset EOF          transition to seg[2]
```

**Last Segment Underrun:**
```
SCENARIO:
  Final segment (segment[N-1]) asset EOF before block fence.

AIR RESPONSE:
  1. Pad output until CT = block.end_utc_ms (block fence)
  2. At fence: transition to next block (if pending) or terminate
  3. Block timing is preserved exactly

EXAMPLE:
  Block fence: T+1800000 (30 min)
  segment[2] (final) EOF at CT=1750000
  AIR pads 50 seconds until fence, then transitions.
```

---

### 5.6.1 Padding vs Recovery (Critical Distinction)

```
┌─────────────────────────────────────────────────────────────────┐
│           PADDING IS NOT RECOVERY                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  PADDING (INV-BLOCKPLAN-SEGMENT-PAD-TO-CT):                     │
│    • Deterministic timing enforcement                           │
│    • Preserves CT boundaries and block fence                    │
│    • Does NOT consult Core                                      │
│    • Does NOT change block timing                               │
│    • Is part of normal execution, not error handling            │
│                                                                 │
│  RECOVERY (forbidden by INV-BLOCKPLAN-NO-SEGMENT-RECOVERY):     │
│    • Substituting alternative content                           │
│    • Skipping to next segment to "catch up"                     │
│    • Requesting replacement from Core                           │
│    • Extending block duration                                   │
│    • Any action that changes scheduled timing                   │
│                                                                 │
│  KEY INSIGHT:                                                   │
│    Padding maintains the invariant that CT boundaries are       │
│    absolute. It is the ABSENCE of recovery - AIR does not       │
│    attempt to fill the gap with real content, adjust timing,    │
│    or notify Core. It simply enforces the CT schedule.          │
│                                                                 │
│  ANALOGY:                                                       │
│    A broadcast station that loses feed emits black until the    │
│    next scheduled program. The schedule does not change.        │
│    This is timing enforcement, not content recovery.            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

### 5.7 Segment Overrun

**Definition:** Asset contains more content than segment's allocated duration.

```
SCENARIO:
  segment[1].segment_duration_ms = 300000  (5 min allocated)
  segment[1].asset actual length = 400000  (6:40 actual)

  CT reaches segment[1].end_ct_ms (300000 relative to segment start).
  Asset still has 100 seconds of content remaining.

AIR RESPONSE:
  1. Stop decoding at CT = segment[1].end_ct_ms
  2. Truncate remaining asset content (do not emit)
  3. Transition to segment[2] at exact CT boundary
  4. Asset handle closed; remaining content discarded

INVARIANT: INV-BLOCKPLAN-SEGMENT-TRUNCATE
  Segment boundaries are HARD. Excess content is truncated.
  CT authority supersedes asset duration.
```

---

### 5.8 Segment Failure

```
SCENARIO: Segment asset missing, corrupt, or unreadable mid-block.

AIR RESPONSE:
  1. Terminate session immediately
  2. Do NOT skip to next segment
  3. Do NOT emit filler
  4. Return: ASSET_ERROR (block-level, not segment-level)

INVARIANT: INV-BLOCKPLAN-NO-SEGMENT-RECOVERY
  There is no segment-level recovery. Any segment failure
  is a block failure. Any block failure is a session failure.
```

---

### 5.9 What AIR MUST NOT Report to Core

```
┌─────────────────────────────────────────────────────────────────┐
│              SEGMENT INFORMATION FIREWALL                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  AIR MUST NOT report to Core:                                   │
│                                                                 │
│    ✗ Individual segment start events                            │
│    ✗ Individual segment completion events                       │
│    ✗ Segment transition timestamps                              │
│    ✗ Segment underrun occurrences                               │
│    ✗ Segment overrun/truncation occurrences                     │
│    ✗ Per-segment timing metrics                                 │
│    ✗ Per-segment error details                                  │
│    ✗ Current segment index during execution                     │
│    ✗ Segment-level progress indicators                          │
│                                                                 │
│  AIR MAY report to Core:                                        │
│                                                                 │
│    ✓ Block accepted/rejected (at delivery time)                 │
│    ✓ Block execution started                                    │
│    ✓ Block execution completed (success)                        │
│    ✓ Block execution failed (with block-level error code)       │
│    ✓ Session terminated                                         │
│                                                                 │
│  RATIONALE:                                                     │
│    Segments are an AIR implementation detail. Core scheduled    │
│    a BLOCK. Core receives block-level outcomes. The segment     │
│    decomposition is invisible at the Core↔AIR boundary.         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

### 5.10 AIR Internal Logging (Permitted)

```
AIR MAY log segment information internally for diagnostics:

  [DEBUG] [block=B001] Segment 0 started, asset=/path/to/file.mp4
  [DEBUG] [block=B001] Segment 0→1 transition at CT=600000ms
  [DEBUG] [block=B001] Segment 1 underrun: EOF at CT=580000ms, padding to CT=600000ms
  [DEBUG] [block=B001] Segment 2 truncated at CT=900000ms

These logs are for AIR diagnostics only. They are NOT:
  - Sent to Core via RPC
  - Published to metrics endpoints with segment granularity
  - Used to trigger Core-side logic

The segment firewall applies to the Core↔AIR protocol boundary,
not to AIR's internal observability.
```

---

### 5.11 Summary: Segment Execution Model

```
┌─────────────────────────────────────────────────────────────────┐
│               MULTI-SEGMENT BLOCK EXECUTION                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  STRUCTURE:                                                     │
│    • Block contains ordered segment array                       │
│    • Σ segment durations = block duration (invariant)           │
│    • Segments indexed 0..N-1, contiguous                        │
│                                                                 │
│  TIMING:                                                        │
│    • Segment boundaries derived from CT                         │
│    • CT is block-relative (starts at 0)                         │
│    • Transitions occur at computed CT thresholds                │
│    • Wall clock not consulted for segment transitions           │
│                                                                 │
│  TRANSITIONS:                                                   │
│    • AIR-internal only (no RPC)                                 │
│    • Invisible to Core                                          │
│    • CT continues monotonically (no reset)                      │
│                                                                 │
│  UNDERRUN:                                                      │
│    • Pad output until segment CT boundary                       │
│    • Transition at scheduled CT (timing preserved)              │
│    • Last segment underrun → pad until block fence              │
│    • Padding is timing enforcement, not recovery                │
│                                                                 │
│  OVERRUN:                                                       │
│    • Truncate at segment CT boundary                            │
│    • Excess content discarded                                   │
│    • CT authority supersedes asset length                       │
│                                                                 │
│  FAILURE:                                                       │
│    • Any segment failure = block failure                        │
│    • No skip, no content substitution, no Core notification     │
│    • Session terminates                                         │
│                                                                 │
│  REPORTING:                                                     │
│    • Block-level only to Core                                   │
│    • Segment details are AIR-internal                           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. Commercials and Interstitials as Segments

This section demonstrates that commercials, promos, and bumpers require no special execution model. They are segments.

### 6.1 Core Principle

```
┌─────────────────────────────────────────────────────────────────┐
│                  ADS ARE JUST SEGMENTS                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  A "commercial break" is a sequence of segments.                │
│  A "promo" is a segment.                                        │
│  A "bumper" is a segment.                                       │
│  A "station ID" is a segment.                                   │
│                                                                 │
│  There is no "ad segment type". There is only Segment.          │
│                                                                 │
│  All execution rules from Section 5 apply identically:          │
│    • CT-derived timing                                          │
│    • Hard boundaries (truncate on overrun)                      │
│    • Pad-to-CT on underrun                                      │
│    • Failure = block failure                                    │
│    • No Core notification during execution                      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

### 6.2 Commercial Break Structure

A commercial break is expressed as consecutive segments within a block.

**Example: 30-minute sitcom block with mid-break**

```
Block: [start=T+0, end=T+1800000]  // 30 minutes

Segments:
  [0] asset="sitcom_s01e01.mp4"    offset=0       duration=720000   // Act 1 (12 min)
  [1] asset="promo_newshow.mp4"   offset=0       duration=30000    // Promo (30 sec)
  [2] asset="ad_soda.mp4"         offset=0       duration=30000    // Ad (30 sec)
  [3] asset="ad_car.mp4"          offset=0       duration=30000    // Ad (30 sec)
  [4] asset="ad_insurance.mp4"    offset=0       duration=30000    // Ad (30 sec)
  [5] asset="bumper_back.mp4"     offset=0       duration=5000     // Bumper (5 sec)
  [6] asset="sitcom_s01e01.mp4"   offset=720000  duration=855000   // Act 2 (14:15)
  ─────────────────────────────────────────────────────────────────
  Sum: 1800000 ✓

CT Timeline:
  0        720000  750000  780000  810000  840000  845000      1800000
  │           │       │       │       │       │       │           │
  ├──Act 1────┼─promo─┼─soda──┼─car───┼─ins───┼─bump──┼───Act 2───┤
```

**Key observations:**
- Segments [1-5] form the "commercial break" — but AIR sees only segments
- The same sitcom asset appears twice ([0] and [6]) with different offsets
- No special "break" container; just segment sequence
- Total duration matches block duration exactly

---

### 6.3 Promo and Bumper Placement

Promos and bumpers follow identical rules.

**Promo:** Promotional content for upcoming programming
**Bumper:** Short transition element ("We'll be right back" / "Now back to...")

```
PLACEMENT OPTIONS (all valid, all identical execution):

Before break:
  [content] [promo] [ad] [ad] [ad] [bumper] [content]

After break:
  [content] [bumper] [ad] [ad] [ad] [promo] [content]

Interleaved:
  [content] [bumper] [ad] [promo] [ad] [ad] [bumper] [content]

Standalone (block is all interstitial):
  [promo] [promo] [station_id] [promo]

AIR DOES NOT CARE. These are all just:
  segment[0], segment[1], segment[2], ...
```

---

### 6.4 Metadata vs Execution

Segment type is **metadata**, not execution semantics.

```
EXTENDED SEGMENT STRUCTURE (optional metadata):

Segment {
    // Execution fields (AIR uses these)
    segment_index: int32
    asset_uri: string
    asset_start_offset_ms: int64
    segment_duration_ms: int64

    // Metadata fields (AIR ignores these)
    metadata: {
        content_type: string     // "program", "ad", "promo", "bumper", "id"
        content_id: string       // External catalog reference
        title: string            // Human-readable name
        // ... any other metadata Core wants to attach
    }
}

INVARIANT: INV-BLOCKPLAN-METADATA-IGNORED
  AIR MUST NOT alter execution behavior based on segment metadata.
  Metadata exists for Core's scheduling, logging, and EPG purposes.
  AIR executes segments identically regardless of metadata content.
```

**What metadata enables (Core-side, outside execution):**
- EPG display ("Now: Sitcom" vs "Commercial Break")
- As-run logging ("Ad X played at time Y")
- Scheduling constraints ("No competing ads in same break")
- Reporting and analytics (post-hoc, not runtime)

**What metadata does NOT enable:**
- Different execution paths in AIR
- Runtime decisions based on content type
- Dynamic behavior changes

---

### 6.5 Why Ads Do NOT Require Special Execution Logic

```
┌─────────────────────────────────────────────────────────────────┐
│          NO SPECIAL AD EXECUTION LOGIC                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  CLAIM: Ads execute identically to program content.             │
│                                                                 │
│  PROOF BY ENUMERATION:                                          │
│                                                                 │
│  1. TIMING                                                      │
│     Program segment: CT-derived boundaries, hard transitions    │
│     Ad segment: CT-derived boundaries, hard transitions         │
│     → Identical                                                 │
│                                                                 │
│  2. UNDERRUN                                                    │
│     Program underrun: Pad to CT boundary                        │
│     Ad underrun: Pad to CT boundary                             │
│     → Identical                                                 │
│                                                                 │
│  3. OVERRUN                                                     │
│     Program overrun: Truncate at CT boundary                    │
│     Ad overrun: Truncate at CT boundary                         │
│     → Identical                                                 │
│                                                                 │
│  4. FAILURE                                                     │
│     Program asset missing: Block failure, session terminates    │
│     Ad asset missing: Block failure, session terminates         │
│     → Identical                                                 │
│                                                                 │
│  5. TRANSITION                                                  │
│     Program→Program: AIR-internal, no RPC                       │
│     Program→Ad: AIR-internal, no RPC                            │
│     Ad→Ad: AIR-internal, no RPC                                 │
│     Ad→Program: AIR-internal, no RPC                            │
│     → Identical                                                 │
│                                                                 │
│  6. REPORTING                                                   │
│     Program segment events: Not reported to Core                │
│     Ad segment events: Not reported to Core                     │
│     → Identical                                                 │
│                                                                 │
│  CONCLUSION: No execution difference exists. QED.               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

### 6.6 Why AIR Does NOT Need Content Type Awareness

```
QUESTION: Should AIR know if a segment is "content" or "ad"?

ANSWER: No.

REASONING:

  1. EXECUTION IS UNIFORM
     AIR's job: decode asset, encode frames, emit at CT-paced rate.
     This job is identical for all segment types.
     Content type adds no information AIR can act on.

  2. BRANCHING WOULD VIOLATE DETERMINISM
     If AIR behaved differently for ads:
       - Which behaviors would differ?
       - Who defines the difference?
       - How is the difference tested?
     Any branch creates non-determinism risk.

  3. AUTHORITY WOULD LEAK
     If AIR made decisions based on content type:
       - AIR would need policy ("skip ad if X")
       - Policy is editorial intent
       - Editorial intent belongs to Core
     Content-type awareness = authority violation.

  4. SIMPLICITY IS CORRECTNESS
     Fewer code paths = fewer bugs.
     Uniform execution = predictable behavior.
     "Just segments" = maximum simplicity.

INVARIANT: INV-BLOCKPLAN-TYPE-BLIND
  AIR executes all segments using identical logic.
  AIR MUST NOT branch on content_type or equivalent metadata.
```

---

### 6.7 Why Core's Scheduling Authority Is Sufficient

```
QUESTION: How are ads "managed" without runtime coordination?

ANSWER: Core schedules them. That's it.

CORE'S SCHEDULING AUTHORITY INCLUDES:

  1. AD SELECTION
     Core chooses which ads appear in which breaks.
     This happens at schedule time, not runtime.
     By the time AIR receives a BlockPlan, ads are fixed.

  2. AD PLACEMENT
     Core determines segment order within blocks.
     Break structure is encoded in segment sequence.
     No runtime negotiation required.

  3. AD TIMING
     Core sets segment_duration_ms for each ad.
     CT boundaries enforce exact timing.
     No runtime adjustment possible or needed.

  4. AD ROTATION
     Core can vary ads across blocks/days/viewers.
     Different BlockPlans = different ad sequences.
     Rotation is a scheduling concern, not execution.

  5. MAKE-GOOD / REPLACEMENT
     If an ad asset is missing, block fails.
     Core handles make-good in NEXT block's schedule.
     No runtime substitution.

WHAT CORE DOES NOT NEED:

  ✗ Runtime ad insertion APIs
  ✗ Mid-block schedule updates
  ✗ AIR callbacks for ad events
  ✗ Dynamic ad decisioning during playback
  ✗ Real-time inventory management

The BlockPlan is the ad schedule. Execution is automatic.
```

---

### 6.8 Example: Hour Block with Multiple Breaks

```
Block: [start=T+0, end=T+3600000]  // 60 minutes (1 hour)

Segments (typical hour drama structure):
  [ 0] drama_s01e01.mp4     offset=0        dur=900000   // Act 1 (15:00)
  [ 1] bumper_out.mp4       offset=0        dur=3000     // "Stay tuned"
  [ 2] ad_pharma.mp4        offset=0        dur=60000    // Ad (1:00)
  [ 3] ad_retail.mp4        offset=0        dur=30000    // Ad (0:30)
  [ 4] ad_auto.mp4          offset=0        dur=30000    // Ad (0:30)
  [ 5] promo_thursday.mp4   offset=0        dur=30000    // Promo (0:30)
  [ 6] bumper_in.mp4        offset=0        dur=3000     // "Now back to"
  [ 7] drama_s01e01.mp4     offset=900000   dur=840000   // Act 2 (14:00)
  [ 8] bumper_out.mp4       offset=0        dur=3000     // "Stay tuned"
  [ 9] ad_finance.mp4       offset=0        dur=30000    // Ad (0:30)
  [10] ad_telecom.mp4       offset=0        dur=30000    // Ad (0:30)
  [11] ad_food.mp4          offset=0        dur=30000    // Ad (0:30)
  [12] station_id.mp4       offset=0        dur=10000    // Station ID (0:10)
  [13] ad_travel.mp4        offset=0        dur=30000    // Ad (0:30)
  [14] bumper_in.mp4        offset=0        dur=3000     // "Now back to"
  [15] drama_s01e01.mp4     offset=1740000  dur=780000   // Act 3 (13:00)
  [16] bumper_out.mp4       offset=0        dur=3000     // "Stay tuned"
  [17] ad_insurance.mp4     offset=0        dur=30000    // Ad (0:30)
  [18] ad_beverage.mp4      offset=0        dur=30000    // Ad (0:30)
  [19] promo_weekend.mp4    offset=0        dur=30000    // Promo (0:30)
  [20] bumper_in.mp4        offset=0        dur=3000     // "Now back to"
  [21] drama_s01e01.mp4     offset=2520000  dur=694000   // Act 4 (11:34)
  ──────────────────────────────────────────────────────────────────
  Sum: 3600000 ✓

AIR sees: 22 segments with CT boundaries.
AIR does not see: "3 ad breaks", "4 acts", "drama vs ads".
```

---

### 6.9 What This Model Explicitly Excludes

```
┌─────────────────────────────────────────────────────────────────┐
│              NOT IN SCOPE (by design)                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  DYNAMIC AD INSERTION (DAI):                                    │
│    Requires: Runtime ad decisioning, mid-stream splicing        │
│    BlockPlan: Ads fixed at schedule time                        │
│    → Not supported, not needed for broadcast simulation         │
│                                                                 │
│  AD BEACONS / TRACKING:                                         │
│    Requires: Runtime callbacks, viewer-specific events          │
│    BlockPlan: No segment-level reporting to Core                │
│    → Business logic, not execution semantics                    │
│                                                                 │
│  PROGRAMMATIC / RTB:                                            │
│    Requires: Real-time bidding, dynamic selection               │
│    BlockPlan: Content fixed before execution                    │
│    → Scheduling concern, happens before BlockPlan creation      │
│                                                                 │
│  AD PODDING WITH FALLBACK:                                      │
│    Requires: "If ad X fails, play ad Y"                         │
│    BlockPlan: Failure = block failure, no substitution          │
│    → Recovery is forbidden; Core schedules reliable assets      │
│                                                                 │
│  VIEWER-SPECIFIC ADS:                                           │
│    Requires: Per-viewer ad selection at runtime                 │
│    BlockPlan: Same block serves all viewers of channel          │
│    → Broadcast model, not addressable advertising               │
│                                                                 │
│  THESE ARE NOT LIMITATIONS — THEY ARE DESIGN CHOICES.           │
│  RetroVue simulates broadcast television, not modern AdTech.    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

### 6.10 Summary: Ads as Segments

```
┌─────────────────────────────────────────────────────────────────┐
│              COMMERCIALS AND INTERSTITIALS                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  REPRESENTATION:                                                │
│    • Ads, promos, bumpers are Segments (same structure)         │
│    • Commercial breaks are segment sequences                    │
│    • content_type is metadata, not execution semantics          │
│                                                                 │
│  EXECUTION:                                                     │
│    • All Section 5 rules apply identically                      │
│    • No special ad code paths                                   │
│    • No content-type branching                                  │
│    • AIR is type-blind                                          │
│                                                                 │
│  AUTHORITY:                                                     │
│    • Core schedules ads (selection, placement, timing)          │
│    • BlockPlan is the ad schedule                               │
│    • No runtime coordination needed                             │
│    • No mid-block mutation                                      │
│                                                                 │
│  INVARIANTS:                                                    │
│    • INV-BLOCKPLAN-METADATA-IGNORED                             │
│    • INV-BLOCKPLAN-TYPE-BLIND                                   │
│                                                                 │
│  PHILOSOPHY:                                                    │
│    Broadcast TV didn't have "ad servers" — it had schedules.    │
│    The schedule said "play tape X at time Y".                   │
│    BlockPlan is that schedule. AIR plays the tapes.             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. Formal Contracts and Test Specification

This section formalizes the BlockPlan execution model as testable contracts.

---

### 7.1 BlockPlan Execution Contract

#### 7.1.1 CONTRACT-BLOCK-001: BlockPlan Acceptance

```
CONTRACT: CONTRACT-BLOCK-001
NAME: BlockPlan Acceptance
SCOPE: Single block delivery from Core to AIR

REQUIRED INPUTS:
  I1. block_id: string, non-empty
  I2. channel_id: int32
  I3. start_utc_ms: int64, milliseconds since Unix epoch
  I4. end_utc_ms: int64, milliseconds since Unix epoch
  I5. segments[]: array, length >= 1
  I6. For each segment:
      - segment_index: int32
      - asset_uri: string, non-empty
      - asset_start_offset_ms: int64, >= 0
      - segment_duration_ms: int64, > 0

PRECONDITIONS:
  P1. end_utc_ms > start_utc_ms
  P2. end_utc_ms > T_receipt (block not stale)
  P3. segment_index values are contiguous [0, 1, 2, ..., N-1]
  P4. Σ segment[i].segment_duration_ms == (end_utc_ms - start_utc_ms)
  P5. All asset_uri files exist and are readable
  P6. For each segment: asset_start_offset_ms < asset_duration

GUARANTEED BEHAVIORS:
  G1. If all preconditions satisfied: BlockPlan accepted
  G2. Acceptance response returned synchronously
  G3. Block queued for execution (slot 0 or slot 1)

FORBIDDEN BEHAVIORS:
  F1. Accept block where end_utc_ms <= T_receipt
  F2. Accept block where segment durations do not sum to block duration
  F3. Accept block with non-contiguous segment indices
  F4. Accept block when queue is full (2 blocks already queued)
  F5. Modify BlockPlan after acceptance

FAILURE MODES:
  E1. STALE_BLOCK_FROM_CORE: end_utc_ms <= T_receipt
  E2. SEGMENT_DURATION_MISMATCH: sum != block duration
  E3. INVALID_SEGMENT_INDEX: indices not contiguous from 0
  E4. ASSET_MISSING: asset_uri not found
  E5. INVALID_OFFSET: asset_start_offset_ms >= asset_duration
  E6. QUEUE_FULL: 2 blocks already queued
  E7. INVALID_BLOCK_TIMING: end_utc_ms <= start_utc_ms
```

---

#### 7.1.2 CONTRACT-BLOCK-002: Block Execution Lifecycle

```
CONTRACT: CONTRACT-BLOCK-002
NAME: Block Execution Lifecycle
SCOPE: Single block from start to completion

REQUIRED INPUTS:
  I1. Accepted BlockPlan (satisfies CONTRACT-BLOCK-001)
  I2. Wall clock (monotonic, millisecond resolution)

PRECONDITIONS:
  P1. Block is in slot 0 (executing position)
  P2. T_now >= start_utc_ms OR early join (waiting permitted)

GUARANTEED BEHAVIORS:
  G1. Epoch established: epoch_wall_ms = start_utc_ms
  G2. CT starts at 0 and advances monotonically
  G3. All segments executed in index order
  G4. Block ends at fence: T_wall == end_utc_ms
  G5. No Core communication during execution
  G6. Output emitted continuously from start to fence

FORBIDDEN BEHAVIORS:
  F1. Reset CT during block execution
  F2. Skip segments
  F3. Reorder segments
  F4. Extend block beyond fence
  F5. End block before fence (except on failure)
  F6. Send RPC to Core during execution
  F7. Poll wall clock for segment transitions

FAILURE MODES:
  E1. ASSET_ERROR: Asset becomes unreadable mid-execution
  E2. DECODE_ERROR: Decoder fails on asset content
  E3. DRIFT_EXCEEDED: |CT_expected - CT_actual| > tolerance

POSTCONDITIONS:
  Q1. On success: Block marked complete, slot 0 available
  Q2. On failure: Session terminated, all slots cleared
```

---

#### 7.1.3 CONTRACT-BLOCK-003: Block Fence Enforcement

```
CONTRACT: CONTRACT-BLOCK-003
NAME: Block Fence Enforcement
SCOPE: Transition at block boundary

REQUIRED INPUTS:
  I1. Executing block with end_utc_ms
  I2. Pending block in slot 1 (optional)

PRECONDITIONS:
  P1. Block execution in progress
  P2. CT approaching block duration

GUARANTEED BEHAVIORS:
  G1. At T_wall == end_utc_ms: current block emission stops
  G2. If pending block exists: promote to slot 0, begin execution
  G3. If no pending block: session terminates with LOOKAHEAD_EXHAUSTED
  G4. Fence transition is atomic (no gap, no overlap)

FORBIDDEN BEHAVIORS:
  F1. Continue emitting past fence
  F2. Wait for late block delivery at fence
  F3. Emit filler while waiting for next block
  F4. Transition before fence time

FAILURE MODES:
  E1. LOOKAHEAD_EXHAUSTED: No pending block at fence time
```

---

### 7.2 Segment Execution Contract

#### 7.2.1 CONTRACT-SEG-001: CT Boundary Derivation

```
CONTRACT: CONTRACT-SEG-001
NAME: Segment CT Boundary Derivation
SCOPE: Computing segment start/end CT from BlockPlan

REQUIRED INPUTS:
  I1. segments[]: array of segments with segment_duration_ms

COMPUTATION (deterministic):
  segment[0].start_ct_ms = 0
  segment[0].end_ct_ms = segment[0].segment_duration_ms

  For i > 0:
    segment[i].start_ct_ms = segment[i-1].end_ct_ms
    segment[i].end_ct_ms = segment[i].start_ct_ms + segment[i].segment_duration_ms

GUARANTEED BEHAVIORS:
  G1. segment[N-1].end_ct_ms == block_duration_ms
  G2. All boundaries are exact (no floating point)
  G3. Boundaries computed once at block acceptance, never recomputed

FORBIDDEN BEHAVIORS:
  F1. Derive boundaries from wall clock
  F2. Derive boundaries from asset duration
  F3. Recompute boundaries during execution

INVARIANT:
  For all i: segment[i].end_ct_ms == segment[i+1].start_ct_ms
```

---

#### 7.2.2 CONTRACT-SEG-002: Segment Transition

```
CONTRACT: CONTRACT-SEG-002
NAME: Segment Transition
SCOPE: Transition from segment[i] to segment[i+1]

REQUIRED INPUTS:
  I1. Current segment index i
  I2. Current CT value
  I3. segment[i].end_ct_ms (precomputed)

PRECONDITIONS:
  P1. i < N-1 (not final segment)
  P2. Segment i is currently executing

TRIGGER:
  CT >= segment[i].end_ct_ms

GUARANTEED BEHAVIORS:
  G1. Stop decoding from segment[i].asset
  G2. Open segment[i+1].asset
  G3. Seek to segment[i+1].asset_start_offset_ms
  G4. Begin decoding segment[i+1]
  G5. CT continues without reset or jump
  G6. No output gap at transition

FORBIDDEN BEHAVIORS:
  F1. Notify Core of transition
  F2. Pause output during transition
  F3. Reset CT to 0
  F4. Skip segment[i+1]
  F5. Transition before CT reaches boundary
```

---

#### 7.2.3 CONTRACT-SEG-003: Segment Underrun (Pad-to-CT)

```
CONTRACT: CONTRACT-SEG-003
NAME: Segment Underrun Handling
SCOPE: Asset EOF before segment CT boundary

REQUIRED INPUTS:
  I1. Current segment index i
  I2. CT at asset EOF: ct_eof
  I3. segment[i].end_ct_ms

PRECONDITIONS:
  P1. Asset EOF encountered
  P2. ct_eof < segment[i].end_ct_ms

GUARANTEED BEHAVIORS:
  G1. Emit pad frames (black video, silence audio)
  G2. CT continues advancing at normal rate
  G3. Padding continues until CT == segment[i].end_ct_ms
  G4. At CT boundary: normal transition (CONTRACT-SEG-002)
  G5. Output stream remains continuous (no gap)

FORBIDDEN BEHAVIORS:
  F1. Advance immediately to next segment
  F2. Notify Core of underrun
  F3. Stop output
  F4. Alter CT advancement rate
  F5. Substitute alternative content

PADDING SPECIFICATION:
  Video: Black frames (Y=16, Cb=128, Cr=128 for YUV)
  Audio: Digital silence (all samples = 0)
  Frame rate: Matches block's configured output rate
  Duration: (segment[i].end_ct_ms - ct_eof) milliseconds
```

---

#### 7.2.4 CONTRACT-SEG-004: Segment Overrun (Truncate)

```
CONTRACT: CONTRACT-SEG-004
NAME: Segment Overrun Handling
SCOPE: Asset has content beyond segment CT boundary

REQUIRED INPUTS:
  I1. Current segment index i
  I2. Current CT value
  I3. segment[i].end_ct_ms

PRECONDITIONS:
  P1. CT == segment[i].end_ct_ms
  P2. Asset not yet at EOF

GUARANTEED BEHAVIORS:
  G1. Stop decoding immediately
  G2. Discard remaining asset content
  G3. Close asset handle
  G4. Transition to next segment (or fence)
  G5. No partial frame emitted past boundary

FORBIDDEN BEHAVIORS:
  F1. Continue decoding past CT boundary
  F2. Buffer remaining content
  F3. Notify Core of truncation
  F4. Extend segment duration
```

---

#### 7.2.5 CONTRACT-SEG-005: Segment Failure Propagation

```
CONTRACT: CONTRACT-SEG-005
NAME: Segment Failure Propagation
SCOPE: Any segment failure during block execution

REQUIRED INPUTS:
  I1. Segment index where failure occurred
  I2. Failure type

FAILURE TYPES:
  F1. ASSET_UNREADABLE: I/O error during decode
  F2. DECODE_ERROR: Codec failure
  F3. SEEK_FAILED: Cannot seek to asset_start_offset_ms

GUARANTEED BEHAVIORS:
  G1. Stop all output immediately
  G2. Terminate session
  G3. Return block-level error (not segment-level)
  G4. Clear all queued blocks

FORBIDDEN BEHAVIORS:
  F1. Skip to next segment
  F2. Substitute filler content
  F3. Retry failed operation
  F4. Report segment index to Core
  F5. Continue partial execution

ERROR MAPPING:
  Any segment failure → ASSET_ERROR (block-level)
  Segment index is internal diagnostic only
```

---

### 7.3 Mid-Block Join Contract

#### 7.3.1 CONTRACT-JOIN-001: Join Time Classification

```
CONTRACT: CONTRACT-JOIN-001
NAME: Join Time Classification
SCOPE: Classifying join time relative to block

REQUIRED INPUTS:
  I1. T_join: wall clock at BlockPlan receipt
  I2. start_utc_ms: block start time
  I3. end_utc_ms: block end time

CLASSIFICATION RULES (mutually exclusive, exhaustive):
  C1. T_join < start_utc_ms → EARLY
  C2. start_utc_ms <= T_join < end_utc_ms → MID_BLOCK
  C3. T_join >= end_utc_ms → STALE

GUARANTEED BEHAVIORS:
  G1. Exactly one classification applies
  G2. Classification determines execution path
  G3. STALE results in immediate rejection

FORBIDDEN BEHAVIORS:
  F1. Accept STALE block
  F2. Misclassify join time
```

---

#### 7.3.2 CONTRACT-JOIN-002: Start Offset Computation

```
CONTRACT: CONTRACT-JOIN-002
NAME: Start Offset Computation
SCOPE: Computing effective playback position for mid-join

REQUIRED INPUTS:
  I1. T_join: wall clock at receipt
  I2. start_utc_ms: block start time
  I3. segments[]: segment array

COMPUTATION (for MID_BLOCK join):
  block_elapsed_ms = T_join - start_utc_ms
  ct_start_ms = block_elapsed_ms

  Find segment i where:
    segment[i].start_ct_ms <= ct_start_ms < segment[i].end_ct_ms

  segment_elapsed_ms = ct_start_ms - segment[i].start_ct_ms
  effective_asset_offset = segment[i].asset_start_offset_ms + segment_elapsed_ms

GUARANTEED BEHAVIORS:
  G1. CT starts at ct_start_ms (not 0)
  G2. Playback begins at effective_asset_offset in segment[i]
  G3. epoch_wall_ms = start_utc_ms (always block start)

FORBIDDEN BEHAVIORS:
  F1. Set epoch to T_join
  F2. Start CT at 0 for mid-join
  F3. Skip segments before join point
```

---

### 7.4 Two-Block Lookahead Contract

#### 7.4.1 CONTRACT-LOOK-001: Queue Management

```
CONTRACT: CONTRACT-LOOK-001
NAME: Block Queue Management
SCOPE: Two-slot lookahead queue

QUEUE STRUCTURE:
  Slot 0: Executing block (or empty)
  Slot 1: Pending block (or empty)
  Maximum capacity: 2

ACCEPTANCE RULES:
  R1. Queue empty: Block goes to slot 0
  R2. Slot 0 occupied, slot 1 empty: Block goes to slot 1
  R3. Both slots occupied: Reject with QUEUE_FULL

GUARANTEED BEHAVIORS:
  G1. Never more than 2 blocks queued
  G2. Blocks execute in queue order (slot 0 first)
  G3. On fence: slot 1 promotes to slot 0

FORBIDDEN BEHAVIORS:
  F1. Queue more than 2 blocks
  F2. Execute slot 1 before slot 0 completes
  F3. Reorder queued blocks
```

---

#### 7.4.2 CONTRACT-LOOK-002: Block Contiguity

```
CONTRACT: CONTRACT-LOOK-002
NAME: Block Contiguity
SCOPE: Timing relationship between consecutive blocks

REQUIRED INPUTS:
  I1. Block N (in slot 0)
  I2. Block N+1 (delivered for slot 1)

PRECONDITION:
  P1. Block N is executing or pending

CONTIGUITY RULE:
  Block_N+1.start_utc_ms == Block_N.end_utc_ms

GUARANTEED BEHAVIORS:
  G1. Contiguous blocks accepted
  G2. Non-contiguous blocks rejected

FORBIDDEN BEHAVIORS:
  F1. Accept gap between blocks
  F2. Accept overlap between blocks

FAILURE MODE:
  E1. BLOCK_NOT_CONTIGUOUS: start != prev.end
```

---

#### 7.4.3 CONTRACT-LOOK-003: Lookahead Exhaustion

```
CONTRACT: CONTRACT-LOOK-003
NAME: Lookahead Exhaustion
SCOPE: Fence reached with empty pending slot

REQUIRED INPUTS:
  I1. Executing block reaching fence
  I2. Slot 1 state (empty or occupied)

TRIGGER:
  T_wall == executing_block.end_utc_ms AND slot_1 == empty

GUARANTEED BEHAVIORS:
  G1. Session terminates immediately
  G2. Return LOOKAHEAD_EXHAUSTED
  G3. No output after fence

FORBIDDEN BEHAVIORS:
  F1. Wait for late block
  F2. Emit filler
  F3. Extend current block
  F4. Poll Core for next block
```

---

### 7.5 Test Specification

#### 7.5.1 Block Acceptance Tests

```
TEST: TEST-BLOCK-ACCEPT-001
NAME: Valid single-segment block accepted
INPUTS:
  block_id: "B001"
  start_utc_ms: 1000000
  end_utc_ms: 1060000
  segments: [{index: 0, uri: "valid.mp4", offset: 0, duration: 60000}]
  T_receipt: 999000
  Asset "valid.mp4" exists, duration >= 60000ms
EXPECTED:
  Result: ACCEPTED
  Block queued in slot 0
ASSERTIONS:
  - Response is synchronous
  - Block accessible in queue
  - No error returned

---

TEST: TEST-BLOCK-ACCEPT-002
NAME: Stale block rejected
INPUTS:
  block_id: "B002"
  start_utc_ms: 1000000
  end_utc_ms: 1060000
  segments: [{index: 0, uri: "valid.mp4", offset: 0, duration: 60000}]
  T_receipt: 1060001
EXPECTED:
  Result: REJECTED
  Error: STALE_BLOCK_FROM_CORE
ASSERTIONS:
  - Block not queued
  - Error code is STALE_BLOCK_FROM_CORE
  - Staleness included in error (1ms)

---

TEST: TEST-BLOCK-ACCEPT-003
NAME: Duration mismatch rejected
INPUTS:
  block_id: "B003"
  start_utc_ms: 1000000
  end_utc_ms: 1060000  (60 seconds)
  segments: [
    {index: 0, uri: "a.mp4", offset: 0, duration: 30000},
    {index: 1, uri: "b.mp4", offset: 0, duration: 20000}
  ]  (sum: 50 seconds)
EXPECTED:
  Result: REJECTED
  Error: SEGMENT_DURATION_MISMATCH
ASSERTIONS:
  - Block not queued
  - Error indicates expected=60000, actual=50000

---

TEST: TEST-BLOCK-ACCEPT-004
NAME: Non-contiguous segment indices rejected
INPUTS:
  block_id: "B004"
  start_utc_ms: 1000000
  end_utc_ms: 1060000
  segments: [
    {index: 0, uri: "a.mp4", offset: 0, duration: 30000},
    {index: 2, uri: "b.mp4", offset: 0, duration: 30000}
  ]
EXPECTED:
  Result: REJECTED
  Error: INVALID_SEGMENT_INDEX
ASSERTIONS:
  - Error indicates gap at index 1

---

TEST: TEST-BLOCK-ACCEPT-005
NAME: Missing asset rejected
INPUTS:
  block_id: "B005"
  start_utc_ms: 1000000
  end_utc_ms: 1060000
  segments: [{index: 0, uri: "nonexistent.mp4", offset: 0, duration: 60000}]
EXPECTED:
  Result: REJECTED
  Error: ASSET_MISSING
ASSERTIONS:
  - Error indicates which asset is missing

---

TEST: TEST-BLOCK-ACCEPT-006
NAME: Queue full rejected
INPUTS:
  Pre-state: Slot 0 and Slot 1 both occupied
  New block: valid BlockPlan
EXPECTED:
  Result: REJECTED
  Error: QUEUE_FULL
ASSERTIONS:
  - Existing blocks unchanged
  - New block not queued
```

---

#### 7.5.2 CT Boundary Tests

```
TEST: TEST-CT-001
NAME: CT boundaries computed correctly for multi-segment block
INPUTS:
  segments: [
    {index: 0, duration: 10000},
    {index: 1, duration: 20000},
    {index: 2, duration: 30000}
  ]
EXPECTED:
  segment[0]: start_ct=0, end_ct=10000
  segment[1]: start_ct=10000, end_ct=30000
  segment[2]: start_ct=30000, end_ct=60000
ASSERTIONS:
  - segment[i].end_ct == segment[i+1].start_ct for all i
  - segment[N-1].end_ct == block_duration

---

TEST: TEST-CT-002
NAME: CT advances monotonically during execution
INPUTS:
  Block with 3 segments, total duration 60000ms
  Sample CT at 100ms intervals
EXPECTED:
  All CT samples strictly increasing
  Final CT == 60000ms at fence
ASSERTIONS:
  - ct[i+1] > ct[i] for all samples
  - No CT value appears twice
  - No CT value decreases
```

---

#### 7.5.3 Segment Transition Tests

```
TEST: TEST-TRANS-001
NAME: Transition occurs at exact CT boundary
INPUTS:
  Block with segments:
    [0] duration: 10000ms, asset: "a.mp4"
    [1] duration: 10000ms, asset: "b.mp4"
  Monitor asset reads
EXPECTED:
  Reads from "a.mp4" stop at CT=10000ms
  Reads from "b.mp4" start at CT=10000ms
ASSERTIONS:
  - No reads from "a.mp4" after CT=10000ms
  - First read from "b.mp4" at CT >= 10000ms
  - CT at transition is exactly 10000ms (±1ms tolerance)

---

TEST: TEST-TRANS-002
NAME: Output continuous across segment transition
INPUTS:
  Block with 2 segments
  Monitor output frame timestamps
EXPECTED:
  No gap in output timestamps at transition
ASSERTIONS:
  - Frame N timestamp + frame_duration == Frame N+1 timestamp
  - No duplicate timestamps
  - No missing frame intervals
```

---

#### 7.5.4 Underrun Tests

```
TEST: TEST-UNDER-001
NAME: Underrun triggers padding to CT boundary
INPUTS:
  Segment: duration=10000ms
  Asset: actual_length=8000ms (2 second underrun)
  Monitor output content
EXPECTED:
  Content frames: CT 0-8000ms
  Pad frames: CT 8000-10000ms
  Transition at CT=10000ms
ASSERTIONS:
  - Pad frames are black video, silent audio
  - Pad duration exactly 2000ms
  - No gap in output
  - CT continues advancing during pad

---

TEST: TEST-UNDER-002
NAME: Last segment underrun pads to block fence
INPUTS:
  Block: end_utc_ms = T+60000
  Final segment: duration=20000ms, asset_length=15000ms
  Monitor output and termination
EXPECTED:
  Pad from CT=40000+15000=55000 to CT=60000 (5 sec pad)
  Block completes at fence
ASSERTIONS:
  - Padding continues until fence
  - Block completes normally (not early)
  - Next block transition occurs at fence (if pending)

---

TEST: TEST-UNDER-003
NAME: Underrun does not notify Core
INPUTS:
  Segment with underrun
  Monitor Core-bound RPC traffic
EXPECTED:
  Zero RPCs during underrun handling
ASSERTIONS:
  - No RPC sent when underrun detected
  - No RPC sent during padding
  - No RPC sent at transition
```

---

#### 7.5.5 Overrun Tests

```
TEST: TEST-OVER-001
NAME: Overrun truncates at CT boundary
INPUTS:
  Segment: duration=10000ms
  Asset: actual_length=15000ms (5 second overrun)
  Monitor decoded frames
EXPECTED:
  Frames decoded: CT 0-10000ms only
  Asset content after 10000ms: not decoded
ASSERTIONS:
  - No frames emitted with CT > 10000ms from this segment
  - Transition occurs at CT=10000ms exactly
  - Remaining 5000ms of asset discarded

---

TEST: TEST-OVER-002
NAME: Overrun does not extend block
INPUTS:
  Final segment with overrun
  Monitor block completion time
EXPECTED:
  Block ends at fence (end_utc_ms)
  Excess content discarded
ASSERTIONS:
  - Block duration not extended
  - Fence respected exactly
```

---

#### 7.5.6 Failure Propagation Tests

```
TEST: TEST-FAIL-001
NAME: Mid-segment asset error terminates session
INPUTS:
  Block with 3 segments
  Segment[1] asset becomes unreadable mid-decode
EXPECTED:
  Session terminates
  Error: ASSET_ERROR (block-level)
ASSERTIONS:
  - No skip to segment[2]
  - No filler emitted
  - Session state is TERMINATED
  - Queue cleared

---

TEST: TEST-FAIL-002
NAME: Segment failure does not report segment index to Core
INPUTS:
  Segment[2] fails
  Monitor error response to Core
EXPECTED:
  Error code: ASSET_ERROR
  No segment index in error
ASSERTIONS:
  - Error is block-level only
  - Segment index not in response payload
```

---

#### 7.5.7 Mid-Block Join Tests

```
TEST: TEST-JOIN-001
NAME: Early join waits for block start
INPUTS:
  Block: start_utc_ms=1000000
  T_join: 999000 (1 second early)
EXPECTED:
  Wait 1000ms
  Begin at CT=0, asset_offset=0
  epoch_wall_ms = 1000000
ASSERTIONS:
  - No output before T=1000000
  - First frame at T=1000000
  - CT=0 at first frame

---

TEST: TEST-JOIN-002
NAME: Mid-block join computes correct offset
INPUTS:
  Block: start_utc_ms=1000000, duration=60000
  Segments: [
    {index: 0, duration: 30000, asset_offset: 0},
    {index: 1, duration: 30000, asset_offset: 0}
  ]
  T_join: 1045000 (45 seconds into block)
EXPECTED:
  ct_start = 45000
  Current segment = 1 (CT 30000-60000)
  segment_elapsed = 15000
  Begin at segment[1], asset_offset=15000
ASSERTIONS:
  - CT at first frame = 45000ms
  - Playing from segment[1]
  - epoch_wall_ms = 1000000 (block start, not join time)

---

TEST: TEST-JOIN-003
NAME: Stale block rejected
INPUTS:
  Block: end_utc_ms=1000000
  T_join: 1000001
EXPECTED:
  Immediate rejection
  Error: STALE_BLOCK_FROM_CORE
ASSERTIONS:
  - No execution attempted
  - Block not queued
```

---

#### 7.5.8 Lookahead Tests

```
TEST: TEST-LOOK-001
NAME: Fence transition with pending block
INPUTS:
  Slot 0: Block A, end_utc_ms=1060000
  Slot 1: Block B, start_utc_ms=1060000
  T_wall reaches 1060000
EXPECTED:
  Block A completes
  Block B promoted to slot 0
  Block B execution begins
ASSERTIONS:
  - No output gap at fence
  - CT continues (block-relative reset for B)
  - Slot 1 now empty

---

TEST: TEST-LOOK-002
NAME: Fence with empty pending slot terminates
INPUTS:
  Slot 0: Block A, end_utc_ms=1060000
  Slot 1: empty
  T_wall reaches 1060000
EXPECTED:
  Session terminates
  Error: LOOKAHEAD_EXHAUSTED
ASSERTIONS:
  - No output after fence
  - No waiting for late block
  - Session state is TERMINATED

---

TEST: TEST-LOOK-003
NAME: Block contiguity enforced
INPUTS:
  Slot 0: Block A, end_utc_ms=1060000
  Delivered: Block B, start_utc_ms=1060001 (1ms gap)
EXPECTED:
  Block B rejected
  Error: BLOCK_NOT_CONTIGUOUS
ASSERTIONS:
  - Gap detected (expected 1060000, got 1060001)
  - Block B not queued

---

TEST: TEST-LOOK-004
NAME: Late block after fence rejected
INPUTS:
  Session terminated due to LOOKAHEAD_EXHAUSTED at T=1060000
  Block B delivered at T=1060500
EXPECTED:
  Block B rejected
  Error: SESSION_TERMINATED
ASSERTIONS:
  - No resurrection of terminated session
  - Block not queued
```

---

#### 7.5.9 Determinism Tests

```
TEST: TEST-DET-001
NAME: Same inputs produce identical CT sequence
INPUTS:
  Same BlockPlan executed twice
  Same T_join
  Same assets
EXPECTED:
  Identical CT sample sequences
ASSERTIONS:
  - CT[i] from run 1 == CT[i] from run 2 for all samples
  - Frame count identical
  - Transition points identical

---

TEST: TEST-DET-002
NAME: Underrun padding is deterministic
INPUTS:
  Same underrun scenario executed twice
EXPECTED:
  Identical pad frame count
  Identical transition CT
ASSERTIONS:
  - Pad duration identical
  - No variance in timing

---

TEST: TEST-DET-003
NAME: No wall-clock dependency in segment transitions
INPUTS:
  Block executed with artificial clock
  Same block executed with real clock (same logical time)
EXPECTED:
  Segment transitions at same CT values
ASSERTIONS:
  - CT triggers transition, not wall clock
  - Transition CT independent of clock source
```

---

### 7.6 Contract-Test Traceability Matrix

```
┌──────────────────────┬────────────────────────────────────────────┐
│ CONTRACT             │ TESTS                                      │
├──────────────────────┼────────────────────────────────────────────┤
│ CONTRACT-BLOCK-001   │ TEST-BLOCK-ACCEPT-001 through 006          │
│ CONTRACT-BLOCK-002   │ TEST-CT-002, TEST-DET-001                  │
│ CONTRACT-BLOCK-003   │ TEST-LOOK-001, TEST-LOOK-002               │
│ CONTRACT-SEG-001     │ TEST-CT-001                                │
│ CONTRACT-SEG-002     │ TEST-TRANS-001, TEST-TRANS-002             │
│ CONTRACT-SEG-003     │ TEST-UNDER-001, TEST-UNDER-002, 003        │
│ CONTRACT-SEG-004     │ TEST-OVER-001, TEST-OVER-002               │
│ CONTRACT-SEG-005     │ TEST-FAIL-001, TEST-FAIL-002               │
│ CONTRACT-JOIN-001    │ TEST-JOIN-001, TEST-JOIN-003               │
│ CONTRACT-JOIN-002    │ TEST-JOIN-002                              │
│ CONTRACT-LOOK-001    │ TEST-BLOCK-ACCEPT-006, TEST-LOOK-001       │
│ CONTRACT-LOOK-002    │ TEST-LOOK-003                              │
│ CONTRACT-LOOK-003    │ TEST-LOOK-002, TEST-LOOK-004               │
└──────────────────────┴────────────────────────────────────────────┘
```

---

### 7.7 Contract Summary

```
┌─────────────────────────────────────────────────────────────────┐
│              BLOCKPLAN EXECUTION CONTRACTS                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  BLOCK-LEVEL (3 contracts):                                     │
│    CONTRACT-BLOCK-001: Acceptance preconditions                 │
│    CONTRACT-BLOCK-002: Execution lifecycle                      │
│    CONTRACT-BLOCK-003: Fence enforcement                        │
│                                                                 │
│  SEGMENT-LEVEL (5 contracts):                                   │
│    CONTRACT-SEG-001: CT boundary derivation                     │
│    CONTRACT-SEG-002: Segment transition                         │
│    CONTRACT-SEG-003: Underrun (pad-to-CT)                       │
│    CONTRACT-SEG-004: Overrun (truncate)                         │
│    CONTRACT-SEG-005: Failure propagation                        │
│                                                                 │
│  JOIN (2 contracts):                                            │
│    CONTRACT-JOIN-001: Join time classification                  │
│    CONTRACT-JOIN-002: Start offset computation                  │
│                                                                 │
│  LOOKAHEAD (3 contracts):                                       │
│    CONTRACT-LOOK-001: Queue management                          │
│    CONTRACT-LOOK-002: Block contiguity                          │
│    CONTRACT-LOOK-003: Lookahead exhaustion                      │
│                                                                 │
│  TOTAL: 13 contracts, 27 tests                                  │
│                                                                 │
│  COVERAGE:                                                      │
│    Every contract has ≥1 test                                   │
│    Every test traces to ≥1 contract                             │
│    All tests are deterministic and repeatable                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 8. Governance: Frozen Contracts, Extension Points, and Forbidden Extensions

This section establishes change governance for the BlockPlan execution model. Its purpose is to prevent accidental erosion of determinism, authority separation, and broadcast authenticity.

---

### 8.1 Frozen Contracts

Frozen contracts are foundational invariants that **MUST NOT change** without a breaking-version declaration. Any modification to these elements constitutes a breaking change requiring:
- Explicit version bump (major version)
- Migration documentation
- Deprecation period for existing implementations

---

#### 8.1.1 Timing Authority

```
FROZEN: CT Single-Writer Rule
SOURCE: Section 1.2 (LAW-CT-SINGLE-WRITER)

STATEMENT:
  AIR is the exclusive writer of Content Time.
  Core never modifies CT.

WHY FROZEN:
  CT is the timing backbone of the entire execution model. If CT could be
  written from multiple sources, determinism becomes impossible. Two viewers
  watching the same channel would see different content at the same wall-clock
  instant. This would violate the fundamental broadcast simulation premise.

CONSEQUENCE OF VIOLATION:
  - Non-deterministic playback
  - Viewer desynchronization
  - Untestable execution
  - Loss of reproducibility

FROZEN ELEMENTS:
  ✗ Cannot add CT write API to Core
  ✗ Cannot allow CT adjustment via RPC
  ✗ Cannot derive CT from external time source during execution
  ✗ Cannot allow multiple CT writers within AIR
```

---

```
FROZEN: Epoch Immutability
SOURCE: Section 1.1 (INV-P8-005)

STATEMENT:
  Epoch is established once at session start and never modified.

WHY FROZEN:
  Epoch anchors all CT calculations. Changing epoch mid-session would
  cause CT discontinuity, violating monotonicity. Viewer A who joined
  before the change would have different CT than viewer B who joined after.

CONSEQUENCE OF VIOLATION:
  - CT discontinuity
  - Monotonicity violation
  - Mid-session viewer desync
  - As-run logging corruption

FROZEN ELEMENTS:
  ✗ Cannot add epoch refresh API
  ✗ Cannot adjust epoch for drift correction
  ✗ Cannot set epoch to join time (must be block start)
```

---

```
FROZEN: Monotonic CT Advancement
SOURCE: Section 1.3 (INV-P8-TIMELINE-MONOTONIC)

STATEMENT:
  CT never decreases. CT(t+1) > CT(t) always.

WHY FROZEN:
  Monotonicity is required for PTS/DTS ordering in MPEG-TS output.
  Non-monotonic CT would produce invalid transport streams that
  decoders cannot play. This is not a design choice; it's a format
  requirement.

CONSEQUENCE OF VIOLATION:
  - Invalid MPEG-TS output
  - Decoder failures
  - Playback artifacts
  - A/V desync

FROZEN ELEMENTS:
  ✗ Cannot allow CT to decrease
  ✗ Cannot allow CT to pause
  ✗ Cannot allow CT to jump backward
  ✗ Cannot reset CT mid-block
```

---

#### 8.1.2 Block Structure

```
FROZEN: Duration Sum Invariant
SOURCE: Section 5.2 (INV-BLOCKPLAN-DURATION-SUM)

STATEMENT:
  Σ segment[i].segment_duration_ms == (end_utc_ms - start_utc_ms)

WHY FROZEN:
  This invariant guarantees that CT boundaries can be computed
  deterministically at block acceptance time. If durations don't sum
  to block duration, either some CT range is unmapped (gap) or
  multiply-mapped (overlap). Both break execution.

CONSEQUENCE OF VIOLATION:
  - Undefined CT behavior at gap/overlap
  - Non-deterministic segment transitions
  - Block fence mismatch

FROZEN ELEMENTS:
  ✗ Cannot accept blocks where sum ≠ duration
  ✗ Cannot "auto-adjust" segment durations
  ✗ Cannot allow "flexible" final segment
```

---

```
FROZEN: Segment Index Contiguity
SOURCE: Section 5.3, CONTRACT-SEG-001

STATEMENT:
  Segment indices must be [0, 1, 2, ..., N-1] with no gaps.

WHY FROZEN:
  Execution order is defined by index order. Gaps create ambiguity:
  what happens when index 1 is missing? The only safe answer is
  rejection. Allowing sparse indices would require execution-time
  decisions about ordering, breaking determinism.

CONSEQUENCE OF VIOLATION:
  - Undefined execution order
  - Potential infinite loop or skip
  - Non-deterministic behavior

FROZEN ELEMENTS:
  ✗ Cannot allow sparse indices
  ✗ Cannot allow out-of-order indices
  ✗ Cannot infer missing indices
```

---

```
FROZEN: CT Boundary Derivation
SOURCE: Section 5.4, CONTRACT-SEG-001

STATEMENT:
  Segment boundaries are computed from cumulative durations, not
  wall clock, not asset duration, not runtime measurement.

WHY FROZEN:
  CT boundaries must be known at block acceptance time. If boundaries
  were derived from actual asset playback, they would vary based on
  decode timing, creating non-determinism. The schedule is the truth;
  assets conform to it.

CONSEQUENCE OF VIOLATION:
  - Non-deterministic transitions
  - Asset-dependent timing
  - Untestable execution

FROZEN ELEMENTS:
  ✗ Cannot derive boundaries from wall clock
  ✗ Cannot derive boundaries from asset EOF
  ✗ Cannot recompute boundaries during execution
```

---

#### 8.1.3 Failure Semantics

```
FROZEN: No Segment-Level Recovery
SOURCE: Section 5.8 (INV-BLOCKPLAN-NO-SEGMENT-RECOVERY)

STATEMENT:
  Any segment failure terminates the session. No skip, no retry,
  no substitution.

WHY FROZEN:
  Recovery logic introduces branching. Branching introduces
  non-determinism. If segment 2 fails and we skip to segment 3,
  the output is different than if segment 2 succeeded. This is
  acceptable in VOD; it is unacceptable in broadcast simulation
  where all viewers see the same stream.

CONSEQUENCE OF VIOLATION:
  - Viewer-dependent output
  - Non-deterministic playback
  - Untestable execution paths

FROZEN ELEMENTS:
  ✗ Cannot skip failed segments
  ✗ Cannot substitute filler for failed segments
  ✗ Cannot retry failed segments
  ✗ Cannot fall back to alternate assets
```

---

```
FROZEN: Lookahead Exhaustion = Termination
SOURCE: Section 4.5, CONTRACT-LOOK-003

STATEMENT:
  If fence is reached with no pending block, session terminates
  immediately. No waiting, no filler, no polling.

WHY FROZEN:
  Waiting introduces wall-clock dependency into execution.
  Different wait durations would produce different outputs.
  Filler would produce viewer-dependent content (some see filler,
  others don't). Both violate broadcast authenticity.

CONSEQUENCE OF VIOLATION:
  - Wall-clock dependent execution
  - Viewer-dependent content
  - Non-deterministic output length

FROZEN ELEMENTS:
  ✗ Cannot wait for late block
  ✗ Cannot emit filler while waiting
  ✗ Cannot poll Core for missing block
  ✗ Cannot extend block past fence
```

---

#### 8.1.4 Authority Boundary

```
FROZEN: Block-Level Reporting Only
SOURCE: Section 5.9 (Segment Information Firewall)

STATEMENT:
  AIR reports block-level events only. Segment events are internal.

WHY FROZEN:
  If segment events crossed the Core↔AIR boundary, Core might
  start making segment-level decisions. This would blur authority
  separation. Segment execution is AIR's domain; exposing it
  invites inappropriate coordination.

CONSEQUENCE OF VIOLATION:
  - Authority leakage
  - Potential for segment-level RPCs
  - Increased coupling
  - Path to dynamic insertion

FROZEN ELEMENTS:
  ✗ Cannot report segment start/complete to Core
  ✗ Cannot report underrun/overrun to Core
  ✗ Cannot report segment index to Core
  ✗ Cannot expose segment progress via API
```

---

```
FROZEN: No Core Communication During Execution
SOURCE: Section 2.2 (Phase 3: EXECUTE), CONTRACT-BLOCK-002

STATEMENT:
  Once block execution begins, AIR does not communicate with Core
  until block completion or failure.

WHY FROZEN:
  Runtime coordination enables runtime decisions. Runtime decisions
  break determinism. The BlockPlan must contain everything needed
  for execution. If mid-execution communication is allowed, the
  temptation to add "just one small query" becomes irresistible.

CONSEQUENCE OF VIOLATION:
  - Path to dynamic segment modification
  - Network-dependent execution
  - Non-deterministic on network failure

FROZEN ELEMENTS:
  ✗ Cannot add mid-execution RPC
  ✗ Cannot poll Core for segment info
  ✗ Cannot request asset substitution
  ✗ Cannot send progress updates during execution
```

---

#### 8.1.5 Fence Semantics

```
FROZEN: Hard Block Fence
SOURCE: Section 4.4, CONTRACT-BLOCK-003

STATEMENT:
  Block ends at exactly end_utc_ms. Not before (except failure),
  not after (ever).

WHY FROZEN:
  Block boundaries are the synchronization points for multi-viewer
  broadcast simulation. All viewers on a channel see the same
  block transition at the same wall-clock instant. Soft fences
  would allow drift, breaking synchronization.

CONSEQUENCE OF VIOLATION:
  - Viewer desynchronization
  - EPG/as-run mismatch
  - Unpredictable block duration

FROZEN ELEMENTS:
  ✗ Cannot extend block past fence
  ✗ Cannot end block early (except failure)
  ✗ Cannot make fence "approximate"
```

---

```
FROZEN: Hard Segment CT Boundaries
SOURCE: Section 5.6, 5.7 (Underrun/Overrun)

STATEMENT:
  Segments end at their computed CT boundary, regardless of asset
  length. Underrun pads; overrun truncates.

WHY FROZEN:
  Segment boundaries derive from the schedule, not from content.
  If a 30-second ad slot plays a 25-second ad, the slot is still
  30 seconds. This is how broadcast works. Asset length is a
  content-plane concern; timing is a transport-plane concern.

CONSEQUENCE OF VIOLATION:
  - Schedule-dependent output
  - Non-deterministic block duration
  - Cascade timing errors

FROZEN ELEMENTS:
  ✗ Cannot extend segment for long asset
  ✗ Cannot shorten segment for short asset
  ✗ Cannot "auto-fit" asset to segment
```

---

### 8.2 Extension Points

Extension points are areas **explicitly designed** for future evolution without breaking frozen contracts. Extensions in these areas are permitted and expected.

---

#### 8.2.1 Metadata Extensions

```
EXTENSION POINT: Segment Metadata
SOURCE: Section 6.4 (Metadata vs Execution)

PERMITTED EXTENSIONS:
  + Add new metadata fields to segments
  + Add content_type values (e.g., "promo", "bumper", "station_id")
  + Add external reference IDs
  + Add scheduling hints for Core's use
  + Add as-run logging annotations

WHY EXTENSIBLE:
  Metadata does not affect execution. AIR ignores it
  (INV-BLOCKPLAN-METADATA-IGNORED). Core can attach any
  metadata it needs for scheduling, logging, or EPG without
  changing AIR's behavior.

CONSTRAINTS:
  - Metadata must not alter execution path
  - AIR must not branch on metadata values
  - New fields must be optional (backward compatible)

EXAMPLES:
  metadata.content_type = "ad"           // OK: ignored by AIR
  metadata.advertiser_id = "acme-corp"   // OK: for as-run logging
  metadata.epg_title = "Commercial"      // OK: for EPG display
```

---

```
EXTENSION POINT: Block Metadata
SOURCE: Implied by segment metadata pattern

PERMITTED EXTENSIONS:
  + Add block-level metadata fields
  + Add scheduling context
  + Add debugging/tracing identifiers
  + Add Core-side annotations

WHY EXTENSIBLE:
  Same rationale as segment metadata. Block metadata travels
  with the BlockPlan but does not affect execution.

CONSTRAINTS:
  - Must not affect execution timing
  - Must not affect segment ordering
  - Must not affect failure handling

EXAMPLES:
  block.metadata.schedule_source = "prime-time-grid"
  block.metadata.trace_id = "abc123"
  block.metadata.generated_at = 1704067200000
```

---

#### 8.2.2 Error Code Extensions

```
EXTENSION POINT: Failure Codes
SOURCE: Section 7.1.1 (Failure Modes)

PERMITTED EXTENSIONS:
  + Add new error codes for specific failure conditions
  + Add error detail fields
  + Add diagnostic information in errors

WHY EXTENSIBLE:
  More specific error codes improve debugging without changing
  failure semantics. The contract "segment failure = block failure"
  remains; we're just naming failures more precisely.

CONSTRAINTS:
  - All failures must still terminate session
  - No error code implies recovery
  - Error codes remain block-level (not segment-level to Core)

EXAMPLES:
  ASSET_MISSING              // existing
  ASSET_MISSING_SEGMENT_0    // NOT OK: exposes segment index
  ASSET_CORRUPT              // OK: more specific than ASSET_ERROR
  DECODE_UNSUPPORTED_CODEC   // OK: diagnostic detail
  SEEK_BEYOND_EOF            // OK: specific seek failure
```

---

#### 8.2.3 Diagnostic Extensions

```
EXTENSION POINT: AIR Internal Logging
SOURCE: Section 5.10 (AIR Internal Logging)

PERMITTED EXTENSIONS:
  + Add segment-level diagnostic logs
  + Add timing instrumentation
  + Add performance metrics
  + Add debug trace points

WHY EXTENSIBLE:
  Internal diagnostics don't cross the Core↔AIR boundary.
  AIR can log anything useful for debugging as long as
  it doesn't affect execution or report to Core.

CONSTRAINTS:
  - Logs must not be sent to Core
  - Logging must not block execution
  - Log presence must not change behavior

EXAMPLES:
  [DEBUG] Segment 2 transition at CT=45000ms     // OK
  [TRACE] Frame decode time: 2.3ms               // OK
  [PERF] Queue depth: video=5, audio=8           // OK
```

---

```
EXTENSION POINT: Telemetry and Metrics
SOURCE: Implied by diagnostic pattern

PERMITTED EXTENSIONS:
  + Add Prometheus/OpenMetrics endpoints
  + Add execution statistics
  + Add health indicators
  + Add performance counters

WHY EXTENSIBLE:
  Observability is important for operations. Metrics can expose
  internal state without affecting execution, as long as they're
  pull-based (scrape) not push-based (callback).

CONSTRAINTS:
  - Metrics must be pull-based, not push-based
  - Metrics must not block execution to emit
  - Segment-level metrics permitted (they're for AIR ops, not Core)

EXAMPLES:
  air_block_execution_duration_seconds
  air_segment_transitions_total
  air_underrun_pad_duration_seconds
  air_overrun_truncate_seconds
```

---

#### 8.2.4 Asset Extensions

```
EXTENSION POINT: Asset URI Schemes
SOURCE: Implied by asset_uri field

PERMITTED EXTENSIONS:
  + Add new URI schemes (file://, http://, s3://)
  + Add asset caching strategies
  + Add asset preloading hints
  + Add asset validation hooks

WHY EXTENSIBLE:
  How assets are fetched doesn't affect execution timing.
  Asset must be available at decode time; how it got there
  is an implementation detail.

CONSTRAINTS:
  - Asset must be fully available before segment starts
  - Fetch failures must be detected at acceptance time
  - No streaming/progressive fetch during execution

EXAMPLES:
  asset_uri: "file:///media/show.mp4"           // local file
  asset_uri: "s3://bucket/show.mp4"             // cloud storage
  asset_uri: "cache://abc123"                   // pre-cached
```

---

#### 8.2.5 Output Extensions

```
EXTENSION POINT: Output Format Configuration
SOURCE: Implied by execution model

PERMITTED EXTENSIONS:
  + Add output format options (resolution, bitrate, codec)
  + Add container format options
  + Add transport options

WHY EXTENSIBLE:
  Output format is orthogonal to timing. A block can be
  encoded to 1080p or 720p; the CT boundaries don't change.

CONSTRAINTS:
  - Format must be fixed for session lifetime
  - Format change requires new session
  - Format must not affect timing derivation

EXAMPLES:
  output.resolution = "1920x1080"
  output.video_codec = "h264"
  output.audio_codec = "aac"
  output.container = "mpegts"
```

---

### 8.3 Forbidden Extensions

Forbidden extensions are changes that **would violate core invariants** even if they appear useful. These are explicitly prohibited regardless of justification.

---

#### 8.3.1 Dynamic Content Modifications

```
FORBIDDEN: Dynamic Ad Insertion (DAI)
VIOLATES: CONTRACT-BLOCK-002 (no Core communication during execution)
          INV-BLOCKPLAN-NO-SEGMENT-RECOVERY (no substitution)

DESCRIPTION:
  Replacing scheduled ad segments with dynamically-selected ads
  at runtime based on viewer profile, inventory, or bidding.

WHY FORBIDDEN:
  DAI requires runtime decisions: "which ad for this viewer?"
  Different viewers get different ads. The output is no longer
  deterministic. This fundamentally breaks broadcast simulation
  where all viewers see the same channel.

EVEN IF:
  "We could make it deterministic per-viewer" → Still violates
  single-stream-per-channel model.

  "We could pre-compute the decision" → Then it's not dynamic;
  put it in the BlockPlan at schedule time.

REMAINS FORBIDDEN: Always
```

---

```
FORBIDDEN: Mid-Block Segment Mutation
VIOLATES: CONTRACT-BLOCK-002 (BlockPlan immutable after acceptance)
          Frozen: CT boundary derivation

DESCRIPTION:
  Modifying segment list, durations, or assets after block
  execution has begun.

WHY FORBIDDEN:
  CT boundaries are computed at acceptance. If segments change,
  boundaries become invalid. Either we recompute (breaking
  determinism) or we ignore changes (then why allow them?).

EVEN IF:
  "Just for the next segment" → Boundaries are interdependent.
  Changing segment 3 affects segment 4's start_ct.

  "Only to fix errors" → Error handling is termination, not
  mutation.

REMAINS FORBIDDEN: Always
```

---

```
FORBIDDEN: Segment Skipping
VIOLATES: INV-BLOCKPLAN-NO-SEGMENT-RECOVERY
          CONTRACT-SEG-002 (execute in order)

DESCRIPTION:
  Skipping a segment due to error, timeout, or policy decision.

WHY FORBIDDEN:
  Skipping changes output. Viewer A (segment succeeded) sees
  different content than viewer B (segment skipped). The output
  is no longer deterministic. Schedules become unreliable.

EVEN IF:
  "Better than black screen" → No. Failure is failure.
  Core should not schedule unreliable assets.

  "Only for ads, not content" → AIR doesn't distinguish.
  Segment is segment.

REMAINS FORBIDDEN: Always
```

---

#### 8.3.2 Timing Modifications

```
FORBIDDEN: CT Adjustment / Correction
VIOLATES: Frozen: Epoch immutability
          Frozen: Monotonic CT advancement

DESCRIPTION:
  Adjusting CT to correct for drift, sync with external source,
  or align with wall clock.

WHY FORBIDDEN:
  CT is derived from epoch + elapsed monotonic time. Any
  "correction" introduces discontinuity. PTS values would
  jump or repeat, producing invalid MPEG-TS.

EVEN IF:
  "Drift is accumulating" → Drift beyond tolerance = session
  termination. Correct by starting new session.

  "NTP correction" → CT is not wall time. CT is content time.
  They are independent clocks.

REMAINS FORBIDDEN: Always
```

---

```
FORBIDDEN: Playback Speed Adjustment
VIOLATES: Frozen: Monotonic CT advancement (rate change)
          Frozen: Hard block fence

DESCRIPTION:
  Speeding up or slowing down playback to "catch up" or "sync"
  with wall clock or other reference.

WHY FORBIDDEN:
  Speed changes alter the relationship between CT and wall clock.
  Viewer A at 1.0x and viewer B at 1.05x would see different
  content at the same wall-clock instant. Block fences would
  occur at different wall times.

EVEN IF:
  "To correct schedule drift" → Drift is a scheduling problem.
  Solve in Core, not AIR.

  "Imperceptible 0.1% adjustment" → Determinism is binary.
  Either CT = monotonic elapsed, or it doesn't.

REMAINS FORBIDDEN: Always
```

---

```
FORBIDDEN: Wall-Clock Segment Transitions
VIOLATES: CONTRACT-SEG-001 (CT-derived boundaries)
          Frozen: CT boundary derivation

DESCRIPTION:
  Triggering segment transitions based on wall-clock time
  rather than CT reaching the boundary.

WHY FORBIDDEN:
  Wall clock varies (NTP, leap seconds, VM clock drift).
  CT is deterministic (monotonic local clock). Using wall
  clock for transitions makes output dependent on time source.

EVEN IF:
  "For better sync with broadcast schedule" → Block fences
  are wall-clock. Segment boundaries are CT. This separation
  is intentional.

REMAINS FORBIDDEN: Always
```

---

#### 8.3.3 Recovery Mechanisms

```
FORBIDDEN: Filler Substitution
VIOLATES: INV-BLOCKPLAN-NO-SEGMENT-RECOVERY
          CONTRACT-LOOK-003 (no filler on lookahead exhaustion)

DESCRIPTION:
  Replacing missing or failed content with pre-defined filler
  (e.g., "technical difficulties" slate, color bars).

WHY FORBIDDEN:
  Filler is content substitution. Different viewers might see
  filler at different times (based on when their failure occurred).
  Output is no longer deterministic. Filler also masks failures
  that should be visible.

EVEN IF:
  "Better user experience" → This is broadcast simulation, not
  VOD. Broadcast failures are visible. That's authentic.

  "Just for transient issues" → Transient = terminate + restart.
  Not substitute.

PERMITTED ALTERNATIVE:
  Underrun padding (black/silence) is NOT filler. Padding
  maintains timing; filler substitutes content. Padding is
  required; filler is forbidden.

REMAINS FORBIDDEN: Always
```

---

```
FORBIDDEN: Waiting for Late Blocks
VIOLATES: CONTRACT-LOOK-003 (immediate termination)
          Frozen: Hard block fence

DESCRIPTION:
  Pausing at fence to wait for late block delivery instead
  of terminating.

WHY FORBIDDEN:
  Wait duration is non-deterministic (depends on network, Core
  load, etc.). Different viewers might wait different amounts.
  Some might receive the late block; others might not. Output
  diverges.

EVEN IF:
  "Just 100ms grace period" → 100ms is ~3 frames. Either we
  emit those frames or we don't. Both break determinism.

  "Core is usually fast" → Contract cannot depend on "usually".

REMAINS FORBIDDEN: Always
```

---

```
FORBIDDEN: Asset Retry
VIOLATES: INV-BLOCKPLAN-NO-SEGMENT-RECOVERY
          CONTRACT-SEG-005 (failure = termination)

DESCRIPTION:
  Retrying a failed asset read/decode operation before giving up.

WHY FORBIDDEN:
  Retry introduces variable latency. First attempt fails, second
  succeeds after 50ms. Now execution is 50ms behind schedule.
  Do we skip frames to catch up? (forbidden) Do we emit late?
  (breaks CT/wall-clock relationship)

EVEN IF:
  "Network glitch, would succeed on retry" → Use reliable
  asset delivery. Pre-cache. Validate at acceptance time.

REMAINS FORBIDDEN: Always
```

---

#### 8.3.4 Authority Violations

```
FORBIDDEN: Segment-Level RPC
VIOLATES: Frozen: Block-level reporting only
          Frozen: No Core communication during execution

DESCRIPTION:
  Any RPC between AIR and Core that operates at segment
  granularity (start segment, complete segment, segment error).

WHY FORBIDDEN:
  Segment-level RPC is the gateway drug to segment-level
  coordination. Once Core knows when segments start, it can
  start making segment-level decisions. Authority separation
  erodes incrementally.

EVEN IF:
  "Just for logging/as-run" → Log locally in AIR. Core can
  query after block completes, or parse AIR logs.

  "Core needs to know which ad played" → Core scheduled it.
  Core knows. If execution completed, ads played in order.

REMAINS FORBIDDEN: Always
```

---

```
FORBIDDEN: Content-Type Execution Branching
VIOLATES: INV-BLOCKPLAN-TYPE-BLIND
          INV-BLOCKPLAN-METADATA-IGNORED

DESCRIPTION:
  Any execution logic that behaves differently based on whether
  a segment is "content", "ad", "promo", etc.

WHY FORBIDDEN:
  Branching on content type means different code paths for
  different segments. Different code paths can have different
  bugs, different timing characteristics. Uniform execution
  is simpler and more reliable.

EVEN IF:
  "Ads need different error handling" → No. Segment failure
  is segment failure. Type doesn't matter.

  "Promos can be skipped if behind schedule" → No skipping.
  Ever. For any reason.

REMAINS FORBIDDEN: Always
```

---

```
FORBIDDEN: Core-Directed Timing
VIOLATES: LAW-CT-SINGLE-WRITER
          CONTRACT-BLOCK-002 (no Core communication during execution)

DESCRIPTION:
  Core sending timing instructions to AIR during execution
  (e.g., "speed up", "pause", "skip to CT=X").

WHY FORBIDDEN:
  This would make Core a CT writer, violating single-writer.
  It would also require mid-execution communication, violating
  the execution isolation contract.

EVEN IF:
  "For live event sync" → BlockPlan model doesn't do live.
  Live is a different architecture.

  "Emergency override" → Emergency = terminate session.
  Not mid-flight control.

REMAINS FORBIDDEN: Always
```

---

### 8.4 Governance Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                    CHANGE GOVERNANCE MATRIX                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  FROZEN (13 items) — Breaking change if modified:               │
│                                                                 │
│    TIMING AUTHORITY:                                            │
│      • CT single-writer rule                                    │
│      • Epoch immutability                                       │
│      • Monotonic CT advancement                                 │
│                                                                 │
│    BLOCK STRUCTURE:                                             │
│      • Duration sum invariant                                   │
│      • Segment index contiguity                                 │
│      • CT boundary derivation                                   │
│                                                                 │
│    FAILURE SEMANTICS:                                           │
│      • No segment-level recovery                                │
│      • Lookahead exhaustion = termination                       │
│                                                                 │
│    AUTHORITY BOUNDARY:                                          │
│      • Block-level reporting only                               │
│      • No Core communication during execution                   │
│                                                                 │
│    FENCE SEMANTICS:                                             │
│      • Hard block fence                                         │
│      • Hard segment CT boundaries                               │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  EXTENSIBLE (5 areas) — Safe to extend:                         │
│                                                                 │
│      • Segment metadata                                         │
│      • Block metadata                                           │
│      • Error codes (block-level)                                │
│      • AIR internal diagnostics                                 │
│      • Asset URI schemes                                        │
│      • Output format configuration                              │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  FORBIDDEN (12 items) — Never implement:                        │
│                                                                 │
│    DYNAMIC CONTENT:                                             │
│      • Dynamic ad insertion                                     │
│      • Mid-block segment mutation                               │
│      • Segment skipping                                         │
│                                                                 │
│    TIMING MODIFICATIONS:                                        │
│      • CT adjustment/correction                                 │
│      • Playback speed adjustment                                │
│      • Wall-clock segment transitions                           │
│                                                                 │
│    RECOVERY MECHANISMS:                                         │
│      • Filler substitution                                      │
│      • Waiting for late blocks                                  │
│      • Asset retry                                              │
│                                                                 │
│    AUTHORITY VIOLATIONS:                                        │
│      • Segment-level RPC                                        │
│      • Content-type execution branching                         │
│      • Core-directed timing                                     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

### 8.5 Governance Enforcement

```
ENFORCEMENT MECHANISMS:

  1. CONTRACT TESTS (Section 7)
     Every frozen contract has associated tests.
     CI must run all contract tests on every change.
     Failing contract test = blocked merge.

  2. CODE REVIEW CHECKLIST
     For any change to AIR execution:
       □ Does this modify a frozen contract?
       □ Does this add a forbidden extension?
       □ Does this use an extension point correctly?
     If any frozen/forbidden box is checked, reject.

  3. ARCHITECTURE DECISION RECORDS (ADR)
     Any proposal that touches frozen contracts requires:
       - Written ADR with rationale
       - Explicit acknowledgment of breaking change
       - Migration plan
       - Version bump plan

  4. INVARIANT COMMENTS IN CODE
     Frozen contracts should be marked in source:
       // FROZEN: INV-BLOCKPLAN-DURATION-SUM
       // See docs/architecture/proposals/BlockLevelPlayoutAutonomy.md §8.1.2
     Modifying code near such comments requires justification.

  5. DOCUMENT VERSIONING
     This document is versioned.
     Changes to Section 8 require explicit approval.
     Frozen items cannot be unfrozen without major version.
```

---

## Document History

| Date | Change |
|------|--------|
| 2026-02-05 | Initial consolidation of exploratory work |
| 2026-02-05 | Added multi-segment block semantics (Section 5) |
| 2026-02-05 | Added commercials/interstitials as segments (Section 6) |
| 2026-02-05 | Added formal contracts and test specification (Section 7) |
| 2026-02-05 | Added governance: frozen/extensible/forbidden (Section 8) |
