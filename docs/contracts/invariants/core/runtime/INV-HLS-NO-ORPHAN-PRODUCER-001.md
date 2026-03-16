# INV-HLS-NO-ORPHAN-PRODUCER-001

## Behavioral Guarantee

A producer MUST NOT remain running after the linger period expires with zero viewers. An orphaned producer wastes compute and violates the compute-follows-attention principle.

## Authority Model

ChannelManager owns linger timer and producer teardown. The linger timer is the enforcement mechanism.

## Boundary / Constraint

- After the linger period expires, the system MUST verify `viewer_count == 0` and if so, stop the producer.
- If the producer is found running with `viewer_count == 0` and no active linger timer, the system MUST log at ERROR level with invariant ID and initiate immediate teardown.
- The linger timer MUST be cancelled if a viewer arrives during the linger period.
- On channel manager periodic health check, the system MUST verify: `producer_running implies (viewer_count > 0 or linger_timer_active)`.

## Violation

Producer running with zero viewers and no linger timer; linger timer not cancelled on viewer arrival; producer surviving past linger expiry.

## Derives From

`INV-HLS-VIEWER-PRESENCE-001`, `INV-HLS-ENDPOINT-COEXIST-001`, `LAW-LIVENESS`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_channel_runtime.py`

## Enforcement Evidence

TODO
