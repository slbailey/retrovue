# INV-TS-EMISSION-LIVENESS

## Behavioral Guarantee
First decodable TS MUST be emitted within a defined bound after attach (e.g. 500ms from PCR-pace timing initialization). Output becomes decodable within that window.

## Boundary / Authority Model
Sink is responsible for emission. Timing initialization defines the start of the window. No extension of the bound without contract change.

## Violation
No decodable TS emitted within the allowed time after attach. MUST be logged; treat as liveness failure.

## Required Tests
- TS-EMISSION-001: first TS within bound after attach
- TS-EMISSION-002: violation logged when bound exceeded

## Enforcement Evidence
TODO
