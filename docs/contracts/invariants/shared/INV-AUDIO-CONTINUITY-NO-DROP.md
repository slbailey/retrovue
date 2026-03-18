# INV-AUDIO-CONTINUITY-NO-DROP

## Behavioral Guarantee
Audio samples MUST NOT be discarded due to queue overflow, congestion, or backpressure. Total samples pushed MUST equal total samples popped across any complete cycle. Underflow MUST return false (no silence fabrication).

## Authority Model
`AudioLookaheadBuffer` owns this guarantee. Push blocks at capacity (never drops). TryPopSamples returns false on underflow (never injects synthetic audio).

## Boundary / Constraint
Backpressure resolution mechanisms MUST NOT violate sample continuity. Pop across frame boundaries MUST return contiguous samples with no gaps or drops at frame seams. Underflow events MUST be counted for observability.

## Violation
Any audio sample loss attributable to overflow or backpressure; silence injection on underflow; non-contiguous samples on cross-boundary pop. MUST be logged.

## Derives From
`LAW-LIVENESS`

## Required Tests
- `pkg/air/tests/contracts/BlockPlan/SharedInvAudioContinuityContractTests.cpp` (`Compliant_PushAndPop_NoSamplesLost`) — push N, pop all, TotalSamplesPushed == TotalSamplesPopped, zero underflow
- `pkg/air/tests/contracts/BlockPlan/SharedInvAudioContinuityContractTests.cpp` (`Compliant_Underflow_ReturnsFalse_NoSilenceInjected`) — empty buffer returns false, no fabrication, underflow counted
- `pkg/air/tests/contracts/BlockPlan/SharedInvAudioContinuityContractTests.cpp` (`Compliant_SamplesContiguous_MultiFramePop`) — pop across frame boundaries, contiguous, pushed == popped

## Enforcement Evidence
TODO
