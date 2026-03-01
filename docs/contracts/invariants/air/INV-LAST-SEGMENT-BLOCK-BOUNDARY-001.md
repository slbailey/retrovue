# INV-LAST-SEGMENT-BLOCK-BOUNDARY-001

**Status:** Proposed
**Owner:** AIR (PipelineManager seam classification)
**Related:** ADR-013 (Seam Resolution Model)

## Statement

When the active segment is the **last segment** in a block, the next seam
MUST be classified as `SeamType::kBlock` — regardless of whether the segment's
computed end time precedes `block_fence_frame_`.

## Rationale

ADR-013 defines three seam outcomes (Defer, Normal commit, Override commit) and
assumes the seam TYPE is correctly classified before resolution begins. Seam
type classification determines which code path handles the transition:

| Seam type | Handler | Purpose |
|---|---|---|
| `kSegment` | Segment swap (POST-TAKE) | Transfer authority to next segment within block |
| `kBlock` | Block fence / PADDED_GAP | Transfer execution to the next block from Core |

When the last segment in a block ends, there is no next segment to swap to.
The segment swap handler's `GetIncomingSegmentState(current + 1)` returns
`nullopt` (out of bounds), causing `SEGMENT_SWAP_DEFERRED reason=no_incoming`
on every subsequent tick — permanently. The block fence path never fires
because `next_seam_type_` was set to `kSegment`.

This is a classification error, not a resolution error. ADR-013's seam
resolution model operates correctly when given the right seam type. The
invariant ensures it receives the right type.

## Violation Signature

Observable in logs as:
1. `SEGMENT_SWAP_DEFERRED reason=no_incoming` firing at a tick where the
   active segment is the last in the block.
2. No `PADDED_GAP_ENTER` or `FENCE_TRANSITION` following the deferral.
3. Indefinite hold/pad frame emission with no block transition.

## Enforcement Point

`PerformSegmentSwap()` — Step 3 (seam rebase after `current_segment_index_++`).
After advancing the segment index, the rebase logic must check whether the
new index is the last segment. If so, `next_seam_type_` MUST be `kBlock`.

The existing `UpdateNextSeamFrame()` already handles this correctly (line 4111:
`current_segment_index_ + 1 < planned_segment_seam_frames_.size()`), but
`PerformSegmentSwap` bypasses `UpdateNextSeamFrame` with its own rebase to
prevent catch-up thrash. The rebase must include the last-segment guard.

## Trigger Condition

The bug requires `block_fence_frame_ > planned_seam[N-1]` (the planned end
of the last segment). This gap arises when `fence_epoch_utc_ms_` differs from
`block.start_utc_ms`:

- `block_fence_frame_` = `ceil((block.end_utc_ms - fence_epoch_utc_ms_) * fps)`
- `planned_seam[N-1]` = `block_activation_frame_ + ceil(block_duration * fps)`

When `fence_epoch_utc_ms_ < block.start_utc_ms` (common in JIP, bootstrap
delay, and multi-block sessions), the fence includes extra frames for the
epoch→block-start gap. The planned seam does not. After `PerformSegmentSwap`
rebases to `session_frame_index + seg_frames`, the rebased end approximately
equals the planned seam — which is less than the fence.

## Boundary Conditions

- Block with a single segment: `current_segment_index_ = 0`, always the last.
  `kBlock` must be set.
- Block where the last segment ends exactly at `block_fence_frame_`: the
  existing `next_seam_frame_ >= block_fence_frame_` check already yields
  `kBlock`. No change needed.
- Block where the last segment ends BEFORE `block_fence_frame_` (epoch delta):
  the gap between the segment end and block fence is dead time. `kBlock`
  routes to the block fence / PADDED_GAP path, which loads the next block.

## Required Tests

- `pkg/air/tests/contracts/BlockPlan/LastSegmentBlockBoundaryContractTests.cpp`

## Test

Contract test: `LastSegmentBlockBoundaryContractTests.cpp`
- Setup: 2-segment block [CONTENT(5000ms), CONTENT(5000ms)] with
  `block.start_utc_ms = epoch + 5000ms`. This creates a 150-frame gap
  between the rebased last segment end and `block_fence_frame_` (300 vs 450).
- RED: After last segment ends, `SEGMENT_SWAP_DEFERRED reason=no_incoming`
  fires forever. Block B never starts (on_block_started never fires).
- GREEN: After fix, `PerformSegmentSwap` detects last segment → sets `kBlock`.
  Block fence / PADDED_GAP fires. Block B starts within expected deadline.
