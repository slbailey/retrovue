_Related: [Architecture](../architecture/ArchitectureOverview.md) • [Runtime](../runtime/ChannelManager.md) • [Operator CLI](../cli/README.md) • [Contracts](../contracts/resources/README.md) • [Channel](Channel.md) • [SchedulePlan](SchedulePlan.md) • [Program](Program.md) • [Playlist](../architecture/Playlist.md) • [PlaylogEvent](PlaylogEvent.md)_

# Domain — Schedule day

> **Note:** This document reflects the modern scheduling architecture. Active chain: **SchedulePlan (Zones + SchedulableAssets) → ScheduleDay (resolved) → Playlist → PlaylogEvent (runtime) → AsRunLog.**

## Purpose

ScheduleDay represents the **"Planned" layer** in the scheduling architecture. It is a **resolved, immutable daily schedule** for a specific channel and calendar date that **defines what airs when during a channel's broadcast day**. **It is derived from [SchedulePlan](SchedulePlan.md) using Zones (time windows) that hold SchedulableAssets (Programs, Assets, VirtualAssets, SyntheticAssets) directly. If multiple plans are active, priority resolves overlapping Zones.** ScheduleDay is materialized 3–4 days in advance. Once generated, the schedule day is **frozen** (locked and immutable) unless force-regenerated or manually overridden by an operator.

**EPG Foundation:** ScheduleDay serves as the **basis for the EPG (electronic program guide)**. The EPG references ScheduleDay as the authoritative source for "what will air when" on a channel. ScheduleDay's SchedulableAsset placements and wall-clock times are used to generate EPG data for viewers.

**Broadcast-Day Display:** All timestamps shown in human-readable outputs are relative to the channel broadcast day start. For example, if a channel's broadcast day starts at 06:00, then `06:00` in the human-readable output represents midnight + 6 hours (the start of the broadcast day). Human-readable times in plan show and ScheduleDay views reflect channel broadcast-day start (e.g., if channel starts at 06:00, human times offset accordingly: 06:00 → 05:59 next day). JSON outputs can keep canonical times (00:00–24:00), but include `broadcast_day_start` so UIs can offset.

**Background/Test Pattern Zones:** Background and test pattern zones don't need to appear in the human-readable plan output, but may exist in JSON for system use. Human-readable views focus on program content, while JSON outputs include all zones (including background/test patterns) with technical metadata for system operations.

The schedule day contains the resolved schedule for a channel on a specific date, with SchedulableAssets (Programs, Assets, VirtualAssets, SyntheticAssets) placed in Zones. **Wall-clock times are calculated by anchoring Zone time windows to the channel's Grid boundaries** (`grid_block_minutes`, `block_start_offsets_minutes`, `programming_day_start`). Zones declare when they apply (e.g., base 00:00–24:00, or After Dark 22:00–05:00), and SchedulableAssets placed in Zones define what content plays during those windows.

ScheduleDay contains **SchedulableAsset references** (Programs, Assets, VirtualAssets, SyntheticAssets) placed in Zones. These SchedulableAssets remain intact in ScheduleDay — expansion to physical assets occurs later at playlist generation.

[Playlists](../architecture/Playlist.md) are generated from ScheduleDay for execution. This is the execution-time view of "what will air on this channel on this date" after resolving Zones and their SchedulableAssets.

## Persistence model

ScheduleDay is managed by SQLAlchemy with the following fields:

- **id** (UUID, primary key): Unique identifier for relational joins and foreign key references
- **channel_id** (UUID, required, foreign key): Reference to Channel
- **plan_id** (UUID, optional, foreign key): Reference to SchedulePlan that generated this schedule day
- **schedule_date** (Text, required): Broadcast date in "YYYY-MM-DD" format
- **is_manual_override** (Boolean, required, default: false): Whether this schedule day was manually overridden
- **created_at** (DateTime(timezone=True), required): Record creation timestamp
- **updated_at** (DateTime(timezone=True), required): Record last modification timestamp

ScheduleDay has a unique constraint on (channel_id, schedule_date) ensuring only one schedule per channel per date.

**Note:** While `plan_id` is optional, the system typically generates schedule days from plans. Manual overrides may not reference a plan.

### Table name

The table is named `broadcast_schedule_days` (plural). Schema migration is handled through Alembic. Postgres is the authoritative backing store.

### Constraints

- `schedule_date` must be in "YYYY-MM-DD" format
- Unique constraint on (channel_id, schedule_date) ensures only one schedule per channel per broadcast day
- Foreign key constraints ensure channel_id and plan_id reference valid entities

## Contract / interface

ScheduleDay is a resolved, immutable daily schedule **derived from [SchedulePlan](SchedulePlan.md) using Zones (time windows) that hold SchedulableAssets (Programs, Assets, VirtualAssets, SyntheticAssets) directly. If multiple plans are active, priority resolves overlapping Zones.** ScheduleDay is **materialized 3–4 days in advance**. It provides the concrete schedule for a specific channel and calendar date. Once generated, the schedule day is **frozen** (locked and immutable) unless force-regenerated or manually overridden. It contains SchedulableAssets placed in Zones with real-world wall-clock times. SchedulableAssets remain intact in ScheduleDay — expansion to physical assets occurs at playlist generation. It defines:

- Channel assignment (channel_id) - the channel this schedule applies to
- Plan reference (plan_id) - the [SchedulePlan](SchedulePlan.md) that generated this schedule (may reference the highest-priority plan when multiple plans are layered)
- Date assignment (schedule_date) - the calendar date for this schedule
- **Broadcast-day start** - channel's broadcast-day start time (e.g., "06:00") for display offset calculation
- SchedulableAsset placements - Programs, Assets, VirtualAssets, and SyntheticAssets placed in Zones
- Real-world wall-clock times - calculated by anchoring Zone time windows to the channel's Grid boundaries (`grid_block_minutes`, `block_start_offsets_minutes`, `programming_day_start`) to produce final wall-clock times
- Manual override flag (is_manual_override) - indicates if this was manually overridden
- Unique constraint ensuring one schedule per channel per date

Schedule days are the resolved output of the planning process. They are **derived from [SchedulePlan](SchedulePlan.md) using Zones (time windows) that hold SchedulableAssets (Programs, Assets, VirtualAssets, SyntheticAssets) directly. If multiple plans are active, priority resolves overlapping Zones.** ScheduleDays are **materialized 3–4 days in advance**, then **frozen** after generation. They represent "what will actually air" after resolving active plans for a given channel and date into concrete schedules with SchedulableAssets placed in Zones, wall-clock times anchored to the channel's Grid boundaries. **SchedulableAssets remain intact in ScheduleDay and expand to physical assets at playlist generation, not at ScheduleDay time.** Manual overrides are permitted post-generation even after the schedule day has been frozen.

## Execution model

ScheduleService generates ScheduleDay records **derived from active [SchedulePlans](SchedulePlan.md) using Zones (time windows) that hold SchedulableAssets (Programs, Assets, VirtualAssets, SyntheticAssets) directly for a given channel and date. If multiple plans are active, priority resolves overlapping Zones.** Schedule days are **materialized 3–4 days in advance** to provide stable schedules for EPG and playout systems. The process:

1. **Plan resolution**: For a given channel and date, identify all applicable active [SchedulePlans](SchedulePlan.md) (based on cron_expression, date ranges, priority). Apply priority-based layering where more specific plans override generic ones. Zones from higher-priority plans override overlapping Zones from lower-priority plans.
2. **Zone resolution**: Retrieve Zones (time windows) and their SchedulableAssets from the matching plan(s)
3. **Time calculation**: Calculate real-world wall-clock times by anchoring Zone time windows to the channel's Grid boundaries:
   - Zones declare when they apply (e.g., base 00:00–24:00, or After Dark 22:00–05:00)
   - All scheduling snaps to the Channel's Grid boundaries (`grid_block_minutes`, `block_start_offsets_minutes`, `programming_day_start`)
   - Final wall-clock times are calculated based on Zone time windows and Grid alignment
4. **Schedule generation**: Create ScheduleDay record with SchedulableAssets placed in Zones, wall-clock times, and broadcast-day start time. SchedulableAssets remain intact in ScheduleDay — expansion to physical assets occurs at playlist generation.
5. **Freezing**: Once generated, the schedule day is **frozen** (locked and immutable) unless force-regenerated or manually overridden by an operator
6. **Playlist generation**: Generate [Playlist](../architecture/Playlist.md) entries from the resolved schedule. At playlist generation, SchedulableAssets expand to physical Assets: Programs expand their asset chains based on play_mode, and VirtualAssets expand to physical Assets.

**Time Resolution:** Real-world wall-clock times in the schedule day are calculated by anchoring Zone time windows to the channel's Grid boundaries (`grid_block_minutes`, `block_start_offsets_minutes`, `programming_day_start`). Zones declare when they apply, and SchedulableAssets placed in Zones define what content plays. This ensures all schedule times are properly aligned to the channel's Grid.

**SchedulableAsset Resolution:** ScheduleDay contains SchedulableAssets (Programs, Assets, VirtualAssets, SyntheticAssets) placed in Zones. These SchedulableAssets remain intact in ScheduleDay — expansion to physical assets occurs later at playlist generation.

## Resolution Semantics for Zones + SchedulableAssets

ScheduleDay generation resolves Zones and their SchedulableAssets into concrete asset placements with precise timing. The resolution process follows these semantics:

### Zone and SchedulableAsset Resolution

**For each Zone, place its SchedulableAssets in the Zone's window, snapping to the Channel grid:**

1. **Zone identification**: Identify all active Zones from SchedulePlans for the channel and date. If multiple plans are active, priority resolves overlapping Zones.
2. **SchedulableAsset retrieval**: For each Zone, retrieve its SchedulableAssets (Programs, Assets, VirtualAssets, SyntheticAssets)
3. **SchedulableAsset placement**: Place SchedulableAssets in the Zone's active window, snapping to the Channel's Grid boundaries (`grid_block_minutes`, `block_start_offsets_minutes`, `programming_day_start`)
4. **Grid alignment**: All content placement snaps to valid grid boundaries; no fractional-minute scheduling

### SchedulableAsset Resolution

**Each SchedulableAsset in the Zone resolves based on its type:**

- **Programs**: Programs are SchedulableAssets with asset_chain (linked list of SchedulableAssets) and play_mode. At playlist generation, Programs expand their asset chains based on play_mode (random, sequential, manual).
- **Assets**: Assets are physical file assets that resolve directly to file paths.
- **VirtualAssets**: VirtualAssets are SchedulableAssets that expand to physical Assets at playlist generation. They behave like regular assets during scheduling but expand to one or more physical Assets at playlist generation.
- **SyntheticAssets**: SyntheticAssets are generated content (e.g., test patterns) that resolve to synthetic content specifications.

### Block Consumption and Avails

**Underfill inside a block becomes avails; overlength consumes additional blocks if allowed:**

- **Underfill**: If content runtime is shorter than the allocated grid block(s), the remaining time becomes an **avail** (gap that can be filled with commercials or filler content)
- **Overlength**: If content runtime exceeds the allocated grid block(s), it consumes additional blocks if:
  - The Program has a `slot_units` override that allows the expansion, or
  - The series pick (for series Programs) naturally requires multiple blocks
- **No mid-longform cuts**: Longform content (with `slot_units` override) is **never cut mid-play**. It always consumes the full number of blocks specified by `slot_units` or required by its duration.

### Soft-Start and Carry-In

**Soft-start & carry-in policies handle Zone transitions and day boundaries:**

- **Soft-start-after-current**: If a Zone opens while content is already playing (in-flight content from a previous Zone), the current content continues to completion. The new Zone's SchedulableAssets begin at the **next valid Grid boundary** after the current content ends. This prevents mid-program interruptions.
- **Carry-in across broadcast day seams**: If content crosses the programming-day seam (e.g., a program starting at 23:30 continues past midnight), Day+1 starts with a **carry-in** until the content completes. The carry-in content is part of Day+1's schedule but originated from Day's plan resolution.

**Example:**
- Zone A: 19:00–22:00 with SchedulableAssets [Program A, Program B]
- Zone B: 20:00–22:00 with SchedulableAssets [Movie Program]
- If Program A is still playing at 20:00 when Zone B opens, Program A continues to completion, and Zone B's Movie Program starts at the next grid boundary after Program A ends.

**Cross-Day Carryover Example:**

If a movie starts at 5:00 AM and ends at 7:00 AM, it belongs to the 5:00–6:00 portion of the prior day's plan, but will carry into the next broadcast day's runtime log seamlessly.

**Timeline (assuming `programming_day_start=06:00`):**

```
Broadcast Day 1 (Jan 15)          Broadcast Day 2 (Jan 16)
06:00 ──────────────────────────── 06:00 ────────────────────────────
                                    │
                                    │ programming_day_start
                                    │
                                    ▼
                    ┌─────────────────────────────┐
                    │ Movie starts at 05:00       │
                    │ (Day 1's plan, Zone 05:00-06:00)
                    │                             │
                    │ Movie continues...          │
                    │                             │
                    │ Movie ends at 07:00         │
                    │ (carries into Day 2)        │
                    └─────────────────────────────┘
                                    │
                                    │ Day 2's first Zone
                                    │ starts at 07:00
                                    │ (next grid boundary)
                                    ▼
```

**Key Points:**
- The movie (05:00–07:00) is scheduled by **Day 1's plan** (Zone covering 05:00–06:00)
- The movie **carries into Day 2's runtime** seamlessly, ending at 07:00
- Day 2's first Zone starts at the next grid boundary after the carry-in completes (07:00)
- The carry-in content appears in **Day 2's ScheduleDay** and runtime log, but originated from **Day 1's plan resolution**
- This ensures seamless transitions across broadcast day boundaries without content interruption

### Immutability and EPG Truthfulness

ScheduleDay maintains these critical properties:

- **Resolved & immutable**: Once generated, ScheduleDay is **frozen** (locked and immutable) unless force-regenerated or manually overridden. Schedule days are materialized **3–4 days in advance** to provide stable schedules.
- **EPG truthfulness**: The EPG references ScheduleDay as the source of truth for "what will air when." ScheduleDay's SchedulableAsset placements and wall-clock times are authoritative for EPG generation.
- **Playlog generation from Playlist**: [PlaylogEvents](PlaylogEvent.md) are generated from [Playlist](../architecture/Playlist.md), which is generated from ScheduleDay. The Playlist contains resolved physical assets with absolute timecodes. PlaylogEvents are then created from Playlist entries, aligned to MasterClock, providing the playout events that drive actual broadcast execution.

**Playback Instructions:** Resolved ScheduleDay assets include playback instructions derived from the assignments in the matching plan. These instructions include:
- Episode selection policies (for series content)
- Playback rules (chronological, random, seasonal, etc.)
- Operator intent metadata
- Content selection constraints

**Critical Rule:** Once generated, ScheduleDay is **frozen** (locked and immutable). Schedule days are materialized 3–4 days in advance and remain frozen to ensure the EPG and playout systems have a stable view of "what will air." The only ways to modify a frozen schedule day are:
- **Force regeneration**: Recreate the schedule day from its plan(s) with updated content based on the current plan state
- **Manual override**: Operators can manually override a frozen schedule day post-generation, creating a new ScheduleDay with `is_manual_override=true`. This breaks the link to the plan but preserves the schedule for that specific date

**Force Regeneration:** Operators can force-regenerate a schedule day from its plan(s), which recreates the schedule day with updated content selections and times based on the current plan state. This is useful after plan updates.

**Manual Overrides (Post-Generation):** Operators can manually override a frozen schedule day post-generation for special events, breaking news, or one-off programming changes. This creates a new ScheduleDay with `is_manual_override=true`, which breaks the link to the plan but preserves the schedule for that specific date. Manual overrides are permitted even after the schedule day has been frozen.

## Freezing and Playlog Generation

**Schedule Day Freezing:** Once a ScheduleDay is created (materialized 3–4 days in advance), it is **frozen** (locked and immutable). This freezing ensures:
- EPG systems have a stable reference for "what will air"
- Playout systems can rely on consistent schedule data
- Changes to the source [SchedulePlan](SchedulePlan.md) do not automatically affect already-generated schedule days

The only ways to modify a frozen schedule day are:
- **Force regeneration**: Operators can force-regenerate the schedule day from its plan(s), which recreates it with updated content based on the current plan state
- **Manual override (post-generation)**: Operators can manually override the frozen schedule day post-generation, creating a new ScheduleDay record with `is_manual_override=true`. Manual overrides are permitted even after the schedule day has been frozen

**PlaylogEvent Generation:** [PlaylogEvents](PlaylogEvent.md) are generated from [Playlist](../architecture/Playlist.md), which is generated from the resolved ScheduleDay. The Playlist contains resolved physical assets with absolute timecodes. PlaylogEvents are then created from Playlist entries, aligned to MasterClock. This generation happens after the schedule day is created and locked, ensuring playout events are based on stable, immutable schedule data.

## Playlist Expansion

ScheduleDay expands into a [Playlist](../architecture/Playlist.md) for execution. The Playlist is the resolved pre–AsRun list of physical assets with absolute timecodes ready for playout.

**Expansion Process:**

1. **SchedulableAsset Resolution**: SchedulableAssets in ScheduleDay (Programs, Assets, VirtualAssets, SyntheticAssets) are resolved to physical Assets. Programs expand their asset chains based on `play_mode` (random, sequential, manual).

2. **VirtualAsset Expansion**: VirtualAssets expand into one or more physical Assets at playlist generation. Each VirtualAsset in the schedule day resolves to concrete file assets.

3. **Program Chain Expansion**: Programs expand their asset chains based on `play_mode`:
   - **random**: Assets in chain are selected randomly
   - **sequential**: Assets in chain are played in order
   - **manual**: Assets are selected manually by operators

4. **Timecode Calculation**: Absolute start/end times are calculated for each physical asset based on the ScheduleDay's wall-clock times and Grid boundaries.

5. **Playlist Creation**: Playlist entries are created with:
   - `asset_id`: Reference to resolved physical Asset
   - `source_slot_id`: Reference to source ScheduleDay slot
   - `start_time` and `end_time`: Absolute timecodes for playout
   - `ffmpeg_input`: File path or input specification for ffmpeg

**Pipeline Flow:**

```
ScheduleDay (SchedulableAssets in Zones)
    ↓
Playlist (resolved physical assets with absolute timecodes)
    ↓
Playlog (runtime execution plan aligned to MasterClock)
    ↓
AsRun (observed ground truth)
```

**Key Points:**

- ScheduleDay contains SchedulableAssets (Programs, Assets, VirtualAssets, SyntheticAssets) placed in Zones
- Playlist generation resolves SchedulableAssets to physical Assets with concrete file paths
- VirtualAssets expand at playlist generation, not at ScheduleDay time
- Programs expand their asset chains based on `play_mode` at playlist generation
- Playlist contains resolved physical assets ready for playout execution
- Playlist feeds Playlog, which aligns entries to MasterClock for synchronized playout

## Failure / fallback behavior

If schedule assignments are missing or invalid, the system falls back to default programming or the most recent valid schedule.

## Naming rules

The canonical name for this concept in code and documentation is ScheduleDay.

Schedule days are resolved from plans. They define "what will air when" for a specific channel and date, but do not execute scheduling.

## Operator workflows

**Generate Schedule Days**: ScheduleService automatically generates ScheduleDay records derived from active SchedulePlans using Zones (time windows) that hold SchedulableAssets (Programs, Assets, VirtualAssets, SyntheticAssets) directly for a given channel and date. If multiple plans are active, priority resolves overlapping Zones. Schedule days are materialized 3–4 days in advance and frozen after generation. Operators don't manually create schedule days in normal operation.

**Preview Schedule**: Use preview/dry-run features to see how a plan will resolve into a ScheduleDay before it's generated.

**Manual Override (Post-Generation)**: Manually override a frozen schedule day post-generation for special events, breaking news, or one-off programming changes. This creates a new ScheduleDay with `is_manual_override=true`. Manual overrides are permitted even after the schedule day has been frozen.

**Force Regenerate Schedule**: Force regeneration of a schedule day from its plan(s) (useful after plan updates). This recreates the schedule day with updated content selections, times, and playback instructions based on the current plan state. The day must be unlocked for regeneration.

**Validate Schedule**: Check resolved schedule days for gaps, rule violations, or content conflicts.

**Multi-Channel Programming**: Different channels can have different plans, resulting in different schedule days for the same date.

**Schedule Inspection**: View resolved schedule days to see "what will air" for a specific channel and date.

## Examples

### Example: Broadcast-Day Display with Test Pattern

**Scenario:** Channel 3 with broadcast-day start at 06:00. ScheduleDay for Friday, Nov 7, 2025 contains:
- Base Zone (06:00–18:00): Test Pattern (SyntheticAsset)
- Primetime Zone (18:00–18:30): Cheers Program
- Base Zone (18:30–06:00): Test Pattern (SyntheticAsset)

**Human View (Plan Show):**

```
Schedule Plan: Channel 3 — Friday, Nov 7, 2025
Broadcast Day: 06:00 → 05:59

Zones
┌─────┬────────┬────────┬────────────┬─────────────────┐
│ Ord │ Start  │ End    │ Zone Name  │ Title           │
├─────┼────────┼────────┼────────────┼─────────────────┤
│ 1   │ 06:00  │ 18:00  │ Base       │ Test Pattern    │
│ 2   │ 18:00  │ 18:30  │ Primetime  │ Cheers          │
│ 3   │ 18:30  │ 06:00  │ Base       │ Test Pattern    │
└─────┴────────┴────────┴────────────┴─────────────────┘
```

**JSON View (Plan Show):**

```json
{
  "channel_id": "channel-3-uuid",
  "broadcast_day_start": "06:00",
  "zones": [
    {
      "order": 1,
      "start": "00:00",
      "end": "12:00",
      "zone_name": "Base",
      "title": "Test Pattern",
      "asset_type": "SyntheticAsset",
      "producer_type": "SyntheticProducer"
    },
    {
      "order": 2,
      "start": "12:00",
      "end": "12:30",
      "zone_name": "Primetime",
      "title": "Cheers",
      "asset_type": "Program",
      "producer_type": "AssetProducer"
    },
    {
      "order": 3,
      "start": "12:30",
      "end": "24:00",
      "zone_name": "Base",
      "title": "Test Pattern",
      "asset_type": "SyntheticAsset",
      "producer_type": "SyntheticProducer"
    }
  ]
}
```

**Key Points:**
- Human-readable times show broadcast-day offset (06:00 → 05:59 next day)
- All timestamps in human-readable output are relative to the channel broadcast day start (06:00 = midnight + 6h)
- JSON contains canonical times (00:00–24:00) plus `broadcast_day_start` for UI offset calculation
- Human view shows only title ("Test Pattern"), not asset_type or producer_type
- JSON includes technical fields (asset_type, producer_type) for system use
- Background/test pattern zones may be omitted from human-readable output but are included in JSON for system use

## Invocation

**CLI:**

```bash
retrovue schedule plan preview --channel <id> --date YYYY-MM-DD
retrovue schedule day build --channel <id> --date YYYY-MM-DD
```

**Programmatic:**

```python
from retrovue.scheduling import preview_schedule, build_schedule_day
```

## See also

- [Scheduling Policies](SchedulingPolicies.md) - Scheduling policy behaviors
- [Scheduling](Scheduling.md) - High-level scheduling system
- [SchedulePlan](SchedulePlan.md) - Top-level operator-created plans that define channel programming using Zones that hold SchedulableAssets (layered to generate schedule days)
- [Program](Program.md) - SchedulableAsset type with asset_chain and play_mode
- [VirtualAsset](VirtualAsset.md) - SchedulableAsset type that expands to physical Assets at playlist generation
- [Playlist](../architecture/Playlist.md) - Resolved pre–AsRun list of physical assets with absolute timecodes (generated from ScheduleDay)
- [PlaylogEvent](PlaylogEvent.md) - Runtime execution plan aligned to MasterClock
- [Channel](Channel.md) - Channel configuration and timing policy (owns Grid: `grid_block_minutes`, `block_start_offsets_minutes`, `programming_day_start`)
- [Channel manager](../runtime/ChannelManager.md) - Stream execution
- [Operator CLI](../cli/README.md) - Operational procedures
