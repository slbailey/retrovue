# INV-VERDICT-REASON-CLASS-BOUNDED-001 (Verdict reason class is bounded)

## Behavioral Guarantee

Every NOT_READY verdict and every DEGRADED verdict MUST carry a reason class drawn from a bounded, documented set. An unclassified NOT_READY or DEGRADED verdict MUST NOT be emitted. The reason-class set MUST be declared at the type level so that emission of an unclassified value fails to compile.

## Authority Model

ReadinessController declares and owns the reason-class set. Additions to the set are contract changes and MUST be reflected in the canonical invariant and in this invariant's `Required Tests` coverage before emission.

## Boundary / Constraint

- Every NOT_READY verdict MUST name one reason class from the bounded set.
- Every DEGRADED verdict MUST name one reason class from the bounded set.
- A READY verdict MUST carry a reason class that designates the ready condition or MUST carry no reason class when the type system expresses READY as an unqualified state.
- The reason-class set MUST be documented in a single canonical location; implementation MUST NOT enumerate reason classes elsewhere.

## Violation

Emission of a NOT_READY or DEGRADED verdict without a reason class; emission of a reason class not in the declared set; enumeration of reason classes in a second location that diverges from the canonical set.

## Derives From

`LAW-LIVENESS`

## Required Tests

- `runtime/tests/contracts/readiness/ReadinessInvariantTests.cpp`

## Enforcement Evidence

TODO
