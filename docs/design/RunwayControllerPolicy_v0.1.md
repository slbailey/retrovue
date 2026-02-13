# Runway Controller Policy — Design Document v0.1

**Status:** Design (Guidance Only)
**Version:** 0.1

**Classification:** Design Document (Feed-Ahead Evolution)
**Scope:** Core Runtime — BlockPlanProducer feed-ahead policy
**Satisfies:** RunwayReadinessContract_v0.1 (INV-RUNWAY-001 through INV-RUNWAY-005)
**Does Not Modify:** HorizonManager, TransmissionLogSeamContract, AsRunReconciliationContract, INV-FEED-QUEUE-DISCIPLINE

---

## 1. Purpose

This document describes why the current feed-ahead policy is insufficient to satisfy RunwayReadinessContract_v0.1, and how feed-ahead must evolve from reactive, event-driven block delivery toward continuous runway-based readiness control.

This is design guidance. It does not prescribe APIs, define contracts, or contain implementation. It prepares the ground for replacing the reactive feed-ahead model with a runway-aware controller.

---

## 2. Current Feed-Ahead Model and Its Limitations

### 2.1 How Feed-Ahead Works Today

The current BlockPlanProducer delivers blocks to AIR through two mechanisms:

1. **Event-driven:** On `BLOCK_COMPLETE`, Core retries any pending block, then generates and feeds the next block. This is the primary path.
2. **Tick-driven:** At ~4 Hz, Core evaluates whether a deadline or runway trigger requires feeding. This is a secondary safety net.

The queue discipline (INV-FEED-QUEUE-001 through 005) ensures correct sequencing: cursor advances only on successful feed, rejected blocks are retried before new generation, and the block sequence is gap-free.

AIR maintains a queue depth of exactly 2 (executing + pending). After seeding two blocks, Core has zero feed credits until the first `BLOCK_COMPLETE` arrives.

### 2.2 Why Reactive BlockCompleted-Based Feeding Is Insufficient

The reactive model assumes that one `BLOCK_COMPLETE` event provides sufficient lead time to generate, resolve, and deliver the next block before the currently-pending block finishes execution. This assumption holds only when:

- Block durations are long relative to preparation time.
- Asset resolution is instantaneous or negligible.
- No transient delays (I/O contention, schedule service latency) occur during the generation window.

When any of these assumptions break, the model degrades:

- **Short blocks compress the available window.** A 30-second block leaves at most 30 seconds between `BLOCK_COMPLETE` and the next fence boundary. If generation or asset resolution takes 5 seconds, the effective cushion is 25 seconds — but the model has no way to know whether 25 seconds is adequate for the *next* block.

- **The reactive model has no memory of readiness.** It does not track how much prepared material lies ahead of the playhead. It only knows that a slot opened and a block should be fed. Whether the fed block provides 30 seconds or 30 minutes of additional runway is not evaluated.

- **Transient delays compound without recovery.** If one `BLOCK_COMPLETE` → feed cycle is slow, the next cycle starts with less lead time. The reactive model does not compensate — it waits for the next event. Consecutive slow cycles can drain the queue to zero with no warning.

- **The tick-driven fallback is throttled.** The 4 Hz evaluation provides a ceiling on reaction speed. If the event-driven path stalls and the tick path is between evaluations, a fence boundary can arrive with no prepared successor.

The fundamental problem: **the reactive model conflates "a queue slot opened" with "readiness is sufficient."** A free queue slot is necessary but not sufficient for runway health. The system needs to know *how much* prepared material exists and whether that amount satisfies the channel's readiness requirements.

---

## 3. Fixed-Depth Queue vs. Runway-Based Readiness

### 3.1 Fixed-Depth Queue Model

A fixed-depth queue targets a constant number of blocks ahead of the playhead: "always keep N blocks queued." This is simple and is roughly what the current model achieves with AIR's 2-block queue.

**Limitations:**

- **Block duration is variable.** Two 15-minute blocks provide 30 minutes of runway. Two 30-second blocks provide 1 minute. A fixed depth of 2 tells you nothing about duration.
- **Not all blocks contribute equally to readiness.** A block composed entirely of planned PAD followed by a content block provides padding duration but does not guarantee the content block is READY (INV-RUNWAY-003).
- **Recovery segments consume queue slots without providing runway.** A block containing runtime recovery material occupies a slot but contributes zero non-recovery runway.

A fixed-depth model cannot distinguish between "2 blocks = 60 minutes of runway" and "2 blocks = 200 ms of runway." Both satisfy "queue depth = 2."

### 3.2 Runway-Based Readiness Model

A runway-based model targets a minimum *duration* of prepared material ahead of the playhead: "always maintain at least `PRELOAD_BUDGET` milliseconds of non-recovery READY content."

**Advantages:**

- **Duration-aware.** Runway is measured in wall-clock time, not block count. A channel with short blocks queues more; a channel with long blocks queues fewer. The target is always the same: sufficient time ahead.
- **Recovery-aware.** Recovery segments are excluded from the measurement. A queue full of recovery material reads as zero runway, correctly reflecting that the channel has no planned content ahead.
- **PAD-transparent.** Planned PAD contributes to measured duration but does not satisfy the requirement that non-PAD successors be READY (INV-RUNWAY-003).
- **Independent of queue depth.** The model works whether AIR's queue is 2, 4, or 10 deep. Runway is measured against the playhead, not against a slot count.

The runway model is what RunwayReadinessContract_v0.1 requires. The fixed-depth model cannot satisfy INV-RUNWAY-001 without additional duration-aware logic.

---

## 4. Micro-Segment Readiness Collapse

### 4.1 The Problem

Consider a TransmissionLog that includes a 2-frame planned PAD (~67 ms at 30 fps) between two content segments, spanning a block boundary:

```
Block N:  [ content_A (29.933s) | pad (0.067s) ]
Block N+1: [ content_B (30.0s) ]
```

Under the reactive model:

1. Block N begins executing. Block N+1 is in the pending slot.
2. `content_A` plays for 29.933 seconds.
3. The PAD begins executing. It will complete in 67 ms.
4. When Block N completes (via `BLOCK_COMPLETE`), Block N+1 moves to executing and a feed credit is emitted.
5. Core must now generate and deliver Block N+2.

In this sequence, Block N+1 is already READY (it was in the pending slot). The reactive model works here — but only because AIR's 2-block queue happened to cover the micro-segment boundary.

Now consider the case where Block N+1 is *not* yet in the queue when the PAD begins executing:

```
Block N:  [ content_A (29.933s) | pad (0.067s) ]
Block N+1: [ not yet queued ]
```

The PAD provides only 67 ms of buffer before the fence boundary. If Block N+1 is not READY when the PAD starts, the system has 67 ms to generate, resolve, and deliver an entire block. This is not achievable.

### 4.2 Why This Causes Collapse

A micro-segment at a block boundary compresses the available preparation window to near zero. The reactive model cannot respond — `BLOCK_COMPLETE` fires only after the block finishes, and by then the successor must already be executing.

The result is a readiness collapse: the system transitions from "healthy" to "recovery required" in a single frame interval. There is no gradual degradation. The micro-segment acts as a trap — it appears to contribute to runway (67 ms is nonzero) but provides no meaningful preparation time.

INV-RUNWAY-002 exists precisely for this case: at any fence boundary, the successor must already be READY. A micro-segment at a fence does not change this requirement. If the successor is not READY when the micro-segment begins, the invariant is already violated — regardless of how much time remains in the micro-segment.

### 4.3 Implication for Feed-Ahead

Feed-ahead must ensure that successors are READY *before* any micro-segment boundary is reached, not in response to the block containing the micro-segment completing. The reactive model's "wait for `BLOCK_COMPLETE`, then feed" is structurally too late when the boundary is sub-second.

---

## 5. Required Control Loop

The feed-ahead policy must evolve from reactive event handling to a continuous control loop that maintains runway above `PRELOAD_BUDGET`.

### 5.1 Loop Structure

The control loop executes the following on each evaluation (whether triggered by tick, event, or explicit invocation):

```
1. MEASURE runway
     runway_ms = compute_runway_ms(block_queue, current_position_ms)

2. IF runway_ms < preload_budget_ms:
     a. Ensure next block is QUEUED
          - If not already generated, generate from TransmissionLog.
          - If generated but not yet fed, attempt feed.

     b. Begin PRIMING next block
          - Resolve all segment material so the block becomes READY.
          - (Priming is the transition from "planned" to "READY".)

     c. REPEAT from step 1
          - Re-measure after each block is primed.
          - Continue until runway_ms >= preload_budget_ms
            or no further blocks are available from the plan.

3. IF runway_ms >= preload_budget_ms:
     No action required. Exit loop.
```

### 5.2 Loop Properties

- **Goal-seeking, not event-chasing.** The loop does not react to a single event. It measures a deficit and works to close it. Multiple blocks may be queued in a single evaluation if runway is deeply deficient.

- **Bounded.** The loop is constrained by `max_queued_blocks` and `max_primed_blocks` (see Section 6). It cannot queue unboundedly even if runway remains below budget.

- **Idempotent.** If runway already meets budget, the loop is a no-op. Repeated evaluations with no state change produce no side effects.

- **Compatible with existing queue discipline.** The loop uses the same feed path (generate → try_feed → advance_cursor or store_pending). INV-FEED-QUEUE-001 through 005 remain enforced. The loop does not bypass the pending-block retry mechanism.

### 5.3 Evaluation Triggers

The control loop should be evaluated on:

- `BLOCK_COMPLETE` (a queue slot opened — existing trigger)
- Tick evaluation (existing ~4 Hz path — may need higher frequency for short blocks)
- Successful prime completion (a block transitioned from not-READY to READY, which changes measured runway)

The loop replaces the current "feed one block per trigger" policy with "feed until runway is satisfied or constraints are reached."

---

## 6. Capacity Limits

### 6.1 max_queued_blocks

A per-channel limit on the number of blocks that may be queued (generated and awaiting feed or already fed) at any time.

**Purpose:** Prevents unbounded block generation when runway is deeply deficient. Without a cap, a channel with very short blocks and a high `PRELOAD_BUDGET` could generate hundreds of blocks in a single loop iteration.

**Relationship to AIR queue depth:** `max_queued_blocks` is a Core-side limit. AIR's queue depth (currently 2) is an independent constraint. `max_queued_blocks` may be larger than AIR's queue depth — Core can prepare blocks in advance that are not yet fed to AIR.

### 6.2 max_primed_blocks

A per-channel limit on the number of blocks that may be in the PRIMED state (material fully resolved, ready for execution) at any time.

**Purpose:** Bounds the memory and I/O cost of pre-resolving material. Priming a block may involve reading asset metadata, verifying file availability, or preparing decode parameters. Doing this for too many blocks simultaneously wastes resources on material that will not execute for minutes or hours.

**Relationship to max_queued_blocks:** `max_primed_blocks <= max_queued_blocks`. A block cannot be PRIMED without first being QUEUED (or at least generated). In practice, `max_primed_blocks` will often equal `max_queued_blocks` since blocks should be primed as soon as they are queued.

### 6.3 Interaction

The control loop in Section 5 respects both limits:

- It will not generate a new block if `queued_count >= max_queued_blocks`.
- It will not begin priming a block if `primed_count >= max_primed_blocks`.
- If both limits are reached and runway is still below budget, the loop exits. This is a degraded condition (see Section 7) but not a fault — the system is doing all it can within its configured capacity.

---

## 7. Steady-State vs. Degraded-State Behavior

### 7.1 Steady-State

The channel is in steady-state when:

- `runway_ms >= preload_budget_ms` (INV-RUNWAY-001 satisfied)
- All fence boundaries have READY successors (INV-RUNWAY-002 satisfied)
- The control loop evaluates and takes no action

Steady-state is the expected operating condition. The control loop maintains it by proactively priming material before the playhead consumes existing runway.

### 7.2 Degraded-State

The channel enters degraded-state when:

- `runway_ms < preload_budget_ms` and the control loop cannot restore it within `max_queued_blocks` / `max_primed_blocks` constraints.

**OR:**

- A fence boundary is reached where the successor is not READY and is not runtime recovery (INV-RUNWAY-002 violated).

Degraded-state behavior:

- **Recovery segments may be injected** to maintain continuous output. These are classifiable as `RUNTIME_RECOVERY` under AsRun reconciliation (INV-RUNWAY-004).
- **The control loop continues operating.** Degraded-state is not a terminal condition. The loop continues measuring and priming. If the underlying cause resolves (e.g., a slow asset becomes available), runway recovers and the channel returns to steady-state.
- **The cause is classified.** Per the RunwayReadinessContract, degradation is either an operational degradation (transient runtime condition) or a planning fault (the TransmissionLog lacks material). The controller does not conflate these — it reports what it observes.

### 7.3 Transitions

```
STEADY-STATE
    |
    | runway_ms drops below preload_budget_ms
    v
DEGRADED-STATE
    |
    | control loop restores runway_ms >= preload_budget_ms
    v
STEADY-STATE
```

Transitions are observable and should be recorded for operational visibility. The controller does not require explicit state-machine transitions — the state is derived from the runway measurement at each evaluation.

---

## 8. What This Document Does Not Define

- **Specific APIs or function signatures.** The control loop describes behavior, not interfaces.
- **HorizonManager changes.** Horizon planning depth and extension policy are unaffected. The controller consumes whatever the Horizon has produced (INV-RUNWAY-005).
- **AIR queue depth changes.** The controller adapts to AIR's queue depth; it does not require AIR to change.
- **Priming implementation.** How a block transitions from "planned" to "READY" (asset resolution, file I/O, metadata lookup) is a Core pipeline concern outside this document.
- **Recovery segment selection.** What material is used for runtime recovery is a separate policy decision. This document only requires that recovery segments exist and are classifiable.
- **Tick frequency or scheduling.** Whether the control loop runs at 4 Hz, 30 Hz, or on-demand is an implementation decision constrained by responsiveness requirements.
- **Contracts.** This document is design guidance. Binding invariants are defined in RunwayReadinessContract_v0.1.

---

## 9. Relationship to Existing Contracts

| Contract | Relationship |
|----------|-------------|
| **RunwayReadinessContract_v0.1** | This design exists to satisfy it. INV-RUNWAY-001 through 005 are the target invariants. |
| **INV-FEED-QUEUE-DISCIPLINE** | Preserved. The control loop uses the existing feed path. Queue discipline invariants remain enforced. |
| **INV-BLOCK-WALLCLOCK-FENCE-DISCIPLINE** | Preserved. Block timestamps and fence semantics are unchanged. |
| **TransmissionLogSeamContract_v0.1** | Unaffected. The controller consumes locked TransmissionLogs; it does not modify them. |
| **AsRunReconciliationContract_v0.1** | Leveraged. Recovery segments injected during degraded-state must be classifiable per INV-ASRUN-005. |
| **PlayoutAuthorityContract** | Preserved. BlockPlanProducer remains the sole feed authority. |
