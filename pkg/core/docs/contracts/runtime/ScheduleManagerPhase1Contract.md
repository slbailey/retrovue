# Schedule Manager Contract - Phase 1: Multiple Programs

Status: Implemented

**Extends:** [ScheduleManagerContract.md](ScheduleManagerContract.md)

---

## Purpose

### How Phase 1 Extends Phase 0

Phase 0 proved the core scheduling loop with a single repeating program. Phase 1 extends this by allowing different programs to be scheduled at different times throughout the broadcast day.

Phase 1 preserves all Phase 0 invariants that still apply. The interface (`ScheduleManager` protocol) remains unchanged. Only the configuration model expands.

### What Problem Phase 1 Solves

Phase 0 plays the same content every grid slot. Real television schedules different shows at different times. Phase 1 enables:

- "Cheers at 9:00 PM" (22 minutes)
- "Movie at 10:00 PM" (2 hours)
- "Morning News at 6:00 AM" (90 minutes)

Programs may span multiple grid slots. A 90-minute morning news show starting at 6:00 AM occupies three 30-minute slots (6:00, 6:30, 7:00).

---

## Scope

### What ScheduleManager Is Responsible For (Phase 1)

- Selecting the correct program for any grid slot based on schedule data
- Handling programs that span multiple consecutive grid slots
- Generating `ProgramBlock` objects that reflect the active program at query time
- Maintaining deterministic, time-based program selection
- Filling unscheduled slots with filler content
- Preserving join-in-progress correctness across all scheduled programs

### What ScheduleManager Explicitly Does Not Do

- Episode selection within a series (Phase 3)
- Dynamic content selection based on playback history (Phase 3)
- Integration with ScheduleDay or EPG entities (Phase 2)
- Randomization of any kind
- Caching or memoization of results
- System clock access
- Playback execution

---

## Key Changes from Phase 0

### Concepts Added

| Concept | Description |
|---------|-------------|
| **ScheduledProgram** | A program starting at a specific grid slot time |
| **Multi-slot programs** | Programs whose duration spans multiple consecutive grid slots |
| **Program lookup** | Finding which program (if any) is active at a given time |
| **Unscheduled slots** | Grid slots not covered by any program (filler-only) |

### Concepts Unchanged

| Concept | Status |
|---------|--------|
| `ProgramBlock` | Unchanged - still represents one grid slot |
| `PlayoutSegment` | Unchanged - still represents one playback instruction |
| Grid alignment | Unchanged - all boundaries align to grid |
| Filler behavior | Fills remainder after program ends (within its final slot) |
| Programming day | Unchanged - 24-hour period starting at configured hour |
| Determinism | Unchanged - same inputs produce same outputs |
| MasterClock-only time | Unchanged - no system clock access |

### Abstractions That Remain Phase-0-Only

| Abstraction | Status |
|-------------|--------|
| `SimpleGridConfig` | Phase 0 only - single repeating program |
| Single `main_show_path` | Phase 0 only - replaced by program lookup |

---

## Data Model (Contract Level)

### ScheduledProgram

Represents a program starting at a specific time. The program occupies consecutive grid slots based on its duration.

| Field | Type | Description |
|-------|------|-------------|
| `slot_time` | time-of-day | Grid-aligned time when this program starts (e.g., 21:00) |
| `file_path` | string | Path to the program file |
| `duration_seconds` | number | Duration of the program content |
| `label` | string (optional) | Human-readable name for debugging |

**Constraints:**
- `slot_time` MUST be grid-aligned (minutes divisible by grid_minutes, seconds = 0)
- `duration_seconds` MUST be positive (> 0)
- `file_path` MUST be non-empty

**Anchoring Rule:** `slot_time` is interpreted relative to the programming day start of the day in which the program is scheduled. A program at 05:30 with `programming_day_start_hour=6` belongs to the *previous* programming day (late night). A program at 06:00 belongs to the *current* programming day.

**Invalid Configuration:** If a ScheduledProgram has invalid duration (zero or negative), behavior is undefined and the configuration is considered invalid. ScheduleManager does not validate configuration; invalid configurations produce undefined results.

### Slot Occupancy

A program occupies consecutive grid slots based on its duration:

```
slots_occupied = ceil(duration_seconds / (grid_minutes * 60))
```

**Example:** 45-minute program with 30-minute grid
- `slots_occupied = ceil(45 / 30) = ceil(1.5) = 2`
- Program occupies 2 consecutive slots

### DailySchedule

Represents a full day's schedule of programs.

| Field | Type | Description |
|-------|------|-------------|
| `grid_minutes` | integer | Grid slot duration |
| `programs` | list of ScheduledProgram | Programs throughout the day |
| `filler_path` | string | Path to filler content |
| `filler_duration_seconds` | number | Duration of filler file |
| `programming_day_start_hour` | integer | Hour when programming day begins (0-23) |

**Programming Day Window:** A programming day is a half-open time window `[DAY_START, DAY_END)` where:
- `DAY_START` = programming_day_start_hour on a given calendar date
- `DAY_END` = DAY_START + 24 hours

This window is authoritative for all scheduling within the day.

**Phase 1 Assumption:** In Phase 1, `DAY_END = DAY_START + 24 hours` always. Future phases may allow shorter programming days (e.g., channel sign-off at midnight), but Phase 1 assumes a full 24-hour window.

**Constraints:**
- `programs` list MAY be empty (all-filler schedule)
- Programs MUST NOT overlap (a slot cannot be covered by two programs)
- All `slot_time` values MUST be grid-aligned

---

## Scheduling Semantics

### How a Program Is Selected for a Grid Slot

Given a query time:

1. Calculate the grid slot `[block_start_utc, block_end_utc)` containing the query time
2. Determine the programming day anchor for the query time
3. For each ScheduledProgram, calculate its absolute time window:
   - `program_start_utc` = programming_day_start + offset_from_slot_time
   - `program_end_utc` = program_start_utc + duration_seconds
4. Find the program (if any) whose time window overlaps the grid slot
5. If found: use that program
6. If not found: slot is unscheduled (filler-only)

This lookup is deterministic and stateless. Programs are matched by absolute time window overlap, not by slot range comparisons.

**Programming Day Anchoring:** Programs belong to a programming day, not to a calendar date. A time before `programming_day_start_hour` belongs to the previous programming day. This means 05:45 on Jan 31 with `programming_day_start_hour=6` maps to Jan 30's programming day.

**Schedule Repetition vs Program Execution:** The schedule definition repeats daily (same programs at same slot_times). However, program execution does not repeat mid-program. A program that crosses the programming-day boundary continues until completion and does not restart at the next day's slot unless explicitly scheduled again.

### Program Shorter Than Grid Slot

If a program's duration is less than the grid slot duration:

- Program plays from slot start for its full duration
- Filler plays from program end until grid boundary
- This matches Phase 0 behavior

**Example:** 22-minute program in 30-minute slot
- 0:00-22:00 → Program
- 22:00-30:00 → Filler

### Program Exactly Fills Grid Slot

If a program's duration equals the grid slot duration:

- Program plays for entire slot
- No filler in this slot

**Example:** 30-minute program in 30-minute slot
- 0:00-30:00 → Program

### Program Spans Multiple Grid Slots

If a program's duration exceeds the grid slot duration:

- Program occupies `ceil(duration / grid_duration)` consecutive slots
- Program plays continuously across slot boundaries
- Filler appears only after the program ends (in the final slot, if there's remaining time)

**Example:** 45-minute program starting at 21:00 with 30-minute grid
- Occupies slots: 21:00-21:30, 21:30-22:00
- 21:00-21:45 → Program (continuous)
- 21:45-22:00 → Filler (15 minutes)

**Example:** 90-minute movie starting at 22:00 with 30-minute grid
- Occupies slots: 22:00-22:30, 22:30-23:00, 23:00-23:30
- 22:00-23:30 → Movie (continuous, exactly fills 3 slots)
- No filler

### Unscheduled Slots

If no program covers a grid slot:

- Entire slot plays filler content
- Filler starts at seek offset 0
- Filler is truncated at grid boundary

### Filler Behavior

- Filler appears only in unscheduled slots OR after a program ends mid-slot
- Filler always starts at seek offset 0
- Filler is always truncated at grid boundary
- Filler file must be at least as long as the grid slot duration

---

## Invariants

### Phase 0 Invariants That Still Apply

| ID | Invariant | Status |
|----|-----------|--------|
| INV-SM-001 | Grid Alignment | **Applies** - all slot boundaries align to grid |
| INV-SM-002 | Deterministic Calculation | **Applies** - same inputs produce same outputs |
| INV-SM-003 | Complete Coverage | **Applies** - every moment covered by exactly one segment |
| INV-SM-004 | Hard Cut at Grid Boundary | **Modified** - applies to filler, not programs |
| INV-SM-005 | Main Show Never Truncated | **Preserved** - see INV-P1-003 |
| INV-SM-006 | Jump-In Anywhere | **Applies** - any time maps to correct file + offset |
| INV-SM-007 | No System Clock Access | **Applies** - time from parameters only |
| INV-SM-008 | Configuration Snapshot Consistency | **Applies** - config immutable per call |

### New Invariants (Phase 1)

#### INV-P1-001: Program Selection Is Deterministic

The same query time MUST always return the same program.

```
GIVEN a query time and a DailySchedule
WHEN program lookup is performed
THEN the result is always the same program (or no program)
```

#### INV-P1-002: Programs Must Not Overlap

No grid slot may be covered by more than one program.

```
GIVEN a DailySchedule with programs A and B
THEN the time windows of A and B MUST NOT overlap
```

#### INV-P1-003: Programs Are Never Truncated

Programs play their full duration. They span as many grid slots as needed.

```
GIVEN a ScheduledProgram with duration D
AND grid slot duration G
WHEN the program is scheduled
THEN the program occupies ceil(D / G) consecutive grid slots
AND playback continues uninterrupted across slot boundaries
```

#### INV-P1-004: Program Slot Coverage

A slot covered by a program MUST NOT contain filler during the program's runtime.

```
GIVEN a grid slot S
WHEN a ScheduledProgram spans S
THEN S is NOT treated as unscheduled
AND filler appears ONLY after the program ends (if it ends mid-slot)
```

#### INV-P1-005: Schedule Definition Repeats Daily

The schedule definition repeats every 24 hours relative to programming day start.

```
GIVEN times T and T + 24 hours
AND neither time falls within a cross-day program from the previous day
WHEN get_program_at() is called for both
THEN both return equivalent content (same program at same offset, or same filler)
```

**Note:** This refers to the schedule *definition*, not program *execution*. A program that crosses the day boundary does not restart—it continues until completion.

#### INV-P1-006: Unscheduled Slots Are Valid

Slots not covered by any program are filled entirely with filler.

```
GIVEN a grid slot with no program coverage
WHEN get_program_at() is called
THEN the returned ProgramBlock contains filler for the slot's duration
```

#### INV-P1-007: Programs May Cross Programming-Day Boundaries

Programs that extend past the programming-day boundary continue until completion.

```
GIVEN a ScheduledProgram with start time S and duration D
AND a programming day window [DAY_START, DAY_END)
WHEN S + D > DAY_END
THEN the program continues past DAY_END until S + D
AND is considered active in the next programming day until it ends
AND filler applies only after the program completes
AND the program does NOT restart at the next day's scheduled slot
```

**Example:** Program at 05:30 with 60-minute duration, programming_day_start=06:00
- Program starts in previous programming day (05:30 is late night)
- Program crosses day boundary at 06:00
- Program ends at 06:30
- Query at 06:15 returns the program at offset 45:00
- The next day's 05:30 slot is a fresh instance (not a continuation)

### Explicit Statement of Determinism and Time Ownership

**Determinism:** All ScheduleManager operations are pure functions of their inputs. Given the same `channel_id`, `at_time`, and configuration, the result is always identical. No internal state, no randomness, no side effects.

**Time Ownership:** ScheduleManager does not own time. All time values come from parameters (`at_time`, `after_time`). These parameters are expected to originate from MasterClock. ScheduleManager never calls `datetime.now()` or any system time function.

---

## Behavior Rules

### B-P1-001: get_program_at() With Multi-Slot Programs

```
GIVEN get_program_at(channel_id, at_time)
THEN:
  1. Calculate grid slot [block_start, block_end) containing at_time
  2. Find program (if any) whose slot range covers this block
  3. Build segments that cover the ENTIRE block:
     a) If program covers the whole block:
        - One program segment [block_start, block_end)
        - seek_offset_seconds = block_start - program_start_time
     b) If program ends mid-block:
        - Program segment [block_start, program_end)
        - seek_offset_seconds = block_start - program_start_time
        - Filler segment [program_end, block_end)
     c) If no program covers this block:
        - Filler segment [block_start, block_end)
  4. Return ProgramBlock with block_start, block_end, segments
```

**Critical:** The returned segments describe the entire grid slot. The query time (`at_time`) is only used to select which slot; the segments are NOT tailored to the query time.

### B-P1-002: get_next_program() Across Multi-Slot Programs

```
GIVEN get_next_program(channel_id, after_time)
THEN:
  1. Calculate next grid boundary >= after_time
  2. Find program (if any) whose slot range covers that slot
  3. Build ProgramBlock for that slot (same rules as B-P1-001)
  4. Return ProgramBlock
```

The returned block may be a continuation of the current program (if it spans multiple slots), a different program, or filler.

### B-P1-003: Boundary Cases

**Exact boundary query:**
```
GIVEN get_program_at(channel_id, at_time) where at_time is exactly on a grid boundary
THEN at_time belongs to the slot STARTING at that boundary
```

**Next program at exact boundary:**
```
GIVEN get_next_program(channel_id, after_time) where after_time is exactly on a grid boundary
THEN return the slot starting at after_time (boundary belongs to new slot)
```

These rules are unchanged from Phase 0.

### B-P1-004: Join-In-Progress Across Multi-Slot Programs

```
GIVEN a viewer joining at any time T within a program that spans multiple slots
THEN:
  1. get_program_at(T) returns the ProgramBlock for the slot containing T
  2. The segment containing T has the correct file_path
  3. The segment's seek_offset_seconds = block_start - program_start_time
  4. The viewer's file position is computed as:
     file_position = seek_offset_seconds + (T - segment.start_utc)
```

**Critical:** `seek_offset_seconds` is the offset at `segment.start_utc` (the block boundary), NOT at the viewer's join time. The join-time position is derived by adding the delta.

**Example:** 45-minute program starts at 21:00, 30-minute grid

| Join Time | Block | seek_offset_seconds | Delta | File Position |
|-----------|-------|---------------------|-------|---------------|
| 21:15 | 21:00-21:30 | 0:00 | 15:00 | 15:00 |
| 21:35 | 21:30-22:00 | 30:00 | 5:00 | 35:00 |
| 21:50 | 21:30-22:00 | (filler) | 5:00 | filler at 5:00 |

Join-in-progress works correctly regardless of which slot the viewer joins in.

---

## Test Specifications

### Program Selection

**P1-T001: Scheduled slot returns correct program**
- Given: ScheduledProgram at 21:00 with file "cheers.mp4"
- When: get_program_at() called for 21:15
- Then: First segment file_path is "cheers.mp4"

**P1-T002: Unscheduled slot returns filler only**
- Given: No ScheduledProgram covering 14:00
- When: get_program_at() called for 14:15
- Then: Single segment with filler file_path

**P1-T003: Adjacent programs return different content**
- Given: "cheers.mp4" (22 min) at 21:00, "night_court.mp4" at 21:30
- When: get_program_at() called for 21:15 and 21:45
- Then: First returns cheers, second returns night_court

**P1-T004: Same slot always returns same program**
- Given: ScheduledProgram at 21:00
- When: get_program_at() called 100 times for 21:15
- Then: All 100 results are identical

### Multi-Slot Programs

**P1-T005: Program spanning two slots - first slot**
- Given: 45-minute program at 21:00, 30-minute grid
- When: get_program_at() called for 21:15
- Then: Returns program segment with seek_offset=0:00, file_position at 21:15 = 15:00

**P1-T006: Program spanning two slots - second slot**
- Given: 45-minute program at 21:00, 30-minute grid
- When: get_program_at() called for 21:35
- Then: Returns program segment with seek_offset=30:00, file_position at 21:35 = 35:00

**P1-T007: Program spanning two slots - filler after program ends**
- Given: 45-minute program at 21:00, 30-minute grid
- When: get_program_at() called for 21:50
- Then: Returns filler segment (program ended at 21:45)

**P1-T008: Program exactly fills multiple slots**
- Given: 60-minute program at 21:00, 30-minute grid
- When: get_program_at() called for 21:15 and 21:45
- Then: First block: seek_offset=0:00, file_position=15:00; Second block: seek_offset=30:00, file_position=45:00

**P1-T009: Long program (movie) spans many slots**
- Given: 120-minute movie at 20:00, 30-minute grid
- When: get_program_at() called for 20:15, 20:45, 21:15, 21:45
- Then: seek_offsets are 0, 30, 60, 90 minutes; file_positions are 15, 45, 75, 105 minutes

### Program Duration Variants

**P1-T010: Program shorter than slot includes filler**
- Given: 20-minute program, 30-minute grid
- When: get_program_at() called for time in filler portion
- Then: Returns filler segment

**P1-T011: Program exactly fills slot has no filler**
- Given: 30-minute program, 30-minute grid
- When: get_program_at() called
- Then: Entire slot is program, no filler

### Join-In-Progress

**P1-T012: Join mid-program in first slot**
- Given: 45-minute program starts at 21:00
- When: Viewer joins at 21:15:30
- Then: seek_offset=0:00, file_position = 0 + 930 = 930 seconds (15:30)

**P1-T013: Join mid-program in second slot**
- Given: 45-minute program starts at 21:00
- When: Viewer joins at 21:35:00
- Then: seek_offset=30:00 (1800s), file_position = 1800 + 300 = 2100 seconds (35:00)

**P1-T014: Join during filler after multi-slot program**
- Given: 45-minute program at 21:00 (ends 21:45)
- When: Viewer joins at 21:50
- Then: Returns filler segment starting at 21:45, seek_offset=0, file_position = 0 + 300 = 5:00

**P1-T015: Join in unscheduled slot**
- Given: No program covering 14:00
- When: Viewer joins at 14:15
- Then: Returns filler with offset 15:00

### Grid Transitions

**P1-T016: get_next_program within multi-slot program**
- Given: 90-minute program at 21:00, currently at 21:25
- When: get_next_program() called for 21:25
- Then: Returns 21:30 slot, still within same program

**P1-T017: get_next_program at end of multi-slot program**
- Given: 45-minute program at 21:00 (ends 21:45), currently at 21:40
- When: get_next_program() called for 21:40
- Then: Returns 21:30 slot with filler (from 21:45-22:00)

**P1-T018: get_next_program transitions to new program**
- Given: Program A ends at 21:45, Program B starts at 22:00
- When: get_next_program() called for 21:50
- Then: Returns 22:00 slot with Program B

### Programming Day Boundaries

**P1-T019: Multi-slot program crossing midnight**
- Given: 90-minute program at 23:00, programming_day_start=6
- When: get_program_at() called for 00:15 (next calendar day)
- Then: Returns program with offset 75:00 (still same programming day)

**P1-T020: Program at 5:30 AM belongs to previous programming day**
- Given: programming_day_start_hour=6, program at 05:30
- When: get_program_at() called for 05:45 on Jan 31
- Then: Returns program from Jan 30's programming day

**P1-T021: Schedule wraps at programming day boundary**
- Given: programming_day_start_hour=6
- When: get_program_at() called for 05:59:59 and 06:00:00 on same calendar day
- Then: First belongs to previous programming day, second to current

**P1-T024: Program crossing programming-day boundary** (INV-P1-007)
- Given: Program at 05:30 with 60-minute duration, programming_day_start=6
- When: get_program_at() called for 06:15
- Then: Returns program with seek_offset=30:00, file_position=45:00
- Note: Program started in previous programming day but continues past 06:00 boundary

### Full Coverage

**P1-T022: Every minute of 24 hours returns valid block**
- Given: Any valid DailySchedule
- When: get_program_at() called for every minute of 24 hours
- Then: All calls return valid ProgramBlock with no gaps

**P1-T023: Empty schedule (all filler) is valid**
- Given: DailySchedule with empty programs list
- When: get_program_at() called for any time
- Then: Returns valid ProgramBlock with filler only

---

## Glossary Additions

| Term | Definition | Disambiguation |
|------|------------|----------------|
| **ScheduledProgram** | A program starting at a specific grid slot time | Not the same as domain `Program` entity (which has asset_chain, play_mode) |
| **Multi-slot program** | A program whose duration spans more than one grid slot | Occupies `ceil(duration / grid_duration)` consecutive slots |
| **Program time window** | Absolute interval `[program_start_utc, program_end_utc)` during which a program is active | Programs may span multiple grid slots; coverage is determined by time overlap, not slot count |
| **Program lookup** | Finding which program (if any) covers a given time | Pure function checking time window overlap, no state |
| **Unscheduled slot** | A grid slot not covered by any program's time window | Filled entirely with filler |
| **DailySchedule** | Configuration containing all ScheduledPrograms for a 24-hour period | Repeats daily; not the same as `ScheduleDay` entity |

---

## Non-Goals

Phase 1 does **not** attempt to solve:

| Non-Goal | Rationale |
|----------|-----------|
| Episode rotation within a series | Phase 3 concern (asset_chain, play_mode) |
| Random program selection | Violates determinism invariant |
| Integration with ScheduleDay/EPG entities | Phase 2 concern |
| Playback history tracking | Requires state; violates statelessness |
| Ad insertion or avail management | Out of scope for ScheduleManager |
| Multiple schedules per channel | Configuration concern, not scheduling |
| Schedule versioning or effective dates | Operational concern, not scheduling |
| Content validation (file existence) | Explicitly out of scope |
| Program overlap resolution | Configuration must be valid; overlaps are invalid |

---

## See Also

- [ScheduleManagerContract.md](ScheduleManagerContract.md) - Phase 0 contract
- [SchedulingSystem.md](../../scheduling/SchedulingSystem.md) - Full scheduling architecture

