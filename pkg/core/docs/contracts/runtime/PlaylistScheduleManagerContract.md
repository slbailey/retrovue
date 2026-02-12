_Related: [Playlist Architecture](../../architecture/PlaylistArchitecture.md) · [Schedule / Traffic Architecture](../../scheduling/ScheduleTrafficArchitecture.md) · [ChannelManager](../../runtime/ChannelManager.md)_

# Playlist ScheduleManager Contract

**Deprecated → Removed by [Phase8DecommissionContract](../../../../docs/contracts/architecture/Phase8DecommissionContract.md).** No runtime can load or drive playout from a Playlist; the only valid playout path is BlockPlan. This contract is retained for reference only.

Status: **Accepted** — Frozen 2026-02-07. Do not modify unless a new invariant is discovered.

---

## Purpose and Scope

This contract defines a **Playlist-only ScheduleManager** — the sole producer
of Playlists consumed by ChannelManager.

The goal is minimal: feed the proven, frame-authoritative Playlist execution
engine in ChannelManager with deterministic, fully-tiled Playlists.  Real
scheduling (ScheduleDay, SchedulePlan, EPG, episode selection) does not exist
yet.  This ScheduleManager produces Playlists from hard-coded or
configuration-driven data.

### What This Contract Defines

- A `PlaylistScheduleManager` that produces `Playlist` objects.
- A single public method: `get_playlists()`.
- Rules for how Playlists are produced from hard-coded segment patterns.
- Invariants that every produced Playlist must satisfy.
- Ownership boundaries between ScheduleManager and ChannelManager.

### What This Contract Does NOT Define

- ScheduleDay, SchedulePlan, or EPG.
- Episode selection, play modes, or sequence state.
- ProgramBlock, ProgramRef, ResolvedSlot, or any legacy scheduling type.
- Grid math exposed to ChannelManager.
- Dynamic ad insertion, promo scheduling, or content resolution.
- Persistence of produced Playlists.

### Relationship to Existing Contracts

The legacy `ScheduleManager` protocol (Phase 0–8) exposes `get_program_at()`
and `get_next_program()`, returning `ProgramBlock` objects consumed by the
legacy ChannelManager execution path.

`PlaylistScheduleManager` is a separate interface.  It does not extend, replace,
or inherit from the legacy protocol.  ChannelManager consumes Playlists via
`load_playlist()` when a Playlist is available; the legacy `ScheduleService`
path remains for channels without a Playlist.

---

## Public Interface

```python
from datetime import datetime
from retrovue.runtime.channel_manager import Playlist


class PlaylistScheduleManager(Protocol):
    """Sole producer of Playlists for ChannelManager consumption.

    Answers: "What should air on this channel during this window?"
    Returns one or more Playlists that fully tile the requested window.
    """

    def get_playlists(
        self,
        channel_id: str,
        window_start_at: datetime,
        window_end_at: datetime,
    ) -> list[Playlist]:
        """Return Playlists that tile [window_start_at, window_end_at).

        Args:
            channel_id: Channel identifier.
            window_start_at: Inclusive start of the requested window
                (timezone-aware).  Typically the start of today's broadcast day.
            window_end_at: Exclusive end of the requested window
                (timezone-aware).  Typically the end of tomorrow's broadcast day.

        Returns:
            One or more Playlist objects whose combined windows tile
            [window_start_at, window_end_at) with no gaps and no overlaps.
            Each Playlist satisfies all invariants in this contract.

        Raises:
            ValueError: If window_start_at >= window_end_at.
            ValueError: If either datetime is naive (no tzinfo).
        """
        ...
```

### Typical Call Site (ChannelManager / Orchestrator)

```python
playlists = schedule_manager.get_playlists(
    channel_id="retrovue-classic",
    window_start_at=today_broadcast_day_start,   # e.g. 2026-02-07T06:00:00-05:00
    window_end_at=tomorrow_broadcast_day_end,     # e.g. 2026-02-09T06:00:00-05:00
)
for playlist in playlists:
    channel_manager.load_playlist(playlist)
```

The caller is responsible for determining broadcast-day boundaries.
`PlaylistScheduleManager` does not compute broadcast-day boundaries; it
accepts arbitrary timezone-aware windows.

---

## Playlist Production Rules

### Segment Pattern (Hard-Coded Phase)

In the hard-coded phase, `PlaylistScheduleManager` produces Playlists from a
repeating pattern of segments.  A minimal pattern consists of:

1. **PROGRAM segment** — a content asset (e.g., a Cheers episode).
2. **INTERSTITIAL segment** — filler content (e.g., a station bumper or
   interstitial reel).

The pattern repeats to fill the requested window.  The implementation may use
any internal method to produce segments (hard-coded lists, TOML/JSON config
files, repeating templates) — the production method is opaque to consumers.

### Segment Construction Rules

Each `PlaylistSegment` MUST be constructed with:

| Field | Rule |
|---|---|
| `segment_id` | Unique across the Playlist.  Recommended format: `seg-{YYYYMMDD}-{HHMM}-{NNN}`. |
| `start_at` | Absolute UTC timestamp (timezone-aware).  First segment's `start_at` equals the Playlist's `window_start_at`. |
| `duration_seconds` | Float.  Exactly `frame_count / fps` (IEEE 754 float64 division, no rounding).  **Metadata only** — used for logging and positional time-lookup.  Execution uses `frame_count`. |
| `type` | `"PROGRAM"` or `"INTERSTITIAL"`. |
| `asset_id` | Identifier for the physical asset in the catalog. |
| `asset_path` | Fully-qualified file system path.  Must be resolvable at execution time. |
| `frame_count` | Non-negative integer.  Total number of frames when played from offset 0.  **Authoritative for execution.** |

### Frame Budget Computation

`frame_count` is the authoritative execution quantity.  It is set by the
producer (ScheduleManager) and never recomputed by the consumer
(ChannelManager).

For hard-coded segments:

```
frame_count = round_half_up(content_duration_seconds * fps)
```

Where `round_half_up(x) = floor(x + 0.5)` for non-negative x.

`duration_seconds` is derived exactly — no rounding:

```
duration_seconds = frame_count / fps
```

This is IEEE 754 float64 division.  `duration_seconds` is metadata; it exists
for logging and positional time-lookup.  `frame_count` is the sole execution
authority.  If a consumer needs a frame count, it reads `frame_count` directly —
never `duration_seconds * fps`.

### Grid Alignment (Internal Only)

The producer MAY internally use grid-aligned time slots (e.g., 30-minute
boundaries) to organize segments.  Grid math is an **internal concern** of
ScheduleManager.  No grid parameters, slot boundaries, or alignment rules
cross the Playlist boundary.  ChannelManager sees only segments with absolute
timestamps.

### Window Tiling

The returned Playlists MUST tile the entire requested window:

- The first segment of the first Playlist starts at `window_start_at`.
- The last segment of the last Playlist ends at `window_end_at`.
- Consecutive segments within a Playlist abut exactly (frame-based):
  `segments[n+1].start_at == segments[n].start_at + timedelta(seconds=segments[n].frame_count / fps)`
- If multiple Playlists are returned, they abut exactly:
  `playlists[n].window_end_at == playlists[n+1].window_start_at`.

**Precision rule:** Abutment is validated using `frame_count / fps` (IEEE 754
float64 division) passed to `timedelta(seconds=...)`.  `datetime` stores
microsecond precision internally.  Producers MUST construct timestamps using
this same computation so that exact `==` comparison holds.

---

## Invariants

Every Playlist produced by `PlaylistScheduleManager` MUST satisfy all of the
following invariants.  These are laws, not guidelines.

### INV-PSM-01: Full Tiling (Frame-Consistent)

Segments MUST tile `window_start_at` through `window_end_at` with no gaps and
no overlaps.  For every instant `t` where `window_start_at <= t < window_end_at`,
exactly one segment covers `t`.

**Abutment law (frame-based):**
- `segments[0].start_at == window_start_at`
- For all consecutive pairs:
  `segments[n+1].start_at == segments[n].start_at + timedelta(seconds=segments[n].frame_count / fps)`
- Last segment closes the window:
  `segments[-1].start_at + timedelta(seconds=segments[-1].frame_count / fps) == window_end_at`

`duration_seconds` is NOT used for tiling validation.  The frame-based
computation is authoritative.  Since `duration_seconds == frame_count / fps`
(INV-PSM-04), the two expressions are numerically identical, but the
frame-based form is canonical.

Dead air is not a valid state.

### INV-PSM-02: Non-Negative Frame Counts

Every segment MUST have `frame_count >= 0`.  Negative frame counts are
rejected by ChannelManager at load time (`load_playlist` raises `ValueError`).

### INV-PSM-03: Absolute Timestamps

All timestamps (`window_start_at`, `window_end_at`, `generated_at`,
`segment.start_at`) are absolute, timezone-aware `datetime` objects.  No
relative offsets, no broadcast-day-relative positions.

### INV-PSM-04: Frame-Authoritative Execution

`frame_count` is the sole authoritative execution quantity.  `duration_seconds`
is **metadata only** — it exists for logging, positional time-lookup, and human
readability.  No consumer may derive `frame_count` from `duration_seconds`.

The exact relationship is:
```
duration_seconds == frame_count / fps
```
This is IEEE 754 float64 division with no rounding.  The producer MUST set
`duration_seconds` to exactly this value.  Validation may use an epsilon of
`1e-9` to absorb float representation noise, but the producer's intent is
exact equality.

### INV-PSM-05: Immutability After Handoff

Once a Playlist is returned from `get_playlists()`, the producer MUST NOT
modify it.  Playlists are frozen dataclasses.  If the schedule changes, the
producer generates a new Playlist.

### INV-PSM-06: Deterministic Output

Given the same `(channel_id, window_start_at, window_end_at)` and the same
internal configuration, `get_playlists()` MUST return identical Playlists
(same segments, same frame counts, same timestamps).

### INV-PSM-07: Resolved Assets Only

Every segment references a concrete file path in `asset_path`.  No unresolved
references, no asset chains, no expansion logic.

### INV-PSM-08: Multi-Playlist Window Coverage

When multiple Playlists are returned, their combined windows MUST tile the
requested `[window_start_at, window_end_at)` with no gaps and no overlaps:
- `playlists[0].window_start_at == window_start_at`
- For all consecutive pairs: `playlists[n].window_end_at == playlists[n+1].window_start_at`
- `playlists[-1].window_end_at == window_end_at`

---

## Ownership Boundaries

### PlaylistScheduleManager Owns

| Concern | Detail |
|---|---|
| Segment ordering | Decides what airs in what order. |
| Frame budgets | Sets `frame_count` for each segment.  Authoritative. |
| Absolute timestamps | Computes `start_at` for each segment. |
| Asset resolution | Maps content to physical file paths. |
| Grid alignment (internal) | May use grid slots internally; never exposed. |
| Pattern construction | Decides how to fill the window (hard-coded, config, etc.). |
| Tiling guarantee | Ensures no gaps, no overlaps in the window. |

### ChannelManager Owns

| Concern | Detail |
|---|---|
| Execution | Plays segments via AIR. |
| Join-in-progress | Computes offset from MasterClock, derives remaining frames. |
| CT-domain switching | Preload, switch-before-exhaustion, emergency fast-path. |
| As-run logging | Records what actually aired. |
| Viewer lifecycle | Start/stop playout based on viewer count. |

### The Hard Rule

ChannelManager MUST NOT:
- Recompute `frame_count` from `duration_seconds`.
- Apply grid rules, zone logic, or editorial policy.
- Query or interpret any artifact other than `Playlist`.
- Branch on the `source` field.

PlaylistScheduleManager MUST NOT:
- Issue commands to AIR or any playout system.
- Know about viewer state, CT cursors, or switch timing.
- Expose grid parameters, slot boundaries, or scheduling internals.

---

## Example Output

### Hard-Coded Two-Hour Window

Configuration: 30fps, 22-minute program + 8-minute interstitial, repeating.

```python
from datetime import datetime, timezone, timedelta
from retrovue.runtime.channel_manager import Playlist, PlaylistSegment

# fps = 30
# program: 39600 frames => duration_seconds = 39600 / 30 = 1320.0
# interstitial: 14400 frames => duration_seconds = 14400 / 30 = 480.0

window_start = datetime(2026, 2, 7, 11, 0, 0, tzinfo=timezone.utc)
window_end   = datetime(2026, 2, 7, 13, 0, 0, tzinfo=timezone.utc)

playlist = Playlist(
    channel_id="retrovue-classic",
    channel_timezone="America/New_York",
    window_start_at=window_start,
    window_end_at=window_end,
    generated_at=datetime(2026, 2, 7, 4, 0, 0, tzinfo=timezone.utc),
    source="HARD_CODED",
    segments=(
        # Block 1: 11:00–11:30
        PlaylistSegment(
            segment_id="seg-20260207-1100-001",
            start_at=datetime(2026, 2, 7, 11, 0, 0, tzinfo=timezone.utc),
            duration_seconds=1320.0,  # 39600 / 30
            type="PROGRAM",
            asset_id="asset-cheers-s01e01",
            asset_path="/mnt/media/cheers/s01e01.mp4",
            frame_count=39600,
        ),
        PlaylistSegment(
            segment_id="seg-20260207-1122-001",
            start_at=datetime(2026, 2, 7, 11, 22, 0, tzinfo=timezone.utc),
            duration_seconds=480.0,  # 14400 / 30
            type="INTERSTITIAL",
            asset_id="asset-filler-retrovue-001",
            asset_path="/mnt/media/filler/retrovue-bumper-01.mp4",
            frame_count=14400,
        ),
        # Block 2: 11:30–12:00
        PlaylistSegment(
            segment_id="seg-20260207-1130-001",
            start_at=datetime(2026, 2, 7, 11, 30, 0, tzinfo=timezone.utc),
            duration_seconds=1320.0,  # 39600 / 30
            type="PROGRAM",
            asset_id="asset-cheers-s01e02",
            asset_path="/mnt/media/cheers/s01e02.mp4",
            frame_count=39600,
        ),
        PlaylistSegment(
            segment_id="seg-20260207-1152-001",
            start_at=datetime(2026, 2, 7, 11, 52, 0, tzinfo=timezone.utc),
            duration_seconds=480.0,  # 14400 / 30
            type="INTERSTITIAL",
            asset_id="asset-filler-retrovue-002",
            asset_path="/mnt/media/filler/retrovue-bumper-02.mp4",
            frame_count=14400,
        ),
        # Block 3: 12:00–12:30
        PlaylistSegment(
            segment_id="seg-20260207-1200-001",
            start_at=datetime(2026, 2, 7, 12, 0, 0, tzinfo=timezone.utc),
            duration_seconds=1320.0,  # 39600 / 30
            type="PROGRAM",
            asset_id="asset-cheers-s01e03",
            asset_path="/mnt/media/cheers/s01e03.mp4",
            frame_count=39600,
        ),
        PlaylistSegment(
            segment_id="seg-20260207-1222-001",
            start_at=datetime(2026, 2, 7, 12, 22, 0, tzinfo=timezone.utc),
            duration_seconds=480.0,  # 14400 / 30
            type="INTERSTITIAL",
            asset_id="asset-filler-retrovue-003",
            asset_path="/mnt/media/filler/retrovue-bumper-03.mp4",
            frame_count=14400,
        ),
        # Block 4: 12:30–13:00
        PlaylistSegment(
            segment_id="seg-20260207-1230-001",
            start_at=datetime(2026, 2, 7, 12, 30, 0, tzinfo=timezone.utc),
            duration_seconds=1320.0,  # 39600 / 30
            type="PROGRAM",
            asset_id="asset-cheers-s01e04",
            asset_path="/mnt/media/cheers/s01e04.mp4",
            frame_count=39600,
        ),
        PlaylistSegment(
            segment_id="seg-20260207-1252-001",
            start_at=datetime(2026, 2, 7, 12, 52, 0, tzinfo=timezone.utc),
            duration_seconds=480.0,  # 14400 / 30
            type="INTERSTITIAL",
            asset_id="asset-filler-retrovue-004",
            asset_path="/mnt/media/filler/retrovue-bumper-04.mp4",
            frame_count=14400,
        ),
    ),
)
```

Tiling verification (frame-based):
- `segments[0].start_at == 11:00:00 == window_start_at`
- Each segment abuts the next via `frame_count / fps`:
  `11:00 + 39600/30s = 11:22`, `11:22 + 14400/30s = 11:30`, ...
- `segments[-1].start_at + 14400/30s == 13:00:00 == window_end_at`
- All `frame_count` values are non-negative.
- `duration_seconds == frame_count / 30` for all segments (exact).

---

## Required Tests

| Test ID | Proves | Summary |
|---|---|---|
| PSM-T001 | INV-PSM-06 | Identical inputs produce identical Playlists (determinism). |
| PSM-T002 | INV-PSM-01, INV-PSM-08 | Tiling holds across multi-day broadcast boundaries. |
| PSM-T003 | INV-PSM-04 | Join-in-progress remaining frames derived from `frame_count`, not `duration_seconds`. |
| PSM-T004 | INV-PSM-01, INV-PSM-08 | Playlist and segment windows cover the full requested range. |
| PSM-T005 | INV-PSM-02, INV-PSM-04 | `duration_seconds == frame_count / fps` (exact) for every segment. |
| PSM-T006 | INV-PSM-02 | `load_playlist` rejects negative `frame_count` with `ValueError`. |
| PSM-T007 | INV-PSM-05 | Frozen dataclass prevents mutation after handoff. |
| PSM-T008 | INV-PSM-03 | Naive (tzinfo-less) datetime arguments are rejected with `ValueError`. |

Test file: `tests/contracts/test_playlist_schedule_manager_contract.py`

---

## Test Specifications

### PSM-T001: Deterministic Output

```
GIVEN: PlaylistScheduleManager with hard-coded configuration
       channel_id = "retrovue-classic"
       window = [2026-02-07T06:00Z, 2026-02-08T06:00Z)
WHEN:  get_playlists() called twice with identical arguments
THEN:  Both calls return identical Playlist objects:
       - Same number of segments
       - Same segment_id, start_at, duration_seconds, frame_count for each
       - Same window_start_at, window_end_at
```

Rationale: INV-PSM-06.  Determinism is required so that a process restart
produces the same Playlist and ChannelManager resumes at the correct position.

### PSM-T002: Broadcast Day Boundary Handling

```
GIVEN: PlaylistScheduleManager with hard-coded 30-min pattern
       window spans two broadcast days:
         window_start_at = 2026-02-07T11:00:00Z (today 06:00 ET)
         window_end_at   = 2026-02-09T11:00:00Z (day after tomorrow 06:00 ET)
WHEN:  get_playlists() called
THEN:  Returned Playlists tile the full 48-hour window with no gaps.
       The segment at the day boundary (2026-02-08T11:00:00Z) is present
       and correctly abuts its neighbours.
       No segment straddles the window boundary (each segment is fully
       within its Playlist's window).
```

Rationale: INV-PSM-01, INV-PSM-08.  Day boundaries are a common source of
off-by-one errors in broadcast scheduling.

### PSM-T003: Join-In-Progress Frame Correctness

```
GIVEN: Playlist with segment:
         start_at = 2026-02-07T11:00:00Z
         frame_count = 39600  (1320.0s at 30fps)
         duration_seconds = 1320.0  (39600 / 30)
WHEN:  Viewer joins at 2026-02-07T11:10:00Z (600s into segment)
       ChannelManager calls _playlist_segment_to_plan(seg, 600.0)
THEN:  Returned plan has:
         frame_count = 39600 - round_half_up(600.0 * 30) = 39600 - 18000 = 21600
         start_pts = 600000  (ms)
       CT exhaustion computed from remaining_frames (21600), not from
       duration_seconds.
```

Rationale: INV-PSM-04.  Frame-authoritative execution means the remaining
budget is derived from `frame_count`, not from `duration_seconds`.  This test
validates the handoff: ScheduleManager sets `frame_count`, ChannelManager
computes remaining frames correctly.

### PSM-T004: Playlist Window Coverage

```
GIVEN: PlaylistScheduleManager
       window = [2026-02-07T11:00:00Z, 2026-02-07T13:00:00Z)
WHEN:  get_playlists() called
THEN:  playlists[0].window_start_at == 2026-02-07T11:00:00Z
       playlists[-1].window_end_at == 2026-02-07T13:00:00Z
       For each playlist:
         segments[0].start_at == playlist.window_start_at
         segments[-1].start_at + timedelta(seconds=segments[-1].frame_count / fps)
           == playlist.window_end_at
         Consecutive segments abut exactly (frame-based):
           segments[n+1].start_at == segments[n].start_at + timedelta(seconds=segments[n].frame_count / fps)
       No gaps between consecutive playlists.
```

Rationale: INV-PSM-01, INV-PSM-08.  This is the foundational coverage test.

### PSM-T005: Frame Math Consistency

```
GIVEN: PlaylistScheduleManager at 30fps
WHEN:  get_playlists() called for any window
THEN:  For EVERY segment in EVERY returned Playlist:
         frame_count >= 0                              (INV-PSM-02)
         duration_seconds == frame_count / fps          (INV-PSM-04, exact)
           Validated: abs(duration_seconds - frame_count / fps) < 1e-9
       Segment abutment is frame-consistent:
         segments[n+1].start_at == segments[n].start_at
           + timedelta(seconds=segments[n].frame_count / fps)
```

Rationale: INV-PSM-02, INV-PSM-04.  `duration_seconds` is derived exactly from
`frame_count / fps`.  No rounding, no "within one frame" tolerance on the
duration derivation itself.

### PSM-T006: Negative Frame Count Rejection

```
GIVEN: A manually constructed Playlist with one segment having frame_count = -1
WHEN:  ChannelManager.load_playlist() called with this Playlist
THEN:  ValueError is raised.
       _playlist remains unchanged (previous value or None).
       Error is logged at ERROR level with segment_id and frame_count.
```

Rationale: INV-PSM-02.  This is the enforcement boundary — ScheduleManager
must not produce it, ChannelManager must reject it.

### PSM-T007: Immutability After Return

```
GIVEN: PlaylistScheduleManager returns a Playlist
WHEN:  Caller attempts to mutate any field of the Playlist or any segment
THEN:  AttributeError is raised (frozen dataclass).
       Original Playlist is unchanged.
```

Rationale: INV-PSM-05.  Playlists are `frozen=True` dataclasses.

### PSM-T008: Naive Datetime Rejection

```
GIVEN: PlaylistScheduleManager
WHEN:  get_playlists() called with naive (tzinfo=None) window_start_at
THEN:  ValueError is raised.
       No Playlist is produced.
```

Rationale: INV-PSM-03.  All timestamps in the system are timezone-aware.

---

## Glossary

| Term | Definition |
|---|---|
| **PlaylistScheduleManager** | The sole producer of Playlists.  Produces Playlists from hard-coded or configuration-driven data.  Does not expose scheduling internals. |
| **Playlist** | A time-bounded, linear, ordered list of executable segments.  The contract surface between scheduling and execution. |
| **PlaylistSegment** | A single executable entry in a Playlist.  Carries frame-authoritative `frame_count`. |
| **frame_count** | Total frames in a segment played from offset 0.  Authoritative for execution.  Set by the producer, never recomputed by the consumer. |
| **ROUND_HALF_UP** | Rounding rule for seconds-to-frames conversion: `floor(x + 0.5)` for non-negative x.  Used consistently by both producer and consumer. |
| **Broadcast day** | A scheduling day typically starting at 06:00 local time.  Broadcast-day boundaries are computed by the caller, not by PlaylistScheduleManager. |
| **Window** | The time span covered by a Playlist, defined by `window_start_at` and `window_end_at`. |
| **Tiling** | The property that segments (or Playlists) cover a time range with no gaps and no overlaps. |
