# INV-HLS-VIEWER-PRESENCE-001

## Behavioral Guarantee

HLS viewer presence is detected by HTTP request recency. A viewer is present when the system has received a manifest or segment request carrying a valid session identifier within the timeout window. Expired sessions are reaped periodically.

## Authority Model

ChannelManager owns session tracking and reaping. ProgramDirector HTTP handlers own session touch on each request.

## Boundary / Constraint

- A viewer MUST be considered present only when an HTTP request with a valid session identifier has been received within the configured timeout threshold.
- The first request from an unknown session identifier MUST create a new viewer session (equivalent to tune-in). If the channel has no prior active sessions, this MUST trigger the first-viewer lifecycle transition.
- Each subsequent request MUST refresh the session's last-activity timestamp.
- Sessions whose last-activity timestamp exceeds the timeout threshold MUST be reaped. Reaping MUST occur at a frequency of at most half the timeout threshold.
- Simultaneous creation of two sessions for the same idle channel MUST trigger the first-viewer transition exactly once.
- A session identifier MUST be scoped to a single channel.

## Violation

Viewer counted as present with no recent request; first-viewer transition triggered more than once on simultaneous session creation; session persisting beyond timeout without refresh; reaping interval exceeding half the timeout.

## Derives From

`LAW-LIVENESS`, `LAW-RUNTIME-AUTHORITY`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_viewer_presence.py`

## Enforcement Evidence

TODO
