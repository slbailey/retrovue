# INV-SEAM-OBSERVABLE-001 (Seam decisions are externally observable)

## Behavioral Guarantee

Every seam decision MUST produce a named, externally observable event. Silent state transitions in SeamController's per-boundary state machine are prohibited. Observers outside the runtime process MUST be able to reconstruct the complete seam-decision history of a session from the emitted event stream.

## Authority Model

SeamController is the sole emitter of seam-decision events. Observers — contract tests, telemetry scrapers, operator tooling — consume seam decisions exclusively through this event stream. No enforcement surface produces parallel seam-decision events.

## Boundary / Constraint

- Every transition in SeamController's per-boundary state sequence — `idle → armed`, `armed → executing`, `executing → committed`, `armed → missed`, `missed → pad-bridge`, `missed → JIP`, `committed → completed` — MUST emit an event carrying boundary identity, prior state, new state, reason class, and a monotonic timestamp.
- Every emitted event's reason class MUST be drawn from a bounded, documented set declared at the type level.
- The event surface MUST be reachable outside the runtime process (structured log line, metrics counter with labels, or equivalent external observability channel).
- A seam decision visible only through inference from downstream side effects (frame emissions, buffer state, encoder output) does not satisfy this invariant — the emission MUST be explicit.

## Violation

A seam state transition that does not emit a transition event; an event lacking any of boundary identity, prior state, new state, reason class, or timestamp; an event whose reason class is not in the documented set; a seam decision observable only inside SeamController's process boundary.

## Derives From

`LAW-LIVENESS`

## Required Tests

- `runtime/tests/contracts/seam/SeamAuthorityInvariantTests.cpp`

## Enforcement Evidence

TODO
