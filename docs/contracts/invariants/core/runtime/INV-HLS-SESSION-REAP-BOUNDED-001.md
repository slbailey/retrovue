# INV-HLS-SESSION-REAP-BOUNDED-001

## Behavioral Guarantee

An expired HLS session is reaped within a bounded time window: at most `timeout + reap_interval` after the session's last activity. Reaping runs on a fixed schedule regardless of request activity.

## Authority Model

ChannelManager owns the reap timer. The timer is system-initiated (asyncio periodic task), not request-triggered.

## Boundary / Constraint

- The reap interval MUST be at most half the timeout threshold (`reap_interval <= timeout / 2`).
- The reap sweep MUST examine all sessions for the channel, not just recently active ones.
- Reaping MUST NOT be triggered by client requests — it MUST run on a fixed periodic schedule.
- If the reap timer fails to fire (event loop blocked), the next successful sweep MUST still correctly identify and remove all expired sessions.
- The reap task MUST be cancelled on channel teardown to prevent orphaned timers.

## Violation

Expired session persisting beyond `timeout + reap_interval`; reap interval exceeding `timeout / 2`; reap triggered by request instead of timer; orphaned reap timer after channel teardown.

## Derives From

`INV-HLS-VIEWER-PRESENCE-001`, `LAW-LIVENESS`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_viewer_count.py`

## Enforcement Evidence

TODO
