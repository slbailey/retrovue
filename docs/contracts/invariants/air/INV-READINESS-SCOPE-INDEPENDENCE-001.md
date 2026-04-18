# INV-READINESS-SCOPE-INDEPENDENCE-001 (Session and candidate-source verdicts are independent)

## Behavioral Guarantee

Session-scope readiness and candidate-source-scope readiness MUST be evaluated independently. A READY session MUST NOT imply that any candidate source is READY. A NOT_READY candidate source MUST NOT force the session verdict to NOT_READY. Verdicts from one scope MUST NOT be written from signals of the other.

## Authority Model

ReadinessController holds a distinct verdict per scope. Each scope's verdict MUST be computed from that scope's own precondition set. Cross-scope inference is prohibited.

## Boundary / Constraint

- Session-scope preconditions MUST include RuntimePhase, sink attachment, aggregated primed state, aggregated A/V phase, fallback engagement, and outstanding terminal events.
- Candidate-source-scope preconditions MUST include per-source opened state, per-source primed state, per-source EOF state, and the session's fallback engagement for that source.
- A consumer that needs both scopes MUST read both independently and MUST NOT substitute one for the other.

## Violation

Any derivation that writes a candidate-source verdict from session-scope signals, or a session verdict from a single candidate-source's signals; any consumer acting on one scope's verdict as if it were the other's.

## Derives From

`LAW-RUNTIME-AUTHORITY`, `LAW-LIVENESS`

## Required Tests

- `runtime/tests/contracts/readiness/ReadinessInvariantTests.cpp`

## Enforcement Evidence

TODO
