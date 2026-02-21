# INV-FPS-MAPPING — Source→Output Frame Authority

**Status:** Active  
**Owner:** TickProducer (mode detection), VideoLookaheadBuffer (cadence gate)  
**Enforcement:** Code (rational detection), regression tests (mode classification)  
**Related:** INV-FPS-RESAMPLE, ResampleMode (BlockPlanSessionTypes.hpp), INV-FPS-TICK-PTS (output PTS authority)

---

## Statement

For any segment where **input_fps ≠ output_fps**, the engine MUST select source frames using exactly one of: **OFF**, **DROP**, or **CADENCE**. Mode MUST be determined by rational comparison only. Misclassification is a contract violation and causes silent regressions (e.g. 60→30 as OFF → audio starvation).

**DROP duration invariant:** In DROP, returned output frame duration metadata MUST equal the output tick duration (1/output_fps), not the input frame duration.

**INV-TICK-AUTHORITY-001 (output duration and PTS):** For all modes (OFF, DROP, CADENCE), the returned video PTS delta MUST equal exactly one output tick, and the returned `video.metadata.duration` MUST equal exactly one output tick. Input frame duration must never leak into output duration or pacing.

---

## Required Mappings (Canonical)

| Input FPS | Output FPS | Required mode | Rational check |
|-----------|------------|---------------|----------------|
| 30/1      | 30/1       | **OFF**       | in_num×out_den == out_num×in_den |
| 60/1      | 30/1       | **DROP**      | (in_num×out_den) % (out_num×in_den) == 0, step = 2 |
| 120/1     | 30/1       | **DROP**      | (in_num×out_den) % (out_num×in_den) == 0, step = 4 |
| 24000/1001| 30/1       | **CADENCE**   | (in_num×out_den) % (out_num×in_den) ≠ 0 |

- **60→30 MUST be DROP.**  
- **120→30 MUST be DROP.**  
- **23.976→30 MUST be CADENCE.**  
- **30→30 MUST be OFF.**

No other mode is allowed for these cases. Any other classification is a violation.

---

## What This Invariant Protects

| Without INV-FPS-MAPPING | With INV-FPS-MAPPING |
|------------------------|----------------------|
| 60→30 can be treated as OFF (e.g. “input ≥ output ⇒ cadence off”) | Mode is defined by rational math only; 60→30 is DROP |
| Audio starvation; no test fails unless mode is asserted | Mode misclassification is a contract violation |
| Silent regression when logic is “optimized” or refactored | Explicit enum + required mappings make regression impossible to hide |

---

## Explicitly Required

| Requirement | Implementation |
|-------------|----------------|
| **Rational comparison only** | Mode detection uses `in_num`, `in_den`, `out_num`, `out_den`. No `double` FPS in the branch that sets mode. |
| **Explicit ResampleMode enum** | `enum class ResampleMode { OFF, DROP, CADENCE }` in BlockPlanSessionTypes.hpp. No boolean “cadence active” as the sole authority. |
| **DROP uses integer step** | `step = (in_num × out_den) / (out_num × in_den)`. Per output tick: advance source by step, emit first of group. No fractional accumulator for DROP. |
| **DROP must not reduce audio production** | All `step` input frames per output tick must contribute decoded audio. Emit one video frame (the first); harvest and enqueue audio from every decoded frame (emit + skip). Total audio per tick MUST match the input time advanced (e.g. step=2 at 60fps → 2/60 s of audio per 1/30 s tick). |
| **Audio must not be tied to video emission** | Audio is produced per decoded input frame. In DROP mode, “skip” decodes (advance_output_state=false) MUST still have their decoded audio collected and delivered; only video emission is gated to one frame per output tick. |
| **Exactly one push point for decoded audio** | TickProducer does not push to any audio buffer. It only returns FrameData. The fill thread (VideoLookaheadBuffer::FillLoop) pushes to the audio ring once per tick, from the single FrameData returned by TryGetFrame(). DROP aggregation appends skip-frame audio into that one FrameData so there is no duplicate or side-channel push. |
| **DROP output frame duration metadata** | Decoder sets video.metadata.duration per decoded input frame (e.g. 1/60 s). In DROP we emit one video frame per output tick spanning `step` input frames. The returned frame’s video.metadata.duration MUST be set to the output tick duration (1/output_fps) so consumers (e.g. ProgramOutput pad_frame_duration_us_, pacing) do not use single-input-frame duration and pop or pace too fast. |
| **CADENCE uses rational accumulator** | decode_budget (or equivalent) accumulates input/output ratio; decode when ≥ 1.0. Handles 23.976→30 etc. |
| **OFF only on exact rational equality** | `in_num × out_den == out_num × in_den`. OFF MUST NOT be the default for “unknown” or “no cadence flag”; it is only when the rationals are equal. |

---

## Explicitly Outlawed

| Pattern | Why forbidden |
|--------|----------------|
| **Floating-point epsilon FPS comparisons** | e.g. `std::abs(input_fps - output_fps) < 0.02` to decide “same rate”. Causes 60 vs 30 to be misclassified when combined with “input &gt; output ⇒ off”. |
| **Implicit “cadence disabled for integer ratios”** | e.g. “activate cadence only when input &lt; output” or “input &lt; output×0.98”. 60→30 then becomes OFF and breaks DROP. |
| **Boolean cadence flag as sole authority** | A single “cadence_active” with no ResampleMode hides DROP vs CADENCE and invites OFF-by-default. |
| **Defaulting to OFF unless explicitly matched** | OFF must be chosen only when rational equality holds. Defaulting to OFF for “no decoder”, “unknown FPS”, or “ratio &gt; 1” violates the mapping table. |

---

## Detection Logic (Normative)

Given input rational `in_num/in_den` and output rational `out_num/out_den` (128-bit intermediates to avoid overflow):

```
if (in_num * out_den == out_num * in_den)
    → ResampleMode::OFF
else if ((in_num * out_den) % (out_num * in_den) == 0)
    → ResampleMode::DROP, step = (in_num * out_den) / (out_num * in_den)
else
    → ResampleMode::CADENCE
```

No floats. No epsilon. No “input &lt; output” or “ratio &gt; 1” branch to force OFF.

---

## Enforcement

- **Code:** TickProducer::UpdateResampleMode() implements the above. VideoLookaheadBuffer uses GetResampleMode() / GetDropStep(); cadence_active = (mode == CADENCE). DROP path: TryGetFrame() accumulates audio from all `step` decodes into the single returned FrameData so audio production is not reduced.
- **Logging:** FPS_CADENCE log must show `mode=OFF` | `mode=DROP ratio=N` | `mode=CADENCE ratio=R`.
- **Tests:** MediaTimeContractTests: ResampleMode_60to30_DROP_step2, ResampleMode_30to30_OFF, ResampleMode_120to30_DROP_step4, ResampleMode_23976to30_CADENCE (rational formula); TickProducer_60to30_ReportsDROP_WhenDecoderOpens (baseline when decoder does not open). E2E with 60fps asset: run 5–10s of ticks, assert mode=DROP step=2 and no audio underflow (or audio depth &gt; 200ms after bootstrap).

---

## Relationship to INV-FPS-RESAMPLE

- **INV-FPS-RESAMPLE** governs *timing*: tick grid and block CT from rational FPS (no rounded intervals, no int-ms accumulation).
- **INV-FPS-MAPPING** governs *frame selection policy*: which source frames are emitted per output tick (OFF / DROP / CADENCE).

Both use the same rational FPS representation. INV-FPS-MAPPING ensures the policy layer cannot silently misclassify and break INV-FPS-RESAMPLE’s timing (e.g. by treating 60→30 as OFF and under-decoding).
