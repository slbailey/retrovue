# INV-NO-SILENCE-INJECTION

## Behavioral Guarantee
No synthetic silence is injected during steady-state. Producer audio is the only audio source once steady-state has begun.

## Authority Model
Steady-state entry disables silence injection; producer is the sole audio source.

## Boundary / Constraint
Silence injection MUST be disabled when steady-state begins. MUST NOT inject silence or fabricate audio packets during steady-state.

## Violation
Injected silence after steady-state has begun.

## Required Tests
- `pkg/air/tests/contracts/BlockPlan/LookaheadBufferContractTests.cpp` (AudioUnderflow_ReturnsFalse_NoSilenceInjected)
- `pkg/air/tests/contracts/Phase9SteadyStateSilenceTests.cpp`

## Enforcement Evidence

- `AudioLookaheadBuffer::TryPopSamples` returns `false` on underflow — no synthetic silence is fabricated or injected into the content audio path.
- `PadProducer` generates real silence frames via `AudioFrame()` only when PAD is the authoritative segment — silence enters through the PAD source path, not by injection into the content path.
- **Steady-state boundary:** Once steady-state begins (first real content frame committed), no silence injection path is reachable from the content audio pipeline.
- Contract tests: `LookaheadBufferContractTests.cpp` (`AudioUnderflow_ReturnsFalse_NoSilenceInjected`) proves underflow returns false without fabricating samples. `Phase9SteadyStateSilenceTests.cpp` validates no silence after steady-state entry.
