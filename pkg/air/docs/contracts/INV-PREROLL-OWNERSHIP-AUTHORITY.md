# INV-PREROLL-OWNERSHIP-AUTHORITY: Preroll Arming and Fence Swap Coherence

**Classification:** INVARIANT (Coordination — Broadcast-Grade)
**Owner:** PipelineManager
**Enforcement Phase:** Every block boundary in a BlockPlan session
**Depends on:** INV-BLOCK-WALLCLOCK-FENCE-001, INV-BLOCK-LOOKAHEAD-PRIMING
**Created:** 2026-02-22
**Status:** Active

---

## Definition

Preroll arming authority MUST be aligned with the same "next block" authority that the fence swap uses. The block that crosses the fence at the TAKE is the **committed successor**. Preroll may only arm for that committed successor — never for a different block derived from the plan queue unless it is the committed successor.

This contract makes PREROLL_OWNERSHIP_VIOLATION structurally impossible in normal operation by ensuring a single source of truth for "which block is next at the fence."

---

## Outcomes (Required Behavior)

### OUT-PREROLL-001: Committed Successor Is Single Source of Truth

- The **committed successor block id** is the block that will be used at the next block fence (the block in the B slot at TAKE time).
- It is set exactly when a block is **committed** to that role: when the preloaded result is taken into the preview slot (TakeBlockResult → preview_), not when a block is popped from the queue and submitted to the preloader.
- Fence swap (TAKE) selects the block in the preview slot. No other authority (queue front, FeedBlockPlan order) may determine which block is "expected" at the fence.

### OUT-PREROLL-002: Preroll Arming Uses Committed Successor Only

- Preroll arming (submitting a block to the preloader) MUST NOT set the "expected next block" from the queue.
- The "expected next block" (ownership stamp) MUST be set only when the preloaded producer is taken into the preview slot (TakeBlockResult). At that moment, the block in preview_ is the committed successor for the upcoming fence.
- After a B→A rotation, the expected stamp is cleared until the next TakeBlockResult.

### OUT-PREROLL-003: Fail-Closed on Mismatch

- If at fence time the block in the preview slot does not match the committed successor stamp (e.g. due to a latent bug or race), the system MUST fail closed: do not arm for a different block; log a single structured violation with `expected_next_block_id` and `candidate_block_id` (the block actually in preview_).
- Playout MUST continue with the block that is in the preview slot (correct session block); only the diagnostic is a violation. No spam; one log per fence.

### OUT-PREROLL-004: No Queue-Peek for Expected Value

- The plan queue (FeedBlockPlan, ctx_->block_queue) MUST NOT be used to derive the "expected block at fence." The queue is input supply; the session state (preview_ / committed successor) is the authority for what crosses the fence.

---

## Required Tests

**File:** `pkg/air/tests/contracts/test_preroll_ownership_authority.py` (Python) and/or `pkg/air/tests/contracts/BlockPlan/PrerollOwnershipContractTests.cpp` (C++)

| Test Name | Outcome(s) | Description |
|-----------|------------|-------------|
| `preroll_arms_only_for_committed_successor` | OUT-001, OUT-002 | Preroll can only arm for the session-committed successor block id (block in preview_ after TakeBlockResult); never for a queued FeedBlockPlan block unless it matches the committed successor. |
| `mismatch_fails_closed_single_log` | OUT-003 | If a mismatch occurs (preview_.block_id != expected stamp), system fails closed: preroll does not arm for the wrong block; one structured violation log with expected_next_block_id and candidate_block_id; playout continues with the correct session block. |
| `expected_set_at_take_not_at_submit` | OUT-002 | Verify expected_preroll_block_id_ is set when TakeBlockResult runs (preview_ assigned), and not when TryKickoffBlockPreload submits. |
| `cleared_after_rotation` | OUT-002 | After B→A rotation, expected stamp is cleared until next TakeBlockResult. |

---

## Relationship to Other Contracts

- **INV-BLOCK-WALLCLOCK-FENCE-001:** Fence tick remains the sole timing authority; this contract governs *which* block is the valid B at the fence.
- **INV-BLOCK-LOOKAHEAD-PRIMING:** Priming prepares the committed successor; ownership authority ensures we only consider that block as "expected."

---

## Structured Log Fields (Observability)

On violation (OUT-PREROLL-003), the log MUST include:

- `expected_next_block_id`: the committed successor block id (from ownership stamp).
- `candidate_block_id`: the block id actually in the preview slot at fence time.
- `tick`: session_frame_index at the fence.

No other keys are required for this contract. Log at most once per fence.
