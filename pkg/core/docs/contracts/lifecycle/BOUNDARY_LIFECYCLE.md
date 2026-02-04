# Core Boundary Lifecycle Contracts

**Status:** Canonical
**Scope:** Boundary planning, issuance protocol, and lifecycle state management
**Authority:** Core owns boundary lifecycle; Protocol governs Core-AIR interface; AIR executes

**Ownership:** These are Core lifecycle and Protocol interface invariants. AIR does not define, plan, or manage boundary lifecycle states. AIR receives boundary declarations via Protocol and executes them.

---

## Protocol Invariants (Core-AIR Interface)

These invariants govern the Protocol interface between Core and AIR. Protocol owns the contract; both parties have obligations.

| Rule ID | Classification | Owner | Enforcement | Test | Log |
|---------|---------------|-------|-------------|------|-----|
| **INV-BOUNDARY-DECLARED-001** | PROTOCOL | Protocol (Core declares, AIR receives) | P8 | No | Yes |
| **INV-SWITCH-DEADLINE-AUTHORITATIVE-001** | PROTOCOL | Protocol (Core declares, AIR executes) | P8 | No | Yes |
| **INV-LEADTIME-MEASUREMENT-001** | PROTOCOL | Protocol (Core + AIR) | P8 | No | Yes |
| **INV-CONTROL-NO-POLL-001** | PROTOCOL | Protocol | RUNTIME | No | Yes |
| **INV-READINESS-SIGNAL-BOUNDARY-001** | PROTOCOL | Protocol (Core + AIR) | RUNTIME | No | No |

### Definitions

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-BOUNDARY-DECLARED-001 | SwitchToLive MUST include `target_boundary_time_ms` parameter; Core declares intent, AIR executes at that time |
| INV-SWITCH-DEADLINE-AUTHORITATIVE-001 | When `target_boundary_time_ms` is provided, AIR MUST execute the switch at that wall-clock time +/- 1 frame; internal readiness is AIR's responsibility. **Protocol declares; AIR obeys.** |
| INV-LEADTIME-MEASUREMENT-001 | Prefeed lead time MUST be evaluated using the issuance timestamp supplied by Core (`issued_at_time_ms`), not AIR receipt time. Transport jitter MUST NOT affect feasibility determination. |
| INV-CONTROL-NO-POLL-001 | Core MUST NOT poll AIR for switch readiness; NOT_READY indicates protocol error (prefeed too late), not a condition to retry. Tick-based reissuance is forbidden. |
| INV-READINESS-SIGNAL-BOUNDARY-001 | AIR's internal readiness signals (e.g., BOOTSTRAP-READY) may be exposed via Protocol so Core can decide LIVE state, but Core MUST NOT infer session existence or viewer presence from these signals. Readiness indicates "output pipeline can emit"; it does not mean "AIR exists" or "viewers are present." |

---

## Core Planning Invariants

These invariants govern how Core plans and validates boundaries before issuance. AIR does not see or validate these rules.

| Rule ID | Classification | Owner | Enforcement | Test | Log |
|---------|---------------|-------|-------------|------|-----|
| **INV-SCHED-PLAN-BEFORE-EXEC-001** | CONTRACT | Core | SCHEDULE-TIME | No | Yes |
| **INV-STARTUP-BOUNDARY-FEASIBILITY-001** | CONTRACT | Core | SCHEDULE-TIME | No | Yes |
| **INV-BOUNDARY-DECLARED-MATCHES-PLAN-001** | CONTRACT | ChannelManager | RUNTIME | No | Yes |

### Definitions

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-SCHED-PLAN-BEFORE-EXEC-001 | Scheduling feasibility MUST be determined once, at planning time. Only boundaries that are already feasible by construction may enter execution. Runtime MUST NOT discover, repair, delay, or re-evaluate boundary feasibility. |
| INV-STARTUP-BOUNDARY-FEASIBILITY-001 | The first scheduled boundary MUST satisfy `boundary_time >= station_utc + startup_latency + MIN_PREFEED_LEAD_TIME`. This is a constraint on schedule content, not on planning_time. |
| INV-BOUNDARY-DECLARED-MATCHES-PLAN-001 | target_boundary_ms sent to AIR MUST equal the boundary computed from the active playout plan, NOT a derived `now + X` value. |

---

## Core Issuance Invariants

These invariants govern how Core issues boundary commands. AIR receives commands; AIR does not manage issuance.

| Rule ID | Classification | Owner | Enforcement | Test | Log |
|---------|---------------|-------|-------------|------|-----|
| **INV-SWITCH-ISSUANCE-DEADLINE-001** | CONTRACT | Core | RUNTIME | No | Yes |
| **INV-SWITCH-ISSUANCE-TERMINAL-001** | CONTRACT | ChannelManager | RUNTIME | No | Yes |
| **INV-SWITCH-ISSUANCE-ONESHOT-001** | CONTRACT | ChannelManager | RUNTIME | No | Yes |

### Definitions

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-SWITCH-ISSUANCE-DEADLINE-001 | SwitchToLive issuance MUST be deadline-scheduled and issued no later than `boundary_time - MIN_PREFEED_LEAD_TIME`. Cadence-based detection, tick loops, and jitter padding are forbidden. |
| INV-SWITCH-ISSUANCE-TERMINAL-001 | Exception during SwitchToLive issuance MUST transition boundary to FAILED_TERMINAL state. No retry, no re-arm. |
| INV-SWITCH-ISSUANCE-ONESHOT-001 | SwitchToLive MUST be issued exactly once per boundary. Duplicate attempts are suppressed; duplicate into FAILED_TERMINAL is fatal. |

---

## Boundary Lifecycle State Machine

**Owner:** Core (ChannelManager)

This state machine describes Core's internal boundary tracking. AIR does not know or care about these states. AIR receives `SwitchToLive` commands with deadlines; AIR executes.

```
NONE -> PLANNED -> PRELOAD_ISSUED -> SWITCH_SCHEDULED -> SWITCH_ISSUED -> LIVE
                                                                          ^
Any state --------------------------------------------------------> FAILED_TERMINAL
```

### Allowed Transitions

| From | To |
|------|-----|
| NONE | PLANNED |
| PLANNED | PRELOAD_ISSUED, FAILED_TERMINAL |
| PRELOAD_ISSUED | SWITCH_SCHEDULED, FAILED_TERMINAL |
| SWITCH_SCHEDULED | SWITCH_ISSUED, FAILED_TERMINAL |
| SWITCH_ISSUED | LIVE, FAILED_TERMINAL |
| LIVE | NONE, PLANNED (next boundary) |
| FAILED_TERMINAL | (absorbing) |

### Terminal States

- `LIVE`: Success terminal for this boundary; next boundary can be planned
- `FAILED_TERMINAL`: Failure terminal; absorbing, no exit

---

## Boundary Lifecycle Invariant

| Rule ID | Classification | Owner | Enforcement | Test | Log |
|---------|---------------|-------|-------------|------|-----|
| **INV-BOUNDARY-LIFECYCLE-001** | CONTRACT | ChannelManager | RUNTIME | No | Yes |

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-BOUNDARY-LIFECYCLE-001 | Boundary state transitions MUST be unidirectional (NONE->PLANNED->...->LIVE or ->FAILED_TERMINAL). Illegal transitions force FAILED_TERMINAL. |

---

## Timing Tolerance (Split Ownership)

| Rule ID | Classification | Owner | Enforcement | Test | Log |
|---------|---------------|-------|-------------|------|-----|
| **INV-BOUNDARY-TOLERANCE-001** | CONTRACT | Protocol (Core + AIR) | P8 | No | Yes |

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-BOUNDARY-TOLERANCE-001 | Grid boundary transitions MUST complete within one video frame duration (33.33ms at 30fps) of the absolute scheduled boundary time. **Core declares boundary; AIR executes within tolerance.** |

---

## Cross-References

- [PHASE12_SESSION_TEARDOWN.md](./PHASE12_SESSION_TEARDOWN.md) - Session teardown lifecycle
- [PHASE8_COORDINATION.md](../../../../docs/contracts/coordination/PHASE8_COORDINATION.md) - AIR switch execution
- [INVARIANT_OWNERSHIP_AND_AUTHORITY.md](../../../../docs/architecture/INVARIANT_OWNERSHIP_AND_AUTHORITY.md) - Ownership boundaries
