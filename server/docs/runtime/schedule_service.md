# RetroVue Runtime — ScheduleService

_Related: [Runtime: Channel manager](channel_manager.md) • [Domain: MasterClock](../domain/MasterClock.md) • [Runtime: Program director](program_director.md)_

> **Note:** This document reflects the modern scheduling architecture.  
> The active scheduling chain is: **SchedulePlan → ScheduleDay → Playlist → PlaylogEvent → AsRunLog.**

> Station's programming authority for "what should air, and when."

## Purpose

SchedulingService is the station's programming authority for "what should air, and when."

All other runtime components (ChannelManager, ProgramDirector, AsRunLogger, the future guide, etc.) rely on it for schedule interpretation.

SchedulingService owns broadcast day logic and channel timing policy. No other component may redefine or guess these rules.

## Content Authority Constraint

**SchedulingService may only schedule Asset entries that are marked as approved for broadcast.**

SchedulingService is forbidden from:

- Fetching raw content directly from Plex, filesystem, or unreviewed sources
- Scheduling unapproved or non-canonical content
- Bypassing Content Manager for content decisions

If no approved content exists for a slot, this is a scheduling failure. ChannelManager must not improvise replacement content.

## Broadcast Day Model (6:00 → 6:00 local)

Each channel has a broadcast day that does not run midnight→midnight.

The broadcast day starts at a channel-specific rollover minute after local midnight (default: 6:00am local, i.e. 360 minutes).

The broadcast day ends just before the next day's rollover.

At 2:00am local, you may still be in "yesterday's" broadcast day.

At 5:30am local, you're still in the previous broadcast day.

At 6:15am local, you're in the new broadcast day.

**Broadcast day is an accounting/reporting construct for station operations.**

**It is NOT a hard playout cut point.**

### SchedulingService Methods

#### `broadcast_day_for(channel_id, when_utc) -> date`

Given a UTC timestamp, return the broadcast day label (a date) for that channel.

**Steps:**

1. Convert when_utc (aware datetime in UTC) to local time
2. If local_time.time() >= 06:00, broadcast day label is local_time.date()
3. Else, broadcast day label is (local_time.date() - 1 day)
4. Return that label as a date object

#### `broadcast_day_window(channel_id, when_utc) -> tuple[datetime, datetime]`

Return (start_local, end_local) for the broadcast day that contains when_utc, in local time (tz-aware datetimes).

- start_local = YYYY-MM-DD 06:00:00
- end_local = (YYYY-MM-DD+1) 05:59:59.999999

#### `active_segment_spanning_rollover(channel_id, rollover_start_utc)`

Given the UTC timestamp for rollover boundary (which is local 06:00:00), return info about any scheduled content that STARTED BEFORE rollover and CONTINUES AFTER rollover.

**Returns:**

- None if nothing is carrying over
- Otherwise return a dict with:
  - program_id: identifier/title/asset ref
  - absolute_start_utc: aware UTC datetime
  - absolute_end_utc: aware UTC datetime
  - carryover_start_local: tz-aware local datetime at rollover start
  - carryover_end_local: tz-aware local datetime when the asset actually ends

### Rollover Handling

A broadcast day schedule may legally include an item whose end is AFTER the 06:00 turnover, if it began before 06:00. The next broadcast day must treat that carried segment as already in progress; it cannot schedule new content under it until it finishes.

**Example: HBO Movie 05:00–07:00**

- Movie starts at 05:00 local (Day A)
- Movie continues past 06:00 rollover
- Movie ends at 07:00 local (Day B)
- Day B's schedule must account for 06:00–07:00 being occupied by carryover

**When building the next broadcast day, ScheduleService must honor rollover carryover. If the previous day's programming continues past rollover, the new broadcast day does not start scheduling fresh content until that carryover ends.**

**Example: If rollover is 06:00 but a movie runs to 07:00, the first schedulable slot for the new day is 07:00, not 06:00.**

This maintains broadcast discipline and prevents double-scheduling conflicts.

## Critical Rules

**ChannelManager never snaps playback at 06:00.**

**AsRunLogger may split one continuous asset across two broadcast days in reporting. That's expected, not an error.**

## Implementation Notes

- APIs accept/return tz-aware UTC datetimes; local-time projections are derived using the system's local timezone.
- If something naive is passed in, raise ValueError.
- Avoid manual timezone arithmetic; prefer standard library conversions.

### Channel Timing Policy

Each channel carries its own timing policy configuration:

- **grid_slot_size_minutes**: Natural planning granularity.
  - Examples:
    - 30 for traditional half-hour grids
    - 15 for movie channels that align promos around film starts/ends
    - 60 for pure longform channels
- **grid_slot_offset_minutes**: Offset from the top of the hour that this channel uses for "starts."
  - Examples:
    - 0 means :00/:30
    - 5 means :05/:35 (classic TBS-style)
- **broadcast_day_start**: Local-time anchor when a new broadcast day begins for that channel (HH:MM).
  - Default: 06:00.
  - Examples: 06:05, 05:00, etc.

SchedulingService is responsible for honoring these policies when extending the plan horizon and building the runtime playlog.

No other component should assume "programs always start on :00/:30" or "broadcast day always rolls at 6:00am."

In v0.1, most channels will likely use:

- grid_slot_size_minutes = 30
- grid_slot_offset_minutes = 0
- broadcast_day_start = 06:00

But the design and interfaces assume per-channel flexibility so we don't have to redesign later.

## Horizon Generation (Scheduler Daemon)

RetroVue maintains a forward "horizon" of scheduled segments for continuous broadcast operations.

- **Near-term horizon** (for ChannelManager playout): precise, second-accurate playout plan for the next ~1–2 hours.
- **Longer horizon** (for preview / guide / UI): higher-level programming blocks for the next several hours or next day(s).

A background loop (scheduler_daemon / horizon builder) keeps these horizons generated.

### Loop Contract

1. Ask MasterClock.now_utc() for the current authoritative time.
2. For each Channel, ask SchedulingService:
   - "Based on this channel's timing policy and broadcast day rollover rules, what's supposed to air next?"
   - "Do we already have scheduled segments covering from now out to the target horizon window?"
   - "If not, generate more future segments."
3. Persist/emit those segments for runtime.

**MasterClock remains passive. It does not fire callbacks or timers. The scheduler_daemon polls MasterClock for time instead of registering 'wake me at 06:00' listeners.**

**SchedulingService never calls datetime.now() directly. It always works from explicit timestamps provided by the daemon, which come from MasterClock.**

## ScheduledSegment Model

ScheduledSegment represents what SchedulingService emits for downstream consumers:

```python
ScheduledSegment:
    channel_id: str
    program_id: str
    title: str

    start_utc: datetime (tz-aware UTC)
    end_utc: datetime (tz-aware UTC)

    start_local: datetime (tz-aware, channel-local)
    end_local: datetime (tz-aware, channel-local)

    broadcast_day_label: date
        - Result of broadcast_day_for(channel_id, start_utc)
        - Used by reporting, compliance, "what aired on Thursday"

    is_continuation: bool
        - True if this segment began before the current planning window or
          continues across a broadcast day rollover
```

- ChannelManager consumes these ScheduledSegments to know what to play now and how far into it we are.
- AsRunLogger uses them for logging actual air events (including splitting at broadcast day boundaries for reporting).
- The future Prevue-style guide channel will consume them to render "what's on now / next," but its visual 30-minute buckets are just presentation. Those 30-minute buckets are NOT written back into the schedule model.

**There is no stored "30-minute grid row" in the authoritative schedule. The 30-minute row is a presentation trick for the guide UI, not a scheduling primitive.**

## Responsibilities

| Component            | Responsibilities                                                                                                                                                                                                                             |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **SchedulingService**  | • Owns broadcast day math<br>• Owns per-channel timing policy<br>• Extends the plan horizon and knows where the "next schedulable slot" begins after rollover<br>• Provides ScheduledSegments for downstream consumers                            |
| **scheduler_daemon** | • Polls MasterClock for "now"<br>• Asks SchedulingService to extend the plan horizon<br>• Never invents timing rules on its own                                                                                                                        |
| **ChannelManager**   | • Plays what ScheduleService/horizon gave it<br>• Never snaps content at broadcast day rollover<br>• Never tries to reschedule mid-flight                                                                                                    |
| **ProgramDirector**  | • Coordinates channels and emergency overrides<br>• May ask "what's airing now?" and "which broadcast day are we in?" but cannot reschedule or cut at rollover                                                                               |
| **AsRunLogger**      | • Uses ScheduledSegments and SchedulingService.broadcast_day_for() to log what aired<br>• Is allowed to break a single continuous airing into multiple reporting rows when it crosses broadcast day<br>• This split is intentional and correct |
| **MasterClock**      | • Provides UTC and channel-local "now"<br>• Does not know what a broadcast day is<br>• Does not accept timers, listeners, alarms, or scheduling callbacks<br>• Is the only valid source of current time for the system                       |

## Testing

Use the `retrovue test broadcast-day-alignment` command to validate broadcast day logic and rollover handling. This test validates the HBO-style 05:00–07:00 scenario and ensures proper broadcast day classification.

SchedulingService operates on Channel entities using UUID identifiers for external operations and logs.

## Cross-References

| Component                                  | Relationship                                                      |
| ------------------------------------------ | ----------------------------------------------------------------- |
| **[MasterClock](../domain/MasterClock.md)**          | Provides authoritative station time for all scheduling operations |
| **[ChannelManager](channel_manager.md)**  | Consumes ScheduledSegments for playout execution                  |
| **[AsRunLogger](asrun_logger.md)**         | Uses broadcast_day_for() for compliance reporting                 |
| **[ProgramDirector](program_director.md)** | Queries SchedulingService for current airing status                 |

_Document version: v0.1 · Last updated: 2025-10-24_
