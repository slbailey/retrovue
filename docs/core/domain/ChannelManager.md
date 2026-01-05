_Related: [Architecture](../architecture/ArchitectureOverview.md) • [Runtime](../runtime/ChannelManager.md) • [ScheduleItem](ScheduleItem.md) • [PlayoutRequest](PlayoutRequest.md) • [Channel](Channel.md) • [MasterClock](MasterClock.md)_

# Domain — ChannelManager

## Purpose

ChannelManager is a **long-running system-wide daemon** responsible for managing **ALL channels**. It is a single persistent process that orchestrates playout execution for all channels in the system. ChannelManager selects the correct [ScheduleItem](ScheduleItem.md) for each channel's current time and launches Retrovue Air (disposable, on-demand) processes with valid [PlayoutRequest](PlayoutRequest.md) objects. ChannelManager runs indefinitely and never terminates automatically.

**What ChannelManager is:**

- **System-wide daemon**: A long-running system-wide daemon process that never terminates automatically; manages ALL channels in a single process
- **Global HTTP server**: Runs a global HTTP server (typically on port 9000) that serves `/channel/<id>.ts` endpoints for all channels
- **Channel registry**: Contains a ChannelRegistry that tracks all channels in the system
- **Per-channel controller orchestrator**: Manages playout execution for multiple channels, each with its own ChannelController instance
- **Schedule consumer**: Reads schedule data and selects active ScheduleItems for each channel
- **Client connection tracker**: Monitors and tracks connected streaming clients (`client_count`) per channel
- **Playout launcher**: Translates ScheduleItems to PlayoutRequests and launches Retrovue Air processes on-demand (zero or one per channel)
- **Process manager**: Manages Retrovue Air process lifecycle per channel based on `client_count` (Retrovue Air is disposable and invoked on-demand)

**What ChannelManager is not:**

- Not a scheduler (that's [ScheduleDay](ScheduleDay.md) and planning systems)
- Not a media decoder (that's Retrovue Air)
- Not an MPEG-TS generator (that's Retrovue Air)
- Not a timing controller (timing accuracy beyond schedule selection is handled by Retrovue Air)
- Not an ad inserter (that's a separate component or Retrovue Air feature)
- Not a block scheduler (scheduling logic is upstream in the planning system)

## Responsibilities

### Core Responsibilities (Phase 8)

**Phase 8 has ONLY these responsibilities:**

1. **Run global HTTP server**: Operate exactly one long-running HTTP server (typically on port 9000) that serves:
   - Global M3U playlist: `/channellist.m3u` for channel discovery
   - All channel endpoints: `/channel/1.ts`, `/channel/2.ts`, `/channel/retro1.ts`, etc.
   - All channels are served from this single HTTP server (no per-channel servers)
2. **Maintain ChannelRegistry**: Manage a ChannelRegistry containing ChannelController objects for all channels in the system
3. **Serve transport stream**: ChannelManager serves MPEG-TS transport stream via an internal pipe from Air to HTTP endpoint (`/channel/<id>.ts`)
4. **Maintain client refcount per channel**: Each ChannelController tracks `client_count` (refcount) for its channel (increment on connect, decrement on disconnect)
5. **Load schedule.json per channel**: Load and parse schedule data (JSON format) containing ScheduleItems for each channel's ChannelController
6. **Select active ScheduleItem per channel**: For each channel, determine which ScheduleItem should be playing at the current time based on `start_time_utc` and `duration_seconds` (performed only when launching Retrovue Air for that channel, when `client_count` transitions 0 → 1)
7. **Build PlayoutRequest**: Convert active ScheduleItem to [PlayoutRequest](PlayoutRequest.md) format:
   - Map `asset_path` to PlayoutRequest's `asset_path` (one file only)
   - Set `start_pts` to `0` (Phase 8 rule)
   - Set `mode` to `"LIVE"` (Phase 8 rule)
   - Copy `channel_id` to PlayoutRequest
   - Copy `metadata` unchanged (opaque passthrough)
8. **Launch Air with a single file**: Start Retrovue Air processes for channels when `client_count > 0` (zero or one running instance per channel; Retrovue Air is disposable and invoked on-demand)
9. **Provide PlayoutRequest via stdin as JSON**: Send exactly one PlayoutRequest to Retrovue Air process via stdin as JSON-encoded data, then close stdin
10. **Kill Air when unused**: Stop Retrovue Air processes when `client_count` drops to 0 for that channel

**What Phase 8 does NOT do:**
- No playlists: Air plays exactly one file per PlayoutRequest
- No preview/live: Air does not have a preview deck or live/next asset switching
- No next-asset logic: ChannelManager does not determine or queue the next asset
- No mid-stream switching: ChannelManager does not change content while Air is running
- No communication back from Air: ChannelManager does not receive events or notifications from Air

### Client Connection Tracking

Each ChannelController within ChannelManager must maintain the number of connected streaming clients for its channel.

**Rules (Per Channel):**

- **Tracks `client_count`**: Each ChannelController tracks the number of connected clients for its channel via lightweight HTTP pings or WebSocket events (implementation detail not required; just define responsibility)
- **Increments `client_count`**: When a client connects to a channel's stream endpoint, that channel's ChannelController increments its `client_count`
- **Decrements `client_count`**: When a client disconnects or times out from a channel, that channel's ChannelController decrements its `client_count`
- **If `client_count` drops to zero**: ChannelController must terminate the Retrovue Air process for that channel immediately
- **If `client_count` rises from 0 to 1**: ChannelController must start or restart Retrovue Air for that channel and issue a new PlayoutRequest

This rule overrides all schedule-change behaviors in Phase 8.

**Important:** 
- ChannelManager is a system-wide persistent daemon that never terminates automatically
- Each channel has zero or one running Retrovue Air instance (spawned by ChannelManager, killed when `client_count` hits 0)
- Retrovue Air is disposable and invoked on-demand when `client_count > 0` for a channel
- ChannelManager never shuts down Retrovue Air due to scheduling in Phase 8
- ChannelManager only stops Air when a channel's `client_count` reaches 0

### Phase 9+ Responsibilities

**Note:** The following responsibilities are reserved for future phases (Phase 9–12) and are **NOT part of Phase 8**:

6. **Maintain persistent connection to Air**: Air will no longer auto-terminate; ChannelManager maintains long-lived connections to Air processes
7. **Interpret Air events**: Receive and interpret events from Air ("asset taken live", "asset finished", etc.)
8. **Query ScheduleManager**: Ask ScheduleManager "what's next?" to resolve next asset decisions
9. **Fill Air's preview buffer**: Load assets into Air's preview deck ahead of time
10. **Orchestrate advanced playout**: Manage back-to-back episodes, clock alignment, ad avails, bumpers, slates
11. **Manage 24×7 playout**: Ensure continuous playout with no gaps (Air runs continuously, not just when clients connect)
12. **Automatic transitions**: Handle automatic transitions between schedule items based on timing and events

## Non-Responsibilities

ChannelManager explicitly does **not** handle:

- **Media decoding**: Retrovue Air handles all media decoding and playback
- **MPEG-TS generation**: Retrovue Air generates MPEG-TS output streams
- **Timing accuracy beyond selecting correct item**: ChannelManager only selects which ScheduleItem should be playing; Retrovue Air handles precise timing and synchronization
- **Ad insertion**: Ad insertion is handled by separate components or Retrovue Air features
- **Block scheduling logic**: Schedule generation and block planning is handled upstream in the planning system

## Architecture

ChannelManager is a **single system-wide daemon process** that manages all channels in the system.

### ChannelManager Structure

**ChannelManager (ONE process):**
- **Global HTTP server**: Runs on port 9000 (or configured port), serves `/channel/<id>.ts` endpoints for all channels
- **ChannelRegistry**: Contains a registry/dictionary mapping channel IDs to ChannelController objects
- **Per-channel management**: Each channel has its own ChannelController instance within the single ChannelManager process

### ChannelController (Per Channel)

Each entry in the ChannelRegistry is a **ChannelController** object that manages a single channel:

- **`client_count`**: Number of connected streaming clients for this channel
- **`schedule`**: Loaded schedule.json data containing ScheduleItems for this channel
- **`active ScheduleItem`**: Currently selected ScheduleItem (selected when launching Air)
- **`process handle for Air`**: Process handle/PID for the Retrovue Air instance (if running)
- **`state machine`**: Internal state machine tracking channel state (idle, launching Air, Air running, etc.)
- **`per-channel timers`**: Timers for schedule transitions and timing events (Phase 9+)
- **`metadata cache`**: Cached metadata for the channel and active schedule items
- **`stream endpoint`**: HTTP endpoint path for this channel (e.g., `/channel/retro1.ts`)

### Retrovue Air (Per Channel)

- **Zero or one running instance per channel**: Each channel has at most one running Retrovue Air process
- **Spawned by ChannelManager**: Air processes are spawned by ChannelManager's ChannelController for that channel
- **Killed when `client_count` hits 0**: Air process is terminated when the channel's `client_count` drops to 0

## Execution Model

### Schedule Loading (Per Channel)

1. **Load schedule.json**: For each channel's ChannelController, read schedule data from a JSON file containing ScheduleItems for that channel
2. **Parse ScheduleItems**: Parse JSON into ScheduleItem objects with validation
3. **Index by time**: Index ScheduleItems by `start_time_utc` for efficient lookup per channel

### Active ScheduleItem Selection (Per Channel)

1. **Get current time**: Query [MasterClock](MasterClock.md) for current UTC time (strictly UTC, no timezone conversions)
2. **Find active ScheduleItem**: For a specific channel, select the ScheduleItem where:
   - `start_time_utc <= current_time_utc`
   - `current_time_utc < (start_time_utc + duration_seconds)`
   - `channel_id` matches the target channel

### Handling Overlapping or Missing ScheduleItems

Each ChannelController must handle the following cases when selecting active ScheduleItems for its channel:

**Case 1: No Active ScheduleItem (Schedule Gap)**

If no ScheduleItem is active at the current UTC time when attempting to launch Retrovue Air for a channel:
- ChannelController must **log an error** (e.g., `"no active schedule item for channel <id>"`)
- ChannelController must **not** launch Retrovue Air for that channel
- ChannelController must **not** send a PlayoutRequest
- ChannelManager daemon continues running (does not exit)
- ChannelController will retry when next client connects to that channel (client_count transitions 0 → 1)

**Note:** This is treated as a transient error, not a fatal startup error. ChannelManager daemon remains running and the ChannelController will attempt to launch Air again when clients reconnect to that channel.

**Case 2: Multiple Active ScheduleItems (Overlapping Items)**

If multiple ScheduleItems are active at the current UTC time for a channel:
- ChannelController must select the ScheduleItem with the **earliest `start_time_utc`**
- If multiple items have the same `start_time_utc`, selection behavior is implementation-specific (e.g., first in schedule array, or by `id` lexicographic order)
- ChannelController proceeds with the selected ScheduleItem and generates a PlayoutRequest for that channel

**Case 3: Asset Path Invalid Before Sending Request**

If the active ScheduleItem's `asset_path` does not exist or is not accessible for a channel:
- ChannelController must **validate** the asset path **before** launching Retrovue Air for that channel
- ChannelController must **fail** with a hard error (see Error Handling section)
- ChannelController must **not** launch Retrovue Air for that channel
- ChannelController must **not** send a PlayoutRequest for that channel
- ChannelManager daemon continues running (does not exit)

ChannelController must verify asset paths exist before generating PlayoutRequests. It must **not** launch Retrovue Air and let it fail—validation must occur in ChannelController. The ChannelManager daemon continues running and will retry when next client connects to that channel.

**Case 4: Required Fields Missing**

If the active ScheduleItem is missing required fields for a channel:
- ChannelController must **validate** required fields during schedule loading
- ChannelController must **fail** with a hard error if any required field is missing
- ChannelController must **not** launch Retrovue Air for that channel
- ChannelController must **not** send a PlayoutRequest for that channel
- ChannelManager daemon continues running (does not exit)

See Error Handling section for complete list of required fields and validation rules. The ChannelManager daemon continues running and will retry when next client connects to that channel.

## Phase 8 Runtime Model (CURRENT PHASE)

**NOTE: Phase 8 implements a simplified one-file playout pipeline for testing. Future phases add PREVIEW/LIVE buffers, continuous playout, signaling, and scheduling logic.**

**Phase 8 Runtime Architecture:**

ChannelManager is a **single, long-running HTTP server serving ALL channels**. It is a single persistent process (not per-channel) that never terminates automatically. ChannelManager serves:
- The global M3U playlist: `/channellist.m3u`
- All channel endpoints: `/channel/1.ts`, `/channel/2.ts`, etc.
- The logic that selects schedules
- The logic that feeds Air

**Important:** ChannelManager is **exactly one HTTP server** serving everything. There is no per-channel HTTP server. ProgramManager does not run a separate HTTP server. All channels are served from a single ChannelManager process.

Retrovue Air is disposable and invoked on-demand.

### Phase 8 Structure

**ChannelManager (ONE process - Single HTTP Server):**
- **Single long-running HTTP server**: Operates exactly one HTTP server (typically port 9000) serving ALL channels
- **Global M3U playlist**: Serves `/channellist.m3u` for channel discovery
- **Per-channel endpoints**: Each channel has one HTTP endpoint (e.g., `/channel/1.ts`, `/channel/2.ts`, `/channel/retro1.ts`)
- **ChannelRegistry**: Contains ChannelController objects for all channels in the system
- **Client refcount per channel**: Each ChannelController maintains a `client_count` (refcount) for its channel

**Important Architecture Points:**
- **One HTTP server for everything**: ChannelManager runs exactly one HTTP server serving all channels and the global M3U playlist
- **No per-channel HTTP servers**: Each channel does not have its own HTTP server
- **No separate ProgramManager HTTP server**: ProgramManager does not run a separate HTTP server
- **Single process, multiple channels**: One ChannelManager process manages all channels via ChannelController instances

**ChannelController (Per Channel):**
- **`client_count`**: Reference count of connected streaming clients (starts at 0)
- **`schedule`**: Loaded schedule.json data containing ScheduleItems for this channel
- **`active ScheduleItem`**: Currently selected ScheduleItem (selected only when launching Air)
- **`process handle for Air`**: Process handle/PID for the Retrovue Air instance (if running)
- **`stream endpoint`**: HTTP endpoint path for this channel (e.g., `/channel/retro1.ts`)

### Phase 8 Runtime Behavior

**On Viewer Connect:**

1. **Client connects** to `/channel/<id>.ts` endpoint
2. **ChannelController increments refcount** (`client_count++`)
3. **If refcount transitions from 0 → 1**:
   - ChannelController **selects current ScheduleItem** based on current UTC time
   - ChannelController **builds PlayoutRequest** from the active ScheduleItem
   - ChannelController **launches Air for that channel** (on-demand, disposable)
   - ChannelController **sends PlayoutRequest via stdin** and closes stdin
   - Air begins playout immediately
4. **ChannelManager serves transport stream** via an internal pipe from Air to HTTP endpoint

**On Viewer Disconnect:**

1. **Client disconnects** from `/channel/<id>.ts` endpoint
2. **ChannelController decrements refcount** (`client_count--`)
3. **If refcount hits 0**:
   - ChannelController **terminates Air** for that channel
   - Air process is disposed (killed)
   - ChannelController waits idle for the next client

### Phase 8 Responsibilities

**The ONLY responsibilities in Phase 8:**

1. **Serve transport stream**: ChannelManager serves MPEG-TS transport stream via an internal pipe from Air to HTTP endpoint (`/channel/<id>.ts`)
2. **Maintain client refcount per channel**: Each ChannelController tracks `client_count` for its channel (increment on connect, decrement on disconnect)
3. **Launch Air with a single file**: When `client_count` transitions 0 → 1, ChannelController launches Air for that channel with exactly one PlayoutRequest containing one `asset_path`
4. **Kill Air when unused**: When `client_count` drops to 0, ChannelController terminates Air for that channel

**What Phase 8 does NOT do (Temporary Simplifications):**

- **No playlists**: Air plays exactly one file per PlayoutRequest; no playlist management
- **No preview/live switching**: Air's preview/live architecture exists but is not actively used (simplified for Phase 8 testing)
- **No next-asset logic**: ChannelManager does not determine or queue the next asset to play
- **No mid-stream switching**: ChannelManager does not change content while Air is running
- **No communication back from Air**: ChannelManager does not receive events or notifications from Air (no "preview is ready", "asset taken live", "asset finished", etc.)
- **Simplified playout**: Air may bypass preview/live buffers and play files directly (Phase 8 testing only)

**Note:** Air's preview/live architecture exists and will be fully active in future phases. Phase 8 uses a simplified direct-playout mode for testing.

### Phase 8 Execution Flow

**Startup:**

1. **Start ChannelManager**: Launch ChannelManager as a system-wide daemon (ONE process for all channels)
2. **Initialize ChannelRegistry**: Create and initialize the ChannelRegistry
3. **Start global HTTP server**: Start the global HTTP server (port 9000) serving `/channel/<id>.ts` endpoints for all channels
4. **Load schedules per channel**: For each channel in the registry, ChannelController loads and parses schedule.json files
5. **Wait for client connections**: ChannelManager waits for clients to connect to channel endpoints

**Runtime Cycle (Per Channel):**

```
Client connects to /channel/<id>.ts
    ↓
ChannelController increments client_count from 0 → 1
    ↓
ChannelController selects current ScheduleItem (based on current time)
    ↓
ChannelController builds PlayoutRequest (one asset_path)
    ↓
ChannelController launches Air for that channel
    ↓
ChannelController sends PlayoutRequest via stdin and closes stdin
    ↓
Air begins playout immediately
    ↓
ChannelManager serves transport stream via internal pipe from Air → /channel/<id>.ts
    ↓
[... additional clients may connect/disconnect to/from this channel ...]
    ↓
Client disconnects (last client for that channel)
    ↓
ChannelController decrements client_count from 1 → 0
    ↓
ChannelController terminates Air for that channel
    ↓
ChannelController waits idle for the next client (ChannelManager daemon continues running)
```

**Important:** ChannelManager only exits on:
- Fatal errors (hard errors during startup that prevent operation)
- External shutdown (operator/system-initiated termination)

ChannelManager never terminates automatically under normal operation. Each channel has zero or one running Air instance at any time.

**Schedule Selection (Phase 8):**

Each ChannelController selects the active ScheduleItem for its channel **only when launching Air** (i.e., only when that channel's `client_count` transitions from 0 → 1). Once Air is running for a channel, ChannelController does not change content for that channel until Phase 9.

**Schedule Change Handling (Phase 8):**

In Phase 8, ChannelControllers do **not** restart Retrovue Air due to schedule changes:
- ChannelController loads schedule.json for its channel at startup
- ChannelController selects active ScheduleItem when launching Retrovue Air for its channel (when that channel's `client_count` goes 0 → 1)
- Any changes to schedule.json **after** Retrovue Air is running for a channel have no effect until the next Air launch for that channel
- Changes to schedule.json do not trigger Air restarts in Phase 8
- ChannelController never shuts down Retrovue Air due to scheduling in Phase 8

**What happens if a schedule item changes mid-playout:**
- Retrovue Air for a channel continues playing the asset from the PlayoutRequest it received
- ChannelController does not restart Air for that channel due to schedule changes
- To change what's playing, the operator must stop Retrovue Air for that channel (by disconnecting all clients from that channel) and wait for a new client to connect (which will trigger a new Air launch for that channel with the updated schedule)

**Phase 8 Limitations (Temporary Simplifications):**
- ChannelControllers do **not** automatically restart Retrovue Air when schedule changes
- ChannelControllers do **not** send multiple PlayoutRequests for transitions (single request per Air launch per channel)
- ChannelControllers do **not** track when content ends or trigger transitions based on timing
- ChannelControllers do **not** receive events or notifications from Air (no "preview is ready", "asset taken live", "asset finished")
- ChannelControllers do **not** use Air's preview/live switching (architecture exists but simplified for Phase 8 testing)
- ChannelControllers **only** manage Retrovue Air lifecycle based on each channel's `client_count`

**Note:** Air's preview/live architecture exists and will be fully active in future phases. Phase 8 uses a simplified direct-playout mode for testing where PlayoutRequest may bypass preview/live buffers.


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

### Retrovue Air Process Management (Phase 8)

**Phase 8 Process Management:**

Each ChannelController launches Retrovue Air **on-demand** only when its channel's `client_count` becomes >0.

**Retrovue Air is disposable per channel**: Each channel has zero or one running Air instance at any time. Instances are created on-demand, used for playback, and disposed of when no longer needed. Retrovue Air processes are fully ephemeral.

ChannelManager (the system-wide daemon) may run for days or weeks without restarting. Retrovue Air processes per channel come and go based on client demand for each channel.

**Process Management Steps (Per Channel - Phase 8):**

1. **Track PID**: ChannelController must track Air's PID for its channel (if running)
2. **Launch process on-demand**: When a channel's `client_count` transitions from 0 → 1, ChannelController starts Retrovue Air process for that channel as a **child process** (on-demand invocation):
   - **Process model**: ChannelController MUST launch Retrovue Air as a child process
   - **Zero or one per channel**: Each channel has at most one running Air instance
   - **On-demand invocation**: Retrovue Air is created fresh each time that channel's `client_count` transitions 0 → 1
   - **CLI flags**: Launch with required flags: `--channel-id <id> --mode live --request-json-stdin`
   - **Working directory**: Implementation-specific (typically current directory or configured path)
   - **Environment variables**: Implementation-specific (may inherit parent environment or set specific vars)
   - **Logging approach**: Implementation-specific (may redirect stdout/stderr to files or log system)
3. **Send PlayoutRequest**: ChannelController writes exactly one PlayoutRequest as JSON to Retrovue Air's stdin
4. **Close stdin**: ChannelController MUST close stdin immediately after writing the complete JSON payload
5. **Serve transport stream**: ChannelManager serves MPEG-TS transport stream via an internal pipe from Air to HTTP endpoint (`/channel/<id>.ts`)
6. **Monitor client_count**: ChannelController continues monitoring its channel's `client_count` while Air is running (ChannelManager daemon continues running)
7. **Kill Air when unused**: When a channel's `client_count` drops to 0, ChannelController terminates and disposes of the Retrovue Air process for that channel

**Phase 8 Process Communication (Temporary Simplifications):**

- **No communication back from Air**: ChannelManager does NOT receive events or notifications from Air in Phase 8 (no "preview is ready", "asset taken live", "asset finished")
- **No persistent connection**: ChannelManager does NOT maintain a persistent connection to Air
- **One-way communication**: ChannelManager sends one PlayoutRequest via stdin, closes stdin, and serves the transport stream
- **No event handling**: ChannelManager does NOT interpret Air events like "preview is ready", "switch preview → live", "asset taken live", or "asset finished"
- **No preview/live switching**: ChannelManager does NOT send "switch preview → live" commands (Air's preview/live architecture exists but simplified for Phase 8 testing)

**Note:** Air's preview/live architecture exists and will be fully active in future phases. Phase 8 uses a simplified direct-playout mode for testing.

**Phase 8 Process Management Rules (Per Channel):**

- **Persistent daemon**: ChannelManager runs as a system-wide persistent daemon that never terminates automatically
- **One process per channel**: Each channel has zero or one running Retrovue Air instance at any time
- **On-demand Air**: Retrovue Air is disposable and invoked on-demand when a channel's `client_count > 0`
- **Launch condition**: ChannelController launches Retrovue Air for its channel **only** when that channel's `client_count` becomes >0 (on-demand)
- **Termination condition**: ChannelController terminates Retrovue Air for its channel **only** when:
  - That channel's `client_count` drops to 0 (kill Air when unused)
  - A fatal error occurs in Air for that channel (dispose of failed process)
- **Spawned by ChannelManager**: Air processes are spawned by ChannelManager's ChannelControllers
- **Killed when client_count hits 0**: Air process is terminated when the channel's `client_count` drops to 0
- **Child process**: ChannelController MUST launch Retrovue Air as a child process (not as a separate daemon)
- **Track PID**: ChannelController MUST track Air's PID for its channel (while Air is running)
- **Close stdin after writing**: ChannelController MUST close stdin immediately after writing the complete PlayoutRequest JSON
- **No long-lived pipes**: ChannelController MUST NOT keep a long-lived pipe open to Retrovue Air (except for transport stream serving)
- **No communication back from Air**: ChannelController does **NOT** receive events or notifications from Air in Phase 8
- **No schedule-based restarts**: ChannelController does **NOT** restart Air due to schedule changes in Phase 8
- **No timing monitoring**: ChannelController does **NOT** monitor Air for timing or transitions
- **Disposable Air lifecycle**: Each Retrovue Air process is fully disposable per channel; ChannelController recreates it on-demand as needed based on that channel's `client_count`

### Phase 9+ Schedule Change Handling

**Note:** The following capabilities are reserved for future phases (Phase 9–12) and are **NOT part of Phase 8**.

When schedule changes are detected (Phase 9+):

1. **Detect change**: Monitor schedule.json for updates or detect active ScheduleItem changes
2. **Evaluate restart need**: Determine if the change requires restarting Retrovue Air:
   - New active ScheduleItem with different asset path → restart required
   - Same ScheduleItem with updated metadata → restart may not be required (implementation-specific)
3. **Terminate current process**: Gracefully stop current Retrovue Air process (if running)
4. **Restart with new request**: Launch new Retrovue Air process with updated PlayoutRequest (only if `client_count > 0`)

**Phase 8 vs Future Phases:**

- **Phase 8**: Only manages Air lifecycle based on `client_count` (launch when 0 → 1, kill when hits 0). No schedule-change-based restarts.
- **Phase 9+**: Will add schedule-change-based restarts, event-driven transitions, and persistent Air connections.

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

- **Schedule must be sorted by `start_time_utc`** (or Channel Manager sorts): ScheduleItems must be ordered by their start times for efficient active item selection. Channel Manager may sort the schedule if it is not pre-sorted.
- **Missing fields cause a hard failure**: All required ScheduleItem fields must be present. Missing required fields must cause ChannelManager to fail hard and not start.
- **`asset_path` must exist on disk**: Channel Manager must verify that `asset_path` exists and is accessible before generating PlayoutRequests.
- **Channel Manager must not validate file length**: Channel Manager does not validate that the file duration matches `duration_seconds`; it only verifies the file exists.
- **All times are UTC (no timezone conversions)**: All `start_time_utc` fields are ISO-8601 UTC timestamps. Channel Manager MUST NOT attempt timezone conversions. It must parse and compare strictly in UTC without any DST (daylight saving time) logic or timezone conversions.

### Schedule Loading Behavior

- **File location**: Configuration-specific (e.g., `/var/retrovue/schedules/channel_retro1.json`)
- **Refresh frequency**: Phase 8 does not refresh schedules automatically. Schedule reload requires restarting ChannelManager.
- **Validation**: Must validate ScheduleItem structure and required fields before use
- **Error handling**: See Error Handling section below for explicit error behavior

### Error Handling

ChannelManager must handle errors according to these explicit rules:

#### Hard Errors (Fatal - Daemon May Exit)

These errors are fatal per channel and may cause ChannelManager daemon to exit. In Phase 8, most errors are handled gracefully per channel to keep the daemon running:

1. **schedule.json missing**: If a channel's schedule.json file does not exist at the expected path
   - **Behavior**: Log error per channel, daemon may exit (fatal startup error) OR retry periodically (implementation choice), OR disable that channel and continue (implementation choice)
2. **schedule.json invalid JSON**: If a channel's schedule.json file exists but cannot be parsed as valid JSON
   - **Behavior**: Log error per channel, daemon may exit (fatal startup error) OR retry periodically (implementation choice), OR disable that channel and continue (implementation choice)
3. **Required fields missing**: If any required ScheduleItem field is missing when attempting to launch Air for a channel:
   - **Behavior**: Log error per channel, ChannelController does not launch Retrovue Air for that channel, daemon continues running
   - Fields: `id`, `channel_id`, `program_type`, `title`, `asset_path`, `start_time_utc`, `duration_seconds`
4. **No schedule item matching current time**: (See Case 1 in "Handling Overlapping or Missing ScheduleItems" - treated as transient error per channel, daemon continues)
5. **asset_path does not exist**: If the `asset_path` for a channel's active ScheduleItem does not exist on disk or is not accessible when attempting to launch Air
   - **Behavior**: Log error per channel, ChannelController does not launch Retrovue Air for that channel, daemon continues running

**Hard Error Behavior (Daemon):**
- ChannelManager must log errors with sufficient detail for debugging, including which channel is affected
- For fatal startup errors (all channels' schedule.json missing/invalid): Daemon may exit with non-zero status OR retry periodically
- For per-channel errors (missing fields, missing asset, no active item): Daemon continues running, ChannelController does not launch Air for that channel, will retry when next client connects to that channel
- ChannelController must not launch Retrovue Air for a channel if validation fails, but ChannelManager daemon typically continues running for other channels

#### Soft Errors (Log + Continue)

These errors are logged per channel but do not prevent ChannelManager or ChannelControllers from operating:

1. **metadata missing**: If a ScheduleItem has no `metadata` field, ChannelController must treat it as an empty object `{}`
2. **Unknown metadata fields**: If metadata contains unknown keys, ChannelController must ignore them and pass metadata through unchanged

**Soft Error Behavior:**
- ChannelController must log a warning or info message per channel
- ChannelController must continue with default/fallback behavior for that channel
- ChannelController must proceed with PlayoutRequest generation for that channel

## Examples

### Example: ChannelManager Selecting Active ScheduleItem

**Current time**: `2025-11-07T18:15:00Z`

**ScheduleItems**:
1. `start_time_utc: 2025-11-07T18:00:00Z`, `duration_seconds: 1800` (ends at 18:30:00Z)
2. `start_time_utc: 2025-11-07T20:00:00Z`, `duration_seconds: 5400` (ends at 21:30:00Z)

**Result**: ScheduleItem #1 is active (current time falls within its duration window)

### Example: ChannelManager Generating PlayoutRequest

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

### Example: Retrovue Air Process Launch

**ChannelManager launches Retrovue Air**:
```bash
retrovue_air --channel retro1
```

**ChannelManager sends PlayoutRequest via stdin**:
```bash
echo '{"asset_path":"/mnt/media/tv/Cheers/Season2/Cheers_S02E05.mp4","start_pts":0,"mode":"LIVE","channel_id":"retro1","metadata":{"commType":"standard"}}' | retrovue_air --channel retro1
```

## Relationships

ChannelManager relates to:

- **ScheduleItem** (reads): ChannelControllers read [ScheduleItem](ScheduleItem.md) entries from schedule.json and select active items for their channels
- **PlayoutRequest** (generates): ChannelControllers generate [PlayoutRequest](PlayoutRequest.md) objects from ScheduleItems and send them to Retrovue Air processes
- **Channel** (manages): ChannelManager manages playout execution for all [Channel](Channel.md) instances via ChannelControllers
- **MasterClock** (queries): ChannelControllers use [MasterClock](MasterClock.md) to determine the current UTC time for ScheduleItem selection
- **Retrovue Air** (controls): ChannelControllers launch, monitor, and control Retrovue Air processes (zero or one per channel)

## Constraints

- **System-wide daemon**: ChannelManager is a single system-wide daemon that manages ALL channels in one process
- **Single HTTP server**: ChannelManager runs exactly one HTTP server serving `/channellist.m3u` and all `/channel/<id>.ts` endpoints (no per-channel HTTP servers)
- **Per-channel ChannelControllers**: Each channel has its own ChannelController instance within the single ChannelManager process (ChannelManager launches one runtime per channel, but still serves everything from one HTTP server)
- **Schedule-driven only**: ChannelManager only plays content that exists in schedule.json; it does not generate or modify schedules
- **Phase 8 timing rules**: ChannelManager always sets `start_pts=0` and `mode="LIVE"` when generating PlayoutRequests (Phase 8 requirements)
- **Metadata passthrough**: ChannelManager does not inspect or validate metadata; it passes it unchanged to Retrovue Air
- **System-wide persistent daemon**: ChannelManager is a system-wide persistent daemon process that never terminates automatically. It manages all channels and must remain running to track connected clients for all channels.
- **Global HTTP server**: ChannelManager runs a global HTTP server (typically port 9000) serving `/channel/<id>.ts` endpoints for all channels
- **ChannelRegistry**: ChannelManager contains a ChannelRegistry mapping channel IDs to ChannelController objects
- **ChannelController per channel**: Each channel has a ChannelController with: `client_count`, `schedule`, `active ScheduleItem`, `process handle for Air`, `state machine`, `per-channel timers` (Phase 9+), `metadata cache`, `stream endpoint`
- **On-demand Air per channel**: Retrovue Air is disposable and invoked on-demand per channel. Each channel has zero or one running Air instance, spawned by ChannelManager and killed when that channel's `client_count` hits 0.
- **Disposable Air lifecycle**: Each Retrovue Air process per channel is fully disposable and ephemeral; ChannelController recreates it on-demand as needed based on that channel's `client_count`.
- **Daemon vs processes**: ChannelManager (system-wide daemon) runs indefinitely; Retrovue Air processes (disposable, per-channel) are created and destroyed on-demand.

## Phase 8 Runtime Sequence Example

The following sequence demonstrates Phase 8 behavior:

```
Client connects to /channel/<id>.ts
    ↓
ChannelController increments refcount (client_count++) from 0 → 1
    ↓
[refcount transition: 0 → 1]
    ↓
ChannelController selects current ScheduleItem (based on current UTC time)
    ↓
ChannelController builds PlayoutRequest (one asset_path)
    ↓
ChannelController launches Air for that channel (on-demand, disposable)
    ↓
ChannelController sends PlayoutRequest via stdin and closes stdin
    ↓
Air begins playout immediately
    ↓
ChannelManager serves transport stream via internal pipe from Air → /channel/<id>.ts
    ↓
Client streams MPEG-TS from /channel/<id>.ts
    ↓
[... additional clients may connect/disconnect to/from this channel ...]
    [... refcount increments/decrements accordingly ...]
    ↓
Client disconnects (last client for that channel)
    ↓
ChannelController decrements refcount (client_count--) from 1 → 0
    ↓
[refcount hits 0]
    ↓
ChannelController terminates Air for that channel
    ↓
ChannelController waits idle for the next client (ChannelManager daemon continues running)
```

**Phase 8 Key Points:**
- **Refcount-driven**: Air launches when refcount goes 0 → 1, terminates when refcount hits 0
- **One request per launch**: ChannelController sends exactly one PlayoutRequest per Air launch
- **No communication back**: ChannelManager does NOT receive events from Air
- **Single file playout**: Air plays exactly one file until EOF or termination

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

**Important:** All advanced features (preview/live switching, event handling, schedule queries, orchestration, continuous playout) are reserved for future phases. Phase 8 focuses solely on: serving transport streams, maintaining client refcount, launching Air with single files, and killing Air when unused.

## Naming Rules

The canonical name for this concept in code and documentation is **ChannelManager**.

ChannelManager represents the system-wide runtime orchestrator that manages all channels — it bridges the gap between scheduled content (ScheduleItems) and playout execution (Retrovue Air) for all channels in the system.

## Operator Workflows

**Start ChannelManager**: Launch ChannelManager as a system-wide daemon. ChannelManager initializes its ChannelRegistry and starts the global HTTP server (port 9000). For each channel, ChannelManager creates a ChannelController that loads schedule.json and waits for clients to connect. When the first client connects to a channel's `/channel/<id>.ts` endpoint, that channel's ChannelController selects the active ScheduleItem and launches Retrovue Air for that channel.

**Monitor Active ScheduleItem**: View which ScheduleItem each ChannelController has selected as active for its channel at the current time. Verify that the selection logic matches expectations per channel.

**Inspect PlayoutRequests**: Review PlayoutRequests generated by each ChannelController to verify correct translation from ScheduleItems. Check that Phase 8 rules (`start_pts=0`, `mode="LIVE"`) are applied per channel.

**Manage Retrovue Air Processes**: Monitor Retrovue Air process status managed by each ChannelController. Verify that processes start correctly per channel and receive PlayoutRequests via stdin. Each channel has zero or one running Air instance at any time.

**Schedule Updates**: Update schedule.json files per channel and verify that ChannelControllers detect changes (Phase 9+). In Phase 8, schedule changes do not trigger Retrovue Air restarts; changes only take effect when Air is relaunched for that channel (when that channel's `client_count` transitions from 0 → 1).

**Debugging**: Use ChannelManager logs to diagnose schedule selection issues, PlayoutRequest generation problems, or Retrovue Air process management failures.

## See Also

- [ScheduleItem](ScheduleItem.md) - Schedule entries consumed by ChannelManager
- [PlayoutRequest](PlayoutRequest.md) - Playout instructions generated by ChannelManager
- [Channel](Channel.md) - Channel configuration managed by ChannelManager
- [MasterClock](MasterClock.md) - Time source used by ChannelManager for ScheduleItem selection
- [PlayoutPipeline](PlayoutPipeline.md) - Playout execution pipeline that includes ChannelManager
- [Runtime ChannelManager](../runtime/ChannelManager.md) - Runtime implementation details

