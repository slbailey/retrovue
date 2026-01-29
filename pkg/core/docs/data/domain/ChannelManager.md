_Related: [Architecture](../architecture/ArchitectureOverview.md) • [Runtime](../runtime/ChannelManager.md) • [ScheduleItem](ScheduleItem.md) • [PlayoutRequest](PlayoutRequest.md) • [Channel](Channel.md) • [MasterClock](MasterClock.md)_

# Domain — ChannelManager

## Purpose

ChannelManager is a **per-channel runtime controller**. It is created by ProgramDirector. It spawns and supervises its channel's internal playout engine process. It never hosts HTTP and never exposes UI.

**Process hierarchy:**
- User starts `retrovue` (the main program)
- `retrovue` spawns ProgramDirector ONLY
- ProgramDirector spawns ScheduleService and ChannelManager instances when needed
- ChannelManager spawns Air (playout engine) processes when needed to create the byte stream
- ChannelManager must **not** spawn ProgramDirector or the main retrovue process

**What ChannelManager is:**

- **Per-channel runtime controller**: A runtime component that controls playout for a single channel
- **Created by ProgramDirector**: ProgramDirector creates ChannelManager instances when needed
- **Spawns and supervises playout engine**: ChannelManager spawns and supervises its channel's internal playout engine process (Air)
- **Never hosts HTTP**: ChannelManager does not host HTTP servers
- **Never exposes UI**: ChannelManager does not expose operator interfaces or UI

**What ChannelManager is not:**

- Not a scheduler (that's [ScheduleDay](ScheduleDay.md) and planning systems)
- Not a UI or operator interface (that's ProgramDirector and CLI)
- Not a global authority or system controller (that's ProgramDirector)
- Not a policy enforcer (that's ProgramDirector)
- Not an HTTP server (it never hosts HTTP)
- Not a media decoder (that's the internal playout engine)
- Not an MPEG-TS generator (that's the internal playout engine)
- Not a timing controller (timing accuracy beyond schedule selection is handled by the internal playout engine)
- Not an ad inserter (that's a separate component or internal playout engine feature)
- Not a block scheduler (scheduling logic is upstream in the planning system)

## Responsibilities

### Core Responsibilities (Phase 8)

**Phase 8 has ONLY these responsibilities:**

1. **Maintain client refcount**: Track `client_count` (refcount) for its channel (increment on connect, decrement on disconnect)
2. **Load schedule.json**: Load and parse schedule data (JSON format) containing ScheduleItems for its channel
3. **Select active ScheduleItem**: Determine which ScheduleItem should be playing at the current time based on `start_time_utc` and `duration_seconds` (performed when coordinating playout, e.g. when `client_count` transitions 0 → 1)
4. **Build PlayoutRequest**: Convert active ScheduleItem to [PlayoutRequest](PlayoutRequest.md) format:
   - Map `asset_path` to PlayoutRequest's `asset_path` (one file only)
   - Set `start_pts` to `0` (Phase 8 rule)
   - Set `mode` to `"LIVE"` (Phase 8 rule)
   - Copy `channel_id` to PlayoutRequest
   - Copy `metadata` unchanged (opaque passthrough)
5. **Spawn Air and play single file**: When `client_count > 0`, spawn an Air (playout engine) process for its channel (zero or one per channel). ChannelManager **does** spawn Air; it must **not** spawn ProgramDirector or retrovue.
6. **Send PlayoutRequest as JSON**: Send exactly one PlayoutRequest (e.g. via stdin) to the Air process as JSON-encoded data, then close stdin.
7. **Terminate Air when unused**: When `client_count` drops to 0, terminate the Air process for its channel. ChannelManager owns Air lifecycle; it does **not** spawn or terminate ProgramDirector or retrovue.

**What Phase 8 does NOT do:**
- No playlists: The internal playout engine plays exactly one file per PlayoutRequest
- No preview/live: The internal playout engine does not have a preview deck or live/next asset switching
- No next-asset logic: ChannelManager does not determine or queue the next asset
- No mid-stream switching: ChannelManager does not change content while the playout engine is running
- No communication back from playout engine: ChannelManager does not receive events or notifications from the playout engine
- No global coordination: ChannelManager does not coordinate across channels (that's ProgramDirector)
- No policy enforcement: ChannelManager does not enforce system-wide policies (that's ProgramDirector)

### Client Connection Tracking

ChannelManager must maintain the number of connected streaming clients for its channel.

**Rules:**

- **Tracks `client_count`**: ChannelManager tracks the number of connected clients for its channel via lightweight HTTP pings or WebSocket events (implementation detail not required; just define responsibility)
- **Increments `client_count`**: When a client connects to the channel's stream endpoint, ChannelManager increments its `client_count`
- **Decrements `client_count`**: When a client disconnects or times out from the channel, ChannelManager decrements its `client_count`
- **If `client_count` drops to zero**: ChannelManager coordinates stopping playout for its channel. ChannelManager does **not** terminate retrovue processes; ProgramDirector owns lifecycle.
- **If `client_count` rises from 0 to 1**: ChannelManager coordinates starting playout for its channel and sends a PlayoutRequest to the playout engine (started by ProgramDirector). ChannelManager does **not** spawn retrovue subprocesses.

This rule overrides all schedule-change behaviors in Phase 8.

**Important:** 
- ChannelManager is a per-channel runtime controller
- ProgramDirector spawns a ChannelManager when one doesn't exist for the requested channel; ChannelManager spawns **Air** to play video
- Each channel has zero or one Air process (spawned and terminated by ChannelManager when `client_count` transitions)
- ChannelManager must **not** spawn ProgramDirector or the main retrovue process
- ChannelManager terminates Air when its channel's `client_count` reaches 0

### Phase 9+ Responsibilities

**Note:** The following responsibilities are reserved for future phases (Phase 9–12) and are **NOT part of Phase 8**:

6. **Maintain persistent connection to playout engine**: The playout engine will no longer auto-terminate; ChannelManager maintains long-lived connections to playout engine processes
7. **Interpret playout engine events**: Receive and interpret events from the playout engine ("asset taken live", "asset finished", etc.)
8. **Query ScheduleManager**: Ask ScheduleManager "what's next?" to resolve next asset decisions
9. **Fill playout engine's preview buffer**: Load assets into the playout engine's preview deck ahead of time
10. **Orchestrate advanced playout**: Manage back-to-back episodes, clock alignment, ad avails, bumpers, slates
11. **Manage 24×7 playout**: Ensure continuous playout with no gaps (the playout engine runs continuously, not just when clients connect)
12. **Automatic transitions**: Handle automatic transitions between schedule items based on timing and events

## Non-Responsibilities

ChannelManager explicitly does **not** handle:

- **Media decoding**: The internal playout engine handles all media decoding and playback
- **MPEG-TS generation**: The internal playout engine generates MPEG-TS output streams
- **Timing accuracy beyond selecting correct item**: ChannelManager only selects which ScheduleItem should be playing; the internal playout engine handles precise timing and synchronization
- **Ad insertion**: Ad insertion is handled by separate components or internal playout engine features
- **Block scheduling logic**: Schedule generation and block planning is handled upstream in the planning system

## Architecture

ChannelManager is a **per-channel runtime controller**. It is created by ProgramDirector. It spawns and supervises its channel's internal playout engine process. It never hosts HTTP and never exposes UI.

### ChannelManager Structure

**ChannelManager (ONE instance per channel):**
- **Per-channel controller**: Controls playout operations for its assigned channel
- **Client tracking**: Tracks `client_count` for its channel
- **Schedule consumption**: Loads and selects ScheduleItems for its channel
- **Playout coordination**: Coordinates with playout engines for its channel

### ChannelManager State

Each ChannelManager instance maintains state for its channel:

- **`client_count`**: Number of connected streaming clients for this channel
- **`schedule`**: Loaded schedule.json data containing ScheduleItems for this channel
- **`active ScheduleItem`**: Currently selected ScheduleItem (selected when coordinating playout)
- **`process handle for playout engine`**: Optional; only if ChannelManager connects to a ProgramDirector-started playout engine (ChannelManager does not spawn retrovue subprocesses)
- **`state machine`**: Internal state machine tracking channel state (idle, coordinating playout, playout running, etc.)
- **`per-channel timers`**: Timers for schedule transitions and timing events (Phase 9+)
- **`metadata cache`**: Cached metadata for the channel and active schedule items

### Internal Playout Engine (Per Channel)

- **Zero or one running instance per channel**: Each channel has at most one playout engine instance
- **Started by ProgramDirector**: `retrovue` spawns ProgramDirector; ProgramDirector spawns ChannelManager instances when needed; ChannelManager spawns Air when needed
- **Lifecycle coordinated by ChannelManager**: When `client_count` hits 0, ChannelManager coordinates stopping playout; ProgramDirector owns process termination

## Execution Model

### Schedule Loading

1. **Load schedule.json**: Read schedule data from a JSON file containing ScheduleItems for its channel
2. **Parse ScheduleItems**: Parse JSON into ScheduleItem objects with validation
3. **Index by time**: Index ScheduleItems by `start_time_utc` for efficient lookup

### Active ScheduleItem Selection

1. **Get current time**: Query [MasterClock](MasterClock.md) for current UTC time (strictly UTC, no timezone conversions)
2. **Find active ScheduleItem**: Select the ScheduleItem where:
   - `start_time_utc <= current_time_utc`
   - `current_time_utc < (start_time_utc + duration_seconds)`
   - `channel_id` matches its channel

### Handling Overlapping or Missing ScheduleItems

ChannelManager must handle the following cases when selecting active ScheduleItems for its channel:

**Case 1: No Active ScheduleItem (Schedule Gap)**

If no ScheduleItem is active at the current UTC time when attempting to coordinate playout:
- ChannelManager must **log an error** (e.g., `"no active schedule item for channel <id>"`)
- ChannelManager must **not** start playout (ChannelManager does not spawn retrovue subprocesses)
- ChannelManager must **not** send a PlayoutRequest
- ChannelManager continues running (does not exit)
- ChannelManager will retry when next client connects (client_count transitions 0 → 1)

**Note:** This is treated as a transient error, not a fatal startup error. ChannelManager remains running and will attempt to coordinate playout again when clients reconnect.

**Case 2: Multiple Active ScheduleItems (Overlapping Items)**

If multiple ScheduleItems are active at the current UTC time:
- ChannelManager must select the ScheduleItem with the **earliest `start_time_utc`**
- If multiple items have the same `start_time_utc`, selection behavior is implementation-specific (e.g., first in schedule array, or by `id` lexicographic order)
- ChannelManager proceeds with the selected ScheduleItem and generates a PlayoutRequest

**Case 3: Asset Path Invalid Before Sending Request**

If the active ScheduleItem's `asset_path` does not exist or is not accessible:
- ChannelManager must **validate** the asset path **before** coordinating playout
- ChannelManager must **fail** with a hard error (see Error Handling section)
- ChannelManager must **not** start playout (ChannelManager does not spawn retrovue subprocesses)
- ChannelManager must **not** send a PlayoutRequest
- ChannelManager continues running (does not exit)

ChannelManager must verify asset paths exist before generating PlayoutRequests. It must **not** coordinate playout with invalid paths—validation must occur in ChannelManager. ChannelManager continues running and will retry when next client connects.

**Case 4: Required Fields Missing**

If the active ScheduleItem is missing required fields:
- ChannelManager must **validate** required fields during schedule loading
- ChannelManager must **fail** with a hard error if any required field is missing
- ChannelManager must **not** start playout (ChannelManager does not spawn retrovue subprocesses)
- ChannelManager must **not** send a PlayoutRequest
- ChannelManager continues running (does not exit)

See Error Handling section for complete list of required fields and validation rules. ChannelManager continues running and will retry when next client connects.

## Phase 8 Runtime Model (CURRENT PHASE)

**NOTE: Phase 8 implements a simplified one-file playout pipeline for testing. Future phases add PREVIEW/LIVE buffers, continuous playout, signaling, and scheduling logic.**

**Phase 8 Runtime Architecture:**

ChannelManager is a **per-channel runtime controller**. It is created by ProgramDirector. It spawns and supervises its channel's internal playout engine process. It never hosts HTTP and never exposes UI.

**Important:** ChannelManager is a per-channel runtime controller. ProgramDirector manages multiple ChannelManager instances and provides the HTTP server and global coordination. ChannelManager spawns and supervises its channel's playout engine process.

The internal playout engine is disposable and invoked on-demand.

### Phase 8 Structure

**ChannelManager (ONE instance per channel):**
- **Per-channel controller**: Controls playout operations for its assigned channel
- **Client refcount**: Maintains `client_count` (refcount) for its channel
- **Schedule consumption**: Loads and selects ScheduleItems for its channel
- **Playout coordination**: Coordinates with playout engines for its channel

**Important Architecture Points:**
- **Per-channel instances**: Each channel has its own ChannelManager instance
- **ProgramDirector coordination**: ProgramDirector manages multiple ChannelManager instances and provides system-wide coordination
- **No global authority**: ChannelManager does not coordinate across channels or enforce system-wide policies

**ChannelManager State (Per Channel):**
- **`client_count`**: Reference count of connected streaming clients (starts at 0)
- **`schedule`**: Loaded schedule.json data containing ScheduleItems for this channel
- **`active ScheduleItem`**: Currently selected ScheduleItem (selected only when coordinating playout)
- **`process handle for playout engine`**: Optional; only if connecting to ProgramDirector-started playout engine (ChannelManager does not spawn retrovue subprocesses)

### Phase 8 Runtime Behavior

**On Viewer Connect:**

1. **Client connects** to channel stream endpoint (managed by ProgramDirector)
2. **ChannelManager increments refcount** (`client_count++`)
3. **If refcount transitions from 0 → 1**:
   - ChannelManager **selects current ScheduleItem** based on current UTC time
   - ChannelManager **builds PlayoutRequest** from the active ScheduleItem
   - ChannelManager **coordinates playout** with the playout engine (started by ProgramDirector; ChannelManager does **not** spawn retrovue subprocesses)
   - ChannelManager **sends PlayoutRequest** (e.g. via stdin) and closes stdin
   - The playout engine begins playout immediately
4. **ProgramDirector serves transport stream** via connection to the playout engine

**On Viewer Disconnect:**

1. **Client disconnects** from channel stream endpoint
2. **ChannelManager decrements refcount** (`client_count--`)
3. **If refcount hits 0**:
   - ChannelManager **coordinates stopping playout** (ProgramDirector owns process termination; ChannelManager does **not** spawn or terminate retrovue subprocesses)
   - ChannelManager waits idle for the next client

### Phase 8 Responsibilities

**The ONLY responsibilities in Phase 8:**

1. **Maintain client refcount**: Track `client_count` for its channel (increment on connect, decrement on disconnect)
2. **Coordinate playout with a single file**: When `client_count` transitions 0 → 1, ChannelManager coordinates with the playout engine for its channel (started by ProgramDirector) and sends exactly one PlayoutRequest containing one `asset_path`. ChannelManager does **not** spawn retrovue subprocesses.
3. **Coordinate playout stop when unused**: When `client_count` drops to 0, ChannelManager coordinates stopping playout. ChannelManager does **not** terminate retrovue processes; ProgramDirector owns lifecycle.

**What Phase 8 does NOT do (Temporary Simplifications):**

- **No playlists**: The internal playout engine plays exactly one file per PlayoutRequest; no playlist management
- **No preview/live switching**: The internal playout engine's preview/live architecture exists but is not actively used (simplified for Phase 8 testing)
- **No next-asset logic**: ChannelManager does not determine or queue the next asset to play
- **No mid-stream switching**: ChannelManager does not change content while the playout engine is running
- **No communication back from playout engine**: ChannelManager does not receive events or notifications from the playout engine (no "preview is ready", "asset taken live", "asset finished", etc.)
- **Simplified playout**: The internal playout engine may bypass preview/live buffers and play files directly (Phase 8 testing only)

**Note:** The internal playout engine's preview/live architecture exists and will be fully active in future phases. Phase 8 uses a simplified direct-playout mode for testing.

### Phase 8 Execution Flow

**Startup:**

1. **Start ChannelManager**: User starts `retrovue`; `retrovue` spawns ProgramDirector; ProgramDirector spawns ChannelManager instances when needed. ChannelManager does **not** spawn ProgramDirector or retrovue.
2. **Load schedule**: ChannelManager loads and parses schedule.json file for its channel
3. **Wait for client connections**: ChannelManager waits for clients to connect to its channel (via ProgramDirector)

**Runtime Cycle:**

```
Client connects to channel stream (via ProgramDirector)
    ↓
ChannelManager increments client_count from 0 → 1
    ↓
ChannelManager selects current ScheduleItem (based on current time)
    ↓
ChannelManager builds PlayoutRequest (one asset_path)
    ↓
ChannelManager coordinates playout (ProgramDirector starts playout engines; ChannelManager does not spawn them)
    ↓
ChannelManager sends PlayoutRequest (e.g. via stdin) and closes stdin
    ↓
Playout engine (started by ProgramDirector) begins playout
    ↓
ProgramDirector serves transport stream via connection to playout engine
    ↓
[... additional clients may connect/disconnect to/from this channel ...]
    ↓
Client disconnects (last client for this channel)
    ↓
ChannelManager decrements client_count from 1 → 0
    ↓
ChannelManager coordinates stopping playout (ProgramDirector owns process lifecycle)
    ↓
ChannelManager waits idle for the next client
```

**Important:** ChannelManager only exits on:
- Fatal errors (hard errors during startup that prevent operation)
- External shutdown (operator/system-initiated termination via ProgramDirector)

ChannelManager never terminates automatically under normal operation. Each channel has zero or one running internal playout engine instance at any time.

**Schedule Selection (Phase 8):**

ChannelManager selects the active ScheduleItem for its channel **only when coordinating playout** (i.e., when `client_count` transitions from 0 → 1). Once playout is active, ChannelManager does not change content until Phase 9.

**Schedule Change Handling (Phase 8):**

In Phase 8, ChannelManager does **not** restart the internal playout engine due to schedule changes:
- ChannelManager loads schedule.json for its channel at startup
- ChannelManager selects active ScheduleItem when coordinating playout (when `client_count` goes 0 → 1)
- Any changes to schedule.json **after** playout is active have no effect until the next playout coordination
- Changes to schedule.json do not trigger playout restarts in Phase 8
- ChannelManager does not terminate retrovue processes; ProgramDirector owns lifecycle

**What happens if a schedule item changes mid-playout:**
- The internal playout engine continues playing the asset from the PlayoutRequest it received
- ChannelManager does not restart the playout engine due to schedule changes
- To change what's playing, the operator must stop the playout engine (by disconnecting all clients) and wait for a new client to connect (which will trigger a new playout engine launch with the updated schedule)

**Phase 8 Limitations (Temporary Simplifications):**
- ChannelManager does **not** automatically restart the internal playout engine when schedule changes
- ChannelManager does **not** send multiple PlayoutRequests for transitions (single request per playout coordination)
- ChannelManager does **not** track when content ends or trigger transitions based on timing
- ChannelManager does **not** receive events or notifications from the playout engine (no "preview is ready", "asset taken live", "asset finished")
- ChannelManager does **not** use the playout engine's preview/live switching (architecture exists but simplified for Phase 8 testing)
- ChannelManager **only** manages the internal playout engine lifecycle based on `client_count`

**Note:** The internal playout engine's preview/live architecture exists and will be fully active in future phases. Phase 8 uses a simplified direct-playout mode for testing where PlayoutRequest may bypass preview/live buffers.


### PlayoutRequest Generation

1. **Extract asset path**: Copy `asset_path` from ScheduleItem to PlayoutRequest
2. **Set timing**: Set `start_pts` to `0` (Phase 8 always starts from beginning)
   - **Important:** `start_pts` is independent of ScheduleItem's `start_time_utc`
   - ScheduleItem's `start_time_utc` is used only for selecting the active item
   - Phase 8 always sets `start_pts = 0` regardless of ScheduleItem timing
   - ChannelManager does not use `start_time_utc` to calculate PTS offset
3. **Set mode**: Set `mode` to `"LIVE"` (Phase 8 only supports live mode)
4. **Copy channel**: Copy `channel_id` from ScheduleItem to PlayoutRequest
5. **Passthrough metadata**: Copy `metadata` object unchanged (opaque to ChannelManager)

**Phase 8 Timing Relationship:**
- ScheduleItem's `start_time_utc`: Used only for selecting which item is active at the current wall-clock time
- PlayoutRequest's `start_pts`: Always `0` in Phase 8, regardless of ScheduleItem's `start_time_utc`
- There is no temporal relationship between `start_time_utc` and `start_pts` in Phase 8
- ChannelManager uses `start_time_utc` for selection logic, but never uses it to calculate PTS offsets

### Internal Playout Engine (Air) Management (Phase 8)

**Phase 8 Process Hierarchy:**

- User starts `retrovue` (the main program)
- `retrovue` spawns ProgramDirector ONLY
- ProgramDirector spawns ChannelManager instances when needed (one per channel)
- ChannelManager spawns Air (playout engine) processes when needed to create the byte stream
- ChannelManager must **not** spawn ProgramDirector or the main retrovue process

**ChannelManager spawns Air**: Each channel has zero or one Air process at any time. ChannelManager spawns Air when `client_count` goes 0 → 1, terminates Air when `client_count` hits 0. ChannelManager does not spawn ProgramDirector or retrovue.

**Management Steps (Phase 8):**

1. **Track refcount**: ChannelManager tracks `client_count` for its channel
2. **Spawn Air on-demand**: When `client_count` transitions from 0 → 1, ChannelManager **spawns** an Air process for its channel. ChannelManager does **not** spawn ProgramDirector or retrovue.
   - **Zero or one per channel**: Each channel has at most one Air process (spawned by ChannelManager)
   - **On-demand**: Spawn when `client_count` transitions 0 → 1
3. **Send PlayoutRequest**: ChannelManager sends exactly one PlayoutRequest as JSON (e.g. via stdin) to the Air process it spawned
4. **Close stdin after sending**: ChannelManager closes stdin immediately after writing the complete JSON payload
5. **Monitor client_count**: ChannelManager continues monitoring its channel's `client_count` while Air is running
6. **Terminate Air when unused**: When `client_count` drops to 0, ChannelManager **terminates** the Air process for its channel. ChannelManager owns Air lifecycle; it does **not** spawn or terminate ProgramDirector or retrovue.

**Phase 8 Process Communication (Temporary Simplifications):**

- **No communication back from Air**: ChannelManager does NOT receive events or notifications from Air in Phase 8 (no "preview is ready", "asset taken live", "asset finished")
- **No persistent connection**: ChannelManager does NOT maintain a persistent connection to Air beyond the initial PlayoutRequest and stream
- **One-way communication**: ChannelManager sends one PlayoutRequest via stdin, closes stdin, and serves the transport stream from Air
- **No event handling**: ChannelManager does NOT interpret Air events like "preview is ready", "switch preview → live", "asset taken live", or "asset finished"
- **No preview/live switching**: ChannelManager does NOT send "switch preview → live" commands (Air's preview/live architecture exists but simplified for Phase 8 testing)

**Note:** Air's preview/live architecture exists and will be fully active in future phases. Phase 8 uses a simplified direct-playout mode for testing.

**Phase 8 Rules:**

- **Per-channel runtime controller**: ChannelManager controls playout for a single channel
- **ChannelManager spawns Air**: ChannelManager **does** spawn Air to play video. It must **not** spawn ProgramDirector or the main retrovue process. ProgramDirector spawns ChannelManager when one doesn't exist for the requested channel.
- **One Air per channel**: Each channel has zero or one Air process at any time (spawned and terminated by ChannelManager)
- **Spawn when client_count > 0**: ChannelManager spawns Air when its channel's `client_count` becomes >0
- **Terminate when client_count hits 0**: ChannelManager terminates Air when its channel's `client_count` drops to 0
- **Close stdin after writing**: ChannelManager closes stdin immediately after writing the complete PlayoutRequest JSON to the Air process it spawned
- **No communication back from Air**: ChannelManager does **NOT** receive events or notifications from Air in Phase 8
- **No schedule-based restarts**: ChannelManager does **NOT** restart Air due to schedule changes in Phase 8
- **No timing monitoring**: ChannelManager does **NOT** monitor Air for timing or transitions

### Phase 9+ Schedule Change Handling

**Note:** The following capabilities are reserved for future phases (Phase 9–12) and are **NOT part of Phase 8**.

When schedule changes are detected (Phase 9+):

1. **Detect change**: Monitor schedule.json for updates or detect active ScheduleItem changes
2. **Evaluate restart need**: Determine if the change requires restarting Air:
   - New active ScheduleItem with different asset path → restart required
   - Same ScheduleItem with updated metadata → restart may not be required (implementation-specific)
3. **Terminate current Air**: ChannelManager terminates the current Air process for that channel (ChannelManager owns Air lifecycle)
4. **Spawn new Air with updated request**: ChannelManager spawns a new Air process with updated PlayoutRequest (only if `client_count > 0`)

**Phase 8 vs Future Phases:**

- **Phase 8**: ChannelManager spawns and terminates Air based on `client_count` (spawn when 0 → 1, terminate when hits 0). ChannelManager does **not** spawn ProgramDirector or retrovue. No schedule-change-based restarts.
- **Phase 9+**: Will add schedule-change-based Air restarts, event-driven transitions, and persistent Air connections. ChannelManager still spawns Air; it does not spawn ProgramDirector or retrovue.

## Schedule Data Format

### Canonical schedule.json Format

**Phase 8 uses a per-channel schedule.json format.** Each channel has its own schedule.json file.

The canonical schedule.json format is a JSON object with a `channel_id` and `schedule` array.

### schedule.json Structure

**Phase 8 Format (Per-Channel File):**

```json
{
  "channel_id": "retro1",
  "schedule": [
    {
      "id": "retro1-2025-11-15-2000",
      "program_type": "series",
      "title": "Leave It to Beaver",
      "episode": "S01E03",
      "asset_path": "/media/shows/beaver/S01E03.mp4",
      "start_time_utc": "2025-11-15T20:00:00Z",
      "duration_seconds": 1800,
      "metadata": {
        "commType": "NONE",
        "bumpers": []
      }
    },
    {
      "id": "retro1-2025-11-15-2130",
      "program_type": "movie",
      "title": "Airplane!",
      "episode": null,
      "asset_path": "/media/movies/Airplane_1980.mp4",
      "start_time_utc": "2025-11-15T21:30:00Z",
      "duration_seconds": 5400,
      "metadata": {
        "commType": "none",
        "rating": "PG"
      }
    }
  ]
}
```

**Format Structure (Phase 8):**
- **Root object**: JSON object containing:
  - `channel_id` (string, required): Channel identifier (e.g., "retro1")
  - `schedule` (array, required): Array of ScheduleItem objects for this channel
- **channel_id**: Channel identifier matching the channel ChannelManager manages
- **schedule**: Array of ScheduleItem objects, each representing a scheduled content entry

**Future Phase Format (Multi-Channel):**

Future phases may use a multi-channel format with a `channels` array:

```json
{
  "channels": [
    {
      "channel_id": "retro1",
      "schedule": [
        {
          "id": "retro1-2025-11-15-2000",
          "program_type": "series",
          "title": "Leave It to Beaver",
          "episode": "S01E03",
          "asset_path": "/media/shows/beaver/S01E03.mp4",
          "start_time_utc": "2025-11-15T20:00:00Z",
          "duration_seconds": 1800,
          "metadata": {
            "commType": "NONE",
            "bumpers": []
          }
        }
      ]
    }
  ]
}
```

**Note:** The multi-channel format with `channels` array is reserved for future phases. Phase 8 uses per-channel files.

### schedule.json Rules

- **Schedule must be sorted by `start_time_utc`** (or ChannelManager sorts): ScheduleItems must be ordered by their start times for efficient active item selection. ChannelManager may sort the schedule if it is not pre-sorted.
- **Missing fields cause a hard failure**: All required ScheduleItem fields must be present. Missing required fields must cause ChannelManager to fail hard and not start.
- **`asset_path` must exist on disk**: ChannelManager must verify that `asset_path` exists and is accessible before generating PlayoutRequests.
- **ChannelManager must not validate file length**: ChannelManager does not validate that the file duration matches `duration_seconds`; it only verifies the file exists.
- **All times are UTC (no timezone conversions)**: All `start_time_utc` fields are ISO-8601 UTC timestamps. ChannelManager MUST NOT attempt timezone conversions. It must parse and compare strictly in UTC without any DST (daylight saving time) logic or timezone conversions.

### Schedule Loading Behavior

- **File location**: Configuration-specific (e.g., `/var/retrovue/schedules/channel_retro1.json`)
- **Refresh frequency**: Phase 8 does not refresh schedules automatically. Schedule reload requires restarting ChannelManager.
- **Validation**: Must validate ScheduleItem structure and required fields before use
- **Error handling**: See Error Handling section below for explicit error behavior

### Error Handling

ChannelManager must handle errors according to these explicit rules:

#### Hard Errors (Fatal - Daemon May Exit)

These errors are fatal per channel and may cause ChannelManager daemon to exit. In Phase 8, most errors are handled gracefully per channel to keep the daemon running:

1. **schedule.json missing**: If the schedule.json file does not exist at the expected path
   - **Behavior**: Log error, ChannelManager may exit (fatal startup error) OR retry periodically (implementation choice)
2. **schedule.json invalid JSON**: If the schedule.json file exists but cannot be parsed as valid JSON
   - **Behavior**: Log error, ChannelManager may exit (fatal startup error) OR retry periodically (implementation choice)
3. **Required fields missing**: If any required ScheduleItem field is missing when attempting to coordinate playout:
   - **Behavior**: Log error, ChannelManager does not start playout (ChannelManager does not spawn retrovue subprocesses), ChannelManager continues running
   - Fields: `id`, `channel_id`, `program_type`, `title`, `asset_path`, `start_time_utc`, `duration_seconds`
4. **No schedule item matching current time**: (See Case 1 in "Handling Overlapping or Missing ScheduleItems" - treated as transient error, ChannelManager continues)
5. **asset_path does not exist**: If the `asset_path` for the active ScheduleItem does not exist on disk or is not accessible when attempting to coordinate playout
   - **Behavior**: Log error, ChannelManager does not start playout (ChannelManager does not spawn retrovue subprocesses), ChannelManager continues running

**Hard Error Behavior:**
- ChannelManager must log errors with sufficient detail for debugging
- For fatal startup errors (schedule.json missing/invalid): ChannelManager may exit with non-zero status OR retry periodically
- For runtime errors (missing fields, missing asset, no active item): ChannelManager continues running, does not start playout (does not spawn retrovue subprocesses), will retry when next client connects
- ChannelManager must not start playout if validation fails

#### Soft Errors (Log + Continue)

These errors are logged but do not prevent ChannelManager from operating:

1. **metadata missing**: If a ScheduleItem has no `metadata` field, ChannelManager must treat it as an empty object `{}`
2. **Unknown metadata fields**: If metadata contains unknown keys, ChannelManager must ignore them and pass metadata through unchanged

**Soft Error Behavior:**
- ChannelManager must log a warning or info message
- ChannelManager must continue with default/fallback behavior
- ChannelManager must proceed with PlayoutRequest generation

## Examples

### Example: Selecting Active ScheduleItem

**Current time**: `2025-11-07T18:15:00Z`

**ScheduleItems**:
1. `start_time_utc: 2025-11-07T18:00:00Z`, `duration_seconds: 1800` (ends at 18:30:00Z)
2. `start_time_utc: 2025-11-07T20:00:00Z`, `duration_seconds: 5400` (ends at 21:30:00Z)

**Result**: ScheduleItem #1 is active (current time falls within its duration window)

### Example: Generating PlayoutRequest

**Active ScheduleItem**:
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

**Generated PlayoutRequest**:
```json
{
  "asset_path": "/mnt/media/tv/Cheers/Season2/Cheers_S02E05.mp4",
  "start_pts": 0,
  "mode": "LIVE",
  "channel_id": "retro1",
  "metadata": {
    "commType": "standard",
    "bumpers": {
      "intro": true,
      "outro": true
    }
  }
}
```

### Example: Playout Engine (Started by ProgramDirector) and PlayoutRequest

**ProgramDirector starts the playout engine** (ChannelManager does **not** spawn retrovue subprocesses):
```bash
retrovue_air --channel retro1
```

**ChannelManager sends PlayoutRequest** (e.g. via stdin) to the playout engine that ProgramDirector started:
```bash
echo '{"asset_path":"/mnt/media/tv/Cheers/Season2/Cheers_S02E05.mp4","start_pts":0,"mode":"LIVE","channel_id":"retro1","metadata":{"commType":"standard"}}' | retrovue_air --channel retro1
```

## Relationships

ChannelManager relates to:

- **ScheduleItem** (reads): ChannelManager reads [ScheduleItem](ScheduleItem.md) entries from schedule.json and selects active items for its channel
- **PlayoutRequest** (generates): ChannelManager generates [PlayoutRequest](PlayoutRequest.md) objects from ScheduleItems and sends them to the internal playout engine process
- **Channel** (controls for): ChannelManager controls playout for a single [Channel](Channel.md) instance
- **MasterClock** (queries): ChannelManager uses [MasterClock](MasterClock.md) to determine the current UTC time for ScheduleItem selection
- **Air (playout engine)** (spawns): ChannelManager spawns Air processes (zero or one per channel) when needed to create the byte stream. ChannelManager owns Air lifecycle.
- **ProgramDirector** (managed by): User starts `retrovue` → `retrovue` spawns ProgramDirector → ProgramDirector spawns ChannelManager instances when needed. ProgramDirector provides system-wide coordination and policy enforcement.

## Constraints

- **Per-channel runtime controller**: ChannelManager controls playout for a single channel
- **Schedule-driven only**: ChannelManager only plays content that exists in schedule.json; it does not generate or modify schedules
- **Phase 8 timing rules**: ChannelManager always sets `start_pts=0` and `mode="LIVE"` when generating PlayoutRequests (Phase 8 requirements)
- **Metadata passthrough**: ChannelManager does not inspect or validate metadata; it passes it unchanged to the internal playout engine
- **Per-channel persistent runtime**: ChannelManager never terminates automatically under normal operation. It must remain running to track connected clients for its channel.
- **On-demand playout**: Each channel has zero or one Air process, spawned by ChannelManager. ChannelManager spawns Air to play video and terminates Air when `client_count` hits 0. ChannelManager does **not** spawn ProgramDirector or retrovue.
- **Process hierarchy**: User starts `retrovue` → `retrovue` spawns ProgramDirector → ProgramDirector spawns ChannelManager when needed → ChannelManager spawns Air when needed. ChannelManager does **not** spawn ProgramDirector or the main retrovue process.
- **No global authority**: ChannelManager does not coordinate across channels or enforce system-wide policies (that's ProgramDirector)
- **No UI or operator interface**: ChannelManager is not operator-facing (that's ProgramDirector and CLI)

## Phase 8 Runtime Sequence Example

The following sequence demonstrates Phase 8 behavior:

```
Client connects to channel stream (via ProgramDirector)
    ↓
ChannelManager increments refcount (client_count++) from 0 → 1
    ↓
[refcount transition: 0 → 1]
    ↓
ChannelManager selects current ScheduleItem (based on current UTC time)
    ↓
ChannelManager builds PlayoutRequest (one asset_path)
    ↓
ChannelManager spawns Air process for its channel
    ↓
ChannelManager sends PlayoutRequest (e.g. via stdin) to Air and closes stdin
    ↓
Air begins playout
    ↓
ProgramDirector serves transport stream via connection to Air
    ↓
Client streams MPEG-TS from channel stream
    ↓
[... additional clients may connect/disconnect to/from this channel ...]
    [... refcount increments/decrements accordingly ...]
    ↓
Client disconnects (last client for this channel)
    ↓
ChannelManager decrements refcount (client_count--) from 1 → 0
    ↓
[refcount hits 0]
    ↓
ChannelManager terminates Air for its channel
    ↓
ChannelManager waits idle for the next client
```

**Phase 8 Key Points:**
- **Refcount-driven**: ChannelManager spawns Air when refcount goes 0 → 1, terminates Air when refcount hits 0. ChannelManager does **not** spawn ProgramDirector or retrovue.
- **One request per coordination**: ChannelManager sends exactly one PlayoutRequest per playout coordination
- **No communication back**: ChannelManager does NOT receive events from the playout engine
- **Single file playout**: The playout engine plays exactly one file until EOF or termination

## Future Runtime Model (Phase 9–12)

**Note:** The following capabilities are reserved for future phases (Phase 9–12). They are **NOT coded in Phase 8**.

### Future Phase Capabilities

In later phases, ChannelManager will expand its responsibilities significantly:

**Persistent Connection to Air:**

- **Maintain a persistent connection to Air**: Air will no longer auto-terminate when `client_count` drops to 0
- **Long-lived Air processes**: Air processes will run continuously and manage transitions internally
- **Bidirectional communication**: ChannelManager and Air will maintain active communication channels

**Interpret Air Events:**

ChannelManager will receive and interpret events from Air (Air's preview/live architecture exists, will be fully active):

- **"preview is ready"**: Air notifies ChannelManager when an asset is loaded and ready in the preview buffer
- **"asset taken live"**: Air notifies ChannelManager when an asset transitions from preview to live
- **"asset finished"**: Air notifies ChannelManager when an asset finishes playing (EOF)
- **Other playback events**: Air may send additional events for error conditions, playback status, etc.

**Query ScheduleManager:**

ChannelManager will query ScheduleManager to resolve scheduling decisions:

- **"What's next?" logic**: ChannelManager will ask ScheduleManager "what's next?" to determine the next asset to play
- **Schedule resolution**: ChannelManager will resolve schedule items, asset sequences, and timing decisions via ScheduleManager
- **Dynamic scheduling**: ChannelManager will handle schedule changes and operator overrides in real-time

**Fill Air's Preview Buffer:**

ChannelManager will manage Air's preview buffer (architecture exists, will be fully active):

- **Preview buffer management**: ChannelManager will load assets into Air's preview buffer via PlayoutRequest ahead of time
- **Preview ready signaling**: Air signals "preview is ready" → ChannelManager sends "switch preview → live"
- **Next asset queuing**: ChannelManager will continuously load next assets into Air's preview buffer before current asset finishes
- **Preview/live switching**: ChannelManager will orchestrate transitions from preview to live, then load next asset into preview (continuous chain)

**Orchestrate Advanced Playout:**

ChannelManager will orchestrate sophisticated playout operations:

- **Back-to-back episodes**: ChannelManager will manage continuous playout of sequential episodes without gaps
- **Clock alignment**: ChannelManager will ensure content starts at precise clock times and maintains synchronization
- **Ad avails**: ChannelManager will manage commercial break insertion and ad placement
- **Bumpers**: ChannelManager will insert bumpers (intro/outro segments) between content
- **Slates**: ChannelManager will insert slates during gaps or transitions

**Manage 24×7 Playout:**

ChannelManager will ensure continuous playout operation:

- **No gaps**: ChannelManager will manage playout to eliminate schedule gaps and dead air
- **Continuous operation**: Air will run continuously, not just when clients are connected
- **Automatic transitions**: ChannelManager will automatically transition between schedule items based on timing
- **Fallback handling**: ChannelManager will handle schedule gaps with slates, filler content, or other fallback mechanisms

### Future Phase vs Phase 8 Comparison

**Phase 8 (Current - Temporary Simplifications):**
- Air terminates when `client_count` drops to 0
- No communication from Air back to ChannelManager (no "preview is ready", "asset taken live", "asset finished")
- Air's preview/live architecture exists but is not actively used (simplified for testing)
- No preview buffer management or preview/live switching (architecture exists, simplified for Phase 8)
- No "what's next?" logic
- No automatic transitions
- Single file playout only (simplified direct-playout mode for testing)
- Air runs only when clients are connected

**Phase 9–12 (Future - Full Preview/Live Architecture):**
- Air runs persistently (does not auto-terminate)
- Bidirectional communication between ChannelManager and Air (preview ready signals, switch commands, asset finished events)
- Preview/live buffer management fully active (load into preview → "preview is ready" → "switch preview → live" → load next into preview)
- Continuous preview chaining (ChannelManager continuously loads next assets into preview before current finishes)
- ScheduleManager integration for "what's next?" queries
- Automatic transitions based on timing and events
- Multi-file sequences and asset chaining via preview/live switching
- 24×7 continuous playout with no gaps

**Important:** All advanced features (preview/live switching, event handling, schedule queries, orchestration, continuous playout) are reserved for future phases. Phase 8 focuses solely on: maintaining client refcount, **spawning Air** to play single files (ChannelManager spawns Air; it does not spawn ProgramDirector or retrovue), and terminating Air when unused.

## Naming Rules

The canonical name for this concept in code and documentation is **ChannelManager**.

ChannelManager represents the system-wide runtime orchestrator that manages all channels — it bridges the gap between scheduled content (ScheduleItems) and playout execution (the internal playout engine) for all channels in the system.

## Operator Workflows

**Start ChannelManager**: User starts `retrovue`; `retrovue` spawns ProgramDirector; ProgramDirector spawns ChannelManager instances when needed. ChannelManager loads schedule.json for its channel and waits for clients to connect. When the first client connects to a channel's stream endpoint (via ProgramDirector), ChannelManager selects the active ScheduleItem, **spawns Air** to play video, and sends a PlayoutRequest. ChannelManager does **not** spawn ProgramDirector or retrovue.

**Monitor Active ScheduleItem**: View which ScheduleItem ChannelManager has selected as active for its channel at the current time. Verify that the selection logic matches expectations.

**Inspect PlayoutRequests**: Review PlayoutRequests generated by each ChannelController to verify correct translation from ScheduleItems. Check that Phase 8 rules (`start_pts=0`, `mode="LIVE"`) are applied per channel.

**Manage Air Processes**: Monitor the Air process status managed by each ChannelManager. ChannelManager spawns Air when viewers connect; verify that Air starts correctly per channel and receives PlayoutRequests via stdin. Each channel has zero or one running Air process at any time.

**Schedule Updates**: Update schedule.json files per channel and verify that ChannelManagers detect changes (Phase 9+). In Phase 8, schedule changes do not trigger Air restarts; changes only take effect when ChannelManager spawns a new Air for that channel (e.g. when that channel's `client_count` transitions from 0 → 1).

**Debugging**: Use ChannelManager logs to diagnose schedule selection issues, PlayoutRequest generation problems, or Air process spawn/terminate failures.

## See Also

- [ScheduleItem](ScheduleItem.md) - Schedule entries consumed by ChannelManager
- [PlayoutRequest](PlayoutRequest.md) - Playout instructions generated by ChannelManager
- [Channel](Channel.md) - Channel configuration managed by ChannelManager
- [MasterClock](MasterClock.md) - Time source used by ChannelManager for ScheduleItem selection
- [PlayoutPipeline](PlayoutPipeline.md) - Playout execution pipeline that includes ChannelManager
- [Runtime ChannelManager](../runtime/ChannelManager.md) - Runtime implementation details

