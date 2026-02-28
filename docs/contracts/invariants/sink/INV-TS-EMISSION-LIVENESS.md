# INV-TS-EMISSION-LIVENESS

## Behavioral Guarantee
First decodable TS MUST be emitted within a defined bound after attach (e.g. 500ms from PCR-pace timing initialization). Output becomes decodable within that window.

## Authority Model
Sink is responsible for emission. Timing initialization defines the start of the window.

## Boundary / Constraint
No extension of the bound without contract change.

## Violation
No decodable TS emitted within the allowed time after attach. MUST be logged; treat as liveness failure.

## Required Tests
- `pkg/air/tests/contracts/Phase9OutputBootstrapTests.cpp` (TEST_INV_P9_TS_EMISSION_LIVENESS_500ms)
- TS-EMISSION-001: first TS within bound after attach
- TS-EMISSION-002: violation logged when bound exceeded

## Enforcement Evidence

- **Boot window:** `MpegTSOutputSink` emits TS packets immediately during the ~500ms boot window without waiting for media — `g_pcr_pace_init_time` tracks the deadline for this window.
- **Null packet fill:** During the boot window, null TS packets fill gaps to maintain transport stream continuity before media frames are available.
- **Bounded liveness:** The boot window is a fixed bound (~500ms from PCR-pace initialization); first decodable TS must appear within this bound or a liveness violation is logged.
- Contract tests: `Phase9OutputBootstrapTests.cpp` (`TEST_INV_P9_TS_EMISSION_LIVENESS_500ms`) validates that decodable TS is emitted within the 500ms bound after attach.
