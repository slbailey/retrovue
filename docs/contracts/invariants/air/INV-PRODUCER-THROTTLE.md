# INV-PRODUCER-THROTTLE

## Behavioral Guarantee
When the decode gate **denies** (no capacity), the producer MUST block or yield. It MUST NOT continue generating or enqueueing frames.

## Authority Model
The gate (per INV-DECODE-GATE) determines admission. This invariant defines required behavior when admission is denied.

## Boundary / Constraint
When capacity is unavailable, producer MUST block or yield. Producer MUST NOT continue producing frames while the gate is closed.

## Violation
When capacity is unavailable, producer continues generating or enqueueing frames (ignoring denial).

## Required Tests
- `pkg/air/tests/contracts/Phase10PipelineFlowControlTests.cpp` (decode gate / buffer full blocks producer)
- `pkg/air/tests/contracts/Phase9SymmetricBackpressureTests.cpp`

## Enforcement Evidence

- **Block on denial:** When the decode gate denies (per `INV-DECODE-GATE`), the fill thread in `VideoLookaheadBuffer` blocks or yields — it does not continue calling `av_read_frame` or enqueuing frames.
- **Backpressure propagation:** Buffer capacity directly controls decode rate. When buffers are full, the producer is throttled at the decode gate; no frames are generated or enqueued while the gate is closed.
- **No frame accumulation:** Producer cannot bypass the gate to accumulate frames outside the bounded buffer — all decoded frames pass through `VideoLookaheadBuffer::Push` / `AudioLookaheadBuffer::Push` which respect capacity limits.
- Contract tests: `Phase10PipelineFlowControlTests.cpp` proves producer blocks when gate is closed. `Phase9SymmetricBackpressureTests.cpp` validates throttle behavior under sustained backpressure across both streams.
