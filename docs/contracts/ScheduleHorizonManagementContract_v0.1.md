# Schedule Horizon Management Contract — v0.1

**Status:** Contract  
**Version:** 0.1

**Classification:** Contract (Planning Horizon & Readiness)  
**Authority Level:** Coordination (Pre-runtime)  
**Governs:** Schedule Manager internal behavior and guarantees to consumers  
**Out of Scope:** Runtime execution, frame timing, decoder behavior

---

## 1. Purpose

This contract establishes the formal **horizon definitions** used by Schedule Manager and the **minimum readiness guarantees** for each horizon. It ensures automation is never starved of execution data and prevents on-demand planning at playout time. Schedule Manager maintains editorial and execution horizons proactively so that Channel Manager and downstream systems always have sufficient, immutable data to run.

**Key principle:** Planning is proactive; execution is never allowed to outrun the plan.

---

## 2. Horizon Definitions (Authoritative)

### Editorial / EPG Horizon

- **What it is:** The window of Schedule Day data maintained ahead of real time for editorial visibility and guide publication.
- **What it contains:** Resolved Schedule Days per channel and date, at program-level (or slot-level) granularity. Content is placed in zones with wall-clock times; programs and assets are identified but execution-level detail (segments, in/out points) is not required within this horizon.
- **What it is used for:** Guide visibility (EPG), operator confidence in “what will air when,” and as the source from which the execution horizon is built. EPG data is derived from Schedule Days within this horizon.
- **Explicit:** The EPG horizon is **not execution-authoritative**. EPG data is derived from Schedule Days. EPG data may exist without execution data (e.g. a day may be in the EPG horizon before the execution horizon has been extended to cover it).

### Execution Horizon

- **What it is:** The window of **execution-ready** data built ahead of real time for actual playout. Transmission Log (also referred to as the execution plan or playlog) is the canonical term for this data. It is the hard guarantee Channel Manager relies on.
- **What it contains:** Blocks and segments; asset-resolved identifiers (paths or stable URIs); durations (time or frame-based); filler and padding instructions. Granularity is block- and segment-level. All material references are resolved before data enters this horizon.
- **What it is used for:** Automation consumes only data within the execution horizon. No Asset Library lookups, no episode resolution, and no schedule math are required at playout time.
- **Immutability:** Execution data is **immutable once inside the locked execution window** (see §4). Changes occur only by explicit operator override that regenerates the affected window.
- **Explicit:** The execution horizon is **automation-safe**. No Asset Library lookups, episode resolution, or schedule math are required within this horizon.

---

## 3. Minimum Horizon Guarantees

These are **guarantees**, not goals. Failure to maintain them is a **planning fault**.

- **Minimum EPG horizon:** Schedule Manager maintains Schedule Day (and thus EPG) coverage for at least N days ahead of real time (N defined by deployment or policy). The exact value is a configuration or policy matter; the contract requires that a minimum is defined and maintained.
- **Minimum execution horizon:** Schedule Manager maintains execution-ready data (Transmission Log) for at least N hours (or equivalent block count) ahead of real time. Automation never encounters “end of horizon” before the next required block exists.
- **Always-available “next block” guarantee:** For any block currently being played, the next block (and where required, the block after that) is present in the execution horizon before the current block’s fence. Automation is never starved at a block boundary. Where downstream coordination (e.g. lookahead priming) requires visibility beyond the immediately next block, the execution horizon must include sufficient future blocks to satisfy those coordination invariants.
- **Continuous coverage:** Within the execution horizon, there are no gaps and no overlaps. The supplied window is continuous and atomically consistent. Execution data supplied for a given window is atomically consistent; Channel Manager will never observe a partially regenerated or mixed-generation window.

---

## 4. Lock Windows and Immutability

Three temporal regions are defined.

### Past

- **Immutable.** Execution that has already been played is historical.
- **Used for:** Audit, as-run comparison, and compliance. No modification after playout.

### Locked execution window (inside execution horizon)

- **Inside the execution horizon;** eligible for playout or currently being played.
- **Immutable except by explicit operator override.** No in-place edits. If a change is required, the affected window is regenerated and replaced as a whole.
- **Safe for automation.** Channel Manager may rely on this data not changing during playout.

**Explicit rule:** Execution data MUST NOT change while it is eligible for playout.

### Flexible future (outside execution horizon)

- **Outside the execution horizon;** not yet built into execution-ready form or not yet locked.
- **Subject to planning changes.** Schedule Day and plan edits apply here. Execution data does not exist here until the horizon is extended.
- **Not consumed by automation.** Channel Manager never reads from this region.

---

## 5. Horizon Advancement Policy

Horizons advance with wall-clock progression. Schedule Manager extends them proactively; it does not wait for Channel Manager demand.

- **Horizons advance based on wall-clock progression.** As real time moves forward, the “now” point moves; the EPG and execution horizons are maintained relative to that point.
- **Extension is incremental.** New Schedule Days and new execution data are added as the future opens; existing locked data is not rewritten.
- **New execution data is built before old data expires.** The execution horizon is extended so that the next block (and, where required, the block after) is available before the current block’s fence.
- **No “last-second” horizon generation.** Schedule Manager must not wait for Channel Manager demand to extend the horizon. Extension is driven by time and policy, not by consumption events.

**Prohibition:** Schedule Manager must not wait for Channel Manager demand to extend the horizon.

---

## 6. Regeneration and Overrides

Controlled mutation is allowed only via operator-initiated overrides (e.g. special events, emergency replacements).

- **Overrides regenerate the affected window atomically.** The planning pipeline produces a new, consistent execution window for the affected channel, date, and time range.
- **Regenerated execution data replaces old data.** The new window is supplied as a whole; there is no partial or in-place edit of existing execution data.
- **Channel Manager consumes the new window as a whole.** From automation’s perspective, the supplied data is replaced for the affected range; consistency and determinism are preserved.

---

## 7. Failure Semantics

The following are **planning failures**. Channel Manager does not compensate; runtime fallback (if any) is governed by runtime laws and invariants, not by this contract.

- **Execution horizon exhaustion:** Automation reaches a point where the next block is not present in the execution horizon. This is a failure of horizon maintenance. Failures must be observable and attributable to planning (Schedule Manager), not to automation.
- **Missing execution data:** A block or segment is required for playout but is absent from the supplied data. Treated as planning failure; Channel Manager does not retry or request data.
- **Asset resolution failure before horizon entry:** Material cannot be resolved or validated when building execution data. Resolution must succeed before data enters the execution horizon; failure is a planning fault and must not result in invalid data being supplied.

**Rules:** These failures are planning failures. Channel Manager does not compensate. Runtime fallback is governed elsewhere. Failures must be observable and attributable.

---

## 8. Relationship to Other Contracts and Laws

- **Schedule Manager Planning Authority (v0.1):** Defines who owns planning and what planning delivers. This contract defines **how far ahead** planning must exist and **how** horizons are maintained and locked. The Authority contract defines the pipeline; this contract defines the horizon and readiness guarantees.
- **Schedule Execution Interface Contract (v0.1):** Defines what crosses the boundary to Channel Manager. **This contract enables those interface guarantees.** The execution horizon maintained here is what the Execution Interface contract assumes: pre-built, immutable, atomically consistent data delivered ahead of real time.
- **Runtime constitutional laws:** This contract does not override Clock Law, Output Liveness Law, or runtime output invariants. It **feeds** runtime coordination layers (fence computation, frame budgets, automation readiness) but does not redefine runtime behavior.

**This contract exists above runtime and adjacent to (but not overlapping) the execution interface.**

---

## 9. Versioning and Evolution

- This contract is versioned independently (e.g. v0.1). Changes to horizon definitions or minimum guarantees require a new contract version.
- Horizon semantics (minimum N days, minimum N hours, “next block” rules) may evolve in future versions. Execution and planning are deployed together; Channel Manager does not negotiate contract versions at runtime.
- The active contract version in force at deployment defines the horizon behavior. No negotiation at runtime.

---

## 10. Non-Goals

- **Runtime buffering strategies:** How the playout engine stages or holds frames is out of scope. This contract governs planning horizons only.
- **Frame-accurate timing:** Frame-level pacing and fence enforcement are runtime concerns, not horizon management.
- **Encoder or decoder readiness:** Hardware or software readiness for playout is out of scope.
- **Viewer-driven scheduling:** Horizons are driven by wall clock and policy, not by viewer presence or tune-in.
- **“Just-in-time” planning:** Planning is proactive. There is no scenario in which execution is allowed to outrun the plan or in which planning is triggered by playout demand.

**Boundary:** This contract governs **how far ahead** planning exists and **how** that ahead-of-time data is maintained and locked. It does not govern what happens at runtime inside the playout engine or how Channel Manager delivers the stream.

---

**Document version:** 0.1  
**Related:** [Schedule Manager Planning Authority (v0.1)](ScheduleManagerPlanningAuthority_v0.1.md) · [Schedule Execution Interface Contract (v0.1)](ScheduleExecutionInterfaceContract_v0.1.md)  
**Governs:** Schedule Manager horizon and readiness guarantees
