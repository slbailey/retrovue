# INV-HLS-MANIFEST-LIVE-001

## Behavioral Guarantee

The HLS manifest for a live channel MUST NOT contain `#EXT-X-ENDLIST`. Its absence is the normative HLS signal that the stream is live.

## Authority Model

ManifestGenerator owns playlist content. Liveness status is derived from producer state.

## Boundary / Constraint

- The manifest MUST NOT contain `#EXT-X-ENDLIST` while the channel has an active producer.
- The manifest MUST contain `#EXT-X-TARGETDURATION` with a value (integer seconds, rounded up) greater than or equal to the actual duration of every segment in the window.
- Every manifest response MUST be a valid HLS media playlist per RFC 8216.

## Violation

`#EXT-X-ENDLIST` present in manifest while producer is active; `EXT-X-TARGETDURATION` less than any segment's `EXTINF` duration; structurally invalid HLS playlist.

## Derives From

`LAW-LIVENESS`

## Required Tests

- `server/tests/contracts/runtime/test_inv_hls_manifest.py`

## Enforcement Evidence

TODO
