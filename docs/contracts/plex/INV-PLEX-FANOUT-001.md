# INV-PLEX-FANOUT-001

## Behavioral Guarantee

Plex viewers MUST share the same playout instance as direct MPEG-TS viewers on the same channel. The adapter MUST NOT create a separate AIR process, fanout, or playout session for Plex clients.

## Authority Model

`ChannelManager` owns the single-producer-per-channel guarantee. All viewers — regardless of transport origin — attach to the same producer fanout.

## Boundary / Constraint

- A Plex viewer tuning into a channel that already has active direct viewers MUST receive bytes from the same producer.
- A direct viewer tuning into a channel that already has active Plex viewers MUST receive bytes from the same producer.
- At most one AIR process MUST exist per channel at any time, regardless of how many Plex and direct viewers are attached.
- The adapter MUST NOT maintain a separate byte buffer, re-mux, or transcode the stream.

## Violation

Multiple AIR processes running for the same channel. Plex viewer receives a different byte stream than a direct viewer who tuned in at the same instant. Adapter maintains an independent buffer or re-encoding pipeline.

## Derives From

`LAW-LIVENESS`, `LAW-RUNTIME-AUTHORITY`

## Required Tests

- `pkg/core/tests/contracts/plex/test_plex_streaming.py` (TestPlexStreaming)

## Enforcement Evidence

TODO
