# INV-HLS-RING-STALENESS-RECOVERY-001

## Behavioral Guarantee

The HLS manifest endpoint MUST NOT serve a playlist containing only stale segments. When the newest segment in the SegmentRing is older than `4 × target_segment_duration` and an HLS client requests the manifest, the endpoint MUST return HTTP 503 with `Retry-After` and trigger channel re-activation through the sole lifecycle entry point.

## Authority Model

ProgramDirector owns the manifest endpoint and staleness detection. SegmentRing provides the freshness signal via segment wall-clock timestamps. Re-activation routes through `HlsConsumptionAdapter.activate()` per `INV-SINGLE-ACTIVATION-PATH-001`.

## Boundary / Constraint

- The manifest endpoint MUST compute the age of the newest segment: `now_utc_ms - (newest.wall_clock_start_utc_ms + newest.duration_ms)`.
- If this age exceeds `4 × target_segment_duration_ms` (default: 24 000 ms), the ring is stale.
- A stale ring MUST be treated identically to an empty ring: HTTP 503 with `Retry-After: 2`.
- The endpoint MUST clear the stale ring and mark the channel as inactive so the next request triggers re-activation per `INV-HLS-FIRST-VIEWER-ACTIVATES-CHANNEL-001`.
- `INV-HLS-PRODUCER-SEGMENT-FLOW-001` covers segmenter stalls while bytes flow. This invariant covers the complementary case: no bytes flowing at all (dead pipeline).

## Violation

Manifest endpoint returns HTTP 200 with a playlist whose newest segment end-time is more than `4 × target_segment_duration` in the past. MUST be logged at WARNING level with invariant ID.

## Derives From

`INV-HLS-LIFECYCLE-SEGMENT-READY-001`, `INV-HLS-PRODUCER-SEGMENT-FLOW-001`, `LAW-LIVENESS`

## Required Tests

- `tests/contracts/hls_delivery/test_hls_stale_ring_recovery.py`

## Enforcement Evidence

TODO
