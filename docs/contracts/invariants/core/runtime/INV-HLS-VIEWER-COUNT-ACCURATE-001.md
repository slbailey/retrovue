# INV-HLS-VIEWER-COUNT-ACCURATE-001

## Behavioral Guarantee

The reported viewer count for a channel equals the number of non-expired sessions at all times. Session creation, refresh, and reaping MUST maintain this invariant atomically. Viewer count drift causes incorrect first-viewer/last-viewer lifecycle transitions.

## Authority Model

ChannelManager owns session storage and viewer count. All mutations (create, refresh, reap) MUST occur under the viewer lock.

## Boundary / Constraint

- After every session mutation (create, reap), the system MUST verify `viewer_count == len(non_expired_sessions)`.
- If the check fails, the system MUST log at ERROR level with invariant ID, reported count, and actual session count, then force-correct the count.
- Session creation and first-viewer transition MUST be atomic — no window where the session exists but viewer count has not incremented.
- Session reaping and last-viewer transition MUST be atomic — no window where the session is removed but viewer count has not decremented.
- Concurrent session mutations for the same channel MUST be serialized.

## Violation

`viewer_count != len(non_expired_sessions)`; first-viewer transition without corresponding session; last-viewer transition with sessions remaining; concurrent unserialized session mutations.

## Derives From

`INV-HLS-VIEWER-PRESENCE-001`, `LAW-LIVENESS`, `LAW-RUNTIME-AUTHORITY`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_viewer_count.py`

## Enforcement Evidence

TODO
