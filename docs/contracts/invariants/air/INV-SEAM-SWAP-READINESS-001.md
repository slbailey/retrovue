# INV-SEAM-SWAP-READINESS-001

**Owner:** AIR (PipelineManager segment swap gate)

## Behavioral Guarantee

The seam swap gate MUST require the incoming buffer to reach its configured target depth before swap, so the transition occurs into a warm pipeline at its designed operating point rather than a cold or partially filled pipeline.

## Authority Model

`PipelineManager::IsIncomingSegmentEligibleForSwap` is the sole enforcement point. The threshold is sourced from `segment_b_video_buffer_->TargetDepthFrames()` at each call site and passed as a parameter — not stored as duplicate state or a separate constant.

## Boundary / Constraint

When evaluating segment swap eligibility for a non-PAD segment:
- `incoming_video_frames` MUST be >= the incoming buffer's `TargetDepthFrames()` (currently 15)
- The threshold MUST be sourced dynamically from the buffer configuration, not duplicated as a separate constant
- Audio depth requirement (`kMinSegmentSwapAudioMs`) is unchanged

PAD segments are exempt from the video depth requirement because they generate frames on demand and do not use a video lookahead buffer. Audio depth is still required for audio continuity at the seam.

When the gate defers a swap:
- The outgoing segment MUST enter hold-last mode (repeat last decoded frame)
- The incoming fill loop MUST continue running
- A diagnostic log MUST be emitted: `SEGMENT_SWAP_DEFERRED` with `incoming_depth` and `required_depth`
- The swap MUST fire on the first subsequent tick where depth reaches the target

## Violation

A segment swap that commits with `incoming_video_frames` below the buffer's `TargetDepthFrames()` for a non-PAD segment constitutes a violation. A PAD segment blocked by the video depth gate constitutes a violation (PAD is exempt).

## Derives From

`INV-SEAM-002`, `INV-VIDEO-LOOKAHEAD-001`

## Required Tests

- `pkg/air/tests/contracts/BlockPlan/SegmentSwapReadinessContractTests.cpp`

## Enforcement Evidence

TODO
