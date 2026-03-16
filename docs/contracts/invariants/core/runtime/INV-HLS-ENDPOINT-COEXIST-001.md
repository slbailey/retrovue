# INV-HLS-ENDPOINT-COEXIST-001

## Behavioral Guarantee

HLS endpoints and the legacy raw TS endpoint for the same channel share the same producer and encoder output. Neither endpoint interferes with the other's operation. Viewers on both endpoints count toward the same channel viewer population.

## Authority Model

ProgramDirector owns endpoint routing. ChannelManager owns unified viewer count. Both delivery paths consume the same upstream TS output.

## Boundary / Constraint

- A viewer on the HLS endpoint and a viewer on the legacy TS endpoint MUST both count toward the channel's viewer population.
- Neither endpoint's behavior MUST be degraded by the other's activity.
- Both endpoints MUST share the same playout producer — a second encoder MUST NOT be started.
- The manifest endpoint MUST return `Content-Type: application/vnd.apple.mpegurl`. The segment endpoint MUST return `Content-Type: video/mp2t`. The legacy TS endpoint MUST return `Content-Type: video/mpeg` per `INV-RAW-TS-TRANSPORT-001`.
- The manifest response MUST carry `Cache-Control: no-cache, max-age=0`. Segment responses MUST carry `Cache-Control: public` with a positive `max-age`.

## Violation

HLS viewer not counted in channel population; second encoder started for HLS path; incorrect Content-Type on any endpoint; endpoint degradation from sibling endpoint activity.

## Derives From

`LAW-LIVENESS`, `LAW-RUNTIME-AUTHORITY`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_endpoint_coexist.py`

## Enforcement Evidence

TODO
