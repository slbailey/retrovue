# Schedule Manager Contract - Phase 4: Demonstration and Validation

Status: Design (pre-implementation)

**Extends:** [ScheduleManagerPhase3Contract.md](ScheduleManagerPhase3Contract.md)

---

## Purpose

### What Phase 4 Is

Phase 4 is a **demonstration and validation phase**. It proves that the Phase 3 architecture produces believable linear TV behavior using real episode durations, without introducing any new runtime responsibilities.

Phase 4 answers: "Does this architecture work with real durations?"

Phase 4 does NOT answer: "How do we discover assets?"

### What Phase 4 Is NOT

Phase 4 is NOT a new scheduling feature layer. It introduces:

- No new managers
- No new runtime responsibilities
- No asset scanning or discovery
- No ffprobe at runtime
- No heuristics or shortcuts

### Why Phase 4 Exists

Phase 3 defined episode selection and EPG resolution. But Phase 3 tests used synthetic durations (e.g., "1320 seconds") without proving the system handles real TV content correctly.

Phase 4 proves:

- EPG grid alignment works with non-grid-aligned content
- Filler insertion handles real episode lengths (22-24 min episodes in 30-min slots)
- Sequential looping works across a full broadcast day
- seek_offset calculations are correct for mid-episode joins

---

## Scope

### What Phase 4 Adds

1. **Static Asset Metadata Fixtures** — JSON files containing real episode metadata (durations, identities, file paths), generated once and committed to the repo.

2. **Fixture-Based Test Scenario** — A minimal, human-observable example using the Cheers series with real episode durations.

3. **Validation Tests** — Tests proving EPG→playout→offset→filler correctness.

### What Phase 4 Does NOT Add

| Non-Goal | Rationale |
|----------|-----------|
| Asset scanning/discovery | Phase 4 uses static fixtures only |
| Runtime ffprobe | Violates no-runtime-probing rule |
| Asset Library implementation | Future concern, not Phase 4 |
| New ScheduleManager responsibilities | Phase 4 is validation, not behavior |
| Ad pods or promos | Phase N concern |
| Live content | Different resolution model |
| Viewer-specific behavior | Violates Phase 3 invariants |
| Background jobs or workers | Phase 4 is synchronous and deterministic |

---

## Core Constraints (Non-Negotiable)

### ScheduleManager Runtime Restrictions

ScheduleManager MUST NOT:

- ffprobe files at runtime
- Inspect media files
- Infer durations dynamically
- Depend on filesystem media access
- Perform asset discovery

All content metadata MUST come from static fixtures that simulate Asset Library responses.

### Phase 3 Invariants Remain in Force

All Phase 3 invariants are preserved:

| Invariant | Status |
|-----------|--------|
| INV-P3-001: Episode Selection Determinism | Unchanged |
| INV-P3-002: EPG Identity Immutability | Unchanged |
| INV-P3-003: Resolution Independence | Unchanged |
| INV-P3-004: Sequential State Isolation | Unchanged |
| INV-P3-005: No Playback-Time Decisions | Unchanged |
| INV-P3-006: Multi-Slot Episode Continuity | Unchanged |
| INV-P3-007: Cross-Day Episode Identity | Unchanged |
| INV-P3-008: Resolution Idempotence | Unchanged |
| INV-P3-009: Content Duration Supremacy | Unchanged |
| INV-P3-010: Playout Is a Pure Projection | Unchanged |

### EPG Grid Alignment Rule

**EPG output ALWAYS snaps to grid boundaries.**

- EPG does NOT reflect natural episode end times
- EPG shows scheduling intent, not execution detail
- Filler is invisible in EPG, visible only in playout

Example:
```
Episode: Cheers S01E01 (22:34 actual runtime)
Grid: 30 minutes
EPG shows: 09:00–09:30 "Cheers S01E01"
Playout: Episode 09:00–09:22:34, Filler 09:22:34–09:30:00
```

---

## Asset Metadata Fixtures

### Fixture Boundary

Phase 4 introduces a clear **fixture boundary**:

```
┌─────────────────────────────────────────────────────────────────┐
│                    DATA AUTHORING (one-time)                    │
│                                                                 │
│   ffprobe → JSON fixtures → committed to repo                   │
│                                                                 │
│   This is NOT runtime. This is data preparation.                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    RUNTIME (Phase 4 tests)                      │
│                                                                 │
│   JSON fixtures loaded as ProgramCatalog                        │
│   ScheduleManager treats fixtures as authoritative truth        │
│   No file inspection occurs                                     │
└─────────────────────────────────────────────────────────────────┘
```

### JSON Schema for Asset Metadata

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Phase4AssetMetadata",
  "type": "object",
  "properties": {
    "version": {
      "type": "string",
      "description": "Schema version",
      "const": "1.0"
    },
    "generated_at": {
      "type": "string",
      "format": "date-time",
      "description": "When this fixture was generated"
    },
    "programs": {
      "type": "array",
      "items": {
        "$ref": "#/definitions/Program"
      }
    }
  },
  "required": ["version", "programs"],
  "definitions": {
    "Program": {
      "type": "object",
      "properties": {
        "program_id": {
          "type": "string",
          "description": "Unique program identifier"
        },
        "name": {
          "type": "string",
          "description": "Display name for EPG"
        },
        "play_mode": {
          "type": "string",
          "enum": ["sequential", "random", "manual"]
        },
        "episodes": {
          "type": "array",
          "items": {
            "$ref": "#/definitions/Episode"
          }
        }
      },
      "required": ["program_id", "name", "play_mode", "episodes"]
    },
    "Episode": {
      "type": "object",
      "properties": {
        "episode_id": {
          "type": "string",
          "description": "Unique episode identifier (e.g., 'cheers-s01e01')"
        },
        "title": {
          "type": "string",
          "description": "Episode title for EPG display"
        },
        "file_path": {
          "type": "string",
          "description": "Path to media file (may be placeholder for testing)"
        },
        "duration_seconds": {
          "type": "number",
          "description": "Actual episode duration from ffprobe"
        },
        "season": {
          "type": "integer",
          "description": "Season number"
        },
        "episode_number": {
          "type": "integer",
          "description": "Episode number within season"
        }
      },
      "required": ["episode_id", "title", "file_path", "duration_seconds"]
    }
  }
}
```

### Sample Fixture: cheers_episodes.json

```json
{
  "version": "1.0",
  "generated_at": "2025-01-30T12:00:00Z",
  "programs": [
    {
      "program_id": "cheers",
      "name": "Cheers",
      "play_mode": "sequential",
      "episodes": [
        {
          "episode_id": "cheers-s01e01",
          "title": "Give Me a Ring Sometime",
          "file_path": "/media/cheers/s01e01.mp4",
          "duration_seconds": 1354.0,
          "season": 1,
          "episode_number": 1
        },
        {
          "episode_id": "cheers-s01e02",
          "title": "Sam's Women",
          "file_path": "/media/cheers/s01e02.mp4",
          "duration_seconds": 1342.0,
          "season": 1,
          "episode_number": 2
        },
        {
          "episode_id": "cheers-s01e03",
          "title": "The Tortelli Tort",
          "file_path": "/media/cheers/s01e03.mp4",
          "duration_seconds": 1368.0,
          "season": 1,
          "episode_number": 3
        }
      ]
    }
  ]
}
```

Note: `duration_seconds` values are illustrative. Real values would come from one-time ffprobe.

### Mapping to Phase 3 Types

| JSON Field | Phase 3 Type | Field |
|------------|--------------|-------|
| `program_id` | `Program` | `program_id` |
| `name` | `Program` | `name` |
| `play_mode` | `Program` | `play_mode` |
| `episode_id` | `Episode` | `episode_id` |
| `title` | `Episode` | `title` |
| `file_path` | `Episode` | `file_path` |
| `duration_seconds` | `Episode` | `duration_seconds` |

### Fixture Loading

Tests load fixtures via a `FixtureProgramCatalog`:

```python
class FixtureProgramCatalog:
    """ProgramCatalog implementation that loads from JSON fixtures."""

    def __init__(self, fixture_path: str):
        with open(fixture_path) as f:
            data = json.load(f)
        self._programs = {
            p["program_id"]: self._parse_program(p)
            for p in data["programs"]
        }

    def get_program(self, program_id: str) -> Program | None:
        return self._programs.get(program_id)
```

---

## Test Scenario

### Configuration

| Parameter | Value |
|-----------|-------|
| Channel | `cheers-24-7` |
| Program | Cheers (sequential) |
| Episodes | S01E01, S01E02, S01E03 |
| Grid size | 30 minutes |
| Programming day start | 06:00 |
| Test duration | 24 hours |

### Episode Durations (Illustrative)

| Episode | Duration | In Slot | Filler |
|---------|----------|---------|--------|
| S01E01 | 22:34 (1354s) | 30:00 | 7:26 |
| S01E02 | 22:22 (1342s) | 30:00 | 7:38 |
| S01E03 | 22:48 (1368s) | 30:00 | 7:12 |

### 24-Hour Schedule

Starting at 06:00:

| Time | EPG Shows | Episode Playing | Filler After |
|------|-----------|-----------------|--------------|
| 06:00–06:30 | Cheers S01E01 | S01E01 | 06:22:34–06:30:00 |
| 06:30–07:00 | Cheers S01E02 | S01E02 | 06:52:22–07:00:00 |
| 07:00–07:30 | Cheers S01E03 | S01E03 | 07:22:48–07:30:00 |
| 07:30–08:00 | Cheers S01E01 | S01E01 (loop) | 07:52:34–08:00:00 |
| ... | ... | ... | ... |

The pattern repeats every 90 minutes (3 episodes × 30 min slots).

### Looping Behavior

- After S01E03 at slot N, S01E01 plays at slot N+1
- SequenceState wraps: 0 → 1 → 2 → 0 → 1 → 2 → ...
- Loop is seamless and deterministic

---

## Test Specifications

### EPG Grid Alignment Tests

#### P4-T001: EPG Shows Grid-Aligned Times Only

```
GIVEN: Cheers S01E01 with duration 1354s (22:34)
       Grid size 30 minutes
WHEN:  EPG resolved for 06:00 slot
THEN:  EPGEvent.start_time = 06:00:00
       EPGEvent.end_time = 06:30:00
       NOT 06:22:34
```

#### P4-T002: EPG Does Not Expose Filler

```
GIVEN: Resolved schedule for 06:00–07:00
WHEN:  get_epg_events() called
THEN:  Returns 2 events (S01E01, S01E02)
       No filler events in EPG
       Each event spans exactly one grid slot
```

### Episode Continuity Tests

#### P4-T003: Sequential Episodes Progress Correctly

```
GIVEN: Cheers with 3 episodes, sequential mode
WHEN:  Schedule resolved for 48 slots (24 hours)
THEN:  Slot 0: S01E01
       Slot 1: S01E02
       Slot 2: S01E03
       Slot 3: S01E01 (loop)
       Slot 4: S01E02
       ...
```

#### P4-T004: Episode Identity Matches EPG

```
GIVEN: EPG shows S01E02 at 06:30
WHEN:  get_program_at() called at 06:42
THEN:  PlayoutSegment.file_path = cheers/s01e02.mp4
       Episode identity matches EPG exactly
```

### Filler Insertion Tests

#### P4-T005: Filler Appears After Episode End

```
GIVEN: S01E01 duration 1354s, slot duration 1800s
WHEN:  get_program_at() called at 06:00
THEN:  Segment 1: S01E01, 06:00:00–06:22:34
       Segment 2: Filler, 06:22:34–06:30:00
```

#### P4-T006: Filler Duration Correct

```
GIVEN: S01E01 duration 1354s, slot 1800s
WHEN:  Playout segments generated
THEN:  Filler duration = 1800 - 1354 = 446s (7:26)
```

#### P4-T007: No Filler When Episode Fills Slot

```
GIVEN: Hypothetical episode with duration 1800s exactly
WHEN:  Playout segments generated
THEN:  Single segment, no filler
```

### Seek Offset Tests

#### P4-T008: Mid-Episode Join Correct Offset

```
GIVEN: S01E02 starts at 06:30:00
WHEN:  Viewer joins at 06:42:00
THEN:  seek_offset = 720s (12 minutes)
       Playback starts at correct position in episode
```

#### P4-T009: Join During Filler

```
GIVEN: S01E01 ends at 06:22:34, filler until 06:30:00
WHEN:  Viewer joins at 06:25:00
THEN:  Playing filler
       seek_offset into filler = 146s (06:25:00 - 06:22:34)
```

#### P4-T010: Join At Exact Slot Boundary

```
GIVEN: New slot starts at 06:30:00
WHEN:  Viewer joins at exactly 06:30:00
THEN:  seek_offset = 0
       S01E02 starts from beginning
```

### Looping Behavior Tests

#### P4-T011: Sequential Loop After Last Episode

```
GIVEN: SequenceState at position 2 (S01E03)
WHEN:  Next slot resolved
THEN:  S01E01 selected (wrapped to position 0)
       SequenceState.positions["cheers"] = 0
```

#### P4-T012: 24-Hour Continuous Loop

```
GIVEN: 48 slots (24 hours) resolved
WHEN:  All slots examined
THEN:  Episodes cycle: E01,E02,E03,E01,E02,E03,...
       16 complete cycles (48 / 3 = 16)
       No gaps or discontinuities
```

#### P4-T013: Loop Determinism

```
GIVEN: Same starting state
WHEN:  24-hour schedule resolved twice
THEN:  Identical episode sequence both times
       Same slot → same episode, always
```

### Integration Tests

#### P4-T014: The Litmus Test

```
GIVEN: EPG shows Cheers S01E02 at 09:30
WHEN:  Human tunes in at 09:42
THEN:  Episode playing IS S01E02
       seek_offset IS correct (720s)
       Filler appears only after 09:52:22
       No asset selection occurs at playback time
```

#### P4-T015: Full Day Validation

```
GIVEN: Complete 24-hour schedule resolved
WHEN:  Random times sampled across the day
THEN:  Each sample:
       - EPG identity matches playout
       - seek_offset correct for sample time
       - Filler only after episode end
       - No identity drift
```

---

## Phase 4 Invariants

Phase 4 introduces no new invariants. It validates existing Phase 3 invariants with real data.

| ID | Validation Target |
|----|-------------------|
| INV-P3-001 | Same fixtures → same schedule (determinism) |
| INV-P3-002 | EPG shows same episodes after re-query (immutability) |
| INV-P3-004 | State advances only during resolution (isolation) |
| INV-P3-008 | Re-resolving same day returns cached result (idempotence) |
| INV-P3-009 | Real durations used for playout, grid for EPG (supremacy) |
| INV-P3-010 | Playout derivable from EPG at any time (projection) |

---

## Implementation Notes

### Fixture Generation (One-Time)

To generate fixtures from real media:

```bash
# NOT part of runtime - data authoring only
ffprobe -v quiet -print_format json -show_format /path/to/episode.mp4 \
  | jq '{duration_seconds: .format.duration | tonumber}'
```

This is run once per episode. Output is manually assembled into the fixture JSON and committed to the repo.

### Test Structure

```
pkg/core/tests/
  fixtures/
    phase4/
      cheers_episodes.json
  contracts/
    test_schedule_manager_phase4_contract.py
```

### FixtureProgramCatalog

```python
class FixtureProgramCatalog:
    """
    ProgramCatalog that loads from JSON fixtures.

    Simulates Asset Library response for Phase 4 testing.
    No runtime file inspection occurs.
    """

    @classmethod
    def from_json_file(cls, path: str) -> "FixtureProgramCatalog":
        with open(path) as f:
            return cls(json.load(f))

    def __init__(self, data: dict):
        self._programs = {}
        for p in data.get("programs", []):
            program = Program(
                program_id=p["program_id"],
                name=p["name"],
                play_mode=p["play_mode"],
                episodes=[
                    Episode(
                        episode_id=e["episode_id"],
                        title=e["title"],
                        file_path=e["file_path"],
                        duration_seconds=e["duration_seconds"],
                    )
                    for e in p["episodes"]
                ],
            )
            self._programs[program.program_id] = program

    def get_program(self, program_id: str) -> Program | None:
        return self._programs.get(program_id)
```

---

## Non-Goals (Explicit)

Phase 4 explicitly does NOT:

| Non-Goal | Why |
|----------|-----|
| Implement Asset Library | Future phase concern |
| Scan filesystem for media | Violates no-probing rule |
| Run ffprobe at runtime | Violates no-probing rule |
| Add new ScheduleManager methods | Phase 4 is validation only |
| Support multiple programs | Minimal scenario uses one program |
| Support non-sequential play modes | Sequential is sufficient for validation |
| Add ad pods or promos | Phase N concern |
| Handle live content | Different model |
| Provide production fixtures | Test fixtures only |
| Define fixture update workflow | Out of scope |

---

## Relationship to Future Phases

### What Phase 4 Proves

- Phase 3 architecture handles real durations
- EPG grid alignment works correctly
- Filler insertion is mathematically sound
- Sequential looping is seamless

### What Comes After Phase 4

| Future Phase | Concern |
|--------------|---------|
| Asset Library | Replace fixtures with real database/API |
| Multiple Programs | Expand beyond single-program scenario |
| Random/Manual Modes | Validate other play modes |
| Multi-Channel | Prove isolation between channels |
| Ad Insertion | Traffic logic for commercial breaks |

Phase 4 is the **proof point** that enables confident development of these future phases.

---

## Litmus Test

> If a human opens the EPG for tomorrow, sees "Cheers S01E02" at 09:30, and tunes in at 09:42, then:
>
> - The episode playing MUST be S01E02
> - seek_offset MUST be 720 seconds (12 minutes)
> - Filler MUST appear only after the episode ends (at ~09:52:22)
> - No asset selection occurs at playback time
>
> If all of these are true, Phase 4 is correct.

---

## Summary

Phase 4 is not a feature. It is a **validation checkpoint** that proves Phase 3 works with real television content.

By using static fixtures with real durations, Phase 4 demonstrates:

1. EPG shows grid-aligned intent
2. Playout uses actual content durations
3. Filler fills the gap correctly
4. Sequential looping is seamless
5. All Phase 3 invariants hold under realistic conditions

No new runtime behavior. No probing. No heuristics. Just proof that the architecture works.
