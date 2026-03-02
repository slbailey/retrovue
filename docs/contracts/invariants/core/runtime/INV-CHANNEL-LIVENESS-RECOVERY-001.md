# INV-CHANNEL-LIVENESS-RECOVERY-001

## Behavioral Guarantee

ChannelManager MUST attempt to restore continuous emission after a transient producer failure while viewers remain connected. Recovery MUST NOT be attempted when the session ended due to explicit teardown (last viewer left, lookahead exhausted).

## Authority Model

ChannelManager owns liveness recovery decisions. BlockPlanProducer signals failure; it does not decide whether to restart.

## Boundary / Constraint

1. When a producer session ends with a recoverable reason AND `viewer_count > 0`, ChannelManager MUST schedule a new producer start.
2. Recoverable reasons: session termination not caused by explicit operator/viewer teardown or schedule exhaustion.
3. Recovery attempts MUST use bounded, increasing delays between consecutive failures.
4. After a finite number of consecutive failures, ChannelManager MUST stop retrying and enter an error state.
5. Recovery MUST be idempotent: no overlapping restart attempts.
6. A recoverable session end MUST NOT transition the channel into a permanently terminal state.

## Violation

Emission ceases while `viewer_count > 0` and no recovery is attempted after a transient producer failure. MUST be logged.

## Derives From

`LAW-LIVENESS`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_channel_liveness_recovery.py`

## Enforcement Evidence

TODO
