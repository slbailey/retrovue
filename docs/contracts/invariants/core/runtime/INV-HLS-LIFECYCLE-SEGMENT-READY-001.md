# INV-HLS-LIFECYCLE-SEGMENT-READY-001

## Behavioral Guarantee

After producer start, there is a bounded startup period before the first completed segment is available. During this period, the manifest endpoint communicates "not yet ready" rather than returning an empty or malformed playlist. Once the first segment is available, new segments are produced at real-time rate.

## Authority Model

ChannelManager owns producer lifecycle. HLSSegmenter owns segment production rate. ProgramDirector owns HTTP response during startup.

## Boundary / Constraint

- When the channel is starting and no segments are yet available, the manifest endpoint MUST return HTTP 503 with a `Retry-After` header.
- The manifest endpoint MUST NOT return an empty playlist or a playlist with zero segment entries.
- A viewer joining an active channel with available segments MUST be able to immediately retrieve the current manifest and all segments in the window.
- Segment production rate during steady state MUST be approximately one per target segment duration, governed by real-time playout, not by client demand.
- Additional viewers joining an active channel (N to N+1 where N >= 1) MUST NOT affect the producer, segmenter, or segment ring.

## Violation

Empty or malformed manifest served during startup; manifest endpoint returning 200 with zero segments; production rate diverging from real-time; per-viewer resource allocation in the production pipeline.

## Derives From

`LAW-LIVENESS`

## Required Tests

- `server/tests/contracts/runtime/test_inv_hls_lifecycle.py`

## Enforcement Evidence

TODO
