# INV-HLS-MANIFEST-SEQUENCE-001

## Behavioral Guarantee

`#EXT-X-MEDIA-SEQUENCE` equals the segment index of the oldest segment in the current window. Across successive manifest responses for the same channel, this value never decreases.

## Authority Model

ManifestGenerator derives `EXT-X-MEDIA-SEQUENCE` from SegmentRing state. SegmentRing owns window boundaries.

## Boundary / Constraint

- `EXT-X-MEDIA-SEQUENCE` MUST equal the index of the first (oldest) segment in the manifest.
- Across successive manifest responses, `EXT-X-MEDIA-SEQUENCE` MUST NOT decrease.
- Segments MUST be listed in the manifest in ascending index order matching the temporal order of the channel timeline.
- The URI for a given segment index MUST NOT change across manifest responses.

## Violation

`EXT-X-MEDIA-SEQUENCE` not matching oldest segment index; decreasing sequence across responses; segments listed out of index order; segment URI changing between manifest versions.

## Derives From

`LAW-CLOCK`, `LAW-DERIVATION`

## Required Tests

- `server/tests/contracts/runtime/test_inv_hls_manifest.py`

## Enforcement Evidence

TODO
