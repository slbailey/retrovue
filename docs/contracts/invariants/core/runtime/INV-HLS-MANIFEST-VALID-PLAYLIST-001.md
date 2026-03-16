# INV-HLS-MANIFEST-VALID-PLAYLIST-001

## Behavioral Guarantee

Every generated manifest is structurally valid HLS per RFC 8216. The manifest generator validates its own output before returning it to the HTTP handler. A malformed manifest MUST NOT be served to clients.

## Authority Model

ManifestGenerator owns output validation. The validation check executes after playlist assembly, before the response is returned.

## Boundary / Constraint

- Every manifest MUST contain `#EXTM3U` as its first line.
- Every manifest MUST contain exactly one `#EXT-X-TARGETDURATION` tag.
- Every manifest MUST contain exactly one `#EXT-X-MEDIA-SEQUENCE` tag.
- Every manifest MUST contain at least one `#EXTINF` + segment URI pair when segments are available.
- `EXT-X-TARGETDURATION` MUST be an integer >= the ceiling of every `EXTINF` value in the playlist.
- If validation fails, the generator MUST log at ERROR level with invariant ID and return HTTP 500 instead of serving the malformed playlist.
- The manifest MUST NOT contain `#EXT-X-ENDLIST` per `INV-HLS-MANIFEST-LIVE-001`.

## Violation

Manifest missing required HLS tags; `EXT-X-TARGETDURATION` less than any `EXTINF` value; malformed manifest served to client; validation check omitted.

## Derives From

`INV-HLS-MANIFEST-LIVE-001`, `INV-HLS-MANIFEST-SEQUENCE-001`, `LAW-DECODABILITY`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_manifest_consistency.py`

## Enforcement Evidence

TODO
