# INV-READINESS-SINGLE-OWNER-001 (Readiness verdict has one owner)

## Behavioral Guarantee

The readiness verdict for an AIR session MUST be declared by exactly one owner at runtime. No component other than the designated readiness authority MUST write a READY, NOT_READY, or DEGRADED verdict. Contributing signals inform the verdict; they do not assert it.

## Authority Model

ReadinessController is the sole owner of readiness verdict state for each scope (session and candidate source). Producers of contributing signals — `PlayoutControl` RuntimePhase transitions, lookahead-buffer primed state, A/V phase tolerance, sink attachment, fallback engagement, the gRPC BlockEvent stream, and underflow counters — MUST NOT themselves declare a verdict.

## Boundary / Constraint

- Readiness verdict writes for a given scope MUST originate in exactly one module.
- Consumers MUST read the verdict from that module and MUST NOT synthesize an alternate verdict from the same input signals.
- Contributing signal surfaces MUST remain non-authoritative with respect to readiness; they produce facts, not verdicts.

## Violation

Any write to readiness verdict state from a module other than the designated owner; any consumer acting on a verdict value not sourced from the designated owner; any mechanism that computes a parallel verdict over the same input signals.

## Derives From

`LAW-RUNTIME-AUTHORITY`, `LAW-LIVENESS`

## Required Tests

- `runtime/tests/contracts/readiness/ReadinessInvariantTests.cpp`

## Enforcement Evidence

TODO
