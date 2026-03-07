# RetroVue Channel DSL – Architectural Contract

---

## 📺 Purpose

The **RetroVue Channel DSL** allows channels to be described in declarative YAML—capturing editorial intent (what airs, when) while maximizing human readability and ease of historical reconstruction.

- **Describe:** Schedules, pools, reusable programs, movie rotations, intros/outros, etc.
- **Editors:** Write like TV guides, not like software configs.
- **Runtime:** Does precise timing, assembly, and segment expansion.

---

## 1. 🕰️ Channel Time Model

- Every channel defines a **time grid** (e.g., 30 minutes).
- **All program start times** must align to this grid.
- **Schedule blocks** must fill an integer number of grid slots. Programs *may bleed* past their assigned grid boundary as determined by the program's `bleed` property.

```yaml
format:
  grid_minutes: 30
```

`grid_duration` refers to the total runtime allocated by a schedule block:

```
grid_duration = grid_minutes x slots
```

**Example (30-min grid):**

| Scheduled   | Actual Playout         |
|-------------|-----------------------|
| 20:00 Movie | 20:00–22:01           |
| 22:00 Movie | 22:01–00:00           |

The schedule remains elegant, even as actual starts drift for movie overruns.

---

## 2. 🏗️ Layered Schedules (Override Model)

Schedules are composed by **layering overrides**:

**Priority (highest wins):**
1. `dates:` – exact dates (e.g., `"10-31"`)
2. Dayname – e.g., `thursday:`
3. `weekday:` / `weekend:`
4. `all_day:`

```yaml
schedule:
  all_day:
    - start: "00:00"
      slots: 48
      program: overnight_movies
      progression: random

  thursday:
    - start: "20:00"
      slots: 4
      program: must_see_tv
      progression: sequential

  dates:
    "10-31":
      - start: "20:00"
        slots: 4
        program: halloween_movie
        progression: random
```

> If October 31 is a Thursday, the special ("10-31") schedule wins.

---

## 3. ⏳ Schedule Block Duration

Each scheduled block specifies its *length* with exactly one of:

- `end_time`
- `duration`
- `slots`

**Examples:**

```yaml
# Use end_time
start: "20:00"
end_time: "23:00"

# Use duration
start: "20:00"
duration: "3h"

# Use slots (6×30min = 3h)
start: "20:00"
slots: 6
```

*All values must resolve to an integer number of grid slots.*
❌ Invalid (if grid is 30min):
```yaml
duration: 1h45m
```

---

## 4. 🧱 Content Pools

**Pools** define sets of candidate assets only.
> *Pools are asset sources, not progression engines.*

```yaml
pools:
  cheers:
    match:
      type: episode
      series_title: Cheers
  movies:
    match:
      type: movie
      genre: Comedy
```

- Define any number of pools for organizational reuse.
- No progression/cooldowns/rotation logic lives inside pools.

---

## 5. 🎬 Programs (Reusable Program Objects)

**Programs** are first-class, reusable building blocks that define:
- What content to assemble
- How many grid units to target
- Whether to allow bleed (overrun)
- How to fill (single asset, accumulate, etc.)
- Optionally, where to include intro/outro segments

Programs bridge the gap between asset pools and scheduling, making complex lineups reusable and explicit.

**Program fields:**
- `pool`: Which assets to draw from (by pool reference)
- `grid_blocks`: Target slot count (integer)
- `fill_mode`: `single` (single asset, e.g., a movie) or `accumulate` (pack episodes/shorts until slots filled)
- `bleed`: `true` (allow program to overrun slot boundary) or `false` (truncate to fit)
- *(Optional)* `intro`: Asset or segment reference to prepend
- *(Optional)* `outro`: Asset or segment reference to append

**Example:**

```yaml
programs:
  sitcom_hour:
    pool: cheers
    grid_blocks: 2
    fill_mode: accumulate
    bleed: false

  weekend_movie:
    pool: movies
    grid_blocks: 4
    fill_mode: single
    bleed: true
    intro: hbo_intro
```

- **Programs** do NOT need to know about schedule timing—they are reusable recipes for assembling content from pools.
- Programs are editorial abstractions, not specific media assets. A program defines how content is assembled, not what specific asset will play.
- Programs may be referenced by schedule blocks.

### Program Assembly Rules

When a schedule block is executed, RetroVue assembles content according to the referenced program definition. If a schedule block executes a program multiple times (because `slots > program.grid_blocks`), each execution is assembled independently using the program's `grid_blocks` as its target.

1. Select candidate assets from the program's pool according to the schedule block's progression mode.
2. Assemble assets until the program's `grid_blocks` target is satisfied.

Fill modes determine behavior:

**single**
- A single asset is selected.
- If `bleed: true`, the asset may exceed the grid allocation.
- If `bleed: false`, assets longer than the grid allocation are rejected.

**accumulate**
- Assets are appended sequentially until the program reaches or slightly exceeds the grid target.
- Break opportunities exist between accumulated assets.
- If perfect grid fill would eliminate a natural break opportunity, RetroVue prioritizes maintaining natural break cadence over exact content fill. Remaining time is absorbed by break padding.

The assembled program is then passed to the break detection stage.

---

## 6. 📅 Schedule Blocks & Progression

Schedule blocks specify **when** and **how** to deploy programs onto the channel timeline:

```yaml
schedule:
  thursday:
    - start: "20:00"
      slots: 4
      program: weekend_movie
      progression: sequential     # or: shuffle, random
    - start: "00:00"
      slots: 2
      program: sitcom_hour
      progression: random
```

**Progression rules:**
- The progression mode is attached to the schedule block, never to the pool or program.
- Allowed: `sequential`, `random`, `shuffle`
  - **Sequential**: Maintains a persistent cursor (per-schedule-block identity); advances across days and does not reset automatically.
  - **Random**: Select an asset randomly each time, subject to cooldown rules.
  - **Shuffle**: Create a shuffled order of the pool and consume sequentially until exhausted, then reshuffle. Honors cooldowns.

- **Cooldowns** (for assets) are attached to the schedule block, never to pools or programs.

**Example:**
```yaml
progression: sequential
cooldown_hours: 4
```

- The schedule determines not only *when* but also exactly *which program* (and progression) is used.

### Slot Allocation and Repeat Execution

If a schedule block allocates more slots than a program's `grid_blocks`, the program is executed repeatedly until the slot allocation is consumed. The slot count must be an exact multiple of the program's `grid_blocks`.

```
schedule.slots = 4, program.grid_blocks = 1  →  program runs 4 times
schedule.slots = 4, program.grid_blocks = 2  →  program runs 2 times
schedule.slots = 4, program.grid_blocks = 3  →  invalid (not a multiple)
```

Each execution advances the progression cursor independently.

### Schedule Block Identity

A schedule block is uniquely identified by the tuple:

`(channel_id, schedule_layer, start_time, program_reference)`

This identity determines the persistent cursor used by sequential progression, and is the key for database state, deterministic replay, and debugging.

---

## 7. 🧩 Programs Replace Composite Episodes

There are no longer "composite episodes" as a separate concept.
Any program using `fill_mode: accumulate` simply fills its grid target by accumulating assets from its pool (e.g., for anthologies, blocks, shorts).

- **Program structure** (e.g., interleaving intros/shorts) is specified in the program object.

- Breaks and transitions between accumulated assets are added during program assembly.

---

## 8. 🎬 Bleed as a Program Property

- **Bleed** (whether a program may overrun its assigned grid slots) is a property of the program, not of asset type.
- Each program specifies `bleed: true` or `bleed: false` as needed.
- All overruns are intentional and explicit.

---

## 9. 🏷️ Templates (Optional Content Wrappers)

**Templates** are still available as *optional* wrappers around programs to handle channel branding, custom intros/outros, or multi-segment bumpers.

- Programs themselves may already include intro/outro segments.
- Templates are only needed for advanced multi-segment structures, or when reusing wrapper logic across multiple programs.

```yaml
templates:
  hbo_feature:
    segments:
      - source:
          collection: Intros
          tags: [hbo]
      - source:
          program: weekend_movie
        primary: true
```

Templates specify *segment structure* only—the schedule determines timing.
Use only when not directly encoding intros/outros in the program itself.

---

## 10. 🌈 Continuity Layer

Add-ons inserted for channel identity:
- Station IDs
- Network bumpers
- Branding

Continuity is **best-effort**—missing branding won't block playout.

---

## 11. 🔲 Break Detection & Budget

Break opportunities are identified during **playlog construction** (program expansion), not during schedule compilation. The schedule assigns grid slots; breaks are discovered when the program's actual content is assembled against those slots.

**Break priority model (highest wins):**

1. **Chapter markers** — Embedded chapter data in the asset. When present, chapter boundaries are the authoritative break points. Cold opens (content before the first chapter mark) MUST be respected; no break is inserted before the first marker.
2. **Asset boundaries** — In `accumulate`-mode programs, the seam between consecutive assets is a natural break point.
3. **Algorithmic placement** — When no chapter or boundary data exists, breaks are generated heuristically:
   - The first ~20% of program runtime is a **protected zone** — no algorithmic break may fall there.
   - Break spacing is **non-uniform**: intervals widen and break durations increase toward the end of the program, matching real broadcast cadence.

**Break budget:**

```
break_budget = grid_duration − program_runtime
```

The budget is the time the grid allots beyond the program's actual runtime. It is distributed across all identified break opportunities and filled with traffic assets. If traffic does not perfectly consume the budget, **padding** (black frames / silence) is inserted to satisfy the remaining duration exactly.

Break budget is always zero or positive. Programs that would produce a negative budget are only permitted when the program definition allows bleed. A non-bleeding program whose runtime exceeds the grid allocation is rejected during assembly.

---

## 12. 📢 Traffic Layer

**Traffic** =
- Commercials
- Promos
- Station IDs
- PSAs

Traffic fills break opportunities identified during program expansion (see §11).

```yaml
allowed_types: [promo]
cooldowns: ...
max_plays_per_day: ...
```

---

## 13. 🛡️ Invariants

**These must _always_ be true:**
- Program starts always align to grid.
- Schedule blocks resolve to integer grid units.
- Programs are reusable named objects; they define content assembly, not timing.
- Pools are asset sources only.
- Progression mode, cooldowns, and cursor persistence are a function of the schedule block.
- Sequential progression maintains a persistent cursor per schedule-block identity across days.
- Bleed behavior is explicitly controlled by program definition.
- Continuity is optional.
- Break opportunities are determined during playlog construction, not schedule compilation.
- Break priority: chapter markers > asset boundaries > algorithmic placement.
- Traffic fills all break opportunities; remaining budget is padded to exact grid fit.
- *Actual* playout time can exceed scheduled grid (overruns allowed if the program bleeds).

This contract maintains RetroVue scheduling correctness.

---

## 📊 DSL & Schedule Compilation Flow

```
CHANNEL CONFIG  (YAML DSL)
         │
         ▼
─────────────────────────────
│  SCHEDULE RESOLVER        │
│  - Applies layer rules    │
│    all_day/weekday/dates  │
─────────────────────────────
         │
         ▼
 PROGRAM BLOCK PLAN
 (grid-aligned)
         │
         ▼
─────────────────────────────
│   PROGRAM RESOLUTION      │
│  - Resolve pool + progr.  │
│  - Fill modes/bleed       │
│  - Progression per-block  │
─────────────────────────────
         │
         ▼
─────────────────────────────
│   PROGRAM ASSEMBLY        │
│  - Select assets from pool│
│  - Accumulate/single fill │
│  - Apply intros/outros    │
─────────────────────────────
         │
         ▼
─────────────────────────────
│   BREAK DETECTION         │
│  1. Chapter markers       │
│  2. Asset boundaries      │
│  3. Algorithmic placement │
│  - Budget = grid − runtime│
─────────────────────────────
         │
         ▼
─────────────────────────────
│      TRAFFIC              │
│  - Commercials/promos     │
│  - PSA, filler, cooldowns │
─────────────────────────────
         │
         ▼
      PLAYLOG
(final timeline)
         │
         ▼
      PLAYOUT
(frames emitted)
```

---

## 14. 🎲 Determinism & Variation

- **Emergent by default:** Playlists feel lifelike, non-repetitive.
- **Deterministic (for test/debug):** Setting a fixed RNG seed gives perfectly repeatable schedules.
    - All randomness flows from a single RNG stream.

---

## 15. ✍️ Authoring Philosophy

- **Author like a TV guide, not a config file.**
- Should support authentic memory- or log-based channel recreation.

```yaml
schedule:
  thursday:
    - start: "20:00"
      slots: 4
      program: weekend_movie
      progression: sequential
    - start: "00:00"
      slots: 2
      program: sitcom_hour
      progression: random
```

---

## 16. 📋 Minimal Channel Example

A complete channel definition using only core DSL features:

```yaml
format:
  grid_minutes: 30

pools:
  cheers:
    match:
      series_title: Cheers

  movies:
    match:
      type: movie

programs:
  cheers_halfhour:
    pool: cheers
    grid_blocks: 1
    fill_mode: single
    bleed: false

  hbo_movie:
    pool: movies
    grid_blocks: 4
    fill_mode: single
    bleed: true
    intro: hbo_intro

schedule:
  thursday:
    - start: "20:00"
      slots: 4
      program: cheers_halfhour
      progression: sequential

  friday:
    - start: "22:00"
      slots: 6
      program: hbo_movie
      progression: random
```

---
