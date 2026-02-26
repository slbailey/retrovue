# LAW-LIVENESS

## Constitutional Principle

Once live output begins, emission must continue until explicit teardown.

## Implications

- No implicit EOF.
- No silent stalls.
- No output starvation while session is live.
- Backpressure must not cause silent freeze.

## Violation

Ceasing emission without explicit teardown or terminal failure state.