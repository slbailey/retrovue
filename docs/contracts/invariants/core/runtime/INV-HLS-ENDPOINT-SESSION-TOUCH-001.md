# INV-HLS-ENDPOINT-SESSION-TOUCH-001

## Behavioral Guarantee

Every successful (HTTP 200) manifest or segment response refreshes the viewer session's last-activity timestamp. Failed responses (4xx, 5xx) MUST NOT refresh the timestamp. This prevents phantom sessions from persisting due to error-loop requests.

## Authority Model

ProgramDirector HTTP handlers own touch placement. ChannelManager owns session timestamp storage.

## Boundary / Constraint

- The session touch MUST occur after the response data is confirmed available (segment found in ring, manifest generated successfully), not before.
- HTTP 503 (startup) MUST NOT touch the session per `INV-HLS-PHANTOM-CLEANUP-001`.
- HTTP 404 (segment not found) MUST NOT touch the session.
- A request with no session identifier MUST create a new session (touch is implicit in creation).
- The touch MUST be idempotent — multiple touches within the same reap interval have no additional effect beyond updating the timestamp.

## Violation

Session touched on failed response; session not touched on successful response; phantom session persisting due to error-loop touches.

## Derives From

`INV-HLS-VIEWER-PRESENCE-001`, `INV-HLS-PHANTOM-CLEANUP-001`, `LAW-LIVENESS`

## Required Tests

- `server/tests/contracts/runtime/test_inv_hls_delivery_path.py`

## Enforcement Evidence

TODO
