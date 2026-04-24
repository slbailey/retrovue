# INV-BOOTSTRAP-CONTENT-PARKED-001 (Source content cursors parked while gate closed)

## Behavioral Guarantee

While the bootstrap content gate is closed, no source-content sample or frame MUST be consumed from the audio or video lookahead buffers. The front-of-buffer source-content position on both streams MUST remain stationary for the entire gate-closed window.

## Authority Model

The tick-loop enforcement surface (today `PipelineManager`) owns the decision of whether a given tick pops real content or emits pad. While the bootstrap content gate is closed, the enforcement surface MUST route every tick through the pad/silence path and MUST NOT invoke the audio or video buffer pop primitives against real-content buffers.

## Boundary / Constraint

- `AudioLookaheadBuffer::TryPopSamples` MUST NOT be invoked against a real-content audio buffer while the gate is closed.
- `VideoLookaheadBuffer::TryPopFrame` MUST NOT be invoked against a real-content video buffer while the gate is closed.
- The source-PTS at the front of the audio buffer MUST be identical at gate-close and gate-open.
- The source-frame-index at the front of the video buffer MUST be identical at gate-close and gate-open.
- Decoder-internal state that advances as a side effect of fill-thread decode is outside the scope of this invariant; only output-side cursor state is governed.

## Violation

Any call to a real-content buffer's pop primitive while the gate is closed; a change in `audio_buffer.front().pts_us` between gate-close and gate-open; a change in `video_buffer.front().source_frame_index` between gate-close and gate-open.

## Derives From

`LAW-LIVENESS`, `LAW-SWITCHING`

## Required Tests

- `runtime/tests/contracts/bootstrap/BootstrapContentGateInvariantTests.cpp`

## Enforcement Evidence

TODO
