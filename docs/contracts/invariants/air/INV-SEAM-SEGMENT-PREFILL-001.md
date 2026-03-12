# INV-SEAM-SEGMENT-PREFILL-001

**Owner:** AIR (PipelineManager tick loop + EnsureIncomingBReadyForSeam)

## Behavioral Guarantee

When a segment swap gate evaluates incoming readiness at a seam tick, the B-side pipeline (buffer + fill loop) MUST have had the full available runway between prep completion and the seam tick to accumulate video lookahead depth. The swap gate MUST evaluate a warm pipeline, not a cold start.

## Authority Model

PipelineManager tick loop is the sole enforcement point. The tick loop creates the B-side pipeline as soon as the SeamPreparer result becomes available, not at the seam tick.

## Boundary / Constraint

When all of the following hold:
- SeamPreparer has a completed segment result (`PeekSegmentResult` returns a valid result)
- The result's `parent_block_id` matches the live block
- The result's `parent_segment_index` is greater than `current_segment_index_`

Then:
- `EnsureIncomingBReadyForSeam` MUST be called on the same tick the result is first observed
- The B-side `VideoLookaheadBuffer` and `AudioLookaheadBuffer` MUST be created and `StartFilling` invoked before the next tick
- `EnsureIncomingBReadyForSeam` MUST be idempotent — repeated calls after B exists MUST return immediately without side effects
- PAD segments MUST NOT create segment_b buffers (PAD uses persistent pad_b_* buffers)

## Violation

A tick where `SEGMENT_TAKE_COMMIT` fires with `segment_b_video_depth_frames` below the `VideoLookaheadBuffer` target depth AND `runway_ticks_remaining` at `SEGMENT_PREFILL_STARTED` was sufficient to reach target depth at sustained decode rate constitutes evidence of a violation. Creation of B-side buffers at the seam tick rather than at prep completion is a structural violation.

## Derives From

`INV-SEAM-006`, `INV-SEAM-SEG-003`

## Required Tests

- `pkg/air/tests/contracts/BlockPlan/SegmentPrefillContractTests.cpp`

## Enforcement Evidence

TODO
