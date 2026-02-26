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
TODO

## Enforcement Evidence
TODO
