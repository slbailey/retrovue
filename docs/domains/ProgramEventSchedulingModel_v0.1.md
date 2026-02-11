# Program Event Scheduling Model — v0.1

**Status:** Domain Model
**Version:** 0.1

**Classification:** Domain (Editorial-to-Execution Mapping)
**Authority Level:** Coordination (Cross-layer)
**Governs:** ProgramEvent identity, event-to-block mapping, episode advancement authority, horizon architecture
**Out of Scope:** Fence timing, frame budgets, segment composition, priming

---

## Domain — Program Event Scheduling Model

### Purpose

Grid Blocks are fixed-duration execution containers (e.g., 30 minutes). Programs are editorial units with variable duration. A 22-minute sitcom occupies one block; a 90-minute movie spans three. The implicit model — one episode per block, episode advancement per block — breaks when program duration does not align with block duration.

ProgramEvent is the canonical editorial unit. It represents a single scheduled airing of an episode, movie, or special within the EPG. ProgramEvent identity persists across block boundaries. Episode advancement occurs at the ProgramEvent level during EPG horizon extension, not at the block level during playout.

This model addresses:

- Grid blocks are fixed; programs are variable. The mapping is not 1:1.
- Editorial identity MUST NOT be block-centric.
- Episode advancement MUST occur when the EPG assigns the next episode, not when a block boundary is crossed.
- Multi-block programs MUST appear as a single EPG entry with a single ProgramEvent identity.

---

### Core Concepts

- **Grid Block** — Fixed-duration execution container aligned to wall-clock boundaries (e.g., hh:00, hh:30). The unit of playout materialization. Contains segments (content, filler, pad) that sum to exactly the block duration.
- **Program Event** — A single scheduled airing of a program (episode, movie, special). The canonical editorial unit. Identified in the EPG. May span one or more grid blocks. Episode advancement occurs at this level.
- **Block Span** — The number of contiguous grid blocks a ProgramEvent occupies. Derived from `ceil(event_duration / block_duration)`. A 22-minute episode on a 30-minute grid: block span 1. A 90-minute movie on a 30-minute grid: block span 3.
- **Event-to-Block Mapping** — The association between a ProgramEvent and the grid blocks that carry its content. Multiple blocks MAY reference the same ProgramEvent. Each block knows its position within the event.
- **EPG Horizon** — The window of ProgramEvents maintained ahead of real time. Defines what will air and when. Episode selection and advancement occur here. Typically 2–3 days.
- **Playout Horizon** — The window of materialized, execution-ready blocks maintained ahead of real time. Contains resolved segments, asset references, and timing. Typically 2–3 blocks.

---

### Authoritative Ownership

| Layer | Owns |
|---|---|
| Schedule Template | Program type pattern, zone structure, day rules |
| EPG | ProgramEvent identity, time assignment, episode selection |
| Playout | Block materialization, segment composition, filler/pad placement |
| AIR | Frame-accurate execution, real-time pacing, fence enforcement |

- EPG assigns ProgramEvents to time slots. Episode selection is an EPG-layer decision.
- Playout MUST NOT select episodes. Playout materializes blocks from ProgramEvents already assigned by the EPG.
- Blocks reference ProgramEvents. A block is an execution container for a portion of a ProgramEvent.
- Lower layers MAY refine presentation (segment boundaries, filler selection, pad duration) but MUST NOT override editorial decisions (which episode, which program, what time).

---

### ProgramEvent Domain Model

| Field | Type | Description |
|---|---|---|
| `id` | string | Stable unique identifier for this scheduled airing |
| `program_id` | string | Parent program (e.g., "cheers") |
| `episode_id` | string | Specific episode within the program |
| `start_utc_ms` | int | Wall-clock start time (epoch milliseconds, grid-aligned) |
| `duration_ms` | int | Intrinsic program runtime (not grid occupancy) |
| `block_span_count` | int | Number of grid blocks this event occupies |
| `metadata` | dict | Optional. Future expansion (ratings, genre, editorial flags) |

Two durations apply to every ProgramEvent:

| Concept | Derivation | Example (22-min sitcom, 30-min grid) |
|---|---|---|
| `duration_ms` | Intrinsic program runtime | 1,320,000 ms (22 min) |
| Occupied grid time | `block_span_count * block_duration_ms` | 1,800,000 ms (30 min) |

`duration_ms` represents intrinsic program runtime, not grid occupancy. Grid occupancy is derived from `block_span_count * block_duration_ms`. These values are equal only when program runtime is an exact multiple of block duration. For short-form content (sitcoms, half-hour shows), the difference between program runtime and grid occupancy is filled by the playout layer per normal block composition rules (filler, breaks, pad).

- `start_utc_ms` MUST align to grid block boundaries under fixed-grid scheduling mode. Non-grid-aligned start times (live events, overrides) are reserved for future scheduling modes and are not supported by the current model.
- `duration_ms` MAY span 1..N grid blocks. A 22-minute episode fits in one 30-minute block. A 2-hour movie spans four.
- `block_span_count` is derived: `ceil(duration_ms / block_duration_ms)`.
- ProgramEvent identity persists across block boundaries. A movie airing across blocks 5, 6, and 7 is one ProgramEvent, not three.
- `duration_ms` MUST NOT be assumed equal to `block_span_count * block_duration_ms`.

---

### Grid Block Model

| Field | Type | Description |
|---|---|---|
| `start_utc_ms` | int | Block start (epoch milliseconds, wall-clock aligned) |
| `end_utc_ms` | int | Block end (epoch milliseconds) |
| `program_event_id` | string | The ProgramEvent this block carries content for |
| `block_index_within_event` | int | Position of this block within the parent event (0-indexed) |

- Blocks are half-open intervals: `[start_utc_ms, end_utc_ms)`.
- Blocks are execution containers only. They carry segments derived from a ProgramEvent but do not define editorial identity.
- Multiple blocks MAY reference the same ProgramEvent. Block 5 and block 6 may both carry content for event "evt-007" with `block_index_within_event` 0 and 1 respectively.

---

### Horizon Architecture

| Layer | Horizon | Content | Typical Depth |
|---|---|---|---|
| Schedule Template | Infinite | Repeating program patterns, zone definitions | Unbounded |
| EPG | 2–3 days | Concrete ProgramEvents with identity and time | Days |
| Playout | 2–3 blocks | Materialized execution-ready blocks with segments | Hours |
| AIR | 1 block | Active block under execution | Minutes |

Horizons roll independently but hierarchically:

- EPG extends by resolving the template for the next time window when the existing EPG horizon shrinks below its minimum depth.
- Playout extends by materializing the next block(s) from assigned ProgramEvents when the playout horizon shrinks below its minimum depth.
- AIR consumes one block at a time. It receives the next block before the current block's fence.

Each layer consumes only the output of the layer above. Playout MUST NOT resolve episodes. AIR MUST NOT query the EPG. Extension at one layer does not force extension at another; each layer maintains its own minimum horizon per policy.

---

### Episode Advancement Rules

- Episode advancement occurs during **EPG horizon extension**. When the EPG layer assigns ProgramEvents for a new time window, it selects the next episode in sequence (or per play mode) and advances the cursor.
- Playout does not mutate episode order. Playout materializes blocks from ProgramEvents already assigned by the EPG. It has no authority to skip, reorder, or substitute episodes.
- Restarting the server MUST NOT alter previously assigned ProgramEvents within the locked EPG horizon. ProgramEvents inside the locked window are immutable. Episode advancement resumes from the persisted cursor position.
- The episode cursor belongs to the EPG layer. It is persisted by the sequence store and consulted only during EPG horizon extension, never during block materialization or playout.

The EPG horizon contains two named windows:

| Window | State | Semantics |
|---|---|---|
| Locked | Editorially committed | ProgramEvents are immutable. Playout and downstream layers MAY rely on stability. Modification requires explicit operator override with atomic regeneration. |
| Open | Extendable | Not yet committed. The EPG layer extends into this window during horizon advancement, assigning new ProgramEvents and advancing the episode cursor. Content here MAY change until locked. |

The boundary between locked and open advances with wall-clock progression. ProgramEvents transition from open to locked as the lock window advances; they never transition back.

---

### Multi-Block Event Behavior

- A 60-minute program on a 30-minute grid spans 2 blocks. Both blocks reference the same ProgramEvent with `block_index_within_event` 0 and 1.
- A movie (90–180 minutes) MAY span 3–6 blocks. All blocks share the same `program_event_id`.
- Event completion is determined by event duration, not by block boundary. Content within each block is a portion of the full event, offset appropriately. The final block of a multi-block event may contain less content than the block duration; the remainder is filled per normal block composition rules.
- Block transitions within a multi-block event are governed by fence timing. Each block boundary is a fence; the playout engine enforces the fence regardless of whether the event continues into the next block.

Two distinct transition types exist at block boundaries:

| Transition Type | What Changes | Example |
|---|---|---|
| Intra-event | Execution container only; editorial identity unchanged | Block 5 → Block 6 within a 90-minute movie |
| Inter-event | Editorial identity and execution container | Block 7 (movie end) → Block 8 (next program) |

AIR treats all fences identically at the execution level. The distinction is editorial: intra-event boundaries do not change `program_event_id`; inter-event boundaries do. This distinction is observable by upper layers (EPG, as-run reporting, now/next signaling, analytics) but is transparent to the playout engine.

---

### Non-Goals

- Fence timing definition or modification. Block fence behavior is governed by runtime invariants.
- Frame budget authority. Frame-level pacing is an AIR responsibility.
- Priming semantics. Decoder priming and lookahead are runtime coordination concerns.
- Segment composition logic. How segments are built within a block (chapter slicing, break placement, filler selection) is governed by the Program Segmentation and Ad Avail Contract.
- This document defines editorial-to-execution mapping only.

---

### Future Extensions

- **Themed scheduling.** Day-type patterns (weekday, weekend, seasonal, holiday) influencing program selection and zone structure.
- **Live events.** ProgramEvents with indeterminate duration that override scheduled content and trigger downstream replanning.
- **Override insertion.** Operator-initiated replacement of ProgramEvents within the locked horizon, with atomic regeneration of affected blocks.
- **Preemption handling.** Breaking news or emergency content that displaces scheduled ProgramEvents with defined resume semantics.

---

**Document version:** 0.1
**Related:** [Schedule Manager Planning Authority (v0.1)](../contracts/ScheduleManagerPlanningAuthority_v0.1.md) · [Schedule Horizon Management (v0.1)](../contracts/ScheduleHorizonManagementContract_v0.1.md) · [Schedule Execution Interface (v0.1)](../contracts/ScheduleExecutionInterfaceContract_v0.1.md) · [Program Segmentation and Ad Avail (v0.1)](../contracts/ProgramSegmentationAndAdAvailContract_v0.1.md)
**Governs:** ProgramEvent identity, event-to-block mapping, episode advancement authority, horizon architecture
