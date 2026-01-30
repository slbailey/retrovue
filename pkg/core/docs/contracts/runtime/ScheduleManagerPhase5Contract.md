# ScheduleManager Phase 5 Contract: Runtime Integration

**Status:** Active
**Version:** 1.0
**Dependencies:** Phase 3, Phase 4

## Overview

Phase 5 wires Phase 3 ScheduleManager into the production runtime. When a channel
is configured with `schedule_source: "phase3"`, the runtime uses Phase3ScheduleService
to resolve schedules dynamically and provide EPG data.

**Goal:** `retrovue start` plays Cheers with correct EPG, no CLI flags needed.

## Scope

Phase 5 is **integration only**:
- No new scheduling features (Phase 3 is complete)
- No database persistence (in-memory stores are acceptable)
- No multi-channel orchestration (single channel demo)
- No ad insertion or traffic logic (future phase)

## Architecture

```
config/channels.json
    └─► schedule_source: "phase3"
            │
            └─► ProgramDirector._get_schedule_service_for_channel()
                    │
                    └─► Phase3ScheduleService
                            │
                            ├─► JsonFileProgramCatalog (config/programs/*.json)
                            ├─► InMemorySequenceStore
                            ├─► InMemoryResolvedStore
                            │
                            └─► Phase3ScheduleManager
                                    │
                                    ├─► get_program_at() → ProgramBlock → playout plan
                                    └─► get_epg_events() → EPG endpoint
```

## Invariants

### INV-P5-001: Config-Driven Activation

**Statement:** `schedule_source: "phase3"` in channel config enables Phase 3 mode.

**Rationale:** Allows gradual migration of channels to Phase 3 without affecting
channels using legacy schedule sources.

**Enforcement:**
- `ProgramDirector._get_schedule_service_for_channel()` checks `schedule_source`
- Returns `Phase3ScheduleService` for "phase3", default service otherwise

### INV-P5-002: Auto-Resolution

**Statement:** Programming day is resolved on first playout or EPG access.

**Rationale:** Lazily resolves schedules when needed, avoiding eager resolution
of days that may never be accessed.

**Enforcement:**
- `Phase3ScheduleService.get_playout_plan_now()` checks if day is resolved
- If not resolved, calls `Phase3ScheduleManager.resolve_schedule_day()`
- Same logic in `get_epg_events()` for EPG queries

### INV-P5-003: Playout Plan Transformation

**Statement:** ProgramBlock segments are correctly transformed to ChannelManager format.

**Rationale:** ChannelManager expects `list[dict]` with specific keys, while
Phase3ScheduleManager returns `ProgramBlock` with `PlayoutSegment` objects.

**Format:**
```python
{
    "asset_path": str,           # Path to media file
    "start_pts": int,            # Seek offset in milliseconds
    "duration_seconds": float,   # Segment duration
    "start_time_utc": str,       # ISO 8601 start time
    "end_time_utc": str,         # ISO 8601 end time
    "metadata": {
        "phase": "phase3",
        "grid_minutes": int,
    },
}
```

### INV-P5-004: EPG Endpoint Independence

**Statement:** EPG queries work without active viewers.

**Rationale:** EPG data must be available for program guides and external
integrations before any viewer tunes in.

**Enforcement:**
- `GET /api/epg/{channel_id}` endpoint exists independently of stream endpoints
- Auto-resolution triggers on EPG query if needed
- No dependency on `ChannelManager` or `Producer` state

## Data Structures

### Channel Config (channels.json)

```json
{
    "channel_id": "cheers-24-7",
    "channel_id_int": 2,
    "name": "Cheers 24/7",
    "schedule_source": "phase3",
    "schedule_config": {
        "grid_minutes": 30,
        "filler_path": "/opt/retrovue/assets/filler.mp4"
    }
}
```

### Schedule File (schedules/{channel_id}.json)

```json
{
    "slots": [
        {
            "slot_time": "06:00",
            "program_ref": {"type": "program", "id": "cheers"},
            "duration_seconds": 1800
        }
    ]
}
```

### Program File (programs/{program_id}.json)

```json
{
    "program_id": "cheers",
    "name": "Cheers",
    "play_mode": "sequential",
    "episodes": [
        {
            "episode_id": "cheers-s01e01",
            "title": "Give Me a Ring Sometime",
            "file_path": "/opt/retrovue/assets/...",
            "duration_seconds": 1501.653
        }
    ]
}
```

## API Endpoints

### GET /api/epg/{channel_id}

Returns EPG events for a channel.

**Query Parameters:**
- `start`: ISO 8601 start time (default: now)
- `end`: ISO 8601 end time (default: start + 24 hours)

**Response:**
```json
{
    "channel_id": "cheers-24-7",
    "start_time": "2025-01-30T06:00:00+00:00",
    "end_time": "2025-01-31T06:00:00+00:00",
    "events": [
        {
            "channel_id": "cheers-24-7",
            "start_time": "2025-01-30T06:00:00+00:00",
            "end_time": "2025-01-30T06:30:00+00:00",
            "title": "Cheers",
            "episode_title": "Give Me a Ring Sometime",
            "episode_id": "cheers-s01e01",
            "programming_day_date": "2025-01-30",
            "asset": {
                "file_path": "/opt/retrovue/assets/...",
                "asset_id": "cheers-s01e01",
                "duration_seconds": 1501.653
            }
        }
    ]
}
```

## Components

### Phase3ScheduleService

Adapter bridging Phase3ScheduleManager to ScheduleService protocol.

**Responsibilities:**
- Load schedule slots from JSON files
- Load programs from catalog directory
- Create and configure Phase3ScheduleManager
- Transform ProgramBlock to ChannelManager playout plan format
- Provide EPG events via get_epg_events()

**Dependencies:**
- JsonFileProgramCatalog
- InMemorySequenceStore
- InMemoryResolvedStore
- Phase3ScheduleManager

### JsonFileProgramCatalog

ProgramCatalog implementation loading from JSON files.

**File Format:** `{program_id}.json` in programs directory

### InMemorySequenceStore

In-memory SequenceStateStore for sequential program positions.

**Note:** Positions reset on process restart. Production should use persistent store.

### InMemoryResolvedStore

In-memory ResolvedScheduleStore for resolved schedule days.

**Note:** Lost on process restart. Production should use persistent store.

## Test Specifications

| ID | Test | Description |
|----|------|-------------|
| P5-T001 | Load Phase 3 schedule | Schedule loads successfully from JSON |
| P5-T002 | Playout plan format | Format matches ChannelManager expectations |
| P5-T003 | EPG endpoint format | Returns correct JSON structure |
| P5-T004 | Auto-resolution | First access triggers resolution |
| P5-T005 | Config activation | schedule_source selects correct service |
| P5-T006 | Episode identity | Playout episode matches EPG episode |
| P5-T007 | Seek offset | Mid-episode join has correct offset |

## Verification Procedure

```bash
# 1. Run contract tests
source pkg/core/.venv/bin/activate
pytest pkg/core/tests/contracts/test_schedule_manager_phase5_contract.py -v

# 2. Start server
retrovue start

# 3. Check channel discovery
curl http://localhost:8000/channels
# Should show cheers-24-7

# 4. Check EPG
curl "http://localhost:8000/api/epg/cheers-24-7"
# Should return EPG events with episode titles

# 5. Stream in VLC
vlc http://localhost:8000/channel/cheers-24-7.ts
# Should play correct episode with correct seek offset
```

## Litmus Test

1. Check EPG shows "Cheers S01E02" at 09:30
2. Tune in at 09:42
3. Verify playing S01E02, 12 minutes in (seek offset ~720 seconds)

## Relationship to Other Phases

- **Phase 3:** Provides core scheduling logic (two-pass model, episode selection)
- **Phase 4:** Validates Phase 3 with real durations (minimum grid occupancy)
- **Phase 5:** Wires Phase 3 into production runtime
- **Future:** Database persistence, multi-channel, ad insertion
