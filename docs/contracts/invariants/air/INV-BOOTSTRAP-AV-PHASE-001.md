# INV-BOOTSTRAP-AV-PHASE-001

## Behavioral Guarantee

Before **`OutputClock`** is started, the live `PipelineManager` session MUST be in **bootstrap phase-valid** state: audio runway, audio ceiling, and **gate** A/V delta bounds defined below MUST all be satisfied **simultaneously** at the moment of handoff, **or** the session MUST enter **bootstrap phase failure** (defined under **Failure semantics**).

## Authority Model

**`PipelineManager`** owns the bootstrap **gate poll** and the decision to call **`OutputClock::Start`**. **`VideoLookaheadBuffer`** owns **fill-domain** clamp per **INV-FILL-AV-LEAD-CLAMP-001**; it does not own clock start.

## Contract parameters (numeric policy)

All millisecond tolerances in this invariant are **logical parameters**, not literals in prose.

| Parameter | Meaning | Default (ms) | Configuration |
|-----------|---------|--------------|----------------|
| `audio_prime_floor_ms` | Minimum `AudioLookaheadBuffer::DepthMs()` before handoff | **Same value as** the existing audio prime threshold used for `PrimeFirstTick` / `kMinAudioPrimeMs` in code (single source of truth in `PipelineManager` / options) | **Not** redefined here; this invariant **references** the existing prime constant |
| `bootstrap_audio_ceiling_ms` | Maximum `AudioLookaheadBuffer::DepthMs()` before handoff | `min(HardCapMs(), HighWaterMs())` **evaluated at gate time** | Derived from buffer construction; **not** an arbitrary literal |
| `av_phase_tolerance_ms` | Maximum absolute **gate** A/V delta (see **video_time_ms_gate**) | **120** | **SHALL** be exposed as **`PipelineManagerOptions.av_phase_tolerance_ms`** (integer, ≥ 1). Until wired, implementation MAY use a compile-time default **only** if it is **identical** in **`PipelineManager`** and **`VideoLookaheadBuffer`** fill clamp (see **INV-FILL-AV-LEAD-CLAMP-001**). |

**Default justification for `av_phase_tolerance_ms` = 120:** At output cadences **24 Hz–30 Hz**, 120 ms spans **3–5 output frame periods**. That bound is **tighter than one GOP** at typical broadcast distances, **wider than one frame**, and sufficient to absorb **decoder demux skew and AAC access-unit clustering** during cold start **without** permitting multi-second audio lead. It is the **authoritative broadcast-style join tolerance** for **bootstrap phase** until operator policy replaces it via configuration.

**Pairing rule:** `av_phase_tolerance_ms` **SHALL equal** the fill-domain **positive** lead cap **`fill_max_positive_av_lead_ms`** defined in **INV-FILL-AV-LEAD-CLAMP-001** (same option field or two fields **MUST** be set equal by configuration validator).

## Boundary / Constraint

### Definitions

- **`audio_depth_ms`**: `AudioLookaheadBuffer::DepthMs()` at the probe instant.
- **`video_time_ms_gate`**: Let `F = max(0, VideoLookaheadBuffer::DepthFrames())`. Let output rational FPS be `(N,D)` from the active session / tick producer context (`ctx_->fps` in `PipelineManager`). Then **`video_time_ms_gate = floor( F * 1000 * D / N )`** (integer division toward zero in implementation; contractually **the value produced by that formula in code**).

- **`gate_av_delta_ms`**: `audio_depth_ms - video_time_ms_gate`.

### Handoff (success path)

Immediately before **`OutputClock::Start`**, all MUST hold:

1. `audio_depth_ms >= audio_prime_floor_ms`
2. `audio_depth_ms <= bootstrap_audio_ceiling_ms`
3. `|gate_av_delta_ms| <= av_phase_tolerance_ms`

If all hold, **`PipelineManager` MUST** call `VideoLookaheadBuffer::EndBootstrap()` (or equivalent documented lifecycle) **before** `OutputClock::Start`, in the order already established by code.

### Relationship to fill-domain estimator

**`video_time_ms_gate` and `video_time_ms_fill` (INV-FILL-AV-LEAD-CLAMP-001) are deliberately different estimators.** The gate uses **committed video depth in frames** from the video buffer API. The fill clamp uses **lookahead / store size** inside the fill thread. **Both are contractually valid.** **Phase-valid** for **clock start** is defined **only** using **`gate_av_delta_ms`**. **Phase-valid** for **suppressing a Push** in FillLoop is defined **only** using **fill** metrics in **INV-FILL-AV-LEAD-CLAMP-001**.

## Failure semantics (bootstrap phase failure)

If the gate poll exceeds **`PipelineManagerOptions.bootstrap_gate_timeout_ms`** without satisfying all three success conditions:

1. **System-level state:** **Session bootstrap aborted** — playout for this activation MUST NOT enter paced emission. **`PipelineManager` MUST** set **`stop_requested`** (or the single authoritative session-stop flag used by AIR for this path) to **true** and **MUST NOT** call **`OutputClock::Start`** and **MUST NOT** open the emission gate on this path.
2. **Observer:** **Core / supervisor** observes session end via the existing AIR session lifecycle (gRPC / process exit / health — **the mechanism already used when `stop_requested` is set during startup**). This invariant does **not** introduce a new IPC channel; it **binds semantics** to the existing flag.
3. **Retryability:** A **new** channel activation / new AIR session **MAY** retry from Core; **in-session** retry of bootstrap without teardown is **not** required and **not** forbidden — implementation chooses, but **MUST NOT** start `OutputClock` after declaring failure on this path.
4. **Logs (MUST):** At minimum one **`Warn`** (or **`Error`** if product policy elevates) structured line including: `invariant_id=INV-BOOTSTRAP-AV-PHASE-001`, `reason=bootstrap_gate_timeout`, `audio_depth_ms`, `audio_prime_floor_ms`, `bootstrap_audio_ceiling_ms`, `gate_av_delta_ms`, `av_phase_tolerance_ms`, `elapsed_ms`, `video_depth_frames`, `fill_phase` (if available).
5. **Metrics (SHOULD):** A counter **`air_bootstrap_phase_failure_total`** (or equivalent name in the existing metrics namespace) incremented once per failure.

## Violation

- `OutputClock::Start` called when any of the three success conditions is false.
- Timeout elapsed without success **and** `OutputClock` started anyway.
- Timeout without **`stop_requested`** (or equivalent) and without successful handoff.

## Derives From

- `LAW-CLOCK`
- `LAW-LIVENESS`

## Required Tests

- `runtime/tests/contracts/BlockPlan/` — bootstrap gate tests (floor, ceiling, `|gate_av_delta|`, timeout → no clock) — **to be added in test pass**.

## Enforcement Evidence

TODO
