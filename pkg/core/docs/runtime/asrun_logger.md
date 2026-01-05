# RetroVue Runtime — AsRunLogger

_Related: [Runtime: Channel manager](channel_manager.md) • [Runtime: Schedule service](schedule_service.md) • [Domain: MasterClock](../domain/MasterClock.md)_

> Records what actually aired for compliance, reporting, and audit.

## Purpose

AsRunLogger records what actually aired for compliance, reporting, and audit. It provides the authoritative record of what content was played and when, including proper handling of content that spans broadcast day boundaries.

**AsRunLogger logs events exactly as aired, splits across rollover only in data.**

**Example: HBO Movie 05:00–07:00**

- Movie starts at 05:00 local (Day A)
- Movie continues past 06:00 rollover
- Movie ends at 07:00 local (Day B)
- AsRunLogger creates two log entries:
  - Entry 1: 05:00–06:00 tagged with Day A label
  - Entry 2: 06:00–07:00 tagged with Day B label
- ChannelManager plays the movie seamlessly without interruption

## Behavior

For every aired segment, AsRunLogger logs:

- absolute UTC start/end
- channel-local start/end
- broadcast_day_label (from ScheduleService.broadcast_day_for)

If a single airing crosses broadcast day rollover, AsRunLogger is allowed — and expected — to create two rows:

- Row 1: up to rollover, tagged with previous day's label
- Row 2: after rollover, tagged with new day's label

**This split is intentional and correct for traffic/sales/compliance.**

ChannelManager does NOT split the airing. AsRunLogger splits only on paper.

**AsRunLogger must call ScheduleService.broadcast_day_for() to determine broadcast_day_label. It must not guess.**

## Core Responsibilities

### Logging Aired Content

- Record precise start/end times for all aired content
- Include both UTC and channel-local timestamps
- Tag each log entry with the correct broadcast day label

### Broadcast Day Boundary Handling

- Detect when content spans broadcast day rollover
- Create separate log entries for each broadcast day portion
- Ensure compliance reporting accuracy across day boundaries

### Integration Requirements

- Always use MasterClock for time operations
- Always use ScheduleService.broadcast_day_for() for day classification
- Never call datetime.now() or datetime.utcnow() directly
- Never guess broadcast day labels

## Integration with Other Components

### ScheduleService

- Calls broadcast_day_for() to determine correct day labels
- Never attempts to compute broadcast day independently
- Relies on ScheduleService for authoritative day classification

### ChannelManager

- Receives playback events and timing information
- Never attempts to modify playback timing
- Records what actually aired, not what was scheduled

### MasterClock

- Uses MasterClock for all time operations
- Ensures consistent timestamps across all log entries
- Never calls datetime.now() or datetime.utcnow() directly

### ProgramDirector

- May receive emergency override events for logging
- Coordinates with emergency response logging
- Never attempts to modify scheduling

## Log Entry Format

Each log entry includes:

```python
{
    "channel_id": str,
    "program_id": str,
    "title": str,
    "start_utc": datetime (tz-aware UTC),
    "end_utc": datetime (tz-aware UTC),
    "start_local": datetime (tz-aware, channel-local),
    "end_local": datetime (tz-aware, channel-local),
    "broadcast_day_label": date,
    "is_split_entry": bool,
    "split_reason": str | None
}
```

## Split Entry Handling

When content spans broadcast day rollover:

1. Create first entry ending at rollover time
2. Create second entry starting at rollover time
3. Mark both entries with is_split_entry = True
4. Include split_reason = "broadcast_day_rollover"
5. Use correct broadcast_day_label for each entry

This ensures accurate compliance reporting while maintaining the integrity of the continuous airing.

## Responsibilities

| Action                               | Description                                 |
| ------------------------------------ | ------------------------------------------- |
| **Record precise start/end times**   | For all aired content                       |
| **Include UTC and local timestamps** | Both timezone-aware                         |
| **Tag with broadcast day label**     | Using ScheduleService.broadcast_day_for()   |
| **Detect rollover content**          | When content spans broadcast day boundaries |
| **Create separate log entries**      | For each broadcast day portion              |
| **Ensure compliance accuracy**       | Across day boundaries                       |

## Forbidden Actions

| Action                                  | Reason                                       |
| --------------------------------------- | -------------------------------------------- |
| **Call datetime.now() directly**        | Must use MasterClock                         |
| **Call datetime.utcnow() directly**     | Must use MasterClock                         |
| **Guess broadcast day labels**          | Must use ScheduleService.broadcast_day_for() |
| **Modify playback timing**              | Only records what aired                      |
| **Compute broadcast day independently** | Must ask ScheduleService                     |

## Integration with Other Components

### ScheduleService

- Calls broadcast_day_for() to determine correct day labels
- Never attempts to compute broadcast day independently
- Relies on ScheduleService for authoritative day classification

### ChannelManager

- Receives playback events and timing information
- Never attempts to modify playback timing
- Records what actually aired, not what was scheduled

### MasterClock

- Uses MasterClock for all time operations
- Ensures consistent timestamps across all log entries
- Never calls datetime.now() or datetime.utcnow() directly

### ProgramDirector

- May receive emergency override events for logging
- Coordinates with emergency response logging
- Never attempts to modify scheduling

## Log Entry Format

Each log entry includes:

```python
{
    "channel_id": str,
    "program_id": str,
    "title": str,
    "start_utc": datetime (tz-aware UTC),
    "end_utc": datetime (tz-aware UTC),
    "start_local": datetime (tz-aware, channel-local),
    "end_local": datetime (tz-aware, channel-local),
    "broadcast_day_label": date,
    "is_split_entry": bool,
    "split_reason": str | None
}
```

## Split Entry Handling

When content spans broadcast day rollover:

1. Create first entry ending at rollover time
2. Create second entry starting at rollover time
3. Mark both entries with is_split_entry = True
4. Include split_reason = "broadcast_day_rollover"
5. Use correct broadcast_day_label for each entry

This ensures accurate compliance reporting while maintaining the integrity of the continuous airing.

## Cross-References

| Component                                  | Relationship                                        |
| ------------------------------------------ | --------------------------------------------------- |
| **[ScheduleService](schedule_service.md)** | Provides broadcast_day_for() for day classification |
| **[ChannelManager](channel_manager.md)**  | Provides playback events and timing information     |
| **[MasterClock](../domain/MasterClock.md)**          | Provides consistent timestamps for all log entries  |
| **[ProgramDirector](program_director.md)** | Coordinates emergency response logging              |

_Document version: v0.1 · Last updated: 2025-10-24_
