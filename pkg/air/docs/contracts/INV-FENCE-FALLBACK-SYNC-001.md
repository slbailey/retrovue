# INV-FENCE-FALLBACK-SYNC-001: Mandatory Synchronous Queue Drain at Fence

**Classification:** INVARIANT (Coordination)
**Owner:** PipelineManager
**Enforcement Phase:** Every fence tick in a BlockPlan session
**Depends on:** OUT-BLOCK-005 (PADDED_GAP on missing block), INV-BLOCK-WALLFENCE-001 (fence timing)
**Derives from:** INV-RUNWAY-MIN-001 (no starvation-induced PADDED_GAP when depth >= 3)
**Created:** 2026-02-12
**Status:** Active

---

## Problem Statement

With queue_depth >= 3, Core's runway controller maintains at least one block
in AIR's queue at all times.  But if the preload path (SeamPreparer /
ProducerPreloader) misses the fence — because the preload was slow, the asset
required a long probe, or the overlap window was too short — the queued block
is unreachable unless AIR explicitly pops and sync-loads it at the fence.

Previously, this fallback was gated by a `fence_fallback_sync` flag that
defaulted to `false`.  This meant depth >= 3 could not prevent
starvation-induced PADDED_GAP: the block was in the queue but the fence
rotation would not use it.

---

## Invariant

### INV-FENCE-FALLBACK-SYNC-001: Queue Drain at Fence Is Unconditional

> When the fence tick fires and the incoming block is NOT ready via the
> normal preload path (preview buffers or SeamPreparer result), AND the
> block queue is non-empty, PipelineManager MUST:
>
> 1. Pop the front block from `block_queue` (under `queue_mutex`).
> 2. Emit `BlockStarted` for the popped block (credit signal to Core).
> 3. Synchronously load the block via `AssignBlock()` (probe + open + seek).
> 4. Install the loaded producer as `live_`.
> 5. Start buffer filling from the new producer.
>
> This path MUST NOT be gated by a configuration flag, feature toggle, or
> runtime condition other than `!block_queue.empty()`.

**Rationale:** The sync fallback is the mechanism that converts queue depth
into fence-time resilience.  Without it, queued blocks are decorative —
they cannot prevent PADDED_GAP when preload misses the fence.  Making the
fallback unconditional closes the gap between "queue is full" and "fence
transition succeeds."

---

## Behavioral Consequences

### On preload hit (normal path):
```
fence tick → preview_video_buffer_ exists → swap B→A → no fallback needed
```

### On preload miss, queue non-empty (this invariant):
```
fence tick → preview not ready → TryTakePreviewProducer() fails
           → pop from block_queue → BlockStarted emitted
           → AssignBlock (sync: probe+open+seek) → live_ assigned
           → buffer filling started → execution continues
           → NO PADDED_GAP
```

### On preload miss, queue empty (true starvation):
```
fence tick → preview not ready → queue empty
           → PADDED_GAP entered (OUT-BLOCK-005)
           → TryLoadLiveProducer on next tick recovers when Core feeds
```

---

## Cost Model

The sync fallback calls `AssignBlock()` on the tick thread.  This blocks the
tick loop for the duration of probe + open + seek (typically 50–200ms for
local files, potentially longer for network assets).

During this stall:
- No frames are emitted (output underrun, not black+silence).
- The timing loop's absolute deadline catches up on resume.
- Downstream clients may see a brief pause.

This is strictly better than PADDED_GAP, which emits black+silence frames for
the entire duration until the next `TryLoadLiveProducer` cycle recovers (at
least one full tick period, often longer).

---

## Scope

This invariant applies to:
- Every fence tick in a BlockPlan session where the preload path failed.

This invariant does NOT apply to:
- Session boot (first block load via `TryLoadLiveProducer`).
- PADDED_GAP recovery (separate path: `TryLoadLiveProducer` in the tick loop).
- Legacy per-segment producer paths.

---

## Relationship to Other Contracts

| Contract | Relationship |
|----------|-------------|
| OUT-BLOCK-005 | Sibling: PADDED_GAP is the fallback when this invariant's precondition fails (queue empty). |
| INV-RUNWAY-MIN-001 | Parent: this invariant is the AIR-side enforcement that makes the system-level runway promise hold. |
| INV-BLOCK-LOOKAHEAD-PRIMING | Sibling: priming is best-effort decode optimization; this invariant is the hard fallback when priming misses the fence. |
| INV-BLOCK-WALLFENCE-001 | Sibling: fence timing is authoritative; this invariant governs what happens at the fence when preload missed. |
| INV-FEED-QUEUE-DISCIPLINE | Upstream (Core): credit-based feeding ensures queue is non-empty; this invariant ensures queue contents are usable at the fence. |

---

## Enforcement

**Code:** `PipelineManager.cpp`, fence rotation block (post-TAKE, Step 5).
The `if (!swapped)` guard before the queue-pop path must have NO additional
conditions.  The former `ctx_->fence_fallback_sync` gate has been removed.

**Field deprecation:** `BlockPlanSessionContext::fence_fallback_sync` is
retained for ABI compatibility but defaults to `true` and is ignored by the
fence rotation logic.

---

## Required Tests

| Test | Description |
|------|-------------|
| T-FENCE-SYNC-001 | When preload misses the fence and queue has a block, the block is sync-loaded and no PADDED_GAP occurs. |
| T-FENCE-SYNC-002 | When preload misses the fence and queue is empty, PADDED_GAP is entered (OUT-BLOCK-005 still holds). |
| T-FENCE-SYNC-003 | BlockStarted is emitted for the sync-loaded block (credit signal reaches Core). |
| T-FENCE-SYNC-004 | After sync fallback, buffer filling starts and subsequent ticks produce frames from the new block. |
