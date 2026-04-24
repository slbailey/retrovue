# INV-BOOTSTRAP-PTS-CONTINUOUS-001 (Output PTS continuous across kickoff)

## Behavioral Guarantee

Output PTS on the video stream and the audio stream MUST be monotonically continuous across the pad-to-content kickoff transition. The output PTS delta between the last pad tick and the first real-content tick MUST equal exactly one output-frame duration on both streams.

## Authority Model

The tick-loop enforcement surface (today `PipelineManager`) owns output PTS assignment for both streams. Output PTS MUST be computed from the tick counter using the existing PTS-origin decoupling primitives (`pts_origin_frame_index`, `pts_origin_audio_samples`); it MUST NOT be reset, snapped, or recomputed at the kickoff transition.

## Boundary / Constraint

- The output PTS of the first real-content video frame MUST equal the output PTS of the last pad video frame plus one output-frame duration.
- The output PTS of the first real-content audio frame MUST equal the output PTS of the last silence audio frame plus the tick's audio sample count converted to 90 kHz units.
- The PTS-origin fields MUST NOT be mutated at the kickoff transition; any absorption of bootstrap delay MUST occur before session tick 0 is emitted.
- Downstream observers MUST NOT be required to detect or skip a discontinuity at the kickoff transition.

## Violation

A PTS delta at the kickoff transition that is not exactly one output-frame duration; a PTS-origin mutation at the kickoff transition; a non-monotonic PTS on either stream across the transition; a required downstream discontinuity skip.

## Derives From

`LAW-CLOCK`, `LAW-LIVENESS`

## Required Tests

- `runtime/tests/contracts/bootstrap/BootstrapContentGateInvariantTests.cpp`

## Enforcement Evidence

TODO
