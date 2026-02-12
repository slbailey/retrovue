# Layer 2 - Phase 12 Live Session Authority & Teardown Invariants

**Status:** Canonical
**Scope:** Teardown semantics, live session authority, startup convergence
**Authority:** Refines Layer 0 Laws; builds on Phase 11 boundary lifecycle

---

## Phase 12 Invariants

| Rule ID | Classification | Owner | Enforcement | Test | Log |
|---------|---------------|-------|-------------|------|-----|
| **INV-TEARDOWN-STABLE-STATE-001** | CONTRACT | ChannelManager | RUNTIME | Yes | Yes |
| **INV-TEARDOWN-GRACE-TIMEOUT-001** | CONTRACT | ChannelManager | RUNTIME | Yes | Yes |
| **INV-TEARDOWN-NO-NEW-WORK-001** | CONTRACT | ChannelManager | RUNTIME | Yes | Yes |
| **INV-VIEWER-COUNT-ADVISORY-001** | CONTRACT | ChannelManager | RUNTIME | Yes | Yes |
| **INV-LIVE-SESSION-AUTHORITY-001** | CONTRACT | ChannelManager | RUNTIME | Yes | Yes |
| **INV-TERMINAL-SCHEDULER-HALT-001** | CONTRACT | ChannelManager | RUNTIME | Pending | Yes |
| **INV-TERMINAL-TIMER-CLEARED-001** | CONTRACT | ChannelManager | RUNTIME | Pending | Yes |
| **INV-SESSION-CREATION-UNGATED-001** | CONTRACT | ChannelManager | RUNTIME | Pending | Yes |
| **INV-STARTUP-CONVERGENCE-001** | CONTRACT | ChannelManager | RUNTIME | Pending | Yes |

### Definitions

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-TEARDOWN-STABLE-STATE-001 | Teardown deferred in transient states (PLANNED, PRELOAD_ISSUED, SWITCH_SCHEDULED, SWITCH_ISSUED); permitted in stable states (NONE, LIVE, FAILED_TERMINAL) |
| INV-TEARDOWN-GRACE-TIMEOUT-001 | Deferred teardown cannot wait indefinitely; grace timeout (10s) forces FAILED_TERMINAL |
| INV-TEARDOWN-NO-NEW-WORK-001 | No new boundary work scheduled when teardown is pending |
| INV-VIEWER-COUNT-ADVISORY-001 | Viewer count triggers but does not force teardown during transient states |
| INV-LIVE-SESSION-AUTHORITY-001 | Channel is durably live only when `_boundary_state == LIVE` |
| INV-TERMINAL-SCHEDULER-HALT-001 | FAILED_TERMINAL is intent-absorbing: no scheduling intent generated after terminal failure |
| INV-TERMINAL-TIMER-CLEARED-001 | Transient timers cancelled on FAILED_TERMINAL entry |
| INV-SESSION-CREATION-UNGATED-001 | Session creation not gated on boundary feasibility; viewer tune-in always creates session if resources available |
| INV-STARTUP-CONVERGENCE-001 | Infeasible boundaries skipped during startup convergence; session must converge within bounded window |

---

## Teardown Semantics

### Stable vs Transient States

| State | Category | Teardown Permitted |
|-------|----------|-------------------|
| NONE | Stable | Yes |
| PLANNED | Transient | No (defer) |
| PRELOAD_ISSUED | Transient | No (defer) |
| SWITCH_SCHEDULED | Transient | No (defer) |
| SWITCH_ISSUED | Transient | No (defer) |
| LIVE | Stable | Yes |
| FAILED_TERMINAL | Stable | Yes |

### Teardown Guard Logic

```python
def _request_teardown(self, reason: str) -> None:
    if self._boundary_state in STABLE_STATES:
        # Immediate teardown permitted
        self._execute_teardown(reason)
    else:
        # Defer until stable state reached
        self._teardown_pending = True
        self._teardown_reason = reason
        self._teardown_requested_at = datetime.now(timezone.utc)
```

### Grace Timeout Enforcement

If teardown is deferred in a transient state and the state does not become stable within `TEARDOWN_GRACE_TIMEOUT_SECONDS` (default: 10), the channel MUST transition to FAILED_TERMINAL:

```python
if self._teardown_pending:
    elapsed = (now - self._teardown_requested_at).total_seconds()
    if elapsed > TEARDOWN_GRACE_TIMEOUT_SECONDS:
        self._logger.error("INV-TEARDOWN-GRACE-TIMEOUT-001: Grace timeout exceeded")
        self._transition_boundary_state(BoundaryState.FAILED_TERMINAL)
```

---

## Terminal State Semantics

### FAILED_TERMINAL is Fully Absorbing

**Fully absorbing** = transition-absorbing + intent-absorbing

**Transition-absorbing:** Once in FAILED_TERMINAL, no transition can exit this state. All transitions to FAILED_TERMINAL are allowed; no transitions from FAILED_TERMINAL are allowed.

**Intent-absorbing:** No new scheduling intent may be generated in FAILED_TERMINAL state:
- No new boundaries planned
- No legacy preload RPC issued
- No legacy switch RPC scheduled
- No timer callbacks registered

**Allowed in FAILED_TERMINAL:**
- Health checks (channel is "up" but not "live")
- Metrics export
- Diagnostic log emission
- Resource cleanup

### Timer Clearing

On entry to FAILED_TERMINAL, all transient timers MUST be cancelled:
- Switch issuance timers
- Prefeed scheduling timers
- Any other boundary-related timers

This prevents ghost timer execution after terminal failure.

---

## Startup Convergence

### Problem Statement

At channel startup, a non-zero interval elapses between session creation and the moment the system can commit to a boundary. During this interval, some boundaries may have already passed.

### Terminology

| Term | Definition |
|------|------------|
| **Session Creation** | The act of creating a ChannelManager instance in response to viewer tune-in. Does NOT imply content is playing. |
| **Boundary Commitment** | The act of scheduling a specific boundary for execution. Requires feasibility (lead-time satisfied). |
| **Startup Convergence** | The window during which infeasible boundaries are skipped until a feasible one is found. |
| **Converged Session** | A session that has successfully committed to at least one boundary. |

### Convergence Rules

1. **Session creation is ungated:** A viewer tune-in ALWAYS creates a session if resources are available. Session creation NEVER fails due to boundary infeasibility.

2. **Infeasible boundaries are skipped:** During convergence, boundaries that cannot satisfy `lead_time >= MIN_PREFEED_LEAD_TIME` are logged and skipped, not fatal.

3. **Convergence has a timeout:** If no feasible boundary is found within `MAX_STARTUP_CONVERGENCE_WINDOW` (default: 30s), session enters FAILED_TERMINAL.

4. **Post-convergence feasibility is fatal:** After convergence, a boundary that cannot satisfy lead-time requirements is FATAL (per INV-SCHED-PLAN-BEFORE-EXEC-001).

### Amended: INV-STARTUP-BOUNDARY-FEASIBILITY-001

The first **committed** boundary MUST satisfy:
```
boundary_time >= station_utc + startup_latency + MIN_PREFEED_LEAD_TIME
```

This invariant applies to **boundary commitment**, not session creation. Pre-convergence infeasibility causes skip; post-convergence infeasibility is FATAL.

---

## Live Session Authority

### INV-LIVE-SESSION-AUTHORITY-001

**A channel is durably live only when `_boundary_state == LIVE`.**

The `is_live` property exposes this:
```python
@property
def is_live(self) -> bool:
    return self._boundary_state == BoundaryState.LIVE
```

Implications:
- Health checks report "up" in any state, "live" only in LIVE state
- External systems should not assume viewers are receiving content unless `is_live == True`
- FAILED_TERMINAL is "up" but not "live"

---

## Viewer Count and Teardown

### INV-VIEWER-COUNT-ADVISORY-001

**Viewer count triggers but does not force teardown during transient states.**

When viewer count drops to zero:
- If in stable state: immediate teardown
- If in transient state: `_teardown_pending = True` (wait for stable)

This prevents teardown from interrupting in-progress switches, which would cause encoder deadlocks and audio queue overflows.

---

## Derivation Notes

| Invariant | Derives From |
|-----------|--------------|
| INV-TEARDOWN-STABLE-STATE-001 | LAW-AUTHORITY-HIERARCHY, INV-BOUNDARY-LIFECYCLE-001 |
| INV-TEARDOWN-GRACE-TIMEOUT-001 | INV-TEARDOWN-STABLE-STATE-001 |
| INV-TEARDOWN-NO-NEW-WORK-001 | INV-TEARDOWN-STABLE-STATE-001 |
| INV-VIEWER-COUNT-ADVISORY-001 | LAW-AUTHORITY-HIERARCHY, INV-TEARDOWN-STABLE-STATE-001 |
| INV-LIVE-SESSION-AUTHORITY-001 | INV-BOUNDARY-LIFECYCLE-001 |
| INV-TERMINAL-SCHEDULER-HALT-001 | INV-BOUNDARY-LIFECYCLE-001, Phase 12 §7 |
| INV-TERMINAL-TIMER-CLEARED-001 | INV-TERMINAL-SCHEDULER-HALT-001 |
| INV-SESSION-CREATION-UNGATED-001 | LAW-AUTHORITY-HIERARCHY, Phase 12 §8 |
| INV-STARTUP-CONVERGENCE-001 | INV-SESSION-CREATION-UNGATED-001, Phase 12 §8 |

---

## Cross-References

- [BROADCAST_LAWS.md](../laws/BROADCAST_LAWS.md) - Layer 0 Laws
- [PHASE8_COORDINATION.md](./PHASE8_COORDINATION.md) - Boundary Lifecycle State Machine
- [PHASE10_FLOW_CONTROL.md](./PHASE10_FLOW_CONTROL.md) - Phase 10 Flow Control
- [CANONICAL_RULE_LEDGER.md](../CANONICAL_RULE_LEDGER.md) - Single source of truth
- [PHASE12.md](../PHASE12.md) - Full Phase 12 specification
