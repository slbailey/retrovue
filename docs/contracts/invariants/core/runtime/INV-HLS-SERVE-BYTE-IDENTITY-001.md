# INV-HLS-SERVE-BYTE-IDENTITY-001

## Behavioral Guarantee

The HTTP segment endpoint serves the exact bytes stored in the segment ring for the requested index. No transformation, transcoding, re-muxing, or modification occurs between ring storage and HTTP response.

## Authority Model

ProgramDirector HTTP handler owns segment serving. SegmentRing `get()` is the sole data source.

## Boundary / Constraint

- The segment endpoint MUST call `ring.get(index)` and return the result's `data` field directly as the HTTP response body.
- No byte-level transformation MUST occur between `ring.get()` and the response body.
- The response `Content-Length` MUST equal `len(segment.data)`.
- If `ring.get()` returns absence, the endpoint MUST return HTTP 404, not an empty 200.

## Violation

Response body differing from `segment.data`; any byte transformation in the serve path; HTTP 200 with empty body for missing segment; `Content-Length` not matching payload size.

## Derives From

`INV-HLS-SEGMENT-IMMUTABLE-001`, `INV-HLS-ENDPOINT-COEXIST-001`, `LAW-IMMUTABILITY`

## Required Tests

- `server/tests/contracts/runtime/test_inv_hls_delivery_path.py`

## Enforcement Evidence

TODO
