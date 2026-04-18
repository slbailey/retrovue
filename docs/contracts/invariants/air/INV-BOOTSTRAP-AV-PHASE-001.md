# INV-BOOTSTRAP-AV-PHASE-001

## Behavioral Guarantee

Before **`OutputClock`** is started, the live `PipelineManager` session MUST be in **bootstrap phase-valid** state: audio runway, audio ceiling, and **gate** A/V safety bounds defined below MUST all be satisfied, **or** the session MUST enter **bootstrap phase failure** (defined under **Failure semantics**).

## Authority Model

**`PipelineManager`** owns the bootstrap **gate poll** and the decision to call **`OutputClock::Start`**. **`VideoLookaheadBuffer`** owns **fill-domain** clamp per **INV-FILL-AV-LEAD-CLAMP-001**; it does not own clock start.

## Contract parameters (numeric policy)

All millisecond tolerances in this invariant are **logical parameters**, not literals in prose.

| Parameter | Meaning | Default (ms) | Configuration |
|-----------|---------|--------------|----------------|
| `audio_prime_floor_ms` | Minimum `AudioLookaheadBuffer::DepthMs()` before handoff | **Same value as** the existing audio prime threshold used for `PrimeFirstTick` / `kMinAudioPrimeMs` in code (single source of truth in `PipelineManager` / options) | **Not** redefined here; this invariant **references** the existing prime constant |
| `bootstrap_audio_ceiling_ms` | Maximum `AudioLookaheadBuffer::DepthMs()` before handoff | `min(HardCapMs(), HighWaterMs())` **evaluated at gate time** | Derived from buffer construction; **not** an arbitrary literal |
| `av_phase_tolerance_ms` | Maximum absolute **gate** A/V delta (see **video_time_ms_gate**) | **120** | **SHALL** be exposed as **`PipelineManagerOptions.av_phase_tolerance_ms`** (integer, ≥ 1). Until wired, implementation MAY use a compile-time default **only** if it is **identical** in **`PipelineManager`** and **`VideoLookaheadBuffer`** fill clamp (see **INV-FILL-AV-LEAD-CLAMP-001**). |
| `bootstrap_handoff_drift_guard_ms` | Maximum allowed queue-state drift from bootstrap pass snapshot to first steady fill evaluation | **0** | Atomic handoff policy: no additional drift budget beyond estimator guard; bootstrap pass state is preserved until first consumer-position update. |
| `startup_primed_audio_max_ms` | Maximum allowed pre-consumer primed-frame audio contribution applied at `StartFilling` before bootstrap fill progression | **output_frame_ms** | Startup priming must be phase-safe independent of decoder packetization shape. |
| `bootstrap_steady_entry_headroom_ms` | Preferred bootstrap steady-entry headroom target | **output_frame_ms** | Defines preferred continuous entry target: `bootstrap_steady_entry_max_ms = min(bootstrap_audio_ceiling_ms, audio_prime_floor_ms + bootstrap_steady_entry_headroom_ms)`. |
| `bootstrap_quantized_handoff_policy` | Quantized pre-consumer handoff admissibility | **first_floor_crossing_safe_quantum** | If continuous target is skipped by decode quantum, handoff may accept the first reachable floor-crossing quantum that still satisfies AV safety + ceiling + atomic handoff. |
| `bootstrap_post_handoff_transition_headroom_ms` | Required burst headroom before enabling normal steady fill control | **max(output_frame_ms, observed_bootstrap_quantum_ms)** | Transition target: `post_handoff_target_audio_ms = bootstrap_audio_ceiling_ms - bootstrap_post_handoff_transition_headroom_ms` (bounded at >=0). |
| `bootstrap_transition_exit_hysteresis_ms` | Required additional margin below transition target before steady re-entry | **min(bootstrap_post_handoff_transition_headroom_ms, reentry_hysteresis_cap_ms)** | Exit threshold: `post_handoff_exit_audio_ms = max(0, post_handoff_target_audio_ms - bootstrap_transition_exit_hysteresis_ms)`. |
| `reentry_hysteresis_cap_ms` | Maximum extra drain hysteresis so transition remains achievable | **3 * output_frame_ms** | Prevents over-conservative timeout-first exits while preserving burst-safe re-entry margin. |

**Default justification for `av_phase_tolerance_ms` = 120:** At output cadences **24 Hz–30 Hz**, 120 ms spans **3–5 output frame periods**. That bound is **tighter than one GOP** at typical broadcast distances, **wider than one frame**, and sufficient to absorb **decoder demux skew and AAC access-unit clustering** during cold start **without** permitting multi-second audio lead. It is the **authoritative broadcast-style join tolerance** for **bootstrap phase** until operator policy replaces it via configuration.

**Pairing rule:** `av_phase_tolerance_ms` **SHALL equal** the fill-domain **positive** lead cap **`fill_max_positive_av_lead_ms`** defined in **INV-FILL-AV-LEAD-CLAMP-001** (same option field or two fields **MUST** be set equal by configuration validator).

## Boundary / Constraint

### Definitions

- **`audio_depth_ms`**: `AudioLookaheadBuffer::DepthMs()` at the probe instant.
- **`video_time_ms_gate`**: Let `F = max(0, VideoLookaheadBuffer::DepthFrames())`. Let output rational FPS be `(N,D)` from the active session / tick producer context (`ctx_->fps` in `PipelineManager`). Then **`video_time_ms_gate = floor( F * 1000 * D / N )`** (integer division toward zero in implementation; contractually **the value produced by that formula in code**).

- **`gate_av_delta_ms`**: `audio_depth_ms - video_time_ms_gate`.
- **`output_frame_ms`**: `floor(1000 * D / N)` using the active output FPS `(N,D)`.
- **`bootstrap_fill_handoff_guard_ms`**: maximum allowed bootstrap→first-steady estimator gap. Default: `output_frame_ms`.
- **`handoff_drift_guard_ms`**: maximum allowed queue-state drift between bootstrap pass snapshot and first steady fill evaluation. Default: `bootstrap_handoff_drift_guard_ms`.
- **`consumer_not_started`**: bootstrap regime prior to first output-tick consumption (`VideoLookaheadBuffer` consumer position not yet advanced from initial sentinel).

### Handoff (success path)

Immediately before **`OutputClock::Start`**, all MUST hold:

1. `audio_depth_ms >= audio_prime_floor_ms`
2. `audio_depth_ms <= bootstrap_audio_ceiling_ms`
3. In `consumer_not_started` bootstrap regime:
   `gate_av_delta_ms <= av_phase_tolerance_ms - bootstrap_fill_handoff_guard_ms`
4. If consumer has started before handoff (non-default path), symmetric bound applies:
   `gate_av_delta_ms >= -av_phase_tolerance_ms`
5. Bootstrap handoff steady-entry admissibility in `consumer_not_started` regime:
   - Preferred: `audio_depth_ms <= bootstrap_steady_entry_max_ms`
   - Quantized-compatible fallback (required):
     if decode admission crosses the floor in a single quantum and skips the preferred band,
     handoff MAY accept the **smallest reachable floor-crossing quantum** provided all of:
     - previous gate sample was below floor: `prev_audio_depth_ms < audio_prime_floor_ms`
     - current sample crosses floor: `audio_depth_ms >= audio_prime_floor_ms`
     - current sample satisfies AV handoff guard (`gate_av_delta_ms` bound above)
     - current sample satisfies `audio_depth_ms <= bootstrap_audio_ceiling_ms`
   where `bootstrap_steady_entry_max_ms = min(bootstrap_audio_ceiling_ms, audio_prime_floor_ms + bootstrap_steady_entry_headroom_ms)`.

If all hold, **`PipelineManager` MUST** call `VideoLookaheadBuffer::EndBootstrap()` (or equivalent documented lifecycle) **before** `OutputClock::Start`, in the order already established by code.
For quantized-compatible handoff, implementation MAY enter a bounded post-handoff transition window that preserves atomicity while draining to transition headroom before enabling normal steady fill control.

### Startup primed-audio semantics (pre-consumer)

Before bootstrap gate polling, startup priming (`PrimeFirstFrame` / `PrimeFirstTick` / first `StartFilling` primed push) MUST satisfy:

1. Primed-frame audio is allowed to be bursty at decoder packet level.
2. The **effective** pre-consumer startup contribution from primed-frame audio MUST be bounded by:
   `primed_audio_effective_ms <= startup_primed_audio_max_ms`.
3. This bound MUST be asset-shape independent: packetization/chunking differences across channels MUST NOT produce deterministic bootstrap positive-lead divergence for equivalent editorial/runtime state.
4. Startup priming MUST NOT create deterministic immediate bootstrap positive-lead clamp solely due to decoder-drain burst shape.
5. `primed_audio_count=0` at `StartFilling` is permitted when audio stream exists **only if** startup liveness outcome remains valid:
   - bootstrap gate MUST still block `OutputClock::Start` until `audio_depth_ms >= audio_prime_floor_ms`, and
   - no decoded startup audio is lost by normalization (`startup_audio_total_ms` is preserved across primed + immediate buffered progression before handoff).
6. Startup normalization MAY shift audio from primed frame to immediately buffered frames, but MUST NOT introduce deterministic bootstrap-time audio starvation, underflow-at-first-tick, or additional clock-start delay beyond the existing bootstrap gate policy.

### Relationship to fill-domain estimator

**`video_time_ms_gate` and `video_time_ms_fill` (INV-FILL-AV-LEAD-CLAMP-001) may differ by estimator family.** The gate uses **committed video depth in frames** from the video buffer API. The fill clamp uses **lookahead / store size** inside the fill thread.

This invariant defines the mandatory bridge outcome for bootstrap pre-consumer state:

1. A state that passes bootstrap gate MUST be phase-safe for first steady-state fill evaluation.
2. The contract MUST NOT allow a deterministic immediate clamp on the first steady-state fill evaluation after bootstrap success.
3. Compliance model for this invariant is **atomic handoff**:
   bootstrap-pass queue state MUST be preserved across gate pass → clock start
   → first consumer-position update so first steady clamp does not evaluate a
   materially drifted state.
4. Bootstrap success MUST be quantized-compatible:
   if the preferred continuous steady-entry target is unreachable due to decode quantum,
   bootstrap MUST still admit the smallest reachable safe floor-crossing quantum
   (not an arbitrary later higher-depth state).

### Bootstrap→steady handoff invariant

For the first steady-state fill clamp evaluation after `EndBootstrap`:

`fill_av_delta_ms_first <= fill_max_positive_av_lead_ms`

With guard-band bridging, bootstrap pass MUST additionally satisfy:

`gate_av_delta_ms <= av_phase_tolerance_ms - bootstrap_fill_handoff_guard_ms`

where `bootstrap_fill_handoff_guard_ms` defaults to `output_frame_ms`.

This is an outcome contract, not an implementation prescription.
If this condition is violated, bootstrap success is invalid even if the original gate checks pass.

### Post-handoff transition headroom (quantized-compatible)

When bootstrap is admitted by quantized floor crossing and handoff starts near ceiling,
the system MUST provide a bounded post-handoff transition outcome:

1. Compute transition burst headroom:
   `bootstrap_post_handoff_transition_headroom_ms = max(output_frame_ms, observed_bootstrap_quantum_ms)`.
2. Compute transition target:
   `post_handoff_target_audio_ms = max(0, bootstrap_audio_ceiling_ms - bootstrap_post_handoff_transition_headroom_ms)`.
3. During a bounded transition window immediately after clock start / first consumer updates,
   handoff MUST converge audio depth toward `post_handoff_target_audio_ms` before treating
   recurring predictive high-water clamp as normal control behavior.
4. Transition drain exclusivity:
   while `audio_depth_ms > post_handoff_target_audio_ms`, transition policy MUST be
   drain-first and MUST NOT admit new bursty decode/admission that re-pressurizes
   high-water behavior in the same window.
4. Transition MUST remain achievable (no bootstrap timeout regression) and MUST preserve
   first-fill AV safety and OutputClock authority.

### Transition exit hysteresis (re-entry safety)

Transition MUST NOT exit exactly at the target boundary when that would allow immediate
burst re-pressurization, but hysteresis MUST be bounded so exit remains reachable.
Define:

`post_handoff_exit_audio_ms = max(0, post_handoff_target_audio_ms - bootstrap_transition_exit_hysteresis_ms)`

with

`bootstrap_transition_exit_hysteresis_ms = min(bootstrap_post_handoff_transition_headroom_ms, reentry_hysteresis_cap_ms)`

and default `reentry_hysteresis_cap_ms = 3 * output_frame_ms`.

Transition may end when either:
- `audio_depth_ms <= post_handoff_exit_audio_ms`, or
- bounded transition timeout is reached.

This hysteresis ensures first resumed steady cycles have burst-safe re-entry headroom.
This bound ensures transition exit is burst-safe **and** achievable under normal HBO cadence.

Negative `gate_av_delta_ms` in `consumer_not_started` bootstrap is not, by itself,
a handoff blocker. In that regime, video-ahead queue shape may occur naturally
because decode/fill runs before first consumption.

### Bounded transient policy

Deterministic immediate post-bootstrap AV-delta clamp is forbidden.
Predictive high-water clamp in the first transition window MAY occur transiently, but recurring
predictive-clamp-controlled behavior in that window is a violation unless transition headroom
convergence conditions above are being satisfied and completed within bounded transition time.
Under transition drain exclusivity, the expected transition path is monotonic drain
toward target with decode admission resumed only after target is reached (or transition timeout).

### Handoff atomicity window

The handoff window includes:

1. gate pass snapshot → `EndBootstrap`
2. `EndBootstrap` → `OutputClock::Start`
3. `OutputClock::Start` / gate open → first steady fill clamp evaluation

During this window, the validated bootstrap state and first steady fill state MUST be phase-safe by construction under the guard relation above.

## Failure semantics (bootstrap phase failure)

If the gate poll exceeds **`PipelineManagerOptions.bootstrap_gate_timeout_ms`** without satisfying all success conditions:

1. **System-level state:** **Session bootstrap aborted** — playout for this activation MUST NOT enter paced emission. **`PipelineManager` MUST** set **`stop_requested`** (or the single authoritative session-stop flag used by AIR for this path) to **true** and **MUST NOT** call **`OutputClock::Start`** and **MUST NOT** open the emission gate on this path.
2. **Observer:** **Core / supervisor** observes session end via the existing AIR session lifecycle (gRPC / process exit / health — **the mechanism already used when `stop_requested` is set during startup**). This invariant does **not** introduce a new IPC channel; it **binds semantics** to the existing flag.
3. **Retryability:** A **new** channel activation / new AIR session **MAY** retry from Core; **in-session** retry of bootstrap without teardown is **not** required and **not** forbidden — implementation chooses, but **MUST NOT** start `OutputClock` after declaring failure on this path.
4. **Logs (MUST):** At minimum one **`Warn`** (or **`Error`** if product policy elevates) structured line including: `invariant_id=INV-BOOTSTRAP-AV-PHASE-001`, `reason=bootstrap_gate_timeout`, `audio_depth_ms`, `audio_prime_floor_ms`, `bootstrap_audio_ceiling_ms`, `gate_av_delta_ms`, `av_phase_tolerance_ms`, `elapsed_ms`, `video_depth_frames`, `fill_phase` (if available).
5. **Metrics (SHOULD):** A counter **`air_bootstrap_phase_failure_total`** (or equivalent name in the existing metrics namespace) incremented once per failure.

## Violation

- `OutputClock::Start` called when any of the three success conditions is false.
- `OutputClock::Start` from a pre-consumer quantized state that is neither within
  preferred steady-entry target nor the smallest reachable safe floor-crossing quantum.
- Timeout elapsed without success **and** `OutputClock` started anyway.
- Timeout without **`stop_requested`** (or equivalent) and without successful handoff.
- Bootstrap gate success followed by deterministic immediate fill clamp on first steady-state evaluation under the configured tolerance.
- Quantized bootstrap success that enters steady-state control without bounded transition
  to post-handoff burst headroom, leading to immediate recurring predictive `audio_high_water` clamps.
- Transition window policy that permits new bursty decode while above transition target,
  reintroducing high-water pressure before drain target is reached.
- Transition exiting at/near target without hysteresis, causing immediate post-transition
  predictive clamp re-entry on normal bursty admission.
- Startup primed-frame burst causing deterministic bootstrap positive-lead clamp that is attributable to decoder packetization shape rather than declared authority state.

## Derives From

- `LAW-CLOCK`
- `LAW-LIVENESS`

## Required Tests

- `runtime/tests/contracts/BlockPlan/BootstrapAvPhaseContractTests.cpp` (`BootstrapGate_BlocksClockStart_WhenAudioDepthBelowPrimeFloor`)
- `runtime/tests/contracts/BlockPlan/BootstrapAvPhaseContractTests.cpp` (`BootstrapGate_BlocksClockStart_WhenAudioDepthExceedsBootstrapCeiling`)
- `runtime/tests/contracts/BlockPlan/BootstrapAvPhaseContractTests.cpp` (`BootstrapGate_BlocksClockStart_WhenPositiveAvDeltaExceedsHandoffSafeTolerance`)
- `runtime/tests/contracts/BlockPlan/BootstrapAvPhaseContractTests.cpp` (`BootstrapGate_PreConsumerCandidateIsAchievableUnderNormalFillShape`)
- `runtime/tests/contracts/BlockPlan/BootstrapAvPhaseContractTests.cpp` (`BootstrapGate_StartsClock_WhenBootstrapStateIsPhaseValid`)
- `runtime/tests/contracts/BlockPlan/BootstrapAvPhaseContractTests.cpp` (`BootstrapGate_RejectsClockStart_WhenAudioDepthAboveSteadyEntryBandTarget`)
- `runtime/tests/contracts/BlockPlan/BootstrapAvPhaseContractTests.cpp` (`BootstrapGate_AllowsClockStart_WhenAudioDepthWithinSteadyEntryBandTarget`)
- `runtime/tests/contracts/BlockPlan/BootstrapAvPhaseContractTests.cpp` (`BootstrapGate_AllowsClockStart_OnFirstSafeQuantizedFloorCrossing`)
- `runtime/tests/contracts/BlockPlan/BootstrapAvPhaseContractTests.cpp` (`BootstrapGate_ContinuousSteadyEntryOnly_WouldRejectHboQuantizedCrossing`)
- `runtime/tests/contracts/BlockPlan/BootstrapAvPhaseContractTests.cpp` (`PostHandoffTransitionTarget_ComputesBurstAwareHeadroom_FromQuantizedBootstrap`)
- `runtime/tests/contracts/BlockPlan/BootstrapAvPhaseContractTests.cpp` (`HboQuantizedHandoff_RequiresTransitionDrainBeforeSteadyBurstControl`)
- `runtime/tests/contracts/BlockPlan/BootstrapAvPhaseContractTests.cpp` (`TransitionDrainExclusivity_HoldsDecodeAdmissionUntilTargetReached`)
- `runtime/tests/contracts/BlockPlan/BootstrapAvPhaseContractTests.cpp` (`TransitionExitHysteresis_ComputesBurstSafeReentryThreshold`)
- `runtime/tests/contracts/BlockPlan/BootstrapAvPhaseContractTests.cpp` (`BootstrapPassState_MustBeFirstSteadyFillSafe`)
- `runtime/tests/contracts/BlockPlan/BootstrapAvPhaseContractTests.cpp` (`BootstrapPassState_MustNotDeterministicallyTripClampNextEvaluation`)
- `runtime/tests/contracts/BlockPlan/BootstrapAvPhaseContractTests.cpp` (`StartupPrimedAudioBurst_MustBePacketizationShapeIndependentForBootstrapSafety`)
- `runtime/tests/contracts/BlockPlan/BootstrapAvPhaseContractTests.cpp` (`HboStylePrimedBurst_MustNotDeterministicallyTripBootstrapPositiveLeadClamp`)

## Enforcement Evidence

TODO
