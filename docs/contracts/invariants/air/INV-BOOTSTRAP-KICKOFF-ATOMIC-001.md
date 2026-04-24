# INV-BOOTSTRAP-KICKOFF-ATOMIC-001 (Real A/V content starts on the same tick)

## Behavioral Guarantee

The first tick at which real audio content is consumed from the audio lookahead buffer MUST be the same tick at which the first real video frame is consumed from the video lookahead buffer. No intermediate tick MUST exist where one stream emits real content while the other emits pad or silence.

## Authority Model

The tick-loop enforcement surface (today `PipelineManager`) owns the decision to transition from pad emission to real-content emission. The kickoff decision MUST apply to both streams in the same tick iteration; it MUST NOT be evaluated per-stream independently.

## Boundary / Constraint

- The tick index at which audio first pops from the real-content audio buffer MUST equal the tick index at which video first pops from the real-content video buffer.
- The kickoff transition MUST be evaluated exactly once per session, at gate-open.
- After kickoff, both streams MUST continue consuming from their real-content buffers in lockstep for the remainder of the session.
- Per-stream independent fallbacks to pad (for example, cadence repeats, hold-last, or pad-bridge) remain governed by their own invariants and are outside this invariant's scope; this invariant governs the single bootstrap kickoff transition only.

## Violation

Any tick in which one stream emits real content while the other emits pad or silence during the pad-to-content transition window; a kickoff tick index that differs between the two streams; a per-stream kickoff decision that is not synchronised.

## Derives From

`LAW-SWITCHING`, `LAW-LIVENESS`

## Required Tests

- `runtime/tests/contracts/bootstrap/BootstrapContentGateInvariantTests.cpp`

## Enforcement Evidence

TODO
