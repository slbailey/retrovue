# INV-PLEX-STREAM-START-001

## Behavioral Guarantee

A Plex client requesting a channel stream MUST trigger the same viewer lifecycle as a direct MPEG-TS request. The Plex adapter MUST delegate stream initiation to `ProgramDirector.stream_channel()` — it MUST NOT implement independent stream startup logic.

## Authority Model

`ProgramDirector.stream_channel()` owns the viewer lifecycle (`tune_in` → stream → `tune_out`). The Plex adapter is a transport adapter only.

## Boundary / Constraint

- Stream request MUST invoke `stream_channel()` with the correct channel identifier.
- The adapter MUST NOT spawn AIR processes, compile schedules, or manage playout sessions directly.
- The MPEG-TS byte stream delivered to Plex MUST be identical to the stream served via `/channel/{id}.ts`.
- JIP (join-in-progress) offset calculation MUST be performed by the existing `ChannelManager`, not by the adapter.

## Violation

Adapter bypasses `stream_channel()`. Adapter spawns AIR or compiles schedules independently. Stream bytes differ between Plex and direct MPEG-TS endpoints for the same channel at the same time.

## Derives From

`LAW-RUNTIME-AUTHORITY`, `LAW-LIVENESS`

## Required Tests

- `pkg/core/tests/contracts/plex/test_plex_streaming.py` (TestPlexStreaming)

## Enforcement Evidence

TODO
