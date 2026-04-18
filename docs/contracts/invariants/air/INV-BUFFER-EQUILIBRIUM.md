# INV-BUFFER-EQUILIBRIUM

## Behavioral Guarantee
Buffer depth remains bounded and oscillates around target. Neither unbounded growth nor steady-state drain to zero is permitted.
Steady-state MUST converge to an operating band where clamp is an occasional
safety guard, not the recurring controller of queue behavior.

## Authority Model
Target depth (e.g. default 3) and range [1, 2N] define the equilibrium band; decode gate and mux consumption enforce it.

## Boundary / Constraint
Depth MUST remain in range [1, 2N] during steady-state. Monotonic growth or drain to zero indicates a bug.
In addition, under normal steady-state cadence-shaped production (no transport
stall and no startup/bootstrap phase), the system MUST NOT remain in a
sustained predictive-clamp-controlled regime where `kAvLeadClamp` repeatedly
governs admission over consecutive windows instead of converging lower.
Healthy steady-state operation MUST maintain a working headroom below
`audio_high_water_ms` so normal burst-shaped decoded batches are usually
admissible without immediately re-entering clamp.

Operationally, recurring clamp bursts may occur transiently, but persistent
high-frequency clamp reliance after convergence is a contract failure.

### Steady-state headroom outcome

Let `steady_operating_headroom_ms` be the minimum steady-state margin below
`audio_high_water_ms` required after convergence (default: one output-frame
period at session FPS). Under normal steady-state operation:

`audio_depth_ms <= audio_high_water_ms - steady_operating_headroom_ms`

must hold for sustained windows, with clamp reserved for occasional safety
events rather than continuous control.

### Burst-aware convergence target

For cadence-shaped burst production, admission MUST target a burst-aware
operating band rather than "maximum safe now" at the clamp boundary.
Define:

- `pending_audio_ms_effective`: effective decoded audio batch contribution for the cycle.
- `steady_burst_headroom_ms = max(steady_operating_headroom_ms, pending_audio_ms_effective)`.
- `steady_target_audio_ms = audio_high_water_ms - steady_burst_headroom_ms`.

Admission in steady state MUST converge toward `steady_target_audio_ms`
(bounded by low-water/liveness constraints), so a normal next burst is
usually admissible without immediate re-entry into predictive clamp.

## Violation
Unbounded growth (memory leak) or steady-state drain to zero.
Sustained predictive-clamp-controlled operation in steady state (clamp acting
as de facto equilibrium controller over repeated windows).

## Required Tests
- `runtime/tests/contracts/Phase9BufferEquilibriumTests.cpp`
- `runtime/tests/contracts/Phase10PipelineFlowControlTests.cpp` (TEST_P10_EQUILIBRIUM_001_BufferDepthStable)
- `runtime/tests/contracts/BlockPlan/FillAvLeadClampContractTests.cpp` (`SteadyState_MustNotRelyOnPersistentPredictiveHighWaterClampControl`)

## Enforcement Evidence

- `VideoLookaheadBuffer` and `AudioLookaheadBuffer` enforce bounded capacity — buffer depth is capped at `2 * target_depth` and cannot grow unbounded.
- **Decode gate feedback:** Fill thread blocks on `av_read_frame` when either buffer is at capacity (per `INV-DECODE-GATE`), preventing monotonic growth.
- **Mux consumption:** `MpegTSOutputSink` dequeues frames at real-time cadence (per `INV-PCR-PACED-MUX`), preventing steady-state drain to zero during active playout.
- Contract tests: `Phase9BufferEquilibriumTests.cpp` validates depth remains in `[1, 2N]` during steady-state. `Phase10PipelineFlowControlTests.cpp` (`TEST_P10_EQUILIBRIUM_001_BufferDepthStable`) verifies no monotonic growth or drain across extended playout.
