# INV-HLS-SEGMENT-KEYFRAME-001

## Behavioral Guarantee

Every HLS segment begins with a keyframe (IDR frame). A client that receives a single segment MUST be able to decode it from its first frame without reference to any prior segment.

## Authority Model

HLSSegmenter owns segment boundary detection. AIR's encoder owns GOP structure and keyframe placement.

## Boundary / Constraint

- Every segment MUST begin at an IDR frame boundary.
- The segmenter MUST NOT cut mid-GOP.
- Segment duration may vary by up to one GOP interval from the target duration due to keyframe alignment.

## Violation

Segment whose first video frame is not an IDR; segment boundary placed between keyframes; client unable to decode segment without prior segment data.

## Derives From

`LAW-DECODABILITY`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_segment_production.py`

## Enforcement Evidence

TODO
