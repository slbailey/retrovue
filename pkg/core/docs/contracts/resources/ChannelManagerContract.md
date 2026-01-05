# Channel Manager Contract

## Purpose

Define the behavioral contract for the ChannelManager daemon process (Phase 8). ChannelManager is a long-running system-wide daemon that manages ALL channels. It operates a single HTTP server serving channel discovery and MPEG-TS streams, manages client connections, selects active schedule items, and launches Retrovue Air processes on-demand.

---

## Command Shape

```
retrovue channel-manager start \
  [--schedule-dir <path>] \
  [--port <port>] \
  [--host <host>] \
  [--json]
```

### Parameters

- `--schedule-dir` (optional, default: `/var/retrovue/schedules`): Directory containing per-channel `schedule.json` files. Each channel has one file: `{channel_id}.json`.
- `--port` (optional, default: `9000`): HTTP server port for serving `/channellist.m3u` and `/channel/<id>.ts` endpoints.
- `--host` (optional, default: `0.0.0.0`): HTTP server bind address.
- `--json` (optional): Output startup status in JSON format (daemon continues running after startup).

---

## Safety Expectations

### Daemon Process Model

- ChannelManager runs as a persistent daemon process that never terminates automatically.
- Server MUST remain running even if individual channels have errors (missing schedules, no active items, etc.).
- ChannelManager exits ONLY on:
  - Fatal startup errors (cannot bind to port, invalid configuration)
  - External shutdown (SIGTERM, SIGINT, system-initiated termination)

### Process Isolation

- Air processes are spawned as child processes by ChannelManager.
- Air processes are mocked in tests (NOT launched in test environment).
- Each channel has at most one running Air instance at any time.

### Error Handling

- Per-channel errors (missing schedule, no active item, invalid asset) do NOT cause daemon exit.
- ChannelManager logs errors per channel and continues serving other channels.
- Missing or malformed `schedule.json` for a channel is logged but does not prevent other channels from operating.

### Test Database Behavior

- `--test-db` flag not applicable (ChannelManager is a runtime daemon, not a database operation).
- Tests MUST use isolated test schedule directories and mock Air processes.

---

## Output Format

### Startup (Human-Readable)

```
ChannelManager started:
  Host: 0.0.0.0
  Port: 9000
  Schedule directory: /var/retrovue/schedules
  Channels loaded: 2
    - retro1
    - retro2
```

### Startup (JSON)

```json
{
  "status": "ok",
  "host": "0.0.0.0",
  "port": 9000,
  "schedule_dir": "/var/retrovue/schedules",
  "channels_loaded": 2,
  "channels": ["retro1", "retro2"]
}
```

### Runtime

ChannelManager runs indefinitely. Logs are emitted to stdout/stderr for:
- Channel state changes (Air launch/termination)
- Schedule loading errors (per channel)
- Active item selection errors (per channel)
- Air process errors (per channel)

---

## Exit Codes

- `0`: ChannelManager started successfully (daemon continues running).
- `1`: Fatal startup error (cannot bind to port, invalid configuration, missing schedule directory).

---

## Behavior Contract Rules (B-#)

### HTTP Server (B-1 to B-4)

- **B-1:** ChannelManager MUST operate exactly one HTTP server serving ALL channels (no per-channel servers).
- **B-2:** ChannelManager MUST serve `/channellist.m3u` for channel discovery (M3U playlist format).
- **B-3:** ChannelManager MUST serve `/channel/<id>.ts` endpoints for MPEG-TS streams (one endpoint per channel).
- **B-4:** HTTP server MUST bind to the specified `--host` and `--port` (default: `0.0.0.0:9000`).

### Schedule Loading (B-5 to B-9)

- **B-5:** ChannelManager MUST load `schedule.json` files from `--schedule-dir` (one file per channel: `{channel_id}.json`).
- **B-6:** Schedule files MUST be valid JSON with `channel_id` and `schedule` array.
- **B-7:** Missing `schedule.json` for a channel MUST be logged as error per channel (daemon continues, channel unavailable).
- **B-8:** Malformed `schedule.json` for a channel MUST be logged as error per channel (daemon continues, channel unavailable).
- **B-9:** Schedule loading errors MUST NOT cause daemon exit (other channels continue operating).

### Active Item Selection (B-10 to B-14)

- **B-10:** ChannelManager MUST select active ScheduleItem based on current UTC time: `start_time_utc ≤ now < start_time_utc + duration_seconds`.
- **B-11:** If multiple items are active (overlapping), ChannelManager MUST select the one with earliest `start_time_utc`.
- **B-12:** If no item is active (schedule gap), ChannelManager MUST log error per channel and NOT launch Air.
- **B-13:** Active item selection occurs ONLY when launching Air (when `client_count` transitions 0 → 1).
- **B-14:** Once Air is running, ChannelManager does NOT change content for that channel until Phase 9.

### Client Connection Tracking (B-15 to B-19)

- **B-15:** Each ChannelController MUST track `client_count` (refcount) for its channel (increment on connect, decrement on disconnect).
- **B-16:** When `client_count` transitions 0 → 1, ChannelController MUST launch Air and send PlayoutRequest.
- **B-17:** When `client_count` drops to 0, ChannelController MUST terminate Air immediately.
- **B-18:** Multiple clients connecting to same channel MUST share one Air instance (`client_count` tracks total connections).
- **B-19:** Each channel MUST have at most one running Air instance at any time.

### PlayoutRequest Generation (B-20 to B-25)

- **B-20:** ChannelManager MUST map ScheduleItem → PlayoutRequest correctly:
  - `asset_path` → `asset_path` (direct copy)
  - `start_pts` = `0` (always in Phase 8)
  - `mode` = `"LIVE"` (always in Phase 8, uppercase)
  - `channel_id` → `channel_id` (direct copy)
  - `metadata` → `metadata` (unchanged, opaque passthrough)
- **B-21:** PlayoutRequest MUST be sent to Air via stdin as JSON-encoded data.
- **B-22:** ChannelManager MUST close stdin immediately after writing complete PlayoutRequest JSON.
- **B-23:** ChannelManager MUST validate `asset_path` exists before launching Air (hard error if missing).
- **B-24:** Required ScheduleItem fields MUST be validated: `id`, `channel_id`, `program_type`, `title`, `asset_path`, `start_time_utc`, `duration_seconds`.
- **B-25:** Missing required fields MUST cause error per channel (Air not launched, daemon continues).

### Air Process Management (B-26 to B-30)

- **B-26:** ChannelManager MUST launch Air as child process with CLI flags: `--channel-id <id> --mode live --request-json-stdin`.
- **B-27:** ChannelManager MUST track Air PID per channel while Air is running.
- **B-28:** ChannelManager MUST terminate Air when `client_count` drops to 0 (dispose of on-demand process).
- **B-29:** ChannelManager MUST NOT launch Air if no active ScheduleItem (per B-12).
- **B-30:** ChannelManager MUST NOT launch Air if `asset_path` does not exist (per B-23).

### Error Handling (B-31 to B-35)

- **B-31:** Missing `schedule.json` for a channel MUST be logged and channel marked unavailable (HTTP 503 or 404 for that channel).
- **B-32:** Malformed `schedule.json` for a channel MUST be logged and channel marked unavailable (HTTP 500 for that channel).
- **B-33:** No active ScheduleItem (schedule gap) MUST be logged per channel and NOT launch Air (HTTP 503 for that channel).
- **B-34:** Invalid `asset_path` MUST be logged per channel and NOT launch Air (HTTP 500 for that channel).
- **B-35:** Per-channel errors MUST NOT cause daemon exit (daemon continues serving other channels).

### Daemon Lifecycle (B-36 to B-38)

- **B-36:** ChannelManager MUST run indefinitely (never terminates automatically).
- **B-37:** ChannelManager MUST exit only on fatal startup errors (cannot bind to port) or external shutdown.
- **B-38:** ChannelManager MUST handle SIGTERM/SIGINT gracefully (terminate all Air processes, close HTTP server, exit cleanly).

---

## Data Contract Rules (D-#)

### Schedule Data (D-1 to D-5)

- **D-1:** Schedule files MUST be valid JSON with structure: `{"channel_id": "<id>", "schedule": [ScheduleItem, ...]}`.
- **D-2:** ScheduleItem fields MUST match ScheduleItem domain model (see [ScheduleItem](../../domain/ScheduleItem.md)).
- **D-3:** All times MUST be UTC (ISO 8601 with Z suffix).
- **D-4:** Schedule files MUST NOT be modified by ChannelManager (read-only).
- **D-5:** Schedule validation MUST occur on load (invalid schedules prevent channel operation, but daemon continues).

### Process State (D-6 to D-10)

- **D-6:** ChannelManager MUST track Air PID per channel while Air is running.
- **D-7:** ChannelManager MUST maintain `client_count` per channel (in-memory state, not persisted).
- **D-8:** ChannelManager MUST maintain ChannelRegistry mapping channel IDs to ChannelController instances.
- **D-9:** Air process state (PID, launch time) MUST be tracked per channel (in-memory state, not persisted).
- **D-10:** No persistent state changes occur (ChannelManager is a runtime daemon, not a database operation).

---

## HTTP Endpoints

### GET /channellist.m3u

**Purpose:** Channel discovery playlist.

**Response:**
- Content-Type: `application/vnd.apple.mpegurl`
- Body: M3U playlist containing all available channels.

**Example:**
```
#EXTM3U
#EXTINF:-1,Retro1
http://localhost:9000/channel/retro1.ts
#EXTINF:-1,Retro2
http://localhost:9000/channel/retro2.ts
```

**Error Handling:**
- Returns 200 with available channels only (missing/malformed schedules excluded from playlist).

### GET /channel/<id>.ts

**Purpose:** MPEG-TS transport stream for a channel.

**Response:**
- Content-Type: `video/mp2t` or `application/vnd.apple.mpegurl`
- Body: MPEG-TS stream (piped from Air process).

**Behavior:**
1. Client connects → `client_count++` for that channel.
2. If `client_count` transitions 0 → 1:
   - Select active ScheduleItem.
   - Launch Air process.
   - Send PlayoutRequest via stdin.
3. Serve MPEG-TS stream from Air → client.
4. When client disconnects → `client_count--`.
5. If `client_count` drops to 0 → terminate Air.

**Error Handling:**
- 404: Channel not found (no schedule.json).
- 500: Schedule error (malformed JSON, missing active item, invalid asset).
- 503: Channel unavailable (no active schedule item, schedule gap).

---

## Test Coverage Mapping

Planned tests:

- `tests/contracts/test_channel_manager_contract.py::test_channel_manager_help_flag_exits_zero`
- `tests/contracts/test_channel_manager_contract.py::test_channel_manager_channellist_m3u_endpoint`
- `tests/contracts/test_channel_manager_contract.py::test_channel_manager_channel_ts_endpoint_exists`
- `tests/contracts/test_channel_manager_contract.py::test_channel_manager_client_refcount_spawns_air`
- `tests/contracts/test_channel_manager_contract.py::test_channel_manager_client_refcount_kills_air`
- `tests/contracts/test_channel_manager_contract.py::test_channel_manager_active_item_selection`
- `tests/contracts/test_channel_manager_contract.py::test_channel_manager_overlapping_items_selects_earliest`
- `tests/contracts/test_channel_manager_contract.py::test_channel_manager_playout_request_mapping`
- `tests/contracts/test_channel_manager_contract.py::test_channel_manager_playout_request_sent_via_stdin`
- `tests/contracts/test_channel_manager_contract.py::test_channel_manager_air_lifecycle_single_instance`
- `tests/contracts/test_channel_manager_contract.py::test_channel_manager_missing_schedule_json_error`
- `tests/contracts/test_channel_manager_contract.py::test_channel_manager_malformed_schedule_json_error`
- `tests/contracts/test_channel_manager_contract.py::test_channel_manager_no_active_item_error`

---

## Error Conditions

### Fatal Startup Errors (Exit Code 1)

- **Port already in use:** "Error: Port 9000 is already in use."
- **Cannot bind to host/port:** "Error: Cannot bind to 0.0.0.0:9000."
- **Invalid schedule directory:** "Error: Schedule directory does not exist: <path>."
- **Invalid port number:** "Error: Invalid port number: <port>."

### Per-Channel Errors (Daemon Continues)

- **Missing schedule.json:** Log: "Error: Schedule file not found for channel <id>: <path>", HTTP 404 for that channel.
- **Malformed schedule.json:** Log: "Error: Invalid JSON in schedule file for channel <id>: <path>", HTTP 500 for that channel.
- **No active ScheduleItem:** Log: "Error: No active schedule item for channel <id>", HTTP 503 for that channel.
- **Invalid asset_path:** Log: "Error: Asset path does not exist for channel <id>: <path>", HTTP 500 for that channel.
- **Missing required fields:** Log: "Error: Missing required field in schedule for channel <id>: <field>", HTTP 500 for that channel.

---

## Phase 8 Limitations

**NOTE: Phase 8 implements a simplified one-file playout pipeline for testing. Future phases add PREVIEW/LIVE buffers, continuous playout, signaling, and scheduling logic.**

### What Phase 8 Does

- Operates one HTTP server serving all channels.
- Tracks client connections per channel (refcount).
- Loads schedule.json files per channel.
- Selects active ScheduleItem based on current time.
- Launches Air on-demand (when `client_count` > 0).
- Terminates Air when unused (`client_count` = 0).
- Maps ScheduleItem → PlayoutRequest correctly.

### What Phase 8 Does NOT Do

- **No preview/live switching:** Air's preview/live architecture exists but is not actively used (simplified for testing).
- **No communication back from Air:** ChannelManager does NOT receive events from Air (no "preview is ready", "asset taken live", "asset finished").
- **No schedule change handling:** Schedule changes do NOT trigger Air restarts (changes only take effect on next Air launch).
- **No continuous playout:** Each ScheduleItem is independent; no sequencing across items.
- **No 24×7 operation:** Air runs only when clients are connected (disposable, on-demand).

---

## See Also

- [ChannelManager Domain](../../domain/ChannelManager.md) - Core domain model and architecture
- [ScheduleItem Domain](../../domain/ScheduleItem.md) - Schedule item data model
- [PlayoutRequest Domain](../../domain/PlayoutRequest.md) - Playout request format
- [Channel Domain](../../domain/Channel.md) - Channel configuration
- [MasterClock Domain](../../domain/MasterClock.md) - Time source for schedule selection
- [CLI Contract](README.md) - General CLI command standards
