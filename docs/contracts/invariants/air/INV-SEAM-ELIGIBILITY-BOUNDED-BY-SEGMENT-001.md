# INV-SEAM-ELIGIBILITY-BOUNDED-BY-SEGMENT-001

## Behavioral Guarantee

A segment's eligibility threshold for seam transition MUST NOT exceed the total decodable frames available for that segment. A segment is eligible when it has produced all frames it is capable of producing OR has reached the steady-state target depth, whichever is smaller. A fully-decoded short segment will never grow deeper — requiring more frames than the segment can produce is an impossible condition that blocks the transition forever.

## Authority Model

PipelineManager owns eligibility evaluation. The segment's total frame count is structural (derived from duration and FPS at block activation). The buffer target depth is operational (configured per session). Eligibility is the intersection of both: readiness bounded by what is physically possible.

## Boundary / Constraint

- The effective eligibility threshold MUST be `min(target_depth, segment_total_frames)`.
- A segment with fewer total frames than the target depth MUST be considered eligible when sufficient frames exist to guarantee valid first emission at the seam.
- The system MUST NOT require a segment to prove readiness using frames that do not exist.
- All readiness thresholds in AIR MUST be physically satisfiable given the media they apply to.

## Violation

Swap eligibility gate requires more frames than the segment can produce; transition blocked indefinitely for a short segment; `eligible=false` when the segment buffer is at maximum possible depth; playout stuck on exhausted previous segment producing black/corrupt output.

## Derives From

`INV-SEAM-CONTINUITY-GUARANTEED-001`, `LAW-LIVENESS`

## Required Tests

- `runtime/tests/contracts/BlockPlan/SeamContinuityGuaranteedTests.cpp`

## Enforcement Evidence

TODO
