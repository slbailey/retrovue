_Related: [Schedule / Traffic Architecture](../scheduling/ScheduleTrafficArchitecture.md) • [Scheduling system](../scheduling/SchedulingSystem.md) • [Domain: Channel](../data/domain/Channel.md) • [Runtime: ChannelManager](../runtime/ChannelManager.md) • [Architecture overview](ArchitectureOverview.md)_

# Playlist (Automation Log) Architecture

## Purpose

This document defines the Automation Log (Playlist) contract produced by
ScheduleManager and consumed by ChannelManager for linear playout execution.

---

## Definitions

| Term | Definition |
|---|---|
| **Playlist** | A time-bounded, linear, ordered list of executable segments that fully covers its time window. Each segment is a resolved physical asset with an absolute start time, a duration, and a file path. Synonymous with Automation Log in broadcast terminology. |
| **Segment** | A single executable entry in a Playlist. Has an absolute start time, a duration, a type, an asset ID, and a file path. A segment is fully resolved — no editorial references, no expansion logic, no scheduling abstractions. A segment is indivisible at execution time; playout may only transition between segments, never within them. |
| **Window** | The time span a Playlist covers, defined by `window_start_at` and `window_end_at`. Segments must tile this window completely. |
| **ScheduleManager** | The component acting in the Traffic role. Sole producer of Playlists. May produce them from a fully resolved Schedule Day, from configuration, or from hard-coded segment lists. The production method is internal to ScheduleManager. |
| **ChannelManager** | The component that coordinates playout execution for a single channel. Sole consumer of Playlists. Determines "what should be playing right now" by position within the Playlist relative to wall-clock time. |

---

## Ownership

### Who Produces Playlists

**ScheduleManager (Traffic) is the sole producer of Playlists.** No other component
may create, modify, or synthesize Playlist entries.

In target state, ScheduleManager derives Playlists from resolved Schedule Days by
expanding SchedulableAssets to physical files and computing absolute timecodes. During
early phases, ScheduleManager MAY produce Playlists by any internal means — including
hard-coded segment lists, configuration files, or simplified scheduling rules. The
production method is an internal concern of ScheduleManager; the Playlist shape is a
system-wide contract.

### Who Consumes Playlists

**ChannelManager is the sole consumer of Playlists.** ChannelManager requests
Playlists from ScheduleManager and uses them to coordinate playout execution.

### What Is Forbidden

ChannelManager MUST NOT:

- Read, query, or interpret Schedule Day.
- Read, query, or interpret Schedule Plan.
- Apply grid rules, zone logic, or editorial policy.
- Derive or re-derive execution intent from any planning artifact.
- Branch on the Playlist `source` field.

ScheduleManager MUST NOT:

- Expose Schedule Day or Schedule Plan to ChannelManager.
- Produce Playlists with unresolved references (SchedulableAssets, VirtualAssets,
  program chains that require expansion).
- Produce Playlists with editorial metadata in segment fields.

### Why This Boundary Exists

The Playlist is the contract surface between scheduling and execution. It exists so
that:

1. **Scheduling logic is replaceable.** ScheduleManager's internals (plans, zones,
   grid rules, episode selection) can change without affecting ChannelManager.
2. **Execution logic is simple.** ChannelManager positions itself in a flat list of
   segments by wall-clock time. It does not interpret editorial intent.
3. **The system is buildable playlist-first.** The Playlist contract can be locked
   and tested before real scheduling exists.

---

## Contract Shape

### Playlist

```json
{
  "channel_id": "retrovue-classic",
  "channel_timezone": "America/New_York",
  "window_start_at": "2026-02-06T06:00:00-05:00",
  "window_end_at": "2026-02-07T06:00:00-05:00",
  "generated_at": "2026-02-06T04:00:00Z",
  "source": "SCHEDULE_DAY",

  "segments": [
    {
      "segment_id": "seg-20260206-0600-001",
      "start_at": "2026-02-06T06:00:00-05:00",
      "duration_seconds": 1440,
      "type": "PROGRAM",
      "asset_id": "asset-astroboy-s01e12",
      "asset_path": "/mnt/media/astro-boy/s01e12.mp4"
    },
    {
      "segment_id": "seg-20260206-0624-001",
      "start_at": "2026-02-06T06:24:00-05:00",
      "duration_seconds": 360,
      "type": "INTERSTITIAL",
      "asset_id": "asset-promo-retrovue-001",
      "asset_path": "/mnt/media/promos/retrovue-classic-id.mp4"
    },
    {
      "segment_id": "seg-20260206-0630-001",
      "start_at": "2026-02-06T06:30:00-05:00",
      "duration_seconds": 1380,
      "type": "PROGRAM",
      "asset_id": "asset-speedracer-s01e05",
      "asset_path": "/mnt/media/speed-racer/s01e05.mp4"
    },
    {
      "segment_id": "seg-20260206-0653-001",
      "start_at": "2026-02-06T06:53:00-05:00",
      "duration_seconds": 420,
      "type": "INTERSTITIAL",
      "asset_id": "asset-filler-retrovue-002",
      "asset_path": "/mnt/media/filler/retrovue-bumper-02.mp4"
    },
    {
      "segment_id": "seg-20260206-0700-001",
      "start_at": "2026-02-06T07:00:00-05:00",
      "duration_seconds": 1500,
      "type": "PROGRAM",
      "asset_id": "asset-tz-s02e15",
      "asset_path": "/mnt/media/twilight-zone/s02e15.mp4"
    },
    {
      "segment_id": "seg-20260206-0725-001",
      "start_at": "2026-02-06T07:25:00-05:00",
      "duration_seconds": 2100,
      "type": "INTERSTITIAL",
      "asset_id": "asset-filler-retrovue-004",
      "asset_path": "/mnt/media/filler/retrovue-interstitial-block.mp4"
    },
    {
      "segment_id": "seg-20260206-0800-001",
      "start_at": "2026-02-06T08:00:00-05:00",
      "duration_seconds": 5520,
      "type": "PROGRAM",
      "asset_id": "asset-movie-tdtess",
      "asset_path": "/mnt/media/movies/the-day-the-earth-stood-still.mp4"
    },
    {
      "segment_id": "seg-20260206-0932-001",
      "start_at": "2026-02-06T09:32:00-05:00",
      "duration_seconds": 1680,
      "type": "INTERSTITIAL",
      "asset_id": "asset-filler-retrovue-003",
      "asset_path": "/mnt/media/filler/retrovue-slate-loop.mp4"
    }
  ]
}
```

*A complete Playlist would continue through to `window_end_at`. Truncated here for
clarity.*

### Playlist Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `channel_id` | string | yes | Channel this Playlist covers. |
| `channel_timezone` | string | yes | IANA timezone (e.g., `"America/New_York"`). |
| `window_start_at` | ISO 8601 | yes | Absolute start of the time window. |
| `window_end_at` | ISO 8601 | yes | Absolute end of the time window. Segments must tile this window completely. |
| `generated_at` | ISO 8601 | yes | When this Playlist was produced (UTC). |
| `source` | string | yes | How this Playlist was produced: `SCHEDULE_DAY`, `HARD_CODED`, `MANUAL`. Diagnostic only — consumers MUST NOT branch on this value. |
| `segments` | array | yes | Ordered list of executable segments covering the full window. |

### Segment Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `segment_id` | string | yes | Unique identifier for this segment. |
| `start_at` | ISO 8601 | yes | Absolute start time with UTC offset. |
| `duration_seconds` | integer | yes | Segment duration in seconds. |
| `type` | string | yes | `PROGRAM` or `INTERSTITIAL`. Additional segment types (e.g., `AD`, `PROMO`, `BUMPER`) may be introduced later; all obey the same execution and integrity rules. |
| `asset_id` | string | yes | Reference to the resolved physical asset in the catalog. |
| `asset_path` | string | yes | File path for playout. Must be resolvable by the playout system at execution time. |

### What Crosses the Boundary

| Crosses | Does NOT cross |
|---|---|
| Asset IDs | Program titles, series names |
| File paths | Episode IDs, season numbers |
| Absolute timestamps | Daypart labels |
| Durations in seconds | Grid rules, zone names |
| Segment type (PROGRAM / INTERSTITIAL) | Scheduling policies, play modes |
| Diagnostic `source` field | SchedulableAsset references |

---

## Invariants

These are laws that apply to every Playlist, regardless of how it was produced.

### INV-PL-01: Full Tiling

Segments MUST tile `window_start_at` through `window_end_at` with no gaps and no
overlaps. For every instant `t` where `window_start_at <= t < window_end_at`, exactly
one segment covers `t`. Dead air is not a valid state.

**Validation rule:** For consecutive segments `S[n]` and `S[n+1]`:
`S[n].start_at + S[n].duration_seconds == S[n+1].start_at`

And: `segments[0].start_at == window_start_at`
And: `segments[last].start_at + segments[last].duration_seconds == window_end_at`

### INV-PL-02: Resolved Assets Only

Every segment MUST reference a concrete file path in `asset_path`. No
SchedulableAsset references, no VirtualAssets, no asset chains, no expansion logic.
The Playlist is fully resolved — ChannelManager performs no content resolution.

### INV-PL-03: No Editorial Metadata

No program titles, series names, episode IDs, dayparts, zone names, or scheduling
policy references appear in segment fields. The Playlist is execution intent, not
editorial description. Editorial metadata lives in Schedule Day, upstream of the
handoff boundary.

### INV-PL-04: Absolute Timestamps

All timestamps are absolute ISO 8601 with UTC offset. No relative offsets, no
broadcast-day-relative times, no grid-relative positions. ChannelManager uses these
timestamps directly against wall-clock time with no interpretation.

### INV-PL-05: Stable Shape

The Playlist shape is identical whether produced from a fully resolved Schedule Day,
a hard-coded segment list, a configuration file, or any other internal
ScheduleManager mechanism. ChannelManager's consumption logic does not vary by
production method.

### INV-PL-06: Immutable After Handoff

Once a Playlist is handed to ChannelManager, it is not modified. If ScheduleManager
needs to change what airs, it produces a new Playlist and signals ChannelManager to
transition. ChannelManager never mutates a Playlist it has received.

### INV-PL-07: Segment Integrity

Once playback of a segment begins, playout MUST proceed continuously from the
segment's start offset to its end. Transitions to another segment may occur only
at segment boundaries.

Mid-segment interruption, truncation, or seeking is invalid except under explicit
fault or operator override policy.

This is the execution-layer mirror of the scheduling-layer breakpoint rule
([INV-BRK-01](../scheduling/ScheduleTrafficArchitecture.md)). Upstream, Traffic
ensures that ad breaks and interstitials are separate segments aligned to authorized
breakpoints. Downstream, this invariant ensures ChannelManager honours that structure
by never splitting a segment during playback. The result: if a break was not
scheduled as a segment boundary, it cannot happen at execution time.

---

## ChannelManager Consumption Model

ChannelManager is a consumer of Playlists. It does not participate in scheduling.
Its responsibilities at the Playlist boundary are:

### Requesting Playlists

ChannelManager requests Playlists from ScheduleManager by channel ID and time range.
ScheduleManager returns one or more Playlists covering the requested window.
ChannelManager does not specify how the Playlist should be produced — it receives
whatever ScheduleManager provides.

### Determining "Now"

When a viewer joins or playout is active, ChannelManager determines what should be
playing by:

1. Querying the MasterClock for the current wall-clock time (`now`).
2. Finding the segment in the Playlist where `segment.start_at <= now < segment.start_at + segment.duration_seconds`.
3. Computing the offset into the segment: `offset = now - segment.start_at`.
4. Instructing the playout system to begin at that offset in the segment's
   `asset_path`.

This is a positional lookup. ChannelManager does not evaluate grid boundaries, zone
transitions, or editorial rules. It finds the current segment by time and plays from
the correct offset.

### Segment Transitions

When the current segment's duration elapses, ChannelManager advances to the next
segment in the Playlist. Because segments tile the window completely (INV-PL-01),
the next segment's `start_at` equals the current segment's end time. The transition
is seamless.

### Window Boundaries

As the current time approaches `window_end_at`, ChannelManager requests the next
Playlist from ScheduleManager. ScheduleManager produces Playlists with sufficient
lookahead for ChannelManager to always have coverage. The overlap or handoff between
consecutive Playlist windows is a coordination concern between ScheduleManager and
ChannelManager, not a scheduling concern.

### As-Run Logging

As each segment begins playback, ChannelManager records an As-Run Log entry with
the actual start time (from MasterClock), the segment ID, and the asset ID. The
As-Run Log is ChannelManager's output — the post-air factual record.

---

## Relationship to Schedule Day

The Playlist is derived from Schedule Day in target state but is a distinct artifact
with a different shape, different consumers, and different invariants.

| | Schedule Day | Playlist |
|---|---|---|
| **Purpose** | Planning truth: what *will* air | Execution intent: what *should* play |
| **Contains** | Editorial events (programs, interstitials, dayparts) | Executable segments (file paths, timecodes) |
| **References** | SchedulableAssets, program IDs, series metadata | Physical asset IDs and file paths only |
| **Scope** | One broadcast day | Any time window (may align to a broadcast day) |
| **Produced by** | Traffic (ScheduleManager) from Schedule Plan | Traffic (ScheduleManager) — from Schedule Day, config, or hard-code |
| **Consumed by** | Traffic (ScheduleManager), EPG Generation | ChannelManager |
| **Forbidden consumers** | ChannelManager | — |
| **Mutable** | Only via operator override after freeze | Immutable after handoff to ChannelManager |

**Key distinction:** Schedule Day contains editorial intent that requires resolution
(SchedulableAssets, program chains, VirtualAssets, play modes). Playlist contains
the output of that resolution — physical files and absolute times, ready for
execution.

ChannelManager never needs to understand this distinction. It only sees Playlists.

---

## Playlist-First Development

The system is intentionally developed **playlist-first**. The Playlist contract
between ScheduleManager and ChannelManager is the first interface locked.

### Phased Implementation

| Phase | ScheduleManager produces Playlists via | Schedule Plan | Schedule Day | EPG |
|---|---|---|---|---|
| **Early** | Hard-coded or config-driven segment lists | Absent | Absent | Absent |
| **Mid** | Simplified scheduling rules; partial resolution | Stubbed | Partial | Absent |
| **Target** | Full Plan → Day → Playlist resolution pipeline | Operational | Frozen/immutable | Derived |

### What Is Constant Across All Phases

- The Playlist shape (fields, types, structure).
- ChannelManager's consumption contract (request, positional lookup, transition).
- All Playlist invariants (INV-PL-01 through INV-PL-06).
- The ownership rule: ScheduleManager produces, ChannelManager consumes.
- The prohibition: ChannelManager does not read planning artifacts.

### What Changes Between Phases

- How ScheduleManager internally produces Playlists (hard-code → config → full
  resolution).
- Whether Schedule Plan, Schedule Day, and EPG exist.
- The `source` field value on produced Playlists (`HARD_CODED` → `SCHEDULE_DAY`).

The `source` field is diagnostic. No consumer branches on it. This is what makes
playlist-first development safe — the interface is stable while the implementation
behind it matures.

---

## See Also

- [Schedule / Traffic Architecture](../scheduling/ScheduleTrafficArchitecture.md) — Scheduling model, event-based truth, Schedule Day contract, handoff boundaries
- [Scheduling system](../scheduling/SchedulingSystem.md) — Full scheduling pipeline architecture
- [ChannelManager](../runtime/ChannelManager.md) — Runtime execution and playout coordination
- [Channel](../data/domain/Channel.md) — Grid configuration and broadcast day anchor
- [Architecture overview](ArchitectureOverview.md) — System layers and data flow
