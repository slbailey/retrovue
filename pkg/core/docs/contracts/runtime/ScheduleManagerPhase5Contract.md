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

### Legacy / Shadow Mode

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
                            └─► ScheduleManager
                                    │
                                    ├─► get_program_at() → ProgramBlock → playout plan
                                    └─► get_epg_events() → EPG endpoint
```

### Authoritative Mode (INV-P5-005)

```
config/channels.json
    └─► schedule_source: "phase3"
            │
            ├─► ProgramDirector._init_horizon_managers()
            │       │
            │       ├─► Phase3ScheduleService (for adapters)
            │       ├─► ExecutionWindowStore (populated by HorizonManager)
            │       ├─► _Phase3ScheduleExtender → ScheduleExtender protocol
            │       ├─► _Phase3ExecutionExtender → ExecutionExtender protocol
            │       │
            │       └─► HorizonManager (background thread)
            │               ├─► evaluate_once() → readiness gate
            │               ├─► EPG extension → resolve_schedule_day()
            │               └─► Execution extension → ExecutionEntry generation
            │
            └─► ProgramDirector._get_schedule_service_for_channel()
                    │
                    └─► HorizonBackedScheduleService (read-only)
                            │
                            ├─► ExecutionWindowStore.get_entry_at(locked_only=True)
                            └─► ResolvedScheduleStore.get() → EPG
```

## Invariants

### INV-P5-001: Config-Driven Activation

**Statement:** `schedule_source: "phase3"` in channel config enables Phase 3 mode.

**Rationale:** Allows gradual migration of channels to Phase 3 without affecting
channels using legacy schedule sources.

**Enforcement:**
- `ProgramDirector._get_schedule_service_for_channel()` checks `schedule_source`
- Returns `Phase3ScheduleService` for "phase3", default service otherwise

### INV-P5-002: Auto-Resolution [DEPRECATED]

**Status:** DEPRECATED — retained for legacy mode only.

**Statement:** Programming day is resolved on first playout or EPG access.

**Rationale:** Lazily resolves schedules when needed, avoiding eager resolution
of days that may never be accessed.

**Deprecation Note:** Auto-resolution at consumption time directly contradicts
ScheduleHorizonManagementContract §5 ("No last-second horizon generation")
and ScheduleExecutionInterfaceContract §2 ("At no time does automation request
the creation of execution data").  In `shadow` and `authoritative` horizon
modes, auto-resolution is prohibited.  HorizonManager proactively extends
EPG and execution horizons ahead of wall-clock time.  See INV-P5-005.

**Active in:** `RETROVUE_HORIZON_AUTHORITY=legacy` only.

**Enforcement (legacy mode):**
- `Phase3ScheduleService.get_playout_plan_now()` checks if day is resolved
- If not resolved, calls `ScheduleManager.resolve_schedule_day()`
- Same logic in `get_epg_events()` for EPG queries
- In `authoritative` mode: raises `NoScheduleDataError` (planning failure)

### INV-P5-003: Playout Plan Transformation

**Statement:** ProgramBlock segments are correctly transformed to ChannelManager format.

**Rationale:** ChannelManager expects `list[dict]` with specific keys, while
ScheduleManager returns `ProgramBlock` with `PlayoutSegment` objects.

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

### INV-P5-005: Horizon Authority Guard

**Statement:** In `authoritative` horizon mode, consumers never trigger
planning.  All EPG resolution and execution data generation is driven
by HorizonManager ahead of wall-clock time.

**Rationale:** Enforces the separation between planning (proactive, ahead
of time) and execution (reactive, read-only).  Supersedes INV-P5-002
in non-legacy modes.  Aligns with:
- ScheduleHorizonManagementContract §5 (no last-second generation)
- ScheduleExecutionInterfaceContract §2 (automation never requests creation)
- ScheduleManagerPlanningAuthority §2 (all planning ahead of real time)

**Enforcement:**
- `Phase3ScheduleService`: In `authoritative` mode, `get_playout_plan_now()`
  and `get_epg_events()` raise `NoScheduleDataError` if data is missing.
  No silent empty returns. Missing data is an explicit planning failure.
- `HorizonBackedScheduleService`: Read-only consumer of
  `ExecutionWindowStore` (playout) and `ResolvedScheduleStore` (EPG).
  Never calls planning pipeline or schedule resolution.
- `ProgramDirector`: Routes Phase3 channels to `HorizonBackedScheduleService`
  in authoritative mode; `Phase3ScheduleService` in legacy/shadow modes.
- `ExecutionWindowStore.get_entry_at()`: Defaults to `locked_only=True`.
  Unlocked entries are invisible to consumers. POLICY_VIOLATION logged.
- `NoScheduleDataError`: Defined in `horizon_config.py`. Propagates
  as an unhandled exception — callers must not catch and regenerate.

**Mode matrix:**

| Mode | EPG Resolution | Execution Generation | Missing Data |
|------|---------------|---------------------|--------------|
| `legacy` | On-demand (INV-P5-002) | On-demand | Auto-resolve |
| `shadow` | HorizonManager + on-demand fallback | HorizonManager + on-demand fallback | Auto-resolve (logged) |
| `authoritative` | HorizonManager only | HorizonManager only | `NoScheduleDataError` raised |

**Configuration:** `RETROVUE_HORIZON_AUTHORITY={legacy,shadow,authoritative}`

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

Adapter bridging ScheduleManager to ScheduleService protocol.

**Responsibilities:**
- Load schedule slots from JSON files
- Load programs from catalog directory
- Create and configure ScheduleManager
- Transform ProgramBlock to ChannelManager playout plan format
- Provide EPG events via get_epg_events()

**Dependencies:**
- JsonFileProgramCatalog
- InMemorySequenceStore
- InMemoryResolvedStore
- ScheduleManager

### JsonFileProgramCatalog

ProgramCatalog implementation loading from JSON files.

**File Format:** `{program_id}.json` in programs directory

### InMemorySequenceStore

In-memory SequenceStateStore for sequential program positions.

**Note:** Positions reset on process restart. Production should use persistent store.

### InMemoryResolvedStore

In-memory ResolvedScheduleStore for resolved schedule days.

**Note:** Lost on process restart. Production should use persistent store.

### GET /debug/horizon/{channel_id}

Returns HorizonManager health report for a channel (shadow/authoritative only).

**Response:**
```json
{
    "channel_id": "cheers-24-7",
    "horizon_mode": "authoritative",
    "is_healthy": true,
    "epg_depth_hours": 72.5,
    "epg_compliant": true,
    "epg_farthest_date": "2025-02-14",
    "execution_depth_hours": 8.2,
    "execution_compliant": true,
    "execution_window_end_utc_ms": 1739520000000,
    "min_epg_days": 3,
    "min_execution_hours": 6,
    "evaluation_interval_seconds": 30,
    "last_evaluation_utc_ms": 1739491200000,
    "store_entry_count": 48
}
```

## Test Specifications

| ID | Test | Description |
|----|------|-------------|
| P5-T001 | Load Phase 3 schedule | Schedule loads successfully from JSON |
| P5-T002 | Playout plan format | Format matches ChannelManager expectations |
| P5-T003 | EPG endpoint format | Returns correct JSON structure |
| P5-T004 | Auto-resolution | First access triggers resolution (legacy only) |
| P5-T005 | Config activation | schedule_source selects correct service |
| P5-T006 | Episode identity | Playout episode matches EPG episode |
| P5-T007 | Seek offset | Mid-episode join has correct offset |
| P5-T008 | Authoritative no-resolve | authoritative mode raises `NoScheduleDataError` on unresolved access; zero resolve/pipeline calls from consumers |
| P5-T009 | Shadow health logging | shadow mode logs health report each evaluation |
| P5-T010 | Horizon readiness gate | evaluate_once() completes before HTTP server accepts requests |
| P5-T011 | Lock gate default | `get_entry_at()` defaults to `locked_only=True`; unlocked entries invisible to consumers |
| P5-T012 | Lock window enforcement | unlocked entry at query time returns None + POLICY_VIOLATION log |
| P5-T013 | Pipeline flag removed | `burn_in.py --pipeline` exits with error, `_RollingPipelineAdapter` deleted |
| P5-T014 | Horizon-only burn-in | `burn_in.py` serves multiple blocks using HorizonManager without any direct generate_day() calls |

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
