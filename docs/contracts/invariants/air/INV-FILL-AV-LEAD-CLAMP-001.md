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

## Boundary / Constraint

For each decode cycle where `pending_audio_frames` is non-empty and `audio_buffer` is non-null, at the Push site:

1. If `audio_depth_ms > audio_high_water_ms`, the implementation **MUST** set suppression to **`kAvLeadClamp`** and **MUST NOT** `Push` those samples in that cycle.
2. Else if `fill_av_delta_ms > fill_max_positive_av_lead_ms`, the implementation **MUST** set suppression to **`kAvLeadClamp`** and **MUST NOT** `Push`.
3. Otherwise the implementation **MUST** allow `Push` subject to other invariants (capacity, generation).

## Violation

- Audio `Push` when `audio_depth_ms > audio_high_water_ms` while this check is active.
- Audio `Push` when `fill_av_delta_ms > fill_max_positive_av_lead_ms` while this check is active.
- Suppression without **`kAvLeadClamp`** classification for these two conditions.
- Implementing the same suppression in mux or encoder instead of fill domain.

## Derives From

- `LAW-LIVENESS`
- `LAW-RUNTIME-AUTHORITY`

## Required Tests

- `runtime/tests/contracts/BlockPlan/VideoLookaheadBufferTests.cpp` (or dedicated fill clamp suite) — **to be added**: high-water, positive delta, within tolerance, enum, multi-cycle bounded lead.

## Enforcement Evidence

TODO
