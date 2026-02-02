# Phase 12 Atomic Task List

**Status:** Draft (In Progress)
**Source:** PHASE12_EXECUTION_PLAN.md; PHASE12.md
**Last Updated:** 2026-02-02

Phase 12 implements **live session authority and teardown semantics**. Task tracking and checklists live here. Phase 12 depends on Phase 11F (BoundaryState, state machine).

---

## Relationship to Other Phases

| Document | Scope |
|----------|--------|
| **PHASE11_TASKS.md** | Phase 11 (Boundary Lifecycle). Prerequisite; Phase 11F complete required. |
| **PHASE12_TASKS.md** | Phase 12 tasks (P12-CORE-*, P12-TEST-*). Live session authority & teardown. |
| **PHASE1_TASKS.md** | Phase 1 (Prevent Black/Silence). ✅ Complete; independent. |

---

## Phase 12 Task Summary

| Group | Tasks | Invariants |
|-------|-------|------------|
| **Core** | P12-CORE-001 through P12-CORE-007 | INV-TEARDOWN-STABLE-STATE-001, INV-TEARDOWN-GRACE-TIMEOUT-001, INV-TEARDOWN-NO-NEW-WORK-001, INV-LIVE-SESSION-AUTHORITY-001, INV-VIEWER-COUNT-ADVISORY-001 |
| **Test** | P12-TEST-001 through P12-TEST-006 | (Contract tests for above invariants) |

**Total Phase 12 tasks:** 13  
**Individual task specs:** `docs/contracts/tasks/phase12/P12-*.md`

---

## Phase 12 Core Checklist (Teardown & Lifecycle)

- [x] P12-CORE-001: Add teardown state fields (`_teardown_pending`, `_teardown_deadline`, `_teardown_reason`; `_STABLE_STATES`, `_TRANSIENT_STATES`)
- [x] P12-CORE-002: Implement `_request_teardown()` guard (defer if transient, execute if stable)
- [x] P12-CORE-003: Integrate deferred teardown into state transitions (execute when entering stable state)
- [x] P12-CORE-004: Add grace timeout enforcement to `tick()` (force FAILED_TERMINAL on expiry)
- [x] P12-CORE-005: Block new boundary work when `_teardown_pending` (no LoadPreview, SwitchToLive, or segment planning)
- [x] P12-CORE-006: Update ProgramDirector viewer disconnect handler (call teardown guard; advisory during transient)
- [x] P12-CORE-007: Add liveness query API (durably live only when `_boundary_state == LIVE`)

---

## Phase 12 Test Checklist (Contract Tests)

- [x] P12-TEST-001: Contract test: teardown blocked in transient states (INV-TEARDOWN-STABLE-STATE-001)
- [x] P12-TEST-002: Contract test: deferred teardown executes on LIVE (INV-TEARDOWN-STABLE-STATE-001)
- [x] P12-TEST-003: Contract test: grace timeout forces FAILED_TERMINAL (INV-TEARDOWN-GRACE-TIMEOUT-001)
- [x] P12-TEST-004: Contract test: no new work when teardown pending (INV-TEARDOWN-NO-NEW-WORK-001)
- [x] P12-TEST-005: Contract test: viewer disconnect defers during transition (INV-VIEWER-COUNT-ADVISORY-001)
- [x] P12-TEST-006: Contract test: liveness only reported in LIVE state (INV-LIVE-SESSION-AUTHORITY-001)

---

## Dependency Order

```
P12-CORE-001 (State fields)
      │
      ▼
P12-CORE-002 (_request_teardown guard)
      │
      ├──────────┬──────────┬──────────┐
      ▼          ▼          ▼          ▼
P12-CORE-003  P12-CORE-004  P12-CORE-005  P12-CORE-006
(Transition)  (Tick grace)  (Block work)  (ProgramDir)
      │          │          │          │
      ▼          ▼          ▼          ▼
P12-TEST-001  P12-TEST-003  P12-TEST-004  P12-TEST-005
P12-TEST-002

P12-CORE-001 ──► P12-CORE-007 ──► P12-TEST-006
```

**Recommended execution:** Complete P12-CORE-001, then P12-CORE-002; then P12-CORE-003 through P12-CORE-006 in parallel where possible; P12-CORE-007 can follow P12-CORE-001. Run contract tests after corresponding Core tasks.

---

## Task State Tracking

When completing a task:

1. Check the box in the checklist above
2. Add completion date and commit hash in the table below (when applicable)
3. Update PHASE12_EXECUTION_PLAN.md if rollout or exit criteria change

### Completed Tasks

| Task ID | Completed | Notes |
|---------|-----------|--------|
| P12-CORE-001 | 2025-02-02 | Teardown state fields, constants, stop_channel clear |
| P12-CORE-002 | 2025-02-02 | _request_teardown() guard |
| P12-CORE-003 | 2025-02-02 | _execute_deferred_teardown, trigger in _transition_boundary_state |
| P12-CORE-004 | 2025-02-02 | Grace timeout at start of tick() |
| P12-CORE-005 | 2025-02-02 | Skip boundary work when pending; _ensure_producer_running guard |
| P12-CORE-006 | 2025-02-02 | ProgramDirector _request_teardown + poll deferred_teardown_triggered |
| P12-CORE-007 | 2025-02-02 | is_live property (INV-LIVE-SESSION-AUTHORITY-001) |
| P12-TEST-001 | 2025-02-02 | test_channel_manager_teardown.py |
| P12-TEST-002 | 2025-02-02 | test_channel_manager_teardown.py |
| P12-TEST-003 | 2025-02-02 | test_channel_manager_teardown.py |
| P12-TEST-004 | 2025-02-02 | test_channel_manager_teardown.py |
| P12-TEST-005 | 2025-02-02 | test_channel_manager_teardown.py |
| P12-TEST-006 | 2025-02-02 | test_channel_manager_teardown.py (is_live) |

---

## Document References

| Document | Relationship |
|----------|--------------|
| `docs/contracts/PHASE12.md` | **Architectural contract** (lifecycle authority, teardown semantics, invariants) |
| `docs/contracts/PHASE12_EXECUTION_PLAN.md` | Phase 12 execution plan (strategy, task breakdown, rollout) |
| `docs/contracts/CANONICAL_RULE_LEDGER.md` | Authoritative rule definitions (Phase 12 invariants when added) |
| `docs/contracts/tasks/phase12/P12-*.md` | Individual task specs |
