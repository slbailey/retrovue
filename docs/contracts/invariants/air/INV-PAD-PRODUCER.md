# INV-PAD-PRODUCER (Content-before-pad gate)

**Owner:** AIR

## Behavioral Guarantee
Pad is a first-class TAKE-selectable source. Produces black video and silent audio in session program format when selected. No pad until first real frame committed (content-before-pad gate).

## Authority Model
PipelineManager owns source selection. PadProducer is unconditionally available; session format and content-before-pad gate define when it may be selected.

## Boundary / Constraint
Pad MUST be available and format-conforming. Pad MUST NOT be selected until at least one real frame has been committed. Selection/deselection within single tick.

## Violation
Selecting pad before first real frame committed; pad output not conforming to session format.

## Required Tests
- `pkg/air/tests/contracts/BlockPlan/PadProducerContractTests.cpp`
- `pkg/air/tests/contracts/BlockPlan/PipelineManagerPadFenceAudioContractTests.cpp`

## Enforcement Evidence

- `PadProducer` (`PadProducer.hpp`) constructed at session start and lives for the session lifetime — unconditionally available as a TAKE-selectable source.
- **Content-before-pad gate:** `PipelineManager` tracks whether the first real content frame has been committed; PAD selection is blocked until this gate opens.
- **Format conformance:** `PadProducer::VideoFrame()` and `PadProducer::AudioFrame()` produce black video and silent audio matching the session program format (resolution, frame rate, sample rate).
- Contract tests: `PadProducerContractTests.cpp` validates format conformance, session-lifetime availability, and content-before-pad gate. `PipelineManagerPadFenceAudioContractTests.cpp` validates PAD audio fence behavior at segment boundaries.
