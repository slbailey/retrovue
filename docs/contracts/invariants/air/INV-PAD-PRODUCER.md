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
TODO
