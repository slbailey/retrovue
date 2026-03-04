# Domain: ScheduleItem

## Purpose

A **ScheduleItem** defines a single editorial airing on a channel's timeline.  
It corresponds to exactly one grid-aligned program slot, selected by the scheduling system.  
**ScheduleItem** is the canonical, persistent unit of editorial scheduling. It replaces the previous `program_blocks` (JSON in `ProgramLogDay.program_log_json`).

**Key capabilities provided by ScheduleItem:**
- Direct SQL inspection of the schedule
- Targeted operator modifications
- Deterministic expansion into playout segments
- Relational integrity checks on the broadcast timeline

> **Note:**  
> ScheduleItem does *not* define playout segments.  
> Segments are generated later during block expansion.

---

## Persistence: `schedule_items` Table

| Column                | Type                           | Notes                                    |
|-----------------------|--------------------------------|------------------------------------------|
| id                    | uuid, primary key              |                                          |
| channel_id            | fk → channels.id               |                                          |
| broadcast_day_id      | fk → broadcast_days.id         |                                          |
| title                 | text                           | Program or segment title                 |
| asset_id              | text or uuid (references asset)|                                          |
| start_at              | timestamp with time zone       | Slot start                              |
| end_at                | timestamp with time zone       | Slot end                                |
| slot_duration_sec     | integer                        | Slot length in seconds                  |
| episode_duration_sec  | integer                        | Actual program length in seconds        |
| collection            | text                           | Source collection name                   |
| selector_json         | jsonb                          | Editorial/selection logic                |
| slot_index            | integer                        | Position within grid                     |
| created_at            | timestamp with time zone       |                                          |
| updated_at            | timestamp with time zone       |                                          |

---

## Scheduling Interaction

**ScheduleItems** are created during DSL schedule compilation.

**Pipeline:**
```
DSL schedule
   ↓
schedule compiler
   ↓
ScheduleItem row(s)
```
Each compiled program block → **one** ScheduleItem.

---

## Runtime Interaction

When playout requires a block:

```
ScheduleItem
   ↓
expand_program_block()
   ↓
ScheduledBlock
   ↓
PlaylistEvent
```
**ScheduleItem** provides:
- Start time
- Slot duration
- Asset reference
- Editorial metadata

Segments are generated during block expansion and do **not** modify the original ScheduleItem.

---

## Operator Workflows

**ScheduleItem** enables direct operator commands:

- `schedule list`
- `schedule reschedule <uuid>`
- `schedule inspect <uuid>`
- `schedule delete <uuid>`

Operators interact with discrete ScheduleItem rows — not monolithic broadcast-day artifacts.

---

## Naming & Identity Rules

- ScheduleItem identifiers: **UUID** (generated at creation)
- **Editorial identity:**  
  Uniquely defined by `(channel_id, start_at)`
  This composite **must be unique per channel**

---

## Ownership

Each ScheduleItem belongs to exactly one ScheduleRevision. ScheduleItems MUST NOT exist outside a revision. ScheduleItems inherit their editorial authority from the revision that contains them. ScheduleItems are immutable once their parent ScheduleRevision becomes active.

---