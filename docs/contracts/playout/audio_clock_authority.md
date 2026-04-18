## Purpose

Define the timing authority contract for playout audio/video timeline emission.
The prohibited failure mode is a dual-clock system where video follows
`OutputClock` while audio advances from independent sample progression.

Audio emission MUST be strictly derived from `OutputClock` time progression.
At any time `t`, cumulative emitted audio duration MUST equal cumulative
`OutputClock` elapsed duration, subject only to the tolerance rules.
The system MUST treat `OutputClock` as the sole timing authority for both audio
and video emission.

## Invariant definition

For every output tick `T`, the system MUST satisfy:

audio_samples_emitted(T) = round((T_elapsed_seconds) * sample_rate)

Where:
- `T_elapsed_seconds` MUST be derived from `OutputClock`.
- `sample_rate` MUST be `48000 Hz` unless an explicitly configured rate is in
  effect.
- The formula governs cumulative emitted audio samples over elapsed
  `OutputClock` time, not only local per-tick behavior.
- Decoder cadence, decoder frame boundaries, FIFO fill rate, encoder packet size,
  and mux behavior MUST be non-authoritative for emission timing.

## Required system behavior

- Audio emission MUST NOT be scheduled from decoder frame boundaries.
- Audio emission MUST NOT be scheduled from fixed encoder packet sizes.
- Audio data MUST be buffered in a FIFO prior to clock-driven pull.
- Audio pull size per tick MUST be determined by `OutputClock` demand.
- Encoder packetization MUST be downstream formatting and MUST NOT influence
  timing authority.
- Live video PTS MUST remain the nominal `OutputClock`/tick-derived timeline;
  it MUST NOT be corrected toward audio PTS as a recovery mechanism.
- `video_time_emitted_ms` MUST mean cumulative output timeline emitted under
  `OutputClock`; it MUST NOT mean source PTS or decoder-native media time.
- `audio_time_emitted_ms` MUST mean cumulative emitted audio time after
  clock-authoritative pull; it MUST NOT mean raw decoded samples received.

## Lifecycle invariants

- Startup preroll MUST NOT establish an independent audio timeline.
- Priming, bootstrap, preroll, seam preparation, and segment prefill MUST only
  prepare buffered media and MUST NOT redefine timing authority.
- Startup priming MUST be packetization-shape independent at the contract
  outcome level: decoder-drain burst shape MUST NOT by itself determine whether
  a channel enters deterministic bootstrap positive-lead clamp.
- On first output tick after startup, emitted audio time and emitted video time
  MUST both anchor to the same `OutputClock` epoch.
- Segment transitions and block transitions MUST preserve cumulative audio/video
  timeline continuity.
- No transition step may reset, fork, or re-anchor audio time independently from
  `OutputClock`.

## Prohibited behavior

The following behaviors are forbidden:

- Driving emission by `nb_samples == 1024` loops.
- Driving emission by decoder push cadence.
- Using audio FIFO depth as timing authority.
- Using FIFO depth, high-water marks, low-water marks, clamp logic, or recovery
  heuristics as the effective timing governor.
- Re-anchoring audio time at startup completion, segment prefill completion, or
  seam activation.
- Allowing AAC frame size, encoder frame size, or mux packet cadence to
  determine emission timing.
- Deriving audio clock from decoded sample arrival rate.
- Mutating live video PTS as a function of audio PTS (bounded convergence,
  clamp-forward, post-hoc recentering).
- Any logic path that allows `audio_time` to diverge from `video_time` when both
  are defined from `OutputClock`.

## Derived timing model

At `29.97 fps`, each output tick requires approximately `1601.6` samples.

- The implementation MAY realize tick demand through fractional accumulation,
  alternating pull sizes, or equivalent methods.
- The contract defines the required timing outcome, not the implementation
  technique.
- The implementation MUST support variable per-tick sample pulls, including
  patterns such as alternating `1601` and `1602` samples.
- The long-run emitted sample total MUST converge to the
  `OutputClock`-derived expectation without unbounded error growth.

Total emitted audio over elapsed time MUST equal the sample count implied by
`OutputClock`.

## Tolerance rules

- Instantaneous A/V delta MUST remain within `±20 ms` as the soft target.
- Absolute A/V delta of `±50 ms` is a hard violation and MUST trigger a
  diagnostic alert.
- The soft target and hard violation thresholds apply to instantaneous measured
  delta.
- The system MUST NOT exhibit monotonic drift accumulation during steady-state
  output.
- A system that remains within tolerance only by repeated clamp/recovery cycles
  is non-compliant if cumulative drift tendency remains present.
- Buffer-control actions MAY protect continuity but MUST NOT serve as the
  primary mechanism of clock reconciliation.

## Observability requirements

The pipeline MUST expose or log the following required fields:

- `audio_time_emitted_ms`
- `video_time_emitted_ms`
- `av_delta_ms`
- `audio_fifo_depth_ms`
- `output_clock_elapsed_ms`
- `expected_audio_samples`
- `actual_audio_samples_emitted`
- `audio_sample_error`
- `clock_authority_mode`

Field semantics are mandatory:

- `video_time_emitted_ms` is cumulative emitted output timeline under
  `OutputClock`, not source PTS and not decoder-native media time.
- `audio_time_emitted_ms` is cumulative emitted audio time after
  clock-authoritative pull, not raw decoded sample arrival.

Observability output MUST support detection of:

- Cumulative drift.
- Clock-authority mismatch between audio and video paths.
- Re-anchoring events.
- Clamp-driven pseudo-stability.
- Packetization-driven timing behavior.

## Enforcement points

This invariant MUST hold across the following contractual boundaries:

- Tick-time demand calculation boundary.
- Audio FIFO pull accounting boundary.
- Encoder submission boundary.
- Mux submission boundary.
- Seam and transition handoff boundaries.

## Test requirements

The following tests are required to enforce this contract:

- Long-run steady-state sync test (`10+` minutes) proving no monotonic drift
  accumulation.
- `24 fps` to `29.97 fps` cadence conversion test proving
  `OutputClock`-authoritative audio timing.
- Startup/preroll anchor test proving first emitted audio/video timelines share
  one `OutputClock` epoch.
- Segment transition continuity test proving no audio re-anchor or cumulative
  timeline discontinuity at segment boundaries.
- Block transition continuity test proving no audio re-anchor or cumulative
  timeline discontinuity at block seams.
- Buffer pressure test proving sync remains compliant without clamp-driven timing
  authority.
- Encoder packetization independence test proving different packetization
  boundaries do not alter emitted timeline.

## Non-goals

This contract does not define:

- Audio quality characteristics.
- Resampling algorithm details.

This contract defines timing authority only.
