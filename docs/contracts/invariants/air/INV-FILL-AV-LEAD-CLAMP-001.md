# INV-FILL-AV-LEAD-CLAMP-001

## Behavioral Guarantee

At the **atomic audio Push site** in **`VideoLookaheadBuffer::FillLoop`** (immediately before `AudioLookaheadBuffer::Push` for decoded audio associated with the current video decode cycle), decoded audio **MUST NOT** be pushed when either **high-water** or **positive A/V lead** exceeds the bounds below. Enforcement **MUST** occur in the **fill / decode domain** only, **before** `Push`. Suppression **MUST** be classified as **`AudioSuppressionReason::kAvLeadClamp`** (same enumeration value for both triggers; log line **MAY** distinguish sub-reason).

**Scope note:** The defect class that motivated this invariant was **bootstrap** skew; the **same** pre-Push check **MAY** apply in **steady** fill as well when the implementation evaluates it on every cycle — **one** tolerance policy applies wherever the check runs.

## Authority Model

**`VideoLookaheadBuffer` fill thread** owns this clamp. **`OutputClock`**, **mux**, and **encoder** MUST NOT implement this logic.

## Contract parameters

| Parameter | Meaning | Source |
|-----------|---------|--------|
| `fill_max_positive_av_lead_ms` | Maximum allowed **positive** `(audio_depth_ms - video_time_ms_fill)` before suppressing Push | **SHALL equal** `PipelineManagerOptions.av_phase_tolerance_ms` (**INV-BOOTSTRAP-AV-PHASE-001**). Default **120** ms with the same justification as **`av_phase_tolerance_ms`**. |
| `audio_high_water_ms` | Audio depth above which Push is suppressed | **`AudioLookaheadBuffer::HighWaterMs()`** at push time — **not** redefined here. |

**Negative and zero A/V lead:** This invariant **does not** require suppressing audio when video leads audio (`gate_av_delta` negative). Low-water / liveness behavior remains **`INV-AUDIO-LIVENESS-001`** (or successor). **Positive** lead cap is **`fill_max_positive_av_lead_ms`**.

## Definitions

- **`audio_depth_ms`**: `AudioLookaheadBuffer::DepthMs()` **immediately before** the atomic Push block for the decoded video frame cycle.
- **`video_time_ms_fill`**: Let `(N,D) = output_fps_` (numerator/denominator). Let `L` = consumer lookahead from `VideoLookaheadBuffer` (`ComputeLookaheadLocked` semantics), or **`kLookaheadConsumerUnknown`**. Let `S = VideoLookaheadBuffer` indexed store size (`frame_store_.Size()`). Let **`B = (L == kLookaheadConsumerUnknown) ? max(0,S) : max(0,L)`**. Then **`video_time_ms_fill = (B * 1000 * D) / N`** using **the same integer arithmetic** as the implementation (contractually: the value returned by the implementation’s `estimate_video_ms` helper).

- **`fill_av_delta_ms`**: `audio_depth_ms - video_time_ms_fill`.

### Bootstrap handoff compatibility

This invariant is the steady-state clamp authority. Therefore bootstrap success
(`INV-BOOTSTRAP-AV-PHASE-001`) MUST guarantee that the first steady-state fill
evaluation is already within this invariant's clamp window.

Equivalent required outcome:

`fill_av_delta_ms_first <= fill_max_positive_av_lead_ms`

No deterministic immediate post-bootstrap clamp is allowed.
`INV-BOOTSTRAP-AV-PHASE-001` enforces this using atomic bootstrap→steady
handoff semantics plus handoff guard-band.

Startup primed-audio burst policy is upstream-owned by `INV-BOOTSTRAP-AV-PHASE-001`.
This invariant assumes startup priming does not inject an asset-shape-dependent
pre-consumer audio burst that deterministically trips the positive-lead clamp.

## Boundary / Constraint

For each decode cycle where `pending_audio_frames` is non-empty and `audio_buffer` is non-null, at the Push site:

1. If `audio_depth_ms > audio_high_water_ms`, the implementation **MUST** set suppression to **`kAvLeadClamp`** and **MUST NOT** `Push` those samples in that cycle.
2. Else if `fill_av_delta_ms > fill_max_positive_av_lead_ms`, the implementation **MUST** set suppression to **`kAvLeadClamp`** and **MUST NOT** `Push`.
3. Otherwise, admission of `pending_audio_frames` MUST still satisfy one-cycle positive-lead safety:
   Let `pending_audio_ms_effective` be the effective audio contribution of the decoded batch that would be accepted in this cycle, and let:
   `projected_fill_av_delta_ms = (audio_depth_ms + pending_audio_ms_effective) - video_time_ms_fill`.
   A cycle MUST NOT admit audio such that `projected_fill_av_delta_ms > fill_max_positive_av_lead_ms`.
4. Otherwise, admission of `pending_audio_frames` MUST still satisfy one-cycle high-water safety:
   `projected_audio_depth_ms = audio_depth_ms + pending_audio_ms_effective`.
   A cycle MUST NOT admit audio such that `projected_audio_depth_ms > audio_high_water_ms`.
5. If admitting the entire decoded batch would violate rule (3) or (4), the cycle MUST enforce `kAvLeadClamp` outcome semantics for the violating portion (suppress, defer, or equivalently prevent violating admission in fill domain). This contract constrains outcome, not batching mechanics.

## Violation

- Audio `Push` when `audio_depth_ms > audio_high_water_ms` while this check is active.
- Audio `Push` when `fill_av_delta_ms > fill_max_positive_av_lead_ms` while this check is active.
- Audio admission from an in-range pre-push state that deterministically crosses above `fill_max_positive_av_lead_ms` in the same fill cycle before clamp can act on the next cycle (one-cycle overshoot loophole).
- Audio admission from a below-high-water pre-push state that deterministically crosses above `audio_high_water_ms` in the same fill cycle before clamp can act on the next cycle (one-cycle high-water overshoot loophole).
- Suppression without **`kAvLeadClamp`** classification for these two conditions.
- Implementing the same suppression in mux or encoder instead of fill domain.
- Contract bridge failure where a bootstrap-pass state deterministically causes first steady-state `kAvLeadClamp`.

## Derives From

- `LAW-LIVENESS`
- `LAW-RUNTIME-AUTHORITY`

## Required Tests

- `runtime/tests/contracts/BlockPlan/FillAvLeadClampContractTests.cpp` (`FillLoop_ClampSuppressesAudio_WhenAudioMsExceedsHighWater`)
- `runtime/tests/contracts/BlockPlan/FillAvLeadClampContractTests.cpp` (`FillLoop_ClampSuppressesAudio_WhenAvDeltaExceedsMaxAvLead`)
- `runtime/tests/contracts/BlockPlan/FillAvLeadClampContractTests.cpp` (`FillLoop_NoClamp_WhenWithinTolerance`)
- `runtime/tests/contracts/BlockPlan/FillAvLeadClampContractTests.cpp` (`PrePushOnlyClampPolicy_CanPermitOneCycleOvershoot_OnHboBurstShape`)
- `runtime/tests/contracts/BlockPlan/FillAvLeadClampContractTests.cpp` (`ProjectedAdmissionGuard_RejectsHboBurstButAllowsCheersLikeBatch`)
- `runtime/tests/contracts/BlockPlan/FillAvLeadClampContractTests.cpp` (`PrePushHighWaterOnlyPolicy_CanPermitOneCycleOvershoot_OnHboBurstShape`)
- `runtime/tests/contracts/BlockPlan/FillAvLeadClampContractTests.cpp` (`ProjectedHighWaterGuard_RejectsHboBurstButAllowsCheersLikeBatch`)
- `runtime/tests/contracts/BlockPlan/BootstrapAvPhaseContractTests.cpp` (`BootstrapPassState_MustBeFirstSteadyFillSafe`)
- `runtime/tests/contracts/BlockPlan/BootstrapAvPhaseContractTests.cpp` (`BootstrapPassState_MustNotDeterministicallyTripClampNextEvaluation`)

## Enforcement Evidence

TODO
