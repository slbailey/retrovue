# INV-PLEX-TUNER-STATUS-001

## Behavioral Guarantee

The `/lineup_status.json` endpoint MUST report the tuner's scan state. The response MUST indicate scan completion so that Plex does not enter an indefinite scan-wait loop.

## Authority Model

The Plex adapter owns scan status reporting. No actual hardware scan occurs — RetroVue channels are always available.

## Boundary / Constraint

- `ScanInProgress` MUST be `0` (false). RetroVue has no physical scan process.
- `ScanPossible` MUST be `1` (true). Plex requires this to consider the device functional.
- `Source` MUST be `"Cable"`.
- The response MUST NOT change based on channel compilation state or viewer count.

## Violation

`ScanInProgress` reports `1`, causing Plex to wait indefinitely. Required fields missing from response.

## Derives From

`LAW-LIVENESS`

## Required Tests

- `pkg/core/tests/contracts/plex/test_plex_discovery.py` (TestPlexDiscovery)

## Enforcement Evidence

TODO
