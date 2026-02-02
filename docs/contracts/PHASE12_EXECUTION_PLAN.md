# Phase 12 Execution Plan: Live Session Authority & Teardown Semantics

**Document Type:** Implementation Plan
**Phase:** 12
**Owner:** Core Team
**Prerequisites:** Phase 11F complete (BoundaryState enum, state machine)
**Governing Document:** PHASE12.md

---

## 1. Execution Strategy

### 1.1 High-Level Approach

Phase 12 enforcement introduces **teardown deferral** as a first-class concept in the Core runtime. The implementation follows three principles:

1. **Guard, don't prevent:** Teardown requests are never rejected—they are either executed immediately (stable state) or deferred (transient state).

2. **State-driven decisions:** All teardown logic queries `_boundary_state` to determine permissibility. No timing heuristics or viewer-count thresholds.

3. **Bounded deferral:** Grace timeout ensures teardown eventually completes, even if boundary transition stalls.

### 1.2 Where Lifecycle Authority Is Checked

| Entry Point | Check Required | Action |
|-------------|----------------|--------|
| Viewer disconnect handler | `_boundary_state` stability | Defer or execute teardown |
| `tick()` loop | `_teardown_pending` flag | Skip new work; check grace timeout |
| `_transition_boundary_state()` | Entering stable state | Trigger deferred teardown |
| Operator stop command | `_boundary_state` stability | Same as viewer disconnect |

### 1.3 Deferred Teardown Coordination

```
Teardown Request
       │
       ▼
┌──────────────────┐
│ Check boundary   │
│ state stability  │
└────────┬─────────┘
         │
    ┌────┴────┐
    │         │
 Stable    Transient
    │         │
    ▼         ▼
Execute   Set _teardown_pending
 Now      Start grace timeout
          │
          ▼
    ┌─────────────────┐
    │ Wait for:       │
    │ • LIVE          │
    │ • FAILED_TERMINAL│
    │ • Grace timeout │
    └────────┬────────┘
             │
             ▼
       Execute Teardown
```

---

## 2. State & Data Model Changes

### 2.1 ChannelManager Additions

| Field | Type | Purpose | Invariant |
|-------|------|---------|-----------|
| `_teardown_pending` | `bool` | Teardown requested but deferred | INV-TEARDOWN-STABLE-STATE-001 |
| `_teardown_deadline` | `datetime | None` | Grace timeout expiration time | INV-TEARDOWN-GRACE-TIMEOUT-001 |
| `_teardown_reason` | `str | None` | Why teardown was requested (logging) | — |

### 2.2 Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `_TEARDOWN_GRACE_TIMEOUT` | `timedelta(seconds=10)` | Maximum deferral duration |
| `_STABLE_STATES` | `{NONE, LIVE, FAILED_TERMINAL}` | States permitting immediate teardown |
| `_TRANSIENT_STATES` | `{PLANNED, PRELOAD_ISSUED, SWITCH_SCHEDULED, SWITCH_ISSUED}` | States requiring deferral |

### 2.3 No Schema Changes Required

Phase 12 is purely runtime state. No database migrations or persistent storage changes.

---

## 3. Task Breakdown (Ordered)

| Task ID | Purpose | Files | Invariants | Blocked By |
|---------|---------|-------|------------|------------|
| P12-CORE-001 | Add teardown state fields | `channel_manager.py` | All | — |
| P12-CORE-002 | Implement `_request_teardown()` guard | `channel_manager.py` | INV-TEARDOWN-STABLE-STATE-001, INV-VIEWER-COUNT-ADVISORY-001 | P12-CORE-001 |
| P12-CORE-003 | Integrate deferred teardown into state transitions | `channel_manager.py` | INV-TEARDOWN-STABLE-STATE-001 | P12-CORE-002 |
| P12-CORE-004 | Add grace timeout enforcement to `tick()` | `channel_manager.py` | INV-TEARDOWN-GRACE-TIMEOUT-001 | P12-CORE-002 |
| P12-CORE-005 | Block new work when teardown pending | `channel_manager.py` | INV-TEARDOWN-NO-NEW-WORK-001 | P12-CORE-002 |
| P12-CORE-006 | Update ProgramDirector viewer disconnect handler | `program_director.py` | INV-VIEWER-COUNT-ADVISORY-001 | P12-CORE-002 |
| P12-CORE-007 | Add liveness query API | `channel_manager.py` | INV-LIVE-SESSION-AUTHORITY-001 | P12-CORE-001 |
| P12-TEST-001 | Contract test: teardown blocked in transient states | `test_channel_manager_teardown.py` | INV-TEARDOWN-STABLE-STATE-001 | P12-CORE-003 |
| P12-TEST-002 | Contract test: deferred teardown executes on LIVE | `test_channel_manager_teardown.py` | INV-TEARDOWN-STABLE-STATE-001 | P12-CORE-003 |
| P12-TEST-003 | Contract test: grace timeout forces FAILED_TERMINAL | `test_channel_manager_teardown.py` | INV-TEARDOWN-GRACE-TIMEOUT-001 | P12-CORE-004 |
| P12-TEST-004 | Contract test: no new work when teardown pending | `test_channel_manager_teardown.py` | INV-TEARDOWN-NO-NEW-WORK-001 | P12-CORE-005 |
| P12-TEST-005 | Contract test: viewer disconnect defers during transition | `test_channel_manager_teardown.py` | INV-VIEWER-COUNT-ADVISORY-001 | P12-CORE-006 |
| P12-TEST-006 | Contract test: liveness only reported in LIVE state | `test_channel_manager_teardown.py` | INV-LIVE-SESSION-AUTHORITY-001 | P12-CORE-007 |
| **Terminal Semantics Amendment (2026-02)** ||||
| P12-CORE-008 | Add FAILED_TERMINAL check to halt scheduling intent | `channel_manager.py` | INV-TERMINAL-SCHEDULER-HALT-001 | P12-CORE-005 |
| P12-CORE-009 | Cancel transient timers on FAILED_TERMINAL entry | `channel_manager.py` | INV-TERMINAL-TIMER-CLEARED-001 | P12-CORE-008 |
| P12-TEST-007 | Contract test: scheduler halts in FAILED_TERMINAL | `test_channel_manager_teardown.py` | INV-TERMINAL-SCHEDULER-HALT-001 | P12-CORE-008 |
| P12-TEST-008 | Contract test: timers cancelled on FAILED_TERMINAL | `test_channel_manager_teardown.py` | INV-TERMINAL-TIMER-CLEARED-001 | P12-CORE-009 |

### 3.1 Dependency Graph

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

                    ┌──────────────────────┐
                    │  Terminal Semantics  │
                    │  Amendment (2026-02) │
                    └──────────────────────┘
                              │
P12-CORE-005 ──► P12-CORE-008 ──► P12-CORE-009
                (Scheduler halt)  (Timer clear)
                      │                │
                      ▼                ▼
                P12-TEST-007     P12-TEST-008
```

---

## 4. Rollout & Safety Plan

### 4.1 Deployment Strategy

**Phased rollout:**

1. **Phase A:** Deploy with feature flag disabled (code in place, not active)
2. **Phase B:** Enable on test channels only (via config)
3. **Phase C:** Enable globally with enhanced logging
4. **Phase D:** Remove feature flag; Phase 12 is default behavior

### 4.2 Required Logging

| Log Level | Event | Content |
|-----------|-------|---------|
| INFO | Teardown deferred | Channel ID, current state, reason, deadline |
| INFO | Deferred teardown executing | Channel ID, triggering state, time deferred |
| WARNING | Grace timeout expired | Channel ID, stuck state, time waited |
| ERROR | Teardown during transient (pre-fix code path) | Channel ID, state (should never appear post-fix) |

### 4.3 Metrics

| Metric | Type | Purpose |
|--------|------|---------|
| `retrovue_teardown_deferred_total` | Counter | How often teardown is deferred |
| `retrovue_teardown_immediate_total` | Counter | How often teardown proceeds immediately |
| `retrovue_teardown_grace_timeout_total` | Counter | How often grace timeout forces termination |
| `retrovue_teardown_deferred_duration_seconds` | Histogram | How long deferrals last |

### 4.4 Regression Detection

**Indicators of regression:**
- `teardown_grace_timeout_total` increasing unexpectedly (transitions hanging)
- `teardown_deferred_duration_seconds` P99 approaching grace timeout
- AIR logs showing "orphaned" or encoder deadlock patterns
- Audio queue overflow logs in AIR after viewer disconnect

**Automated checks:**
- Contract tests in CI (CT-P12-001 through CT-P12-010)
- Integration test: disconnect viewer during `SWITCH_ISSUED`, verify no AIR deadlock

---

## 5. Explicit Non-Goals

Phase 12 execution plan **does not** address:

| Non-Goal | Rationale |
|----------|-----------|
| AIR-side drain command | Non-normative per PHASE12.md §8.2 |
| AIR-side teardown acknowledgement | Non-normative per PHASE12.md §8.3 |
| Viewer reconnect canceling deferral | Future consideration; not in Phase 12 scope |
| Multi-channel teardown coordination | Out of scope per PHASE12.md §9.3 |
| Operator visibility into deferred teardowns | Operational tooling; out of scope per PHASE12.md §9.5 |
| Configurable grace timeout | Default (10s) is sufficient; configurability is optimization |
| Phase 8 timing changes | Explicitly forbidden by constraints |
| Weakening invariants for edge cases | Explicitly forbidden by constraints |

---

## 6. Summary

| Metric | Value |
|--------|-------|
| Core implementation tasks | 9 |
| Contract tests | 8 (minimum) |
| New runtime state fields | 3 |
| Invariants enforced | 7 |

**Critical path:** P12-CORE-001 → P12-CORE-002 → P12-CORE-003 (enables deferred teardown) → P12-TEST-001/002 (validates correctness)

**Terminal semantics path:** P12-CORE-005 → P12-CORE-008 (scheduler halt) → P12-CORE-009 (timer clear) → P12-TEST-007/008 (validates absorbing properties)

**Exit criteria:** All contract tests pass; no teardown during transient states observable in logs; no AIR orphanment incidents; no scheduling intent after FAILED_TERMINAL; no ghost timer callbacks.

---

## 7. Document References

| Document | Relationship |
|----------|--------------|
| `docs/contracts/PHASE12.md` | Governing architectural contract (lifecycle authority, teardown semantics) |
| `docs/contracts/PHASE12_TASKS.md` | Phase 12 atomic task list and checklists |
| `docs/contracts/tasks/phase12/P12-*.md` | Individual task specs |
