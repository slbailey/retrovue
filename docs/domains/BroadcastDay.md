# Domain: BroadcastDay

## Purpose

A **BroadcastDay** defines the programming-day boundary for a channel.

- Groups **ScheduleItems** for a single programming day, defined by the channel’s `programming_day_start`.

### Example

```yaml
channel: nightmare-theater
programming_day_start: 06:00
broadcast_day: 2026-03-03
```

- **Range:**  
  `2026-03-03 06:00` → `2026-03-04 06:00`

---

## Persistence: `broadcast_days` Table

| Column         | Type                    | Notes                        |
|----------------|-------------------------|------------------------------|
| id             | uuid, primary key       |                              |
| channel_id     | fk → channels.id        |                              |
| broadcast_day  | date                    | Programming day              |
| range_start    | timestamp with time zone| Day start (e.g. 06:00)       |
| range_end      | timestamp with time zone| Day end (e.g. next day 06:00)|
| created_at     | timestamp with time zone|                              |

---

## Relationships

- **BroadcastDay**
  └── **ScheduleItems** (1-many, grouped by date)

---

## Derived View

ScheduleDay is not an editorial authority. ScheduleDay is a derived grouping of ScheduleItems that fall within a broadcast_day boundary. ScheduleDay exists for operational and API convenience but does not own ScheduleItems. ScheduleItems remain owned by their ScheduleRevision.

```
ScheduleRevision
   ↓
ScheduleItem (multiple)
   ↓ grouped by date
ScheduleDay
```

---

## System Invariants

Defined in:  
`docs/contracts/invariants/core/scheduling/`

### INV-SCHEDULE-ITEM-TIMELINE-001  
A ScheduleItem must define a valid timeline.

- `start_at < end_at`
- `slot_duration_sec > 0`
- `episode_duration_sec ≤ slot_duration_sec`

---

### INV-SCHEDULE-ITEM-UNIQUE-SLOT-002  
A channel may not have two ScheduleItems starting at the same time.

- Constraint: `UNIQUE(channel_id, start_at)`

---

### INV-SCHEDULE-ITEM-WITHIN-DAY-003  
A ScheduleItem must fall entirely within its BroadcastDay range.

- `range_start ≤ start_at`
- `end_at ≤ range_end`

---

### INV-SCHEDULE-ITEM-GRID-ALIGNMENT-004  
ScheduleItems must align with the channel grid.

- Example:  
  `grid_block_minutes = 30`  
  Valid starts: `:00`, `:30`

---

## Contract Tests

Tests validating these invariants are in:  
`tests/contracts/scheduling/`

- **test_schedule_item_timeline.py**
  - `test_start_before_end`
  - `test_slot_duration_positive`
  - `test_episode_duration_not_exceed_slot`
- **test_schedule_item_unique_slot.py**
  - `test_two_items_same_start_rejected`
- **test_schedule_item_within_day.py**
  - `test_item_within_day_range`
  - `test_item_cannot_cross_day_boundary`
- **test_schedule_item_grid_alignment.py**
  - `test_valid_grid_start`
  - `test_invalid_grid_start_rejected`

---

## Implementation Protocol

Only after all tests pass:

- Implement `schedule_items` table
- ORM model
- Compiler write path

> **Sequence:** contracts → tests → implementation

---

## Rationale

**ScheduleItem** is the foundation of the entire system. All playout and editorial logic hangs off it:

```
ScheduleItem
   ↓
PlaylistEvent
   ↓
segments
```

Once ScheduleItem is established:

- Operator CLI schedule commands are enabled
- JSON schedule blobs are eliminated
- Operator workflows are simplified
- Schedule debugging becomes trivial

---