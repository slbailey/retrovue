<!--
      ╭────────────────────────────────────────────────────────────────────────────╮
      │                Phase 12 – Live Session Authority & Teardown Semantics      │
      ╰────────────────────────────────────────────────────────────────────────────╯
-->

> **Document Type:** _Architectural Contract_ &nbsp;&nbsp; 
> **Status:** Draft &nbsp;&nbsp;
> **Law:** `LAW-AUTHORITY-HIERARCHY` &nbsp;&nbsp;
> **Prerequisites:** Phase 8 (Timeline Semantics), Phase 11F (Boundary Lifecycle State Machine)

---

## 1. Purpose

### 1.1 Why Phase 12 Exists

Phase 8 establishes clock authority over frame completion for switch execution.
Phase 11F defines the boundary lifecycle state machine. But **when is a channel durably live—and who ends its session?**

_Phase 12 answers this:_ It defines explicit lifecycle authority—rules for creating, sustaining, destroying a live playout session, and who controls those moments.

### 1.2 What Class of Failures This Prevents

Without clear lifecycle authority, you get:

- **Premature teardown**
  - Core destroys the channel while AIR is mid-transition
  - ➔ AIR orphaned, encoder deadlocks, resources exhausted

- **Authority ambiguity**
  - Viewer-driven teardown vs. time-authoritative playout
  - ➔ Conflict, no precedence

- **Zombie sessions**
  - Channel "live" after terminal failure, still using resources

- **Undefined recovery**
  - Teardown during transient state undefined—everyone guesses, implementations diverge

**Phase 12 eliminates these:**
It sets clear rules for lifecycle transitions and teardown.

---

## 2. Terminology

<dl>
  <dt><b>Live Session</b></dt>
  <dd>
    Interval when AIR is producing playout output. Begins with AIR-confirmed switch to live content, ends with Core-issued, AIR-acknowledged teardown. At most one at a time.
  </dd>
  <dt><b>Boundary State</b></dt>
  <dd>
    Lifecycle position of scheduled content boundary. Owned by Core. Progresses from planning through confirmed live. See Phase 11F.
  </dd>
  <dt><b>Stable vs Transient State</b></dt>
  <dd>
    <b>Stable:</b> No time-critical ops pending, system quiescent. Teardown permitted.<br>
    <b>Transient:</b> Time-critical ops running; system mid-transition. Teardown forbidden.
  </dd>
  <dt><b>Terminal Failure</b></dt>
  <dd>
    Unrecoverable error; boundary enters <code>FAILED_TERMINAL</code>. No further operations. Still considered a stable state for teardown.
  </dd>
  <dt><b>Teardown</b></dt>
  <dd>
    Orderly destruction of channel resources (Core's manager, AIR comms, playout pipeline). Not instantaneous—a negotiated lifecycle event.
  </dd>
  <dt><b>Scheduling Intent</b></dt>
  <dd>
    Any operation that (a) allocates resources for future boundary work, (b) sends control-plane RPCs to AIR, (c) registers timers for boundary lifecycle operations, or (d) would require a boundary state transition to complete. Examples: LoadPreview, SwitchToLive, segment planning.
  </dd>
</dl>

---

## 3. Lifecycle Authority Model

**Who holds power, and when, in the channel lifecycle?**

### 3.1 Authority Assignment

| **Lifecycle Stage**   | **Authority** | **Rationale**                                                      |
|-----------------------|---------------|---------------------------------------------------------------------|
| Channel existence     | Core          | Persistent domain object                                            |
| Session creation      | Core          | Core decides when to spawn AIR                                      |
| Preview loading       | Core          | Controls what to preview, when                                      |
| Switch arming         | Core          | Computes boundaries, issues switch                                  |
| Switch execution      | AIR           | Owns real-time frame pacing; switch on AIR clock                    |
| Live confirmation     | AIR           | Only AIR knows when output flows                                    |
| Teardown initiation   | Core          | Controls viewer lifecycle, resources                                |
| Teardown execution    | Shared        | Core requests, AIR acknowledges, then Core destroys                 |

### 3.2 Authority Transitions

Authority doesn't flip instantly. Between Core issuing a command and AIR confirming completion:

- **Core**: authority over _should_ the op proceed (can cancel)
- **AIR**: authority on _when/how_ the op is executed

This "shared authority" window defines the _transient state_. **Teardown here is forbidden** (Core must wait for AIR).

### 3.3 The Viewer-Count Paradox

- Viewer count is a Core-side metric (HTTP clients)
- Phase 8: playout starts with viewers, stops when zero viewers.  
- **But**: tear down immediately (viewer model) vs. honoring exact switch deadlines (time-authoritative model)

_Phase 12's solution:_  
**Viewer count is advisory during transient states.**  
Viewer count controls session start/end, but never interrupts an in-progress boundary transition.

---

## 4. Boundary State Classification

### 4.1 State Enumeration

| **State**         | **Description**                                      |
|-------------------|------------------------------------------------------|
| `NONE`            | No boundary planned; channel idle                    |
| `PLANNED`         | Boundary computed; `LoadPreview` scheduled           |
| `PRELOAD_ISSUED`  | `LoadPreview` sent to AIR                            |
| `SWITCH_SCHEDULED`| Switch timer set, waiting for deadline               |
| `SWITCH_ISSUED`   | `SwitchToLive` sent to AIR                           |
| `LIVE`            | AIR confirms switch; output flowing                  |
| `FAILED_TERMINAL` | Unrecoverable failure; session is dead               |

### 4.2 State Classification

| **State**        | **Classification** | **Teardown Permitted** |
|------------------|-------------------|------------------------|
| `NONE`           | Stable            | ✔️ Yes                 |
| `PLANNED`        | Transient         | ❌ No                  |
| `PRELOAD_ISSUED` | Transient         | ❌ No                  |
| `SWITCH_SCHEDULED`| Transient        | ❌ No                  |
| `SWITCH_ISSUED`  | Transient         | ❌ No                  |
| `LIVE`           | Stable            | ✔️ Yes                 |
| `FAILED_TERMINAL`| Stable            | ✔️ Yes                 |

> **Terminal Failure Semantics:** `FAILED_TERMINAL` is not merely "stable for teardown"—it is the **end of the boundary's lifecycle**. No scheduling intent is valid after entering `FAILED_TERMINAL`. The boundary is dead; only teardown and observability may proceed. See §7 for full terminal semantics.

### 4.3 Why Teardown Is Forbidden in Transient States

Transient states = in-flight, fragile operations:
- **Allocated, not-yet-stable resources** (decoders/buffers, timing)
- **Active comms** (channel torn mid-exchange = AIR can't confirm/abort)
- **Time-critical deadlines** (switch may be missed, or fire into dead air)
- **Backpressure dependencies** (loss of output sink = pipeline jam/deadlock)

Supporting teardown in these states would require full mid-op cancellation support—**unnecessary complexity for zero real benefit**.  
**Correct: Forbid teardown in transient states.**

---

## 5. Teardown Semantics

Boundary state is the authoritative proxy for lifecycle stability in Phase 12.

### 5.1 Teardown as Negotiated Event

Teardown is **phased**, not instant:

1. **Request**: Core decides teardown needed (eg. 0 viewers)
2. **Evaluation**: Core checks if teardown allowed _now_
3. **Deferral/Execution**: Proceed if allowed, else queue request
4. **Coordination**: Core signals AIR to drain/stop
5. **Acknowledgement**: AIR confirms shutdown complete
6. **Destruction**: Core destroys local resources

**Net effect:** Both components always reach a consistent "stopped" state.

### 5.2 Teardown Request Deferral

Teardown **MUST be deferred** if:

- `_boundary_state` is any _transient state_: [`PLANNED`, `PRELOAD_ISSUED`, `SWITCH_SCHEDULED`, `SWITCH_ISSUED`]

Deferral means:

- Record request (`_teardown_pending = True`)
- Start grace timeout
- Do not schedule new boundary work
- Execute teardown when a stable state is reached

### 5.3 Teardown Permission

Teardown **MAY proceed immediately** if:

- `_boundary_state` is `NONE`, `LIVE`, or `FAILED_TERMINAL`

Here, nothing in flight—destruction is safe.

### 5.4 Teardown Triggers

**May trigger teardown request:**
- Viewer count = 0
- Operator command (e.g. `retrovue channel stop`)
- Unrecoverable scheduling error
- Grace timeout expiration (deferred teardown)

**Must _not_ trigger immediate teardown:**
- Viewer count drops to 0 _during transient state_
- Network blips to AIR (should retry)
- Non-fatal playout warnings

---

## 6. **Core Invariants** (Normative)

### 6.1 `INV-TEARDOWN-STABLE-STATE-001`

- **Definition:**  
  Teardown due to viewer inactivity must be deferred until `_boundary_state` is stable. _Never execute teardown in a transient state._
- **Stable states:** `NONE`, `LIVE`, `FAILED_TERMINAL`
- **Transient states:** `PLANNED`, `PRELOAD_ISSUED`, `SWITCH_SCHEDULED`, `SWITCH_ISSUED`
- **Enforcement:**  
  Core checks `_boundary_state` before teardown. If transient, sets `_teardown_pending`, defers until stable or grace timeout.

### 6.2 `INV-TEARDOWN-GRACE-TIMEOUT-001`

- **Definition:**  
  Deferred teardown can't wait forever.  
  **Grace timeout** (default: 10s) is enforced.  
  If elapsed while still transient, boundary forced to `FAILED_TERMINAL` before teardown.
- **Rationale:**  
  Prevents zombie channels/resource leaks.

### 6.3 `INV-TEARDOWN-NO-NEW-WORK-001`

- **Definition:**
  With `_teardown_pending`, Core must not schedule new boundary work: _no new_ `LoadPreview`, `SwitchToLive`, or segment planning.
- **Rationale:**
  New work would prolong transient, defeating teardown deferral.
- **Relationship:**
  This invariant addresses teardown lifecycle (`_teardown_pending`). For scheduler halt after terminal failure, see `INV-TERMINAL-SCHEDULER-HALT-001`. Both conditions independently block new work; both MUST be checked.

### 6.4 `INV-LIVE-SESSION-AUTHORITY-001`

- **Definition:**  
  A channel is _durably live_ only when `_boundary_state == LIVE`.  
  Before LIVE, session is provisional and may fail. Only after LIVE is it stable and only ended explicitly or by terminal failure.  
  Any component behavior that assumes sustained output MUST be gated on LIVE.
- **Rationale:**  
  "Channel is live" features must not assume liveness during transient states; overlays, guide UX, and metrics are downstream consumers that depend on this gate.

### 6.5 `INV-VIEWER-COUNT-ADVISORY-001`

- **Definition:**
  Viewer count is _advisory_, not authoritative, for teardown during transient states.
  Zero viewers must **trigger** (not force) teardown request.
- **Rationale:**
  Viewer count is Core-only metric—does not account for AIR's in-flight ops.

### 6.6 `INV-TERMINAL-SCHEDULER-HALT-001`

- **Definition:**
  Once `_boundary_state == FAILED_TERMINAL`, Core MUST NOT generate new **scheduling intent**.
- **Scheduling intent** is any operation that:
  1. Allocates resources for future boundary work (e.g., preview buffers)
  2. Sends control-plane RPCs to AIR (e.g., LoadPreview, SwitchToLive)
  3. Registers timers for boundary lifecycle operations
  4. Would require a boundary state transition to complete
- **Explicitly allowed in `FAILED_TERMINAL`:**
  - Health check evaluation and reporting
  - Metrics collection and export
  - Diagnostic state reads
  - Logging
  - Teardown coordination
- **Enforcement:**
  All scheduling entry points (`tick()`, explicit plan methods) MUST check for `FAILED_TERMINAL` and return early before evaluating boundary logic. This check is independent of `_teardown_pending`.
- **Rationale:**
  `FAILED_TERMINAL` means the session is dead. Scheduling intent is meaningless without a live boundary. Continuing to generate intent wastes resources, produces spurious log errors, and contradicts the semantic meaning of "unrecoverable failure."

### 6.7 `INV-TERMINAL-TIMER-CLEARED-001`

- **Definition:**
  Upon transition to `FAILED_TERMINAL`, all pending transient operation timers MUST be cancelled immediately. This includes:
  - Switch issuance timers (`_switch_handle`)
  - LoadPreview scheduling timers
  - Any deadline-scheduled boundary callbacks
- **Enforcement:**
  `_transition_boundary_state()` MUST cancel all transient timers when `new_state == FAILED_TERMINAL`.
- **Rationale:**
  Ghost timers firing after terminal failure generate spurious errors and may attempt operations against a dead boundary. Clearing timers on terminal entry ensures clean shutdown semantics.

---

## 7. Failure Handling

### 7.0 Absorbing Properties (Canonical Terminology)

`FAILED_TERMINAL` is the only **fully absorbing** state in the boundary lifecycle:

| Property | Scope | Invariant | Meaning |
|----------|-------|-----------|---------|
| **Transition-absorbing** | State machine | INV-BOUNDARY-LIFECYCLE-001 | No state transitions out |
| **Intent-absorbing** | Scheduler | INV-TERMINAL-SCHEDULER-HALT-001 | No scheduling intent may be generated |
| **Timer-cleared** | Transient ops | INV-TERMINAL-TIMER-CLEARED-001 | All pending timers cancelled on entry |

A state that is both transition-absorbing and intent-absorbing is called **fully absorbing**.

### 7.1 `FAILED_TERMINAL` Definition

`FAILED_TERMINAL` is a fully absorbing boundary state indicating unrecoverable failure. Once entered:

- **Transition-absorbing:** No boundary state transitions are permitted (INV-BOUNDARY-LIFECYCLE-001)
- **Intent-absorbing:** No scheduling intent may be generated (INV-TERMINAL-SCHEDULER-HALT-001)
- **Timer-cleared:** All transient operation timers are cancelled (INV-TERMINAL-TIMER-CLEARED-001)

**Transition reasons:**
- Illegal state transition (per invariant violations)
- Switch issuance exception
- Duplicate command into terminal state
- Boundary mismatch
- Grace timeout expiry

### 7.2 `FAILED_TERMINAL` Properties

| Property | Meaning |
|----------|---------|
| **Transition-absorbing** | No transitions out (INV-BOUNDARY-LIFECYCLE-001) |
| **Intent-absorbing** | No scheduling intent may be generated (INV-TERMINAL-SCHEDULER-HALT-001) |
| **Timer-cleared** | Transient timers cancelled on entry (INV-TERMINAL-TIMER-CLEARED-001) |
| **Stable** | Teardown permitted |
| **Observable** | Health checks, metrics, diagnostics allowed |
| **Diagnostic** | `_pending_fatal` contains failure reason |

**Valid operations in `FAILED_TERMINAL`:**
- Teardown coordination and resource cleanup
- Health check reporting
- Metrics export
- Diagnostic state reads
- Logging

### 7.3 Grace Timeout Behavior

When a deferred teardown's grace timeout expires:

1. Core logs the stuck state
2. `_boundary_state` → `FAILED_TERMINAL`
3. `_pending_fatal` = timeout cause
4. This stable state triggers deferred teardown
5. Teardown proceeds as normal

### 7.4 Why Indefinite Waiting Is Forbidden

Indefinitely deferred teardown causes:

- Resource exhaustion: memory, FDs, threads
- Zombie channels: seen as "live" but outputless
- Cascade failures: other channels block
- Operator confusion: apparent deadlock

**Grace timeout bounds the worst case:** 
_Teardown may be 10s late, but never waits forever._

---

## 8. AIR Coordination _(Non-Normative)_

Optional AIR-side best practices (not required, but valuable):

### 8.1 Output Established Ack

- AIR may explicitly report when output is _reliably_ flowing
- Core can use this to set `LIVE` with greater confidence

_Without this: Core can only infer `LIVE` after SwitchToLive completes._

### 8.2 Drain Command

AIR may implement “drain”:

1. Stop accepting new frames
2. Flush in-flight frames through encoder
3. Write buffered output
4. Signal Core on completion

This ensures graceful teardown (last frames delivered, not dropped).  
_No drain: teardown is abrupt but still correct._

### 8.3 Teardown Ack

AIR may acknowledge teardown, letting Core confirm AIR released all resources (e.g., files, sockets).  
Without ack: Core uses timeouts.

---

## 9. Out-of-Scope

_Phase 12 does **not** address_:

- **9.1 Implementation details:**  
  Timeout durations (10s is default, not spec), buffer sizes, threading, error-retry logic

- **9.2 Phase 8 timing:**  
  Epochs, CT/MT mapping, switch deadlines, prefeed time

- **9.3 Multi-channel:**  
  Channel prioritization, cascading teardown, resource sharing

- **9.4 Viewer experience during transient state:**  
  What viewers see (e.g., cached content, client timeout behavior)

- **9.5 Operational tooling:**  
  Monitoring/stats around deferred teardowns, grace timeouts, manual overrides

---

## 10. ✨ Summary

_Phase 12 defines who is in charge, and when:_

- **Core:** controls session existence, initiates teardown
- **AIR:** controls switch execution and live confirmation
- **Teardown:** forbidden in transient states &rarr; always deferred

The _key insight_:  
Viewer count alone cannot interrupt time-authoritative playout. Scheduled transitions must be allowed to complete or fail terminally before teardown. This ensures encoder correctness, prevents resource leaks, and keeps system states well-defined.

**Phase 12 + Phase 8**  
= Full, rigorous specification for live playout session management.

<!-- End of pretty Phase 12 -->
