_Related: [Architecture](../architecture/ArchitectureOverview.md) • [Runtime](../runtime/ChannelManager.md) • [ScheduleDay](ScheduleDay.md) • [PlaylogEvent](PlaylogEvent.md) • [PlayoutRequest](PlayoutRequest.md) • [Channel](Channel.md) • [Asset](Asset.md)_

# Domain — ScheduleItem

## Purpose

ScheduleItem represents a **single scheduled piece of content for a specific channel**. It defines what should play, when it should play, for how long, and what asset backs it. ScheduleItem serves as the resolved, concrete representation of a scheduled content entry, ready for playout execution.

**What ScheduleItem is:**

- **Resolved schedule entry**: A concrete, executable schedule entry with all timing and asset information resolved
- **Channel-specific**: Each ScheduleItem belongs to exactly one channel
- **Asset-backed**: References a specific asset file path for playout
- **Time-bound**: Defines exact start time and duration for playout

**What ScheduleItem is not:**

- Not a planning construct (that's [ScheduleDay](ScheduleDay.md) with SchedulableAssets)
- Not a runtime execution record (that's [PlaylogEvent](PlaylogEvent.md))
- Not a playout instruction (that's [PlayoutRequest](PlayoutRequest.md))

## Data Fields

ScheduleItem is managed with the following canonical fields:

### Core Fields

| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `id` | string | Unique identifier for this schedule entry | ✔ |
| `channel_id` | string | Channel this item belongs to (e.g., "retro1") | ✔ |
| `program_type` | `"series"` \| `"movie"` \| `"block"` | Type of content program | ✔ |
| `title` | string | Name of the series or film | ✔ |
| `episode` | string \| null | Episode identifier like "S01E03" | ✖ |
| `asset_path` | string | Local filesystem path to MP4 | ✔ |
| `start_time_utc` | ISO 8601 string | When playback should begin (UTC) | ✔ |
| `duration_seconds` | integer | Grid block duration, not actual file duration | ✔ |
| `end_time_utc` | ISO 8601 string | Computed: `start_time_utc + duration_seconds` | ✖ |
| `metadata` | object | Additional details (commType, bumpers, etc.) | ✖ |

### Field Details

- **id**: Unique string identifier. Used for tracking, logging, and cross-referencing with playout systems.
- **channel_id**: Channel identifier (typically a string like "retro1", "retro2"). References the [Channel](Channel.md) this item belongs to.
- **program_type**: Content type classification:
  - `"series"`: Multi-episode content (TV shows)
  - `"movie"`: Single-feature content (films, specials)
  - `"block"`: Multi-part programming block
- **title**: Human-readable title of the content. For series, this is the series name; for movies, this is the film title.
- **episode**: Optional episode identifier (e.g., "S01E03", "E05", "2025-01-15"). Can be `null` or omitted entirely. Only present for series or episodic content. Channel Manager must accept both `null` values and missing fields as valid.
- **asset_path**: Absolute local filesystem path to the media file. Must be accessible to the playout system. Example: `/mnt/media/tv/Cheers_S01E03.mp4`
- **start_time_utc**: ISO 8601 formatted timestamp in UTC indicating when playback should begin. Example: `"2025-11-07T18:00:00Z"`
- **duration_seconds**: Scheduled duration in seconds. This is the **grid block duration**, not necessarily the actual file duration. Content may be shorter or longer than this duration, but the schedule allocates this time slot.
- **end_time_utc**: Computed field (not stored in schedule.json). Calculated as `start_time_utc + duration_seconds`. Channel Manager computes this value for active item selection and validation. Example: If `start_time_utc = "2025-11-07T18:00:00Z"` and `duration_seconds = 1800`, then `end_time_utc = "2025-11-07T18:30:00Z"`. This field is useful for consumers (ChannelManager, operator UIs, debugging tools) to determine when a ScheduleItem's time window ends.
- **metadata**: Optional object containing additional playout instructions and context. This is opaque to the Channel Manager and passed through to Retrovue Air. May contain:
  - `commType`: Commercial break type
  - `bumpers`: Bumper/intro/outro instructions
  - `overlay`: Overlay configuration
  - Other playout-specific metadata
  
  **Important:** Metadata must be treated as an opaque JSON object. Channel Manager MUST pass it to PlayoutRequest exactly as-is without modification or inspection.

## Constraints

- **All times are UTC**: All timestamps must be in UTC format (ISO 8601 with Z suffix or explicit UTC offset)
- **Duration is grid duration**: The `duration_seconds` field represents the scheduled time slot, not the actual media file duration
- **Metadata is opaque**: The Channel Manager does not inspect or validate metadata content; it is passed through unchanged to Retrovue Air as an opaque JSON object

## Active ScheduleItem Selection Rule

A ScheduleItem is **active** if the current UTC time falls within its scheduled window:

```
start_time_utc ≤ now < start_time_utc + duration_seconds
```

Or equivalently, using the computed `end_time_utc`:

```
start_time_utc ≤ now < end_time_utc
```

**Selection Logic:**
- If current time is before `start_time_utc`, the item is not yet active
- If current time is at or after `start_time_utc` and before `end_time_utc` (or `start_time_utc + duration_seconds`), the item is active
- If current time is at or after `end_time_utc`, the item is no longer active

Channel Manager uses this rule to select which ScheduleItem should be playing at any given time.

### Handling Overlapping ScheduleItems

**Multiple Active Items:**
If multiple ScheduleItems are active at the current time (overlapping time windows), Channel Manager MUST:
- Select the ScheduleItem with the **earliest `start_time_utc`**
- If multiple items have the same `start_time_utc`, selection behavior is implementation-specific (e.g., first in schedule array, or by `id` lexicographic order)

**No Active Items (Schedule Gaps):**
If no ScheduleItem is active at the current time (schedule gap), Channel Manager MUST:
- Select **none** (no active ScheduleItem)
- Log the message: `"no active schedule item"` (or equivalent)
- Treat this as a hard error and abort startup (per ChannelManager error handling rules)

**Examples:**

**Overlapping Items:**
- Item A: `start_time_utc: 18:00:00Z`, `duration_seconds: 3600` (ends 19:00:00Z)
- Item B: `start_time_utc: 18:30:00Z`, `duration_seconds: 1800` (ends 19:00:00Z)
- Current time: `18:45:00Z`
- Both items are active, but Channel Manager selects Item A (earliest `start_time_utc`)

**Schedule Gap:**
- Item A: `start_time_utc: 18:00:00Z`, `duration_seconds: 1800` (ends 18:30:00Z)
- Item B: `start_time_utc: 19:00:00Z`, `duration_seconds: 1800` (ends 19:30:00Z)
- Current time: `18:45:00Z`
- No items are active (gap between 18:30:00Z and 19:00:00Z)
- Channel Manager logs "no active schedule item" and aborts startup

## Phase 8 Simplifications

**Phase 8 Implementation Notes:**

In Phase 8, ScheduleItems are loaded **directly from schedule.json**. 

- **No ScheduleDay resolution**: Phase 8 does not use ScheduleDay or SchedulableAssets. ScheduleItems are provided directly in schedule.json.
- **No VirtualAsset expansion**: VirtualAssets do not exist in Phase 8. All ScheduleItems already contain resolved `asset_path` values when loaded.
- **No Program chain resolution**: Programs and asset chains are not expanded in Phase 8. Each ScheduleItem is a self-contained entry with a single `asset_path`.
- **Direct JSON loading**: Channel Manager loads schedule.json and parses ScheduleItems directly. No intermediate resolution or expansion steps occur.

All ScheduleItems already contain complete `asset_path` values when loaded from schedule.json. Channel Manager does not perform any asset resolution or expansion.

## Phase 8 vs Future Phases — Execution Scope

**NOTE: Phase 8 implements a simplified one-file playout pipeline for testing. Future phases add PREVIEW/LIVE buffers, continuous playout, signaling, and scheduling logic.**

### Phase 8 Execution Model

**One ScheduleItem = One Media File (Temporary Simplification):**

In Phase 8, a ScheduleItem maps directly to **ONE media file** (simplified for testing):

- **ChannelManager loads ONE active ScheduleItem** and plays it until EOF (end of file)
- **No chaining**: There is no asset chaining or sequence logic
- **No preview/live**: There is no preview deck or live/next asset management
- **No multi-file playout**: Each ScheduleItem represents a single file playout operation
- **No "next asset" logic**: ChannelManager does not determine or queue the next asset to play

**Phase 8 Playout Behavior:**

- Air plays exactly and only the file referenced by `ScheduleItem.asset_path`
- When the media ends (EOF), ChannelManager does nothing further (Air process continues until client disconnects)
- ChannelManager does not track when files finish or trigger transitions to next items
- ChannelManager does not manage continuous playout across multiple files
- Each PlayoutRequest corresponds to exactly one ScheduleItem playing exactly one file

**Phase 8 Limitations (Temporary Simplifications):**

- **No file completion handling**: ChannelManager does not receive notifications when Air finishes playing a file
- **No preview/live switching**: Air's preview/live architecture exists but is not actively used (simplified for Phase 8 testing)
- **No transition management**: No automatic transitions between ScheduleItems based on timing
- **No continuous playout**: Each ScheduleItem is independent; there is no sequencing across items
- **Simplified playout**: Air may bypass preview/live buffers and play files directly (Phase 8 testing only)

**Note:** Air's preview/live architecture exists and will be fully active in future phases. Phase 8 uses a simplified direct-playout mode for testing.

### Future Phases Execution Model

In future phases, ScheduleItem execution becomes more sophisticated using Air's preview/live architecture:

**ScheduleItem as Source for Asset Sequence:**

- **ScheduleItem becomes the source for a sequence of assets**: One ScheduleItem may map to multiple media files or assets
- **ChannelManager manages continuous playout**: ChannelManager orchestrates playout across multiple files via preview/live switching
- **Air notifies ChannelManager**: Air notifies ChannelManager when preview is ready and when assets are taken live or finished playing
- **"What's next?" logic**: ChannelManager asks ScheduleManager "what's next?" to fill Air's preview buffer
- **Preview/live switching**: ChannelManager loads assets into preview, triggers "switch preview → live", then loads next asset into preview (continuous chain)
- **One ScheduleItem maps to multiple Air commands**: A single ScheduleItem may result in multiple PlayoutRequests (each loading into preview) to create continuous asset chains

**Future Phase Capabilities:**

- **Multi-file sequences**: ScheduleItems can represent sequences that require multiple files to be played in order
- **Preview/live deck management**: Air maintains a preview deck with next assets ready to play
- **Asset chaining**: Programs and VirtualAssets expand into chains of assets that play sequentially
- **Transition management**: ChannelManager manages smooth transitions between assets within and across ScheduleItems
- **Completion-driven progression**: ChannelManager receives completion events and automatically progresses to the next asset or ScheduleItem

### Phase 8 Duration Handling

In Phase 8, Channel Manager **does not**:
- Trim or cut media files to match `duration_seconds`
- Loop content if the file is shorter than `duration_seconds`
- Pad content if the file is longer than `duration_seconds`
- Verify alignment between the file's actual duration and `duration_seconds`

Channel Manager only selects which ScheduleItem is active based on `start_time_utc` and `duration_seconds`. The actual playback duration is determined by the media file itself and Retrovue Air.

### Phase 8 Limitations

The following concepts referenced in this document are **not part of Phase 8** and are reserved for future phases:

- **ScheduleDay**: Phase 8 loads ScheduleItems directly from schedule.json. References to ScheduleDay and SchedulableAssets are for future phases.
- **SchedulableAssets**: Phase 8 does not resolve SchedulableAssets. All ScheduleItems contain complete asset information.
- **VirtualAssets**: Phase 8 does not expand VirtualAssets. Each ScheduleItem has a single resolved `asset_path`.
- **Program asset chains**: Phase 8 does not expand Program asset chains. Each ScheduleItem is independent.

Phase 8 focuses on direct schedule.json → ScheduleItem → PlayoutRequest → Retrovue Air execution without intermediate resolution steps.

## Relationships

ScheduleItem relates to:

- **Channel** (via `channel_id`): The [Channel](Channel.md) this item is scheduled for
- **Asset** (via `asset_path`): The physical [Asset](Asset.md) file that backs this schedule entry
- **PlayoutRequest**: ScheduleItems generate [PlayoutRequest](PlayoutRequest.md) entries for playout execution

**Phase 8 Relationships:**
- In Phase 8, ScheduleItems are loaded directly from schedule.json
- Channel Manager selects active ScheduleItems and generates PlayoutRequests
- No ScheduleDay, SchedulableAssets, or VirtualAsset relationships exist in Phase 8

**Future Phase Relationships:**
- **ScheduleDay**: In future phases, ScheduleItems will be derived from [ScheduleDay](ScheduleDay.md) entries during playlist generation
- **PlaylogEvent**: In future phases, ScheduleItems may be used to generate [PlaylogEvent](PlaylogEvent.md) entries for runtime execution

## Execution Model

### Phase 8 Execution Model

In Phase 8, ScheduleItems are loaded **directly from schedule.json**:

1. **Schedule Loading**: ChannelController loads schedule.json for its channel and parses the schedule array
2. **ScheduleItem Parsing**: Extract ScheduleItem objects from the schedule array for that channel
3. **Active Item Selection**: Use the active selection rule to determine which ScheduleItem should play now (performed only when launching Air)
4. **PlayoutRequest Generation**: Convert the ONE active ScheduleItem to ONE PlayoutRequest and send to Retrovue Air

**Phase 8 Characteristics:**
- All ScheduleItems are pre-resolved with complete `asset_path` values
- No asset resolution or expansion occurs
- No ScheduleDay or SchedulableAsset resolution
- Direct JSON → ScheduleItem → PlayoutRequest flow
- **One-to-one mapping**: One ScheduleItem = One file = One PlayoutRequest
- **Single file playout**: Air plays exactly one file until EOF, then stops
- **No sequencing**: No chaining or multi-file playout across ScheduleItems

### Future Phase Execution Model

In future phases, ScheduleItems will be generated from [ScheduleDay](ScheduleDay.md) entries during playlist generation:

1. **ScheduleDay Resolution**: Retrieve resolved schedule entries from ScheduleDay
2. **Asset Resolution**: Resolve SchedulableAssets (Programs, Assets, VirtualAssets) to physical asset file paths
3. **Time Calculation**: Calculate precise UTC start times based on channel schedule and broadcast day boundaries
4. **Duration Assignment**: Assign grid block durations based on channel grid configuration
5. **Metadata Propagation**: Pass through metadata from schedule plan to playout instructions

**Time Resolution (Future):** Start times will be calculated in UTC by:
- Taking the broadcast day's schedule times
- Converting to UTC based on channel timezone
- Accounting for broadcast day boundaries and grid alignment
- Ensuring precise timing for synchronized playout

**Asset Resolution (Future):** Asset paths will be resolved by:
- Expanding Programs to their asset chains based on play_mode
- Expanding VirtualAssets to physical asset file paths
- Resolving canonical URIs to local filesystem paths via path mappings
- Validating that asset files exist and are accessible

## Examples

### Example: Series Episode ScheduleItem

```json
{
  "id": "schedule-item-abc123",
  "channel_id": "retro1",
  "program_type": "series",
  "title": "Cheers",
  "episode": "S02E05",
  "asset_path": "/mnt/media/tv/Cheers/Season2/Cheers_S02E05.mp4",
  "start_time_utc": "2025-11-07T18:00:00Z",
  "duration_seconds": 1800,
  "metadata": {
    "commType": "standard",
    "bumpers": {
      "intro": true,
      "outro": true
    }
  }
}
```

### Example: Movie ScheduleItem

```json
{
  "id": "schedule-item-def456",
  "channel_id": "retro1",
  "program_type": "movie",
  "title": "Airplane!",
  "episode": null,
  "asset_path": "/mnt/media/movies/Airplane_1980.mp4",
  "start_time_utc": "2025-11-07T20:00:00Z",
  "duration_seconds": 5400,
  "metadata": {
    "commType": "none",
    "rating": "PG"
  }
}
```

### Example: Programming Block ScheduleItem

```json
{
  "id": "schedule-item-ghi789",
  "channel_id": "retro1",
  "program_type": "block",
  "title": "Saturday Morning Cartoons",
  "episode": null,
  "asset_path": "/mnt/media/blocks/saturday-cartoons-2025-11-08.m3u8",
  "start_time_utc": "2025-11-08T06:00:00Z",
  "duration_seconds": 10800,
  "metadata": {
    "commType": "children",
    "block_type": "cartoon_block"
  }
}
```

## Naming Rules

The canonical name for this concept in code and documentation is **ScheduleItem**.

ScheduleItems represent resolved, executable schedule entries — they define "what to play when" with all timing and asset information resolved and ready for playout.

## Operator Workflows

**Schedule Inspection**: View ScheduleItems for a channel and time range to see what content is scheduled. Each entry shows the title, timing, asset path, and metadata.

**Timing Verification**: Verify that ScheduleItem start times align with channel schedule and broadcast day boundaries. Check that durations match grid block allocations.

**Asset Validation**: Ensure that all ScheduleItem asset paths reference accessible files. Validate that assets exist and are readable by the playout system.

**Metadata Review**: Review metadata passed through to playout systems. Verify that commercial break types, bumper configurations, and other playout instructions are correct.

**Schedule Debugging**: Use ScheduleItems to diagnose schedule generation issues. Trace items back to their source ScheduleDay entries and original schedule plans.

## See Also

- [ScheduleDay](ScheduleDay.md) - Resolved schedules that generate ScheduleItems
- [PlaylogEvent](PlaylogEvent.md) - Runtime execution records derived from ScheduleItems
- [PlayoutRequest](PlayoutRequest.md) - Playout instructions generated from ScheduleItems
- [Channel](Channel.md) - Channel configuration and timing policy
- [Asset](Asset.md) - Physical media files referenced by ScheduleItems
- [PlayoutPipeline](PlayoutPipeline.md) - Playout execution that consumes ScheduleItems

