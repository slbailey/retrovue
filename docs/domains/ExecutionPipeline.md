# Execution Pipeline — Canonical Reference

**Status:** Authoritative
**Authority Level:** System-wide

---

## Pipeline

```
SchedulePlan
   ↓
ScheduleRevision
   ↓
ScheduleItem
   ↓
PlaylistEvent
   ↓
ExecutionSegment
   ↓
BlockPlan
   ↓
AIR
   ↓
AsRun
```

## Authority Boundaries

| Stage | Owner | Layer |
|-------|-------|-------|
| **SchedulePlan** | Operator (zones, templates, pools) | Tier 1 — Editorial intent |
| **ScheduleRevision** | Scheduler (DSL compiler) | Tier 1 — Editorial snapshot |
| **ScheduleItem** | Scheduler (DSL compiler), owned by ScheduleRevision | Tier 1 — Editorial |
| **PlaylistEvent** | PlaylistBuilderDaemon | Tier 2 — Execution planning |
| **ExecutionSegment** | Execution planner | Tier 2 — Execution planning |
| **BlockPlan** | Core → AIR interface (gRPC) | Tier 2 → Runtime handoff |
| **AIR** | Playout engine (C++) | Runtime |
| **AsRun** | Evidence store | Runtime → Audit |

## Definitions

**SchedulePlan** — The operator's declaration of editorial intent. Contains zones, templates, pools, and day-of-week rules. Compiled into a ScheduleRevision.

**ScheduleRevision** — An immutable snapshot of the editorial schedule for a single channel and broadcast_day. The authoritative container for ScheduleItems. Exactly one revision may be active per channel per broadcast_day at any time.

**ScheduleItem** — The canonical, persistent unit of editorial scheduling. One grid-aligned program slot on a channel's timeline. Belongs to exactly one ScheduleRevision. Created during DSL schedule compilation. Frozen after generation. ScheduleDay is a derived grouping of ScheduleItems by date, not an owner.

**PlaylistEvent** — Execution-intent unit. A single time-bounded instruction for playout derived from a ScheduleItem. Contains segment structure (content, filler, pad, transition), wall-clock timestamps, and resolved asset references. Tiles the timeline without gaps or overlaps.

**ExecutionSegment** — Frame-accurate playback instruction derived from a PlaylistEvent. The final Core-produced artifact before handoff to AIR. Contains seek positions, asset URIs, PTS offsets, and segment-level metadata.

**BlockPlan** — The AIR execution unit fed via gRPC (`FeedBlockPlan`). Contains a sequence of ExecutionSegments for a single time window. Core feeds BlockPlans to AIR; AIR executes them frame-accurately.

**AIR** — Real-time playout engine. Renders ExecutionSegments frame-accurately. Knows nothing about schedules, EPG, zones, or editorial intent.

**AsRun** — Observed ground truth. Records what actually aired during playout, including actual timestamps from MasterClock. Compared against planned PlaylistEvents to identify discrepancies.

**ContentEvent** — A PlaylistEvent of kind `content`. References a ScheduleItem and carries an asset offset indicating where within the program's content this event begins. A single ScheduleItem may produce one or more ContentEvents, but only when semantic boundaries require splitting.

**Non-Content Event** — A PlaylistEvent of kind `ad`, `promo`, `pad`, or `override`. These events do not reference a ScheduleItem's editorial identity. They fill time between, around, or in place of content.

**Semantic Boundary** — A point in the timeline where execution intent changes for a reason meaningful to the playout model. Semantic boundaries include: ad insertion points, promo insertion points, operator overrides, content transitions (one ScheduleItem ending and another beginning), and explicit metadata boundaries (e.g., rating change, parental advisory trigger). Grid block boundaries are NOT semantic boundaries.

## Layer Rules

- **Tier 1 (Editorial)** operates days in advance. Frozen and immutable once generated.
- **Tier 2 (Execution)** operates hours ahead. Immutable once inside the locked execution window.
- **Runtime** renders frames. Aligned to MasterClock.
- Each stage derives exclusively from the stage above it (`LAW-DERIVATION`).
- No stage may introduce content absent from its upstream authority (`LAW-CONTENT-AUTHORITY`).
- PlaylistEvent is the sole runtime authority for what plays now (`LAW-RUNTIME-AUTHORITY`).

Authority flows downward. Each layer consumes the output of the layer above and produces input for the layer below.

- ScheduleItem determines WHAT airs and WHEN (editorial). PlaylistEvent determines HOW the airing is structured for execution.
- PlaylistEvent MUST NOT select episodes, choose programs, or alter editorial identity. It receives ScheduleItems as input and structures them for execution.
- ExecutionSegment MUST NOT decide when ad breaks occur or where content transitions happen. It receives PlaylistEvents and produces concrete clip instructions.
- AIR MUST NOT interpret execution intent. It renders ExecutionSegments frame-accurately.

Lower layers MAY refine presentation within their authority (e.g., ExecutionSegment adjusts seek position for frame accuracy; AIR manages decoder priming) but MUST NOT override decisions made by upper layers.

## Grid Boundaries vs Semantic Boundaries

Grid blocks are planning artifacts. They exist to organize the schedule into fixed-duration containers for materialization purposes. Blocks MUST NOT propagate into the execution layer.

PlaylistEvent generation from ScheduleItems follows these rules:

- A ScheduleItem that requires no semantic splitting produces **one** PlaylistEvent regardless of how many grid blocks it spans. A 90-minute movie on a 30-minute grid that plays without interruption produces one ContentEvent with `duration_ms=5,400,000`.
- Grid block boundaries (fences) do NOT mandate PlaylistEvent splitting. The fact that a movie crosses from block 5 into block 6 is irrelevant to PlaylistEvent generation.
- Splitting occurs **only** at semantic boundaries:
  - **Ad insertion** -- An ad break within the movie creates a split: content before the break, one or more ad/promo events, content after the break.
  - **Promo insertion** -- Same as ad insertion.
  - **Override** -- An operator override replacing a segment of content.
  - **Content transition** -- One ScheduleItem ending and the next beginning.
  - **Explicit metadata boundary** -- A point where metadata changes require a new event (e.g., rating change, parental advisory).
- The number of PlaylistEvents for a given ScheduleItem is determined by the number of semantic boundaries, not by grid geometry.

**Examples:**

| Scenario | Grid Blocks | PlaylistEvents |
|---|---|---|
| 22-min sitcom, 30-min grid, no ads | 1 | 1 content + 1 pad |
| 22-min sitcom, 30-min grid, 2 ad breaks | 1 | 3 content + 2 ad + 1 pad |
| 90-min movie, 30-min grid, no ads | 3 | 1 content |
| 90-min movie, 30-min grid, 2 ad breaks | 3 | 3 content + 2 ad |
| 90-min movie, 30-min grid, 2 ad breaks + trailing promo | 3 | 3 content + 2 ad + 1 promo |

## Horizon Interaction

PlaylistEvents exist within the playout horizon. They are generated when the playout horizon extends and are valid only within the horizon window that produced them.

| Property | Behavior |
|---|---|
| Generation | PlaylistEvents are generated from ScheduleItems during playout horizon extension. |
| Regeneration | If upstream editorial changes occur (EPG modification, operator override), affected PlaylistEvents are regenerated. Regeneration replaces the affected window atomically. |
| Lifetime | A PlaylistEvent is authoritative only while it is within the active playout horizon window. PlaylistEvents beyond the horizon boundary are speculative and MUST NOT be relied upon. |
| Consumption | ExecutionSegments are derived from PlaylistEvents. AIR consumes ExecutionSegments. AIR never sees PlaylistEvents directly. |

The playout horizon depth (typically 2-3 blocks worth of wall-clock time) determines how far ahead PlaylistEvents are generated. PlaylistEvents are not persisted beyond the horizon window; they are regenerable from ScheduleItems and break/insertion policy at any time.

## What This Pipeline Replaces

Earlier documentation used intermediate concepts that no longer exist as distinct pipeline stages:

- **ProgramEvent** — replaced by ScheduleItem
- **Playlist** (as a structural layer between ScheduleDay and execution) — eliminated; PlaylistEvent is the execution-intent entity directly
- **PlaylogEvent** — renamed to PlaylistEvent
- **TransmissionLog** (as a pipeline entity) — replaced by PlaylistEvent store; the `.tlog` artifact format is an operational output, not a pipeline stage

## See Also

- [GLOSSARY.md](../core/GLOSSARY.md) — Canonical vocabulary
- [ScheduleRevision](scheduling/ScheduleRevision.md) — Editorial snapshot domain model
- [ScheduleItem](ScheduleItem.md) — Editorial unit domain model
- [BroadcastDay](BroadcastDay.md) — Derived date grouping
- [PlaylistEvent](playout/PlaylistEvent.md) — Execution-intent domain model
- [ExecutionSegment](playout/ExecutionSegment.md) — Frame-accurate instruction domain model
- [Scheduling Contract](../contracts/scheduling_contract.md) — Constitutional scheduling invariants
