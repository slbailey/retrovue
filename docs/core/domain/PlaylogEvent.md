_Related: [Architecture](../architecture/ArchitectureOverview.md) • [Runtime](../runtime/ChannelManager.md) • [Operator CLI](../cli/README.md) • [SchedulePlan](SchedulePlan.md) • [Program](Program.md) • [ScheduleDay](ScheduleDay.md) • [Playlist](../architecture/Playlist.md) • [VirtualAsset](VirtualAsset.md)_

# Domain — PlaylogEvent

> **Note:** This document reflects the modern scheduling architecture. Active chain: **SchedulePlan (Zones + SchedulableAssets) → ScheduleDay (resolved) → Playlist → PlaylogEvent (runtime) → AsRunLog.**

## Purpose

PlaylogEvent is the **"Runtime" layer representation** that records the actual playback of an asset during a broadcast. Events are emitted when the per-channel playout engine begins playback. It represents the runtime execution plan aligned to the MasterClock, providing the definitive "what should play now" instructions for the playout system.

**What PlaylogEvent is:**

- **Runtime execution plan**: The active playout instructions aligned to MasterClock timing
- **Asset playback record**: Records which asset is scheduled to play at specific UTC timestamps during broadcast
- **Derived from Playlist**: Generated from [Playlist](../architecture/Playlist.md) entries but may diverge if substitutions or timing corrections occur
- **Transient and rolling**: Continuously rolled forward by the scheduler ~3-4 hours ahead of real time, then later persisted as an AsRun log after playback completes

**What PlaylogEvent is not:**

- Not the planning layer (that's [ScheduleDay](ScheduleDay.md))
- Not the resolved pre-AsRun list (that's [Playlist](../architecture/Playlist.md))
- Not the observed ground truth (that's AsRun log)

**Critical Behavior:** PlaylogEvent is derived from Playlist but may diverge when:
- Last-minute substitutions are made (e.g., breaking news, emergency content changes)
- Timing corrections are applied (e.g., adjusting for technical delays, synchronization adjustments)
- Fallback content is activated (e.g., when primary assets are unavailable)

The Playlog is **transient** — it's continuously rolled forward by the scheduler to maintain a ~3-4 hour look-ahead window. After playback completes, the actual observed playback is persisted as an AsRun log entry for historical record and audit purposes.

## Relationships

PlaylogEvent sits at the **Runtime layer** in the scheduling pipeline, positioned between the resolved Playlist and the observed AsRun log:

### Relationship to Playlist

PlaylogEvent is **derived from Playlist** entries. The Playlist contains the resolved pre-AsRun list of physical assets with absolute timecodes, generated from [ScheduleDay](ScheduleDay.md). PlaylogEvent takes these Playlist entries and aligns them to the MasterClock for synchronized playout execution.

**Divergence from Playlist:** While PlaylogEvent is initially derived from Playlist, it may diverge when:
- Substitutions occur (operator-initiated content changes, emergency updates)
- Timing corrections are applied (MasterClock alignment adjustments, technical delay compensation)
- Fallback mechanisms activate (primary content unavailable, using alternative assets)

### Relationship to ScheduleDay

Each PlaylogEvent references its **originating ScheduleDay** via `schedule_day_id` for traceability. This allows operators and systems to trace any playlog event back to the original schedule plan and understand which [SchedulePlan](SchedulePlan.md) and Zone generated the event.

### Relationship to Program

PlaylogEvents reference the resolved physical **Asset** that will be played. The Asset may have originated from a [Program](Program.md) during playlist generation (Programs expand their asset chains at playlist generation, not at ScheduleDay time). While PlaylogEvent doesn't directly reference Program, the traceability chain (PlaylogEvent → Playlist → ScheduleDay → SchedulePlan → Program) allows full lineage tracking from runtime playback back to the original programming intent.

### Relationship to AsRun Log

After playback completes, the **AsRun log** records what actually aired. AsRun entries reference their source PlaylogEvent (`playlog_event_id`) to enable comparison between planned (PlaylogEvent) and actual (AsRun) playback. This comparison identifies discrepancies, timing variances, or substitutions that occurred during execution.

**Pipeline Flow:**

```
ScheduleDay (resolved schedule)
    ↓
Playlist (resolved physical assets with absolute timecodes)
    ↓
PlaylogEvent (runtime execution plan, aligned to MasterClock, may diverge from Playlist)
    ↓
AsRun Log (observed ground truth after playback)
```

## Data Fields

PlaylogEvent is managed by SQLAlchemy with the following fields:

### Core Fields

- **id** (Integer, primary key): Unique identifier for relational joins and foreign key references
- **uuid** (UUID, required, unique): Stable external identifier used for audit, cross-domain tracing, and as-run logs
- **channel_id** (UUID, required, foreign key): Reference to Channel that will play this event
- **asset_uuid** (UUID, required, foreign key): Reference to Asset UUID (primary key) - the resolved physical asset to be played
- **schedule_day_id** (UUID, optional, foreign key): Reference to ScheduleDay - provides traceability to the originating schedule plan
- **start_utc** (DateTime(timezone=True), required): Event start time in UTC, aligned to MasterClock
- **end_utc** (DateTime(timezone=True), required): Event end time in UTC, aligned to MasterClock
- **broadcast_day** (Text, required): Broadcast day label in "YYYY-MM-DD" format
- **created_at** (DateTime(timezone=True), required): Record creation timestamp

### Indexes

PlaylogEvent has indexes on:
- `channel_id` and `start_utc` (for efficient playout queries by channel and time)
- `broadcast_day` (for broadcast day lookups)
- `asset_uuid` (for asset-based queries)

### Traceability

Each PlaylogEvent maintains traceability through:
- **schedule_day_id**: References the originating [ScheduleDay](ScheduleDay.md), which can be traced back to:
  - The [SchedulePlan](SchedulePlan.md) that generated the schedule day
  - The Zone that contained the SchedulableAsset
  - The [Program](Program.md) or other SchedulableAsset that was resolved to the asset
- **asset_uuid**: References the resolved physical Asset that will be played
- **broadcast_day**: Provides the broadcast day context for the event

This traceability enables full lineage tracking from runtime playback back to the original programming plan.

## Execution Model

### PlaylogEvent Generation

PlaylogEvents are generated from [Playlist](../architecture/Playlist.md) entries:

1. **Playlist Retrieval**: Retrieve Playlist entries for the current time window (~3-4 hours ahead of real time)
2. **MasterClock Alignment**: Align Playlist entries to the MasterClock for synchronized playout
3. **Playlog Creation**: Create PlaylogEvent records with `start_utc`, `end_utc` aligned to MasterClock
4. **ScheduleDay Mapping**: Map each PlaylogEvent to its source ScheduleDay via `schedule_day_id` for traceability
5. **Continuous Rolling**: Scheduler continuously extends the Playlog ~3-4 hours ahead, maintaining a rolling window

### Runtime Divergence

PlaylogEvents may diverge from their source Playlist entries when:

- **Substitutions**: Operators replace planned content with alternative assets (breaking news, emergency updates)
- **Timing Corrections**: MasterClock synchronization adjustments or technical delay compensation
- **Fallback Activation**: Primary assets unavailable, system activates fallback content

When divergence occurs, the PlaylogEvent maintains its `schedule_day_id` reference for audit purposes, but the `asset_uuid` or timing may differ from the original Playlist entry.

### Transient Nature and Persistence

The Playlog is **transient** — it exists as an active, rolling execution plan:

- **Rolling Window**: Continuously extended ~3-4 hours ahead of real time by the scheduler
- **Active Execution**: Current and upcoming events drive actual playout
- **Historical Persistence**: After playback completes, the observed playback is recorded in the AsRun log
- **AsRun Log**: The AsRun log becomes the persistent historical record, referencing the source PlaylogEvent for comparison

This transient design ensures the Playlog remains current and aligned with real-time execution, while the AsRun log provides the durable audit trail.

## Failure / Fallback Behavior

PlaylogEvent supports **fallback mechanisms** to ensure continuous playout when primary content is unavailable:

- **Missing playlog events**: System falls back to default programming or the most recent valid schedule
- **Unavailable assets**: If a referenced asset is unavailable (file missing, corrupted, or not accessible), the system can:
  - Use alternative assets from the same ScheduleDay
  - Activate default filler content configured for the channel
  - Skip to the next available playlog event in sequence
- **Asset segment failures**: For assets that originated from VirtualAsset expansions, if one asset fails:
  - Skip to the next asset in the sequence
  - Fall back to alternative content for that grid block
  - Continue with remaining assets if the failure is non-critical

**Fallback Priority:**
1. Alternative content from the same ScheduleDay assignment
2. Default filler content configured for the channel
3. Skip to the next playlog event in sequence
4. System-wide default programming

## Last-Minute Overrides

PlaylogEvent supports **last-minute overrides** to handle emergency changes or special events:

- **Override existing events**: Operators can override specific playlog events to replace content with emergency updates, breaking news, or special programming
- **Insert new events**: Operators can insert new playlog events into the sequence for last-minute additions
- **Modify timing**: Operators can adjust timing of existing playlog events for last-minute schedule changes
- **Preserve traceability**: Overridden events maintain their `schedule_day_id` mapping for audit and traceability purposes

**Override Behavior:**
- Last-minute overrides take precedence over generated playlog events
- Overridden events are marked to indicate they were manually changed
- The original ScheduleDay mapping is preserved for audit trails
- Overrides can be applied even after playlog events have been generated
- Overrides are applied in real-time and take effect immediately for upcoming playout

**Use Cases:**
- Breaking news interruptions
- Emergency announcements
- Special event programming
- Last-minute content substitutions
- Schedule adjustments for technical issues

## Examples

### Example: PlaylogEvent Entry

A PlaylogEvent entry representing a single asset playback during broadcast:

```json
{
  "uuid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "channel_id": "550e8400-e29b-41d4-a716-446655440000",
  "asset_uuid": "660e8400-e29b-41d4-a716-446655440001",
  "schedule_day_id": "770e8400-e29b-41d4-a716-446655440002",
  "start_utc": "2025-11-07T18:00:00+00:00",
  "end_utc": "2025-11-07T18:30:00+00:00",
  "broadcast_day": "2025-11-07",
  "created_at": "2025-11-04T14:23:15+00:00",
  "asset": {
    "uuid": "660e8400-e29b-41d4-a716-446655440001",
    "canonical_uri": "plex://library/metadata/12345",
    "title": "Cheers - Season 2, Episode 5",
    "duration_seconds": 1800,
    "file_path": "/mnt/media/cheers/season2/cheers_s2e5.mp4",
    "metadata": {
      "series": "Cheers",
      "season": 2,
      "episode": 5,
      "episode_title": "Personal Business",
      "parental_rating": "TV-PG"
    }
  },
  "schedule_day": {
    "id": "770e8400-e29b-41d4-a716-446655440002",
    "channel_id": "550e8400-e29b-41d4-a716-446655440000",
    "schedule_date": "2025-11-07",
    "plan_id": "880e8400-e29b-41d4-a716-446655440003"
  }
}
```

This example shows:
- Real UTC timestamps (`start_utc`, `end_utc`) aligned to MasterClock
- Asset metadata including title, duration, file path, and content metadata
- Traceability through `schedule_day_id` to the originating ScheduleDay
- Broadcast day context for the event
- Full asset details including canonical URI and metadata

## Naming Rules

The canonical name for this concept in code and documentation is **PlaylogEvent**.

PlaylogEvents represent the runtime execution plan — they define "what to play when" during actual broadcast execution. They are transient, continuously rolled forward by the scheduler, and later persisted as AsRun log entries after playback completes.

## Operator Workflows

**Monitor Playout**: View active PlaylogEvents to see what content is scheduled to play now and in the near future. Each entry shows the asset, timing, and traceability to the originating ScheduleDay.

**Playout Verification**: Verify that scheduled content matches programming intentions and timing. Check that each PlaylogEvent correctly maps to its ScheduleDay and references valid assets.

**Content Timing**: Review start/end times to ensure proper content sequencing and timing across the playout sequence.

**Broadcast Day Management**: Track content across broadcast day boundaries and rollover periods using the `broadcast_day` field.

**Playout Troubleshooting**: Use PlaylogEvents to diagnose playout issues and content problems. Trace issues back to the ScheduleDay and original Zones + SchedulableAssets from the plan using the `schedule_day_id` reference.

**Fallback Management**: Monitor and configure fallback behavior for when primary content is unavailable. Review fallback chains and ensure default content is properly configured.

**Last-Minute Overrides**: Apply last-minute overrides for emergency changes, breaking news, or special events. Override specific PlaylogEvents or insert new events as needed.

## See Also

- [Scheduling](Scheduling.md) - High-level scheduling system
- [SchedulePlan](SchedulePlan.md) - Top-level operator-created plans that define channel programming using Zones that hold SchedulableAssets directly
- [ScheduleDay](ScheduleDay.md) - Resolved schedules for specific channel and date (source for Playlist generation)
- [Playlist](../architecture/Playlist.md) - Resolved pre-AsRun list of physical assets with absolute timecodes (source for PlaylogEvent generation)
- [Program](Program.md) - SchedulableAsset type with asset_chain and play_mode (may be resolved to assets in PlaylogEvents)
- [Scheduling system architecture](../architecture/SchedulingSystem.md) - Detailed scheduling system architecture and flow
- [Asset](Asset.md) - Approved content (referenced by PlaylogEvents)
- [VirtualAsset](VirtualAsset.md) - SchedulableAsset type that expands to physical Assets at playlist generation
- [Channel manager](../runtime/ChannelManager.md) - Stream execution (consumes PlaylogEvents)
- [Operator CLI](../cli/README.md) - Operational procedures

**Pipeline:** ScheduleDay (resolved schedule) → Playlist (resolved physical assets) → PlaylogEvent (runtime execution plan, may diverge from Playlist) → AsRun Log (observed ground truth)
