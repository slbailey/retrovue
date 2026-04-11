# INV-HLS-MANIFEST-WINDOW-RING-ALIGNMENT-001

## Behavioral Guarantee

Every segment URI listed in a manifest corresponds to a segment currently present in the segment ring. The manifest window is a strict subset of the ring's contents. No manifest may reference an evicted or not-yet-produced segment.

## Authority Model

ManifestGenerator owns window selection. SegmentRing `window()` is the sole data source for manifest segment lists.

## Boundary / Constraint

- The manifest MUST be generated from a single atomic snapshot of the ring (via `window()`).
- The generator MUST NOT compose manifests from multiple non-atomic ring reads.
- After generating the manifest, the generator MUST NOT re-check the ring — the snapshot is authoritative for that response.
- If `window()` returns an empty list, the generator MUST return HTTP 503 per `INV-HLS-LIFECYCLE-SEGMENT-READY-001`, not an empty playlist.

## Violation

Manifest listing a segment not in the ring snapshot; manifest assembled from multiple non-atomic reads; empty playlist served when ring is empty.

## Derives From

`INV-HLS-MANIFEST-CHANNEL-SCOPED-001`, `INV-HLS-RING-OBSERVATION-001`, `LAW-LIVENESS`

## Required Tests

- `server/tests/contracts/runtime/test_inv_hls_manifest_consistency.py`

## Enforcement Evidence

TODO
