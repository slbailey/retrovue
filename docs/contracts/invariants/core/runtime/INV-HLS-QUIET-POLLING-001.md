# INV-HLS-QUIET-POLLING-001

## Behavioral Guarantee

HLS client polling MUST NOT produce per-request log output at INFO level or above. Playlist and segment GET requests are high-frequency, low-information events that MUST be suppressed from default log output.

## Authority Model

ProgramDirector HTTP server configuration owns log filtering. uvicorn access logger is the enforcement point.

## Boundary / Constraint

- HTTP requests matching `/hls/{channel_id}/live.m3u8` and `/hls/{channel_id}/seg_*.ts` MUST NOT be logged at INFO level.
- Lifecycle events (segmenter start, stop, standalone FFmpeg launch) MUST remain at INFO level.
- Error conditions on HLS paths MUST still be logged at WARNING or above.

## Violation

Any HLS playlist or segment GET request producing a log line at INFO level or above during normal operation.

## Derives From

`LAW-LIVENESS`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_no_disk_io.py`

## Enforcement Evidence

TODO
