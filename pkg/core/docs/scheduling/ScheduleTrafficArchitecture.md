_Related: [Scheduling system](SchedulingSystem.md) • [Domain: SchedulePlan](../data/domain/SchedulePlan.md) • [Domain: ScheduleDay](../data/domain/ScheduleDay.md) • [Domain: Channel](../data/domain/Channel.md) • [Contracts: Zones](../contracts/ZonesPatterns.md) • [Domain: Scheduling Policies](../data/domain/SchedulingPolicies.md)_

# Schedule / Traffic Architecture for Linear Television

> **Scope:** This document defines the broadcast-correct scheduling and traffic
> model for RetroVue. It covers terminology, responsibility boundaries, the time
> model, the event-based truth model, invariants, the Schedule Day JSON contract,
> and the **Automation Log (Playlist) contract** — the execution interface
> consumed by ChannelManager. It deliberately excludes playout, pipelines, PTS,
> viewers, and decoding — those concerns belong to [AIR](../../../air/CLAUDE.md).
>
> **Development approach:** This system is being built **playlist-first**. The
> Playlist contract between ScheduleManager and ChannelManager is locked first.
> SchedulePlan and ScheduleDay resolution may be stubbed, hard-coded, or
> incomplete during early phases. The Playlist shape must remain valid when real
> scheduling is introduced later.

## Broadcast Terminology

| Term | Definition |
|---|---|
| **Broadcast Day** | A station-defined 24-hour scheduling period beginning at a fixed local time (often 05:00, 06:00, or midnight). Schedules, logs, and compliance reporting are referenced to the broadcast day, not necessarily the calendar day. |
| **Grid** | The fixed time structure that defines allowed program start times on a channel. A 30-minute grid permits starts at :00 and :30; a 15-minute grid permits :00, :15, :30, :45. |
| **Block** | A single grid-aligned time slot. Blocks are a derived view useful for UI display, grid-alignment validation, and simulator modes. Blocks are not the scheduling truth. |
| **Event (Schedule Event)** | The atomic unit of scheduling truth. An event has a start time, a duration, and a content reference. Events may span multiple grid blocks. Events are what "airs." |
| **Daypart** | A named contiguous span of the broadcast day (e.g., "Morning", "Daytime", "Prime Time", "Late Night", "Overnight"). Dayparts are editorial labels used during planning and traffic resolution. They MUST NOT affect runtime timing or playout behavior. They MAY be carried as metadata for reporting, but downstream systems must not depend on them. |
| **Program** | A schedulable editorial unit. May be a single asset (a film) or a composed chain of assets (episode + bumpers). Programs have an intrinsic duration that is independent of the block they occupy. |
| **Interstitial** | Non-program content that fills time between programs within a block: promos, station IDs, bumpers, filler. Interstitials are scheduled as explicit events, not inferred gaps. |
| **Avail** | Unfilled time after a program event ends but before the next grid boundary. Traffic resolves avails into interstitial events. In the final Schedule Day, avails do not exist — only interstitial events. Dead air is never a valid state. |
| **Schedule Plan** | An operator-authored template that assigns programs or program pools to dayparts/zones across a repeating pattern (typically weekly). A plan is reusable across calendar dates. See [SchedulePlan](../data/domain/SchedulePlan.md). |
| **Schedule Day** | The resolved, frozen, concrete schedule for a specific channel on a specific calendar date. Generated from a Schedule Plan by Traffic. Contains an ordered list of events. Once frozen, a Schedule Day is the source of truth for that date. See [ScheduleDay](../data/domain/ScheduleDay.md). |
| **Traffic** | The function responsible for resolving a Schedule Plan into a Schedule Day — selecting specific episodes, computing event start times and durations, generating interstitial events for avails, enforcing grid alignment, and validating completeness. Traffic is a process, not a runtime actor. |
| **Automation Log (Playlist)** | The pre-air execution list **produced by Traffic (ScheduleManager)**. Contains resolved physical assets with absolute timecodes, ready for playout. In target state, derived from Schedule Day. During early phases, MAY be hard-coded or produced by any means internal to ScheduleManager. Regardless of production method, the Playlist shape and contract are identical. This is the sole artifact consumed by ChannelManager for execution — ChannelManager never reads Schedule Day directly. |
| **As-Run Log** | The post-air factual record of what actually played and when. Independent of the Automation Log. Used for compliance, billing, and audit. |
| **EPG (Electronic Program Guide)** | A viewer-facing, read-only derivation of Schedule Day data. EPG is never a source of truth; it is always downstream. See [EPGGeneration](../data/domain/EPGGeneration.md). |

---

## Responsibility Boundaries

```
                         ┌─────────────────────────────────────────────┐
                         │        ScheduleManager (Traffic)            │
                         │                                             │
  Operator               │  TARGET STATE          EARLY PHASES         │
    │  authors            │                                             │
    v                     │  SchedulePlan          (stubbed / absent)   │
  SchedulePlan ──────────►│    │                                       │
                         │    │ resolves                               │
                         │    v                                        │
                         │  ScheduleDay            (stubbed / absent)  │
                         │    │                                        │
                         │    │ derives              hard-codes         │
                         │    v                        │                │
                         │  Automation Log ◄───────────┘               │
                         │  (Playlist)                                 │
                         └───────┬──────────────────┬──────────────────┘
                                 │                  │
                    ┌────────────┘                  └──────────┐
                    v                                          v
              EPG Generation                           Automation Log
              (from ScheduleDay;                       (resolved segments)
               absent in early phases)                        │
                                                              │
                    ║  ◄────── HANDOFF BOUNDARY ──────►       │
                    ║  Automation Log is the contract surface. │
                    ║  Nothing below this line reads           │
                    ║  ScheduleDay, SchedulePlan, or           │
                    ║  any planning artifact.                  │
                                                              │
                                                              v
                                                      ChannelManager
                                                      (consumes Playlist,
                                                       coordinates playout)
                                                              │
                                                              v
                                                        As-Run Log
                                                      (observed ground truth)
```

**Traffic's essential output is the Playlist.** That is the contract being locked.

In target state, Traffic resolves Plan → Day → Playlist. In early phases, Traffic
MAY hard-code or stub the Playlist directly. ChannelManager does not know or care
which path produced the Playlist — it consumes the same shape either way.

**ChannelManager never interprets, re-derives, or queries Schedule Day.** It
receives finished Playlist entries and coordinates execution against wall-clock time.

- Operators own editorial intent (what *kind* of content airs when).
- Traffic owns resolution (what *specific* content airs when, as events).
- **Traffic owns Playlist production** (which *physical files* play, with timecodes). This is Traffic's essential output — the one that must work from day one.
- Traffic owns Schedule Day resolution when the full pipeline is operational.
- Schedule Day owns planning truth (the event list that *will* air).
- Automation Log (Playlist) owns execution intent (the pre-air file list that *should* play).
- EPG owns presentation (what viewers *see*).
- ChannelManager owns execution coordination (feeding playout from the Playlist).
- As-Run Log owns historical fact (what *did* air).

### Production and Consumption Rules

The following table makes explicit who produces and who consumes each artifact.
"Forbidden" means the component MUST NOT read or derive the artifact.

| Artifact | Produced by | Consumed by | Forbidden consumers |
|---|---|---|---|
| **Schedule Plan** | Operator | Traffic (ScheduleManager) | ChannelManager |
| **Schedule Day** | Traffic (ScheduleManager) | Traffic (ScheduleManager), EPG Generation | ChannelManager |
| **Automation Log** | Traffic (ScheduleManager) | ChannelManager | — |
| **As-Run Log** | ChannelManager | Operators, Reporting | — |
| **EPG** | EPG Generation (from Schedule Day) | Viewers, Operators | ChannelManager |

**Why ChannelManager must not read Schedule Day:** Schedule Day contains editorial
events (programs, interstitials) with SchedulableAsset references that may not yet
be resolved to physical files. Only the Automation Log contains the fully resolved
physical assets, absolute timecodes, and file paths required for playout. If
ChannelManager were to interpret Schedule Day directly, it would duplicate Traffic's
resolution logic, creating two sources of truth for "what file plays when."

### Playlist-First Development

The system is intentionally developed **playlist-first**. The Playlist contract
between ScheduleManager and ChannelManager is the first interface locked. All other
scheduling artifacts (SchedulePlan, ScheduleDay, EPG) are developed behind
ScheduleManager's boundary at their own pace.

**What this means in practice:**

- ScheduleManager MUST produce valid Playlists from day one.
- ScheduleManager MAY produce Playlists by any internal means: hard-coded segment
  lists, configuration files, or full Schedule Day resolution.
- ChannelManager MUST NOT know or care how the Playlist was produced. The Playlist
  shape is identical regardless of source.
- SchedulePlan and ScheduleDay MAY be stubs, placeholders, or entirely absent
  during early phases.
- EPG Generation is deferred until Schedule Day resolution is operational.
- The `source` field on a Playlist records how it was produced (for diagnostics),
  but no consumer may branch on this value.

**Phased implementation:**

| Phase | ScheduleManager produces Playlists via | SchedulePlan | ScheduleDay | EPG |
|---|---|---|---|---|
| **Early** | Hard-coded or config-driven segment lists | Absent | Absent | Absent |
| **Mid** | Simplified scheduling rules; partial resolution | Stubbed | Partial | Absent |
| **Target** | Full Plan → Day → Playlist resolution pipeline | Operational | Frozen/immutable | Derived |

**In all phases, the Playlist shape and ChannelManager's consumption contract are
identical.** This is the architectural constraint that makes playlist-first
development safe.

---

## Time Model

### Channel Timezone

Every channel declares an IANA timezone (e.g., `"America/New_York"`). All schedule
times are interpreted in this timezone. See [Channel](../data/domain/Channel.md)
for grid and boundary configuration.

### Broadcast Date

`broadcast_date` is the local calendar date on which the broadcast day **begins** at
`broadcast_day_start_local`. For a channel with `broadcast_day_start_local: "06:00"`
and `broadcast_date: "2026-02-06"`, the broadcast day runs from
2026-02-06 06:00 local through 2026-02-07 05:59:59 local.

### Absolute Timestamps

Every event in a Schedule Day carries an absolute ISO 8601 timestamp with UTC offset
(e.g., `"2026-02-06T06:00:00-05:00"`). The computed field `broadcast_day_start_at`
anchors the entire day.

### DST Handling

On DST transitions, the broadcast day may contain 23 or 25 wall-clock hours. Grid
math is derived from grid counts, not from assuming 60-minute hours. Events always
carry absolute timestamps, so DST ambiguity does not affect playout.

---

## Truth Model: Events, Not Blocks

Schedule Day truth is an ordered list of **events**. Each event has an absolute start
time, a duration, and a content reference. Events may span multiple grid blocks
naturally — a 92-minute film is one event, not three continuation blocks.

**Blocks are a derived view.** They are useful for:

- Grid-alignment validation
- UI display (EPG grids, operator dashboards)
- Simulator modes that think in fixed-width slots

Blocks are never the source of truth. They are always computed from events.

---

## Invariants

These are laws. They are not guidelines. Violation of any invariant is a system bug.

See also: [Zones + SchedulableAssets Contracts](../contracts/ZonesPatterns.md) for
the testable contract counterparts (C-GRID-01, C-ZONE-01, etc.).

### INV-GRID-01: Grid Alignment

Every event start time must fall on a grid boundary defined by the channel. No event
may begin at a non-grid-aligned time.

*Contract: C-GRID-01*

### INV-COV-01: Full Coverage

A Schedule Day must account for every second of the broadcast day. There are no gaps.
Every moment is covered by either a program event or an interstitial event. Dead air
is not a valid state.

### INV-FREEZE-01: Immutability After Freeze

Once a Schedule Day is frozen (generated within the EPG horizon), its event list is
fixed. Modifications require explicit operator override and re-freeze — never silent
mutation.

### INV-DURATION-01: Intrinsic Duration Integrity

A program's duration is a property of the program, not the block. A 22-minute program
in a 30-minute window produces a separate 8-minute interstitial event. A 92-minute
film is a single event spanning multiple grid blocks. The program is never stretched
or truncated to fit.

### INV-SEAM-01: Broadcast Day Continuity

The broadcast-day boundary is an accounting boundary, not a playout boundary. Events
may span the seam. Day views may include continuation records for reporting and EPG,
but playout continuity must remain uninterrupted.

*Contract: C-BD-01*

### INV-DAYPART-01: Daypart Non-Interference

Dayparts are editorial labels. They MUST NOT affect runtime timing or playout
behavior. They MAY be carried as metadata on events for reporting purposes, but no
downstream system may depend on them for scheduling or execution decisions.

### INV-EPG-01: EPG Derivation

EPG is always derived from Schedule Day. EPG never feeds back into scheduling. There
is no circular dependency.

*Contract: C-EPG-01*

### INV-HANDOFF-01: Playlist is the Execution Contract

ChannelManager MUST consume Automation Log (Playlist) entries for execution. It MUST
NOT read, query, or interpret Schedule Day or Schedule Plan. Traffic (ScheduleManager)
is the sole producer of Playlist entries. No other component may derive execution
intent from planning artifacts.

**This invariant holds regardless of how the Playlist was produced.** Whether
ScheduleManager derived the Playlist from a fully resolved Schedule Day, hard-coded
it from a configuration file, or generated it by any other internal means, the
Playlist shape and ChannelManager's consumption contract are identical. The production
method is an internal concern of ScheduleManager; the Playlist shape is a system-wide
contract.

### INV-BRK-01: Cuts Only at Authorized Breakpoints

Playout may transition from program content to interstitial or ad content only at
authorized breakpoints within the program — cue points, act breaks, SCTE markers,
or explicit chapter markers. Mid-segment cuts at arbitrary positions are invalid.

Programs that contain no breakpoints play to completion without interruption. Programs
that declare breakpoints define the only positions where Traffic may insert
interstitial events. If a program event extends beyond a grid boundary, the event
spans it; Traffic adjusts subsequent events at resolution time.

*Contract: C-BRK-01*

### INV-SM-009: Segment Integrity

Once playback of a PlayoutSegment begins, execution MUST proceed continuously until
the segment's declared `frame_count` is exhausted. Transitions may occur only between
segments, never within a segment.

This invariant applies to both program and filler segments.

This aligns ScheduleManager's output contract with:

- **INV-BRK-01** (authorized breakpoints) — upstream, Traffic ensures breaks are
  separate segments at authorized positions.
- **INV-PL-07** ([Segment Integrity in Playlist](../architecture/PlaylistArchitecture.md)) —
  the Playlist-level mirror stating segments are indivisible at execution time.
- **CT-domain switching logic** — the execution engine honours segment boundaries
  by switching only at segment transitions.

---

## Non-Goals

These are explicitly out of scope for the Schedule/Traffic architecture:

- **Playout / runtime execution.** How bytes reach a viewer is not a scheduling concern.
- **Encoding, muxing, transport.** These are downstream of scheduling.
- **Viewer sessions.** Scheduling does not know whether anyone is watching.
- **Dynamic ad insertion.** Avails are resolved into interstitial events at traffic time, not at runtime.
- **DVR, rewind, or time-shift.** The schedule is linear and forward-only.
- **Multi-channel coordination.** Each channel's schedule is independent. Simulcast or cross-channel logic, if ever needed, lives above this layer.
- **Real-time pacing.** The schedule defines *what* and *when*. Pacing is an execution concern.

---

## Schedule Day JSON Contract

Truth is events. This contract defines the canonical shape of a resolved Schedule Day.

### Example

Channel: **RetroVue Classic** |
Grid: **30 minutes** |
Broadcast Day Start: **06:00 America/New_York** |
Date: **2026-02-06**

```json
{
  "channel_id": "retrovue-classic",
  "channel_timezone": "America/New_York",
  "broadcast_date": "2026-02-06",
  "broadcast_day_start_local": "06:00",
  "broadcast_day_start_at": "2026-02-06T06:00:00-05:00",
  "grid_minutes": 30,
  "status": "FROZEN",
  "frozen_at": "2026-02-03T12:00:00Z",

  "events": [
    {
      "event_id": "evt-20260206-0600-001",
      "start_at": "2026-02-06T06:00:00-05:00",
      "scheduled_duration_seconds": 1440,
      "type": "PROGRAM",
      "daypart": "Morning",
      "program": {
        "program_id": "prog-001",
        "series_title": "Astro Boy",
        "episode_id": "S01E12",
        "episode_title": "Atlas Lives",
        "asset_id": "asset-astroboy-s01e12",
        "asset_duration_seconds": 1440
      }
    },
    {
      "event_id": "evt-20260206-0624-001",
      "start_at": "2026-02-06T06:24:00-05:00",
      "scheduled_duration_seconds": 360,
      "type": "INTERSTITIAL",
      "interstitial": {
        "policy": "AVAIL_FILL",
        "allowed_kinds": ["PROMO", "ID", "FILLER"]
      }
    },
    {
      "event_id": "evt-20260206-0630-001",
      "start_at": "2026-02-06T06:30:00-05:00",
      "scheduled_duration_seconds": 1380,
      "type": "PROGRAM",
      "daypart": "Morning",
      "program": {
        "program_id": "prog-002",
        "series_title": "Speed Racer",
        "episode_id": "S01E05",
        "episode_title": "The Secret Engine",
        "asset_id": "asset-speedracer-s01e05",
        "asset_duration_seconds": 1380
      }
    },
    {
      "event_id": "evt-20260206-0653-001",
      "start_at": "2026-02-06T06:53:00-05:00",
      "scheduled_duration_seconds": 420,
      "type": "INTERSTITIAL",
      "interstitial": {
        "policy": "AVAIL_FILL",
        "allowed_kinds": ["PROMO", "ID", "FILLER"]
      }
    },
    {
      "event_id": "evt-20260206-0700-001",
      "start_at": "2026-02-06T07:00:00-05:00",
      "scheduled_duration_seconds": 1500,
      "type": "PROGRAM",
      "daypart": "Morning",
      "program": {
        "program_id": "prog-003",
        "series_title": "The Twilight Zone",
        "episode_id": "S02E15",
        "episode_title": "The Invaders",
        "asset_id": "asset-tz-s02e15",
        "asset_duration_seconds": 1500
      }
    },
    {
      "event_id": "evt-20260206-0725-001",
      "start_at": "2026-02-06T07:25:00-05:00",
      "scheduled_duration_seconds": 2100,
      "type": "INTERSTITIAL",
      "interstitial": {
        "policy": "AVAIL_FILL",
        "allowed_kinds": ["PROMO", "ID", "FILLER"]
      }
    },
    {
      "event_id": "evt-20260206-0800-001",
      "start_at": "2026-02-06T08:00:00-05:00",
      "scheduled_duration_seconds": 5520,
      "type": "PROGRAM",
      "daypart": "Daytime",
      "program": {
        "program_id": "prog-004",
        "title": "The Day the Earth Stood Still",
        "asset_id": "asset-movie-tdtess",
        "asset_duration_seconds": 5520
      }
    },
    {
      "event_id": "evt-20260206-0932-001",
      "start_at": "2026-02-06T09:32:00-05:00",
      "scheduled_duration_seconds": 1680,
      "type": "INTERSTITIAL",
      "interstitial": {
        "policy": "AVAIL_FILL",
        "allowed_kinds": ["PROMO", "ID", "FILLER"]
      }
    }
  ]
}
```

### Contract Notes

- **Time is absolute + timezone-correct.** Every event carries a full ISO 8601
  timestamp. The channel timezone is declared. `broadcast_date` is the local
  calendar date when the broadcast day begins.
- **Longform spans naturally.** The 92-minute film is one event. No
  "continuation blocks" or repeated program references.
- **Avails are explicit interstitial events.** Every second is accounted for by
  an event. Traffic resolved avails into interstitial fill windows with a
  declared policy.
- **Dayparts are metadata, not structure.** The optional `"daypart"` field is a
  reporting label. Remove it and nothing breaks.
- **Events are truth.** Traffic (ScheduleManager) takes this event list and
  derives the Automation Log by resolving physical files and computing
  timecodes. EPG Generation takes the same event list and produces
  viewer-facing guide data. Both derive from the same planning truth.
  ChannelManager never reads this structure — it consumes the Automation Log.
- **A complete broadcast day** would continue through to 05:59:59 the following
  morning, covering the full 24-hour period. Truncated here for clarity.

### Optional: Derived Grid View

If consumers need a block-oriented view (for EPG grid UIs, the RetroVue
30-minute simulator mode, etc.), it is derived from events:

```json
{
  "grid_view": {
    "block_minutes": 30,
    "blocks": [
      {
        "block_start_at": "2026-02-06T06:00:00-05:00",
        "covers_event_ids": ["evt-20260206-0600-001", "evt-20260206-0624-001"]
      },
      {
        "block_start_at": "2026-02-06T06:30:00-05:00",
        "covers_event_ids": ["evt-20260206-0630-001", "evt-20260206-0653-001"]
      },
      {
        "block_start_at": "2026-02-06T07:00:00-05:00",
        "covers_event_ids": ["evt-20260206-0700-001", "evt-20260206-0725-001"]
      },
      {
        "block_start_at": "2026-02-06T07:30:00-05:00",
        "covers_event_ids": ["evt-20260206-0725-001"]
      },
      {
        "block_start_at": "2026-02-06T08:00:00-05:00",
        "covers_event_ids": ["evt-20260206-0800-001"]
      },
      {
        "block_start_at": "2026-02-06T08:30:00-05:00",
        "covers_event_ids": ["evt-20260206-0800-001"]
      },
      {
        "block_start_at": "2026-02-06T09:00:00-05:00",
        "covers_event_ids": ["evt-20260206-0800-001"]
      },
      {
        "block_start_at": "2026-02-06T09:30:00-05:00",
        "covers_event_ids": ["evt-20260206-0800-001", "evt-20260206-0932-001"]
      }
    ]
  }
}
```

This keeps the simulator-friendly view without making blocks the scheduling truth.

---

## Automation Log (Playlist) Contract

> **Authoritative source:** [Playlist Architecture](../architecture/PlaylistArchitecture.md)
> defines the full Playlist contract — shape, field definitions, invariants
> (INV-PL-01 through INV-PL-06), ChannelManager consumption model, and
> playlist-first development phases. This section summarizes the key points
> relevant to the scheduling boundary.

The Playlist is a **time-bounded, linear, ordered list of executable segments** that
fully covers its time window. Each segment is a resolved physical asset with an
absolute start time, a duration, and a file path. No editorial metadata crosses
this boundary — no program titles, no dayparts, no SchedulableAsset references.

**Key properties:**

- **Produced by** ScheduleManager (Traffic). No other component may produce Playlists.
- **Consumed by** ChannelManager. No other execution component reads planning
  artifacts.
- **Fully tiled.** Segments cover every second of the window with no gaps.
- **Fully resolved.** Every segment has a concrete `asset_path`. No expansion logic.
- **Stable shape.** Identical whether derived from Schedule Day, hard-coded, or
  produced by any other ScheduleManager-internal means.
- **Immutable after handoff** to ChannelManager.

### Contrast with Schedule Day

| | Schedule Day | Playlist |
|---|---|---|
| **Purpose** | Planning truth: what *will* air | Execution intent: what *should* play |
| **Contains** | Editorial events (programs, interstitials, dayparts) | Executable segments (file paths, timecodes) |
| **References** | SchedulableAssets, program IDs, series metadata | Physical asset IDs and file paths only |
| **Scope** | One broadcast day | Any time window |
| **Produced by** | Traffic (ScheduleManager) from Schedule Plan | Traffic (ScheduleManager) — from Schedule Day, config, or hard-code |
| **Consumed by** | Traffic (ScheduleManager), EPG Generation | ChannelManager |
| **Forbidden consumers** | ChannelManager | — |

For the full contract shape, segment field definitions, and invariant details, see
[Playlist Architecture](../architecture/PlaylistArchitecture.md).

---

## See Also

- [Playlist Architecture](../architecture/PlaylistArchitecture.md) — **Authoritative Playlist contract** (shape, invariants, consumption model, playlist-first phases)
- [SchedulingSystem.md](SchedulingSystem.md) — Full scheduling pipeline architecture
- [SchedulePlan](../data/domain/SchedulePlan.md) — Operator-authored plans with Zones and SchedulableAssets
- [ScheduleDay](../data/domain/ScheduleDay.md) — Resolved, frozen daily schedule
- [Channel](../data/domain/Channel.md) — Grid configuration and broadcast day anchor
- [SchedulingPolicies](../data/domain/SchedulingPolicies.md) — Default scheduling policy catalog
- [ZonesPatterns](../contracts/ZonesPatterns.md) — Testable behavioral contracts (C-GRID-01 through C-EPG-01)
