# Channel Manager Contract

## Purpose

Define the observable guarantees for the RetroVue Core runtime (channel manager) — a long-running process that serves MPEG-TS streams for all channels via HTTP. This contract specifies **what** the runtime guarantees, not how it is implemented internally.

**Process hierarchy:** ProgramDirector spawns a ChannelManager when one doesn't exist for the user's requested channel. ChannelManager **spawns Air** (playout engine) to play video. ChannelManager must **not** spawn ProgramDirector or the main retrovue process.

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

- `--schedule-dir` (optional, default: `/var/retrovue/schedules`): Directory containing per-channel `schedule.json` files.
- `--port` (optional, default: `9000`): HTTP server port.
- `--host` (optional, default: `0.0.0.0`): HTTP server bind address.
- `--json` (optional): Output startup status in JSON format.

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Started successfully (daemon continues running) |
| `1` | Fatal startup error (port unavailable, invalid config) |

---

## Startup Output

### Human-Readable

```
ChannelManager started:
  Host: 0.0.0.0
  Port: 9000
  Schedule directory: /var/retrovue/schedules
  Channels loaded: 2
    - retro1
    - retro2
```

### JSON

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

---

## HTTP API Contract

### GET /channellist.m3u

**Purpose:** Channel discovery playlist.

**Response:**
- Status: `200 OK`
- Content-Type: `application/vnd.apple.mpegurl`
- Body: M3U playlist listing all available channels

**Example:**
```
#EXTM3U
#EXTINF:-1,Retro1
http://localhost:9000/channel/retro1.ts
#EXTINF:-1,Retro2
http://localhost:9000/channel/retro2.ts
```

**Behavior:**
- Only channels with valid schedules are listed
- Channels with errors are excluded (no partial entries)

---

### GET /channel/{id}.ts

**Purpose:** MPEG-TS video stream for a channel.

**Response (success):**
- Status: `200 OK`
- Content-Type: `video/mp2t`
- Body: Continuous MPEG-TS stream

**Error responses:**

| Status | Condition |
|--------|-----------|
| `404` | Channel not found (no schedule file) |
| `500` | Schedule error (malformed JSON, invalid asset) |
| `503` | No active schedule item (schedule gap) |

---

## Behavioral Guarantees

### CM-010: Single Server

**Guarantee:** One HTTP server serves all channels.

**Observable behavior:**
- All channel endpoints share the same host:port
- `/channellist.m3u` lists all channels from one server

---

### CM-020: On-Demand Playout

**Guarantee:** Playout only runs when viewers are connected.

**Observable behavior:**
- First viewer connection to a channel starts playout
- Last viewer disconnection stops playout
- No playout resources consumed when no viewers connected

**Verification:** Connect to channel, observe stream; disconnect all clients, observe playout stops.

---

### CM-021: Shared Playout

**Guarantee:** Multiple viewers on the same channel share one playout instance.

**Observable behavior:**
- All viewers see the same stream (synchronized)
- Adding viewers does not restart playout
- Playout continues as long as at least one viewer is connected

---

### CM-030: Schedule-Based Content Selection

**Guarantee:** Active content is determined by schedule and current time.

**Observable behavior:**
- Content matches the ScheduleItem where `start_time_utc ≤ now < start_time_utc + duration_seconds`
- If multiple items overlap, earliest start time wins
- If no item is active, channel returns HTTP 503

**Verification:** Set up schedule with known times; connect at different times; observe correct content.

---

### CM-031: Asset Validation

**Guarantee:** Invalid assets are detected before playout starts.

**Observable behavior:**
- Missing asset file → HTTP 500, playout does not start
- Error message identifies the missing asset
- Other channels are unaffected

---

### CM-040: Channel Isolation

**Guarantee:** Per-channel errors do not affect other channels.

**Observable behavior:**
- Missing schedule for channel A → channel A returns 404
- Channel B with valid schedule continues working
- Runtime does not exit due to per-channel errors

---

### CM-041: Daemon Resilience

**Guarantee:** Runtime runs continuously until explicitly stopped.

**Observable behavior:**
- Runtime does not exit on per-channel errors
- Runtime exits only on fatal startup errors or SIGTERM/SIGINT
- Graceful shutdown terminates all playout and closes connections

---

### CM-042: Spawn Hierarchy

**Guarantee:** ProgramDirector spawns a ChannelManager when one doesn't exist for the requested channel. ChannelManager **spawns Air** (playout engine) to play video. ChannelManager must **not** spawn ProgramDirector or the main retrovue process.

**Observable behavior:**
- ChannelManager spawns and terminates Air processes for its channel(s); it owns Air lifecycle
- ChannelManager does not spawn ProgramDirector or the main `retrovue` process

---

## Schedule File Format

### CM-050: Schedule File Structure

**File location:** `{schedule_dir}/{channel_id}.json`

**Required structure:**
```json
{
  "channel_id": "retro1",
  "schedule": [
    {
      "id": "item-1",
      "channel_id": "retro1",
      "program_type": "movie",
      "title": "Example Movie",
      "asset_path": "/media/movies/example.mp4",
      "start_time_utc": "2025-01-01T00:00:00Z",
      "duration_seconds": 7200,
      "metadata": {}
    }
  ]
}
```

**Required ScheduleItem fields:**
- `id` — unique identifier
- `channel_id` — must match file's channel
- `program_type` — content type
- `title` — display name
- `asset_path` — path to media file
- `start_time_utc` — ISO 8601 UTC timestamp
- `duration_seconds` — length in seconds

---

### CM-051: Schedule Validation

**Guarantee:** Schedules are validated on load.

**Observable behavior:**
- Missing required fields → channel returns HTTP 500
- Invalid JSON → channel returns HTTP 500
- Error message identifies the validation failure
- Daemon continues running; only affected channel is unavailable

---

## Error Messages

### Fatal Startup Errors (Exit 1)

| Condition | Message |
|-----------|---------|
| Port in use | "Error: Port 9000 is already in use." |
| Cannot bind | "Error: Cannot bind to 0.0.0.0:9000." |
| Missing schedule dir | "Error: Schedule directory does not exist: {path}" |
| Invalid port | "Error: Invalid port number: {port}" |

### Per-Channel Errors (Daemon Continues)

| Condition | Log Message | HTTP Status |
|-----------|-------------|-------------|
| Missing schedule file | "Schedule file not found for channel {id}" | 404 |
| Malformed JSON | "Invalid JSON in schedule file for channel {id}" | 500 |
| No active item | "No active schedule item for channel {id}" | 503 |
| Missing asset | "Asset path does not exist for channel {id}: {path}" | 500 |
| Missing field | "Missing required field in schedule for channel {id}: {field}" | 500 |

---

## Phase 8 Scope

This contract covers Phase 8 (simplified playout). Future phases will add:

- Preview/live switching
- Bidirectional communication with playout engine
- Schedule change detection
- Continuous 24/7 operation
- Multi-asset sequencing

### Phase 8 Limitations

- Content selection occurs only when viewer connects (not continuously)
- No mid-stream content changes
- No communication back from playout engine
- Each schedule item is independent (no sequencing)

---

## Behavioral Rules Summary

| Rule | Guarantee |
|------|-----------|
| CM-010 | Single HTTP server for all channels |
| CM-020 | On-demand playout (starts with first viewer) |
| CM-021 | Shared playout for multiple viewers |
| CM-030 | Schedule-based content selection |
| CM-031 | Asset validation before playout |
| CM-040 | Channel isolation (errors don't spread) |
| CM-041 | Daemon resilience (runs until stopped) |
| CM-050 | Schedule file structure |
| CM-051 | Schedule validation on load |

---

## Test Coverage

| Rule | Test |
|------|------|
| CM-010 | `test_channel_manager_single_server` |
| CM-020, CM-021 | `test_channel_manager_viewer_lifecycle` |
| CM-030 | `test_channel_manager_schedule_selection` |
| CM-031 | `test_channel_manager_asset_validation` |
| CM-040 | `test_channel_manager_channel_isolation` |
| CM-041 | `test_channel_manager_resilience` |
| CM-050, CM-051 | `test_channel_manager_schedule_format` |

---

## See Also

- [ScheduleItem Domain](../../domain/ScheduleItem.md) — schedule item data model
- [Channel Domain](../../domain/Channel.md) — channel configuration
- [MasterClock Domain](../../domain/MasterClock.md) — time source
- [Contract Hygiene Checklist](../../../standards/contract-hygiene.md) — authoring guidelines
