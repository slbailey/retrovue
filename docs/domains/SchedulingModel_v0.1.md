# Scheduling Model v0.1

## 1. Purpose

This model defines the compositional structure through which content is selected, wrapped in presentation structure, placed in time, and filled with interstitial material to produce a complete playout sequence.

**In scope:**
- Asset selection rules (pools)
- Block presentation structure (blocks)
- Content-to-structure binding (programs)
- Time-based placement (schedule)
- Flexible slot filling (traffic)

**Out of scope:**
- Runtime execution and frame-level timing (AIR)
- Ingest, transcoding, and asset lifecycle
- EPG generation
- As-run logging
- Viewer-facing transport

---

## 2. Core Concepts Overview

**Pool** — A named set of match rules that identifies a subset of assets in the catalog. Pools do not select individual assets; they define the eligible set from which selection occurs.

**Block** — A declared sequence of typed slots that defines the structural shape of a playout unit. Blocks describe presentation order and slot types, not specific content.

**Program** — A binding between a primary content pool and a block format. Programs declare what content source feeds the block and how successive items are selected, but do not define structure.

**Schedule** — A time-ordered sequence of program placements against a grid. Each entry specifies when a program airs, how many grid slots it occupies, and how the program progresses across repeated placements.

**Traffic** — The mechanism that fills flexible slots within a resolved block using assets drawn from designated pools. Traffic operates after block structure is established.

---

## 3. Concept Relationships

- Pools define eligible asset sets by match criteria.
- Blocks define the structural skeleton of a playout unit as an ordered sequence of typed slots.
- Programs bind a primary content pool to a block format and declare selection behavior.
- Schedule places programs into time slots on the grid.
- Traffic fills any slots marked as `flex` with interstitial assets from their designated pools.

### Resolution flow

1. Schedule entry identifies a program and a time window.
2. Program identifies the primary content pool and selects the next asset.
3. Block format is instantiated: the primary content slot is populated, fixed-duration slots are populated from their designated pools, and flex slots are left pending.
4. Traffic resolves all pending flex slots from their designated pools.
5. The result is an ordered, fully-populated segment sequence with concrete asset URIs and durations.

---

## 4. Schema Definitions

### 4.1 Pools

**Purpose:** Declare a named, reusable set of match rules that identify eligible assets from the catalog.

**Required fields:**

| Field   | Type   | Description                                      |
|---------|--------|--------------------------------------------------|
| `name`  | string | Unique identifier for the pool                   |
| `match` | object | Key-value criteria evaluated against asset metadata |

**Constraints:**
- Pools define eligibility only. They contain no selection logic, ordering, or rotation state.
- Match rules are conjunctive (all criteria must be satisfied).
- A pool may match zero assets at resolution time. This is not an error at definition time; it is a resolution-time condition.

**Example:**

```yaml
pools:
  hbo_movies:
    match:
      source: hbo
      content_type: movie

  hbo_promos:
    match:
      source: hbo
      content_type: promo

  hbo_intros:
    match:
      source: hbo
      content_type: intro

  hbo_ratings:
    match:
      source: hbo
      content_type: ratings_card

  hbo_station_ids:
    match:
      source: hbo
      content_type: station_id

  hbo_next_bumps:
    match:
      source: hbo
      content_type: coming_up_next
```

---

### 4.2 Blocks

**Purpose:** Declare the structural shape of a playout unit as an ordered sequence of typed slots.

**Slot types:**

Slots are classified into three types based on their role in the block:

| Slot type         | Category  | Behavior                                                                 |
|-------------------|-----------|--------------------------------------------------------------------------|
| `primary_content` | primary   | The scheduled content item — the program that appears in the EPG. Populated by the program's content selection. Duration is the asset's natural duration. Exactly one per block. |
| `pool`            | secondary | Required structural decoration baked into the program format (intros, ratings cards, station IDs, coming-up-next bumps, etc.). Populated from a named pool. Duration is the selected asset's natural duration. |
| `flex`            | flex      | Consumes all remaining duration not occupied by primary or secondary slots. Populated by traffic at resolution time. At most one per block. |

- **Primary content** is what is published on the schedule and visible in the EPG. It is the editorial payload of the block.
- **Secondary content** is everything the program format requires around the primary content. These slots are fixed in the block definition and resolve to concrete assets with known durations.
- **Flex** absorbs the difference between the block's target duration and the sum of primary + secondary durations. Traffic fills this space with interstitial assets from the flex slot's designated pool.

**Required fields:**

| Field   | Type          | Description                                |
|---------|---------------|--------------------------------------------|
| `name`  | string        | Unique identifier for the block format     |
| `slots` | list of slots | Ordered sequence of slot definitions       |

**Per-slot fields:**

| Field    | Type   | Required | Description                                         |
|----------|--------|----------|-----------------------------------------------------|
| `type`   | string | yes      | One of: `pool`, `primary_content`, `flex`           |
| `pool`   | string | conditional | Required when `type` is `pool` or `flex`. Pool name to draw from. |
| `label`  | string | no       | Human-readable slot purpose (e.g., "intro", "promo fill") |

**Timing behavior:**
- Blocks resolve against a target duration derived from the schedule entry (grid slot count multiplied by grid slot duration).
- Primary and secondary slots consume their selected asset's natural duration. These durations are fixed at resolution time.
- The flex slot consumes all remaining duration: `target_duration - sum(primary) - sum(secondary)`.
- If primary + secondary durations exceed the target duration, the block is in overflow. Overflow handling is not defined in this version.

**Constraints:**
- Exactly one `primary_content` slot per block.
- At most one `flex` slot per block. A block with no `flex` slot has no flexible time.
- A `flex` slot represents total unallocated duration within the block. It does not imply a single contiguous region in the resolved playout sequence. Resolution-phase operations (e.g., commercial break insertion) may distribute flex time across multiple regions.
- Slot order in the definition is slot order in playout. The flex slot's declared position is its default placement; resolution may redistribute it.

**Example:**

```yaml
blocks:
  premium_movie:
    slots:
      - { type: pool,            pool: hbo_intros,       label: intro }
      - { type: pool,            pool: hbo_ratings,      label: ratings_card }
      - { type: primary_content,                         label: movie }
      - { type: pool,            pool: hbo_next_bumps,   label: coming_up_next }
      - { type: flex,            pool: hbo_promos,       label: promo_fill }
      - { type: pool,            pool: hbo_station_ids,  label: station_id }
```

---

### 4.3 Programs

**Purpose:** Bind a primary content pool to a block format and declare how successive content items are selected.

A program does not define structure. It declares: "draw content from this pool, present it using this block format, and advance through the pool using this selection behavior."

**Required fields:**

| Field       | Type   | Description                                              |
|-------------|--------|----------------------------------------------------------|
| `name`      | string | Unique identifier for the program                        |
| `pool`      | string | Primary content pool name                                |
| `block`     | string | Block format name                                        |
| `selection` | string | Selection behavior: `sequential` or `random`             |

**Selection behaviors:**

| Behavior     | Description                                                        |
|--------------|--------------------------------------------------------------------|
| `sequential` | Assets are selected in catalog order. Position advances on each placement. Wraps on exhaustion. |
| `random`     | Assets are selected uniformly at random from the eligible set.     |

**Constraints:**
- The program's `pool` provides assets for the block's `primary_content` slot.
- The program's `block` must contain exactly one `primary_content` slot.
- Selection state (e.g., sequential cursor position) is maintained per program instance in the schedule, not per program definition.

**Example:**

```yaml
programs:
  hbo_prime_movies:
    pool: hbo_movies
    block: premium_movie
    selection: sequential
```

---

### 4.4 Schedule

**Purpose:** Place programs into time on a grid. The schedule is an ordered list of entries, each specifying a program, a start time, and a duration expressed in grid blocks.

**Required fields per entry:**

| Field         | Type   | Description                                              |
|---------------|--------|----------------------------------------------------------|
| `time`        | string | Start time within the broadcast day (HH:MM, 24h format) |
| `program`     | string | Program name                                             |
| `grid_blocks` | int    | Number of grid slots this entry occupies                 |

**Optional fields per entry:**

| Field             | Type   | Default      | Description                                      |
|-------------------|--------|--------------|--------------------------------------------------|
| `grid_blocks_max` | int    | —            | Maximum grid slots (dynamic sizing). Mutually exclusive with `grid_blocks`. |
| `exhaustion`      | string | `wrap`       | Behavior when the content pool is exhausted: `wrap` (restart from beginning) or `stop`. |

**Grid model:**
- The grid is divided into uniform slots (e.g., 30 minutes each). Slot duration is a channel-level configuration, not a per-entry field.
- `grid_blocks: N` means the entry occupies exactly N consecutive grid slots.
- `grid_blocks_max: N` means the entry occupies as many grid slots as needed to contain the selected content, up to N. Used for variable-duration content (e.g., movies of different lengths).
- Entries are placed sequentially. Gaps between entries are not permitted.

**Progression:**
- Each schedule entry maintains independent selection state for its program.
- On each broadcast day, the schedule is evaluated in order. Each entry selects the next content item according to its program's selection behavior and advances the cursor.
- `exhaustion: wrap` resets the cursor to the beginning of the pool when all items have been selected.

**Example:**

```yaml
schedule:
  grid_slot_minutes: 30
  entries:
    - { time: "20:00", program: hbo_prime_movies, grid_blocks_max: 5 }
    - { time: "22:30", program: hbo_prime_movies, grid_blocks_max: 5 }
    - { time: "01:00", program: hbo_prime_movies, grid_blocks_max: 5 }
```

---

### 4.5 Traffic

**Purpose:** Fill all `flex`-type slots in resolved blocks with concrete interstitial assets drawn from the slot's designated pool.

**Behavior:**
- After block resolution, any slot with `type: flex` has a known remaining duration.
- Traffic selects assets from the fill slot's pool and packs them sequentially until the remaining duration is consumed.
- If the pool is empty or no assets fit, the remaining duration is filled with the channel's designated filler asset (e.g., `filler.mp4`). This is a fallback, not a desired state.

**Selection:**
- Traffic selects assets greedily: longest-fitting first, no repeat within a single fill span.
- No prioritization, weighting, or campaign logic exists in this version.

**Required channel-level fields:**

| Field        | Type   | Description                                  |
|--------------|--------|----------------------------------------------|
| `filler_uri` | string | Fallback asset URI when no pool assets fit   |

**Example (channel-level traffic configuration):**

```yaml
traffic:
  filler_uri: /media/filler/bars.ts
```

---

## 5. Resolution Model

A scheduled entry becomes a playout sequence through the following steps:

1. **Schedule evaluation.** The schedule identifies the current entry by wall-clock time. The entry specifies a program reference and a target duration (grid slots).

2. **Content selection.** The program's selection behavior chooses the next asset from the program's primary content pool. The selection cursor advances.

3. **Block instantiation.** The program's block format is instantiated as an ordered list of concrete slots:
   - Primary slot (`primary_content`): populated with the selected content asset. Duration is the asset's natural duration. This is the EPG-visible program.
   - Secondary slots (`pool`): each populated by selecting one asset from the named pool. These are the required decorations defined by the program format. Duration is each selected asset's natural duration.
   - Flex slot (`flex`): marked pending. Assigned a remaining duration equal to `target_duration - sum(primary) - sum(secondary)`.

4. **Traffic fill.** The `flex` slot's remaining duration is filled by traffic, which selects assets from the fill slot's designated pool and packs them sequentially. Any unfilled remainder uses the channel's filler asset.

5. **Final sequence.** The result is an ordered list of segments, each with a concrete asset URI, a start offset, and a duration. This sequence is the input to playout execution.

### Note: Commercial Breaks and Channel Type

Breaks are a property of the channel, not the content. The same movie airs uninterrupted on a premium channel and with breaks on a commercial network. Break insertion is a resolution-time concern: when a commercial channel resolves a block, breaks are derived from the primary content and injected into the sequence.

Break placement is determined by one of two sources, evaluated in order:
1. **Chapter markers.** If the content asset carries chapter metadata, break points align to chapter boundaries.
2. **Calculated placement.** If no chapter markers exist, break points are computed from content duration (e.g., evenly spaced at intervals appropriate to the grid slot).

Premium channels never insert breaks. The block format alone governs the structure.

This version does not implement break insertion. The mechanism is documented here because it is fundamental to the resolution model's design: the block format defines the skeleton, but the resolved sequence may contain additional structure injected by the resolver based on channel type. Future versions will formalize break insertion as a resolution-phase step between block instantiation (step 3) and traffic fill (step 4).

---

## 6. Timing Model (Simplified)

- Every block resolves against a **target duration** derived from the schedule entry's grid allocation.
- Primary and secondary slots consume their selected asset's **natural duration**. These are fixed once resolved.
- The flex slot consumes **remaining duration**: `target_duration - sum(primary) - sum(secondary)`.
- If remaining duration is zero or negative, the flex slot is empty (or the block is in overflow).
- Exact overflow and underflow handling rules are not defined in this version. The assumption is that grid allocation is chosen to accommodate typical content durations with positive fill remainder.
- Sub-second timing precision, frame-level alignment, and cadence are runtime concerns outside this model's scope.

---

## 7. Constraints and Non-Goals

This version explicitly does **not** support:

- **Campaign-based traffic.** No flight dates, impression targets, or advertiser contracts.
- **Advanced rotation systems.** No dayparting, frequency capping, or weighted rotation beyond sequential/random.
- **Compatibility rules.** No exclusion matrices, product separation, or adjacency constraints.
- **Multi-break topology.** Blocks contain at most one flex region. Mid-content breaks (act-based interruptions) are not modeled.
- **Hard/soft timing enforcement.** No distinction between must-hit times and flexible placement. Grid placement is assumed to be exact.
- **Dynamic block format selection.** A program references exactly one block format. Runtime format switching based on content duration or daypart is not supported.
- **Pool selection logic within pool definitions.** Pools define eligibility. All selection logic (ordering, deduplication, rotation) lives in the program or traffic layer, not the pool.

---

## 8. Example End-to-End Configuration

A complete configuration for an HBO-style premium movie channel:

```yaml
pools:
  hbo_movies:
    match:
      source: hbo
      content_type: movie

  hbo_intros:
    match:
      source: hbo
      content_type: intro

  hbo_ratings:
    match:
      source: hbo
      content_type: ratings_card

  hbo_next_bumps:
    match:
      source: hbo
      content_type: coming_up_next

  hbo_promos:
    match:
      source: hbo
      content_type: promo

  hbo_station_ids:
    match:
      source: hbo
      content_type: station_id

blocks:
  premium_movie:
    slots:
      - { type: pool,            pool: hbo_intros,       label: intro }
      - { type: pool,            pool: hbo_ratings,      label: ratings_card }
      - { type: primary_content,                         label: movie }
      - { type: pool,            pool: hbo_next_bumps,   label: coming_up_next }
      - { type: flex,            pool: hbo_promos,       label: promo_fill }
      - { type: pool,            pool: hbo_station_ids,  label: station_id }

programs:
  hbo_prime_movies:
    pool: hbo_movies
    block: premium_movie
    selection: sequential

schedule:
  grid_slot_minutes: 30
  entries:
    - { time: "20:00", program: hbo_prime_movies, grid_blocks_max: 5 }
    - { time: "22:30", program: hbo_prime_movies, grid_blocks_max: 5 }
    - { time: "01:00", program: hbo_prime_movies, grid_blocks_max: 5 }

traffic:
  filler_uri: /media/filler/bars.ts
```

**Resolved example** (20:00 entry, 107-minute movie, grid_slot=30min, grid_blocks_max=5):

Grid allocation: 4 blocks = 120 minutes (ceil(107/30) = 4).

```
Slot 1:  intro           (hbo_intros)         →  15s
Slot 2:  ratings_card    (hbo_ratings)         →   5s
Slot 3:  movie           (primary_content)     → 107m 00s
Slot 4:  coming_up_next  (hbo_next_bumps)      →  30s
Slot 5:  promo_fill      (hbo_promos, traffic) →  11m 10s  [filled with promos]
Slot 6:  station_id      (hbo_station_ids)     →  15s
                                         Total → 120m 00s
```

---

## 9. Future Considerations

- **Commercial break insertion.** Breaks are injected during resolution for commercial channels. Break points are derived from content chapter markers when present, or calculated from content duration when absent. The same content asset produces different resolved sequences depending on channel type. Premium channels never insert breaks.
- **Rotation policies.** Weighted selection, daypart affinity, frequency capping, and no-repeat windows.
- **Break structure.** Typed sub-slots within a break (bumper-in, commercial pods, bumper-out).
- **Traffic prioritization.** Ordered fill preference, contractual obligations, and fallback chains.
- **Dynamic format selection.** Choose block format at resolution time based on content properties or schedule context.
- **Timing enforcement.** Hard-start constraints, join-in-progress semantics, and underflow/overflow policy.
