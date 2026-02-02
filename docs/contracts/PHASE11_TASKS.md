# Phase 11 Atomic Task List

**Status:** Phase 11A–11F complete (2026-02-02)
**Source:** PHASE11_EXECUTION_PLAN.md; CANONICAL_RULE_LEDGER.md
**Last Updated:** 2026-02-02

Phase 11 is a **separate execution track** from Phase 1. Task tracking and checklists live here so Phase 11 can be paused or stopped independently.

---

## Relationship to Phase 1

| Document | Scope |
|----------|--------|
| **PHASE1_TASKS.md** | Phase 1 tasks (P1-PO-*, P1-EP-*, P1-MS-*, P1-PE-*, P1-FP-*). ✅ Complete. |
| **PHASE11_TASKS.md** | Phase 11 tasks (P11A–P11F). Separate track; can be stopped independently. |

---

## Phase 11 Task Summary

| Phase | Tasks | New Invariants |
|-------|-------|----------------|
| **11A** | P11A-001 through P11A-005 | INV-AUDIO-SAMPLE-CONTINUITY-001 |
| **11B** | P11B-001 through P11B-006 | INV-BOUNDARY-TOLERANCE-001 (observability) |
| **11C** | P11C-001 through P11C-005 | INV-BOUNDARY-DECLARED-001 |
| **11D** | P11D-001 through P11D-012 | INV-SWITCH-DEADLINE-AUTHORITATIVE-001, INV-CONTROL-NO-POLL-001, INV-SCHED-PLAN-BEFORE-EXEC-001, INV-STARTUP-BOUNDARY-FEASIBILITY-001, INV-SWITCH-ISSUANCE-DEADLINE-001, INV-LEADTIME-MEASUREMENT-001 (observability) |
| **11E** | P11E-001 through P11E-005 | (Core prefeed contract) |
| **11F** | P11F-001 through P11F-009 | INV-SWITCH-ISSUANCE-TERMINAL-001, INV-SWITCH-ISSUANCE-ONESHOT-001, INV-BOUNDARY-LIFECYCLE-001, INV-BOUNDARY-DECLARED-MATCHES-PLAN-001 |

**Total Phase 11 tasks:** 42  
**Individual task specs:** `docs/contracts/tasks/phase11/P11*.md`

---

## Phase 11A Checklist (Audio Sample Continuity) — Complete 2026-02-01

- [x] P11A-001: Audit audio queue behavior under backpressure
- [x] P11A-002: Add audio sample drop detection logging
- [x] P11A-003: Audio queue overflow → producer throttle (already implemented; logs added)
- [x] P11A-004: Contract test Phase11AudioContinuityTests.cpp
- [x] P11A-005: Phase10 TEST_INV_P10_BACKPRESSURE_SYMMETRIC_NoAudioDrops

---

## Phase 11B Checklist (Boundary Timing Observability) — Code complete 2026-02-01

- [x] P11B-001: switch_completion_time_ms in SwitchToLiveResponse
- [x] P11B-002: INV-BOUNDARY-TOLERANCE-001 violation/success logging
- [x] P11B-003: retrovue_switch_boundary_delta_ms histogram
- [x] P11B-004: retrovue_switch_boundary_violations_total counter
- [ ] P11B-005: OPS baseline 24h (deferred until deployment)
- [ ] P11B-006: OPS analysis (blocked by P11B-005)

---

## Phase 11C Checklist (Declarative Boundary Protocol) — Complete 2026-02-01

- [x] P11C-001: target_boundary_time_ms in SwitchToLiveRequest (proto)
- [x] P11C-002: Proto stubs regenerated (C++ and Python)
- [x] P11C-003: PlayoutEngine parse/log/store target_boundary_time_ms
- [x] P11C-004: Core ChannelManager populates target_boundary_time_ms
- [x] P11C-005: BoundaryDeclarationTests.TargetFlowsFromCoreToAir

---

## Phase 11D Checklist (Deadline-Authoritative Switching) — Closed 2026-02-02

- [x] P11D-001: AIR schedule switch via MasterClock
- [x] P11D-002: AIR execute switch at deadline regardless of readiness
- [x] P11D-003: AIR safety rails if not ready at deadline
- [x] P11D-004: AIR PROTOCOL_VIOLATION for insufficient lead time
- [x] P11D-005: Core remove SwitchToLive retry loop
- [x] P11D-006: Core LoadPreview with sufficient lead time
- [x] P11D-007: Contract test switch within 1 frame of boundary
- [x] P11D-008: Contract test late prefeed → PROTOCOL_VIOLATION
- [x] P11D-009: Core planning-time feasibility (INV-SCHED-PLAN-BEFORE-EXEC-001)
- [x] P11D-010: Core startup boundary feasibility (INV-STARTUP-BOUNDARY-FEASIBILITY-001)
- [x] P11D-011: Core deadline-scheduled switch issuance (INV-SWITCH-ISSUANCE-DEADLINE-001)
- [x] P11D-012: Core + AIR delta logging for lead-time / clock skew (INV-LEADTIME-MEASUREMENT-001 observability)

---

## Phase 11E Checklist (Prefeed Timing Contract) — Closed 2026-02-02

- [x] P11E-001: MIN_PREFEED_LEAD_TIME_MS constant (env RETROVUE_MIN_PREFEED_LEAD_TIME_MS)
- [x] P11E-002: Core issue LoadPreview at boundary_time - MIN_PREFEED_LEAD_TIME_MS
- [x] P11E-003: Core log violation if LoadPreview/SwitchToLive issued with &lt;MIN
- [x] P11E-004: Core metrics prefeed_lead_time_ms, switch_lead_time_ms, violations
- [x] P11E-005: Contract test prefeed/switch lead time

---

## Phase 11F Checklist (Boundary Lifecycle Hardening) — Complete 2026-02-02

- [x] P11F-001: Fix `_MIN_PREFEED_LEAD_TIME_MS` typo → `MIN_PREFEED_LEAD_TIME_MS` (Done 2026-02-02)
- [x] P11F-002: Add BoundaryState enum and transition enforcement (Done 2026-02-02)
- [x] P11F-003: Implement terminal exception handling in switch issuance (Done 2026-02-02)
- [x] P11F-004: Add one-shot guard to prevent duplicate issuance (Done 2026-02-02)
- [x] P11F-005: Replace threading.Timer with loop.call_later() (Done 2026-02-02)
- [x] P11F-006: Add plan-boundary match validation (Done 2026-02-02)
- [x] P11F-007: Contract test: boundary lifecycle transitions (Done 2026-02-02)
- [x] P11F-008: Contract test: duplicate issuance suppression (Done 2026-02-02)
- [x] P11F-009: Contract test: terminal exception handling (Done 2026-02-02)

---

## Document References

| Document | Relationship |
|----------|--------------|
| `docs/contracts/PHASE11.md` | **Architectural contract** (authority hierarchy, invariants, lifecycle; same style as PHASE12.md) |
| `docs/contracts/PHASE11_EXECUTION_PLAN.md` | Phase 11 execution plan and authority hierarchy |
| `docs/contracts/CANONICAL_RULE_LEDGER.md` | Authoritative rule definitions; Phase 11 task tables |
| `docs/contracts/tasks/phase11/README.md` | Phase 11 task index |
| `docs/contracts/tasks/phase11/P11*.md` | Individual task specs |
