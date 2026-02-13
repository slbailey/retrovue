# Runway Minimum Operational Promise — v0.1

**Status:** Contract  
**Version:** 0.1

**Classification:** Contract (Operational Promise)  
**Authority Level:** Core + AIR (system)  
**Governs:** When AIR may enter PADDED_GAP when queue depth is sufficient  
**Out of Scope:** RunwayReadinessContract (duration-based runway), Horizon depth, filler logic

---

## 1. Scope

This contract defines a single, measurable operational promise: with sufficient queue depth, the only acceptable reason for AIR to enter PADDED_GAP (no next block at fence) is a true planning gap — ScheduleService returned None. No other cause is acceptable.

---

## 2. Definitions

- **queue_depth:** The configured depth of the block queue Core feeds to AIR (e.g. `BlockPlanProducer._queue_depth`). When queue_depth >= 3, Core has committed to keeping at least three blocks’ worth of material ahead (or filling slots as they open).

- **PADDED_GAP:** The AIR state when no incoming block is available at a fence tick. AIR enters PAD mode, continues output, and records the gap (e.g. `padded_gap_count`). See Program Block Authority Contract (OUT-BLOCK-005).

- **ScheduleService returns None:** Core’s schedule service (e.g. `get_block_at` / horizon-backed resolution) has no planned block for the requested time. This is a **true planning gap** — the TransmissionLog or horizon has no entry for that block boundary.

- **“No next block” (cause of PADDED_GAP):** AIR reached a fence and no block was available in the queue. The cause is either (a) ScheduleService returned None, or (b) Core had a block to give but did not deliver it in time.

---

## 3. Invariant

### INV-RUNWAY-MIN-001 — No PADDED_GAP From Starvation When Runway Is Sufficient

When **queue_depth >= 3**, AIR must **never** enter PADDED_GAP due to “no next block”, **except** when ScheduleService returns None (true planning gap).

**In other words:**  
With queue_depth >= 3, any PADDED_GAP must be attributable solely to ScheduleService returning None. If Core had a block to supply and did not deliver it before the fence, the system has violated this invariant.

**Measurable:**  
- When queue_depth >= 3 and the schedule is continuous (ScheduleService does not return None for the next block), `padded_gap_count` must not increase.  
- When queue_depth >= 3 and PADDED_GAP occurs, the only acceptable explanation is that ScheduleService returned None for that block.

---

## 4. Enforcement

- **Core** is responsible for feeding blocks so that with queue_depth >= 3, the next block is always delivered before the fence unless ScheduleService returned None.
- **AIR** is responsible for using queued blocks at the fence when preload missed.  Specifically, INV-FENCE-FALLBACK-SYNC-001 requires PipelineManager to unconditionally pop and sync-load the front block from `block_queue` when the normal preload path (SeamPreparer / preview buffers) fails at the fence.  Without this AIR-side enforcement, queued blocks are unreachable at the fence and depth >= 3 cannot prevent starvation-induced PADDED_GAP.
- **PADDED_GAP** may only occur when both the preload path failed AND `block_queue` is empty — meaning Core failed to feed in time, or ScheduleService returned None (true planning gap).
- Violations are operational: PADDED_GAP with queue_depth >= 3 when ScheduleService had not returned None indicates either (a) Core failed to feed in time, or (b) AIR failed to drain the queue at the fence (violation of INV-FENCE-FALLBACK-SYNC-001).

---

## 5. Relationship to Other Contracts

- **Program Block Authority Contract (OUT-BLOCK-005):** AIR's behavior (PADDED_GAP when no next block) is unchanged. This contract restricts when that outcome is acceptable at the system level.
- **INV-FENCE-FALLBACK-SYNC-001:** AIR-side enforcement that makes this system-level promise hold.  When preload misses the fence and queue is non-empty, PipelineManager unconditionally pops and sync-loads the block.  See `pkg/air/docs/contracts/INV-FENCE-FALLBACK-SYNC-001.md`.
- **RunwayReadinessContract:** Addresses duration-based runway (PRELOAD_BUDGET, READY). INV-RUNWAY-MIN-001 is a simpler, queue-depth-based promise: sufficient depth implies no starvation-induced PADDED_GAP except true planning gap.
- **INV-FEED-QUEUE-DISCIPLINE:** Governs credit and sequencing; INV-RUNWAY-MIN-001 is the operational promise that results when that discipline is applied with queue_depth >= 3.
