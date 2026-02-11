# Playlist Event Execution Model — v0.1

**Status:** Domain Model
**Version:** 0.1

**Classification:** Domain (Execution Intent)
**Authority Level:** Coordination (Cross-layer)
**Governs:** PlaylistEvent identity, execution-intent time slicing, semantic boundary splitting, relationship to ProgramEvent and ExecutionSegment
**Out of Scope:** Frame timing, decoder priming, fence enforcement implementation, block definition, editorial episode selection

---

## Domain — Playlist Event Execution Model

### Purpose

ProgramEvent is the canonical editorial unit. It represents what airs and when — episode identity, program association, grid occupancy. But ProgramEvent is not an execution instruction. It carries no information about ad breaks, promo insertions, content transitions, or time-bounded playback intent. The gap between editorial identity and concrete clip-level instructions requires an intermediate layer.

PlaylistEvent is that layer. It represents **execution intent**: a time-bounded instruction describing what should happen during a specific wall-clock interval. PlaylistEvent is not editorial identity (that is ProgramEvent) and not frame-level segmentation (that is ExecutionSegment). PlaylistEvent answers the question: "What is the execution plan for this interval of time?"

This model addresses:

- ProgramEvent defines what airs. PlaylistEvent defines how the airing is structured for execution.
- Execution requires time-bounded units that account for ad insertion, promo placement, content transitions, and padding — none of which are editorial decisions.
- Grid blocks are planning artifacts. They MUST NOT exist at the execution level. PlaylistEvent is the first execution-visible layer.
- Multi-block ProgramEvents must not be artificially split at grid boundaries when no semantic reason exists for the split.

The layering is:

    ProgramEvent (editorial identity)
        ↓
    PlaylistEvent (execution intent)
        ↓
    ExecutionSegment (concrete clip instructions)

Each layer has exclusive authority over its concerns. No layer reaches into another's domain.

---

### Core Concepts

- **PlaylistEvent** — A time-bounded execution-intent unit aligned to wall-clock time. Describes what should happen during a specific interval: play content, insert an ad, run a promo, emit pad, or execute an override. Every PlaylistEvent has a definite start time and duration. PlaylistEvents tile the timeline without gaps or overlaps within a channel.
- **ContentEvent** — A PlaylistEvent of kind `content`. References a ProgramEvent and carries an asset offset indicating where within the program's content this event begins. A single ProgramEvent may produce one or more ContentEvents, but only when semantic boundaries require splitting.
- **Non-Content Event** — A PlaylistEvent of kind `ad`, `promo`, `pad`, or `override`. These events do not reference a ProgramEvent's editorial identity. They fill time between, around, or in place of content.
- **Semantic Boundary** — A point in the timeline where execution intent changes for a reason meaningful to the playout model. Semantic boundaries include: ad insertion points, promo insertion points, operator overrides, content transitions (one ProgramEvent ending and another beginning), and explicit metadata boundaries (e.g., rating change, parental advisory trigger). Grid block boundaries are NOT semantic boundaries.
- **Timeline Alignment** — PlaylistEvents are wall-clock aligned. Their `start_utc_ms` values correspond to real UTC time. The sum of all PlaylistEvent durations within a channel's playout horizon equals the horizon's total duration with no gaps.

---

### Domain Model

| Field | Type | Description |
|---|---|---|
| `id` | string | Stable unique identifier for this PlaylistEvent |
| `start_utc_ms` | int | Wall-clock start time (epoch milliseconds) |
| `duration_ms` | int | Duration of this event in milliseconds |
| `kind` | Literal["content", "ad", "promo", "pad", "override"] | The type of execution intent |
| `program_event_id` | string or null | ProgramEvent this event derives from. Required for `content`. Null for non-content kinds. |
| `asset_id` | string or null | Asset to play. Required for `content`, `ad`, `promo`. Null for `pad`. |
| `offset_ms` | int or null | Offset into the asset at which playback begins. Required for `content`. Null or 0 for non-content kinds. |
| `metadata` | dict | Optional. Extensible metadata (ratings, flags, signaling hints). |

**Field requirements by kind:**

| Field | content | ad | promo | pad | override |
|---|---|---|---|---|---|
| `program_event_id` | Required | Null | Null | Null | Optional |
| `asset_id` | Required | Required | Required | Null | Required |
| `offset_ms` | Required | 0 | 0 | Null | 0 |

Notes:

- `start_utc_ms` is absolute wall-clock time aligned to the playout timeline.
- `duration_ms` is the wall-clock duration this event occupies. For content events, this is the playback duration within this event, not the full program duration.
- `offset_ms` for content events indicates the byte-stream position within the asset. For block 1 of a 90-minute movie on a 30-minute grid with no semantic breaks, `offset_ms` would be 0 and `duration_ms` would be 5,400,000. If an ad break splits the movie at minute 45, the first content event has `offset_ms=0, duration_ms=2,700,000` and the second has `offset_ms=2,700,000, duration_ms=2,700,000`.
- `id` is generated during PlaylistEvent creation and is stable for the lifetime of the playout horizon window containing it.

---

### Ownership and Authority

| Layer | Owns |
|---|---|
| ProgramEvent | Editorial identity, episode selection, program-to-time assignment, grid occupancy |
| PlaylistEvent | Execution intent, time slicing at semantic boundaries, non-content event placement, wall-clock alignment |
| ExecutionSegment | Concrete asset playback instructions, seek positions, frame-accurate boundaries, segment-level metadata |
| AIR | Frame-accurate rendering, real-time pacing, decoder management, transport |

Authority flows downward. Each layer consumes the output of the layer above and produces input for the layer below.

- ProgramEvent determines WHAT airs and WHEN (editorial). PlaylistEvent determines HOW the airing is structured for execution.
- PlaylistEvent MUST NOT select episodes, choose programs, or alter editorial identity. It receives ProgramEvents as input and structures them for execution.
- ExecutionSegment MUST NOT decide when ad breaks occur or where content transitions happen. It receives PlaylistEvents and produces concrete clip instructions.
- AIR MUST NOT interpret execution intent. It renders ExecutionSegments frame-accurately.

Lower layers MAY refine presentation within their authority (e.g., ExecutionSegment adjusts seek position for frame accuracy; AIR manages decoder priming) but MUST NOT override decisions made by upper layers.

---

### Multi-Block ProgramEvent Handling

Grid blocks are planning artifacts. They exist to organize the schedule into fixed-duration containers for materialization purposes. Blocks MUST NOT propagate into the execution layer.

PlaylistEvent generation from ProgramEvents follows these rules:

- A ProgramEvent that requires no semantic splitting produces **one** PlaylistEvent regardless of how many grid blocks it spans. A 90-minute movie on a 30-minute grid that plays without interruption produces one ContentEvent with `duration_ms=5,400,000`.
- Grid block boundaries (fences) do NOT mandate PlaylistEvent splitting. The fact that a movie crosses from block 5 into block 6 is irrelevant to PlaylistEvent generation.
- Splitting occurs **only** at semantic boundaries:
  - **Ad insertion** — An ad break within the movie creates a split: content before the break, one or more ad/promo events, content after the break.
  - **Promo insertion** — Same as ad insertion.
  - **Override** — An operator override replacing a segment of content.
  - **Content transition** — One ProgramEvent ending and the next beginning.
  - **Explicit metadata boundary** — A point where metadata changes require a new event (e.g., rating change, parental advisory).
- The number of PlaylistEvents for a given ProgramEvent is determined by the number of semantic boundaries, not by grid geometry.

**Examples:**

| Scenario | Grid Blocks | PlaylistEvents |
|---|---|---|
| 22-min sitcom, 30-min grid, no ads | 1 | 1 content + 1 pad |
| 22-min sitcom, 30-min grid, 2 ad breaks | 1 | 3 content + 2 ad + 1 pad |
| 90-min movie, 30-min grid, no ads | 3 | 1 content |
| 90-min movie, 30-min grid, 2 ad breaks | 3 | 3 content + 2 ad |
| 90-min movie, 30-min grid, 2 ad breaks + trailing promo | 3 | 3 content + 2 ad + 1 promo |

---

### Horizon Architecture Interaction

PlaylistEvents exist within the playout horizon. They are generated when the playout horizon extends and are valid only within the horizon window that produced them.

| Property | Behavior |
|---|---|
| Generation | PlaylistEvents are generated from ProgramEvents during playout horizon extension. |
| Regeneration | If upstream editorial changes occur (EPG modification, operator override), affected PlaylistEvents are regenerated. Regeneration replaces the affected window atomically. |
| Lifetime | A PlaylistEvent is authoritative only while it is within the active playout horizon window. PlaylistEvents beyond the horizon boundary are speculative and MUST NOT be relied upon. |
| Consumption | ExecutionSegments are derived from PlaylistEvents. AIR consumes ExecutionSegments. AIR never sees PlaylistEvents directly. |

The playout horizon depth (typically 2–3 blocks worth of wall-clock time) determines how far ahead PlaylistEvents are generated. PlaylistEvents are not persisted beyond the horizon window; they are regenerable from ProgramEvents and break/insertion policy at any time.

---

### Non-Goals

This document explicitly does NOT govern:

- **Frame timing.** Frame-level pacing, frame budgets, and frame-accurate boundaries are ExecutionSegment and AIR responsibilities.
- **Decoder priming.** Lookahead and decoder warm-up are runtime coordination concerns outside PlaylistEvent scope.
- **Fence enforcement implementation.** How block fences are enforced at the execution level is an AIR runtime invariant. PlaylistEvent does not reference fences.
- **Block definition.** Grid blocks are planning artifacts. PlaylistEvent supersedes blocks at the execution layer. This document does not modify or govern block semantics.
- **Editorial episode selection.** Which episode airs is a ProgramEvent/EPG decision. PlaylistEvent receives that decision as input.
- **Segment composition logic.** How content is sliced into frame-accurate segments within a PlaylistEvent is governed by ExecutionSegment, not by this model.

---

### Future Extensions

- **SCTE marker generation.** PlaylistEvents at ad boundaries could drive SCTE-35 splice insert signaling for downstream ad decisioning systems.
- **Dynamic ad decisioning.** Ad-kind PlaylistEvents could carry targeting metadata enabling real-time ad selection at playout time rather than pre-resolved filler.
- **Live insertion.** Live content events that override scheduled PlaylistEvents with indeterminate duration and defined resume semantics.
- **Operator override.** Real-time operator commands that replace a window of PlaylistEvents with override content, with atomic regeneration of the affected horizon region.
- **Metadata signaling.** PlaylistEvent metadata could carry downstream signaling (parental advisory, audio language switches, closed caption triggers) that ExecutionSegments translate into transport-level descriptors.

---

**Document version:** 0.1
**Related:** [Program Event Scheduling Model (v0.1)](ProgramEventSchedulingModel_v0.1.md) · [Schedule Execution Interface (v0.1)](../contracts/ScheduleExecutionInterfaceContract_v0.1.md) · [Program Segmentation and Ad Avail (v0.1)](../contracts/ProgramSegmentationAndAdAvailContract_v0.1.md)
**Governs:** PlaylistEvent identity, execution-intent time slicing, semantic boundary splitting, relationship to ProgramEvent and ExecutionSegment
