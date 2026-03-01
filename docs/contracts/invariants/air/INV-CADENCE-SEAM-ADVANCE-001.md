# INV-CADENCE-SEAM-ADVANCE-001

**Owner:** AIR (PipelineManager frame-selection cascade)

## Behavioral Guarantee

On a segment seam tick where the incoming segment is eligible for swap and the video source gate selects the incoming segment buffer, frame selection MUST advance. The cadence repeat-vs-advance decision MUST NOT prevent reading from an eligible incoming source.

## Authority Model

PipelineManager frame-selection cascade is the sole enforcement point. The cadence decision is subordinate to the v_src selection when the incoming segment is eligible at a seam tick.

## Boundary / Constraint

When all of the following hold on a single tick:
- `take_segment == true` (segment seam tick)
- `v_src == segment_b_video_buffer_` (incoming segment buffer selected)
- `IsIncomingSegmentEligibleForSwap` returns true

Then:
- `should_advance_video` MUST be true
- `is_cadence_repeat` MUST be false
- Frame selection MUST call `TryPopFrame` on the incoming buffer

The cadence budget accumulator MUST NOT be reset by this override. Only the advance/repeat decision for the current tick is suppressed. The cadence state resumes normal operation after `RefreshFrameSelectionCadenceFromLiveSource` fires post-swap.

## Violation

A tick where `SEAM_TICK_EMISSION_AUDIT` logs `cadence_repeat=1` AND `SEAM_VSRC_GATE` logs `v_src=incoming eligible=true` AND `decision=R` constitutes a violation. The emitted frame originates from the outgoing segment when the incoming segment was eligible and its buffer was selected.

## Derives From

`INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001`

## Required Tests

- `pkg/air/tests/contracts/BlockPlan/CadenceSeamAdvanceContractTests.cpp`

## Enforcement Evidence

TODO
