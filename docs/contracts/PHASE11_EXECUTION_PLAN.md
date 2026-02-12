# Phase 11 Execution Plan: Broadcast-Grade Timing Compliance

**Status:** Phase 11A–11F complete (2026-02-02)
**Source:** 2026-02-01 Systems Contract Audit; CANONICAL_RULE_LEDGER.md
**Last Updated:** 2026-02-02

Phase 11 is a **separate execution track** from Phase 1. It can be paused or stopped independently. Phase 1 (Prevent Black/Silence) is complete; Phase 11 implements broadcast-grade timing invariants identified by a post–Phase 1 audit.

---

## Relationship to Phase 1

| Document | Scope |
|----------|--------|
| **PHASE1_EXECUTION_PLAN.md** | Phase 1: Prevent Black/Silence (ProgramOutput, EncoderPipeline, MpegTSOutputSink, PlayoutEngine, FileProducer). ✅ Complete. |
| **PHASE11_EXECUTION_PLAN.md** | Phase 11: Broadcast-Grade Timing (Authority Hierarchy, 11A–11F). Separate track; can be stopped independently. |

---

## Foundational Principle: LAW-AUTHORITY-HIERARCHY

The 2026-02-01 audit identified a contradiction between clock-based rules (LAW-CLOCK, LAW-SWITCHING) and frame-based rules (LAW-FRAME-EXECUTION, INV-FRAME-001, INV-FRAME-003). This was resolved by establishing an explicit authority hierarchy:

```
┌─────────────────────────────────────────────────────────────────┐
│                    LAW-AUTHORITY-HIERARCHY                       │
│         "Clock authority supersedes frame completion"            │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│   LAW-CLOCK   │    │ LAW-SWITCHING │    │LAW-FRAME-EXEC │
│ WHEN things   │    │ WHEN switch   │    │ HOW precisely │
│ happen        │    │ executes      │    │ cuts happen   │
│ [AUTHORITY]   │    │ [AUTHORITY]   │    │ [EXECUTION]   │
└───────────────┘    └───────────────┘    └───────────────┘
                              │
                              ▼
                    ┌───────────────┐
                    │INV-SEGMENT-   │
                    │CONTENT-001    │
                    │ WHETHER       │
                    │ sufficient    │
                    │ [VALIDATION]  │
                    │ (clock does   │
                    │  not wait)    │
                    └───────────────┘
```

**Key Principle:** If frame completion and clock deadline conflict, **clock wins**. Frame-based rules describe *how to execute* within a segment, not *whether to execute* a scheduled transition.

**Anti-Pattern (BUG):** Code that waits for frame completion before executing a clock-scheduled switch.

**Correct Pattern:** Schedule switch at clock time. If content isn't ready, use safety rails (pad/silence). Never delay the clock.

---

## Rules Downgraded from Authority to Execution

| Rule ID | Old Interpretation | New Interpretation |
|---------|-------------------|-------------------|
| **LAW-FRAME-EXECUTION** | "Frame index is execution authority" | Governs execution precision (HOW), not timing (WHEN). Subordinate to LAW-CLOCK. |
| **INV-FRAME-001** | "Boundaries are frame-indexed, not time-based" | Frame-indexed for execution precision. Does not delay clock-scheduled transitions. |
| **INV-FRAME-003** | "CT derives from frame index" | CT derivation within segment. Frame completion does not gate switch execution. |

---

## Rules Demoted to Diagnostic Goals

| Rule ID | Old Role | New Role | Superseded By |
|---------|----------|----------|---------------|
| **INV-SWITCH-READINESS** | Completion gate | Diagnostic goal | INV-SWITCH-DEADLINE-AUTHORITATIVE-001 |
| **INV-SWITCH-SUCCESSOR-EMISSION** | Completion gate | Diagnostic goal | INV-SWITCH-DEADLINE-AUTHORITATIVE-001 |

---

## New Invariants (Phase 11)

| Rule ID | Description | Phase |
|---------|-------------|-------|
| INV-BOUNDARY-TOLERANCE-001 | Grid transitions within 1 frame of boundary | 11B, 11D |
| INV-BOUNDARY-DECLARED-001 | legacy switch RPC carries `target_boundary_time_ms` | 11C |
| INV-AUDIO-SAMPLE-CONTINUITY-001 | No audio drops under backpressure | 11A |
| INV-SCHED-PLAN-BEFORE-EXEC-001 | Scheduling feasibility at planning time, not runtime | 11D |
| INV-STARTUP-BOUNDARY-FEASIBILITY-001 | First boundary must satisfy startup latency constraint | 11D |
| INV-SWITCH-ISSUANCE-DEADLINE-001 | Switch issuance deadline-scheduled, not cadence-detected | 11D |
| INV-CONTROL-NO-POLL-001 | No poll/retry for switch readiness | 11D, 11E |
| INV-SWITCH-DEADLINE-AUTHORITATIVE-001 | Switch at declared time regardless of readiness | 11D |
| INV-LEADTIME-MEASUREMENT-001 | Lead time evaluated using issuance timestamp | 11D |
| INV-SWITCH-ISSUANCE-TERMINAL-001 | Exception during issuance → FAILED_TERMINAL | 11F |
| INV-SWITCH-ISSUANCE-ONESHOT-001 | Exactly one issuance per boundary | 11F |
| INV-BOUNDARY-LIFECYCLE-001 | Unidirectional boundary state machine | 11F |
| INV-BOUNDARY-DECLARED-MATCHES-PLAN-001 | target_boundary_ms must match plan | 11F |

---

## Phase 11 Implementation Plan

| Phase | Goal | Dependencies | Risk | Est. Effort |
|-------|------|--------------|------|-------------|
| **11A** | Audio sample continuity | None | Low | 2-3 days |
| **11B** | Boundary timing observability | None | Very Low | 1-2 days |
| **11C** | Declarative boundary protocol (proto) | None | Medium | 2-3 days |
| **11D** | Deadline-authoritative switching | 11C | High | 5-7 days |
| **11E** | Prefeed timing contract | 11D | Medium | 3-4 days |
| **11F** | Boundary lifecycle hardening | 11E | Medium | 2-3 days |

### Phase Dependency Graph

```
Phase 11A (Audio Continuity)      ─────────────────────────────────┐
                                                                    │
Phase 11B (Observability)         ──────────────────────────────┐  │
                                                                 │  │
Phase 11C (Proto Change)          ─────────────────────────┐    │  │
                                                            │    │  │
                                                            v    v  v
Phase 11D (Deadline Enforcement)  ◄─────────────────────────────────┤
                                                                    │
Phase 11E (Prefeed Contract)      ◄─────────────────────────────────┤
                                                                    │
Phase 11F (Lifecycle Hardening)   ◄─────────────────────────────────┘
```

### Execution Order

1. **Parallel:** 11A + 11B + 11C (no dependencies between them)
2. **Sequential:** 11D (after 11C)
3. **Sequential:** 11E (after 11D)
4. **Sequential:** 11F (after 11E)

### Status

- **11A–11C:** Complete (2026-02-01)
- **11D:** Closed (2026-02-02)
- **11E:** Closed (2026-02-02)
- **11F:** Complete (2026-02-02)

---

## Document References

| Document | Relationship |
|----------|--------------|
| `docs/contracts/PHASE11.md` | **Architectural contract** (authority hierarchy, invariants, lifecycle; same style as PHASE12.md) |
| `docs/contracts/CANONICAL_RULE_LEDGER.md` | Authoritative rule definitions; Phase 11 task tables and audit history |
| `docs/contracts/PHASE11_TASKS.md` | Phase 11 atomic task list and checklists |
| `docs/contracts/tasks/phase11/README.md` | Phase 11 task index and structure |
| `docs/contracts/tasks/phase11/P11*.md` | Individual Phase 11 task specs |
