# INV-HLS-NO-DISK-IO-001

## Behavioral Guarantee

HLS segment and playlist data MUST be stored in and served from memory. No filesystem I/O MUST occur on the segment feed, playlist serve, or segment serve paths.

## Authority Model

HLSSegmenter owns segment storage. ProgramDirector HTTP handlers own serving. Both MUST use in-memory data structures exclusively. Single-process runtime assumed.

## Boundary / Constraint

- Completed segments MUST be stored as `bytes` objects in a bounded in-memory collection (at most `max_segments` retained).
- Playlist content MUST be generated from in-memory segment metadata on each request.
- HTTP handlers MUST serve playlist and segment responses from in-memory data, not via filesystem reads.
- The path `/tmp/retrovue-hls` MUST NOT be created, written to, or read from during HLS operation.
- Segment names served over HTTP MUST match the pattern `seg_\d{5}\.ts` exactly. All other names MUST be rejected.

## Violation

Any filesystem write (`write_bytes`, `write_text`, `mkdir`) or read (`read_text`, `read_bytes`, `FileResponse`) within the HLS feed/serve hot path. Any segment name accepted by the HTTP handler that does not match the canonical pattern.

## Derives From

`LAW-LIVENESS`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_no_disk_io.py`

## Enforcement Evidence

TODO
