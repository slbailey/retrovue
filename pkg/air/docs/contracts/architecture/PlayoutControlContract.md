# Playout Control Contract

_Related: [Playout Engine Contract](PlayoutEngineContract.md) · [Phase 6A Overview](../phases/Phase6A-Overview.md)_

**Applies starting in:** Phase 6A.1 (slot management, state transitions); latency and full telemetry Deferred (Applies Phase 7+)  
**Status:** Draft; Phase 6A–compatible rules enforced; remainder Deferred (Applies Phase 7+) with intent preserved

**Principle:** Air must be correct before it is fast. Performance guarantees are explicitly deferred until correctness is contractually proven.

## Purpose

Define enforceable guarantees for session control: state transitions, preview/live slot management, and (when in scope) latency and fault telemetry. This contract specifies **what** the control plane guarantees, not how it is implemented. **Segment-based control** is canonical: preview is loaded via LoadPreview (segment payload); SwitchToLive is control-only. **Engine** owns preview/live slots and switch timing; producers are passive.

---

## Phase 6A–Enforced Rules

### CTL-001: Deterministic State Transitions

**Guarantee:** Control plane only performs legal state transitions.

**Phase applicability:** 6A.1+

**Observable behavior:**
- Legal commands move channel through documented states (e.g. initialized → preview loaded → live → stopped).
- Illegal transitions are rejected (state unchanged).
- States align with Phase 6A: e.g. after StartChannel → initialized; after LoadPreview → preview loaded; after SwitchToLive → live running; after StopChannel → stopped.

**Deferred (Applies Phase 7+):** Metric `playout_control_state_transition_total{from,to}` and `playout_control_illegal_transition_total{from,to}`; validated when full telemetry is in scope. Legal transition matrix (Idle → Playing → Paused → Stopped, etc.) may be refined when full loop/Renderer exists.

---

### CTL-002: Control Action Latency

**Guarantee:** Control actions complete within documented tolerances.

**Phase applicability:** Deferred (Applies Phase 7+). Specific numeric targets are future enforcement.

**Intent (preserved):**

| Action | Target (p95) |
|--------|--------------|
| Pause | ≤ 33ms |
| Resume | ≤ 50ms |
| Seek | ≤ 250ms end-to-end |
| Stop | ≤ 500ms |
| Teardown | Within configured timeout |

**Why deferred:** Phase 6A does not enforce microsecond-level control latency; validation starts when full pipeline (producer → buffer → Renderer/TS) exists.

**Deferred observable behavior:** Latency histograms `playout_control_*_latency_ms`; violation metric `playout_control_latency_violation_total`; escalation to Error state.

---

### CTL-003: Command Idempotency

**Guarantee:** Idempotency is defined **per command**, not as a blanket “all methods idempotent.”

**Phase applicability:** 6A.0+

**Observable behavior:**
- **StartChannel** on already-started channel: idempotent success (no state change; same result as first start).
- **StopChannel** on unknown or already-stopped channel: idempotent success.
- **LoadPreview:** Replaces preview; duplicate same segment not required to be no-op.
- **SwitchToLive:** No segment payload; “no preview loaded” → error; otherwise switch or no-op per engine semantics.

**Deferred (Applies Phase 7+):** Dedup window `(channel_id, command_id)` and metric “no additional transition increment” when full telemetry is required.

---

### CTL-004: Failure Telemetry

**Guarantee:** All failures are observable (design intent). Full telemetry implementation is Phase 7+.

**Phase applicability:** Phase 6A: failures result in `success=false` (and optional error_message). **Deferred (Applies Phase 7+):** Counters and histograms (timeout, queue overflow, recovery) and “channel to Error requiring explicit Recover.”

**Why deferred:** Phase 6A focuses on control surface and producer lifecycle; full failure metrics validated when pipeline and recovery flows exist.

---

### CTL-005: Preview/Live Slot Management

**Guarantee:** Preview and live slots are managed for segment-based execution. Engine owns slots; producers are passive (Start/Stop only). Segment-based control: LoadPreview (asset_path, start_offset_ms, hard_stop_time_ms) loads **preview**; SwitchToLive promotes preview → live and clears/recycles previous live.

**Phase applicability:** 6A.1+

**Observable behavior:**
- Preview asset (segment) can be loaded while live continues (or while no live).
- LoadPreview installs segment into **preview** slot; live unchanged until SwitchToLive.
- SwitchToLive promotes preview to live atomically; old live content stops (or is recycled); preview slot cleared or ready for next LoadPreview.
- Producers do not “self-switch” or manage switch timing; engine owns switch timing.

---

### CTL-006: Producer Switching Seamlessness

**Guarantee:** Switching from preview to live is **seamless** when output path (Renderer/TS) exists.

**Phase applicability:** Deferred (Applies Phase 7+). Phase 6A validates correct order (LoadPreview → SwitchToLive) and slot semantics, not output continuity.

**Intent (preserved):**
- Switch occurs at frame boundary.
- **PTS continuity maintained** — no jumps, no resets.
- **No visual discontinuity** — no black frames, no stutter.
- Last live frame and first preview frame consecutive; buffer not flushed.
- Switch completes within 100ms.

**Why deferred:** Phase 6A explicitly defers Renderer placement and MPEG-TS; seamless output is enforced post-6A.

---

## Behavioral Rules Summary

| Rule | Guarantee | Phase |
|------|-----------|--------|
| CTL-001 | Legal state transitions only | 6A.1+ |
| CTL-002 | Control latency within bounds | Deferred (Applies Phase 7+) |
| CTL-003 | Per-command idempotency (Start/Stop idempotent) | 6A.0+ |
| CTL-004 | Failures observable (full telemetry 7+) | 6A: response; 7+: metrics |
| CTL-005 | Preview/live slot management (engine-owned) | 6A.1+ |
| CTL-006 | Seamless producer switching | Deferred (Applies Phase 7+) |

---

## Test Coverage

| Rule | Test | Phase |
|------|------|--------|
| CTL-001 | `test_control_state_transitions` | 6A.1+ |
| CTL-002 | `test_control_latency` | 7+ |
| CTL-003 | `test_control_idempotency` (StartChannel, StopChannel) | 6A.0+ |
| CTL-004 | `test_control_failure_telemetry` | 7+ |
| CTL-005, CTL-006 | `test_control_switching` (slot semantics in 6A; seamlessness in 7+) | 6A.1+ / 7+ |

---

## See Also

- [Playout Engine Contract](PlayoutEngineContract.md) — gRPC API
- [Phase 6A Overview](../phases/Phase6A-Overview.md) — segment-based control
- [Phase6A-1 ExecutionProducer](../phases/Phase6A-1-ExecutionProducer.md) — slots and lifecycle
