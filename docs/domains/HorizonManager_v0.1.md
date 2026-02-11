# Horizon Manager — v0.1

**Status:** Domain Model
**Version:** 0.1

**Classification:** Coordination (Cross-layer policy enforcement)
**Authority Level:** Core runtime orchestration
**Governs:** Horizon depth enforcement, lock window progression, eviction policy
**Out of Scope:** Episode selection, segmentation logic, AIR execution, frame timing

---

## 1. Purpose

HorizonManager is a wall-clock-driven policy enforcer responsible for maintaining compliant EPG and execution horizons ahead of real time.

Existing contracts establish the horizon guarantees:

- EPG horizon must be maintained at least N days ahead of real time.
- Execution horizon must be maintained at least N hours (or equivalent block count) ahead of real time.
- Horizons advance with wall-clock progression, not on demand.
- No last-second generation is permitted.
- Lock windows progress from flexible future through locked execution to immutable past.
- The next execution block is always available before the current block's fence.

These contracts define outcomes. HorizonManager is the component that enforces them over time. It is the concrete answer to "who maintains these invariants?"

HorizonManager does not:

- Perform episode selection or cursor advancement. (Schedule Manager owns resolution.)
- Perform segmentation, break insertion, or filler placement. (Planning pipeline owns composition.)
- Perform frame rendering, pacing, or transport. (AIR owns execution.)
- Respond to starvation or content deficit at runtime. (Channel Manager and runtime laws govern fallback.)
- Operate in response to Channel Manager demand. (Horizons advance by wall-clock policy, not consumption events.)

HorizonManager operates independently of Channel Manager. Channel Manager is a consumer of execution data; it never triggers, requests, or waits for HorizonManager activity.

---

## 2. Ownership Boundaries

| Component | Owns |
|---|---|
| **Schedule Manager** | ProgramEvent resolution, episode advancement, Schedule Day generation |
| **HorizonManager** | Horizon depth enforcement, lock window progression, eviction of expired data |
| **Channel Manager** | Execution consumption, session lifecycle, stream delivery |
| **AIR** | Frame rendering, real-time pacing, transport |

Authority flows downward. Schedule Manager produces planning artifacts. HorizonManager ensures those artifacts exist with sufficient depth and are locked on schedule. Channel Manager consumes locked execution data. AIR renders frames.

HorizonManager does not produce planning artifacts itself. It invokes Schedule Manager and the planning pipeline to extend horizons when depth falls below policy thresholds. The distinction is between policy authority (HorizonManager decides *when* to extend) and planning authority (Schedule Manager and the pipeline decide *what* the extension contains).

---

## 3. Horizon Definitions

### EPG Horizon

The window of Schedule Day and ProgramEvent data maintained ahead of real time for editorial visibility, guide publication, and operator confidence. Coarse granularity: day-level and slot-level. Contains resolved program assignments but not execution-level segments or asset paths.

### Execution Horizon

The window of execution-ready data (Transmission Log entries: blocks, segments, resolved asset references, filler and padding instructions) maintained ahead of real time for playout. Fine granularity: block-level and segment-level. All material references are resolved. Immutable once inside the locked window.

### Lock Windows

Three temporal regions, as established by the Schedule Horizon Management Contract:

- **Past.** Immutable. Execution that has been played. Used for audit and as-run comparison.
- **Locked execution window.** Inside the execution horizon. Immutable except by explicit operator override. Safe for automation consumption.
- **Flexible future.** Outside the execution horizon. Subject to planning changes. Not consumed by automation.

### Minimum Configurable Depths

| Parameter | Scope | Meaning |
|---|---|---|
| `min_epg_days` | Deployment-configurable | Minimum number of days of EPG coverage maintained ahead of real time |
| `min_execution_hours` | Deployment-configurable | Minimum number of hours of execution-ready data maintained ahead of real time |

These are minimums, not targets. Falling below either threshold is a policy violation. The exact values are deployment configuration; the contract requires that they are defined and enforced.

---

## 4. Responsibilities

### HorizonManager MUST

- Maintain EPG depth at or above `min_epg_days` ahead of real time.
- Maintain execution depth at or above `min_execution_hours` ahead of real time.
- Advance the lock window boundary as wall-clock time progresses. Data that enters the execution horizon becomes locked; data that passes behind the current time becomes past.
- Prune expired data (past window) according to retention policy. Pruning is bounded: data older than the retention window may be discarded. Retention policy is deployment-configurable.
- Trigger planning pipeline extensions when horizon depth falls below the configured minimum. Extensions produce new Schedule Days (for EPG) and new Transmission Log entries (for execution).
- Replace affected windows atomically when regenerated due to operator override. Partial or mixed-generation windows are not permitted within the execution horizon.

### HorizonManager MUST NOT

- Generate execution data on demand in response to Channel Manager activity. Horizon extension is wall-clock-driven.
- Be triggered by Channel Manager. Channel Manager never requests, signals, or polls HorizonManager for data.
- Perform segmentation, break insertion, filler placement, or any planning pipeline stage. HorizonManager invokes the pipeline; it does not contain pipeline logic.
- Select episodes or advance sequence cursors. Episode resolution is owned by Schedule Manager.
- Inspect AIR state, decoder readiness, or playout session status. HorizonManager operates above runtime.

---

## 5. Lifecycle Model

HorizonManager runs as a long-lived background component within Core. It is not a request handler or a consumer-driven service.

**Evaluation cadence.** HorizonManager evaluates horizon policy at a fixed interval (deployment-configurable; e.g. every 5-30 seconds). At each evaluation:

1. Determine current wall-clock time from MasterClock.
2. Compute current EPG depth (distance from now to the farthest resolved Schedule Day).
3. Compute current execution depth (distance from now to the farthest locked Transmission Log entry).
4. If EPG depth is below `min_epg_days`, invoke Schedule Manager to resolve the next required Schedule Day(s).
5. If execution depth is below `min_execution_hours`, invoke the planning pipeline to extend the execution horizon.
6. Advance the lock window boundary: any execution data that has entered the execution window since the last evaluation is now locked.
7. Prune past data beyond retention policy.

Evaluation cadence is not execution cadence. HorizonManager does not run once per block or once per segment. It runs on its own timer, independent of playout activity.

**MasterClock.** HorizonManager uses MasterClock for wall-clock authority. It does not derive time from playout state, viewer activity, or block boundaries.

---

## 6. Data Flow

```
                     ┌──────────────────────┐
                     │   HorizonManager     │
                     │  (policy enforcement) │
                     └──────┬───────┬───────┘
                            │       │
              extend EPG    │       │  extend execution
                            ▼       ▼
                  ┌─────────────┐  ┌─────────────────┐
                  │  Schedule   │  │    Planning      │
                  │  Manager   │  │    Pipeline       │
                  │ (resolve)  │  │ (Stages 0→6)     │
                  └──────┬──────┘  └───────┬──────────┘
                         │                 │
                         ▼                 ▼
                  ┌─────────────┐  ┌─────────────────┐
                  │  Resolved   │  │  Transmission    │
                  │  Store      │  │  Log Store       │
                  │ (EPG data)  │  │ (execution data) │
                  └──────┬──────┘  └───────┬──────────┘
                         │                 │
                         │    read-only    │
                         ▼                 ▼
                     ┌──────────────────────┐
                     │   Channel Manager    │
                     │   (execution only)   │
                     └──────────────────────┘
```

- HorizonManager calls Schedule Manager to extend the EPG horizon (resolve new Schedule Days).
- HorizonManager calls the planning pipeline to extend the execution horizon (produce new Transmission Log entries).
- Artifacts are stored in their respective stores (Resolved Store for Schedule Days; Transmission Log Store for execution data).
- Channel Manager reads from the execution store. The view is read-only. Channel Manager does not write to, invalidate, or request population of any store.
- Channel Manager never triggers generation. If execution data is absent when needed, that is a planning failure attributable to HorizonManager.

---

## 7. Failure Semantics

- If HorizonManager fails to maintain EPG depth at or above `min_epg_days`, this is a **horizon policy violation**. The system must log the violation with the current depth, the required minimum, and the wall-clock time of the shortfall.
- If HorizonManager fails to maintain execution depth at or above `min_execution_hours`, this is a **horizon policy violation**. Same logging requirements apply.
- If Channel Manager encounters starvation (lookahead exhausted, missing block at fence), this indicates an **upstream fault** in HorizonManager or the planning pipeline. Channel Manager does not compensate; runtime fallback (if any) is governed by runtime laws.
- The system must log invariant violations rather than silently regenerate. On-demand regeneration triggered by consumption is explicitly prohibited. If starvation occurs, the root cause is insufficient horizon maintenance, and the diagnostic path starts at HorizonManager.
- Planning pipeline failures (asset resolution failure, episode resolution failure) during horizon extension are reported by HorizonManager. HorizonManager does not suppress or retry silently; it logs the failure and the resulting horizon shortfall.

---

## 8. Burn-In Alignment

The burn-in harness (`tools/burn_in.py`) must align with HorizonManager's model:

- burn_in.py must instantiate HorizonManager (or an equivalent test double that enforces the same policy).
- burn_in.py must consume execution data from the horizon-managed execution window, not from direct pipeline invocation.
- burn_in.py must not call the planning pipeline directly for playout data.
- burn_in.py must not perform modulo day wrapping or index cycling to simulate multi-day operation. Day advancement is a consequence of horizon extension, not arithmetic.

Until HorizonManager is implemented as a runtime component, burn_in.py may use an interim adapter that approximates these semantics. The interim adapter must be documented as non-compliant and must be replaced when the production HorizonManager is available.

---

## 9. Non-Goals

The following are explicitly excluded from this document:

- **Persistence implementation details.** Whether stores are backed by memory, Postgres, Redis, or filesystem is a deployment decision, not a domain concern.
- **Distributed coordination.** Multi-node or clustered HorizonManager is a future concern. This document assumes a single-process deployment.
- **Multi-node clustering.** No leader election, consensus, or replication semantics are defined.
- **AIR seam delta handling.** Block transitions, seam preparation, and frame-level handoff are AIR execution concerns.
- **Segment composition logic.** Break insertion, chapter segmentation, filler packing, and pad placement are planning pipeline concerns.
- **Specific evaluation interval.** The exact cadence (5s, 10s, 30s) is deployment-configurable. This document requires that an interval exists and is honored.

---

## 10. Future Extensions

The following are recognized as future work and are not addressed in this version:

- **Persistent store backing.** Production deployments will require durable storage for resolved schedules and transmission logs across process restarts.
- **Multi-channel coordination.** HorizonManager policy enforcement across many channels with shared resources (pipeline throughput, store capacity).
- **Cluster coordination.** Distributed HorizonManager instances with coordinated horizon ownership and failover.
- **Predictive regeneration.** Anticipatory horizon extension based on pipeline throughput and historical generation time, rather than simple depth threshold.
- **SLA monitoring.** Formal service-level tracking of horizon depth compliance, extension latency, and policy violation rates.

---

**Document version:** 0.1
**Related:**
- [Schedule Horizon Management Contract (v0.1)](../contracts/ScheduleHorizonManagementContract_v0.1.md)
- [Schedule Manager Planning Authority (v0.1)](../contracts/ScheduleManagerPlanningAuthority_v0.1.md)
- [Schedule Execution Interface Contract (v0.1)](../contracts/ScheduleExecutionInterfaceContract_v0.1.md)
- [Program Event Scheduling Model (v0.1)](ProgramEventSchedulingModel_v0.1.md)
