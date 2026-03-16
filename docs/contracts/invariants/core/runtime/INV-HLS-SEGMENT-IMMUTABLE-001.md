# INV-HLS-SEGMENT-IMMUTABLE-001

## Behavioral Guarantee

Once a segment transitions to complete, its byte payload, duration, wall-clock timestamp, index, and discontinuity flag are frozen. Any read of a completed segment returns identical data regardless of when or by whom the read occurs.

## Authority Model

HLSSegmenter owns segment completion. SegmentRing owns storage of completed segments.

## Boundary / Constraint

- Completed segment fields MUST NOT be modified, appended to, or rewritten.
- The byte payload returned for a given `(channel_id, segment_index)` MUST be identical across all requests from all clients.
- No client-specific transformation, watermarking, or mutation MUST occur.

## Violation

Any mutation of a completed segment's fields; byte-level divergence between two reads of the same segment index; client-specific payload modification.

## Derives From

`LAW-IMMUTABILITY`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_segment_production.py`

## Enforcement Evidence

TODO
