# INV-DETERMINISTIC-UNDERFLOW-AND-TICK-OBSERVABILITY: Underflow Policy and Tick Lateness

**Classification:** INVARIANT (Coordination — Broadcast-Grade) / Observability
**Owner:** PipelineManager, VideoLookaheadBuffer
**Enforcement Phase:** Every output tick within a BlockPlan session
**Depends on:** INV-LOOKAHEAD-BUFFER-AUTHORITY, INV-TICK-DEADLINE-DISCIPLINE-001, INV-TICK-GUARANTEED-OUTPUT
**Created:** 2026-02-22
**Status:** Active

---

## Definition

Under decode jitter or tick gaps, the system MUST behave deterministically: when the video lookahead buffer cannot supply a frame, the tick loop MUST emit output using a deterministic policy (freeze last frame and/or PADDED_GAP) so that underflow does not cascade into a "stall spiral." Underflow MUST be a controlled state transition with enriched observability; MasterClock timing MUST be preserved.

Tick lateness MUST be observable via structured log fields and optional metrics so that TICK_GAP and underflow events can be diagnosed with consistent keys.

---

## Outcomes (Required Behavior)

### OUT-UNDERFLOW-001: Deterministic Underflow Behavior

- When lookahead depth falls at or below low_water, the system MUST NOT rely on nondeterministic behavior. The tick loop MUST use a deterministic policy: emit last decoded frame (freeze) or PADDED_GAP frame to keep output cadence.
- Underflow (buffer empty when a frame is requested from a primed source) MUST be a controlled transition: log once with enriched fields, then either (a) emit freeze/pad for that tick and continue, or (b) session stop, per existing INV-VIDEO-LOOKAHEAD-001. The contract does not require changing the current "session stop on underflow" semantics; it requires that any path that continues (e.g. fallback) use deterministic freeze/pad, and that underflow never cause a "random stall spiral" (unbounded delay or nondeterministic catch-up).
- Audio/video decoupling intentions (ROADMAP_AUDIO_VIDEO_DECOUPLING) MUST be preserved; underflow handling MUST NOT re-couple audio to video advancement.

### OUT-UNDERFLOW-002: Enriched Underflow Log

- When INV-VIDEO-LOOKAHEAD-001 UNDERFLOW is logged, the log MUST include at least: `low_water`, `target`, `depth_at_event` (buffer depth at underflow), and optionally `lateness_ms` or `p95_lateness_ms` when tick lateness context is available.
- Existing fields `total_pushed`, `total_popped`, `frame` (session_frame_index) remain required.

### OUT-TICK-OBS-001: Tick Lateness Observable

- The tick loop MUST make tick lateness observable: per-tick deadline/start/end timestamps and computed `lateness_ms` (how late the tick was relative to spt(N)).
- Periodic or rolling-window lateness metrics (e.g. p50/p95/p99) MAY be emitted in logs or metrics.
- When inter-frame gaps exceed a threshold (e.g. 50ms), the system MUST log TICK_GAP with consistent structured fields: `gap_ms`, `tick`, `lateness_ms` (when available), `phase` (or equivalent).

### OUT-TICK-OBS-002: No Nondeterministic Sleeps

- All timing MUST be MasterClock-driven (or session-epoch–derived). No nondeterministic sleeps in the tick or underflow path that could cause a "stall spiral."

---

## Required Tests

**File:** `pkg/air/tests/contracts/test_deterministic_underflow_and_tick_observability.py` and/or C++ contract tests in `pkg/air/tests/contracts/BlockPlan/`

| Test Name | Outcome(s) | Description |
|-----------|------------|-------------|
| `under_simulated_jitter_output_stable` | OUT-UNDERFLOW-001 | Under simulated decode jitter / tick gaps (e.g. 50–600ms), output timing remains stable; system transitions to pad/freeze deterministically; no stall spiral. |
| `underflow_emits_enriched_log` | OUT-UNDERFLOW-002 | When underflow occurs, the UNDERFLOW log includes low_water, target, depth_at_event; optionally lateness_ms/p95 when available. |
| `tick_gap_log_has_structured_fields` | OUT-TICK-OBS-001 | When a gap exceeds threshold, TICK_GAP log includes gap_ms, tick, and consistent keys (lateness_ms when available, phase). |
| `tick_loop_emits_lateness_metrics` | OUT-TICK-OBS-001 | Tick loop emits lateness metrics (e.g. periodic p50/p95 or rolling window) in logs or metrics. |

---

## Relationship to Other Contracts

- **INV-VIDEO-LOOKAHEAD-001:** Underflow remains a hard fault at the buffer boundary; this contract specifies deterministic handling and log content at the PipelineManager/tick layer.
- **INV-TICK-DEADLINE-DISCIPLINE-001:** Lateness observability supports deadline discipline; deadlines remain epoch-derived.
- **INV-TICK-GUARANTEED-OUTPUT:** Freeze/pad policy satisfies guaranteed output; no tick is skipped.
