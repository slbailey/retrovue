# INV-DECODE-GATE

## Behavioral Guarantee
Decode is **admitted** only when buffer has capacity (at least one slot free). The admission condition is binary: capacity present or not. No hysteresis — resume condition MUST equal admission condition (one slot free).

## Authority Model
Downstream buffer capacity defines the gate; the rule is the condition under which decode is permitted.

## Boundary / Constraint
Decode is permitted if and only if at least one slot is free. Hysteresis (e.g. low-water / high-water thresholds that delay resume after capacity returns) MUST NOT be used.

## Violation
Decoding when no capacity exists (gate closed). Using hysteresis so that resume differs from the admission condition.

## Required Tests
- `pkg/air/tests/contracts/Phase10PipelineFlowControlTests.cpp` (TEST_P10_DECODE_GATE_001_NoReadWhenEitherBufferFull)
- `pkg/air/tests/contracts/Phase9SymmetricBackpressureTests.cpp`

## Enforcement Evidence

- `VideoLookaheadBuffer` fill thread checks buffer capacity before each `av_read_frame` call — decode is admitted only when at least one slot is free in both video and audio buffers.
- **No hysteresis:** Resume condition is identical to admission condition (one slot free). No low-water/high-water threshold logic exists in the gate path.
- **Binary gate:** Gate is open (capacity present) or closed (no capacity). Fill thread blocks when closed; resumes immediately when a single slot becomes available.
- Contract tests: `Phase10PipelineFlowControlTests.cpp` (`TEST_P10_DECODE_GATE_001_NoReadWhenEitherBufferFull`) proves decode is blocked when either buffer is full. `Phase9SymmetricBackpressureTests.cpp` validates gate behavior under sustained backpressure.
