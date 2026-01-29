_Related: [Scheduling system architecture](../architecture/SchedulingSystem.md) • [Architecture overview](../architecture/ArchitectureOverview.md) • [Runtime](../runtime/ChannelManager.md) • [Operator CLI](../cli/README.md)_

# Domain — Scheduling

> **Note:** This document reflects the modern scheduling architecture. Active chain: **SchedulePlan (Zones + SchedulableAssets) → ScheduleDay (resolved) → Playlist → PlaylogEvent (runtime) → AsRunLog.**

> **Chain:** Channel (Grid) → SchedulePlan (Zones + SchedulableAssets) → ScheduleDay (resolved) → Playlist → PlaylogEvent (runtime) → AsRunLog.

## Purpose

The scheduling system assigns assets (or rules to select them) into grid blocks for future air. This is planning-time logic that runs ahead of real time and extends the plan horizon (coarse view) and builds the runtime playlog (fine-grained view).

**End-to-End Flow:**
1. Operator creates a [SchedulePlan](SchedulePlan.md) defining Zones (time windows) that hold SchedulableAssets (Programs, Assets, VirtualAssets, SyntheticAssets) directly
2. SchedulableAssets are placed directly in Zones within SchedulePlans
3. SchedulingService uses the channel's Grid boundaries to generate [ScheduleDay](ScheduleDay.md) rows 3–4 days in advance. ScheduleDay contains SchedulableAssets placed in Zones with wall-clock times
4. [Playlist](../architecture/Playlist.md) is generated from ScheduleDay by expanding SchedulableAssets to physical Assets. Programs expand their asset chains, and VirtualAssets expand to physical Assets
5. [PlaylogEvent](PlaylogEvent.md) records are generated from Playlist, aligned to MasterClock
6. PlaylogEvents drive the playout stream

**Flow:** Plan → ScheduleDay (resolved 3–4 days out) → PlaylogEvent

**Relationship Diagram:**

```text
SchedulePlan ─┬─> ScheduleDay ─┬─> PlaylogEvent
               │                 └─> AsRunLog
               │
               └─> Policy/Rules
```

This visual shows the cascade: SchedulePlan generates ScheduleDay (realization), which produces PlaylogEvent (runtime execution) and AsRunLog (audit trail). Policies and rules govern the transformation from Plan to Day.

**Critical Rule:** The scheduler and playlog builder may only consider assets where `state == 'ready'` and `approved_for_broadcast == true`.

## Plan Horizon

The scheduling system operates on a **plan → realization** model:

**SchedulePlan** is the **abstract plan** that defines operator intent:
- Defines Zones (time windows) that hold SchedulableAssets (Programs, Assets, VirtualAssets, SyntheticAssets) directly
- Timeless and reusable — the same plan can generate different ScheduleDays for different dates
- Contains no specific dates, episodes, or assets — only the structure and catalog references

**ScheduleDay** is the **concrete, date-bound realization**:
- Represents a concrete, date-bound instance of a channel's plan
- Built automatically by SchedulingService 3–4 days in advance
- Generated from the abstract SchedulePlan (Zones with SchedulableAssets) and contains SchedulableAssets placed in Zones with wall-clock times
- Immutable once generated — provides stable EPG and playout instructions
- Each ScheduleDay is tied to a specific channel and date
- SchedulableAssets remain intact in ScheduleDay — expansion to physical assets occurs at playlist generation

**Key Distinction:**
- **SchedulePlan** = Plan (what should play, when in the day, but not which specific episodes). Zones hold SchedulableAssets directly
- **ScheduleDay** = Realization (SchedulableAssets placed in Zones with wall-clock times). Expansion to physical assets occurs at playlist generation

SchedulingService continuously monitors active plans and extends the plan horizon ahead of time, ensuring the EPG and playout pipeline are always populated with resolved, concrete schedules.

## Core model / scope

The Broadcast Scheduling Domain defines the core data models that enable RetroVue's scheduling and playout systems. This domain contains the persistent entities that ScheduleService, ProgramDirector, and ChannelManager depend upon for generating and executing broadcast schedules.

### Simplified Architecture

The scheduling system follows a simplified architecture based on Zones + SchedulableAssets:

**Core Model:** Channel Grid → Plan Zones → SchedulableAssets (Programs, Assets, VirtualAssets, SyntheticAssets)

1. **Channel owns the Grid** - Channel owns the Grid configuration (`grid_block_minutes`, `block_start_offsets_minutes`, `programming_day_start`) that defines temporal boundaries. All scheduling snaps to these grid boundaries.

2. **SchedulePlan defines Zones** - Plans define operator intent for channel programming using Zones (time windows with optional day filters). Each Zone holds SchedulableAssets directly.

3. **Zones hold SchedulableAssets** - Zones contain SchedulableAssets (Programs, Assets, VirtualAssets, SyntheticAssets) that play during the Zone's time window. Duration is controlled by the Zone, not by the SchedulableAssets themselves.

4. **Programs are SchedulableAssets** - Programs are SchedulableAssets with asset_chain (linked list of SchedulableAssets) and play_mode (random, sequential, manual). Programs can reference other Programs, Assets, VirtualAssets, and SyntheticAssets in their asset chains.

5. **Layering allows combining multiple plans** - Plans may layer by priority; more specific plans override generic ones within overlapping windows. Higher priority plans override lower priority plans when both are active for the same date. Zones from higher-priority plans override overlapping Zones from lower-priority plans.

6. **VirtualAssets enable modular packaging** - [VirtualAssets](VirtualAsset.md) are SchedulableAssets that act as input-driven composites. They behave like regular assets during scheduling but expand to physical assets at playlist generation, enabling reusable modular programming blocks (e.g., branded intro → episode → outro).

7. **Scheduler builds ScheduleDay (resolved, immutable) → Playlist → PlaylogEvent (runtime)** - The Scheduler resolves active plans into [ScheduleDay](ScheduleDay.md) records, which contain SchedulableAssets placed in Zones with wall-clock times. [Playlist](../architecture/Playlist.md) is generated from ScheduleDay by expanding SchedulableAssets to physical Assets. [PlaylogEvent](PlaylogEvent.md) records are then generated from Playlist for actual playout execution.

### Primary Models

The Broadcast Scheduling Domain consists of these primary models:

- **Channel** - Channel configuration and timing policy (owns Grid: `grid_block_minutes`, `block_start_offsets_minutes`, `programming_day_start`)
- **SchedulePlan** - Top-level scheduling construct that defines operator intent using Zones that hold SchedulableAssets directly
- **Zone** - Named time windows within the programming day (e.g., base 00:00–24:00, or After Dark 22:00–05:00) that hold SchedulableAssets directly
- **SchedulableAsset** - Root abstraction for anything that can appear on a schedule. Concrete types: Program, Asset, VirtualAsset, SyntheticAsset
- **Program** - SchedulableAsset type that is a linked list of SchedulableAssets with play_mode (random, sequential, manual). Defines ordering and sequencing, not duration
- **VirtualAsset** - SchedulableAsset type that acts as input-driven composite. Expands to physical Assets at playlist generation
- **ScheduleDay** - Resolved, immutable daily schedules (generated from plans). Contains SchedulableAssets placed in Zones with wall-clock times
- **Playlist** - Resolved pre–AsRun list of physical assets with absolute timecodes. Generated from ScheduleDay by expanding SchedulableAssets to physical Assets
- **Asset** - Broadcast-approved content (airable content), a type of SchedulableAsset
- **PlaylogEvent** - Generated playout events (runtime execution), derived from Playlist

## Contract / interface

### Architecture Flow

The scheduling system follows this end-to-end flow:

**Operator creates SchedulePlan → Zones defined with SchedulableAssets → SchedulingService generates ScheduleDay 3–4 days in advance → Playlist generated from ScheduleDay → PlaylogEvents generated from Playlist → PlaylogEvents drive playout stream**

1. **Operator creates SchedulePlan**: Operators create [SchedulePlan](SchedulePlan.md) records that define channel programming intent using Zones (time windows with optional day filters) that hold SchedulableAssets (Programs, Assets, VirtualAssets, SyntheticAssets) directly. Plans can be layered (e.g., base plan + holiday overlay) with higher priority plans overriding lower priority plans.

2. **Zones are defined with SchedulableAssets**: Operators define Zones (named time windows within the programming day, e.g., base 00:00–24:00, or After Dark 22:00–05:00, with optional day filters like Mon–Fri) and place SchedulableAssets directly in Zones. Duration is controlled by the Zone, not by the SchedulableAssets.

3. **SchedulableAssets are placed in Zones**: Operators place [Program](Program.md) references, Assets, [VirtualAssets](VirtualAsset.md), or SyntheticAssets directly in Zones. Programs are SchedulableAssets with asset_chain (linked list of SchedulableAssets) and play_mode (random, sequential, manual).

4. **SchedulingService extends the plan horizon 3–4 days in advance**: SchedulingService uses the channel's Grid boundaries (`grid_block_minutes`, `block_start_offsets_minutes`, `programming_day_start`) to generate [ScheduleDay](ScheduleDay.md) rows 3–4 days in advance. ScheduleDays contain SchedulableAssets placed in Zones with real-world wall-clock times. SchedulableAssets remain intact in ScheduleDay — expansion to physical assets occurs at playlist generation.

5. **Playlist is generated from ScheduleDay**: [Playlist](../architecture/Playlist.md) is generated from ScheduleDay by expanding SchedulableAssets to physical Assets. Programs expand their asset chains based on play_mode, and VirtualAssets expand to physical Assets.

6. **PlaylogEvents are generated from Playlist**: [PlaylogEvent](PlaylogEvent.md) records are generated from Playlist entries, aligned to MasterClock. Each PlaylogEvent is a resolved media segment with precise timestamps for playout execution.

7. **PlaylogEvents drive the playout stream**: PlaylogEvents contain precise timestamps for playout execution and feed ChannelManager for actual playout stream generation.

### Key Architectural Principles

- **Channel owns the Grid** - Channel owns Grid configuration (`grid_block_minutes`, `block_start_offsets_minutes`, `programming_day_start`). All scheduling snaps to these boundaries.
- **SchedulePlan is the top-level construct** - All scheduling logic flows from plans defining Zones that hold SchedulableAssets directly
- **Zones + SchedulableAssets model** - Plans define Zones (time windows) that hold SchedulableAssets (Programs, Assets, VirtualAssets, SyntheticAssets) directly. Duration is controlled by the Zone, not by SchedulableAssets.
- **SchedulableAsset is the root abstraction** - Programs, Assets, VirtualAssets, and SyntheticAssets are all types of SchedulableAssets
- **Programs are linked lists** - Programs are SchedulableAssets with asset_chain (linked list of SchedulableAssets) and play_mode. They define ordering and sequencing, not duration.
- **Layering enables plan composition** - Plans may layer by priority; more specific plans override generic ones within overlapping windows. Zones from higher-priority plans override overlapping Zones from lower-priority plans.
- **VirtualAssets enable modularity** - SchedulableAssets that act as input-driven composites, expanding to physical Assets at playlist generation
- **ScheduleDay is resolved and immutable** - Once generated, days are locked unless manually overridden. ScheduleDay contains SchedulableAssets placed in Zones with wall-clock times.
- **Playlist expands SchedulableAssets** - Playlist is generated from ScheduleDay by expanding SchedulableAssets to physical Assets. Programs expand their asset chains, and VirtualAssets expand to physical Assets.
- **PlaylogEvent is runtime** - Generated from Playlist for actual playout execution, aligned to MasterClock

## Execution model

### Scheduler Process

The Scheduler (ScheduleService) processes the Broadcast Scheduling Domain models. It follows this end-to-end flow:

1. **Operator creates SchedulePlan**: Operators create SchedulePlan records that define channel programming intent using Zones (time windows with optional day filters) that hold SchedulableAssets (Programs, Assets, VirtualAssets, SyntheticAssets) directly. Plans can be layered (e.g., base plan + holiday overlay) with higher priority plans overriding lower priority plans.

2. **Zones are defined with SchedulableAssets**: Operators define Zones (named time windows within the programming day, with optional day filters) and place SchedulableAssets directly in Zones. Duration is controlled by the Zone, not by the SchedulableAssets.

3. **SchedulableAssets are placed in Zones**: Operators place SchedulableAssets (Programs, Assets, VirtualAssets, SyntheticAssets) directly in Zones. Programs are SchedulableAssets with asset_chain (linked list of SchedulableAssets) and play_mode (random, sequential, manual).

4. **SchedulingService extends the plan horizon 3–4 days in advance**: The SchedulingService:
   - Identifies active SchedulePlans for channels and dates (based on cron_expression, date ranges, priority)
   - Applies layering: combines multiple plans using priority resolution (higher priority plans override lower priority plans). Zones from higher-priority plans override overlapping Zones from lower-priority plans.
   - Retrieves Zones and their SchedulableAssets from active plans
   - Places SchedulableAssets in Zones, snapping to the Channel's Grid boundaries (`grid_block_minutes`, `block_start_offsets_minutes`, `programming_day_start`)
   - Applies scheduling policies: grid alignment, soft-start-after-current, snap-next-boundary, fixed zone end, no mid-longform cuts, carry-in across broadcast day seams
   - Builds ScheduleDay records (resolved, immutable daily schedules) 3–4 days in advance with SchedulableAssets placed in Zones with wall-clock times
   - Uses the channel's Grid boundaries to anchor Zone time windows and produce real-world wall-clock times
   - Validates Zones and SchedulableAssets and ensures no gaps or conflicts

5. **Playlist is generated from ScheduleDay**: The ScheduleService generates [Playlist](../architecture/Playlist.md) entries from ScheduleDay:
   - SchedulableAssets are resolved to physical Assets
   - Programs expand their asset chains based on play_mode (random, sequential, manual)
   - VirtualAssets expand into one or more physical Assets
   - Creates absolute timecodes for each physical asset

6. **PlaylogEvents are generated from Playlist**: The ScheduleService generates PlaylogEvent records from Playlist entries:
   - Each PlaylogEvent is a resolved media segment aligned to MasterClock
   - Points to a resolved physical asset
   - Creates precise playout timestamps for runtime execution

7. **PlaylogEvents drive the playout stream**: PlaylogEvents feed ChannelManager for actual playout stream generation.

### Content Eligibility

The Scheduler queries Asset for eligible content:
- Only assets with `state='ready'` and `approved_for_broadcast=true` are eligible
- VirtualAssets expand to actual assets during resolution
- Content references (series, rules) resolve to eligible assets

**Critical Rules:**

- **Eligibility rule**: Scheduler never touches assets in `new` or `enriching` state. Only assets with `state='ready'` and `approved_for_broadcast=true` are eligible for scheduling.
- **Immutability rule**: ScheduleDays are immutable once generated (unless manually overridden)

**Scheduling Policies:**

See [SchedulingPolicies.md](SchedulingPolicies.md) for detailed descriptions of each policy and their user-facing outcomes.

- **Grid alignment**: All scheduling snaps to the Channel's Grid boundaries (`grid_block_minutes`, `block_start_offsets_minutes`, `programming_day_start`)
- **Soft-start-after-current**: When a Zone opens while content is already playing, the current content continues to completion, and the new Zone's SchedulableAssets start at the next valid Grid boundary
- **Snap-next-boundary**: Content placement snaps to the next valid Grid boundary when transitioning between Zones
- **Fixed zone end**: Zones have fixed end times; SchedulableAssets in Zones play within the zone's time window, respecting the zone boundary
- **No mid-longform cuts**: Longform content (with `slot_units` override) is never cut mid-program; it consumes the required number of grid blocks
- **Carry-in across broadcast day seams**: Content can carry in across broadcast day boundaries (e.g., a program starting at 23:30 can continue into the next programming day)
- **Duration is zone-controlled**: Duration is determined by the Zone or Schedule context, not by Programs or SchedulableAssets themselves
- **ScheduleDay contains SchedulableAssets**: ScheduleDay contains SchedulableAssets placed in Zones. Expansion to physical assets occurs at playlist generation.

ProgramDirector coordinates multiple channels and may reference:

- Channel records for channel configuration
- SchedulePlan records for plan resolution and layering
- ScheduleDay records for cross-channel programming
- Asset records for content availability and approval status

ChannelManager executes playout but does not modify any Broadcast Scheduling Domain models. It:

- Reads PlaylogEvent records for playout instructions
- References Channel configuration for channel identity
- Uses Asset file paths for content playback

**Critical Rule:**

- **Runtime never spins up playout for an asset unless it's in `ready` state**

## Failure / fallback behavior

Scheduling runs ahead of real time and extends the plan horizon (coarse view) and builds the runtime playlog (fine-grained view). If scheduling fails, the system falls back to the most recent successful schedule or default programming.

## Naming rules

The canonical name for this concept in code and documentation is "Scheduling" or "Broadcast Scheduling Domain".

Scheduling is planning-time logic, not runtime logic. It defines "what to play when" but does not execute playout.

All scheduling logic, operator tooling, and documentation MUST refer to the Broadcast Scheduling Domain as the complete data foundation for automated broadcast programming.

## Invocation

Scheduling can be invoked either via CLI or programmatically:

**CLI Example:**

```bash
retrovue schedule plan build --channel-id=1 --date=2025-11-07
```

**Programmatic Example:**

```python
from retrovue.app.schedule import build_schedule_plan
build_schedule_plan(channel_id=1, date=date(2025, 11, 7))
```

The CLI entrypoint provides a user-friendly interface to the underlying scheduling functions, which handle plan resolution, Zone and SchedulableAsset placement, and ScheduleDay generation.

**Note:** The CLI "plan-building mode" is a front-end to the same schedule engine the UI uses; both call the same SchedulePlanService methods.

## Next Steps

Implementation checklist for the scheduling system:

- [ ] Implement CLI entrypoint for schedule planning
- [ ] Add FastAPI endpoint for on-demand regeneration
- [ ] Write tests for plan/daily generation integrity

## See also

- [Scheduling system architecture](../architecture/SchedulingSystem.md) - Comprehensive scheduling system architecture
- [Scheduling roadmap](../architecture/SchedulingRoadmap.md) - Implementation roadmap
- [Channel](Channel.md) - Channel configuration and timing policy (owns Grid)
- [SchedulePlan](SchedulePlan.md) - Top-level scheduling construct that defines operator intent using Zones that hold SchedulableAssets directly
- [Program](Program.md) - SchedulableAsset type that is a linked list of SchedulableAssets with play_mode
- [VirtualAsset](VirtualAsset.md) - SchedulableAsset type that acts as input-driven composite, expanding to physical Assets at playlist generation
- [ScheduleDay](ScheduleDay.md) - Resolved, immutable daily schedules (generated from plans). Contains SchedulableAssets placed in Zones with wall-clock times.
- [Playlist](../architecture/Playlist.md) - Resolved pre–AsRun list of physical assets. Generated from ScheduleDay by expanding SchedulableAssets to physical Assets.
- [PlaylogEvent](PlaylogEvent.md) - Generated playout events (runtime execution), derived from Playlist
- [PlayoutPipeline](PlayoutPipeline.md) - Live stream generation
- [Channel manager](../runtime/ChannelManager.md) - Stream execution
- [Operator CLI](../cli/README.md) - Operational procedures
