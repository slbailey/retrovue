# ScheduleManager Contract

**Status:** Active  
**Component:** Core Runtime (scheduling and playout plan generation)

---

## 1. Overview

ScheduleManager provides playout instructions to ChannelManager. It answers: "What should be playing right now, and what comes next?"

This contract defines the complete scheduling and runtime integration: grid-based scheduling, ScheduleDay resolution, dynamic content selection (programs, episodes), runtime integration with HorizonManager, and mid-segment seek offset calculation.

**Removed:** Per-segment LoadPreview/SwitchToLive orchestration, CT-domain switching, and playlist-driven execution are removed by [Phase8DecommissionContract](../../../../docs/contracts/architecture/Phase8DecommissionContract.md). The only valid runtime path is BlockPlan.

---

## 2. Scope

### Responsibilities

- Generating `ProgramBlock` objects on demand
- Deterministic calculation based on MasterClock-provided UTC time
- Grid-aligned scheduling (main show starts at grid boundaries)
- ScheduleDay resolution (day-specific schedules)
- Dynamic episode selection (sequential, random, manual)
- EPG generation and identity stability
- Playout plan transformation for ChannelManager
- Mid-segment seek offset calculation (join-in-progress)
- Filler placement (fills gap between program end and grid boundary)

### Not Responsible For

- Executing playout (ChannelManager does this)
- Asset file validation (assumes files exist)
- MasterClock ownership (uses MasterClock, doesn't own it)
- ffprobe at runtime (all metadata from static fixtures or Asset Library)

---

## 3. Architectural Constraints

### Time Source (CRITICAL)

All time calculations MUST be based on MasterClock-provided UTC time. No direct system clock access permitted.

```
INVARIANT: ScheduleManager receives time as a parameter, never fetches it.
```

### Horizon Authority

HorizonManager is the sole planning trigger. Consumers perform reads only. Missing data raises `HorizonNoScheduleDataError`. No consumer-triggered resolution. See [ScheduleHorizonManagementContract](../../../../docs/contracts/ScheduleHorizonManagementContract_v0.1.md).

### Boundary Rule (CRITICAL)

Grid boundaries belong to the block they START, not the block they end.

```
Time 9:30:00.000 belongs to the 9:30-10:00 block, NOT the 9:00-9:30 block.
get_program_at(9:29:59.999) → returns 9:00-9:30 block
get_program_at(9:30:00.000) → returns 9:30-10:00 block
```

---

## 4. Data Structures

### ScheduleSlot

A scheduled program slot within a ScheduleDay. References a Program or direct Asset.

```python
@dataclass
class ScheduleSlot:
    slot_time: time              # Grid-aligned time when this slot starts
    program_ref: ProgramRef      # Reference to Program, Asset, or direct file
    duration_seconds: float      # Duration of the slot
    label: str = ""
```

### ProgramRef

Reference to schedulable content: Program (series), Asset (specific movie), or FILE (literal path).

### ResolvedSlot / ResolvedAsset

A ScheduleSlot with content fully resolved during EPG generation. Immutable once published.

### ResolvedScheduleDay

A ScheduleDay with all content resolved to specific assets. Carries `resolved_slots` and `sequence_state`.

### ProgramBlock

One grid slot's worth of playout. Contains `block_start`, `block_end`, `segments` (PlayoutSegment list).

### PlayoutSegment

Single file to play with `start_utc`, `end_utc`, `file_path`, `seek_offset_seconds`, `duration_seconds`.

### EPGEvent

Viewer-facing EPG entry: `channel_id`, `start_time`, `end_time`, `title`, `episode_title`, `episode_id`, `resolved_asset`.

---

## 5. Interface

```python
def get_program_at(channel_id: str, at_time: datetime) -> ProgramBlock
def get_epg_events(channel_id: str, start: datetime, end: datetime) -> list[EPGEvent]
def resolve_schedule_day(channel_id: str, programming_day_date: date, slots: list, resolution_time: datetime) -> ResolvedScheduleDay
```

`ScheduleManagerBackedScheduleService` wraps ScheduleManager and provides `get_playout_plan_now()`, `get_epg_events()`, and `prime_schedule_day()` for HorizonManager adapters.

---

## 6. Invariants

### Grid and Scheduling

| ID | Statement |
|----|-----------|
| INV-SM-001 | Main show MUST start exactly at grid boundaries |
| INV-SM-002 | Same inputs MUST produce same outputs (deterministic) |
| INV-SM-003 | Every moment within a grid slot MUST be covered by exactly one segment |
| INV-SM-004 | Filler MUST be truncated at grid boundary |
| INV-SM-006 | Any wall-clock time within a grid slot MUST map to correct file + offset |
| INV-SM-007 | ScheduleManager MUST NOT access system time directly |

### ScheduleDay and Resolution

| ID | Statement |
|----|-----------|
| INV-P2-* | ScheduleDay resolution, day-specific scheduling |
| INV-P3-001 | Episode selection MUST be deterministic |
| INV-P3-002 | EPG identity MUST be immutable once published |
| INV-P3-005 | No playback-time content decisions |
| INV-P3-009 | Content duration from catalog, not inferred |

### Runtime Integration

| ID | Statement |
|----|-----------|
| INV-P5-001 | `schedule_source: "phase3"` in channel config enables dynamic schedule mode |
| INV-P5-003 | ProgramBlock segments correctly transformed to ChannelManager format (`asset_path`, `start_pts`, `duration_seconds`, etc.) |
| INV-P5-004 | EPG queries work without active viewers |
| INV-P5-005 | Horizon authority: consumers never trigger planning; missing data raises `HorizonNoScheduleDataError` |

### Mid-Segment Seek

| ID | Statement |
|----|-----------|
| INV-P6-001 | Core calculates `start_offset_ms` as elapsed time from segment start: `(now - segment.start_utc).total_seconds() * 1000 + segment.seek_offset_seconds * 1000` |
| INV-P6-002 | AIR seeks to nearest keyframe at or before target PTS |
| INV-P6-003 | At most one seek per viewer join |
| INV-P6-004 | Frame admission: frames with PTS < effective_seek_target decoded but not emitted |

---

## 7. Playout Plan Format

ChannelManager expects `list[dict]` per segment:

```python
{
    "asset_path": str,
    "start_pts": int,            # Seek offset in milliseconds
    "duration_seconds": float,
    "start_time_utc": str,       # ISO 8601
    "end_time_utc": str,         # ISO 8601
    "metadata": {"phase": "phase3", "grid_minutes": int},
}
```

---

## 8. Runtime Architecture

```
config/channels.json
    └─► schedule_source: "phase3"
            │
            ├─► ProgramDirector._init_horizon_managers()
            │       ├─► ScheduleManagerBackedScheduleService (for adapters)
            │       ├─► ExecutionWindowStore
            │       ├─► HorizonManager (background thread)
            │       │       ├─► EPG extension → resolve_schedule_day()
            │       │       └─► Execution extension → Planning pipeline
            │       └─► HorizonBackedScheduleService (read-only consumer)
            │
            └─► HorizonBackedScheduleService
                    ├─► ExecutionWindowStore.get_entry_at(locked_only=True)
                    └─► ResolvedScheduleStore.get() → EPG
```

---

## 9. Test Specifications

| ID | Description |
|----|-------------|
| SM-001 | Grid boundary alignment |
| SM-002 | Main show segment correctness |
| SM-003 | Filler segment correctness |
| SM-004 | Filler truncation at boundary |
| SM-005 | Jump-in mid-main-show |
| SM-006 | Jump-in mid-filler |
| SM-007 | Next program boundary semantics |
| SM-008 | Determinism |
| P5-T001 | Load schedule from JSON |
| P5-T002 | Playout plan format (required keys, start_pts ms, asset_path) |
| P5-T003 | EPG events structure |
| P5-T004 | No consumer resolution — raises when unresolved |
| P5-T005 | Config activation (schedule_source) |
| P5-T006 | Episode identity consistency |
| P5-T007 | Mid-episode seek offset |
| P6-T001 | Offset calculated from segment start |
| P6-T002 | Offset at segment start is zero |

---

## 10. Deprecated

The following behavior is removed by [Phase8DecommissionContract](../../../../docs/contracts/architecture/Phase8DecommissionContract.md):

- **Segment transitions** (LoadPreview/SwitchToLive, prebuffering ordering) — was ScheduleManagerPhase7Contract
- **Timeline Controller** (CT/MT mapping, segment mapping for preview/live) — was ScheduleManagerPhase8Contract

The only valid runtime path is BlockPlan. Core hands BlockPlans to AIR; AIR owns execution.

---

## 11. See Also

- [ScheduleHorizonManagementContract](../../../../docs/contracts/ScheduleHorizonManagementContract_v0.1.md)
- [Phase8DecommissionContract](../../../../docs/contracts/architecture/Phase8DecommissionContract.md)
- [PlayoutAuthorityContract](../PlayoutAuthorityContract.md)
- [INV-CANONICAL-BOOTSTRAP](INV-CANONICAL-BOOTSTRAP.md)
