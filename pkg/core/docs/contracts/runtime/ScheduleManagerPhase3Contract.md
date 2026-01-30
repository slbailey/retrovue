# Schedule Manager Contract - Phase 3: Dynamic Content Selection

Status: Implemented

**Extends:** [ScheduleManagerPhase2Contract.md](ScheduleManagerPhase2Contract.md)

---

## Purpose

### How Phase 3 Extends Phase 2

Phase 2 proved day-specific schedule resolution via ScheduleDay entities. However, Phase 2 schedules reference static file paths—the same file plays every time "Cheers at 9pm" is scheduled.

Phase 3 introduces **dynamic content selection**: a scheduled program slot (e.g., "Cheers at 9pm") resolves to a **specific episode** before playout begins. This resolution happens during EPG generation, not at playback time.

Phase 3 preserves all Phase 0–2 invariants. The external interface (`ScheduleManager` protocol) remains unchanged. The internal behavior gains two conceptual phases: Programming Logic (editorial) and Traffic Logic (structural).

### What Problem Phase 3 Solves

Phase 2 schedules are static: "Cheers at 9pm" always plays the same file. Real television has:

- Series with many episodes requiring selection logic
- Sequential viewing (episode 1, then 2, then 3...)
- Syndicated rotation (random episode from pool)
- Special programming (Movie of the Week, marathons)
- EPG guides showing specific episode information

Phase 3 enables:

- "Cheers at 9pm" → "Cheers S02E05 - Simon Says" in the EPG
- Viewers see episode titles before tuning in
- Deterministic episode progression across days
- Movie slots with specific film selections

### What Phase 3 Does NOT Solve

Phase 3 does NOT introduce:

- Viewer-specific content selection
- Playback-time episode decisions
- Ad pod insertion or promo scheduling (Phase N)
- Soft transitions or overlapping content (Phase N)
- As-run logging or playback history during playout
- Real-time schedule modifications

---

## Scope

### What ScheduleManager Is Responsible For (Phase 3)

ScheduleManager is the **primary scheduling engine**, responsible for:

- Building and maintaining the EPG horizon (24–72 hours ahead)
- Deciding which episode or asset airs for each program slot
- Producing deterministic, repeatable schedules
- Ensuring EPG identity stability (episode choice is immutable once published)

ScheduleManager is NOT a thin router. It owns:

- Editorial decisions (what airs)
- Structural decisions (how it fits the grid)
- EPG truth (what viewers see in the guide)

### What ChannelManager Consumes

ChannelManager is execution-only:

- Consumes already-decided playout plans from ScheduleManager
- Does NOT choose content
- Does NOT alter schedules
- Does NOT know about episodes, series, or play modes

Playout is rendered just-in-time, but decisions are made ahead of time.

---

## Architecture

### Internal Phases (Conceptual, Not Separate Components)

Phase 3 introduces two internal responsibilities within ScheduleManager:

#### Programming Logic (Editorial)

Responsible for:

- Selecting episodes from a series
- Choosing special items (Movie of the Week, marathons, theme nights)
- Applying play modes (sequential, random, manual)
- Producing a stable, deterministic EPG

This logic owns **identity** (what the viewer thinks is on).

#### Traffic Logic (Structural)

Responsible for:

- Expanding EPG entries into playout segments
- Calculating seek offsets for mid-program joins
- Inserting filler segments after program end
- Respecting grid boundaries

This logic owns **clock integrity**, not editorial choice.

**These are internal phases, not separate managers or services.**

### Scheduling Timeline Model

```
EPG Horizon (24-72 hours ahead)
┌─────────────────────────────────────────────────────────────┐
│  Programming Logic runs here                                │
│  Episodes already chosen, identities locked                 │
│  EPG is browsable even with no viewers                      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    Playout Plan Generation
                    (lazy, on-demand)
┌─────────────────────────────────────────────────────────────┐
│  Traffic Logic runs here                                    │
│  Uses already-decided EPG entries                           │
│  Produces PlayoutSegments with seek offsets                 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ChannelManager (execution)
┌─────────────────────────────────────────────────────────────┐
│  Consumes playout plans                                     │
│  No content decisions                                       │
│  Pure execution                                             │
└─────────────────────────────────────────────────────────────┘
```

Key behaviors:

- ScheduleManager continuously builds the EPG horizon (24–72 hours ahead)
- Episodes and movies are already chosen in the EPG
- Playout plans are built lazily, only when ChannelManager needs them
- If no viewers exist: EPG still exists, no playout exists
- When a viewer tunes in: playout is generated immediately from EPG

---

## Data Structures

### ScheduleSlot (Replaces ScheduleEntry)

Phase 3 replaces `ScheduleEntry` with `ScheduleSlot` to distinguish between the **program reference** (what is scheduled) and the **resolved asset** (what will actually air).

```python
@dataclass
class ScheduleSlot:
    """
    A scheduled program slot within a ScheduleDay.

    Phase 3 data structure that references a Program or direct Asset,
    which is then resolved to a specific episode/asset during EPG generation.
    """
    slot_time: time              # Grid-aligned time when this slot starts
    program_ref: ProgramRef      # Reference to Program, Asset, or direct file
    duration_seconds: float      # Duration of the slot
    label: str = ""              # Optional label for debugging/logging
```

### ProgramRef (New)

```python
@dataclass
class ProgramRef:
    """
    Reference to schedulable content.

    Can reference:
    - A Program (series/collection requiring episode selection)
    - A direct Asset (specific movie or special)
    - A literal file path (backward compatibility)
    """
    ref_type: ProgramRefType     # PROGRAM | ASSET | FILE
    ref_id: str                  # Program ID, Asset ID, or file path
```

```python
class ProgramRefType(Enum):
    PROGRAM = "program"   # Requires episode selection
    ASSET = "asset"       # Direct asset reference
    FILE = "file"         # Literal file path (Phase 2 compatibility)
```

### ResolvedSlot (New)

```python
@dataclass
class ResolvedSlot:
    """
    A ScheduleSlot with its content fully resolved.

    Created during EPG generation. The resolved_asset is immutable
    once the EPG is published.
    """
    slot_time: time              # Grid-aligned time
    program_ref: ProgramRef      # Original reference (for display)
    resolved_asset: ResolvedAsset  # The specific asset that will air
    duration_seconds: float      # Duration of the slot
    label: str = ""              # Display label
```

### ResolvedAsset (New)

```python
@dataclass
class ResolvedAsset:
    """
    A fully resolved asset ready for playout.

    Contains both the physical file path and display metadata
    for EPG presentation.
    """
    file_path: str               # Physical file path for playout
    asset_id: str | None         # Asset ID if from catalog

    # EPG display metadata
    title: str                   # Display title (e.g., "Cheers")
    episode_title: str | None    # Episode title (e.g., "Simon Says")
    episode_id: str | None       # Episode identifier (e.g., "S02E05")

    # Content metadata
    content_duration_seconds: float  # Actual duration of content
```

### EPGEvent (New)

```python
@dataclass
class EPGEvent:
    """
    An event in the Electronic Program Guide.

    Represents a resolved, immutable entry in the EPG that viewers
    can browse. Once published, the identity cannot change.
    """
    channel_id: str
    start_time: datetime         # Absolute start time (UTC)
    end_time: datetime           # Absolute end time (UTC)

    # Display information (from ResolvedAsset)
    title: str                   # Program title
    episode_title: str | None    # Episode title (if applicable)
    episode_id: str | None       # Episode identifier (if applicable)

    # Resolution metadata
    resolved_asset: ResolvedAsset  # The resolved asset
    programming_day_date: date     # Which programming day this belongs to
```

### ResolvedScheduleDay (New)

```python
@dataclass
class ResolvedScheduleDay:
    """
    A ScheduleDay with all content resolved to specific assets.

    Created during EPG generation. Once created, the resolved slots
    are immutable—the same episodes will air regardless of when
    playout is requested.
    """
    programming_day_date: date
    resolved_slots: list[ResolvedSlot]  # Ordered by slot_time

    # Resolution metadata
    resolution_timestamp: datetime  # When this day was resolved
    sequence_state: SequenceState   # State snapshot for sequential programs
```

### SequenceState (New)

```python
@dataclass
class SequenceState:
    """
    Snapshot of sequential program positions at resolution time.

    Captures which episode each sequential program was at when
    this ScheduleDay was resolved. Used for deterministic replay
    and debugging.
    """
    positions: dict[str, int]  # program_id -> episode_index
    as_of: datetime            # When this state was captured
```

---

## Episode Selection

### Play Modes

Phase 3 supports three play modes for Programs:

#### Sequential Mode

Episodes play in order, advancing after each scheduled slot.

```
Day 1: Cheers 9pm → S01E01
Day 2: Cheers 9pm → S01E02
Day 3: Cheers 9pm → S01E03
...
```

**State management:**
- SequenceState tracks current position per program
- State advances at **EPG generation time**, not playback time
- State is persisted and deterministic

**Invariant:** If Day 2's EPG shows S01E02, it will always air S01E02 for that slot, even if generated multiple times.

#### Random Mode (Deterministic)

Episodes are selected pseudo-randomly, seeded by schedule context.

```python
seed = hash(channel_id, program_id, programming_day_date, slot_time)
episode = episodes[seed % len(episodes)]
```

**Properties:**
- Same inputs always produce same episode selection
- No viewer-specific randomness
- No runtime state required

**Invariant:** Random selection is reproducible from inputs alone.

#### Manual Mode

Explicit asset references—no selection logic.

```
ScheduleSlot references specific Asset ID directly
```

Used for:
- Movies (specific film scheduled)
- Specials (holiday episode explicitly chosen)
- Operator overrides

### Selection Timing

Episode selection happens during **EPG generation**, not at playout time.

```
EPG Generation (24-72 hours ahead)
├── For each ScheduleSlot in ScheduleDay:
│   ├── If ProgramRef.ref_type == PROGRAM:
│   │   ├── Load Program definition
│   │   ├── Apply play_mode selection logic
│   │   ├── Resolve to specific asset
│   │   └── Create ResolvedSlot with ResolvedAsset
│   ├── If ProgramRef.ref_type == ASSET:
│   │   ├── Load Asset metadata
│   │   └── Create ResolvedSlot with ResolvedAsset
│   └── If ProgramRef.ref_type == FILE:
│       └── Create ResolvedSlot with file path (Phase 2 compat)
└── Store ResolvedScheduleDay
```

### Selection Determinism Guarantee

**INV-P3-001 (Episode Selection Determinism):**
Given the same inputs (ScheduleDay, SequenceState, Program definitions), episode selection MUST produce identical results.

Inputs that affect selection:
- Program ID and play_mode
- Episode list and ordering
- SequenceState (for sequential mode)
- Programming day date and slot time (for random mode seed)

Inputs that MUST NOT affect selection:
- Current wall clock time
- Viewer presence or count
- Previous playout history (only SequenceState at resolution time)
- Random number generators without deterministic seeds

---

## EPG Generation

### EPG Horizon

ScheduleManager maintains an EPG horizon extending 24–72 hours ahead of current time.

```
Now                    EPG Horizon
 │                         │
 ▼                         ▼
 ├─────────────────────────┤
 │  Resolved EPG Events    │
 │  Episodes chosen        │
 │  Identities locked      │
 └─────────────────────────┘
```

### EPG Identity Stability

**INV-P3-002 (EPG Identity Immutability):**
Once an EPGEvent is published (resolved and stored), its identity MUST NOT change.

- Episode selection is final at resolution time
- Re-resolving the same slot MUST produce the same result
- EPG consumers (Prevue channel, guide API) see stable data

### EPG Resolution Process

```
Input: ScheduleDay (from ScheduleSource)
Output: ResolvedScheduleDay with EPGEvents

1. Load current SequenceState for channel
2. For each ScheduleSlot:
   a. Resolve ProgramRef to ResolvedAsset
   b. If sequential: use and advance SequenceState
   c. If random: compute deterministic selection
   d. Create ResolvedSlot
3. Store ResolvedScheduleDay
4. Persist updated SequenceState
5. Generate EPGEvents for guide consumption
```

### Lazy Playout Generation

Playout plans are generated on-demand from resolved EPG:

```
Input: ResolvedScheduleDay, query_time
Output: ProgramBlock with PlayoutSegments

1. Find ResolvedSlot containing query_time
2. Apply Traffic Logic:
   a. Calculate segment boundaries
   b. Compute seek offsets for mid-program join
   c. Add filler segments if needed
3. Return ProgramBlock (unchanged from Phase 2)
```

**Key distinction:**
- EPG resolution: happens ahead of time, selects episodes
- Playout generation: happens on-demand, calculates offsets

---

## Internal Resolution Boundary

ScheduleManager operates in two distinct passes with a hard boundary between them:

### Editorial Resolution Pass

Produces identity-complete EPG artifacts:

- Resolves ProgramRefs to specific episodes/assets
- Advances SequenceState for sequential programs
- Creates ResolvedScheduleDay with immutable episode identities
- Generates EPGEvents for guide consumption

**Output:** "What is on" — complete identity information.

### Structural Expansion Pass

Produces time-accurate playout artifacts:

- Calculates grid-aligned segment boundaries
- Computes seek offsets for mid-program joins
- Inserts filler segments after content ends
- Returns ProgramBlock with PlayoutSegments

**Output:** "How to play it" — execution instructions.

### The Hard Rule

**No editorial decisions are permitted after the Editorial Resolution Pass.**

The Structural Expansion Pass receives resolved identities as input. It may calculate timing, offsets, and filler, but it MUST NOT:

- Select or change episodes
- Modify EPG identity
- Advance sequential state
- Re-resolve ProgramRefs

This separation is critical because identity drift is catastrophic in broadcast systems. A viewer checking the guide must see exactly what will air—no exceptions.

---

## Invariants

### Phase 3 Invariants

| ID | Invariant | Rationale |
|----|-----------|-----------|
| INV-P3-001 | Episode Selection Determinism | Same inputs → same episode, always |
| INV-P3-002 | EPG Identity Immutability | Published EPG cannot change |
| INV-P3-003 | Resolution Independence | EPG exists even with no viewers |
| INV-P3-004 | Sequential State Isolation | State advances only at resolution time |
| INV-P3-005 | No Playback-Time Decisions | All content decisions made in EPG |
| INV-P3-008 | Resolution Idempotence | Resolve at most once per (channel, day) |
| INV-P3-009 | Content Duration Supremacy | Actual content duration governs playout |
| INV-P3-010 | Playout Is a Pure Projection | Playout artifacts are derivable and disposable |

### Inherited Invariants (Phase 0–2)

All previous invariants remain in force:

- INV-001: Grid Alignment
- INV-002: Segment Coverage
- INV-003: Deterministic Results
- INV-004: No System Clock Access
- INV-P1-001 through INV-P1-005 (multi-slot, cross-day, etc.)
- INV-P2-001 through INV-P2-005 (day-specific resolution, etc.)

### INV-P3-008: Resolution Idempotence

**A given (channel_id, programming_day_date) MUST be resolved at most once.**

Repeated resolution attempts MUST return the previously resolved ResolvedScheduleDay and MUST NOT re-run episode selection or advance state.

```
First call:  resolve(channel-1, 2025-01-30) → resolves, stores, returns ResolvedScheduleDay
Second call: resolve(channel-1, 2025-01-30) → returns stored ResolvedScheduleDay (no re-resolution)
```

This invariant prevents:

- Double-bumping the sequential episode counter
- Split-brain EPG identity if horizon rebuild logic is refactored
- Accidental state drift from retry logic or caching bugs

Implementation pattern: Check for existing ResolvedScheduleDay before resolving. If found, return it unchanged.

### INV-P3-009: Content Duration Supremacy

**Actual content duration (ResolvedAsset.content_duration_seconds) is authoritative for playout continuity.**

When slot duration and content duration disagree:

| Scenario | Behavior |
|----------|----------|
| Content shorter than slot | Content plays fully, filler fills remainder |
| Content longer than slot | Content plays fully, extends into subsequent slots |
| Content spans multiple slots | Same episode continues across slot boundaries |

Slot duration defines **scheduling intent**, not truncation behavior. Programs are never truncated mid-content.

```
Slot: 30 minutes
Episode: 22 minutes
Result: 22 min episode + 8 min filler

Slot: 30 minutes
Movie: 102 minutes
Result: Movie spans 4 slots, ends at natural duration
```

This matters when:

- Asset metadata is incorrect (discovered at playout time)
- Content has variable duration (live-to-tape, sports overruns)
- Ads/promos are added in later phases

### INV-P3-010: Playout Is a Pure Projection

**Playout artifacts are derivable, disposable projections of resolved schedule state.**

Deleting all playout data MUST NOT affect:

- EPG identity (what episode was scheduled)
- Episode selection (which episode was chosen)
- SequenceState (where sequential programs are in their rotation)

```
State that survives playout deletion:
├── ResolvedScheduleDay (immutable)
├── EPGEvents (immutable)
└── SequenceState (persistent)

State that can be regenerated:
└── ProgramBlock / PlayoutSegments (derivable from resolved state)
```

This protects against:

- Process restarts (playout regenerated from EPG)
- Scaling scenarios (multiple workers derive same playout)
- Multi-viewer fanout (same content, different connection state)
- Future "rewind channel" features (regenerate past playout)

The identity layer (EPG) is permanent. The execution layer (playout) is ephemeral and reproducible.

---

## Multi-Slot Episode Behavior

### Single Episode Across Multiple Slots

When a program's content duration exceeds one grid slot, the **same episode** spans multiple slots:

```
21:00 slot: Movie of the Week → "Casablanca" (starts)
21:30 slot: Movie of the Week → "Casablanca" (continues)
22:00 slot: Movie of the Week → "Casablanca" (continues)
22:30 slot: Movie of the Week → "Casablanca" (ends at 22:42)
            Filler until 23:00
```

**INV-P3-006 (Multi-Slot Episode Continuity):**
A single episode spanning multiple grid slots MUST be represented as the same ResolvedAsset in each slot's ResolvedSlot.

### EPG Representation

EPG displays multi-slot episodes as a single event:

```
EPGEvent:
  start_time: 21:00
  end_time: 22:42  (actual content end, not grid boundary)
  title: "Movie of the Week"
  episode_title: "Casablanca"
```

Traffic Logic handles the grid alignment; EPG shows viewer-facing reality.

---

## Cross-Day Episode Continuation

### Episode Spanning Programming Day Boundary

When an episode starts before `programming_day_start` and continues past it:

```
Programming Day A (ends at 06:00):
  05:30 slot: Late Night Movie → "2001: A Space Odyssey" (starts)

Programming Day B (starts at 06:00):
  06:00 slot: Late Night Movie → "2001: A Space Odyssey" (continues)
  06:30 slot: Late Night Movie → "2001: A Space Odyssey" (continues)
  07:00 slot: (next program)
```

**INV-P3-007 (Cross-Day Episode Identity):**
An episode spanning the programming day boundary MUST maintain the same identity in both days' EPG. The episode is resolved once (in Day A) and referenced in Day B.

### Resolution Order

Cross-day episodes require resolving programming days in order:

1. Resolve Day A → selects "2001: A Space Odyssey"
2. Resolve Day B → detects cross-day continuation from Day A
3. Day B's early slots reference Day A's resolved episode

---

## Sequence State Management

### State Structure

```python
@dataclass
class ChannelSequenceState:
    """
    Persistent state for sequential programs on a channel.
    """
    channel_id: str
    program_positions: dict[str, ProgramPosition]
    last_updated: datetime

@dataclass
class ProgramPosition:
    """
    Current position in a sequential program.
    """
    program_id: str
    episode_index: int          # 0-based index into episode list
    last_scheduled_date: date   # Last programming day this advanced
```

### State Advancement Rules

**INV-P3-004 (Sequential State Isolation):**
Sequential program state advances ONLY during EPG resolution, never during playout.

```
EPG Resolution for Day N:
1. Load ChannelSequenceState
2. For each sequential program slot:
   a. Get current episode_index
   b. Select episode at that index
   c. Increment episode_index for next slot
3. Persist updated ChannelSequenceState

Playout (anytime):
1. Read ResolvedScheduleDay
2. Episode already chosen - use it
3. DO NOT modify SequenceState
```

### State Determinism

If EPG resolution is re-run for the same day:
- Load SequenceState as it was before that day's resolution
- Produce identical episode selections
- State changes are idempotent per programming day

---

## ScheduleManager Protocol (Phase 3)

The public interface remains unchanged from Phase 2:

```python
class ScheduleManager(Protocol):
    def get_program_at(self, channel_id: str, at_time: datetime) -> ProgramBlock:
        """Get the program block containing the specified time."""
        ...

    def get_next_program(self, channel_id: str, after_time: datetime) -> ProgramBlock:
        """Get the next program block after the specified time."""
        ...
```

### Internal Flow (Phase 3)

```
get_program_at(channel_id, at_time)
│
├── Determine programming_day_date from at_time
├── Get or generate ResolvedScheduleDay
│   ├── If cached/stored: return existing
│   └── If not: resolve ScheduleDay → ResolvedScheduleDay
├── Find ResolvedSlot containing at_time
├── Apply Traffic Logic:
│   ├── Calculate block boundaries
│   ├── Compute seek offset
│   └── Generate filler segments
└── Return ProgramBlock with PlayoutSegments
```

### EPG Query Interface (New)

Phase 3 adds EPG query capability:

```python
class EPGProvider(Protocol):
    def get_epg_events(
        self,
        channel_id: str,
        start_time: datetime,
        end_time: datetime
    ) -> list[EPGEvent]:
        """
        Get EPG events for the specified time range.

        Returns resolved events with episode information.
        Events are immutable once returned.
        """
        ...
```

This interface serves EPG consumers (Prevue channel, guide API) with resolved content.

---

## Test Specifications

### Episode Selection Tests

#### P3-T001: Sequential Episode Selection

```
GIVEN: Program "Cheers" with play_mode="sequential", episodes [E01, E02, E03]
       SequenceState.positions["cheers"] = 0
WHEN:  EPG resolves Day 1 with Cheers at 21:00
THEN:  ResolvedSlot.resolved_asset references E01
       SequenceState.positions["cheers"] = 1
```

#### P3-T002: Sequential Advancement Across Days

```
GIVEN: Program "Cheers" with sequential episodes
       Day 1 resolved with E01
       SequenceState.positions["cheers"] = 1
WHEN:  EPG resolves Day 2 with Cheers at 21:00
THEN:  ResolvedSlot.resolved_asset references E02
       SequenceState.positions["cheers"] = 2
```

#### P3-T003: Sequential Wrap-Around

```
GIVEN: Program "Cheers" with 3 episodes
       SequenceState.positions["cheers"] = 2 (at last episode)
WHEN:  EPG resolves next day with Cheers at 21:00
THEN:  ResolvedSlot.resolved_asset references E01 (wrapped)
       SequenceState.positions["cheers"] = 0
```

#### P3-T004: Random Selection Determinism

```
GIVEN: Program "Cartoons" with play_mode="random", episodes [A, B, C, D]
WHEN:  EPG resolves channel-1, 2025-01-30, 09:00 slot twice
THEN:  Both resolutions produce identical episode selection
```

#### P3-T005: Random Selection Varies By Day

```
GIVEN: Program "Cartoons" with play_mode="random"
WHEN:  EPG resolves 2025-01-30 and 2025-01-31 for same slot time
THEN:  Different episodes selected (different seeds)
```

#### P3-T006: Manual Mode Direct Reference

```
GIVEN: ScheduleSlot with ProgramRef(ASSET, "casablanca-id")
WHEN:  EPG resolves slot
THEN:  ResolvedAsset.asset_id == "casablanca-id"
       No episode selection logic invoked
```

### EPG Identity Tests

#### P3-T007: EPG Identity Immutability

```
GIVEN: ResolvedScheduleDay for 2025-01-30 with Cheers → E05
WHEN:  get_epg_events() called multiple times
THEN:  All calls return E05 for that slot
       Identity never changes
```

#### P3-T008: EPG Exists Without Viewers

```
GIVEN: Channel with no active viewers
WHEN:  get_epg_events() called for tomorrow
THEN:  Returns resolved EPGEvents with episode information
       No playout infrastructure required
```

#### P3-T009: Playout Matches EPG

```
GIVEN: EPGEvent shows "Cheers S02E05" at 21:00
WHEN:  Viewer tunes in at 21:15
THEN:  get_program_at() returns PlayoutSegment for S02E05
       seek_offset = 15 minutes
```

### Multi-Slot Episode Tests

#### P3-T010: Movie Spans Multiple Slots

```
GIVEN: Movie (102 min) scheduled at 20:00 in 30-min grid
WHEN:  EPG resolves 20:00, 20:30, 21:00, 21:30 slots
THEN:  All four ResolvedSlots reference same movie
       EPGEvent shows single event 20:00-21:42
```

#### P3-T011: Multi-Slot Seek Offsets

```
GIVEN: Movie (102 min) starting at 20:00
WHEN:  get_program_at() called at 21:15
THEN:  PlayoutSegment.file_path = movie file
       PlayoutSegment.seek_offset_seconds = 4500 (75 min)
```

### Cross-Day Episode Tests

#### P3-T012: Episode Spans Programming Day Boundary

```
GIVEN: Late movie (180 min) at 05:00, programming_day_start = 06:00
WHEN:  EPG resolves Day A (05:00 slot) and Day B (06:00, 06:30, 07:00 slots)
THEN:  Day A 05:00 slot: movie starts
       Day B 06:00 slot: same movie continues
       Day B 06:30 slot: same movie continues
       Same ResolvedAsset in all slots
```

#### P3-T013: Cross-Day Sequential State

```
GIVEN: Sequential program scheduled in Day A and Day B
       Day A ends mid-episode
WHEN:  Day B resolves
THEN:  SequenceState reflects Day A's advancement
       Day B continues from correct position
```

### State Isolation Tests

#### P3-T014: Playout Does Not Advance State

```
GIVEN: Sequential program with SequenceState.positions["show"] = 5
WHEN:  get_program_at() called 100 times for that slot
THEN:  SequenceState.positions["show"] still = 5
       No state mutation during playout
```

#### P3-T015: State Advances Only At Resolution

```
GIVEN: Sequential program, SequenceState.positions["show"] = 0
WHEN:  resolve_schedule_day() called for Day 1 with 2 slots of "show"
THEN:  SequenceState.positions["show"] = 2
       Both slots resolved before state persisted
```

### Backward Compatibility Tests

#### P3-T016: FILE ProgramRef Compatibility

```
GIVEN: ScheduleSlot with ProgramRef(FILE, "/media/show.mp4")
WHEN:  EPG resolves slot
THEN:  ResolvedAsset.file_path = "/media/show.mp4"
       Behavior identical to Phase 2
```

#### P3-T017: Phase 2 Invariants Preserved

```
GIVEN: Phase 3 ScheduleManager with Phase 2-style ScheduleDay
WHEN:  All Phase 2 tests executed
THEN:  All tests pass unchanged
```

### Resolution Idempotence Tests (INV-P3-008)

#### P3-T018: Double Resolution Returns Same Result

```
GIVEN: ScheduleDay for channel-1, 2025-01-30 with sequential Program
WHEN:  resolve_schedule_day() called twice for same (channel, day)
THEN:  Second call returns identical ResolvedScheduleDay
       SequenceState NOT advanced on second call
       Episode identities identical
```

#### P3-T019: Horizon Rebuild Does Not Re-Resolve

```
GIVEN: ResolvedScheduleDay exists for 2025-01-30
       SequenceState.positions["show"] = 5
WHEN:  EPG horizon rebuild triggered (system restart, etc.)
THEN:  Existing ResolvedScheduleDay returned
       SequenceState.positions["show"] still = 5
       No episode re-selection
```

#### P3-T020: Concurrent Resolution Requests

```
GIVEN: No ResolvedScheduleDay for 2025-01-30
WHEN:  Two concurrent resolve requests for same (channel, day)
THEN:  Exactly one resolution executes
       Both requests return same ResolvedScheduleDay
       SequenceState advanced exactly once
```

### Duration Authority Tests (INV-P3-009)

#### P3-T021: Content Shorter Than Slot

```
GIVEN: Slot duration = 30 min, Episode duration = 22 min
WHEN:  Playout generated for slot
THEN:  Episode segment: 0-22 min
       Filler segment: 22-30 min
       Episode NOT stretched or looped
```

#### P3-T022: Content Longer Than Slot

```
GIVEN: Slot duration = 30 min, Movie duration = 102 min
WHEN:  Playout generated for first slot
THEN:  Movie segment: 0-30 min (continues into next slots)
       No truncation
       Filler only after movie ends (at 102 min mark)
```

#### P3-T023: Content Duration Wins Over Slot Metadata

```
GIVEN: Slot says 30 min, Asset metadata says 25 min
       Actual file duration = 27 min
WHEN:  Playout generated
THEN:  content_duration_seconds = 27 min used for segments
       Filler from 27-30 min
```

### Playout Projection Tests (INV-P3-010)

#### P3-T024: Playout Regeneration After Discard

```
GIVEN: ResolvedScheduleDay for 2025-01-30 with "Cheers S02E05"
       Playout generated at 21:15
WHEN:  All playout artifacts deleted
       Playout regenerated at 21:20
THEN:  Same episode (S02E05) returned
       seek_offset = 20 min (correct for new time)
       EPG unchanged
```

#### P3-T025: Multiple Playout Derivations Match

```
GIVEN: ResolvedScheduleDay with movie at 20:00
WHEN:  get_program_at() called by viewer A at 20:15
       get_program_at() called by viewer B at 20:45
THEN:  Both return same movie
       Viewer A: seek_offset = 15 min
       Viewer B: seek_offset = 45 min
       Same ResolvedAsset referenced
```

#### P3-T026: EPG Survives Playout Layer Restart

```
GIVEN: ScheduleManager with resolved EPG for next 48 hours
WHEN:  Playout subsystem restarted (simulated crash)
       get_epg_events() called
THEN:  All EPGEvents returned unchanged
       Episode identities preserved
       SequenceState unchanged
       Playout regenerable from EPG
```

---

## Glossary

### New Terms (Phase 3)

| Term | Definition |
|------|------------|
| **ScheduleSlot** | A scheduled time slot referencing a Program or Asset (replaces ScheduleEntry) |
| **ProgramRef** | Reference to schedulable content (Program, Asset, or file path) |
| **ResolvedSlot** | A ScheduleSlot with content resolved to a specific asset |
| **ResolvedAsset** | Fully resolved asset with file path and EPG metadata |
| **EPGEvent** | Immutable entry in the Electronic Program Guide |
| **ResolvedScheduleDay** | A ScheduleDay with all content resolved |
| **SequenceState** | Persistent state tracking sequential program positions |
| **Programming Logic** | Internal phase handling editorial decisions (episode selection) |
| **Traffic Logic** | Internal phase handling structural decisions (segments, offsets) |
| **Editorial Resolution Pass** | First pass: produces identity-complete EPG artifacts |
| **Structural Expansion Pass** | Second pass: produces time-accurate playout artifacts |
| **Resolution Idempotence** | Property that re-resolving same (channel, day) returns cached result |
| **Content Duration Supremacy** | Actual content duration governs playout, not slot duration |

### Clarifications

| Term | Phase 2 Meaning | Phase 3 Meaning |
|------|-----------------|-----------------|
| **ScheduleEntry** | Slot with file_path | Deprecated, use ScheduleSlot |
| **file_path** | Direct reference | May come from ResolvedAsset |
| **Episode** | N/A | Specific content instance from a series |
| **Play Mode** | N/A | Selection strategy (sequential/random/manual) |

### Conceptual Distinctions

| Concept | Definition | Example |
|---------|------------|---------|
| **Program Identity** | What the viewer thinks is on | "Cheers" |
| **Episode Identity** | Which specific content | "S02E05 - Simon Says" |
| **Asset Identity** | Physical file reference | "/media/cheers/s02e05.mp4" |
| **EPG Event** | Viewer-facing guide entry | "Cheers - Simon Says, 9:00-9:30pm" |
| **Playout Segment** | Execution instruction | file + seek_offset + timing |

---

## Design Validation

### The Litmus Test

> "Could a viewer browse the EPG for tomorrow and see the exact episode that will air — even if nobody tunes in?"

**Answer: YES**

- EPG is generated 24–72 hours ahead
- Episode selection happens at EPG generation time
- ResolvedScheduleDay stores immutable episode choices
- get_epg_events() returns resolved content without playout
- Viewers see "Cheers S02E05" in the guide, guaranteed to air

### What This Design Avoids

- ❌ Separate PlaylistGenerator manager
- ❌ Episode logic in ChannelManager
- ❌ Assets decided at playback time
- ❌ Viewer-specific randomness
- ❌ Caching or background workers for content decisions
- ❌ Mutable EPG entries

### What This Design Enables

- ✅ Deterministic, reproducible schedules
- ✅ Stateless playout generation (from resolved EPG)
- ✅ EPG available before any playout
- ✅ Sequential progression across days
- ✅ Consistent identity across EPG, Prevue, and playout

---

## Migration Path

### Phase 2 → Phase 3

1. **ScheduleEntry → ScheduleSlot**: Add ProgramRef wrapper around file_path
2. **ScheduleDay → uses ScheduleSlot**: Update data structure
3. **Add ResolvedScheduleDay**: New resolution layer
4. **Add SequenceState**: Persistence for sequential programs
5. **Add EPGEvent generation**: New query interface

### Backward Compatibility

- `ProgramRef(FILE, path)` preserves Phase 2 behavior exactly
- Existing tests continue to pass with FILE refs
- Phase 3 features are additive, not breaking

---

## Dependencies

### Required Before Phase 3

- Program entity in database (with play_mode, episode list)
- Asset catalog with episode metadata
- SequenceState persistence mechanism

### Interfaces Phase 3 Provides

- `EPGProvider.get_epg_events()` for guide consumption
- Unchanged `ScheduleManager.get_program_at()` for playout

---

## Non-Goals (Deferred to Later Phases)

| Feature | Deferred To | Rationale |
|---------|-------------|-----------|
| Ad pod insertion | Phase N | Separate concern from content selection |
| Promo scheduling | Phase N | Requires inventory management |
| Soft transitions | Phase N | Affects Traffic Logic only |
| Live content | Phase N | Different resolution model |
| DVR/catch-up | Phase N | Viewer-specific, breaks EPG model |
