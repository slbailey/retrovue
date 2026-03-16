# INV-HLS-RING-EVICTION-GRACE-001

## Behavioral Guarantee

A segment remains retrievable for at least one manifest window advancement after it is removed from the manifest. Ring capacity exceeds manifest window size by at least 2 to prevent the race where a client receives a manifest listing segment N, then segment N is evicted before the client fetches it.

## Authority Model

SegmentRing capacity configuration owns this guarantee. The capacity MUST be set to `manifest_window_size + grace_count` where `grace_count >= 2`.

## Boundary / Constraint

- Ring `capacity` MUST be strictly greater than `manifest_window_size + 1`.
- If ring capacity is configured less than or equal to manifest window size + 1, startup MUST fail with a configuration error naming this invariant.
- The grace margin absorbs the latency between manifest generation and client segment fetch.

## Violation

Ring capacity <= manifest window size + 1; segment evicted before a client that received a manifest listing it could fetch it.

## Derives From

`INV-HLS-MANIFEST-CHANNEL-SCOPED-001`, `INV-HLS-RING-BOUNDED-001`, `LAW-LIVENESS`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_ring_integrity.py`

## Enforcement Evidence

TODO
