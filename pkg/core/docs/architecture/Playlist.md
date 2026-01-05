_Related: [Architecture overview](ArchitectureOverview.md) • [Domain: ScheduleDay](../domain/ScheduleDay.md) • [Domain: PlaylogEvent](../domain/PlaylogEvent.md) • [Runtime: Channel manager](../runtime/ChannelManager.md)_

# Architecture — Playlist

## Purpose

Playlist is part of the **Planned** layer in the scheduling architecture, positioned between
[ScheduleDay](../domain/ScheduleDay.md) and [PlaylogEvent](../domain/PlaylogEvent.md). It is a **flattened,
time-resolved sequence of all items from a ScheduleDay** — including programs, bumpers, commercials, and
transitions — with absolute timecodes ready for playout execution.

**What Playlist is:**

- A flattened, time-resolved sequence of all items from ScheduleDay
- Part of the **Planned** layer (between ScheduleDay and Playlog)
- Contains resolved physical assets with absolute start/end times
- Generated from ScheduleDay by expanding SchedulableAssets to physical Assets
- Provides the timeline input for the runtime Playlog

**What Playlist is not:**

- Not the runtime execution plan (that's Playlog)
- Not the observed ground truth (that's AsRun)
- Not the planning layer (that's ScheduleDay)

## Core Model / Scope

Playlist is a **flattened, time-resolved sequence** that contains all items from a ScheduleDay in chronological order. It includes:

- **Programs**: Expanded into multiple PlaylistItems based on their asset chains and play_mode
- **Bumpers**: Appear as resolved assets in the sequence (not as explicit attributes)
- **Commercials**: Appear as resolved assets in the sequence (not as explicit attributes)
- **Transitions**: Appear as resolved assets in the sequence

**Key Points:**

- Playlist is generated from ScheduleDay, not directly from SchedulePlan
- Playlist is part of the **Planned** layer, positioned between ScheduleDay and Playlog
- All items (programs, bumpers, commercials, transitions) appear as resolved assets in the flattened sequence
- Bumpers and ads are resolved assets, not explicit attributes
- Programs expand into multiple PlaylistItems when scheduled based on their asset chains
- VirtualAssets expand at playlist generation, not at ScheduleDay time
- Playlist provides the timeline input for the runtime Playlog

## Persistence Model

Playlist entries (PlaylistItems) are managed with the following fields:

- **start_time** (datetime, required): Absolute start time for the asset
- **end_time** (datetime, required): Absolute end time for the asset
- **asset_id** (UUID, required): Reference to resolved physical Asset
- **source_slot_id** (UUID, required): Reference to source ScheduleDay slot
- **ffmpeg_input** (string, required): File path or input specification for ffmpeg

**Note:** Playlist may be stored in memory or persisted to database depending on implementation. The key requirement is that it contains resolved physical assets with absolute timecodes ready for playout.

## Contract / Interface

Playlist defines:

- **Flattened sequence**: All items from ScheduleDay appear in chronological order as resolved assets
- **Physical asset resolution**: SchedulableAssets from ScheduleDay are resolved to physical Assets
- **Program expansion**: Programs expand into multiple PlaylistItems based on their asset chains and play_mode
- **Bumper/commercial resolution**: Bumpers and commercials appear as resolved assets, not as explicit attributes
- **VirtualAsset expansion**: VirtualAssets expand into one or more physical Assets
- **Absolute timecodes**: Each entry has precise start_time and end_time
- **Source references**: Each entry references source ScheduleDay slot for traceability
- **ffmpeg input**: Each entry includes file path or input specification for ffmpeg
- **Timeline input for Playlog**: Playlist provides the timeline input for the runtime Playlog

## Execution Model

Playlist is generated from [ScheduleDay](../domain/ScheduleDay.md) as part of the **Planned** layer:

1. **SchedulableAsset Resolution**: SchedulableAssets in ScheduleDay (Programs, Assets, VirtualAssets, SyntheticAssets) are resolved to physical Assets
2. **VirtualAsset Expansion**: VirtualAssets expand into one or more physical Assets at this stage
3. **Program Chain Expansion**: Programs expand their asset chains based on play_mode:
   - **random**: Assets in chain are selected randomly
   - **sequential**: Assets in chain are played in order
   - **manual**: Assets are selected manually by operators
4. **Flattening**: All items (programs, bumpers, commercials, transitions) are flattened into a single chronological sequence
5. **Timecode Calculation**: Absolute start/end times are calculated for each physical asset
6. **Playlist Creation**: Playlist entries are created with asset_id, source_slot_id, and ffmpeg_input

**Pipeline Flow:**

```
ScheduleDay (SchedulableAssets in Zones)
    ↓
Playlist (Planned layer: flattened, time-resolved sequence)
    ↓
Playlog (runtime execution plan aligned to MasterClock)
    ↓
AsRun (observed ground truth)
```

## Relationship to ScheduleDay

Playlist is generated from [ScheduleDay](../domain/ScheduleDay.md). ScheduleDay contains SchedulableAssets
(Programs, Assets, VirtualAssets, SyntheticAssets) placed in Zones. At playlist generation:

- SchedulableAssets are resolved to physical Assets
- VirtualAssets expand into one or more physical Assets
- Programs expand their asset chains based on play_mode into multiple PlaylistItems
- All items (programs, bumpers, commercials, transitions) are flattened into a single chronological sequence
- Absolute timecodes are calculated for each physical asset

## Relationship to Playlog

Playlist is part of the **Planned** layer and provides the **timeline input for the runtime Playlog**.
[PlaylogEvent](../domain/PlaylogEvent.md) (Playlog) is the runtime execution plan aligned to the MasterClock.
Playlog entries are derived from Playlist entries but aligned to the MasterClock for synchronized playout.

## Relationship to AsRun

Playlist is the pre–AsRun list. [AsRun](../domain/PlaylogEvent.md#asrun) records what actually aired during
playout execution. AsRun can be compared to Playlist (via Playlog) to identify discrepancies between planned
and actual playout.

## Program Expansion

When a Program is scheduled, it expands into multiple PlaylistItems based on its asset chain and play_mode:

**Example: Cheers (Syndicated) Program**

A Program with `play_mode: "manual"` and `asset_chain: [intro_bumper_id, episode_pool_id, outro_bumper_id]` expands into:

1. **PlaylistItem 1**: Intro bumper asset (resolved from intro_bumper_id)
2. **PlaylistItem 2**: Selected episode asset (resolved from episode_pool_id based on play_mode)
3. **PlaylistItem 3**: Outro bumper asset (resolved from outro_bumper_id)

All three items appear as separate entries in the flattened Playlist sequence with consecutive absolute timecodes.

## Examples

### Example: Playlist Entry

A Playlist entry for a resolved physical asset:

```json
{
  "start_time": "2025-11-07T18:00:00Z",
  "end_time": "2025-11-07T18:30:00Z",
  "asset_id": "550e8400-e29b-41d4-a716-446655440000",
  "source_slot_id": "schedule-day-slot-uuid",
  "ffmpeg_input": "/mnt/media/cheers/season2/cheers_s2e5.mp4"
}
```

### Example: Program Expansion

A Program in ScheduleDay expands to multiple PlaylistItems:

**ScheduleDay:**

- Program: "Cheers (Syndicated)" with `play_mode: "manual"`, `asset_chain: [intro_bumper_id, episode_pool_id, outro_bumper_id]`

**Playlist:**

- Entry 1: Intro bumper asset (start_time: 18:00:00, end_time: 18:00:30)
- Entry 2: Cheers S02E05 episode asset (start_time: 18:00:30, end_time: 18:22:15)
- Entry 3: Outro bumper asset (start_time: 18:22:15, end_time: 18:22:45)

### Example: VirtualAsset Expansion

A VirtualAsset in ScheduleDay expands to multiple Playlist entries:

**ScheduleDay:**

- VirtualAsset: "SpongeBob Episode Block" (contains intro + 2 random episodes)

**Playlist:**

- Entry 1: Intro asset (start_time: 18:00:00, end_time: 18:02:00)
- Entry 2: SpongeBob S03E12 (start_time: 18:02:00, end_time: 18:13:00)
- Entry 3: SpongeBob S02E08 (start_time: 18:13:00, end_time: 18:23:00)

### Example: Generated Playlist Segment (YAML)

A generated playlist segment showing the flattened, time-resolved sequence:

```yaml
playlist:
  channel_id: "550e8400-e29b-41d4-a716-446655440001"
  schedule_date: "2025-11-07"
  items:
    - start_time: "2025-11-07T18:00:00Z"
      end_time: "2025-11-07T18:00:30Z"
      asset_id: "bumper-intro-uuid"
      source_slot_id: "schedule-day-slot-uuid-1"
      ffmpeg_input: "/mnt/media/bumpers/intro_30s.mp4"
      item_type: "bumper"

    - start_time: "2025-11-07T18:00:30Z"
      end_time: "2025-11-07T18:22:15Z"
      asset_id: "cheers-s2e5-uuid"
      source_slot_id: "schedule-day-slot-uuid-2"
      ffmpeg_input: "/mnt/media/cheers/season2/cheers_s2e5.mp4"
      item_type: "program"

    - start_time: "2025-11-07T18:22:15Z"
      end_time: "2025-11-07T18:22:45Z"
      asset_id: "bumper-outro-uuid"
      source_slot_id: "schedule-day-slot-uuid-3"
      ffmpeg_input: "/mnt/media/bumpers/outro_30s.mp4"
      item_type: "bumper"

    - start_time: "2025-11-07T18:22:45Z"
      end_time: "2025-11-07T18:27:45Z"
      asset_id: "commercial-pod-1-uuid"
      source_slot_id: "schedule-day-slot-uuid-4"
      ffmpeg_input: "/mnt/media/commercials/pod_2025_11_07_1822.mp4"
      item_type: "commercial"

    - start_time: "2025-11-07T18:27:45Z"
      end_time: "2025-11-07T18:28:00Z"
      asset_id: "transition-fade-uuid"
      source_slot_id: "schedule-day-slot-uuid-5"
      ffmpeg_input: "/mnt/media/transitions/fade_15s.mp4"
      item_type: "transition"
```

This example shows how a Program (Cheers episode) expands into multiple PlaylistItems (intro bumper, episode, outro bumper), and how all items (programs, bumpers, commercials, transitions) appear as resolved assets in the flattened sequence with absolute start times.

## Failure / Fallback Behavior

If playlist generation fails:

- **Missing SchedulableAssets**: System falls back to default content or leaves gaps
- **VirtualAsset expansion failures**: System falls back to alternative content or leaves gap
- **Program chain expansion failures**: System falls back to default assets or leaves gap
- **Invalid asset references**: System skips invalid entries and continues with next valid entry

## Naming Rules

The canonical name for this concept in code and documentation is Playlist.

Playlist is the resolved pre–AsRun list of physical assets. It is distinct from Playlog (runtime execution plan) and AsRun (observed ground truth).

## See Also

- [ScheduleDay](../domain/ScheduleDay.md) - Resolved schedules for specific channel and date (source for Playlist generation)
- [PlaylogEvent](../domain/PlaylogEvent.md) - Runtime execution plan aligned to MasterClock (derived from Playlist)
- [Program](../domain/Program.md) - SchedulableAsset type with asset_chain and play_mode
- [VirtualAsset](../domain/VirtualAsset.md) - SchedulableAsset type that expands to physical Assets at playlist generation
- [Scheduling system architecture](SchedulingSystem.md) - Detailed scheduling system architecture and flow
- [Channel manager](../runtime/ChannelManager.md) - Stream execution

Playlist is part of the **Planned** layer in the scheduling architecture, positioned between ScheduleDay and Playlog. It is a flattened, time-resolved sequence of all items from a ScheduleDay — including programs, bumpers, commercials, and transitions — with absolute timecodes. Playlist is generated from ScheduleDay by expanding SchedulableAssets to physical Assets. Programs expand into multiple PlaylistItems when scheduled based on their asset chains and play_mode. Bumpers and commercials appear as resolved assets in the sequence, not as explicit attributes. Playlist provides the timeline input for the runtime Playlog, which aligns entries to MasterClock for synchronized playout.
