# Invariant Audit: House Format and Tick Cadence

**Classification:** Audit (no code changes)  
**Date:** 2026-02-23  
**Scope:** Architectural consistency of house format, output_fps, tick cadence, master clock, and execution_model

---

## A) Is tick cadence defined as being driven by house/output format?

**Yes.** Tick cadence (when ticks occur) is defined as driven by the session’s rational output FPS (house/output format), not by input or source FPS.

| Reference | Location | Quote / fact |
|-----------|----------|--------------|
| INV-FPS-RESAMPLE | `pkg/air/docs/contracts/semantics/INV-FPS-RESAMPLE.md` | "Output session time (tick grid / block CT grid). Authority: Rational FPS (fps_num, fps_den). Output tick time: tick_time_us(n) = floor(n * 1_000_000 * fps_den / fps_num)." |
| INV-TICK-DEADLINE-DISCIPLINE-001 | `pkg/air/docs/contracts/INV-TICK-DEADLINE-DISCIPLINE-001.md` | "spt(N) = session_epoch_utc + N * fps_den / fps_num" (rational FPS timebase). |
| INV-TICK-MONOTONIC-UTC-ANCHOR-001 | `pkg/air/docs/contracts/INV-TICK-MONOTONIC-UTC-ANCHOR-001.md` | "deadline_mono_ns(N) = session_epoch_mono_ns + round_rational(N * 1e9 * fps_den / fps_num)". |
| TIMING-AUTHORITY-OVERVIEW | `pkg/air/docs/contracts/semantics/TIMING-AUTHORITY-OVERVIEW.md` | "Output session time is defined **exclusively** by the rational tick grid." |
| INVARIANTS-INDEX | `pkg/air/docs/contracts/INVARIANTS-INDEX.md` L34 | Channel Clock domain: "Tick cadence, guaranteed output, monotonic enforcement". |
| INV-BLOCK-WALLCLOCK-FENCE-001 | `pkg/air/docs/contracts/INV-BLOCK-WALLCLOCK-FENCE-001.md` | Fence tick from "Rational output FPS" (fps_num/fps_den); "No floating-point FPS in fence computation". |
| INV-SEAM-SEG-004 | `pkg/air/docs/contracts/INVARIANTS-INDEX.md` L158 | Segment seam tick: `segment_seam_frame = block_activation_frame + ceil(boundary.end_ct_ms × fps_num / (fps_den × 1000))` — same rational arithmetic as block fence (session output FPS). |

**Code:** TickProducer is constructed with `RationalFps output_fps` and stores `output_fps_` as authoritative; CtMs(k) and TickTimeUs use it. PipelineManager uses `ctx_->fps` (session rational FPS) for fence and seam formulas (`PipelineManager.cpp` 875–884, 3014–3021).

---

## B) Is there any invariant stating that output timing must remain fixed for a session?

**Yes.** Session output timing (frame rate / tick grid) is fixed for the session lifetime.

| Reference | Location | Quote / fact |
|-----------|----------|--------------|
| PlayoutInstanceAndProgramFormatContract | `pkg/air/docs/contracts/semantics/PlayoutInstanceAndProgramFormatContract.md` | "ProgramFormat … Fixed for the lifetime of a PlayoutInstance"; "ProgramFormat does not change during a PlayoutInstance." |
| INVARIANTS-INDEX | `pkg/air/docs/contracts/INVARIANTS-INDEX.md` | ProgramFormat fixed for session (see Layer 0 / PlayoutInstance). |
| PlayoutInvariants-BroadcastGradeGuarantees | `pkg/air/docs/contracts/laws/PlayoutInvariants-BroadcastGradeGuarantees.md` L62–64 | "The channel's program format … is established at session start … and does not change for the lifetime of the session." |
| INV-PAD-PRODUCER | `pkg/air/docs/contracts/INV-PAD-PRODUCER.md` L63 | "The session's immutable output format: … frame rate (rational fps_num/fps_den) … Fixed at session creation." |
| INV-TICK-MONOTONIC-UTC-ANCHOR-001 | `pkg/air/docs/contracts/INV-TICK-MONOTONIC-UTC-ANCHOR-001.md` R1 | "A session MUST record both UTC epoch and monotonic epoch once, at session start, and MUST NOT rewrite them during the session." |
| INV-BLOCK-WALLCLOCK-FENCE-001 | `pkg/air/docs/contracts/INV-BLOCK-WALLCLOCK-FENCE-001.md` | Fence tick "immutable after computation"; no mid-session change of output FPS for fence math. |

There is no separate one-line "output timing must remain fixed" INV with that exact wording; the fixity is implied by ProgramFormat immutability, epoch immutability, and rational FPS as single authority for the tick grid.

---

## C) Is segment swap allowed to alter execution cadence?

**No.** Execution cadence (when output ticks fire) must not be altered by segment swap. Segment swap may only change **frame-selection policy** (which frame to emit per tick), not tick timing.

| Reference | Location | Quote / fact |
|-----------|----------|--------------|
| INV-TICK-DEADLINE-DISCIPLINE-001 | `pkg/air/docs/contracts/INV-TICK-DEADLINE-DISCIPLINE-001.md` R5 | "A slow/long/blocked tick MUST NOT shift the scheduled deadlines of future ticks. Tick N+1 remains anchored to spt(N+1) derived from the session epoch." |
| INV-FPS-RESAMPLE | `pkg/air/docs/contracts/semantics/INV-FPS-RESAMPLE.md` | Output tick grid from rational (fps_num, fps_den); no recalculation from source. |
| INV-FPS-MAPPING | `pkg/air/docs/contracts/semantics/INV-FPS-MAPPING.md` | Governs *frame selection policy* (OFF/DROP/CADENCE) per output tick; "INV-FPS-RESAMPLE governs *timing*". |
| INV-SEAM-001 | `pkg/air/docs/contracts/INVARIANTS-INDEX.md` L142 | "Channel clock MUST NOT observe, wait for, or be influenced by any decoder lifecycle event." |

**Code:** `RefreshFrameSelectionCadenceFromLiveSource` / `InitFrameSelectionCadenceForLiveBlock` refresh `frame_selection_cadence_enabled_`, `frame_selection_cadence_budget_den_`, `frame_selection_cadence_increment_` from **input_fps vs output_fps**. Those control **repeat-vs-advance** (emit new frame vs repeat last) within the **same** output tick grid; they do **not** change spt(N), session_frame_index advancement, or tick deadlines. So segment swap does **not** alter execution cadence (tick timing); it only refreshes the cadence **policy** for which frame is shown on each tick.

---

## D) Is input_fps allowed to affect output tick timing, or must it be mapped?

**input_fps must not affect output tick timing.** It may only affect **which** source frame is chosen per output tick (mapping); output tick timing is from output FPS only.

| Reference | Location | Quote / fact |
|-----------|----------|--------------|
| INV-FPS-MAPPING | `pkg/air/docs/contracts/semantics/INV-FPS-MAPPING.md` | "Input frame duration must never leak into output duration or pacing." INV-TICK-AUTHORITY-001: "Returned video PTS delta and video.metadata.duration MUST equal exactly one output tick." |
| INV-FPS-TICK-PTS | `pkg/air/docs/contracts/semantics/INV-FPS-TICK-PTS.md` | "Output video PTS must advance by exactly one output tick per returned frame"; "PTS is owned by the tick grid, not by the decoder." |
| INV-AIR-MEDIA-TIME-004 | `pkg/air/docs/contracts/semantics/INV-AIR-MEDIA-TIME.md` | "Cadence independence — output FPS does not affect media time tracking" (and conversely, input/media time does not define output cadence). |
| TIMING-AUTHORITY-OVERVIEW | `pkg/air/docs/contracts/semantics/TIMING-AUTHORITY-OVERVIEW.md` | "metadata.duration for each returned video frame equals **one output tick** … Input frame duration must never leak into output duration or pacing." |

**Code:** TickProducer stores `output_fps_` (constructor/session) and `input_fps_num_`/`input_fps_den_` (per segment). CtMs(k), TickTimeUs, and frame_index advancement use **output_fps_** only. Input FPS is used for ResampleMode and, in CADENCE mode, for decode_budget in VideoLookaheadBuffer (frame **selection**), not for when ticks occur.

---

## E) Where is the "house format" defined as authoritative?

**Channel/session program format is the authority; it is called "house" in the audio context.**

| Reference | Location | Quote / fact |
|-----------|----------|--------------|
| PlayoutInvariants-BroadcastGradeGuarantees | `pkg/air/docs/contracts/laws/PlayoutInvariants-BroadcastGradeGuarantees.md` L61–64 | "**Channel defines house audio format.** The channel's program format (sample rate, channel layout, sample format) is the single source of truth for audio. It is established at session start … and does not change for the lifetime of the session." |
| INVARIANTS-INDEX | `pkg/air/docs/contracts/INVARIANTS-INDEX.md` L56 | "**Audio Format** | Channel defines house format; all audio normalized before OutputBus; EncoderPipeline never negotiates. Contract test: **INV-AUDIO-HOUSE-FORMAT-001**." |
| INVARIANTS-INDEX | `pkg/air/docs/contracts/INVARIANTS-INDEX.md` L117 | "INV-AUDIO-HOUSE-FORMAT-001 | All audio reaching EncoderPipeline (including pad) must be house format; … pad uses same path, CT, **cadence**, format as program." |
| PlayoutInstanceAndProgramFormatContract | `pkg/air/docs/contracts/semantics/PlayoutInstanceAndProgramFormatContract.md` | ProgramFormat: per-channel, fixed for PlayoutInstance lifetime; includes video frame rate (timebase), audio sample rate, channels. |
| PlayoutInvariants-BroadcastGradeGuarantees | L76 | "Format authority stays with the channel/session; the encoder is a consumer of a fixed contract." |

So: **house format** is explicitly used for **audio** (sample rate, layout, sample format); the same authority (channel/session program format) defines **video** frame rate and resolution. The **rational output FPS** (fps_num/fps_den) used for tick grid and fences is that session program format’s frame rate.

---

## Contradictions / potential violations

### 1) Cadence recalculated from source FPS

- **Contracts:** Tick grid and spt(N) are from session rational output FPS only (INV-FPS-RESAMPLE, INV-TICK-DEADLINE-DISCIPLINE-001). Input FPS is for frame **mapping** (INV-FPS-MAPPING), not for when ticks fire.
- **Code:** `InitFrameSelectionCadenceForLiveBlock` and `RefreshFrameSelectionCadenceFromLiveSource` recompute `frame_selection_cadence_budget_den_` and `frame_selection_cadence_increment_` from **input_fps** and **output_fps**. These drive **repeat-vs-advance** (presentation) only; tick **deadlines** remain spt(N) from epoch + output_fps. So there is **no** recalculation of **tick timing** from source FPS; only the **policy** of whether to advance or repeat is refreshed. **No contradiction** if "cadence" in those functions is read as "frame-selection cadence" not "tick cadence."
- **Resolved:** Code now uses `frame_selection_cadence_*` and the above function names; TIMING-AUTHORITY-OVERVIEW.md § E documents the distinction.

### 2) input_fps overwrites output_fps

- **Searched:** No place found where `ctx_->fps`, `output_fps_`, or session output FPS is assigned from input_fps or segment metadata.
- **Code:** TickProducer keeps `output_fps_` from constructor; segment open sets `input_fps_num_`/`input_fps_den_` only. PipelineManager fence/seam use `ctx_->fps` only. **No violation found.**

### 3) Tick timing depends on segment metadata

- **Contracts:** Fence tick is from block UTC schedule and session FPS (INV-BLOCK-WALLCLOCK-FENCE-001). Segment **seam** tick is `block_activation_frame + ceil(boundary.end_ct_ms × fps_num / (fps_den × 1000))` (INV-SEAM-SEG-004): boundary.end_ct_ms is **content** boundary from the plan; the **tick index** is computed using **session** fps_num/fps_den. So the **instant** (tick index) when the seam fires is driven by session output FPS; segment metadata supplies the **content** boundary (end_ct_ms), not a different FPS or tick rate.
- **Code:** `ComputeSegmentSeamFrames` uses `ctx_->fps` and `live_boundaries_[].end_ct_ms` (`PipelineManager.cpp` 3011–3024). So tick timing for seams **does** depend on segment/block metadata (end_ct_ms) to know **which** tick is the seam, but the **tick grid** itself (and thus cadence) does not come from segment FPS. **No contradiction** with "tick cadence driven by house/output format."

---

## CONFIRMED INVARIANTS

1. **Tick grid is output/house FPS.** Output tick time and block CT are from rational (fps_num, fps_den) only (INV-FPS-RESAMPLE). No round(1e6/fps) or int(1000/fps) accumulation.
2. **Session output timing is fixed.** ProgramFormat and session epoch are immutable for the session; output FPS does not change mid-session.
3. **Segment swap does not change tick timing.** RefreshFrameSelectionCadenceFromLiveSource updates only repeat-vs-advance policy; spt(N) and deadlines remain epoch + output FPS.
4. **input_fps is mapped, not timing authority.** OFF/DROP/CADENCE (INV-FPS-MAPPING) define frame selection; returned PTS and duration are one output tick (INV-TICK-AUTHORITY-001, INV-FPS-TICK-PTS). Input frame duration must not leak into output.
5. **House format is channel/session authority.** Channel defines house (audio) format; program format (including frame rate) is fixed at session start (laws, PlayoutInstanceAndProgramFormatContract, INV-AUDIO-HOUSE-FORMAT-001).
6. **Master clock / deadline authority.** MasterClock is the source of "now"; tick deadlines are from session epoch + rational FPS (INV-TICK-DEADLINE-DISCIPLINE-001, INV-TICK-MONOTONIC-UTC-ANCHOR-001).
7. **Fence and seam ticks use same rational formula.** Block fence and segment seam frame index use ceil(delta * fps_num / (fps_den * 1000)) with session fps_num/fps_den (INV-BLOCK-WALLCLOCK-FENCE-001, INV-SEAM-SEG-004).
8. **Resample mode.** input≠output must use OFF/DROP/CADENCE with rational comparison only; 60→30 DROP, 23.976→30 CADENCE, 30→30 OFF (INV-FPS-MAPPING).
9. **Guaranteed output.** Every tick emits exactly one frame; fallback chain real → freeze → black (INV-TICK-GUARANTEED-OUTPUT).

---

## POTENTIAL VIOLATIONS

1. **PTS-AND-FRAME-RATE-AUDIT.md** lists historical violations (TickProducer/FileProducer using int ms or rounded µs). The audit states these should be fixed per INV-FPS-RESAMPLE. Whether current code still uses `frame_duration_ms_` or rounded intervals in any path was not re-verified in this audit; the **contracts** are clear that such patterns are forbidden.
2. **Naming ambiguity:** "tick cadence" in `InitTickCadenceForLiveBlock` / `RefreshTickCadenceFromLiveSource` and in logs could be interpreted as "tick timing." Contracts use "tick cadence" for the Channel Clock (tick grid); the code’s tick_cadence_* controls **presentation** (repeat/advance). No functional violation, but clarity could be improved.

---

## AREAS REQUIRING CLARIFICATION

1. **execution_model=continuous_output:** Referenced in code (PipelineManager, BlockPlanTypes.hpp PlayoutExecutionMode::kContinuousOutput, tests). No INV-* in INVARIANTS-INDEX or contracts explicitly defines "continuous_output" or ties it to "tick cadence driven by house format." Clarify whether this mode is meant to be a first-class contract.
2. **format=...fps:** No single contract document was found that uses the literal string "format=...fps" as a key. ProgramFormat and rational fps_num/fps_den are the defined authority; any external "format" field (e.g. in gRPC or config) should be mapped to that. Clarify where "format=...fps" appears (API, config, logs) and that it must align with session rational FPS.
3. **INV-AIR-MEDIA-TIME-001:** Superseded for **block** transition authority by INV-BLOCK-WALLFENCE-001; CT remains authoritative for **segment** transitions within a block. The split (block = fence tick, segment = CT threshold) is documented; ensuring all call sites and tests respect this split may need a quick pass.
4. **VideoLookaheadBuffer decode_budget:** INV-FPS-MAPPING says "decode_budget / input_fps-derived budgeting ONLY when mode==CADENCE." VideoLookaheadBuffer.cpp ~238 confirms cadence_active (CADENCE) uses input_fps for budget; OFF/DROP do not use input_fps for decode gating. Aligned with contract; no open question except to keep this constraint under test.

---

## INV-* and related references (cadence / timing)

| ID | Topic | Location (doc or index) |
|----|--------|--------------------------|
| INV-FPS-RESAMPLE | Tick grid, block CT from rational FPS | semantics/INV-FPS-RESAMPLE.md |
| INV-FPS-MAPPING | OFF/DROP/CADENCE; output duration = one tick | semantics/INV-FPS-MAPPING.md |
| INV-FPS-TICK-PTS | Output PTS = one output tick per frame | semantics/INV-FPS-TICK-PTS.md |
| INV-TICK-AUTHORITY-001 | PTS delta and duration = one output tick | INV-FPS-MAPPING, index |
| INV-TICK-GUARANTEED-OUTPUT | One frame per tick; fallback chain | INV-TICK-GUARANTEED-OUTPUT.md |
| INV-TICK-DEADLINE-DISCIPLINE-001 | spt(N) from epoch + rational FPS; no slip | INV-TICK-DEADLINE-DISCIPLINE-001.md |
| INV-TICK-MONOTONIC-UTC-ANCHOR-001 | Monotonic deadline from epoch + rational FPS | INV-TICK-MONOTONIC-UTC-ANCHOR-001.md |
| INV-BLOCK-WALLFENCE-001 | Fence tick from rational FPS; immutable | INV-BLOCK-WALLCLOCK-FENCE-001.md |
| INV-SEAM-SEG-004 | Segment seam frame = block_activation_frame + ceil(ct_ms×fps/1000) | INVARIANTS-INDEX.md |
| INV-AIR-MEDIA-TIME-004 | Cadence independence (output FPS vs media time) | semantics/INV-AIR-MEDIA-TIME.md |
| INV-AUDIO-HOUSE-FORMAT-001 | Audio house format; pad same cadence/format | INVARIANTS-INDEX.md, laws |
| Clock Law | MasterClock sole source of "now" | PlayoutInvariants-BroadcastGradeGuarantees.md |
| INV-DETERMINISTIC-UNDERFLOW-AND-TICK-OBSERVABILITY | Underflow policy; tick lateness observable | INV-DETERMINISTIC-UNDERFLOW-AND-TICK-OBSERVABILITY.md |
| INV-PREROLL-OWNERSHIP-AUTHORITY | Preroll aligned with fence; no queue-peek for "next" | INV-PREROLL-OWNERSHIP-AUTHORITY.md |

---

## Summary

- **A)** Yes: tick cadence is driven by house/output format (rational fps_num/fps_den).
- **B)** Yes: output timing is fixed for the session (ProgramFormat and epoch immutability).
- **C)** No: segment swap is not allowed to alter execution cadence; it may only refresh frame-selection (repeat/advance) policy.
- **D)** input_fps must be mapped (OFF/DROP/CADENCE); it must not affect output tick timing.
- **E)** House format is defined as authoritative in the Clock/Audio laws and PlayoutInstanceAndProgramFormatContract; rational output FPS for the tick grid is that program format’s frame rate.

No architectural contradictions were found. Naming has been aligned: code uses frame_selection_cadence_* for repeat-vs-advance policy; TIMING-AUTHORITY-OVERVIEW.md § E documents the distinction. Clarifications are suggested for execution_model=continuous_output, format=...fps, and the block-vs-segment authority split.
