# Building a Channel Schedule from Scratch

This guide walks through creating a RetroVue channel schedule using YAML, explains what happens behind the scenes at each stage, and covers the patterns used by existing channels.

Every channel in RetroVue is defined by a single YAML file. That file is the complete editorial intent for the channel -- what airs, when, wrapped in what presentation, and what fills the breaks.

---

## Prerequisites

Before building a schedule, you need:

1. **Ingested content** -- Movies, episodes, or other media imported through the ingest pipeline. Each asset has probed metadata (duration, codec info, chapter markers if present).
2. **A channel concept** -- What the channel airs, when, and in what style (premium movie channel, sitcom block, themed marathon, etc.).

---

## The Channel YAML File

Every channel is defined by a single YAML file in `config/dsl/`. This file is the **sole editorial input** for the channel -- the schedule compiler reads it and produces everything downstream.

### Minimal Example

The simplest possible channel loops a single pool of content 24 hours a day:

```yaml
channel: my-channel
timezone: America/New_York
grid_minutes: 30

pools:
  episodes:
    select:
      where:
        type: { eq: episode }
        series_title: { eq: "Cheers" }

schedule:
  all_day:
    - block:
        start: "06:00"
        end: "06:00"
        title: "Cheers Marathon"
        pool: episodes
        mode: sequential
```

This creates a channel that plays Cheers episodes back-to-back, 24 hours a day, advancing sequentially through the series. The broadcast day runs from 06:00 to 06:00 the next day.

### Required Top-Level Fields

| Field | Purpose |
|---|---|
| `channel` | Unique slug identifier (used in URLs, file references) |
| `timezone` | IANA timezone string. All `start`/`end` times in the schedule are interpreted in this zone. |
| `grid_minutes` | Grid slot duration in minutes (typically `30`). All block start times must align to grid boundaries. |

Optional top-level fields include `notes` (for `vibe` and `tagline` metadata), `number`, `name`, and `channel_type`.

The full top-level structure of a channel YAML is:

```yaml
channel: <slug>
timezone: <IANA timezone>
grid_minutes: <int>

pools: { ... }           # Asset set definitions.
programs: { ... }        # Program assembly definitions.
presentation: { ... }    # Preroll/postroll structure.
traffic: { ... }         # Traffic profiles and config.
obligations: [ ... ]     # Clock/daypart obligations (Tier 2).
schedule: { ... }        # Time-grid programming.
```

---

## Pools: Defining Your Content Sets

Pools are declarative queries that define sets of candidate assets. A pool says *what* content is eligible -- it does not say how to select from it or in what order.

### Pool Selection Syntax

The canonical syntax uses `select.where` with explicit operators:

```yaml
pools:
  sitcom_episodes:
    select:
      where:
        type: { eq: episode }
        series_title: { eq: "Cheers" }
```

Available operators:

| Operator | Purpose | Example |
|---|---|---|
| `eq` | Exact match | `type: { eq: episode }` |
| `in` | Match any in list | `rating: { in: ["PG", "PG-13"] }` |
| `contains_all` | Tags must include all | `tags: { contains_all: ["classic", "sitcom"] }` |
| `contains_any` | Tags must include at least one | `tags: { contains_any: ["horror", "thriller"] }` |
| `excludes_any` | Tags must not include any | `tags: { excludes_any: ["documentary"] }` |

> **Migration note:** Existing channel YAML files may still use the legacy `match` syntax (e.g., `match: { type: episode }`). The runtime normalizer accepts both forms, but `select.where` is the canonical form per `INV-DSL-QUERY-CANONICAL-001`. New channels should use `select.where` exclusively.

### Multiple Pools

Define as many pools as you need. Different schedule blocks can draw from different pools:

```yaml
pools:
  tng:
    select:
      where:
        type: { eq: episode }
        series_title: { eq: "Star Trek: The Next Generation" }
  ds9:
    select:
      where:
        type: { eq: episode }
        series_title: { eq: "Star Trek: Deep Space Nine" }
  voyager:
    select:
      where:
        type: { eq: episode }
        series_title: { eq: "Star Trek: Voyager" }
```

### Pool Rules

- Pools are **pure queries** -- they return matching assets and nothing else.
- Pools must not contain selection strategy, ordering, or rotation logic. That belongs in the program or schedule block.
- An empty pool (zero matching assets) does not crash compilation. The compiler logs a warning and the segment is omitted per `INV-DSL-MISSING-ASSET-NONFATAL-001`.

---

## Programs: Reusable Content Assembly Rules

A **program** is a reusable assembly rule that transforms eligible assets (from a pool) into a broadcastable structural unit. Programs define *how* content is selected and packaged -- they are not schedule blocks and they are not time-bound.

The distinction matters:

| Concept | What it does |
|---|---|
| **Pool** | Declares *which* assets are eligible (a query) |
| **Program** | Defines *how* to assemble those assets into a broadcastable unit (an assembly rule) |
| **Schedule block** | Binds a program to a *time slot* in the grid |

### Program Definition

```yaml
programs:
  hbo_movies_r:
    pool: movies                   # Base pool reference.
    select:                        # Optional narrowing query.
      where:
        rating: { eq: "R" }
    grid_blocks_max: 5             # Dynamic grid sizing (see below).
    fill_mode: single              # single | accumulate
    presentation: movies           # References presentation.programs.<name>.
    bleed: false
```

### Program Fields

| Field | Required | Description |
|---|---|---|
| `pool` | Yes | Reference to a named pool. |
| `select` | No | Additional `where` clause narrowing the pool for this program. |
| `grid_blocks` | One of `grid_blocks` / `grid_blocks_max` | Fixed grid slot count per execution. |
| `grid_blocks_max` | One of `grid_blocks` / `grid_blocks_max` | Maximum grid slots; actual count is `ceil(structural_runtime / grid_slot)`. |
| `fill_mode` | Yes | `single` (one asset per execution) or `accumulate` (pack assets to fill grid). |
| `bleed` | No (default false) | Whether content may overrun its grid allocation into the next block. |
| `presentation` | No | Reference to a named presentation definition under `presentation.programs`. |

### grid_blocks vs grid_blocks_max

These are mutually exclusive grid allocation strategies:

- **`grid_blocks`** -- A **fixed slot count**. The block always occupies exactly this many grid slots regardless of content duration. Useful for episodic TV where episodes have consistent runtimes and you want predictable grid layout.

- **`grid_blocks_max`** -- A **candidate selection constraint** that limits the maximum size/runtime of assets eligible for scheduling. The actual grid allocation is computed dynamically: `actual_blocks = ceil(structural_runtime_sec / grid_slot_sec)`. The grid grows to accommodate structural content; structural segments are never dropped to fit. Useful for movies and other variable-length content.

### bleed

A **boundary-overrun policy** that determines whether the final scheduled asset may extend beyond the block or grid boundary:

- `bleed: false` (default) -- Content iteration MUST NOT begin if the minimum duration exceeds remaining window capacity (capacity gating). The block stays within its allocated time.
- `bleed: true` -- The final content iteration MAY exceed remaining capacity. The next block begins where the bleed ends, not at the nominal grid boundary. Bleed programs have an empty break plan -- no commercial breaks are inserted when content overruns the allocation.

### fill_mode

- **`single`** -- One asset per program execution. A 2-hour movie block selects one movie.
- **`accumulate`** -- Pack multiple assets to fill the grid allocation. A 6-hour sitcom block selects episodes sequentially until the window is full.

---

## Obligations: Clock and Daypart Requirements (Tier 2)

Obligations are clock-scoped or daypart-scoped structural requirements -- content that fires on a schedule regardless of what's airing. They are Tier 2 in the assembly model and override block structure.

```yaml
obligations:
  - type: station_id
    pool: station_ids
    interval_minutes: 60
    mandatory: true

  - type: legal_id
    pool: legal_ids
    interval_minutes: 60
    mandatory: true

  - type: daypart_transition
    pool: daypart_bumpers
    at_daypart_boundaries: true
```

### Obligation Types

| Type | Purpose | Trigger |
|---|---|---|
| `station_id` | FCC-required station identification | Every N minutes on the clock |
| `legal_id` | Legal/regulatory identification | Every N minutes on the clock |
| `daypart_transition` | Daypart boundary bumper | At daypart boundary times |

### Obligation Placement Rules

Obligations are placed based on where their trigger time falls:

1. **Within an existing break** -- The obligation is inserted into the break, displacing Tier 4 fill. The break's fill budget is reduced by the obligation's duration.
2. **Before primary content** -- Prepended at the head of the block.
3. **After primary content** -- Appended at the tail of the block.
4. **At a block boundary** -- Prepended before Tier 1 presentation.
5. **Deferred** -- If no valid placement exists within the current block, deferred to the next valid position per conformance policy.

Obligations MUST NOT be inserted into uninterrupted primary content. Content integrity is paramount -- a movie or episode in progress is never interrupted by an obligation insertion.

> **Note on break-scoped station IDs vs clock obligations:** There are two separate station ID mechanisms:
> - `traffic.break_config.station_id_ms` -- A slot reserved *inside each commercial break* (break-scoped, Tier 4 structural). Used for network-style channels with regular breaks.
> - `obligations[].type: station_id` -- Clock-triggered, fires every N minutes regardless of breaks (Tier 2). Used for premium channels like HBO with no commercial breaks.
>
> For a premium channel, use the clock obligation. If you currently have a station ID baked into a program's postroll presentation, that fires once per program block (Tier 1 behavior). The obligations approach fires on the clock, which is correct for FCC compliance.

### Obligation Properties

- Obligations require no persisted state (`INV-TIER2-OBLIGATION-YAML-ONLY-001`). They are evaluated deterministically from config + block boundaries at each compilation.
- Same config + same block boundaries produce identical obligations across compilations.
- Mandatory obligations cannot be suppressed by template configuration.
- Multiple obligations at the same trigger time stack in YAML declaration order.

---

## Schedule: Programming the Grid

The `schedule` section binds programs or inline block definitions to time slots. It uses a layered override model where more specific layers replace less specific ones.

### Layer Priority (highest wins)

1. `dates:` -- Exact dates (e.g., `"10-31"` for Halloween specials)
2. Day names -- `monday`, `tuesday`, ..., `sunday`
3. `weekdays:` / `weekends:`
4. `all_day:` -- Default for every day

Higher-priority layers fully replace lower-priority ones for overlapping time slots.

### Schedule Block Boundary Styles

Schedule blocks define their time window using one of three mutually exclusive boundary styles:

| Style | Format | Description |
|---|---|---|
| `start` + `end` | `HH:MM` times | Explicit wall-clock start and end. Most common in current YAML. |
| `start` + `slots` | `HH:MM` + integer | Start time plus grid slot count. Canonical form per the DSL contract. |
| `start` + `duration` | `HH:MM` + minutes | Start time plus duration. Derived from `slots * grid_minutes`. |

All three forms are normalized into a **single canonical start/end representation** at compile time. `start` + `slots` is the canonical form; `start` + `end` and `start` + `duration` are ergonomic equivalents. All block start times must align to grid boundaries (`grid_minutes` multiples from the broadcast day start).

### Schedule Blocks

Each entry in a schedule layer defines a programming block:

```yaml
schedule:
  all_day:
    - block:
        start: "06:00"
        end: "12:00"
        title: "Morning TNG"
        pool: tng
        mode: sequential
```

#### Block Fields

| Field | Required | Description |
|---|---|---|
| `start` | Yes | Grid-aligned start time (`HH:MM`). |
| `end` | Yes (or `slots`/`duration`) | End time. Use `"06:00"` to wrap to next broadcast day start. |
| `title` | Yes | Display title for EPG. |
| `pool` | Yes | Pool name or list of pool names. |
| `mode` | Yes | Content selection mode: `sequential`, `random`, or `shuffle`. |

Optional fields:

| Field | Default | Description |
|---|---|---|
| `bleed` | `false` | Allow content to overrun its grid allocation into the next block. |
| `program` | (none) | Reference to a named program definition instead of inline pool/mode. |

### Content Selection Modes

**`sequential`** -- Plays content in series order (Season 1 Episode 1, then Episode 2, etc.). A persistent cursor advances across days. When the series ends, it wraps back to the beginning.

**`random`** -- Seeded random selection per execution. Deterministic for the same seed, so recompiling the same day produces the same schedule.

**`shuffle`** -- Shuffles the entire pool, then plays through sequentially. When exhausted, reshuffles and starts over. Good for variety channels.

### Multi-Pool Blocks

Pass a list of pools to mix content from multiple series:

```yaml
- block:
    start: "06:00"
    end: "06:00"
    title: "Retro Prime"
    pool: [batman, barney, cheers, cosby]
    mode: shuffle
```

This shuffles episodes from all four series together, creating a varied rotation.

### Day-of-Week Overrides

Override the default schedule for specific days:

```yaml
schedule:
  all_day:
    - block:
        start: "06:00"
        end: "06:00"
        title: "Weekday Programming"
        pool: sitcoms
        mode: sequential

  sunday:
    - block:
        start: "14:00"
        end: "22:00"
        title: "Sunday Movie Marathon"
        pool: movies
        mode: random
```

On Sundays, the 14:00-22:00 window is replaced by the movie marathon. Times outside that window still use the `all_day` schedule.

---

## Movie Marathons

Movies get special handling because their runtimes vary widely. Use the `movie_marathon` block type:

```yaml
- movie_marathon:
    start: "09:00"
    end: "22:00"
    title: "Horror Movie Marathon"
    movie_selector:
      pool: horror_all
      mode: random
      max_duration_sec: 9000
    allow_bleed: true
```

#### How It Works

The compiler fills the time window by selecting movies from the pool one at a time, accumulating until the window is full. `max_duration_sec` filters out movies longer than the specified duration (2.5 hours in this example) to prevent a single film from consuming too much of the window. `allow_bleed: true` lets the last movie overrun the end time rather than cutting it short.

### 24-Hour Movie Channel

For a channel that plays movies around the clock:

```yaml
- movie_marathon:
    start: "06:00"
    end: "06:00"
    title: "HBO Feature Presentation"
    movie_selector:
      pool: all_movies
      mode: random
      max_duration_sec: 10800
    allow_bleed: true
```

---

## Real Channel Examples

### Trek TV -- Multi-Series Daypart Rotation

Divides the day into four 6-hour blocks, each dedicated to a different Star Trek series:

```yaml
channel: trek-tv
timezone: America/New_York
grid_minutes: 30

pools:
  tng:
    select:
      where:
        type: { eq: episode }
        series_title: { eq: "Star Trek: The Next Generation" }
  ds9:
    select:
      where:
        type: { eq: episode }
        series_title: { eq: "Star Trek: Deep Space Nine" }
  voyager:
    select:
      where:
        type: { eq: episode }
        series_title: { eq: "Star Trek: Voyager" }
  snw:
    select:
      where:
        type: { eq: episode }
        series_title: { eq: "Star Trek: Strange New Worlds" }

schedule:
  all_day:
    - block:
        start: "06:00"
        end: "12:00"
        title: "The Next Generation"
        pool: tng
        mode: sequential
    - block:
        start: "12:00"
        end: "18:00"
        title: "Deep Space Nine"
        pool: ds9
        mode: sequential
    - block:
        start: "18:00"
        end: "00:00"
        title: "Voyager"
        pool: voyager
        mode: sequential
    - block:
        start: "00:00"
        end: "06:00"
        title: "Strange New Worlds"
        pool: snw
        mode: sequential
```

Each series plays sequentially through its episodes, advancing day after day.

### Nightmare Theater -- Mixed Format

Combines episodic TV blocks with a movie marathon:

```yaml
channel: nightmare-theater
timezone: America/New_York
grid_minutes: 30

pools:
  tales_from_the_crypt:
    select:
      where:
        type: { eq: episode }
        series_title: { eq: "Tales from the Crypt" }
  freddys_nightmares:
    select:
      where:
        type: { eq: episode }
        series_title: { eq: "Freddy's Nightmares" }
  horror_all:
    select:
      where:
        type: { eq: movie }
        tags: { contains_any: ["horror"] }

schedule:
  all_day:
    - block:
        start: "06:00"
        end: "09:00"
        title: "Freddy's Nightmares"
        pool: freddys_nightmares
        mode: sequential
    - movie_marathon:
        start: "09:00"
        end: "22:00"
        title: "Horror Movie Marathon"
        movie_selector:
          pool: horror_all
          mode: random
          max_duration_sec: 9000
        allow_bleed: true
    - block:
        start: "22:00"
        end: "06:00"
        title: "Tales from the Crypt"
        pool: tales_from_the_crypt
        mode: sequential
```

### HBO Classics -- Premium Movie Channel

A 24-hour premium movie channel with clock-triggered station IDs and no commercial breaks:

```yaml
channel: hbo-classics
timezone: America/New_York
grid_minutes: 30
notes:
  vibe: "HBO -- premium movies all day, every day"
  tagline: "It's Not TV. It's HBO."

pools:
  all_movies:
    select:
      where:
        type: { eq: movie }
  station_ids:
    select:
      where:
        type: { eq: interstitial }
        tags: { contains_all: ["station-id"] }

obligations:
  - type: station_id
    pool: station_ids
    interval_minutes: 60
    mandatory: true

schedule:
  all_day:
    - movie_marathon:
        start: "06:00"
        end: "06:00"
        title: "HBO Feature Presentation"
        movie_selector:
          pool: all_movies
          mode: random
          max_duration_sec: 10800
        allow_bleed: true
```

The station ID fires every 60 minutes on the clock, placed within existing breaks or at block boundaries -- never interrupting a movie in progress.

### Saturday Supercade -- All-Day Shuffle

A single block shuffles episodes from multiple cartoon series across the entire broadcast day:

```yaml
channel: saturday-supercade
timezone: America/New_York
grid_minutes: 30

pools:
  supercade:
    select:
      where:
        type: { eq: episode }
        series_title: { eq: "Saturday Supercade" }
  mario:
    select:
      where:
        type: { eq: episode }
        series_title: { eq: "Super Mario World" }
  xmen:
    select:
      where:
        type: { eq: episode }
        series_title: { eq: "X-Men '97" }

schedule:
  all_day:
    - block:
        start: "06:00"
        end: "06:00"
        title: "Cartoon Block"
        pool: [supercade, mario, xmen]
        mode: shuffle
```

---

## What Happens Behind the Scenes

When the schedule compiler processes your YAML, a multi-stage pipeline transforms editorial intent into an execution-ready playout plan.

### Stage 1: DSL Parsing and Validation

The compiler parses the YAML and validates:

- All required fields are present
- Pool `select.where` clauses use valid operators
- Pool references point to defined pools
- Start/end times align to the grid (`grid_minutes`)
- No overlapping blocks within a schedule layer
- `grid_blocks` and `grid_blocks_max` are not both set on any program

### Stage 2: Day Resolution

For a given broadcast day, the compiler resolves which schedule layer applies. If today is Sunday and both `all_day` and `sunday` layers exist, the `sunday` layer overrides `all_day` for any overlapping time slots.

The broadcast day runs from `day_start_hour` (default 06:00) to the same hour the next calendar day, all in the channel's configured timezone.

### Stage 3: Program Assembly (Tier 0 -- Primary Content)

For each schedule block, the compiler:

1. Queries the pool(s) for matching assets
2. Applies the selection mode (`sequential`, `random`, or `shuffle`)
3. Selects content to fill the block's time allocation
4. For `sequential` mode, advances the persistent cursor so the next compilation picks up where this one left off

The selected content is **Tier 0 -- Primary Content**. It is atomic and never cut, shifted, or truncated. A movie that runs 1 hour 47 minutes is scheduled for exactly 1 hour 47 minutes. The grid allocation expands if needed.

### Stage 4: Break Detection and Budget Derivation

The compiler identifies where commercial breaks can be placed. Break positions follow a strict priority:

1. **Chapter markers** (if present in asset metadata) -- Natural story break points embedded during production
2. **Asset boundaries** -- Seams between accumulated content segments (e.g., between episodes)
3. **Algorithmic placement** -- Synthetic breaks spaced using `target_segment_minutes`

These sources follow a fallback model (`INV-BREAK-PLACEMENT-FALLBACK-001`): chapter markers are used when present and suppress algorithmic placement for the same asset. Algorithmic placement activates only when neither chapter markers nor sufficient boundary opportunities exist.

#### Break Detection Constraints

Break placement is subject to several constraints:

- **Protected zone** (`INV-BREAK-003`): No algorithmic break may be placed within the first 20% of program runtime. Chapter markers and asset boundaries are exempt from this constraint -- they represent editorial or structural intent and are always respected.
- **Cold open protection** (`INV-BREAK-010`): No algorithmic break before the first chapter marker within a segment.
- **Non-uniform spacing** (`INV-BREAK-007`): For 2+ algorithmic breaks, intervals must widen toward the end of the program. Equal spacing is prohibited. Later breaks also receive a larger share of the break budget (non-uniform weight distribution).
- **Intro/outro protection** (`INV-BREAK-009`): No breaks within intro or outro segments. Transitions between segments are not break opportunities.
- **Boundary count**: Accumulate-mode programs with N content segments produce exactly (N-1) boundary opportunities. Single-segment programs produce zero boundary opportunities.

When no valid break positions exist (e.g., a short program where the protected zone eliminates all algorithmic candidates and no chapter markers or boundaries exist), break detection returns an empty opportunities list. The entire break budget becomes post-content padding.

#### Break Budget

The **break budget** is derived, never fixed:

```
break_budget = scheduled_duration - content_duration - presentation_duration
```

For a 30-minute grid slot with a 22-minute episode and a 15-second intro:

```
break_budget = 1800s - 1320s - 15s = 465s (7:45)
```

Zero or negative budget means no breaks (empty opportunities list). The budget is derived from *total assembled runtime* (Tiers 0-3), not raw asset duration.

Break count is derived from content runtime divided by the template's `target_segment_minutes`. Each break's duration is allocated proportionally based on weights (later breaks receive more time).

### Stage 5: Break Structure

Each break is internally structured in a canonical order:

```
[to-break bumper] -> [interstitial slots] -> [station ID] -> [from-break bumper]
```

Bumpers are the short "We'll be right back" / "And now back to..." clips. The interstitial slots are where traffic fill (commercials, promos, trailers) will be packed. Station IDs are the break-scoped legal identification clips (via `traffic.break_config.station_id_ms`).

### Stage 6: Clock Obligation Evaluation (Second Pass)

After primary assembly and break detection, the compiler runs a second pass to evaluate Tier 2 clock obligations. For each obligation defined in the YAML, the compiler checks whether its trigger time falls within the current block and places it:

- **Within an existing break** -- Inserted into the break, displacing Tier 4 fill.
- **At a block boundary** -- Prepended before Tier 1 presentation.
- **Before or after primary content** -- Placed at the next valid structural seam.

Obligations never interrupt unbroken primary content. If a trigger falls within primary content, it defers to the next valid placement point (break, block boundary, or post-content). Primary content remains atomic per `INV-PRIMARY-CONTENT-UNINTERRUPTIBLE-001` and `INV-MOVIE-PRIMARY-ATOMIC`.

### Stage 7: Tier Assembly

The full tier model builds the complete block:

| Tier | Name | Content | When Resolved |
|------|------|---------|---------------|
| **0** | Primary Content | Movie, episode, event | Compile time |
| **1** | Mandatory Presentation | Intro, rating card | Compile time |
| **2** | Clock Obligations | Station ID at top of hour, legal ID | Second compilation pass (wall-clock) |
| **3** | Optional Presentation | "Coming up next" promo, channel ident | Compile time (with next-block lookahead) |
| **4** | Traffic Fill | Commercials, promos, trailers | Playlog plan generation time |

Tiers 0-3 are fully resolved (asset selected, duration known) at compile time. Tier 4 is filled later, hours before air, when traffic inventory is most current.

### Stage 8: Compiled Output -- ScheduleRevision

The compiled output is written to the database as a **ScheduleRevision** -- an immutable snapshot of the editorial schedule for one channel-day. A ScheduleRevision contains **ScheduleItems**, each representing a compiled block with all structural segments resolved.

ScheduleRevisions are append-only and immutable once published. If the schedule changes, a new revision supersedes the old one.

### Stage 9: Playlog Plan Generation

A background daemon monitors the playlog plan depth (2-3+ hours ahead of current time). When depth runs low, it reads the next ScheduleItems from the program schedule and runs the **traffic manager** to fill Tier 4 break slots with actual interstitial assets.

The result is a **PlaylistEvent** -- the fully resolved, execution-ready playout plan with real asset URIs, timecodes, and filled breaks.

### Stage 10: Runtime Execution

When a viewer tunes in:

1. **ProgramDirector** determines what should be airing right now based on wall clock
2. ProgramDirector generates a playout plan with the correct offset (join-in-progress)
3. ProgramDirector starts **AIR** (the C++ playout engine) for that channel if not already running
4. AIR begins emitting MPEG-TS bytes at the correct position in the current program
5. Multiple viewers on the same channel share the same playout instance

The channel's timeline advances with wall clock whether or not anyone is watching. When the last viewer leaves, playout stops -- but the schedule keeps advancing. The next viewer gets seamless join-in-progress at wherever the schedule has reached.

---

## The Two-Layer Horizon Model

RetroVue maintains two rolling horizons:

### Program Schedule Horizon (2-3 days ahead)

The DSL compiler produces ScheduleRevisions 2-3 days into the future. When a day falls off the trailing edge (it's now in the past), the compiler generates the next day at the leading edge.

This horizon drives:
- EPG (Electronic Program Guide) generation
- Schedule introspection and debugging
- Playlog plan generation

### Playlog Plan Horizon (2-3+ hours ahead)

PlaylistEvents are generated from the program schedule with traffic fill applied. This horizon is shorter because traffic inventory should be current -- selecting ads days in advance would risk stale inventory.

This horizon drives:
- Actual playout execution
- What AIR receives and plays

---

## Determinism and Reproducibility

RetroVue schedules are **deterministic**: the same YAML, same content library, and same seed produce the identical schedule every time. This means:

- Restarting the system produces the same timeline
- Debugging a past schedule is straightforward -- recompile with the same inputs
- Sequential progression cursors persist, so episodes don't repeat or skip after a restart

Each channel has an independent PRNG seed. Channels do not influence each other's schedules.

---

## Cross-Midnight Continuity

Content that spans midnight (the broadcast day boundary) is handled via **carry-in** semantics. If a movie starts at 23:30 on Monday and runs until 01:15 on Tuesday, Monday's schedule "carries in" the remainder to Tuesday's schedule. The carry-in state survives system restarts.

This ensures no gaps or awkward cuts at midnight -- the viewing experience is seamless.

---

## Common Patterns

### Single-Series Sequential Channel

The simplest pattern. One series, playing in order, all day:

```yaml
pools:
  cheers:
    select:
      where:
        type: { eq: episode }
        series_title: { eq: "Cheers" }

schedule:
  all_day:
    - block:
        start: "06:00"
        end: "06:00"
        title: "Cheers"
        pool: cheers
        mode: sequential
```

### Daypart Rotation

Different content for different times of day:

```yaml
schedule:
  all_day:
    - block:
        start: "06:00"
        end: "12:00"
        title: "Morning Sitcoms"
        pool: sitcoms
        mode: sequential
    - block:
        start: "12:00"
        end: "18:00"
        title: "Afternoon Drama"
        pool: dramas
        mode: sequential
    - block:
        start: "18:00"
        end: "00:00"
        title: "Prime Time Movies"
        pool: movies
        mode: random
    - block:
        start: "00:00"
        end: "06:00"
        title: "Late Night"
        pool: late_night
        mode: shuffle
```

### Weekend Override

Override weekend programming while keeping weekday defaults:

```yaml
schedule:
  all_day:
    - block:
        start: "06:00"
        end: "06:00"
        title: "Weekday Lineup"
        pool: weekday_shows
        mode: sequential

  weekends:
    - movie_marathon:
        start: "06:00"
        end: "06:00"
        title: "Weekend Movie Marathon"
        movie_selector:
          pool: all_movies
          mode: random
          max_duration_sec: 10800
        allow_bleed: true
```

### Variety Shuffle

Mix multiple series for a channel that feels like tuning into a real broadcast network:

```yaml
pools:
  show_a:
    select:
      where:
        type: { eq: episode }
        series_title: { eq: "Show A" }
  show_b:
    select:
      where:
        type: { eq: episode }
        series_title: { eq: "Show B" }
  show_c:
    select:
      where:
        type: { eq: episode }
        series_title: { eq: "Show C" }

schedule:
  all_day:
    - block:
        start: "06:00"
        end: "06:00"
        title: "The Mix"
        pool: [show_a, show_b, show_c]
        mode: shuffle
```

---

## Key Invariants

| Invariant | Guarantee |
|---|---|
| `INV-DSL-QUERY-CANONICAL-001` | All asset selection uses `select.where` with explicit operators. |
| `INV-BREAK-003` | No algorithmic break in protected zone (first 20% of runtime). |
| `INV-BREAK-007` | Algorithmic break intervals must widen toward end of program. |
| `INV-BREAK-009` | No breaks within intro or outro segments. |
| `INV-BREAK-010` | No algorithmic break before first chapter marker in segment. |
| `INV-BREAK-PLACEMENT-FALLBACK-001` | Chapter markers suppress algorithmic placement for same asset. |
| `INV-MOVIE-PRIMARY-ATOMIC` | Primary content is never cut, truncated, or shifted. |
| `INV-CLOCK-OBLIGATIONS-OVERRIDE-001` | Clock obligations MUST NOT interrupt primary content. If a trigger occurs during primary content, the obligation is deferred to the next valid placement point (break, block boundary, or post-content). |
| `INV-PRIMARY-CONTENT-UNINTERRUPTIBLE-001` | Primary content cannot be interrupted, split, or truncated by any compilation pass. |
| `INV-TIER2-OBLIGATION-YAML-ONLY-001` | Obligations require no persisted state; deterministic from config. |
| `INV-TIER3-BUDGET-BEFORE-FILL-001` | Tier 3 budget is computed before Tier 4 fill. |
| `INV-DSL-GRID-STRUCTURAL-EXPANSION-001` | Grid allocation grows to accommodate structural content. |
| `INV-DSL-MISSING-ASSET-NONFATAL-001` | Missing presentation/obligation pool does not crash compilation. |

---

## Summary: From YAML to Viewer

```
Channel YAML (editorial intent)
    |
    v
Schedule Compiler
    |-- Day resolution (which layer applies today?)
    |-- Program assembly (select content from pools)
    |-- Break detection (where can breaks go? + constraints)
    |-- Clock obligation evaluation (second pass)
    |-- Tier assembly (presentation, obligations, optional elements)
    |-- Grid sizing and conformance check
    v
ScheduleRevision (immutable, in Postgres, 2-3 days ahead)
    |
    v
Playlog Plan Generator (background daemon)
    |-- Read next schedule items
    |-- Fill breaks with traffic inventory (Tier 4)
    v
PlaylistEvent (execution-ready, 2-3 hours ahead)
    |
    v
ProgramDirector (wall-clock lookup, viewer join-in-progress)
    |
    v
AIR (C++ playout engine, MPEG-TS bytes to viewer)
```

The YAML file is where it starts. Everything downstream is derived, deterministic, and auditable.
