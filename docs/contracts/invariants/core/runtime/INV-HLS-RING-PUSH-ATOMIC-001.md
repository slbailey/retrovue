# INV-HLS-RING-PUSH-ATOMIC-001

## Behavioral Guarantee

The push operation (insert new segment + evict oldest if over capacity) is atomic with respect to readers. No reader may observe a state where the new segment is present but the evicted segment has not yet been removed, or vice versa.

## Authority Model

SegmentRing owns atomicity. The push operation and any concurrent reads MUST be serialized by the ring's concurrency mechanism.

## Boundary / Constraint

- Push and eviction MUST execute within a single critical section.
- A reader that snapshots the window MUST NOT observe: (a) `len(segments) > capacity`, (b) a gap in the index range, or (c) the new segment absent while capacity has decreased.
- The `window()` method MUST acquire the same lock as `push()` to guarantee snapshot consistency.
- The `get()` method MUST acquire the same lock as `push()` for individual segment retrieval.

## Violation

Reader observes `len > capacity`; reader observes index gap during push; reader retrieves a segment that is simultaneously being evicted.

## Derives From

`INV-HLS-RING-OBSERVATION-001`, `LAW-LIVENESS`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_ring_integrity.py`

## Enforcement Evidence

TODO
