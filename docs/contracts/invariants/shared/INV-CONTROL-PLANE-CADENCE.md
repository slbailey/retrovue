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
- `pkg/air/tests/contracts/Phase9OutputBootstrapTests.cpp` (TS emission within bound; mux does not wait indefinitely)
- `pkg/air/tests/contracts/PrimitiveInvariants/SinkLivenessContractTests.cpp`

## Enforcement Evidence

- **Boot window emission:** `MpegTSOutputSink` emits TS immediately during the boot window (~500ms) without waiting for media — control-plane packets (PAT/PMT, PCR) are emitted on schedule regardless of media availability.
- **Null packet loop:** When no media is available, null TS packets maintain transport cadence and carry PCR, ensuring decoders stay synchronized.
- **Bounded media wait:** Media wait within the mux loop is bounded by the control-plane emission cadence — the mux does not wait indefinitely for a media frame before emitting the next control-plane burst.
- Contract tests: `Phase9OutputBootstrapTests.cpp` validates TS emission within the 500ms bound when media is not yet available. `SinkLivenessContractTests.cpp` validates continuous control-plane emission independent of media starvation.
