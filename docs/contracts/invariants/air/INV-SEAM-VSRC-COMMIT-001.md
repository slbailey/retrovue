# INV-SEAM-VSRC-COMMIT-001

## Classification
CONTRACT — AIR

## Owner
AIR (PipelineManager)

## One-Line Definition
When SEAM_VSRC_GATE selects the incoming segment buffer and a frame is
emitted from it, POST-TAKE MUST execute the swap.

## Context

Frame selection and swap execution are separate phases of the tick loop:

1. **SEAM_VSRC_GATE** (early tick): Evaluates incoming segment eligibility,
   selects which buffer (`v_src`) to read from.
2. **Frame selection cascade** (mid tick): Pops/reads a frame from `v_src`,
   encodes and emits it.
3. **POST-TAKE** (late tick): Re-evaluates eligibility and decides whether
   to commit the segment swap.

These phases sample `DepthFrames()` independently. If the FIVS state changes
between phases (e.g., due to TryPopFrame eviction — see
INV-FIVS-TRYPOP-EVICTION-SAFE-001), the re-evaluation can diverge from the
gate commitment.

## Invariant

```
forall T where take_segment(T) = true:
  if SEAM_VSRC_GATE selects v_src = segment_b
  AND frame_selection_cascade pops frame F from segment_b
  AND F.segment_origin_id = current_segment_index + 1
  then POST-TAKE MUST execute PerformSegmentSwap
```

Once a frame from the incoming segment has been emitted, deferring the swap
creates an authority divergence: `origin(T) != active(T)`.

## Enforcement

A `force_swap_for_vsrc_commit` flag is set when:
1. `v_src == segment_b_video_buffer_` (SEAM_VSRC_GATE selected incoming), AND
2. The frame selection cascade produced `decision == kContentA`, AND
3. `frame_origin_segment_id == current_segment_index_ + 1` (frame actually from B)

This flag bypasses the `IsIncomingSegmentEligibleForSwap` re-check in
POST-TAKE, analogous to `force_swap_for_pad_seam` and
`force_swap_for_content_seam`.

## Derives From

- INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001 (frame origin must match active authority)

## Evidence

- Log: `hbo-air.log.prev` line 677–680:
  - SEAM_VSRC_GATE: `eligible=true v_src=incoming` (tick 1077)
  - SEGMENT_SWAP_DEFERRED: `reason=not_ready incoming_video_frames=1` (tick 1077)
  - VIOLATED: `active_segment_id=0 frame_origin_segment_id=1` (tick 1077)
