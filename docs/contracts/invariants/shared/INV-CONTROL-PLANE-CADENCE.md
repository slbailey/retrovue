# INV-CONTROL-PLANE-CADENCE

## Behavioral Guarantee
Control-plane (e.g. PAT/PMT, PCR) is emitted on a cadence independent of media availability. The mux MUST NOT wait indefinitely for media before emitting control-plane. Media wait is bounded by control-plane cadence.

## Authority Model
Output remains valid and time-bounded even when media is starved. Control-plane emission is not gated by media availability.

## Boundary / Constraint
Control-plane MUST be emitted on schedule regardless of media. Media wait loop MUST be bounded by control-plane cadence (e.g. emission within 500ms window).

## Violation
Mux waiting indefinitely for media without emitting control-plane; control-plane emission blocked by media starvation. MUST be logged.

## Required Tests
TODO

## Enforcement Evidence
TODO
