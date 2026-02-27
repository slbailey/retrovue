# Program Segmentation and Ad Avail Contract — v0.1

**Status:** Contract  
**Version:** 0.1

**Classification:** Contract (Planning Semantics — Traffic)  
**Authority Level:** Coordination (Pre-runtime)  
**Governs:** Program → Block → Segment expansion  
**Out of Scope:** Runtime ad insertion, decoder behavior, playout timing

---

## 1. Purpose

This contract defines how program material is **segmented into editorial parts** and **ad avail opportunities** during planning. It establishes Schedule Manager as the sole authority for determining break structure and ad placement readiness before execution. Segmentation and break placement are planning-time decisions; execution consumes the result.

**Key principle:** Programs do not air as monolithic files; they air as segmented material with defined break opportunities.

---

## 2. Definitions

| Term | Definition |
|------|------------|
| **Program** | Editorial unit (episode, movie, special). The schedulable content that traffic places in zones and resolves to one or more segments. |
| **Segment** | Contiguous portion of a program between breakpoints. A segment has defined in/out (time or frame) and is execution-ready once inside the execution horizon. |
| **Break / Avail** | Planned non-program interval intended for ads, promos, or filler. A break is a slot within a block; its duration and placement are determined during planning. |
| **Synthetic break** | A break manufactured by traffic when no natural markers (e.g. chapter boundaries) exist in the program material. Synthetic breakpoints are treated identically to authored breakpoints after creation. |
| **Ad inventory** | Total non-program time available within a block after program duration and pad/tail requirements are accounted for. Allocated across breaks during planning. |

### Segment Identity

Segments are identified by stable indices within a block and retain their ordering across regeneration. Segment identity is planning-time metadata and has no execution authority. (Relevant for as-run logs, analytics, and ad performance tracking.)

---

## 3. Break Detection Rules

Schedule Manager **MUST** inspect program material during planning to establish break structure.

### If chapter markers exist

- Chapter boundaries are treated as **authoritative breakpoints**.
- Resulting segments define program parts. Segments are contiguous; breaks sit between them.

### If no chapter markers exist

- Schedule Manager **MUST** synthesize breakpoints according to policy.
- **Default policy (illustrative):**
  - 30-minute program → 3 program segments (2 synthetic breaks).
  - 60-minute program → 6 program segments (5 synthetic breaks).
- Synthetic breakpoints are treated identically to authored breakpoints after creation. Execution does not distinguish their origin.

### Immutability

- Break structure is **resolved once, during planning**, and is **immutable inside the execution horizon**. Channel Manager does not re-detect or re-slice; it executes the supplied segment list.

---

## 4. Ad Inventory Calculation

For each block containing a program:

```
Block duration
  − Program duration
  − Pad / tail requirements
  = Ad inventory
```

Ad inventory **MUST** be allocated across available breaks. The sum of break durations (and any pad within the block) **MUST** equal the block duration so that the block is continuous and deterministic.

---

## 5. Ad Inventory Distribution

- Ad inventory **MUST NOT** be placed as a single contiguous block after program completion. Inventory **MUST** be distributed across break opportunities.
- Distribution may be proportional (e.g. equal time per break) or per policy (e.g. first break longer, end break optional). Policy is a planning concern; the contract requires distribution across multiple breaks.
- Distribution **MUST** result in:
  - **Multiple mid-program breaks** (at least one break between program segments, where segment count allows).
  - **Optional end break** (a final break after the last program segment may be used for remaining inventory or omitted per policy).
  - **Deterministic total duration** matching the block. No unallocated time; no over-allocation.

---

## 6. Ad and Filler Placement

- Each break becomes a **planned mini-playlist** of ads, promos, or filler. Selection occurs **during planning**. Execution data contains fully resolved segments with durations and asset references.
- Channel Manager **does not** select or time ads. It plays the ordered list of segments (program segments and break segments) as supplied in the Transmission Log. Ads and filler are pre-placed segments.

---

## 7. Immutability and Horizon Interaction

- Once segments and breaks **enter the execution horizon**, they are **immutable**. No in-place edits; no runtime rebalancing.
- Regeneration requires **operator action** and **full window replacement** (per Schedule Horizon Management Contract). The affected block or window is rebuilt with new segment and break structure and supplied atomically.

---

## 8. Non-Responsibilities

**Channel Manager does not:**

- Infer break structure.
- Slice program material.
- Allocate ad inventory.
- Move or rebalance ads at runtime.

All of the above are Schedule Manager (traffic) responsibilities during planning.

---

## 9. Relationship to Other Contracts

- **Schedule Manager Planning Authority (v0.1):** Defines Schedule Manager as the sole planning authority. This contract defines **how** programs are expanded into segments and breaks within that authority.
- **Schedule Horizon Management (v0.1):** Defines when segmentation becomes locked (execution horizon, lock window). Segment and break structure is immutable once inside the locked execution window.
- **Schedule Execution Interface (v0.1):** Defines how segmented output is consumed. Channel Manager receives blocks and segments with resolved asset references and durations; it does not perform segmentation or ad placement.

---

## 10. Non-Goals

- **Dynamic ad insertion:** Ads are planned and fixed in the Transmission Log; no viewer-specific or request-time ad selection.
- **Viewer-specific ad decisions:** All viewers on a channel receive the same segment sequence.
- **Runtime break detection:** Break structure is determined during planning only.
- **Frame-accurate splice enforcement:** Splice semantics and frame-accurate boundaries are runtime/playout concerns, not defined by this contract.

---

**Document version:** 0.1  
**Related:** [Schedule Manager Planning Authority (v0.1)](ScheduleManagerPlanningAuthority_v0.1.md) · [Schedule Horizon Management (v0.1)](ScheduleHorizonManagementContract_v0.1.md) · [Schedule Execution Interface (v0.1)](ScheduleExecutionInterfaceContract_v0.1.md)  
**Governs:** Program → Block → Segment expansion and ad avail semantics
