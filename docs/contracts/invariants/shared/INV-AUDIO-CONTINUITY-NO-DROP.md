# INV-AUDIO-CONTINUITY-NO-DROP

## Behavioral Guarantee
Audio samples MUST NOT be discarded as a result of queue overflow, congestion, or backpressure.

Audio sample continuity MUST be preserved.

## Authority Model
Audio path and backpressure design own this guarantee.

## Boundary / Constraint
Backpressure resolution mechanisms MUST NOT violate sample continuity.

## Violation
Any audio sample loss attributable to overflow or backpressure MUST be logged as a contract violation.

## Required Tests
- `pkg/air/tests/contracts/Phase11AudioContinuityTests.cpp`
- `pkg/air/tests/contracts/BlockPlan/LookaheadBufferContractTests.cpp` (AudioUnderflow_ReturnsFalse_NoSilenceInjected)

## Enforcement Evidence

- `VideoLookaheadBuffer` fill thread: audio packets are always pushed to `AudioLookaheadBuffer` even when video frames are dropped due to backpressure — audio continuity is preserved unconditionally.
- `AudioLookaheadBuffer::Push` blocks when at capacity (does not discard) — no audio sample is ever dropped due to queue overflow.
- **Asymmetric drop policy:** Under extreme backpressure, only video may be dropped; audio is never discarded. This asymmetry is enforced at the fill-thread level.
- Contract tests: `Phase11AudioContinuityTests.cpp` validates zero audio drops across sustained backpressure scenarios. `LookaheadBufferContractTests.cpp` (`AudioUnderflow_ReturnsFalse_NoSilenceInjected`) validates the underflow path returns false without fabricating or dropping samples.
