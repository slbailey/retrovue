# Channel DSL — Authoritative Contract

Status: Contract
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-GRID`, `LAW-DERIVATION`

---

## Purpose

The Channel DSL is the declarative specification of a RetroVue channel. A single YAML file defines the complete editorial intent for one channel: what airs, when, wrapped in what presentation, and what fills the breaks.

The schedule compiler reads Channel YAML and produces compiled blocks with fully resolved structural segments (Tiers 0–3). The expansion layer adds fill (Tier 4) without modifying structural content.

---

## Top-Level Structure

```yaml
channel: <slug>                    # Required. Unique identifier.
number: <int>                      # Required. Unique channel number.
name: <string>                     # Required. Display name.
channel_type: <network|premium>    # Required. Drives break placement rules.
timezone: <IANA timezone>          # Required. All times interpreted in this zone.

format:                            # Required. Technical format.
  video: { width, height, frame_rate }
  audio: { sample_rate, channels }
  grid_minutes: <int>              # Grid slot duration in minutes.

pools: { ... }                     # Asset set definitions.
programs: { ... }                  # Program assembly definitions.
presentation: { ... }             # Preroll/postroll structure.
traffic: { ... }                  # Traffic profiles and config.
schedule: { ... }                 # Time-grid programming.
```

All sections except `presentation` and `traffic` are required.

---

## Grid Time Model

Every channel defines a time grid. All schedule block start times MUST align to grid boundaries. Grid duration is the product of `grid_minutes` and the schedule block's `slots` count.

```
block_duration = grid_minutes × slots
```

The broadcast day runs from `day_start_hour` (default 06:00) to the same hour the following day, in the channel's timezone.

---

## Pools

Pools define sets of candidate assets via declarative queries. Pools are used by programs (content selection), presentation (structural segment selection), and traffic (fill selection).

```yaml
pools:
  movies:
    select:
      where:
        type:
          eq: movie

  station_ids:
    select:
      where:
        type:
          eq: bumper
        tags:
          contains_all: [hbo, station_id]
```

Pools MUST NOT contain selection strategy, ordering, rotation, or progression logic. A pool is a pure query that returns matching assets.

All asset selection in the DSL MUST use `select.where` syntax with explicit operators. The `match` keyword is not part of this contract.

### Query Operators

| Operator | Meaning | Example |
|---|---|---|
| `eq` | Exact equality | `type: { eq: movie }` |
| `in` | Value is one of set | `rating: { in: ["PG", "PG-13"] }` |
| `contains_all` | All specified values present | `tags: { contains_all: [hbo, intros] }` |
| `contains_any` | At least one specified value present | `tags: { contains_any: [action, comedy] }` |
| `excludes_any` | None of specified values present | `tags: { excludes_any: [anime] }` |
| `lte` | Less than or equal | `year: { lte: 1995 }` |
| `gte` | Greater than or equal | `duration_sec: { gte: 3600 }` |

The three tag operators (`contains_all`, `contains_any`, `excludes_any`) may be combined on the same field. All are AND-combined: the asset must satisfy every specified operator.

```yaml
tags:
  contains_any: [action, comedy, thriller]
  excludes_any: [anime, adult]
```

### Contextual References

Within `presentation` entries, query values MAY reference properties of the current program's selected content:

```yaml
select:
  where:
    rating:
      eq: program.rating
```

`program.*` references are resolved at compile time after the primary content asset is selected. Available references: `program.rating`, `program.release_year`, `program.genre`.

---

## Programs

Programs are reusable editorial recipes defining content assembly from a pool.

```yaml
programs:
  hbo_movies_r:
    pool: movies                   # Base pool reference.
    select:                        # Optional narrowing query.
      where:
        rating:
          eq: "R"
    grid_blocks_max: 5             # Dynamic grid sizing (XOR with grid_blocks).
    fill_mode: single              # single | accumulate
    presentation: movies           # References presentation.programs.<name>.
```

### Program Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `pool` | string | Yes | Reference to a named pool. |
| `select` | dict | No | Additional `where` clause narrowing the pool for this program. |
| `grid_blocks` | int | One of `grid_blocks` / `grid_blocks_max` | Fixed grid slot count per execution. |
| `grid_blocks_max` | int | One of `grid_blocks` / `grid_blocks_max` | Maximum grid slots; actual count is `ceil(structural_runtime / grid_slot)`. |
| `fill_mode` | string | Yes | `single` (one asset) or `accumulate` (pack assets to fill grid). |
| `bleed` | bool | No (default false) | Whether content may overrun its grid allocation. |
| `presentation` | string | No | Reference to a named presentation definition under `presentation.programs`. |

`grid_blocks` and `grid_blocks_max` are mutually exclusive.

Grid block allocation MUST accommodate the total structural runtime (T0–T3). If structural segments cause the total to exceed the current grid allocation, the grid grows. Structural segments are never dropped to fit.

---

## Presentation

Presentation defines the preroll and postroll segments that accompany programs and dayparts.

```yaml
presentation:
  programs:
    <name>:
      preroll:
        - <entry>
        - <entry>
      postroll:
        - <entry>
        - <entry>

  dayparts:
    <name>:
      preroll:
        - <entry>
```

### Presentation Entry Types

**Pool reference:**
```yaml
- pool: intros
```

**Pool reference with contextual filter:**
```yaml
- pool: ratings_cards
  select:
    where:
      rating:
        eq: program.rating
```

**Traffic fill directive (Tier 4):**
```yaml
- type: traffic
  profile: hbo_premium
  fill: remaining
```

A `{ type: traffic }` entry is a Tier 4 fill directive, not a structural segment. It is NOT resolved at compile time. It produces a filler placeholder whose duration is the residual after all structural segments are accounted for. See "Fill Allocation Model" below.

**Traffic fill with placement (midroll):**
```yaml
- type: traffic
  profile: sitcom_standard
  fill: remaining
  placement:
    fallback:
      strategy: weighted_positions
      positions: [0.30, 0.72]
      weights: [1, 1]
```

A midroll traffic entry with `placement` defines WHERE breaks are inserted within content. If the content asset has chapter markers, they are used and the fallback is ignored. If no chapter markers exist, the fallback strategy generates synthetic break positions. See `placement_dsl.md`.

**Explicit asset (by ID):**
```yaml
- asset: hbo_station_id_winter_2024
```

### Ordering

Preroll entries appear before primary content, in declared order. Postroll entries appear after primary content, in declared order. Declared order determines the visual sequence — the order segments appear to the viewer.

Declared order does NOT determine budgeting sequence. All structural entry durations are reserved first, regardless of their position. Traffic fill receives the residual. See `INV-DSL-POSTROLL-STRUCTURAL-RESERVED-001`.

### Fill Allocation Model

A block has exactly one fill mechanism. The two modes are mutually exclusive:

**Presentation-declared traffic:** When a `{ type: traffic }` entry exists in the postroll, it owns all non-structural time. Break opportunities produced by break detection become inputs to the traffic allocator — they inform where fill is placed, not how much. Break-derived filler MUST NOT independently consume time.

**Break-derived filler (default):** When no `{ type: traffic }` entry exists in the presentation, break-derived filler consumes all non-structural time. This is the existing behavior for channels without a `presentation` block.

At most one `{ type: traffic }` entry is permitted across all preroll and postroll sequences in a single block. See `INV-DSL-SINGLE-FILL-DIRECTIVE-001`.

### Program-Level vs Daypart-Level

- **Program-level** presentation activates whenever the program executes. Defined under `presentation.programs.<name>`. Referenced by `programs.<name>.presentation: <name>`.
- **Daypart-level** presentation activates when the schedule block declares `daypart: <name>`. Defined under `presentation.dayparts.<name>`. Applied in addition to program-level presentation.

When both apply, daypart preroll precedes program preroll. Daypart postroll follows program postroll.

### Missing Assets

A presentation pool that matches zero assets MUST NOT prevent block compilation. The entry is omitted from the compiled segments. An omitted segment contributes zero duration and zero structural weight. The compiler MUST log a warning identifying the empty pool and the affected block.

---

## Traffic

Traffic fills time remaining after structural segments are placed.

```yaml
traffic:
  profiles:
    hbo_premium:
      allowed_pools: [traffic_trailers, traffic_teasers]
      weights:
        traffic_trailers: 3
        traffic_teasers: 1
      rotation:
        strategy: weighted
      duration_strategy: pack
      default_cooldown_seconds: 3600
      max_plays_per_day: 0

  break_config:
    to_break_bumper_ms: 3000
    from_break_bumper_ms: 3000
    station_id_ms: 5000

  default: hbo_premium
```

### Profile Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `allowed_pools` | list[str] | — | Pool names eligible for traffic fill under this profile. |
| `weights` | dict[str, int] | equal | Relative selection weight per pool. |
| `rotation.strategy` | string | `weighted` | `weighted` or `round_robin`. |
| `duration_strategy` | string | `pack` | `pack` (fill to capacity) or `single` (one asset per break). |
| `default_cooldown_seconds` | int | 3600 | Minimum seconds between replays of same asset. |
| `type_cooldowns_seconds` | dict[str, int] | {} | Per-type cooldown overrides. |
| `max_plays_per_day` | int | 0 | Max plays per asset per day. 0 = unlimited. |

### Profile Resolution

1. Schedule block declares `traffic_profile: <name>` → use that profile.
2. Otherwise → use `traffic.default`.

### Traffic Constraints

- Traffic MUST NOT add time to a block.
- Traffic MUST NOT displace structural segments (T0–T3).
- Traffic MUST NOT modify the compiled block structure.
- Traffic fill is resolved at playlog plan generation time, not at compile time.
- Break opportunities are advisory inputs to traffic allocation, not guaranteed insertion points.
- All non-structural time is allocated to exactly one fill mechanism per block (`INV-DSL-UNIFIED-FILL-001`).

---

## Schedule

The schedule binds programs to grid-aligned time slots.

```yaml
schedule:
  all_day:
    - start: "06:00"
      slots: 8
      program: [hbo_movies_g]
      progression: random
      bleed: true

    - start: "20:00"
      daypart: late_night
      slots: 20
      program: [hbo_movies_pg, hbo_movies_r]
      progression: random
      bleed: true

  sunday:
    - start: "14:00"
      slots: 5
      program: hbo_scifi_movies
      progression: random
      bleed: true
```

### Schedule Block Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `start` | string | Yes | Grid-aligned start time (HH:MM). |
| `slots` | int | Yes | Number of grid slots allocated. |
| `program` | string or list[str] | Yes | Program reference(s). |
| `progression` | string | Yes | `sequential`, `random`, or `shuffle`. |
| `bleed` | bool | No (default false) | Allow content overrun. |
| `daypart` | string | No | Activates daypart-level presentation. |
| `traffic_profile` | string | No | Override traffic profile for this block. |
| `run_id` | string | No | Explicit progression run identity. |
| `exhaustion` | string | No (default `wrap`) | Episode exhaustion policy: `wrap`, `hold_last`, `stop`. |

### Layered Override Model

Priority (highest wins):
1. `dates:` — exact dates (e.g., `"10-31"`)
2. Day name — `monday`, `tuesday`, ..., `sunday`
3. `weekdays:` / `weekends:`
4. `all_day:`

Higher-priority layers replace lower-priority layers for overlapping time slots.

### Progression

- **sequential:** Persistent cursor per schedule-block identity. Advances across days.
- **random:** Seeded random selection per execution. Deterministic for same seed.
- **shuffle:** Seeded shuffle of pool; consume sequentially until exhausted, then reshuffle.

Progression is a property of the schedule block, never of the pool or program.

---

## Compilation Model

The schedule compiler transforms Channel YAML into compiled blocks:

```
Channel YAML
    ↓
Schedule Resolution (layer merging)
    ↓
Program Assembly (T0 content + T1 presentation selection)
    ↓
Break Detection (content segmentation + advisory break opportunities)
    ↓
Second Pass (T2 obligations + T3 optional presentation)
    ↓
Grid Sizing (structural total → grid block count)
    ↓
Compiled Blocks (ProgramBlockOutput with compiled_segments)
```

All structural segments (T0–T3) are fully resolved during compilation, including asset selection and duration. Grid sizing is based on the total structural runtime.

Break opportunities are advisory — they inform where fill may be placed, not how much fill exists. Fill duration is the residual: `grid_slot - structural_total`.

Expansion MUST NOT modify structural segments — it hydrates asset paths, sequences tiers, and adds fill (T4) only.

---

## Invariants

### INV-DSL-QUERY-CANONICAL-001

All asset selection in the DSL MUST use `select.where` syntax with explicit operators. The `match` keyword MUST NOT appear in canonical channel YAML.

### INV-DSL-POOL-SETS-ONLY-001

Pools define asset sets via queries. Pools MUST NOT contain selection strategy, ordering, rotation, or progression logic.

### INV-DSL-PRESENTATION-STRUCTURE-001

The `presentation` section defines segment structure and ordering. Asset selection is resolved at compile time from pools. The presentation section MUST NOT define selection outcomes — only the structure and pool references from which assets are selected.

### INV-DSL-TRAFFIC-RESIDUAL-001

Traffic fills time remaining after structural segments (T0–T3). Traffic MUST NOT displace structural segments, add time, or modify block structure. All non-structural time is allocated to exactly one fill mechanism per block. Break opportunities are advisory inputs to traffic allocation, not guaranteed insertion points — a break opportunity that receives zero fill time is valid.

### INV-DSL-SEGMENT-ORDER-DETERMINISTIC-001

Segment ordering within a block MUST be deterministic for same inputs. Preroll entries appear in declared order. Postroll entries appear in declared order. No reordering occurs during expansion.

### INV-DSL-MISSING-ASSET-NONFATAL-001

A presentation or obligation pool that matches zero assets MUST NOT prevent block compilation. The segment is omitted. An omitted segment contributes zero duration and zero structural weight. Grid sizing uses the actual resolved structural total — omitted segments do not inflate the grid. The grid MUST NOT shrink below the minimum required for primary content (Tier 0). The compiler MUST log a warning.

### INV-DSL-GRID-STRUCTURAL-EXPANSION-001

Grid block allocation MUST expand if structural segments (T0–T3) exceed the initial grid slot. Structural segments are never dropped to fit. References `INV-GRID-SIZING-STRUCTURAL-001`.

### INV-DSL-POSTROLL-STRUCTURAL-RESERVED-001

All structural entries in a preroll or postroll sequence MUST have their durations reserved before traffic fill duration is computed. Traffic fill duration is the residual after all structural durations (across all tiers, all positions) are subtracted from the grid slot. Declared order determines visual sequence, not budgeting sequence.

### INV-DSL-SINGLE-FILL-DIRECTIVE-001

At most one `{ type: traffic }` entry is permitted across all preroll and postroll sequences in a single block. Multiple fill directives within a block are invalid. When no fill directive is declared, break-derived filler is the sole fill mechanism.

### INV-DSL-UNIFIED-FILL-001

All non-structural time within a block is allocated to exactly one fill mechanism. When a presentation-declared `{ type: traffic }` entry exists, it owns all non-structural time; break opportunities become advisory inputs to traffic allocation, not independent filler consumers. When no `{ type: traffic }` entry exists, break-derived filler consumes all non-structural time. No time is double-allocated.

### INV-DSL-NONNEGATIVE-FILL-001

Computed fill duration MUST be greater than or equal to zero. If structural duration equals or exceeds block duration, fill duration is zero. A negative fill duration MUST NOT occur — grid sizing (`INV-DSL-GRID-STRUCTURAL-EXPANSION-001`) ensures the block is large enough for all structural segments.

### INV-DSL-TIME-CONSERVATION-001

For any compiled block: `block_duration = sum(structural_segment_durations) + sum(fill_segment_durations)`. No time is unaccounted for. No time is double-allocated. This is the conservation law of the block assembly system. References `INV-BLOCK-SEGMENT-CONSERVATION-001`.

---

## Required Tests

- `pkg/core/tests/contracts/test_channel_dsl.py`

| Test | Invariant | Scenario |
|---|---|---|
| `test_select_where_required` | INV-DSL-QUERY-CANONICAL-001 | Pool using `match` is rejected; pool using `select.where` is accepted. |
| `test_pool_no_strategy` | INV-DSL-POOL-SETS-ONLY-001 | Pool with `progression` or `rotation` field is rejected. |
| `test_preroll_declared_order` | INV-DSL-SEGMENT-ORDER-DETERMINISTIC-001 | Preroll entries appear in compiled_segments in declared YAML order. |
| `test_postroll_declared_order` | INV-DSL-SEGMENT-ORDER-DETERMINISTIC-001 | Postroll entries appear in compiled_segments in declared YAML order. |
| `test_empty_pool_nonfatal` | INV-DSL-MISSING-ASSET-NONFATAL-001 | Presentation pool matching zero assets produces block without that segment, no error. |
| `test_traffic_cannot_displace` | INV-DSL-TRAFFIC-RESIDUAL-001 | Structural segment durations unchanged after traffic fill. |
| `test_grid_expands_for_structural` | INV-DSL-GRID-STRUCTURAL-EXPANSION-001 | T1+T2+T3 durations pushing total past grid boundary increase grid block count. |
| `test_postroll_structural_reserved_before_fill` | INV-DSL-POSTROLL-STRUCTURAL-RESERVED-001 | Station_id after traffic entry in postroll retains its full duration; fill budget is reduced by station_id duration. |
| `test_single_fill_directive` | INV-DSL-SINGLE-FILL-DIRECTIVE-001 | Block with two `{ type: traffic }` entries is rejected. |
| `test_no_fill_directive_uses_break_filler` | INV-DSL-SINGLE-FILL-DIRECTIVE-001 | Block without `{ type: traffic }` uses break-derived filler for all non-structural time. |
| `test_fill_directive_owns_all_nonstructural` | INV-DSL-UNIFIED-FILL-001 | When `{ type: traffic }` declared, break-derived filler produces zero independent time. |
| `test_no_double_fill` | INV-DSL-UNIFIED-FILL-001 | No block has both break-derived filler and presentation-declared traffic consuming time independently. |
| `test_fill_duration_nonnegative` | INV-DSL-NONNEGATIVE-FILL-001 | Fill duration is >= 0 for every compiled block. |
| `test_structural_equals_block_zero_fill` | INV-DSL-NONNEGATIVE-FILL-001 | When structural total equals block duration, fill is exactly zero. |
| `test_time_conservation` | INV-DSL-TIME-CONSERVATION-001 | `block_duration == sum(structural) + sum(fill)` for every compiled block. |
| `test_omitted_segment_zero_weight` | INV-DSL-MISSING-ASSET-NONFATAL-001 | Omitted segment contributes zero to structural total and grid sizing. |

---

## Enforcement Evidence

TODO
