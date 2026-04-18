# INV-READINESS-NOT-BYTE-INFERRED-001 (Readiness is not byte-flow-inferred)

## Behavioral Guarantee

A READY verdict MUST NOT be derived from byte flow alone. The presence of bytes on the transport MUST NOT cause the readiness authority to publish READY when one or more correctness preconditions — primed state, A/V phase within tolerance, sink attachment, and absence of terminal fault — are not satisfied.

## Authority Model

ReadinessController owns the predicate. It MUST evaluate the full correctness precondition set for every READY verdict. Transport-layer components (sink, encoder, mux) MUST NOT be consulted as positive inputs to the READY predicate.

## Boundary / Constraint

- Byte-path liveness (bytes flowing, sockets open, encoder running) MUST NOT raise the verdict toward READY in the absence of the correctness preconditions.
- Sink attachment MAY be consulted only as a precondition that MUST also be joined by primed state and A/V phase within tolerance for READY to be declared.
- Terminal fault signals MUST take precedence over any byte-flow evidence.

## Violation

The readiness authority publishes READY while one or more of {video primed, audio primed, A/V delta within tolerance, sink attached, no outstanding terminal fault} is not satisfied; any derivation path that treats "bytes are flowing" as sufficient evidence for READY.

## Derives From

`LAW-LIVENESS`

## Required Tests

- `runtime/tests/contracts/readiness/ReadinessInvariantTests.cpp`

## Enforcement Evidence

TODO
