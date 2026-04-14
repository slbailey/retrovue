# INV-AUDIO-CONTINUITY-NO-DROP

## Behavioral Guarantee

For every audio sample that **enters** `AudioLookaheadBuffer` via a successful **`Push`**, the buffer **MUST** preserve **sample continuity**: no loss due to **queue overflow**, **queue congestion** (capacity), or **post-push backpressure** handling inside the buffer. Total samples **pushed** **MUST** equal total samples **popped** across any **complete** drain cycle that does not reset the buffer. **Underflow** on pop **MUST** return false and **MUST NOT** fabricate silence.

## Authority Model

**`AudioLookaheadBuffer`** owns continuity **after admission**. **`VideoLookaheadBuffer`** fill thread owns **pre-push** decisions per **INV-FILL-AV-LEAD-CLAMP-001**.

## Boundary / Constraint

### Committed vs suppressed samples

1. **Committed sample:** A sample that is accepted into the buffer’s accounting by **`Push`** returning success (`kPushed` or equivalent).
2. **Suppressed sample:** Decoded audio that **never** calls `Push` success because **`INV-FILL-AV-LEAD-CLAMP-001`** forbids admission for that decode cycle.

**Formal resolution (Conflict B):** **Suppression is not a “drop” under this invariant.** This invariant’s “MUST NOT be discarded” applies **only** to samples **after** successful **`Push`**. **Suppressed** samples are **outside** `AudioLookaheadBuffer` duty; they are governed by **INV-FILL-AV-LEAD-CLAMP-001** and **MUST** be counted by fill-domain diagnostics (counters / logs) so they are **not** confused with **post-push** loss.

### Queue backpressure

`Push` **MUST** block at capacity — **not** discard. That remains mandatory.

### Pop

Pop across frame boundaries **MUST** return contiguous committed samples. Underflow **MUST** be observable (counted).

## Violation

- Any **committed** sample lost due to overflow, erroneous discard inside the buffer, or silent fabrication on underflow.
- Classifying **INV-FILL-AV-LEAD-CLAMP-001** suppression as a violation of **this** invariant (it is **not**).

## Derives From

`LAW-LIVENESS`

## Required Tests

- `runtime/tests/contracts/BlockPlan/SharedInvAudioContinuityContractTests.cpp` (`Compliant_PushAndPop_NoSamplesLost`)
- `runtime/tests/contracts/BlockPlan/SharedInvAudioContinuityContractTests.cpp` (`Compliant_Underflow_ReturnsFalse_NoSilenceInjected`)
- `runtime/tests/contracts/BlockPlan/SharedInvAudioContinuityContractTests.cpp` (`Compliant_SamplesContiguous_MultiFramePop`)

## Enforcement Evidence

TODO
