# INV-HLS-RING-BOUNDED-001

## Behavioral Guarantee

The segment ring holds at most `capacity` completed segments. Eviction is strictly FIFO by index order. Segments in the ring form a contiguous index range with no gaps.

## Authority Model

SegmentRing owns capacity enforcement and eviction. HLSSegmenter is the sole writer.

## Boundary / Constraint

- The ring MUST NOT hold more than `capacity` segments at any time.
- When a push would exceed capacity, the oldest segment (lowest index) MUST be evicted before or atomically with the push.
- At any observation point, segments in the ring MUST form a contiguous index range `[oldest_index, newest_index]` with no gaps.
- Eviction MUST NOT skip a segment or evict out of order.
- Once evicted, a segment index MUST return absence on retrieval permanently within this ring instance.

## Violation

Ring exceeding declared capacity; non-contiguous index range; out-of-order eviction; evicted segment returning data.

## Derives From

`LAW-LIVENESS`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_segment_ring.py`

## Enforcement Evidence

TODO
