# INV-BACKPRESSURE-SYMMETRIC

## Behavioral Guarantee
Audio and video advance together; neither stream leads the other by more than one frame duration. When backpressure is applied, both streams are throttled symmetrically.

## Authority Model
Single backpressure signal applies to both audio and video decode gates.

## Boundary / Constraint
A/V delta MUST remain ≤ one frame duration at all times. When one stream is blocked, the other MUST also block.

## Violation
A/V delta exceeds one frame duration; one stream decoding while the other is blocked.

## Required Tests
- `pkg/air/tests/contracts/Phase10PipelineFlowControlTests.cpp` (TEST_INV_P10_BACKPRESSURE_SYMMETRIC_NoAudioDrops)
- `pkg/air/tests/contracts/Phase9SymmetricBackpressureTests.cpp`

## Enforcement Evidence

- **Symmetric gate:** Decode gate in `VideoLookaheadBuffer` fill thread checks BOTH video and audio buffer depth before calling `av_read_frame` — when either buffer is full, both streams are blocked.
- **No audio drop:** Audio is never dropped under backpressure. `AudioLookaheadBuffer::Push` blocks (does not discard) when at capacity. Only video may be dropped in extreme conditions.
- **A/V delta bounded:** Single fill thread decodes both streams interleaved from the same demuxer, ensuring neither stream leads the other by more than one frame duration.
- Contract tests: `Phase9SymmetricBackpressureTests.cpp` validates symmetric throttling and A/V delta. `Phase10PipelineFlowControlTests.cpp` (`TEST_INV_P10_BACKPRESSURE_SYMMETRIC_NoAudioDrops`) proves zero audio drops under backpressure.
