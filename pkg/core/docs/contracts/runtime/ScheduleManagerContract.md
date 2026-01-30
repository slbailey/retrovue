# Schedule Manager Contract

Status: Design (pre-implementation)

## Purpose

ScheduleManager provides playout instructions to ChannelManager. It answers the question: "What should be playing right now, and what comes next?"

This contract defines the **Phase 0 implementation**: a deterministic grid-based schedule using a single main-show asset and a filler asset. This proves the core loop (get program → play program → get next program) before adding EPG complexity.

---

## Scope

ScheduleManager is responsible for:
- Generating `ProgramBlock` objects on demand
- Deterministic calculation based on MasterClock-provided UTC time
- Grid-aligned scheduling (main show starts at grid boundaries)
- Filler placement (fills gap between main show end and next grid boundary)

ScheduleManager is NOT responsible for:
- Executing playout (ChannelManager does this)
- Managing multiple shows/EPG (future phases)
- Asset file validation (assumes files exist)
- MasterClock ownership (uses MasterClock, doesn't own it)

---

## Architectural Constraints

### Time Source (CRITICAL)

All time calculations MUST be based on MasterClock-provided UTC time. No direct system clock access (`datetime.now()`, `time.time()`, etc.) is permitted in ScheduleManager or any code that calls it.

```
INVARIANT: ScheduleManager receives time as a parameter, never fetches it.
```

This ensures deterministic behavior and testability.

### Channel Configuration Immutability

ScheduleManager MUST treat channel configuration as immutable for the duration of a ProgramBlock. If configuration changes mid-block, behavior is undefined.

```
INVARIANT: Configuration is read once per get_program_at() / get_next_program() call.
           The returned ProgramBlock reflects that configuration snapshot.
```

Different channels MAY have different grid sizes and configurations.

---

## Data Structures

### PlayoutSegment

A single file to play with timing information.

A PlayoutSegment represents a time-bounded playback instruction. In later phases, segments may reference partial assets, concatenations, or synthesized outputs.

```python
@dataclass
class PlayoutSegment:
    start_utc: datetime       # When this segment starts (wall clock)
    end_utc: datetime         # When this segment ends (wall clock)
    file_path: str            # Path to the media file
    seek_offset_seconds: float = 0.0  # Where to start in the file
```

### ProgramBlock (Phase 0 Only)

> **NOTE:** `ProgramBlock` is a Phase 0 abstraction representing one grid slot's worth of playout. In later phases, this type may be replaced or wrapped by continuous playlog segments that are not grid-bounded. Do not build dependencies on grid-bounded semantics beyond Phase 0.

A complete program unit bounded by grid boundaries.

```python
@dataclass
class ProgramBlock:
    block_start: datetime     # Grid boundary start (e.g., 9:00:00)
    block_end: datetime       # Grid boundary end (e.g., 9:30:00)
    segments: list[PlayoutSegment]  # Ordered list of segments
```

### Terminology Note

`ProgramBlock` refers to "one grid slot's worth of playout" — not to be confused with `Program` (the domain entity representing a show, episode, or asset chain). This naming collision is acknowledged and acceptable for Phase 0. Later phases may rename this type.

---

## Interface

```python
class ScheduleManager(Protocol):
    def get_program_at(self, channel_id: str, at_time: datetime) -> ProgramBlock:
        """
        Get the program block containing the specified time.

        Args:
            channel_id: The channel identifier
            at_time: The MasterClock-provided UTC time to query

        Returns:
            ProgramBlock where: block_start <= at_time < block_end

        Raises:
            ScheduleError: If no schedule is configured for the channel
        """
        ...

    def get_next_program(self, channel_id: str, after_time: datetime) -> ProgramBlock:
        """
        Get the next program block after the specified time.

        Boundary behavior:
            - after_time is treated as EXCLUSIVE
            - If after_time falls exactly on a grid boundary, that boundary's
              block is returned (the boundary belongs to the NEW block)
            - If after_time is mid-block, the next grid boundary's block is returned

        Examples:
            after_time = 9:28:00  → returns 9:30-10:00 block
            after_time = 9:30:00  → returns 9:30-10:00 block (boundary belongs to new block)
            after_time = 9:30:01  → returns 10:00-10:30 block

        Args:
            channel_id: The channel identifier
            after_time: The MasterClock-provided UTC time; returns block starting at or after this

        Returns:
            The next ProgramBlock where: block_start >= after_time
            AND block_start is the nearest grid boundary >= after_time

        Raises:
            ScheduleError: If no schedule is configured for the channel
        """
        ...
```

### Boundary Rule (CRITICAL)

Grid boundaries belong to the block they START, not the block they end.

```
Time 9:30:00.000 belongs to the 9:30-10:00 block, NOT the 9:00-9:30 block.

get_program_at(9:29:59.999) → returns 9:00-9:30 block
get_program_at(9:30:00.000) → returns 9:30-10:00 block

get_next_program(9:29:59.999) → returns 9:30-10:00 block
get_next_program(9:30:00.000) → returns 9:30-10:00 block (boundary case)
get_next_program(9:30:00.001) → returns 10:00-10:30 block
```

This eliminates off-by-one ambiguity at block transitions.

---

## Phase 0 Behavior: Grid-Based Main Show + Filler

### Configuration

Phase 0 uses a simple configuration per channel:

```python
@dataclass
class SimpleGridConfig:
    grid_minutes: int              # Grid slot duration (e.g., 30)
    main_show_path: str            # Path to main show file
    main_show_duration_seconds: float  # Duration of main show
    filler_path: str               # Path to filler file
    filler_duration_seconds: float # Duration of filler (must be >= grid - main)
    programming_day_start_hour: int = 6  # Broadcast day start (default 6 AM)
```

### Schedule Pattern

Each grid slot follows this pattern:

```
Grid boundary                              Next grid boundary
     │                                              │
     ▼                                              ▼
     ├──────── Main Show ────────┼──── Filler ─────┤
     │      (full duration)      │  (truncated)    │
     │                           │                 │
   0:00                    main_show_end     grid_minutes
```

- Main show always starts at offset 0:00 within the grid slot
- Main show plays its full duration
- Filler starts immediately after main show ends
- Filler is truncated at the next grid boundary (hard cut)

### Hard Cut Semantics (Phase 0 Only)

> **NOTE:** Hard cut at grid boundary is Phase 0 behavior. Later phases may introduce soft transitions, ad pods that align but don't hard-cut, or bumpers that intentionally overlap. This contract does not preclude those extensions.

### Example

With `grid_minutes=30`, `main_show_duration=22 minutes`:

| Time | Content | File Offset |
|------|---------|-------------|
| 9:00:00 | Main show starts | 0:00 |
| 9:22:00 | Main show ends, filler starts | 0:00 |
| 9:30:00 | **Hard cut** - filler stops, main show starts | 0:00 |
| 9:52:00 | Main show ends, filler starts | 0:00 |
| 10:00:00 | **Hard cut** - filler stops, main show starts | 0:00 |

---

## Invariants

### INV-SM-001: Grid Alignment

Main show MUST start exactly at grid boundaries. No exceptions.

```
GIVEN a ProgramBlock
THEN block_start MUST be aligned to grid boundary
AND the first segment MUST start at block_start
```

### INV-SM-002: Deterministic Calculation

The same inputs MUST produce the same outputs. No randomness, no state.

```
GIVEN channel_id, at_time, and configuration
WHEN get_program_at() is called multiple times
THEN the result MUST be identical each time
```

### INV-SM-003: Complete Coverage

Every moment within a grid slot MUST be covered by exactly one segment.

```
GIVEN a ProgramBlock
THEN segments MUST cover [block_start, block_end) completely
AND segments MUST NOT overlap
AND there MUST be no gaps
```

### INV-SM-004: Hard Cut at Grid Boundary (Phase 0)

Filler MUST be truncated at grid boundary. Never bleeds into next slot.

```
GIVEN a ProgramBlock with filler segment
THEN filler.end_utc MUST equal block_end exactly
AND filler duration MAY be less than filler file duration
```

### INV-SM-005: Main Show Never Truncated

Main show always plays full duration. Filler absorbs timing variance.

```
GIVEN a ProgramBlock
THEN main_show segment duration MUST equal main_show_duration_seconds
AND main_show MUST NOT be truncated
```

### INV-SM-006: Jump-In Anywhere

Any wall-clock time within a grid slot MUST map to correct file + offset.

```
GIVEN any at_time within a grid slot
WHEN get_program_at() is called
THEN the returned ProgramBlock MUST contain a segment covering at_time
AND the segment's seek_offset + (at_time - segment.start_utc) gives correct file position
```

### INV-SM-007: No System Clock Access

ScheduleManager MUST NOT access system time directly.

```
GIVEN any call to get_program_at() or get_next_program()
THEN all time values MUST come from the at_time / after_time parameter
AND no calls to datetime.now(), time.time(), or similar are permitted
```

### INV-SM-008: Configuration Snapshot Consistency

A returned ProgramBlock MUST be internally consistent with a single configuration snapshot.

```
GIVEN a ProgramBlock returned by get_program_at()
THEN all segments within that block MUST reflect the same grid_minutes,
     main_show_duration_seconds, and other configuration values
```

---

## Behavior Rules

### B-SM-001: Program Block Contains Query Time

```
GIVEN get_program_at(channel_id, at_time)
THEN returned ProgramBlock MUST satisfy:
  block_start <= at_time < block_end
```

### B-SM-002: Next Program Boundary Semantics

```
GIVEN get_next_program(channel_id, after_time)
THEN returned ProgramBlock MUST satisfy:
  block_start >= after_time
AND block_start is the nearest grid boundary >= after_time

Specifically:
  - If after_time is exactly on a grid boundary, return that boundary's block
  - If after_time is between boundaries, return the next boundary's block
```

### B-SM-003: Segments Are Contiguous

```
GIVEN a ProgramBlock with segments [s1, s2, ...]
THEN s1.start_utc == block_start
AND s1.end_utc == s2.start_utc (if s2 exists)
AND last_segment.end_utc == block_end
```

### B-SM-004: Seek Offset Calculation

For any time T within a segment:

```
file_position = segment.seek_offset_seconds + (T - segment.start_utc).total_seconds()
```

### B-SM-005: Programming Day Boundary

Grid slots are calculated relative to programming day start, not midnight.

```
GIVEN programming_day_start_hour = 6
THEN grid boundaries are: 6:00, 6:30, 7:00, ..., 5:30 (next day)
```

---

## Test Specifications

### Test SM-001: Grid Boundary Alignment

```
GIVEN SimpleGridConfig(grid_minutes=30, main_show_duration=1320)
AND current time is 9:17:23
WHEN get_program_at() is called
THEN block_start == 9:00:00
AND block_end == 9:30:00
```

### Test SM-002: Main Show Segment

```
GIVEN SimpleGridConfig(grid_minutes=30, main_show_duration=1320)
AND current time is 9:10:00
WHEN get_program_at() is called
THEN segments[0].file_path == main_show_path
AND segments[0].start_utc == 9:00:00
AND segments[0].end_utc == 9:22:00
AND segments[0].seek_offset_seconds == 0
```

### Test SM-003: Filler Segment

```
GIVEN SimpleGridConfig(grid_minutes=30, main_show_duration=1320)
AND current time is 9:25:00
WHEN get_program_at() is called
THEN segments[1].file_path == filler_path
AND segments[1].start_utc == 9:22:00
AND segments[1].end_utc == 9:30:00  # Hard cut at grid boundary
AND segments[1].seek_offset_seconds == 0
```

### Test SM-004: Filler Truncation

```
GIVEN SimpleGridConfig(grid_minutes=30, main_show_duration=1320)
# Filler file is 60 minutes but only 8 minutes are used
WHEN get_program_at() is called for 9:00-9:30 slot
THEN filler segment duration == 480 seconds (8 minutes)
NOT filler_duration_seconds (60 minutes)
```

### Test SM-005: Jump-In Mid-Main-Show

```
GIVEN SimpleGridConfig as above
AND viewer joins at 9:15:30
WHEN get_program_at(at_time=9:15:30) is called
THEN returned block contains main show segment
AND to play from correct position:
    file_position = 0 + (9:15:30 - 9:00:00) = 930 seconds
```

### Test SM-006: Jump-In Mid-Filler

```
GIVEN SimpleGridConfig as above
AND viewer joins at 9:26:00
WHEN get_program_at(at_time=9:26:00) is called
THEN returned block contains filler segment
AND to play from correct position:
    file_position = 0 + (9:26:00 - 9:22:00) = 240 seconds
```

### Test SM-007: Next Program Mid-Block

```
GIVEN current time is 9:28:00
WHEN get_next_program(after_time=9:28:00) is called
THEN block_start == 9:30:00
AND block_end == 10:00:00
```

### Test SM-007b: Next Program At Exact Boundary

```
GIVEN after_time is exactly 9:30:00 (a grid boundary)
WHEN get_next_program(after_time=9:30:00) is called
THEN block_start == 9:30:00  # Boundary belongs to new block
AND block_end == 10:00:00
```

### Test SM-007c: Next Program Just After Boundary

```
GIVEN after_time is 9:30:00.001 (just after boundary)
WHEN get_next_program(after_time=9:30:00.001) is called
THEN block_start == 10:00:00  # Next boundary
AND block_end == 10:30:00
```

### Test SM-008: Determinism

```
GIVEN fixed configuration and time
WHEN get_program_at() is called 100 times
THEN all 100 results MUST be identical
```

### Test SM-009: Day Boundary Handling

```
GIVEN programming_day_start_hour=6
AND current time is 5:45:00 AM (within previous programming day)
WHEN get_program_at() is called
THEN block is within the previous programming day's schedule
AND block_start aligns to grid from previous day's 6:00 AM
```

### Test SM-010: Full 24-Hour Loop

```
GIVEN SimpleGridConfig(grid_minutes=30, ...)
WHEN get_program_at() is called for every minute of 24 hours
THEN every call returns a valid ProgramBlock
AND no gaps exist
AND no overlaps exist
```

---

## Integration with ChannelManager

ChannelManager uses ScheduleManager as follows:

1. **On viewer join:**
   ```python
   now = master_clock.now_utc()  # Always from MasterClock
   block = schedule_manager.get_program_at(channel_id, now)
   segment = find_segment_containing(block, now)
   offset = calculate_offset(segment, now)
   air.play(segment.file_path, offset)
   ```

2. **On segment end:**
   ```python
   next_segment = get_next_segment_in_block(block, current_segment)
   if next_segment:
       air.play(next_segment.file_path, next_segment.seek_offset_seconds)
   else:
       # Block ended, get next block
       now = master_clock.now_utc()
       next_block = schedule_manager.get_next_program(channel_id, now)
       air.play(next_block.segments[0].file_path, 0)
   ```

3. **Proactive lookahead:**
   ```python
   # Near end of current block, pre-fetch next
   if approaching_block_end(block, now, threshold=30_seconds):
       next_block = schedule_manager.get_next_program(channel_id, block.block_end)
       # Cache for instant switch
   ```

---

## Future Phases

### Phase 1: Multiple Shows

Replace single main_show with a list of shows and their time slots.

### Phase 2: EPG Integration

Generate playout segments from ScheduleDay entities. `ProgramBlock` may be replaced or wrapped by continuous playlog segments.

### Phase 3: Dynamic Content Selection

Support Programs with asset_chain and play_mode for episode selection.

### Phase N: Transition Flexibility

Relax hard-cut semantics to support soft transitions, overlapping bumpers, and ad pods.

---

## Glossary

Terms used in this contract and their alignment with the broader RetroVue system:

| Term | Definition (this contract) | System-wide meaning | Notes |
|------|---------------------------|---------------------|-------|
| **ProgramBlock** | One grid slot's worth of playout (Phase 0 only) | N/A - Phase 0 abstraction | May be replaced in later phases. Not to be confused with `Program`. |
| **PlayoutSegment** | A single file to play with start/end times and seek offset | Aligns with `PlaylistEntry` / `PlaylogEvent` | Simplified version for Phase 0. |
| **Grid** | Fixed time slots (e.g., 30 min) that structure the broadcast day | Same as `grid_block_minutes` on Channel entity | The atomic scheduling unit. |
| **Grid boundary** | The exact moment a grid slot starts/ends (e.g., 9:00:00, 9:30:00) | Same | Boundaries belong to the slot they START, not end. |
| **Main show** | The primary content that plays at grid start (Phase 0) | Analogous to scheduled `Program` content | Phase 0 uses a single file; later phases use asset chains. |
| **Filler** | Content that fills gap between main show end and grid boundary | Analogous to interstitials, bumpers, or avails | Phase 0 truncates at boundary; later phases may use soft transitions. |
| **Hard cut** | Abrupt transition at grid boundary (filler stops, next content starts) | Phase 0 behavior only | Later phases may support soft transitions. |
| **Programming day** | The broadcast day, starting at a configured hour (e.g., 6 AM) | Same as `programming_day_start` on Channel | Times before this hour belong to the previous day. |
| **MasterClock** | The authoritative time source for all scheduling decisions | Same - see [MasterClock.md](../../domain/MasterClock.md) | ScheduleManager never accesses system clock directly. |
| **Program** | (Domain entity) A show, episode, or content unit with metadata | SchedulePlan contains Programs with asset_chain | Different from `ProgramBlock` - naming collision acknowledged. |
| **Channel** | A logical broadcast entity with grid configuration | Same - see Channel entity | Different channels may have different grid sizes. |
| **Segment** | A contiguous portion of media playback | Used loosely across system | In this contract: `PlayoutSegment`. |
| **Seek offset** | Position within a file to start playback (seconds) | Same | Used for join-in-progress. |
| **Block** | (In this contract) Synonym for `ProgramBlock` | Elsewhere: may refer to grid block | Context-dependent. |

### Terminology Collisions

| Collision | Resolution |
|-----------|------------|
| `ProgramBlock` vs `Program` | `ProgramBlock` = grid slot playout unit (Phase 0). `Program` = domain entity (show/episode). Different concepts. |
| `Segment` vs `PlayoutSegment` | This contract uses `PlayoutSegment` (dataclass). Generic "segment" appears elsewhere. |
| `Block` vs `Grid block` vs `ProgramBlock` | "Grid block" = time slot concept. `ProgramBlock` = Phase 0 data structure. Use qualified names when ambiguous. |

---

## See Also

- [SchedulingSystem.md](../../scheduling/SchedulingSystem.md) - Full scheduling architecture
- [ChannelManager.md](../../runtime/ChannelManager.md) - Runtime execution
- [MasterClock.md](../../domain/MasterClock.md) - Time authority

