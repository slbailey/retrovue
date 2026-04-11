# INV-SEAM-CONTINUITY-GUARANTEED-001

## Behavioral Guarantee

For every scheduled segment boundary, playout MUST transition seamlessly into the next segment with valid A/V output. The next segment MUST be prepared and ready before the seam frame is reached. A scheduled transition that fails to produce a valid next frame is a playout continuity violation.

## Authority Model

The playout pipeline owns seam transitions. The schedule defines segment boundaries. The tick loop reaches the seam frame. At that point, the next segment's video and audio MUST be available. The seam preparer is the mechanism but the contract is on the outcome: transition succeeds.

## Boundary / Constraint

- Every segment boundary in a multi-segment block MUST resolve to a valid video frame and valid audio state in the next segment.
- If the next segment is not prepared when the seam frame is reached, the transition fails and output corrupts.
- Black frames, missing PPS, or stalled output at a scheduled segment boundary is a violation.
- The system MUST NOT silently remain on an exhausted segment — if segment N reaches EOF, segment N+1 MUST already be active.

## Violation

Seam frame reached with no prepared next segment; black or corrupted frames at segment boundary; output stalled at transition point; segment N exhausted without segment N+1 active; `seam_preparer_has_result=0` at seam tick.

## Derives From

`LAW-LIVENESS`, `LAW-DECODABILITY`

## Required Tests

- `runtime/tests/contracts/BlockPlan/SeamContinuityTests.cpp`

## Enforcement Evidence

TODO
