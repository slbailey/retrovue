# INV-LOUDNESS-NORMALIZED-001

## Behavioral Guarantee
All playout audio MUST be loudness-normalized toward -24 LUFS integrated (ATSC A/85). Core measures; AIR applies.

## Authority Model
Core owns loudness measurement truth. Core computes `gain_db` per asset and propagates it on every playout segment. AIR owns gain application: a constant linear scalar applied to every S16 sample in the segment.

## Boundary / Constraint

1. If a playout segment carries `gain_db != 0.0`, AIR MUST apply that `gain_db` as a constant linear scalar (`10^(gain_db/20)`) to every S16 sample in that segment.
2. Sample count and timing MUST remain unchanged by gain application.
3. Applied gain MUST clamp each sample to the int16 range (`[-32768, +32767]`). No wraparound.
4. Segments with `gain_db == 0.0` (or absent) MUST pass through at unity — no samples are modified.
5. When Core builds a playout segment for an asset that has no stored loudness measurement, Core MUST set `gain_db = 0.0` AND enqueue a background loudness measurement job for that asset.
6. When the background measurement completes, the result (`integrated_lufs`, `gain_db`) MUST be persisted to the asset's probed metadata. All subsequent playout segments for that asset MUST carry the computed `gain_db`.
7. `gain_db` MUST be computed as `target_lufs - integrated_lufs` where `target_lufs = -24.0`.
8. Core owns measurement truth. AIR owns gain application. Neither invents loudness values.

## Violation
- AIR emits audio samples for a segment with `gain_db != 0.0` without applying the gain.
- Gain application alters sample count, frame timing, or PTS.
- An unmeasured asset is played without a background measurement job being enqueued.
- A sample after gain exceeds `[-32768, +32767]` (wraparound).

## Derives From
`LAW-LIVENESS`

## Required Tests
- `pkg/air/tests/contracts/BlockPlan/SharedInvLoudnessNormalizedContractTests.cpp` (`GainFormula_TargetMinusIntegrated`) — Rule 7: gain_db = target_lufs - integrated_lufs, +6 dB ≈ 2.0× linear
- `pkg/air/tests/contracts/BlockPlan/SharedInvLoudnessNormalizedContractTests.cpp` (`ZeroGainPassthrough_SamplesUnchanged`) — Rule 4: gain_db=0 passes through unchanged
- `pkg/air/tests/contracts/BlockPlan/SharedInvLoudnessNormalizedContractTests.cpp` (`ClampPreventsWrap`) — Rule 3: large gain clamped to int16 range, no wraparound
- `pkg/air/tests/contracts/BlockPlan/SharedInvLoudnessNormalizedContractTests.cpp` (`GainDoesNotAlterSampleCountOrPts`) — Rule 2: nb_samples and pts_us unchanged by gain
- `pkg/air/tests/contracts/BlockPlan/LoudnessGainContractTests.cpp` — arithmetic coverage for gain conversion and application
- `pkg/core/tests/contracts/test_inv_loudness_normalized_001.py` — Core-side: measurement truth, gain_db propagation, background measurement jobs

## Enforcement Evidence
TODO
