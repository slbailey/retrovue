# INV-READINESS-OBSERVABLE-001 (Readiness transitions are observable)

## Behavioral Guarantee

Every change of the readiness verdict for a scope, and every change of the reason class attached to a NOT_READY or DEGRADED verdict, MUST produce an externally observable event. Silent mutation of readiness state MUST NOT occur.

## Authority Model

ReadinessController is the sole emitter of readiness transition events. Each scope (session and candidate source) has its own transition stream. Observers — contract tests, telemetry scrapers, operator tooling — consume the verdict and its transitions exclusively from this surface.

## Boundary / Constraint

- Every verdict value change MUST emit one transition event carrying the prior verdict, the new verdict, the reason class, and a monotonic timestamp.
- Entry into, and exit from, any DEGRADED verdict MUST emit a transition event even when the outer verdict value does not change as a result of a reason-class change inside DEGRADED.
- The transition event surface MUST be reachable outside the runtime process (metrics export, log record, or equivalent external observability channel).

## Violation

A verdict change that is not accompanied by a transition event; a transition event lacking prior verdict, new verdict, reason class, or timestamp; a verdict change observable only inside the producing process.

## Derives From

`LAW-LIVENESS`

## Required Tests

- `runtime/tests/contracts/readiness/ReadinessInvariantTests.cpp`

## Enforcement Evidence

TODO
