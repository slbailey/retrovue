# INV-HLS-SEGMENT-PTS-CONTINUITY-001

## Behavioral Guarantee

Within a continuous producer session, the first PTS of segment N+1 equals the last PTS of segment N plus one frame duration (within frame-time tolerance). PTS breaks across segment boundaries are detected and marked as discontinuities before the segment enters the ring.

## Authority Model

HLSSegmenter owns PTS tracking across segment boundaries. Discontinuity detection MUST occur during segment accumulation, before completion.

## Boundary / Constraint

- The segmenter MUST track the last PTS of the previous completed segment.
- When a new segment's first PTS diverges from the expected next PTS by more than one frame duration, the segment MUST be marked discontinuous per `INV-HLS-DISCONTINUITY-MARKER-001`.
- PTS continuity checks MUST use integer arithmetic. Float comparison MUST NOT be used.
- On producer restart, the PTS tracker MUST reset. The first segment after restart MUST carry a discontinuity flag.
- Detection failure (PTS gap not flagged) MUST be logged at ERROR level with invariant ID.

## Violation

PTS gap between consecutive segments not detected; discontinuity flag missing on PTS break; PTS tracker not reset on producer restart; float arithmetic used in PTS comparison.

## Derives From

`INV-HLS-SEGMENT-IDENTITY-001`, `INV-HLS-DISCONTINUITY-MARKER-001`, `LAW-DECODABILITY`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_segment_timeline.py`

## Enforcement Evidence

TODO
