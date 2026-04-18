# INV-VERDICT-BOUNDED-STATES-001 (Readiness verdict has a bounded state set)

## Behavioral Guarantee

The readiness verdict MUST be one of exactly three values: READY, NOT_READY, DEGRADED. No fourth value, null value, or "unknown" value MUST be emitted on the verdict surface. A scope whose verdict cannot currently be computed MUST report NOT_READY with a reason class that names the unobservability.

## Authority Model

ReadinessController enforces the bounded state set at the verdict emission site. The set MUST be declared at the type level (a bounded enumeration) so that emission of any value outside the set fails to compile.

## Boundary / Constraint

- Verdict producers MUST NOT emit any value outside {READY, NOT_READY, DEGRADED}.
- Verdict consumers MUST handle exactly these three values.
- A scope whose signals cannot currently be observed MUST be reported as NOT_READY with a named reason class, not as a novel or absent value.

## Violation

Any emission of a verdict value outside the bounded set; any null, absent, or "unknown" verdict on the emission surface; any consumer pathway that accepts a fourth state.

## Derives From

`LAW-LIVENESS`

## Required Tests

- `runtime/tests/contracts/readiness/ReadinessInvariantTests.cpp`

## Enforcement Evidence

TODO
