# INV-PCR-PACED-MUX

## Behavioral Guarantee
Emission is time-driven by wall clock / PCR. Frames are emitted when the output clock reaches scheduled presentation time, not when frames become available.

## Authority Model
Mux loop is the sole pacing authority. Producers do not pace the output loop.

## Boundary / Constraint
Mux MUST wait for wall_clock >= frame.ct_us before dequeue and emission. Emission MUST NOT be triggered by frame availability alone.

## Violation
Emitting before scheduled CT or emitting based on availability rather than clock.

## Required Tests
- `pkg/air/tests/contracts/PrimitiveInvariants/PacingInvariantContractTests.cpp`

## Enforcement Evidence

- `MpegTSOutputSink` main loop: peek frame CT → wait for wall clock to reach `frame.ct_us` → dequeue → emit. Emission is gated by clock comparison, not frame availability.
- **Pacing instrumentation:** `pacing_wait_count` and `total_pacing_wait_us` counters track every pacing wait, making clock-driven emission observable and auditable.
- **No producer-driven emission:** Producers push into bounded buffers; the mux loop pulls at wall-clock cadence. No callback or signal from producers triggers emission.
- Contract tests: `PacingInvariantContractTests.cpp` validates that emission timestamps align with scheduled CT and that no frame is emitted before its scheduled presentation time.
