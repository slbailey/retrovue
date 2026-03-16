# INV-HLS-MANIFEST-CHANNEL-SCOPED-001

## Behavioral Guarantee

The manifest content for a channel at a given instant is identical for all clients requesting it. No client-specific, session-specific, or request-specific data appears in the manifest body.

## Authority Model

ManifestGenerator owns playlist content. The manifest is a pure function of `(channel_id, segment_ring_state)`.

## Boundary / Constraint

- The manifest body MUST NOT contain client-specific or session-specific data.
- Two concurrent manifest requests for the same channel MUST return identical playlist content.
- Every segment listed in the manifest MUST be present in the segment ring at the time of generation. The manifest MUST NOT reference evicted or not-yet-produced segments.
- A segment MUST remain retrievable for at least one full manifest poll interval after removal from the manifest (ring capacity > manifest window size provides this grace).

## Violation

Manifest content diverging between concurrent clients; manifest referencing a segment not in the ring; client-specific data in the playlist body.

## Derives From

`LAW-CLOCK`, `LAW-DERIVATION`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_manifest.py`

## Enforcement Evidence

TODO
