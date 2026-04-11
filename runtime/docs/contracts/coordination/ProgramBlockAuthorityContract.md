# Program Block Authority Contract (AIR)

**Classification**: Coordination Contract (Layer 2)
**Owner**: `PipelineManager`
**Derives From**: INV-BLOCK-WALLFENCE-001 (Coordination), INV-TICK-GUARANTEED-OUTPUT (Law, Layer 0)
**Related**: [SegmentContinuityContract.md](../semantics/SegmentContinuityContract.md), [SegmentSeamOverlapContract.md](../semantics/SegmentSeamOverlapContract.md), [SeamContinuityEngine.md](../semantics/SeamContinuityEngine.md)

## Purpose
Define schedule/timeline ownership outcomes for **program blocks**.
This contract explicitly excludes continuity mechanics, which are governed by Segment Continuity Contract.

## Definitions
- **Program block**: The scheduling unit that owns the channel timeline for a wall-clock interval.
- **Fence tick**: The tick at which block ownership must transfer, as determined by the master clock.

## Scope

These outcomes apply to:

- **Program block lifecycle** — block start, block completion, ownership transfer.
- **Fence-driven transitions** between blocks.
- **Block identity and observability** for audit and as-run logging.

These outcomes do NOT apply to:

- **Decoder transition mechanics** — how the swap between outgoing and incoming
  decode sources is executed. That is Seam Continuity Engine responsibility
  (INV-SEAM-001..006, OUT-SEG-001..006).
- **Audio continuity or fallback** at block boundaries — delegated via
  OUT-BLOCK-004 to the Segment Continuity Contract.
- **Intra-block segment transitions** — segment seam timing, decoder preparation,
  pointer-swap mechanics, and fill-thread constraints are exclusively governed by
  the Segment Seam Overlap Contract (INV-SEAM-SEG-001..006). This contract does
  not define, constrain, or assume any specific intra-block segment transition
  mechanism. PipelineManager owns segment seam ticks alongside the block fence
  tick; both use the same rational-arithmetic framework (INV-BLOCK-WALLFENCE-001,
  INV-SEAM-SEG-004) but this contract governs only the fence.
- **Tick cadence** — the clock is not block-aware (Channel Clock domain).

## Contract Outcomes

### OUT-BLOCK-001: Fence is the sole authority for block ownership transfer
Block ownership MUST transfer only at fence tick.
No content or segment lifecycle event may advance block ownership early.

### OUT-BLOCK-002: Block identity is externally observable
On block start and completion, the system MUST emit block lifecycle events containing:
- block_id
- scheduled wall-clock end (or fence time)
- actual fence tick observed
- verdict/proof fields needed for auditability

### OUT-BLOCK-003: Block completion must be recorded
On fence tick, the outgoing block MUST be finalized with:
- emitted frame count
- pad frame count (if any)
- emitted asset ranges (as available)
- a block completion event

### OUT-BLOCK-004: Block-to-block transition MUST invoke segment continuity outcomes
When transitioning from block A to block B, the system MUST satisfy Segment Continuity Contract outcomes
for the decoder transition implied by the swap. The swap mechanism used is the same pointer-swap
primitive defined in INV-SEAM-SEG-005 and INV-SEAM-004.

(Requirement reference: Segment Continuity Contract, Segment Seam Overlap Contract.)

### OUT-BLOCK-005: Missing/late next block results in PADDED_GAP, not stream death
If no incoming block is ready at fence tick, the system MUST:
- enter PAD mode,
- continue continuous output,
- record the gap as PADDED_GAP, and
- remain eligible to resume when a new block arrives.

## Required Tests (must exist in tests/contracts/)
- T-BLOCK-001: BlockTransferOccursOnlyAtFence
- T-BLOCK-002: BlockLifecycleEventsAreEmitted
- T-BLOCK-003: BlockCompletionIsRecordedAtFence
- T-BLOCK-004: BlockToBlockTransitionSatisfiesSegmentContinuity
- T-BLOCK-005: MissingNextBlockPadsInsteadOfStopping

## Notes
This contract defines outcomes only. Implementation strategy is intentionally unspecified.
