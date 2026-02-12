# Phase 11: Broadcast-Grade Timing Compliance

This phase implements invariants identified by the 2026-02-01 Systems Contract Audit to achieve broadcast-grade timing compliance.

## Foundational Principle: Authority Hierarchy

**LAW-AUTHORITY-HIERARCHY** (Supreme Law)

> Clock authority supersedes frame completion for switch execution.

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. Clock (LAW-CLOCK)        → WHEN transitions occur [AUTHORITY]│
│ 2. Frame (LAW-FRAME-EXEC)   → HOW precisely cuts happen [EXEC]  │
│ 3. Content (INV-SEGMENT-*)  → WHETHER sufficient [VALIDATION]   │
│                               (clock does NOT wait)             │
└─────────────────────────────────────────────────────────────────┘
```

**All Phase 11 work implements this hierarchy.** Code that inverts it (waiting for frame completion before clock-scheduled switch) is the root cause of the observed violations.

## Background

The audit identified gaps between current implementation and broadcast-grade requirements:
- Grid boundaries missed by >1 video frame
- Frame-accurate cuts occurring late relative to absolute boundary time
- Audio discontinuities from queue backpressure
- Control-plane logic using poll/retry instead of declarative intent

**Root Cause:** Frame-based rules were incorrectly treated as authority (decision-makers) rather than execution (precision mechanisms). This caused code to wait for frame completion before executing clock-scheduled transitions.

## Phase Structure

| Phase | Description | Tasks | Risk | Dependencies |
|-------|-------------|-------|------|--------------|
| 11A | Audio Sample Continuity | 5 | Low | None |
| 11B | Boundary Timing Observability | 6 | Very Low | None |
| 11C | Declarative Boundary Protocol | 5 | Medium | None |
| 11D | Deadline-Authoritative Switching | 12 | High | 11C |
| 11E | Prefeed Timing Contract | 5 | Medium | 11D |
| 11F | Boundary Lifecycle State Machine | 9 | Medium | 11E |

**Total: 42 tasks**

## Execution Order

Phases 11A, 11B, and 11C can proceed in parallel. Phase 11D requires 11C. Phase 11E requires 11D. Phase 11F requires 11E.

```
11A (Audio) ──────────────────────────────────────┐
11B (Observability) ──────────────────────────────┤
11C (Proto) ──────────────────────────────────────┼──► 11D (Enforcement) ──► 11E (Prefeed) ──► 11F (Lifecycle)
```

**Important Dependency Clarification:**

P11B-005 (baseline collection) and P11B-006 (analysis) are OPS tasks that:
- Do NOT block Phase 11D code implementation
- DO block production enablement of `use_deadline_authoritative_switch=true`

**Deployment Sequence:**
1. Implement all Phase 11D code (feature flag defaults OFF)
2. Deploy to production with flag OFF
3. Complete P11B-005: Collect 24h baseline metrics
4. Complete P11B-006: Analyze baseline, make GO/NO-GO recommendation
5. If GO → Enable feature flag in production
6. If NO-GO → Address identified issues first

## Task Index

### Phase 11A: Audio Sample Continuity

| Task | Type | Owner | Description |
|------|------|-------|-------------|
| [P11A-001](P11A-001.md) | AUDIT | AIR | Audit current audio queue behavior under backpressure |
| [P11A-002](P11A-002.md) | LOG | AIR | Add audio sample drop detection and logging |
| [P11A-003](P11A-003.md) | FIX | AIR | Implement audio queue overflow → producer throttle |
| [P11A-004](P11A-004.md) | TEST | AIR | Contract test: audio samples never dropped |
| [P11A-005](P11A-005.md) | FIX | AIR | Update backpressure invariant to include audio |

### Phase 11B: Boundary Timing Observability

| Task | Type | Owner | Description |
|------|------|-------|-------------|
| [P11B-001](P11B-001.md) | FIX | AIR | Add switch_completion_time_ms to response |
| [P11B-002](P11B-002.md) | LOG | AIR | Log boundary tolerance violations |
| [P11B-003](P11B-003.md) | METRICS | AIR | Add switch_boundary_delta_ms histogram |
| [P11B-004](P11B-004.md) | METRICS | AIR | Add switch_boundary_violations_total counter |
| [P11B-005](P11B-005.md) | OPS | Ops | Baseline current boundary timing |
| [P11B-006](P11B-006.md) | OPS | Ops | Analyze baseline timing data |

### Phase 11C: Declarative Boundary Protocol

| Task | Type | Owner | Description |
|------|------|-------|-------------|
| [P11C-001](P11C-001.md) | PROTO | Proto | Add target_boundary_time_ms to proto |
| [P11C-002](P11C-002.md) | BUILD | Build | Regenerate proto stubs |
| [P11C-003](P11C-003.md) | LOG | AIR | Parse and log target_boundary_time_ms |
| [P11C-004](P11C-004.md) | FIX | Core | Populate target_boundary_time_ms from schedule |
| [P11C-005](P11C-005.md) | TEST | Test | Integration test: target flows Core→AIR |

### Phase 11D: Deadline-Authoritative Switching — **Closed 2026-02-02**

| Task | Type | Owner | Description |
|------|------|-------|-------------|
| [P11D-001](P11D-001.md) | FIX | AIR | Schedule switch via MasterClock |
| [P11D-002](P11D-002.md) | FIX | AIR | Execute switch at deadline regardless of readiness |
| [P11D-003](P11D-003.md) | FIX | AIR | Use safety rails if not ready at deadline |
| [P11D-004](P11D-004.md) | FIX | AIR | Replace NOT_READY with PROTOCOL_VIOLATION |
| [P11D-005](P11D-005.md) | FIX | Core | Remove legacy switch RPC retry loop |
| [P11D-006](P11D-006.md) | FIX | Core | Ensure legacy preload RPC with sufficient lead time |
| [P11D-007](P11D-007.md) | TEST | Test | Contract test: switch within 1 frame of boundary |
| [P11D-008](P11D-008.md) | TEST | Test | Contract test: late prefeed → PROTOCOL_VIOLATION |
| [P11D-009](P11D-009.md) | FIX | Core | Enforce planning-time feasibility (INV-SCHED-PLAN-BEFORE-EXEC-001) |
| [P11D-010](P11D-010.md) | FIX | Core | Enforce startup boundary feasibility (INV-STARTUP-BOUNDARY-FEASIBILITY-001) |
| [P11D-011](P11D-011.md) | FIX | Core | Deadline-scheduled switch issuance (INV-SWITCH-ISSUANCE-DEADLINE-001) |
| [P11D-012](P11D-012.md) | FIX | Core+AIR | Lead-time measurement / delta logging (INV-LEADTIME-MEASUREMENT-001) |

### Phase 11E: Prefeed Timing Contract

| Task | Type | Owner | Description |
|------|------|-------|-------------|
| [P11E-001](P11E-001.md) | FIX | Core | Define MIN_PREFEED_LEAD_TIME_MS constant |
| [P11E-002](P11E-002.md) | FIX | Core | Issue legacy preload RPC at correct trigger time |
| [P11E-003](P11E-003.md) | LOG | Core | Log violations if lead time insufficient |
| [P11E-004](P11E-004.md) | METRICS | Core | Add prefeed_lead_time_ms histogram |
| [P11E-005](P11E-005.md) | TEST | Test | Contract test: all legacy preload RPC with sufficient lead time |

### Phase 11F: Boundary Lifecycle State Machine

| Task | Type | Owner | Description |
|------|------|-------|-------------|
| [P11F-001](P11F-001.md) | FIX | Core | Fix _MIN_PREFEED_LEAD_TIME_MS typo |
| [P11F-002](P11F-002.md) | FIX | Core | Add BoundaryState enum and transition enforcement |
| [P11F-003](P11F-003.md) | FIX | Core | Terminal exception handling in switch issuance |
| [P11F-004](P11F-004.md) | FIX | Core | One-shot guard to prevent duplicate issuance |
| [P11F-005](P11F-005.md) | FIX | Core | Replace threading.Timer with loop.call_later() |
| [P11F-006](P11F-006.md) | FIX | Core | Plan-boundary match validation |
| [P11F-007](P11F-007.md) | TEST | Test | Contract test: boundary lifecycle transitions |
| [P11F-008](P11F-008.md) | TEST | Test | Contract test: duplicate issuance suppression |
| [P11F-009](P11F-009.md) | TEST | Test | Contract test: terminal exception handling |

## New Invariants

| Invariant | Description |
|-----------|-------------|
| INV-BOUNDARY-TOLERANCE-001 | Grid transitions within 1 frame of boundary |
| INV-BOUNDARY-DECLARED-001 | legacy switch RPC carries target_boundary_time_ms |
| INV-AUDIO-SAMPLE-CONTINUITY-001 | No audio drops under backpressure |
| INV-SCHED-PLAN-BEFORE-EXEC-001 | Scheduling feasibility determined at planning time, not runtime |
| INV-STARTUP-BOUNDARY-FEASIBILITY-001 | First boundary must satisfy startup latency + MIN_PREFEED_LEAD_TIME |
| INV-SWITCH-ISSUANCE-DEADLINE-001 | Switch issuance deadline-scheduled, not cadence-detected |
| INV-CONTROL-NO-POLL-001 | No poll/retry for switch readiness |
| INV-SWITCH-DEADLINE-AUTHORITATIVE-001 | Switch at declared time regardless of readiness |
| INV-SWITCH-ISSUANCE-TERMINAL-001 | Exception during issuance → FAILED_TERMINAL (11F) |
| INV-SWITCH-ISSUANCE-ONESHOT-001 | Exactly one issuance per boundary (11F) |
| INV-BOUNDARY-LIFECYCLE-001 | Unidirectional boundary state machine (11F) |
| INV-BOUNDARY-DECLARED-MATCHES-PLAN-001 | target_boundary_ms must match plan (11F) |

## Rules Downgraded from Authority to Execution

| Rule | Old Interpretation | New Interpretation |
|------|-------------------|-------------------|
| LAW-FRAME-EXECUTION | "Frame index is execution authority" | Governs HOW cuts happen, not WHEN. Subordinate to LAW-CLOCK. |
| INV-FRAME-001 | "Boundaries are frame-indexed, not time-based" | Frame-indexed for execution precision. Does not delay clock-scheduled transitions. |
| INV-FRAME-003 | "CT derives from frame index" | CT derivation within segment. Frame completion does not gate switch execution. |

## Rules Demoted to Diagnostic Goals

| Rule | New Status | Reason |
|------|------------|--------|
| INV-SWITCH-READINESS | Diagnostic goal | Superseded by deadline-authoritative semantics |
| INV-SWITCH-SUCCESSOR-EMISSION | Diagnostic goal | Superseded by deadline-authoritative semantics |

## Reference

- [PHASE11.md](../../PHASE11.md) — **Architectural contract** (authority hierarchy, invariants, lifecycle; same style as PHASE12.md)
- [CANONICAL_RULE_LEDGER.md](../../CANONICAL_RULE_LEDGER.md) — Authoritative rule definitions
- [PHASE11_EXECUTION_PLAN.md](../../PHASE11_EXECUTION_PLAN.md) — Phase 11 execution plan (authority hierarchy, 11A–11F)
- [PHASE11_TASKS.md](../../PHASE11_TASKS.md) — Phase 11 task list and checklists
