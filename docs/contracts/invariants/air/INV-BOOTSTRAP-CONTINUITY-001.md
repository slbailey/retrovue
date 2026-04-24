# INV-BOOTSTRAP-CONTINUITY-001 (Bootstrap emits continuous pad + silence)

## Behavioral Guarantee

While the bootstrap content gate is closed, every tick MUST emit exactly one pad video frame and one silence audio frame to the output sink at tick cadence. The output transport MUST observe no emission gap between session start and the first real-content tick.

## Authority Model

The tick-loop enforcement surface (today `PipelineManager`) owns emission timing. The bootstrap content gate is a gate-state flag owned by the same surface; it is set open once the content-origin preconditions are met. PadProducer supplies the pad video frame and silence audio template consumed while the gate is closed.

## Boundary / Constraint

- While the bootstrap content gate is closed, each tick MUST emit one pad video frame via the existing per-tick encode path.
- While the bootstrap content gate is closed, each tick MUST emit one silence audio frame of the tick's declared sample count via the existing per-tick audio encode path.
- The tick clock MUST advance one tick per emission, identical to steady-state pacing.
- The output sink MUST receive bytes at the session's declared bitrate across the entire gate-closed window.

## Violation

A tick during the gate-closed window that does not emit both a video frame and an audio frame to the output sink; an emission gap observed on the output transport between session start and the first real-content tick; pad/silence emitted off tick cadence.

## Derives From

`LAW-LIVENESS`

## Required Tests

- `runtime/tests/contracts/bootstrap/BootstrapContentGateInvariantTests.cpp`

## Enforcement Evidence

TODO
