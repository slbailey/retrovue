# INV-HLS-PHANTOM-CLEANUP-001

## Behavioral Guarantee

HLS phantom viewers MUST be cleaned up when channel startup fails. Failed HLS responses (non-200) MUST NOT refresh the phantom viewer's activity timestamp.

## Authority Model

ProgramDirector HLS endpoint handler owns phantom lifecycle and activity tracking.

## Boundary / Constraint

- When HLS channel startup fails (no fanout buffer created), the segmenter MUST be stopped and the phantom session MUST be removed from `_hls_phantom_sessions`.
- HTTP 503 responses on the HLS playlist endpoint MUST NOT update `_hls_last_activity`. Only successful (200) responses MUST update the activity timestamp.
- A failed startup MUST NOT leave the segmenter in a "running" state that blocks future startup attempts.

## Violation

A phantom session entry persists in `_hls_phantom_sessions` after startup failure; or a 503 HLS response updates `_hls_last_activity`, preventing phantom idle timeout.

## Derives From

`LAW-LIVENESS`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_phantom_cleanup.py`

## Enforcement Evidence

TODO
