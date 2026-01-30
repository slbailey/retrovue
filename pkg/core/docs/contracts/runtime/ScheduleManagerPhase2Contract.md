# Schedule Manager Contract - Phase 2: ScheduleDay Integration

Status: Implemented

**Extends:** [ScheduleManagerPhase1Contract.md](ScheduleManagerPhase1Contract.md)

---

## Purpose

### How Phase 2 Extends Phase 1

Phase 1 proved multi-program scheduling with a flat `DailyScheduleConfig` that repeats identically every day. Phase 2 replaces this flat configuration with **ScheduleDay** entities—immutable snapshots representing one programming day's worth of scheduled content.

Phase 2 preserves all Phase 1 invariants and behaviors. The external interface (`ScheduleManager` protocol) remains unchanged. Only the configuration source changes: from a repeating list to day-specific schedule lookups.

### What Problem Phase 2 Solves

Phase 1 schedules repeat identically forever. Real television has:

- Different schedules on different days (weekday vs weekend)
- Special event programming on specific dates
- Schedule changes over time (new season lineups)
- Day-specific content that does not repeat

Phase 2 enables:

- "Monday Night Football" only on Mondays
- "Holiday Special" on December 25th only
- Different weekend programming
- Schedule evolution without code changes

### What Phase 2 Does NOT Solve

Phase 2 does NOT introduce:

- Episode selection within a series (Phase 3)
- Schedule generation or editing logic
- EPG rendering or guide display
- Conflict resolution or validation
- Dynamic content selection
- Playback history or as-run logging

---

## Scope

### What ScheduleManager Is Responsible For (Phase 2)

- Resolving which ScheduleDay applies to a given query time
- Selecting the correct program from that ScheduleDay for any grid slot
- Handling programs that span multiple grid slots (unchanged from Phase 1)
- Handling programs that cross programming-day boundaries (unchanged from Phase 1)
- Generating `ProgramBlock` objects that reflect the active program at query time
- Maintaining deterministic, stateless behavior

### What ScheduleManager Explicitly Does Not Do

- Episode selection within a series (Phase 3)
- Schedule generation, creation, or editing
- EPG guide rendering or display formatting
- Conflict detection or resolution
- Validation of schedule consistency
- Caching or memoization of results
- System clock access
- Playback execution or control
- As-run logging or history tracking
- "What's on tonight?" queries spanning multiple hours

---

## Key Changes from Phase 1

### Concepts Added

| Concept | Description |
|---------|-------------|
| **ScheduleDay** | Immutable snapshot of one programming day's schedule |
| **ScheduleEntry** | A single scheduled item within a ScheduleDay |
| **ScheduleSource** | Abstraction that provides ScheduleDay for any programming day |
| **Day-specific scheduling** | Different programs on different days |

### Concepts Unchanged

| Concept | Status |
|---------|--------|
| `ProgramBlock` | Unchanged - still represents one grid slot |
| `PlayoutSegment` | Unchanged - still represents one playback instruction |
| Grid alignment | Unchanged - all boundaries align to grid |
| Filler behavior | Fills remainder after program ends (within its final slot) |
| Programming day window | Unchanged - `[DAY_START, DAY_END)` |
| Multi-slot programs | Unchanged - programs span `ceil(duration/grid)` slots |
| Cross-day programs | Unchanged - programs continue past day boundary until completion |
| Determinism | Unchanged - same inputs produce same outputs |
| MasterClock-only time | Unchanged - no system clock access |
| seek_offset semantics | Unchanged - offset at block boundary |

### Abstractions Superseded

| Abstraction | Status |
|-------------|--------|
| `DailyScheduleConfig.programs` | Replaced by ScheduleDay lookup |
| Implicit daily repetition | Replaced by explicit day resolution |

---

## Data Model (Contract Level)

### ScheduleEntry

Represents a single scheduled item within a ScheduleDay. This is the Phase 2 equivalent of Phase 1's `ScheduledProgram`, but anchored to a specific programming day rather than repeating daily.

| Field | Type | Description |
|-------|------|-------------|
| `slot_time` | time-of-day | Grid-aligned time when this entry starts |
| `file_path` | string | Path to the program file |
| `duration_seconds` | number | Duration of the program content |
| `label` | string (optional) | Human-readable name for debugging |

**Constraints:**
- `slot_time` MUST be grid-aligned (minutes divisible by grid_minutes, seconds = 0)
- `duration_seconds` MUST be positive (> 0)
- `file_path` MUST be non-empty

**Note:** ScheduleEntry is structurally identical to Phase 1's ScheduledProgram. The semantic difference is that ScheduleEntry belongs to a specific ScheduleDay, not a repeating configuration.

### ScheduleDay

Represents an immutable snapshot of one programming day's schedule.

| Field | Type | Description |
|-------|------|-------------|
| `programming_day_date` | date | The calendar date of the programming day start |
| `entries` | list of ScheduleEntry | Scheduled items for this day |

**Semantics:**
- A ScheduleDay covers the programming day window starting at `programming_day_date` + `programming_day_start_hour`
- The window extends for the configured duration (24 hours in Phase 2)
- `entries` are ordered by `slot_time`
- Entries MUST NOT overlap (enforced by schedule generation, not ScheduleManager)

**Immutability:** Once created, a ScheduleDay MUST NOT be modified. Any schedule change requires generating a new ScheduleDay. ScheduleManager treats ScheduleDay as a read-only value.

### ScheduleSource

Abstraction that provides ScheduleDay instances to ScheduleManager.

```
Protocol ScheduleSource:
    get_schedule_day(channel_id: str, programming_day_date: date) -> ScheduleDay | None
```

**Semantics:**
- Returns the ScheduleDay for the given channel and programming day date
- Returns `None` if no schedule exists for that day
- The returned ScheduleDay MUST be immutable
- Multiple calls with the same arguments MUST return equivalent results

**Implementation Note:** ScheduleSource is an abstraction boundary. Implementations may read from a database, a file, or an in-memory cache. ScheduleManager does not care how ScheduleDay is obtained—only that it is deterministic and immutable.

### ScheduleDayConfig

Configuration for a ScheduleDay-based ScheduleManager.

| Field | Type | Description |
|-------|------|-------------|
| `grid_minutes` | integer | Grid slot duration |
| `schedule_source` | ScheduleSource | Provider of ScheduleDay instances |
| `filler_path` | string | Path to filler content |
| `filler_duration_seconds` | number | Duration of filler file |
| `programming_day_start_hour` | integer | Hour when programming day begins (0-23) |

**Constraints:**
- `grid_minutes` MUST be positive and divide evenly into 60 or 1440
- `filler_duration_seconds` MUST be >= `grid_minutes * 60`

---

## Scheduling Semantics

### How ScheduleDay Is Resolved

Given a query time:

1. Determine which programming day the query time belongs to
2. Calculate the `programming_day_date` for that programming day
3. Call `schedule_source.get_schedule_day(channel_id, programming_day_date)`
4. If no ScheduleDay exists, treat as an empty schedule (all filler)

**Programming Day Resolution:**
- Query time `T` belongs to programming day starting at `T.date` if `T.hour >= programming_day_start_hour`
- Otherwise, `T` belongs to the programming day starting at `T.date - 1 day`

This is unchanged from Phase 1.

### How a Program Is Selected

Given a query time and a resolved ScheduleDay:

1. Calculate the grid slot `[block_start_utc, block_end_utc)` containing the query time
2. For each ScheduleEntry in the ScheduleDay, calculate its absolute time window:
   - `entry_start_utc` = programming_day_start + offset_from_slot_time
   - `entry_end_utc` = entry_start_utc + duration_seconds
3. Find the entry (if any) whose time window overlaps the grid slot
4. If found: use that entry
5. If not found: check previous programming day for cross-day programs
6. If still not found: slot is unscheduled (filler-only)

This algorithm is identical to Phase 1, with ScheduleDay replacing DailyScheduleConfig.

### Cross-Day Program Handling

Programs that cross the programming-day boundary are handled exactly as in Phase 1:

1. The program is listed in the ScheduleDay where it **starts**
2. When querying a time in the **next** programming day, ScheduleManager checks the previous day's ScheduleDay for still-active programs
3. A program continues until its natural end, regardless of day boundaries
4. The program does NOT appear in the next day's ScheduleDay (it's not "scheduled" there—it's continuing from yesterday)

**Example:** A program at 05:30 with 60-minute duration in Monday's ScheduleDay:
- Starts Monday 05:30 (Monday's programming day, which started Sunday 06:00)
- Crosses into Tuesday's programming day at 06:00
- Ends Tuesday 06:30
- Query at Tuesday 06:15 returns this program from Monday's ScheduleDay

### Missing ScheduleDay Handling

If `schedule_source.get_schedule_day()` returns `None`:

- The programming day is treated as having no scheduled programs
- All slots return filler
- This is NOT an error—it represents an intentionally empty schedule

ScheduleManager MUST NOT raise exceptions for missing schedules. Filler is the correct fallback.

---

## Invariants

### Phase 1 Invariants That Still Apply

All Phase 1 invariants apply unchanged:

| ID | Invariant | Status |
|----|-----------|--------|
| INV-P1-001 | Program Selection Is Deterministic | **Applies** |
| INV-P1-002 | Programs Must Not Overlap | **Applies** (within a ScheduleDay) |
| INV-P1-003 | Programs Are Never Truncated | **Applies** |
| INV-P1-004 | Program Slot Coverage | **Applies** |
| INV-P1-005 | Schedule Definition Repeats Daily | **Modified** - see INV-P2-001 |
| INV-P1-006 | Unscheduled Slots Are Valid | **Applies** |
| INV-P1-007 | Programs May Cross Programming-Day Boundaries | **Applies** |

### New Invariants (Phase 2)

#### INV-P2-001: Day-Specific Schedule Resolution

Each programming day resolves to at most one ScheduleDay.

```
GIVEN a query time T
WHEN ScheduleManager resolves the programming day
THEN exactly one ScheduleDay (or None) is used for that day
AND the same query time always resolves to the same ScheduleDay
```

This replaces INV-P1-005's "repeats daily" with "resolves per day."

#### INV-P2-002: ScheduleDay Immutability

ScheduleManager treats ScheduleDay as immutable.

```
GIVEN a ScheduleDay S returned by ScheduleSource
WHEN ScheduleManager uses S
THEN ScheduleManager MUST NOT modify S
AND ScheduleManager MUST NOT cache S beyond the current call
```

#### INV-P2-003: ScheduleSource Determinism

ScheduleSource MUST return consistent results.

```
GIVEN a channel_id and programming_day_date
WHEN get_schedule_day() is called multiple times
THEN all calls MUST return equivalent ScheduleDay instances (or all return None)
```

**Note:** This is a constraint on ScheduleSource implementations, not on ScheduleManager. ScheduleManager assumes ScheduleSource is deterministic.

#### INV-P2-004: Cross-Day Lookup Is Bounded

ScheduleManager checks at most two ScheduleDays per query.

```
GIVEN a query time T
WHEN ScheduleManager resolves the active program
THEN ScheduleManager checks at most:
  - The ScheduleDay for T's programming day
  - The ScheduleDay for the previous programming day (for cross-day programs)
AND no other ScheduleDays are consulted
```

This bounds the lookup scope and prevents unbounded backward searches.

#### INV-P2-005: Missing Schedule Produces Filler

A missing ScheduleDay results in filler, not an error.

```
GIVEN a channel_id and programming_day_date
WHEN get_schedule_day() returns None
THEN all slots in that programming day return filler
AND no exception is raised
```

### Explicit Statement of Determinism

**Determinism:** All ScheduleManager operations remain pure functions of their inputs. Given the same `channel_id`, `at_time`, and ScheduleSource state, the result is always identical.

**ScheduleSource Contract:** ScheduleManager's determinism depends on ScheduleSource's determinism. If ScheduleSource returns different results for the same inputs, ScheduleManager's output will differ accordingly. This is not a violation—ScheduleManager correctly reflects its inputs.

---

## Behavior Rules

### B-P2-001: get_program_at() With ScheduleDay

```
GIVEN get_program_at(channel_id, at_time)
THEN:
  1. Determine programming_day_date for at_time
  2. Retrieve ScheduleDay via schedule_source.get_schedule_day(channel_id, programming_day_date)
  3. If ScheduleDay is None: return filler for the grid slot
  4. Calculate grid slot [block_start, block_end) containing at_time
  5. Search ScheduleDay entries for time window overlap with grid slot
  6. If no overlap found: check previous programming day's ScheduleDay for cross-day program
  7. Build segments for the grid slot (unchanged from Phase 1)
  8. Return ProgramBlock
```

### B-P2-002: get_next_program() With ScheduleDay

```
GIVEN get_next_program(channel_id, after_time)
THEN:
  1. Calculate next grid boundary >= after_time
  2. Apply B-P2-001 logic for that grid slot
  3. Return ProgramBlock
```

### B-P2-003: ScheduleDay Boundary Handling

```
GIVEN a query time T near a programming day boundary
WHEN T is in the first slot of a new programming day (e.g., 06:00-06:30)
THEN:
  1. Retrieve current day's ScheduleDay
  2. Check for programs starting at 06:00 or later
  3. Retrieve previous day's ScheduleDay
  4. Check for programs that started before 06:00 and extend past 06:00
  5. If a previous-day program overlaps, use it
  6. Otherwise, use current-day program or filler
```

Previous-day programs take precedence over current-day programs in the overlap case. However, overlaps are invalid configurations—ScheduleSource SHOULD NOT produce them.

---

## Test Specifications

### ScheduleDay Resolution

**P2-T001: Query resolves to correct ScheduleDay**
- Given: ScheduleDay for 2025-01-30 with program at 21:00
- When: get_program_at() called for 2025-01-30 21:15
- Then: Returns program from 2025-01-30's ScheduleDay

**P2-T002: Query before programming_day_start resolves to previous day**
- Given: ScheduleDay for 2025-01-29 with program at 05:30
- When: get_program_at() called for 2025-01-30 05:45 (programming_day_start=6)
- Then: Returns program from 2025-01-29's ScheduleDay

**P2-T003: Missing ScheduleDay returns filler**
- Given: No ScheduleDay for 2025-01-30
- When: get_program_at() called for 2025-01-30 21:15
- Then: Returns filler segment for entire slot

**P2-T004: Different days return different programs**
- Given: Monday ScheduleDay with "monday_show.mp4" at 21:00
- Given: Tuesday ScheduleDay with "tuesday_show.mp4" at 21:00
- When: get_program_at() called for Monday 21:15 and Tuesday 21:15
- Then: Returns monday_show and tuesday_show respectively

### Cross-Day Programs With ScheduleDay

**P2-T005: Cross-day program from previous ScheduleDay**
- Given: Monday ScheduleDay with program at 05:30 (60 min duration)
- Given: Tuesday ScheduleDay with program at 06:30
- When: get_program_at() called for Tuesday 06:15
- Then: Returns Monday's program at offset 45:00

**P2-T006: Cross-day program does not appear in next day's ScheduleDay**
- Given: Monday ScheduleDay with program at 23:00 (120 min duration, ends 01:00)
- Given: Tuesday ScheduleDay is empty
- When: get_program_at() called for Tuesday 00:30
- Then: Returns Monday's program at offset 90:00

**P2-T007: Current-day program after cross-day program ends**
- Given: Monday ScheduleDay with program at 05:30 (30 min, ends 06:00)
- Given: Tuesday ScheduleDay with program at 06:00
- When: get_program_at() called for Tuesday 06:15
- Then: Returns Tuesday's program (Monday's program ended exactly at boundary)

### Multi-Slot Programs (Phase 1 Behavior Preserved)

**P2-T008: Multi-slot program spans correctly with ScheduleDay**
- Given: ScheduleDay with 45-minute program at 21:00
- When: get_program_at() called for 21:35
- Then: Returns program with seek_offset=30:00, file_position=35:00

**P2-T009: Long program across ScheduleDay**
- Given: ScheduleDay with 120-minute movie at 20:00
- When: get_program_at() called for 20:15, 20:45, 21:15, 21:45
- Then: All return movie with correct seek_offsets (0, 30, 60, 90 min)

### Filler Behavior

**P2-T010: Unscheduled slot in ScheduleDay returns filler**
- Given: ScheduleDay with program at 21:00 only
- When: get_program_at() called for 14:15
- Then: Returns filler for entire slot

**P2-T011: Empty ScheduleDay returns all filler**
- Given: ScheduleDay with empty entries list
- When: get_program_at() called for any time
- Then: Returns filler for entire slot

### Determinism

**P2-T012: Same query returns same result**
- Given: ScheduleDay with program at 21:00
- When: get_program_at() called 100 times for 21:15
- Then: All 100 results are identical

**P2-T013: ScheduleSource determinism reflected**
- Given: ScheduleSource returns consistent ScheduleDay
- When: get_program_at() called multiple times
- Then: Results are identical

### Grid Transitions

**P2-T014: get_next_program with ScheduleDay**
- Given: ScheduleDay with program at 21:00, current time 20:50
- When: get_next_program() called for 20:50
- Then: Returns 21:00 slot with program

**P2-T015: get_next_program crosses into next ScheduleDay**
- Given: Monday ScheduleDay ends at 06:00, Tuesday ScheduleDay has program at 06:00
- When: get_next_program() called for Monday 05:50
- Then: Returns 06:00 slot with Tuesday's program

### Full Coverage

**P2-T016: Every minute of 24 hours returns valid block**
- Given: Any valid ScheduleDay
- When: get_program_at() called for every minute of 24 hours
- Then: All calls return valid ProgramBlock with no gaps

---

## Glossary Additions

| Term | Definition | Disambiguation |
|------|------------|----------------|
| **ScheduleDay** | Immutable snapshot of one programming day's schedule | Not the same as calendar day; anchored to programming_day_start_hour |
| **ScheduleEntry** | A single scheduled item within a ScheduleDay | Equivalent to Phase 1's ScheduledProgram but day-specific |
| **ScheduleSource** | Abstraction providing ScheduleDay instances | Implementation may be in-memory, database, or file-based |
| **Day-specific scheduling** | Different schedules on different days | Replaces Phase 1's identical daily repetition |
| **Programming day date** | Calendar date when a programming day starts | Used to look up ScheduleDay |

---

## Non-Goals

Phase 2 does **not** attempt to solve:

| Non-Goal | Rationale |
|----------|-----------|
| Episode selection within a series | Phase 3 concern |
| Schedule generation or editing | ScheduleSource responsibility |
| EPG rendering or guide display | Consumer responsibility |
| Conflict detection or resolution | ScheduleSource responsibility |
| Schedule validation | ScheduleSource responsibility |
| "What's on tonight?" multi-hour queries | EPG consumer responsibility |
| Schedule versioning or effective dates | ScheduleSource responsibility |
| As-run logging | Separate system |
| Playback control | AIR responsibility |
| Random or dynamic content selection | Violates determinism |

---

## Phase 1 Behavior Preservation

Phase 2 MUST preserve all Phase 1 behaviors when ScheduleDay data is equivalent to Phase 1 configuration.

### Equivalence Definition

A ScheduleSource is **Phase-1-equivalent** if:
- `get_schedule_day()` returns the same ScheduleDay for all dates
- That ScheduleDay contains entries equivalent to DailyScheduleConfig.programs

### Preservation Guarantee

```
GIVEN a Phase-1-equivalent ScheduleSource
AND the same grid_minutes, filler_path, filler_duration_seconds, programming_day_start_hour
WHEN get_program_at() or get_next_program() is called
THEN the result MUST be identical to Phase 1's DailyScheduleManager
```

This ensures backward compatibility. Existing Phase 1 tests SHOULD pass with a Phase-1-equivalent ScheduleSource.

---

## Implementation Notes (Non-Normative)

These notes guide implementation but are not part of the contract.

### ScheduleSource Implementations

Possible ScheduleSource implementations:

1. **StaticScheduleSource**: Returns the same ScheduleDay for all dates (Phase-1-equivalent)
2. **DayOfWeekScheduleSource**: Returns different ScheduleDay based on day of week
3. **DatabaseScheduleSource**: Looks up ScheduleDay from database
4. **CalendarScheduleSource**: Returns ScheduleDay from a date-keyed dictionary

ScheduleManager does not care which implementation is used.

### Performance Considerations

ScheduleManager calls `get_schedule_day()` on every `get_program_at()` call. Implementations MAY cache internally, but ScheduleManager itself MUST NOT cache.

For cross-day program handling, ScheduleManager may call `get_schedule_day()` twice per query (current day + previous day). This is acceptable and bounded by INV-P2-004.

### Migration Path

To migrate from Phase 1 to Phase 2:

1. Implement a StaticScheduleSource wrapping existing DailyScheduleConfig
2. Replace DailyScheduleManager with Phase 2 ScheduleManager
3. Verify all Phase 1 tests pass
4. Gradually introduce day-specific ScheduleDays as needed

---

## See Also

- [ScheduleManagerContract.md](ScheduleManagerContract.md) - Phase 0 contract
- [ScheduleManagerPhase1Contract.md](ScheduleManagerPhase1Contract.md) - Phase 1 contract
- Core domain documentation for ScheduleDay entity (when defined)
