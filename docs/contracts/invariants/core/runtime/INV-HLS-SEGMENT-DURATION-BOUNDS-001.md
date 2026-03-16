# INV-HLS-SEGMENT-DURATION-BOUNDS-001

## Behavioral Guarantee

Every completed segment's duration falls within `[target_duration - max_gop_interval, target_duration + max_gop_interval]`. Segments outside this range indicate a keyframe detection failure or encoder misconfiguration.

## Authority Model

HLSSegmenter owns duration validation at segment completion. Target duration and GOP interval are configuration-derived.

## Boundary / Constraint

- At segment completion, the segmenter MUST verify the segment duration is within one GOP interval of the target duration.
- If the check fails, the segmenter MUST log at WARNING level with invariant ID, actual duration, target duration, and GOP interval.
- The segment MUST NOT be dropped on duration violation — it still represents valid playout output.
- A zero-duration or negative-duration segment MUST be rejected and logged at ERROR level. It MUST NOT enter the ring.

## Violation

Segment duration outside tolerance band without warning; zero-duration segment entering the ring; negative-duration segment produced.

## Derives From

`INV-HLS-SEGMENT-KEYFRAME-001`, `LAW-DECODABILITY`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_segment_timeline.py`

## Enforcement Evidence

TODO
