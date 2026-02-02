<!--
      ╭────────────────────────────────────────────────────────────────────────────╮
      │            Phase 11 – Broadcast-Grade Timing & Authority Hierarchy         │
      ╰────────────────────────────────────────────────────────────────────────────╯
-->

> **Document Type:** _Architectural Contract_ &nbsp;&nbsp;
> **Status:** Complete (2026-02-02) &nbsp;&nbsp;
> **Law:** `LAW-AUTHORITY-HIERARCHY` &nbsp;&nbsp;
> **Prerequisites:** Phase 1 (Prevent Black/Silence), Phase 8 (Timeline Semantics)

---

## 1. Purpose

### 1.1 Why Phase 11 Existed

Phase 1 established liveness and content-before-pad guarantees. Phase 8 established timeline semantics and switch deadlines. A **2026-02-01 Systems Contract Audit** found that grid boundaries were still being missed by more than one frame and that control logic was using poll/retry instead of declarative intent.

_Phase 11 addressed this:_ It defined explicit **authority hierarchy**—clock decides WHEN transitions occur; frame rules govern HOW precisely cuts happen. It then implemented that hierarchy across Core and AIR (observability, proto, deadline enforcement, prefeed contract, boundary lifecycle).

### 1.2 What Class of Failures This Prevents

Without clock-authoritative timing and lifecycle discipline, you get:

- **Late switches**
  - Code waits for frame completion before executing switch
  - ➔ Grid boundaries missed by >1 frame; viewers see content drift

- **Poll/retry cascades**
  - Core retries SwitchToLive until "ready"; each retry shortens lead time
  - ➔ Negative lead time, PROTOCOL_VIOLATION, or retry into terminal failure

- **Authority contradiction**
  - Frame-based rules treated as authority (decision-makers) instead of execution (precision)
  - ➔ Undefined behavior when "frame not ready" vs "clock says switch now"

- **Audio drops under backpressure**
  - Video pacing dominates; audio queue overflows and drops samples
  - ➔ Audible glitches, PTS discontinuities

- **Duplicate or illegal boundary transitions**
  - Multiple issuance attempts per boundary; transitions out of terminal state
  - ➔ AIR confusion, resource leaks, undefined state

**Phase 11 eliminates these:**
It establishes LAW-AUTHORITY-HIERARCHY and implements it through 11A–11F (audio continuity, observability, declarative protocol, deadline enforcement, prefeed contract, boundary lifecycle state machine).

---

## 2. Terminology

<dl>
  <dt><b>Authority Hierarchy</b></dt>
  <dd>
    Explicit precedence: <b>Clock</b> decides WHEN transitions occur; <b>Frame</b> rules decide HOW precisely cuts happen; <b>Content</b> rules validate WHETHER sufficient—clock does not wait for content.
  </dd>
  <dt><b>Boundary</b></dt>
  <dd>
    Scheduled instant (wall time) at which playout switches from preview to live segment. Declared in protocol as <code>target_boundary_time_ms</code>.
  </dd>
  <dt><b>Boundary State</b></dt>
  <dd>
    Lifecycle position of a boundary in Core (ChannelManager). Progresses from PLANNED → PRELOAD_ISSUED → SWITCH_SCHEDULED → SWITCH_ISSUED → LIVE, or to FAILED_TERMINAL. See Phase 11F.
  </dd>
  <dt><b>Prefeed</b></dt>
  <dd>
    Core sends LoadPreview to AIR so successor segment is ready before the boundary. Lead time must be ≥ MIN_PREFEED_LEAD_TIME_MS (e.g. 5000 ms).
  </dd>
  <dt><b>Deadline-Authoritative Switch</b></dt>
  <dd>
    AIR executes switch at the declared boundary time regardless of readiness. If not ready, safety rails (pad/silence); clock is not delayed.
  </dd>
  <dt><b>FAILED_TERMINAL</b></dt>
  <dd>
    Absorbing boundary state: unrecoverable failure (illegal transition, issuance exception, duplicate issuance, plan mismatch). No further operations; teardown permitted.
  </dd>
  <dt><b>One-Shot Issuance</b></dt>
  <dd>
    SwitchToLive is issued exactly once per boundary. Duplicate attempts are suppressed; state machine enforces exactly-once semantics.
  </dd>
</dl>

---

## 3. Authority Hierarchy Model

**Who decides WHEN vs HOW in playout transitions?**

### 3.1 LAW-AUTHORITY-HIERARCHY

The audit resolved a contradiction between clock-based rules (LAW-CLOCK, LAW-SWITCHING) and frame-based rules (LAW-FRAME-EXECUTION, INV-FRAME-001, INV-FRAME-003) by making authority explicit:

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

### 3.2 Key Principle

If frame completion and clock deadline conflict, **clock wins**. Frame-based rules describe *how to execute* within a segment, not *whether to execute* a scheduled transition.

- **Anti-pattern (BUG):** Code that waits for frame completion before executing a clock-scheduled switch.
- **Correct pattern:** Schedule switch at clock time. If content isn't ready, use safety rails (pad/silence). Never delay the clock.

### 3.3 Rules Downgraded from Authority to Execution

| **Rule** | **Old Interpretation** | **New Interpretation** |
|----------|-------------------------|--------------------------|
| LAW-FRAME-EXECUTION | "Frame index is execution authority" | Governs HOW cuts happen, not WHEN. Subordinate to LAW-CLOCK. |
| INV-FRAME-001 | "Boundaries are frame-indexed, not time-based" | Frame-indexed for execution precision. Does not delay clock-scheduled transitions. |
| INV-FRAME-003 | "CT derives from frame index" | CT derivation within segment. Frame completion does not gate switch execution. |

### 3.4 Rules Demoted to Diagnostic Goals

| **Rule** | **Old Role** | **New Role** | **Superseded By** |
|----------|--------------|--------------|-------------------|
| INV-SWITCH-READINESS | Completion gate | Diagnostic goal | INV-SWITCH-DEADLINE-AUTHORITATIVE-001 |
| INV-SWITCH-SUCCESSOR-EMISSION | Completion gate | Diagnostic goal | INV-SWITCH-DEADLINE-AUTHORITATIVE-001 |

---

## 4. Phase 11 Structure (11A–11F)

Phase 11 was implemented in six sub-phases. Execution order: 11A, 11B, 11C in parallel; then 11D → 11E → 11F sequentially.

| **Phase** | **Goal** | **Dependencies** | **Deliverables** |
|-----------|----------|------------------|------------------|
| **11A** | Audio sample continuity | None | No audio drops under backpressure; throttle instead of drop |
| **11B** | Boundary timing observability | None | switch_completion_time_ms, metrics, violation logs |
| **11C** | Declarative boundary protocol | None | target_boundary_time_ms in SwitchToLiveRequest; Core populates, AIR parses |
| **11D** | Deadline-authoritative switching | 11C | AIR switches at deadline; Core no retry; feasibility at planning time |
| **11E** | Prefeed timing contract | 11D | MIN_PREFEED_LEAD_TIME_MS; LoadPreview at boundary − lead time; violation logging |
| **11F** | Boundary lifecycle state machine | 11E | BoundaryState enum; one-shot issuance; terminal exception → FAILED_TERMINAL; plan-boundary match |

---

## 5. Boundary State Classification (Phase 11F)

### 5.1 State Enumeration

| **State**           | **Description**                                      |
|---------------------|------------------------------------------------------|
| `NONE`              | No boundary planned; channel idle                    |
| `PLANNED`           | Boundary computed; LoadPreview scheduled             |
| `PRELOAD_ISSUED`    | LoadPreview sent to AIR                              |
| `SWITCH_SCHEDULED`  | Switch timer set, waiting for deadline                |
| `SWITCH_ISSUED`    | SwitchToLive sent to AIR                             |
| `LIVE`              | AIR confirms switch; output flowing                   |
| `FAILED_TERMINAL`   | Unrecoverable failure; no further operations         |

### 5.2 Allowed Transitions

Transitions are unidirectional and constrained by `_ALLOWED_BOUNDARY_TRANSITIONS`. Illegal transitions force `FAILED_TERMINAL`.

- NONE → PLANNED
- PLANNED → PRELOAD_ISSUED, FAILED_TERMINAL
- PRELOAD_ISSUED → SWITCH_SCHEDULED, FAILED_TERMINAL
- SWITCH_SCHEDULED → SWITCH_ISSUED, FAILED_TERMINAL
- SWITCH_ISSUED → LIVE, FAILED_TERMINAL
- LIVE → PLANNED, NONE
- FAILED_TERMINAL → (none; absorbing)

### 5.3 One-Shot and Terminal Semantics

- **One-shot:** At most one SwitchToLive issuance per boundary. Guard prevents duplicate issuance; tick early-returns for SWITCH_ISSUED / LIVE / FAILED_TERMINAL.
- **Terminal exception:** Any exception during switch issuance → boundary set to FAILED_TERMINAL; no retry.
- **Plan-boundary match:** target_boundary_ms at issuance must match plan-derived boundary; mismatch → FAILED_TERMINAL.

---

## 6. Core Invariants (Normative)

### 6.1 Timing & Protocol

| **Invariant** | **Definition** |
|---------------|----------------|
| **INV-BOUNDARY-DECLARED-001** | SwitchToLive carries target_boundary_time_ms (proto + Core population). |
| **INV-BOUNDARY-TOLERANCE-001** | Grid transitions within 1 frame of boundary (observability + enforcement in 11B/11D). |
| **INV-SWITCH-DEADLINE-AUTHORITATIVE-001** | AIR executes switch at declared time regardless of readiness; safety rails if not ready. |
| **INV-SWITCH-ISSUANCE-DEADLINE-001** | Switch issuance is deadline-scheduled, not cadence-detected; no poll/retry. |
| **INV-CONTROL-NO-POLL-001** | No poll/retry for switch readiness; planning-time feasibility only. |
| **INV-LEADTIME-MEASUREMENT-001** | Lead-time feasibility uses issuance timestamp; transport jitter must not affect feasibility. |

### 6.2 Planning & Feasibility

| **Invariant** | **Definition** |
|---------------|----------------|
| **INV-SCHED-PLAN-BEFORE-EXEC-001** | Scheduling feasibility determined at planning time, not runtime. |
| **INV-STARTUP-BOUNDARY-FEASIBILITY-001** | First boundary must satisfy startup latency + MIN_PREFEED_LEAD_TIME. |
| **INV-BOUNDARY-DECLARED-MATCHES-PLAN-001** | target_boundary_ms at issuance must equal plan-derived boundary. |

### 6.3 Lifecycle & Failure (Phase 11F)

| **Invariant** | **Definition** |
|---------------|----------------|
| **INV-BOUNDARY-LIFECYCLE-001** | Boundary state transitions are unidirectional; illegal transition → FAILED_TERMINAL. |
| **INV-SWITCH-ISSUANCE-ONESHOT-001** | SwitchToLive issued exactly once per boundary; duplicates suppressed or fatal. |
| **INV-SWITCH-ISSUANCE-TERMINAL-001** | Exception during switch issuance → FAILED_TERMINAL; no retry. |

### 6.4 Audio (Phase 11A)

| **Invariant** | **Definition** |
|---------------|----------------|
| **INV-AUDIO-SAMPLE-CONTINUITY-001** | No audio sample drops under backpressure; producer throttle, not drop. |

---

## 7. Failure Handling

### 7.1 FAILED_TERMINAL Definition

FAILED_TERMINAL is an _absorbing_ boundary state. Entry reasons include:

- Illegal state transition (invariant violation)
- Exception during switch issuance
- Duplicate issuance attempt (one-shot guard)
- Plan-boundary mismatch at issuance
- (Phase 12: grace timeout for deferred teardown)

### 7.2 FAILED_TERMINAL Properties

- **Absorbing:** no transitions out
- **Stable:** teardown permitted (Phase 12)
- **Diagnostic:** reason captured (e.g. _pending_fatal) for logging/ops

### 7.3 No Retry After Terminal

Core must not retry SwitchToLive for the same boundary after FAILED_TERMINAL. Tick must not re-arm issuance for that boundary. New boundary requires new plan and new state progression.

### 7.4 Why Poll/Retry Is Forbidden

Poll/retry for "ready then switch" causes:

- Shrinking lead time on each retry → negative lead time → PROTOCOL_VIOLATION
- Retry cascades after transient errors (e.g. NameError from typo) → same boundary issued repeatedly
- Authority inversion: readiness (frame/content) dictating when Core acts, instead of clock

**Deadline-scheduled issuance + one-shot + terminal exception** bounds the worst case: one attempt per boundary, then stable terminal state.

---

## 8. AIR Coordination _(Normative for Phase 11)_

### 8.1 Switch at Deadline

AIR schedules switch for target_boundary_time_ms (MasterClock). At that time, AIR executes switch even if readiness not achieved; uses safety rails (pad/silence) and logs violation if needed.

### 8.2 No NOT_READY Retry Path

AIR may return PROTOCOL_VIOLATION (e.g. insufficient lead time) instead of NOT_READY. Core treats such response as fatal for that boundary; no retry loop.

### 8.3 Response and Observability

- SwitchToLiveResponse includes switch_completion_time_ms (11B).
- Violations (e.g. >1 frame late) logged and reflected in metrics (switch_boundary_delta_ms, switch_boundary_violations_total).

---

## 9. Out-of-Scope

_Phase 11 does **not** address_:

- **9.1 Teardown semantics:** When to tear down a channel, deferred teardown, grace timeout → Phase 12.
- **9.2 Viewer-count interaction:** Viewer count vs time-authoritative playout during transient state → Phase 12.
- **9.3 Multi-channel orchestration:** Prioritization, resource sharing, cascading failure.
- **9.4 Operational tooling:** Dashboards for lead time, boundary violations, baseline analysis (P11B-005/006 are Ops tasks).
- **9.5 Phase 1 liveness:** Content-before-pad, starvation failsafe, sink gate → Phase 1.

---

## 10. Summary

_Phase 11 defined and implemented clock-authoritative, broadcast-grade timing:_

- **LAW-AUTHORITY-HIERARCHY:** Clock decides WHEN; frame rules decide HOW; content rules validate WHETHER—clock does not wait.
- **Declarative protocol:** target_boundary_time_ms flows Core → AIR; switch execution at that time.
- **No poll/retry:** Issuance deadline-scheduled; one-shot per boundary; exception → FAILED_TERMINAL.
- **Boundary lifecycle:** Unidirectional state machine (11F); illegal or duplicate transitions → FAILED_TERMINAL.
- **Prefeed contract:** LoadPreview at boundary − MIN_PREFEED_LEAD_TIME_MS; violation logged, not retried.

The _key insight_:  
Treating frame completion as authority caused late switches and retry cascades. Phase 11 subordinates frame rules to clock and enforces exactly-once, deadline-scheduled issuance with terminal failure semantics. Phase 12 then builds on this by defining when teardown is allowed relative to boundary state (stable vs transient).

**Phase 11 + Phase 8**  
= Full, rigorous specification for deadline-authoritative switching and boundary lifecycle.

<!-- End of pretty Phase 11 -->
