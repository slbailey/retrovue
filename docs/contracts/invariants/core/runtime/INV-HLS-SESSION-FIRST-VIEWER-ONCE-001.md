# INV-HLS-SESSION-FIRST-VIEWER-ONCE-001

## Behavioral Guarantee

The first-viewer lifecycle transition (0 to 1 viewers) fires exactly once, even when multiple sessions are created concurrently. The transition is protected by the viewer lock and includes a post-increment guard.

## Authority Model

ChannelManager owns the 0-to-1 transition. The viewer lock serializes session creation.

## Boundary / Constraint

- The first-viewer check MUST occur inside the same critical section as the session insertion and viewer count increment.
- The check MUST be: `viewer_count_before_insert == 0`.
- If two threads race to create sessions, only the thread that observes `count == 0` MUST trigger `on_first_viewer()`.
- `on_first_viewer()` MUST be idempotent — if called twice (defensive), it MUST NOT start a second producer.
- The same pattern applies to the last-viewer transition (1 to 0): only the thread that decrements to 0 MUST trigger `on_last_viewer()`.

## Violation

`on_first_viewer()` called twice for the same activation; producer started twice; first-viewer check outside the critical section; last-viewer fired with sessions remaining.

## Derives From

`INV-HLS-VIEWER-PRESENCE-001`, `INV-HLS-LIFECYCLE-SEGMENT-READY-001`, `LAW-LIVENESS`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_viewer_count.py`

## Enforcement Evidence

TODO
