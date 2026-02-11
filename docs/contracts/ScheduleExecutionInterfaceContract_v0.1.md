# Schedule Execution Interface Contract — v0.1

**Status:** Contract  
**Version:** 0.1

**Classification:** Contract (Planning ↔ Execution Boundary)  
**Authority Level:** Coordination (Non-runtime)  
**Governs:** Schedule Manager → Channel Manager  
**Out of Scope:** Runtime playout laws, frame timing, media execution

---

## 1. Purpose

This contract defines the **sole interface** by which automation (Channel Manager) consumes planning output. It establishes Schedule Manager as the **exclusive source of execution truth** for playout and prevents any planning, resolution, or material lookup in the playout path.

**Key principle:** Automation executes what it is given; it does not decide what to air.

---

## 2. Authority Model

### Schedule Manager

- **Planning authority.**
- Owns editorial intent, traffic, material resolution, and horizon maintenance.
- Supplies execution artifacts to Channel Manager; does not control real-time delivery.

### Channel Manager

- **Execution authority.**
- Owns runtime coordination, session lifecycle, and stream delivery.
- Consumes execution artifacts as supplied; does not request or trigger planning.

### No shared authority

- Channel Manager never escalates decisions back into planning logic at runtime.
- At no time does automation request the creation of execution data.

---

## 3. Supplied Execution Artifacts

The following cross the boundary from Schedule Manager to Channel Manager.

### Execution plan (also referred to as the Transmission Log)

- Ordered blocks.
- Segment boundaries (time or frame-based).
- Durations (time or frame-based).
- Resolved asset identifiers (paths or stable URIs).
- Filler and padding instructions.

### Execution metadata

- Stable identifiers for blocks and segments.
- Titles for logging and telemetry.
- Optional guide labels (non-authoritative for playout).

Channel Manager **consumes these artifacts as-is**. It does not transform, resolve, or extend them.

---

## 4. Temporal Guarantees

- **Execution data is delivered ahead of real time.** Every block and segment that automation will play is supplied before the playout engine needs it.
- **Execution plans cover a continuous window.** No gaps, no overlaps within the supplied window. Execution data supplied across the boundary is atomically consistent for the covered window.
- **Schedule Manager extends the execution horizon before Channel Manager reaches the end.** The planning pipeline maintains sufficient lookahead so that the next block (and, where required, the next-next block) is available before the current block’s fence.
- **Channel Manager never blocks waiting for planning output.** If execution data is missing at the point it is needed, that is a planning failure; automation does not stall awaiting a response from planning.

**At no time does automation request the creation of execution data.**

---

## 5. Immutability Rules

- **Execution data inside the execution horizon is immutable.** Once supplied, it is not edited in place.
- **Changes require explicit operator action:** override or regeneration of the affected window, and replacement of the execution plan (or the affected portion), not mutation of existing data.
- **Channel Manager never edits, patches, or repairs execution data.** It executes what it receives; it does not correct or fill in missing segments.

---

## 6. Error and Exceptional Conditions

- **Missing execution data** (e.g. no block at a fence, lookahead exhausted) is a **planning failure**. Automation may terminate the session or signal failure; it does not retry planning or request new data. Channel Manager does not implicitly retry or poll planning systems for missing execution data.
- **Missing material** (e.g. asset path invalid, file not found) is a **planning failure**. Resolution and validation are planning responsibilities; Channel Manager does not substitute, resolve, or query the Asset Library.
- **Runtime fallback** (freeze, pad, black, silence) when content is unavailable or decoder fails is governed by **runtime laws and invariants**, not by this contract. This contract governs the planning–execution boundary only.

---

## 7. Non-Responsibilities (Explicit)

### Channel Manager does not

- Resolve episodes or programs.
- Query the Asset Library.
- Build playlists.
- Compute block boundaries.
- Perform schedule math.
- Interpret EPG data for playout decisions.

### Schedule Manager does not

- Control real-time pacing.
- Manage frame-level delivery.
- Observe decoder state.
- React to runtime stalls or content deficits.

---

## 8. Relationship to Constitutional Laws and Invariants

- **This contract does not override:**
  - Clock Law (time authority).
  - Output Liveness Law (continuous emission, bounded delivery).
  - INV-TICK-GUARANTEED-OUTPUT and other runtime output invariants.

- **This contract feeds:**
  - Fence computation (block end times / frame budgets).
  - Frame budget derivation for segments and padding.
  - Lookahead priming (current + next block, or equivalent).

- **This contract exists above runtime coordination layers.** It defines what automation receives and how it may use it; it does not define how the playout engine enforces fences, emits frames, or handles content deficit. Those are governed by runtime laws and semantic invariants.

---

## 9. Versioning and Evolution

- This contract is versioned independently (e.g. v0.1). Changes that alter the boundary or guarantees require a new contract version.
- Planning and execution are deployed together; Channel Manager does not independently negotiate contract versions. Compatibility is maintained by coordinated deployment.
- Backward compatibility expectations (if any) will be stated in the contract version that introduces them.

---

## 10. Non-Goals

- **Playout logic in this contract:** Frame timing, encoder behavior, pad/fill strategies, and session teardown are out of scope; they are defined by runtime laws and AIR contracts.
- **Schedule Manager controlling playout:** Schedule Manager does not send real-time commands to the playout engine; it only supplies execution data ahead of time.
- **Channel Manager as fallback planner:** In the event of missing data or material, Channel Manager does not assume planning duties; it fails or applies runtime fallback per runtime laws.
- **EPG or Schedule Day as execution input:** Playout is driven solely by the execution plan (playlog / transmission log), not by EPG or Schedule Day directly.

---

**Document version:** 0.1  
**Related:** [Schedule Manager Planning Authority (v0.1)](ScheduleManagerPlanningAuthority_v0.1.md)  
**Governs:** Schedule Manager → Channel Manager interface
