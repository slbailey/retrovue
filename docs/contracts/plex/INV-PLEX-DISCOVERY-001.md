# INV-PLEX-DISCOVERY-001

## Behavioral Guarantee

The `/discover.json` endpoint MUST return a valid HDHomeRun device descriptor that identifies the RetroVue instance as a virtual tuner. The response MUST be structurally identical to a real HDHomeRun device discovery payload.

## Authority Model

The Plex adapter owns device identity. Channel count is derived from `ProgramDirector`'s channel registry — the adapter MUST NOT maintain an independent channel list.

## Boundary / Constraint

- `FriendlyName` MUST be a stable, operator-configurable string.
- `DeviceID` MUST be a stable hex identifier unique per RetroVue instance.
- `TunerCount` MUST equal the number of channels registered in `ProgramDirector`.
- `LineupURL` MUST point to the same adapter's `/lineup.json` endpoint.
- The response MUST NOT include fields that imply hardware capabilities (firmware version, hardware model number) that do not exist.

## Violation

Response missing required HDHomeRun fields. `TunerCount` diverges from registered channel count. `LineupURL` points to a non-existent or external endpoint.

## Derives From

`LAW-CONTENT-AUTHORITY`

## Required Tests

- `pkg/core/tests/contracts/plex/test_plex_discovery.py`

## Enforcement Evidence

TODO
