# Channel YAML Reference

Authoritative reference for the `<channel>.yaml` file format used to define
RetroVue channel programming.

Each channel is defined by a single YAML file in `config/channels/`.
The schedule compiler reads these files and produces grid-aligned program
schedules that drive 24/7 playout.

---

## Minimal Example

```yaml
channel: cheers-24-7
number: 101
name: "Cheers 24/7"
channel_type: network
timezone: America/New_York

format:
  video: { width: 968, height: 720, frame_rate: "30000/1001" }
  audio: { sample_rate: 48000, channels: 2 }
  grid_minutes: 30

filler: !include _defaults.yaml:filler

pools:
  cheers:
    match:
      type: episode
      series_title: Cheers

schedule:
  all_day:
    - block:
        start: "06:00"
        duration: "24h"
        title: "Cheers"
        pool: cheers
        mode: sequential
```

---

## Top-Level Keys

### Required

| Key | Type | Description |
|-----|------|-------------|
| `channel` | string | Unique channel identifier (slug). Used as the canonical channel ID everywhere in the system. Must be lowercase with hyphens. |
| `number` | int | **Required.** Positive integer, unique across all channels. Used as Plex GuideNumber and XMLTV `<channel id>`. See [Channel Numbering](channels/channel_numbering.md). Legacy: `channel_number` is accepted if `number` is missing. |
| `timezone` | string | IANA timezone (e.g. `America/New_York`). All schedule times are interpreted in this zone. |
| `schedule` | dict | The programming schedule. See [Schedule](#schedule). |

### Optional

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `channel_number` | int | — | **Legacy.** Use `number` instead. Accepted for backward compatibility when `number` is absent. |
| `name` | string | — | Human-readable display name. |
| `channel_type` | string | `network` | Determines break placement strategy. See [Channel Types](#channel-types). |
| `template` | string | `network_television` | Grid template. `network_television` = 30-min grid, `premium_movie` = 15-min grid. |
| `format` | dict | — | Video/audio encoding specs. See [Format](#format). |
| `filler` | dict | — | Filler asset for ad breaks. Typically loaded via `!include`. See [Filler](#filler). |
| `pools` | dict | — | Named asset pools for episode/movie selection. See [Pools](#pools). |
| `templates` | dict | — | Reusable schedule templates. See [Templates](#templates). |
| `notes` | dict | — | Human-readable notes (ignored by compiler). |
| `traffic` | dict | — | Ad break traffic rules. See [Traffic](#traffic). |

### Compile-Time (injected by the system)

| Key | Type | Description |
|-----|------|-------------|
| `broadcast_day` | string | ISO date (`YYYY-MM-DD`). Injected at compile time — not authored in the YAML. |

---

## Channel Types

The `channel_type` field controls how ad/promo breaks are placed relative
to content. It does **not** control what fills those breaks (that's `traffic`).

| Type | Grid | Break Placement | Typical Use |
|------|------|-----------------|-------------|
| `network` | 30 min | Mid-content (at chapter markers) | Sitcoms, dramas, episodic TV |
| `movie` | 30 min | Post-content only (movie plays uninterrupted) | HBO, Showtime-style premium |

**`network`** — emulates ad-supported broadcast/cable:
```
[Act 1] -> [Ad Break] -> [Act 2] -> [Ad Break] -> [Act 3]
```

**`movie`** — emulates premium channels:
```
[Full Movie] -> [Promos/Filler until next grid slot]
```

See: `docs/contracts/core/channel_types.md`

---

## Format

Video, audio, and grid configuration.

```yaml
format:
  video:
    width: 1280
    height: 720
    frame_rate: "30000/1001"   # NTSC 29.97fps
  audio:
    sample_rate: 48000
    channels: 2
  grid_minutes: 30             # 30 or 15
```

| Field | Type | Description |
|-------|------|-------------|
| `video.width` | int | Output width in pixels |
| `video.height` | int | Output height in pixels |
| `video.frame_rate` | string | Frame rate as fraction (e.g. `"30000/1001"`) |
| `audio.sample_rate` | int | Audio sample rate in Hz |
| `audio.channels` | int | Audio channel count |
| `grid_minutes` | int | Grid slot size: `30` (network) or `15` (premium) |

---

## Filler

The filler asset plays during ad breaks when no other interstitial is
available. Typically loaded from a shared defaults file.

```yaml
filler: !include _defaults.yaml:filler
```

Or defined inline:

```yaml
filler:
  path: /opt/retrovue/assets/filler.mp4
  duration_ms: 3650000
```

| Field | Type | Description |
|-------|------|-------------|
| `path` | string | Absolute path to the filler video file |
| `duration_ms` | int | Duration of the filler file in milliseconds |

---

## Pools

Pools are named, rule-based queries against the asset catalog. They
replace hardcoded asset references and are evaluated at compile time.

### Episode Pool

```yaml
pools:
  cheers:
    match:
      type: episode
      series_title: Cheers
```

### Multi-Series Pool

```yaml
pools:
  all_legal:
    match:
      type: episode
      series_title:
        - "Boston Legal"
        - "Suits"
```

When `series_title` is a list, assets matching **any** title are included
(OR within the field). Multiple fields are AND-combined.

### Movie Pool

```yaml
pools:
  horror_all:
    match:
      type: movie
      genre: horror
```

### Match Criteria

All criteria are AND-combined. Array values within a field are OR-combined.

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | `episode` or `movie` |
| `series_title` | string or string[] | Exact series name(s) |
| `genre` | string or string[] | Genre filter |
| `rating.include` | string[] | Include only these ratings (e.g. `[PG, PG-13]`) |
| `rating.exclude` | string[] | Exclude these ratings (e.g. `[NC-17]`) |
| `max_duration_sec` | int | Maximum duration in seconds |
| `min_duration_sec` | int | Minimum duration in seconds |
| `season` | int, int[], or range | Season number(s). Supports `6`, `[1, 3, 5]`, or `2..10` |
| `episode` | int, int[], or range | Episode number(s). Same syntax as `season` |

### Pool Ordering

Default ordering for matched assets:
- **Episodes:** series_title ASC, season ASC, episode ASC
- **Movies:** title ASC

---

## Schedule

The `schedule` section defines what airs and when. It uses a **layered
day-of-week system** where more specific layers override less specific ones.

### Layer Precedence (highest to lowest)

1. **Specific day:** `monday`, `tuesday`, ..., `sunday`
2. **Day group:** `weekdays` (Mon-Fri), `weekends` (Sat-Sun)
3. **Default:** `all_day` (every day)

Higher layers override specific time slots from lower layers but pass
through all other slots unchanged. Layers merge by start time.

### Valid Schedule Keys

```
all_day, weekdays, weekends,
monday, tuesday, wednesday, thursday, friday, saturday, sunday
```

### Example: Layered Schedule

```yaml
schedule:
  all_day:
    - block:
        start: "06:00"
        end: "20:00"
        title: "Daytime"
        pool: daytime_pool
        mode: sequential

  weekdays:
    - block:
        start: "20:00"
        end: "06:00"
        title: "Weeknight Dramas"
        pool: dramas
        mode: sequential

  weekends:
    - block:
        start: "20:00"
        end: "06:00"
        title: "Weekend Movies"
        pool: movies
        mode: random

  friday:
    - block:
        start: "20:00"
        end: "06:00"
        title: "Friday Night Special"
        pool: specials
        mode: random
```

On Friday, the 20:00-06:00 slot comes from the `friday` layer (overrides
`weekdays`). The 06:00-20:00 slot comes from `all_day` (inherited).

---

## Block Types

Each entry in a schedule layer is one of four block types.

### Episode Block (`block`)

Fills a time range with episodes from one or more pools.

```yaml
- block:
    start: "06:00"
    end: "06:00"         # same as start = full 24h
    title: "Cheers"
    pool: cheers
    mode: sequential
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `start` | string | yes | Start time in `HH:MM` (local timezone) |
| `end` | string | no | End time in `HH:MM`. If end <= start, wraps past midnight. |
| `duration` | string | no | Alternative to `end`. Accepts `24h`, `3h`, `90m`, `3h30m`. |
| `title` | string | no | EPG display title |
| `pool` | string or string[] | yes | Pool ID or list of pool IDs |
| `mode` | string | no | Episode selection mode (default: `sequential`) |

If neither `end` nor `duration` is specified, defaults to 24 hours.

When `start` equals `end` (e.g. both `"06:00"`), fills a full 24-hour
broadcast day.

#### Selection Modes

| Mode | Behavior |
|------|----------|
| `sequential` | Episodes play in catalog order (series, season, episode). Counter persists across blocks within the same compilation. |
| `random` | Random episode each slot. Deterministic per channel (seeded by channel ID). |
| `shuffle` | Round-robin across pools. With a single pool, equivalent to `sequential`. |

#### Multi-Pool Episode Blocks

When `pool` is a list, the behavior depends on `mode`:

```yaml
pool: [cheers, cosby, barney]
mode: shuffle       # round-robin: cheers, cosby, barney, cheers, ...
```

```yaml
pool: [cheers, cosby, barney]
mode: sequential    # cycles through pools sequentially
```

```yaml
pool: [cheers, cosby, barney]
mode: random        # random pool per slot
```

### Movie Marathon (`movie_marathon`)

Fills a time range with back-to-back movies.

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

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `start` | string | yes | Start time `HH:MM` |
| `end` | string | yes | End time `HH:MM` |
| `title` | string | no | EPG display title |
| `movie_selector` | dict | yes | Movie selection config (see below) |
| `allow_bleed` | bool | no | Allow the last movie to extend past `end` (default: `false`) |

**`movie_selector` fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `pool` | string | yes* | Single pool ID |
| `pools` | string[] | yes* | Multiple pool IDs (alternative to `pool`) |
| `mode` | string | yes | Selection mode (`random`) |
| `max_duration_sec` | int | no | Skip movies longer than this |
| `rating.include` | string[] | no | Only include these ratings |
| `rating.exclude` | string[] | no | Exclude these ratings |

*One of `pool` or `pools` is required.

**Bleed behavior:** When `allow_bleed: true`, if the last movie would
end before the marathon's `end` time, one more movie is scheduled even
if it extends past `end`. The compiler's compaction pass resolves the
overlap by pushing the next block forward to the bleed block's
grid-aligned end time.

**Repeat avoidance:** Movies are not repeated within a single marathon
or across marathon blocks in the same broadcast day. If the pool is
exhausted, the used set resets and selection continues.

### Movie Block (`movie_block`)

Schedules a single movie at a specific time.

```yaml
- movie_block:
    start: "20:00"
    movie_selector:
      pool: action_movies
      mode: random
      rating:
        include: [PG, PG-13]
      max_duration_sec: 7200
```

Same `movie_selector` fields as movie marathon.

### Sitcom Block (legacy)

The original slot-based format with explicit per-slot episode selectors.
Used in older configs and test fixtures. For new channels, prefer `block`.

```yaml
- start: "20:00"
  slots:
    - title: "The Cosby Show"
      episode_selector:
        pool: cosby_s3
        mode: sequential
    - title: "Cheers"
      episode_selector:
        pool: cheers_s6
        mode: random
    - title: "Taxi"
      episode_selector:
        pool: taxi_s2
        mode: sequential
```

Each slot occupies one grid period (30 min for network). If an episode's
duration exceeds one grid slot, it claims multiple slots and subsequent
slot definitions are skipped (preemption).

`episode_selector` accepts either `pool` (preferred) or `collection`
(legacy, deprecated).

---

## Templates

Named schedule fragments that can be referenced from the schedule section.

```yaml
templates:
  weeknight_sitcom_block:
    start: "20:00"
    slots:
      - title: "The Cosby Show"
        episode_selector:
          pool: cosby_s3
          mode: sequential
      - title: "Cheers"
        episode_selector:
          pool: cheers_s6
          mode: random

schedule:
  weeknights:
    use: weeknight_sitcom_block
```

The `use` key expands the template inline at compile time.

---

## Traffic

Controls what types of interstitials fill ad breaks and how often they
repeat.

```yaml
traffic:
  allowed_types: [commercial, promo, station_id, psa, stinger, bumper, filler]
  default_cooldown_seconds: 3600
  type_cooldowns:
    commercial: 3600
    promo: 1800
  max_plays_per_day: 0       # 0 = unlimited
```

| Field | Type | Description |
|-------|------|-------------|
| `allowed_types` | string[] | Asset types allowed in ad breaks |
| `default_cooldown_seconds` | int | Minimum seconds before an interstitial can repeat |
| `type_cooldowns` | dict | Per-type cooldown overrides |
| `max_plays_per_day` | int | Max plays per interstitial per day (`0` = unlimited) |

**Note:** `traffic` controls break **content**. `channel_type` controls
break **placement**. These are independent. A `movie` channel with
`allowed_types: [promo]` gets post-movie breaks filled with promos only.

---

## Shared Defaults

The `_defaults.yaml` file in `config/channels/` defines shared
configuration (filler, format, traffic) loaded via `!include`:

```yaml
filler: !include _defaults.yaml:filler
```

Contents of `_defaults.yaml`:

```yaml
filler:
  path: /opt/retrovue/assets/filler.mp4
  duration_ms: 3650000

format:
  video: { width: 968, height: 720, frame_rate: "30000/1001" }
  audio: { sample_rate: 48000, channels: 2 }
  grid_minutes: 30

traffic:
  allowed_types: [commercial, promo, station_id, psa, stinger, bumper, filler]
  default_cooldown_seconds: 3600
  type_cooldowns:
    commercial: 3600
    promo: 1800
  max_plays_per_day: 0
```

---

## Time Model

- **Broadcast day** runs from 06:00 local to 06:00 local the next day.
- All `start`/`end` times in the YAML are in the channel's `timezone`.
- Times before 06:00 (e.g. `"02:00"`) are interpreted as belonging to the
  next calendar day (overnight wrap).
- The compiler converts everything to UTC for storage and execution.
- Daylight Saving transitions preserve wall-clock alignment.

### Duration Syntax

The `duration` field accepts these formats:

| Format | Example | Meaning |
|--------|---------|---------|
| Hours | `24h` | 24 hours |
| Minutes | `90m` | 90 minutes |
| Combined | `3h30m` | 3 hours 30 minutes |
| Spaced | `2h 15m` | 2 hours 15 minutes |

---

## Grid Alignment

All program blocks must start on grid boundaries:

- **Network (30-min grid):** `:00` and `:30` only
- **Premium (15-min grid):** `:00`, `:15`, `:30`, `:45`

The compiler enforces this. Non-aligned start times are a fatal error.

Episode durations are rounded up to the nearest grid slot. A 22-minute
sitcom gets a 30-minute slot. A 45-minute drama gets a 60-minute slot
(2 grid slots).

---

## Complete Examples

### Single-Series Channel

```yaml
channel: soap-opera
channel_number: 10
name: "Soap!"
channel_type: network
timezone: America/New_York

format:
  video: { width: 968, height: 720, frame_rate: "30000/1001" }
  audio: { sample_rate: 48000, channels: 2 }
  grid_minutes: 30

filler: !include _defaults.yaml:filler

pools:
  soap:
    match:
      type: episode
      series_title: "Soap"

schedule:
  all_day:
    - block:
        start: "06:00"
        duration: "24h"
        title: "Soap"
        pool: soap
        mode: sequential
```

### Multi-Series Rotation

```yaml
channel: chicago-dispatch
channel_number: 5
name: "Chicago Dispatch"
channel_type: network
timezone: America/New_York

format:
  video: { width: 1280, height: 720, frame_rate: "30000/1001" }
  audio: { sample_rate: 48000, channels: 2 }
  grid_minutes: 30

filler: !include _defaults.yaml:filler

pools:
  chicago_med:
    match: { type: episode, series_title: "Chicago Med" }
  chicago_fire:
    match: { type: episode, series_title: "Chicago Fire" }
  chicago_pd:
    match: { type: episode, series_title: "Chicago P.D." }

schedule:
  all_day:
    - block:
        start: "06:00"
        duration: "24h"
        title: "Chicago Rotation"
        pool: [chicago_med, chicago_fire, chicago_pd]
        mode: sequential
```

### Mixed Episodes and Movies

```yaml
channel: nightmare-theater
channel_number: 4
name: "Nightmare Theater"
channel_type: network
timezone: America/New_York

format:
  video: { width: 1280, height: 720, frame_rate: "30000/1001" }
  audio: { sample_rate: 48000, channels: 2 }
  grid_minutes: 30

filler: !include _defaults.yaml:filler

pools:
  tales_from_the_crypt:
    match: { type: episode, series_title: "Tales from the Crypt" }
  freddys_nightmares:
    match: { type: episode, series_title: "Freddy's Nightmares" }
  horror_all:
    match: { type: movie, genre: horror }

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

### Premium Movie Channel

```yaml
channel: hbo-classics
channel_number: 6
name: "HBO"
channel_type: movie
timezone: America/New_York

format:
  video: { width: 1280, height: 720, frame_rate: "30000/1001" }
  audio: { sample_rate: 48000, channels: 2 }
  grid_minutes: 30

filler: !include _defaults.yaml:filler

pools:
  hbo_movies:
    match:
      type: movie

schedule:
  all_day:
    - movie_marathon:
        start: "06:00"
        end: "14:00"
        title: "HBO Feature Presentation"
        movie_selector:
          pool: hbo_movies
          mode: random
          max_duration_sec: 10800
        allow_bleed: true
    - movie_marathon:
        start: "14:00"
        end: "22:00"
        title: "HBO Prime"
        movie_selector:
          pool: hbo_movies
          mode: random
          max_duration_sec: 10800
        allow_bleed: true
    - movie_marathon:
        start: "22:00"
        end: "06:00"
        title: "HBO Late Night"
        movie_selector:
          pool: hbo_movies
          mode: random
          max_duration_sec: 10800
        allow_bleed: true

traffic:
  allowed_types: [promo]
  default_cooldown_seconds: 7200
  max_plays_per_day: 3
```

---

## Related Documents

- `docs/contracts/core/programming_dsl.md` — Two-tier architecture and compiler contract
- `docs/contracts/core/programming_pools.md` — Pool definition and match criteria details
- `docs/contracts/core/channel_types.md` — Channel type and break placement contract
- `docs/contracts/core/programming_dsl.schema.json` — JSON schema for compiled output
