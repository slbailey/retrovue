# INV-BOOTSTRAP-CONTENT-ORIGIN-001 (Buffer fronts source-aligned at gate-open)

## Behavioral Guarantee

At the instant the bootstrap content gate opens, the source-content moment represented by the front of the audio lookahead buffer MUST equal the source-content moment represented by the front of the video lookahead buffer, within one output-frame duration.

## Authority Model

The bootstrap content gate is owned by the tick-loop enforcement surface (today `PipelineManager`). The gate-open predicate MUST include a source-time-alignment check against both buffer fronts. The check MUST be explicit, not implicit — the gate MUST NOT open on depth predicates alone.

## Boundary / Constraint

- At gate-open, `source_time(audio_buffer.front())` MUST equal `source_time(video_buffer.front())` within one output-frame duration.
- The gate-open predicate MUST read both buffer fronts and MUST compute the source-time delta before declaring the gate open.
- If the source-time delta exceeds one output-frame duration, the gate MUST NOT open; it MUST either wait for alignment or declare a bootstrap failure.
- The source-time field on each buffer is the decoder-assigned source PTS of the sample or frame at the buffer's consumption front (accounting for partial consumption on the audio side).

## Violation

The gate opens while the buffer-front source-time delta exceeds one output-frame duration; the gate-open predicate does not read both buffer fronts; a gate-open decision made on depth predicates alone without source-time alignment.

## Derives From

`LAW-CLOCK`, `LAW-LIVENESS`

## Required Tests

- `runtime/tests/contracts/bootstrap/BootstrapContentGateInvariantTests.cpp`

## Enforcement Evidence

TODO
