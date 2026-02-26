# INV-P9-TS-EMISSION-LIVENESS

## Behavioral Guarantee
First decodable TS MUST be emitted within a bounded window after attach (e.g. 500ms of PCR-pace timing initialization). Output must become live within the allowed time.

## Authority Model
Sink is responsible for emitting; timing initialization defines the start of the window.

## Boundary / Constraint
First decodable TS packet MUST be emitted within the defined bound (e.g. 500ms) after attach / PCR-pace initialization.

## Violation
No emission within the allowed time; output fails to become live.

## Required Tests
TODO

## Enforcement Evidence
TODO
