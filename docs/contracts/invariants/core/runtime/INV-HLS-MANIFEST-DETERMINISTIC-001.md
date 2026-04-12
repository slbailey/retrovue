# INV-HLS-MANIFEST-DETERMINISTIC-001

## Behavioral Guarantee

Given the same ring snapshot, the manifest generator produces byte-identical output regardless of which client requested it, how many times it is called, or the server's current system time. The manifest is a pure function of the ring window.

## Authority Model

ManifestGenerator owns determinism. The generator MUST NOT read any state other than the ring snapshot when constructing the playlist.

## Boundary / Constraint

- The generator MUST NOT incorporate request headers, client IP, session ID, request timestamp, or any per-request state into the manifest body.
- The generator MUST NOT call system clock functions during manifest construction.
- Two calls to the generator with the same ring snapshot MUST produce byte-identical output.
- Non-determinism in the manifest body (e.g., random nonces, timestamps from `time.time()`) constitutes a violation.

## Violation

Manifest content varying between calls with the same ring state; system clock read during generation; per-request data in manifest body.

## Derives From

`INV-HLS-MANIFEST-CHANNEL-SCOPED-001`, `LAW-CLOCK`, `LAW-DERIVATION`

## Required Tests

- `server/tests/contracts/runtime/test_inv_hls_delivery_path.py`

## Enforcement Evidence

TODO
