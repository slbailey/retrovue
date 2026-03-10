# INV-PLEX-STREAM-DISCONNECT-001

## Behavioral Guarantee

When a Plex client disconnects from a channel stream, the adapter MUST invoke the standard `tune_out` path. The adapter MUST NOT leave orphaned viewer references or prevent playout teardown when the last viewer departs.

## Authority Model

`ChannelManager` owns viewer reference counting. `ProgramDirector` owns playout lifecycle (last viewer out → stop playout). The adapter MUST NOT interfere with either.

## Boundary / Constraint

- Client disconnect (TCP close, HTTP abort, timeout) MUST trigger `tune_out` for that viewer.
- `tune_out` MUST be called exactly once per `tune_in`, regardless of disconnect cause.
- The adapter MUST NOT hold phantom viewer references after disconnect.
- If the Plex viewer is the last viewer, playout MUST stop according to existing `ChannelManager` policy.

## Violation

Viewer count does not decrement on Plex client disconnect. Playout continues after last Plex viewer departs. `tune_out` called zero or more than one time per `tune_in`.

## Derives From

`LAW-LIVENESS`, `LAW-RUNTIME-AUTHORITY`

## Required Tests

- `pkg/core/tests/contracts/plex/test_plex_streaming.py` (TestPlexStreaming)

## Enforcement Evidence

TODO
