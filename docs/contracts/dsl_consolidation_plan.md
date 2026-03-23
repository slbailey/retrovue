# Channel DSL Consolidation — Audit, Reconciliation, and Migration Plan

---

## 1. Documentation Audit

| Document | Scope | Overlaps With | Outdated / Conflicting | Disposition |
|---|---|---|---|---|
| `docs/channel-yaml-reference.md` | User-facing YAML syntax reference. Pool `match` syntax, schedule layering, block types (episode, movie_marathon, movie, sitcom), templates, traffic config. | `channel_dsl.md` (pools, schedule, programs). `traffic_dsl.md` (traffic config). | Uses `match` keyword (legacy). Documents `block:` and `movie_marathon:` block types not in current `config/channels/` YAMLs. No `presentation`, no `select.where`, no tiers. | **Rewrite** to match new canonical YAML. Becomes operator guide, not contract. |
| `docs/contracts/channel_dsl.md` | Architectural contract. Grid model, layered schedules, pools, programs, schedule blocks, progression, bleed, break detection, traffic layer. 13 informal invariants. | `core/programming_dsl.md` (pools, schedule, programs). `traffic_dsl.md` (traffic layer). `block_assembly_tiers.md` (break detection, tier model). | Uses `match` in pool examples. `intro`/`outro` on programs (replaced by `presentation` block). Break detection described as "during playlog construction" — now moves to compile time per `INV-STRUCTURAL-RESOLUTION-001`. Continuity layer (§10) is vague and superseded by Tier 2/3 model. Templates section (§9) uses legacy `source.collection` syntax. Invariants in §13 are informal (no IDs, not in INVARIANTS.md). | **Replace** with new authoritative `channel_dsl.md`. Formal invariants already exist in dedicated files. |
| `docs/contracts/core/programming_dsl.md` | Draft v2. DSL syntax, schedule compiler pipeline, playlog plan expansion, traffic manager v1. Output schema. | `channel_dsl.md` (everything). `traffic_dsl.md` (traffic manager). | Entirely superseded. Uses `collection` (not `pool`), `episode_selector`/`movie_selector` (not `select.where`), `p.` and `col.` prefixes. References Traffic Manager v1 (loop filler.mp4). Has "Next Steps" checklist with unchecked items. | **Delete.** All content is either implemented and documented elsewhere or deprecated. |
| `docs/contracts/traffic_dsl.md` | Traffic configuration contract. Inventories, profiles, break config, assignment, resolution rules. 7 formal invariants. | `channel_dsl.md` (§12 traffic layer). `channel-yaml-reference.md` (traffic section). | Uses `match` in inventory examples. `TrafficInventory` concept with `asset_type` field — new model unifies inventories into pools. `traffic.inventories` section is replaced by pools. Break config (`to_break_bumper_ms`, etc.) remains valid. Profile structure remains valid but `allowed_types` changes to `allowed_pools`. | **Rewrite** as `traffic_dsl.md` focused on profiles, break config, and fill behavior. Remove inventory concept — pools handle asset sets. |

---

## 2. DSL Concept Extraction

### Pool

A named set of candidate assets, defined by a declarative query. Pools are the universal mechanism for defining asset sets — used by content, presentation, traffic, and obligations alike.

```yaml
pools:
  movies:
    select:
      where:
        type:
          eq: movie
```

Pools define WHAT is available. They do not define selection strategy, ordering, or rotation. A pool is a pure query — it returns matching assets, nothing more.

**Key change from legacy:** The `match` keyword is replaced by `select.where` with explicit operators (`eq`, `in`, `contains_all`, `lte`, `gte`). This eliminates ambiguity between exact match, substring, and containment.

### Program

A reusable editorial recipe that defines how content is assembled from a pool. Programs own Tier 0 (primary content) and Tier 1 (mandatory presentation) selection rules.

```yaml
programs:
  hbo_movies_r:
    pool: movies
    select:
      where:
        rating:
          eq: "R"
    grid_blocks_max: 5
    fill_mode: single
    presentation: movies    # references a presentation definition
```

Programs define content assembly: pool, fill mode, grid sizing, and which presentation template to apply. Programs do NOT define progression (that belongs to the schedule block) or traffic behavior.

### Presentation

A named structure defining the preroll and postroll segments that accompany a program or daypart. Presentation owns Tier 1 (mandatory program presentation), Tier 2 (clock/daypart obligations), and Tier 3 (optional enrichment) segment definitions.

```yaml
presentation:
  programs:
    movies:
      preroll:
        - pool: intros
        - pool: ratings_cards
          select:
            where:
              rating:
                eq: program.rating
      postroll:
        - pool: coming_up_next_promos
        - type: traffic
          profile: hbo_premium
          fill: remaining
        - pool: station_ids

  dayparts:
    late_night:
      preroll:
        - pool: late_night_intros
```

Presentation defines segment structure and ordering. Asset selection uses pools with optional contextual filters (`program.rating`). Presentation does NOT define timing — the schedule determines when programs and dayparts activate.

### Schedule

The time-first specification of what airs when. Schedule blocks bind programs to grid-aligned time slots with progression rules.

```yaml
schedule:
  all_day:
    - start: "20:00"
      daypart: late_night
      slots: 20
      program: [hbo_movies_pg, hbo_movies_r]
      progression: random
      bleed: true
```

The schedule owns timing, progression, daypart assignment, and program selection order. It does NOT own content assembly, presentation structure, or traffic behavior.

### Segment

A duration-bearing unit within a compiled block. Every segment has a type, an asset reference, and a duration. Segments are classified by tier:

- **Tier 0:** Primary content (movie, episode)
- **Tier 1:** Mandatory program presentation (intro, rating card)
- **Tier 2:** Clock/daypart obligation (station ID, daypart intro)
- **Tier 3:** Optional enrichment (coming up next, channel ident)
- **Tier 4:** Fill (traffic — promos, trailers, commercials)

Tiers 0–3 are structural: resolved at compile time, immutable during expansion. Tier 4 is fill: resolved at playlog plan generation time.

### Traffic

The fill layer that occupies time remaining after structural segments are placed. Traffic is defined by profiles that control which pools are eligible, rotation strategy, cooldowns, and caps.

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
  default: hbo_premium
```

Traffic fills break opportunities. It MUST NOT add time, displace structural segments, or alter the compiled block structure.

---

## 3. Conflict Resolution

### `match` vs `select.where`

- **Old:** `match: { type: movie, rating: PG }` — flat dict, implicit exact match, no operators.
- **New:** `select: { where: { type: { eq: movie }, rating: { eq: "PG" } } }` — explicit operators.
- **Decision:** `select.where` is canonical. `match` is deprecated. The new syntax supports operators (`eq`, `in`, `contains_all`, `lte`, `gte`) and contextual references (`program.rating`). The old `match` syntax cannot express containment (`contains_all` for tags), inequality (`lte`/`gte`), or set membership (`in`).
- **Migration:** Existing `match` clauses map 1:1 to `select.where` with `eq` operators. Compiler MAY accept `match` as sugar during transition but MUST normalize to `select.where` internally.

### Traffic inventories vs pools

- **Old:** `traffic.inventories` defined separate named asset sets with `match` + `asset_type`. Pools were content-only.
- **New:** Pools are universal. Traffic-eligible assets are defined as pools (`traffic_trailers`, `traffic_teasers`). Traffic profiles reference pools via `allowed_pools`, not via `allowed_types` matching `asset_type` on inventory entries.
- **Decision:** `traffic.inventories` is removed. All asset sets are pools. Traffic profiles reference pools by name. The `asset_type` concept on inventory entries is eliminated — the pool query itself determines what assets are eligible.
- **Migration:** Each `traffic.inventories.<name>.match` becomes a top-level `pools.<name>.select.where`. The `asset_type` field is dropped. `traffic.profiles.<name>.allowed_types` becomes `allowed_pools`.

### Program `presentation` vs `intro`/`outro`

- **Old:** Programs had `intro` and `outro` fields referencing single assets.
- **New:** Programs reference a named presentation definition via `presentation: <name>`. The presentation definition specifies preroll and postroll sequences with multiple entries, pool-based selection, and contextual filters.
- **Decision:** `intro`/`outro` fields on programs are deprecated. All program presentation is expressed via the `presentation` block. This supports multi-segment preroll/postroll, contextual selection (e.g., rating-matched cards), and traffic fill integration within postroll.
- **Migration:** `intro: hbo_intro` becomes a presentation definition with a single preroll entry: `preroll: [{ pool: intros }]`.

### Where selection logic belongs

- **Old:** Pools had `match` (selection). Programs had `pool` (reference) + optional `intro`/`outro`. Traffic had `inventories` (separate selection).
- **New:** All selection uses `select.where` on pools. Programs add a `select.where` clause to narrow a pool for content selection. Presentation entries reference pools. Traffic profiles reference pools.
- **Decision:** `select.where` is the single query mechanism. It appears on:
  - Pools (defines the candidate set)
  - Programs (narrows pool for content selection)
  - Presentation entries (narrows pool for contextual selection, e.g., `program.rating`)

### Optional vs required segments

- **Old:** `channel_dsl.md` §10 described continuity as "best-effort — missing branding won't block playout."
- **New:** All structural segments (T0–T3) are resolved at compile time. Missing assets cause the segment to be skipped — not a playout failure, but the compiler logs a warning. The block still compiles; grid sizing adjusts.
- **Decision:** Missing structural assets are non-fatal. A presentation pool that matches zero assets produces zero segments for that entry — the block continues without it. This is a compile-time decision, not a runtime one. `INV-STRUCTURAL-RESOLUTION-001` requires resolution at compile time; resolution to "no matching asset" is a valid outcome.

### Break detection timing

- **Old:** `channel_dsl.md` §11: "Break opportunities are identified during playlog construction (program expansion), not during schedule compilation."
- **New:** Per `INV-STRUCTURAL-RESOLUTION-001` and `INV-EXPANSION-NON-MUTATION-001`, break detection moves to compile time. The compiler produces break-aware content segments in `compiled_segments`.
- **Decision:** The new model is canonical. Break detection at compile time. The old statement is retired.

---

## 4. New Contract Structure

```
docs/contracts/
├── channel_dsl.md              # Top-level channel structure, grid model, schedule layering
├── programming_dsl.md          # Programs, pools, progression, fill modes, grid sizing
├── presentation_dsl.md         # Preroll/postroll structure, dayparts, tier 1-3 segments  [NEW]
├── traffic_dsl.md              # Traffic profiles, fill behavior, break config
├── query_dsl.md                # select.where query language specification              [NEW]
├── block_assembly_tiers.md     # Tier model, displacement, assembly sequence            [EXISTS]
└── ...existing contracts...
```

| Contract | Owns | Does NOT Own |
|---|---|---|
| `channel_dsl.md` | Top-level YAML structure, required/optional keys, `format`, `schedule` block syntax, layered override model, grid time model, daypart assignment on schedule blocks. | Pool syntax, program assembly, presentation structure, traffic fill, query operators. |
| `programming_dsl.md` | `programs` section, `pools` section, program fields (`pool`, `select`, `grid_blocks`, `grid_blocks_max`, `fill_mode`, `bleed`, `presentation`), progression modes, slot allocation, grid sizing rules. | Presentation entry structure (→ `presentation_dsl.md`), traffic policy (→ `traffic_dsl.md`), query operators (→ `query_dsl.md`). |
| `presentation_dsl.md` | `presentation` section, program-level and daypart-level preroll/postroll, segment entry types (pool ref, traffic ref), contextual references (`program.rating`), ordering rules, T1/T2/T3 segment definitions. | Tier model and displacement (→ `block_assembly_tiers.md`), pool query syntax (→ `query_dsl.md`). |
| `traffic_dsl.md` | `traffic` section, profiles (`allowed_pools`, `weights`, `rotation`, `cooldowns`, `caps`), break config, default profile, profile resolution order. | Break detection (→ `break_detection.md`), candidate evaluation (→ `traffic_policy.md`), query syntax (→ `query_dsl.md`). |
| `query_dsl.md` | `select.where` syntax, operators (`eq`, `in`, `contains_all`, `lte`, `gte`), contextual references (`program.*`), pool query semantics. | What uses queries (pools, programs, presentation — each documented in their own contracts). |

---

## 5. Authoritative DSL Contract

*This replaces the existing `docs/contracts/channel_dsl.md`.*

See the full contract written to `docs/contracts/channel_dsl.md` (companion file).

---

## 6. Required Invariants

### New invariants introduced by this consolidation

| ID | Guarantee |
|---|---|
| INV-DSL-QUERY-CANONICAL-001 | All asset selection in the DSL MUST use `select.where` syntax. The `match` keyword MUST NOT appear in canonical channel YAML. |
| INV-DSL-POOL-SETS-ONLY-001 | Pools define asset sets via queries. Pools MUST NOT contain selection strategy, ordering, rotation, or progression logic. |
| INV-DSL-PRESENTATION-STRUCTURE-001 | The `presentation` section defines segment structure and ordering. It MUST NOT define selection outcomes — asset selection is resolved at compile time from pools. |
| INV-DSL-TRAFFIC-RESIDUAL-001 | Traffic fills time remaining after structural segments (T0–T3). Traffic MUST NOT displace structural segments, add time, or modify block structure. |
| INV-DSL-SEGMENT-ORDER-DETERMINISTIC-001 | Segment ordering within a block MUST be deterministic for same inputs. Preroll entries appear in declared order. Postroll entries appear in declared order. |
| INV-DSL-MISSING-ASSET-NONFATAL-001 | A presentation or obligation pool that matches zero assets MUST NOT prevent block compilation. The segment is omitted. The compiler MUST log a warning. |
| INV-DSL-GRID-STRUCTURAL-EXPANSION-001 | Grid block allocation MUST expand if structural segments (T0–T3) exceed the initial grid slot. Structural segments are never dropped to fit. (References `INV-GRID-SIZING-STRUCTURAL-001`.) |

### Existing invariants retained (no change)

All `INV-SBLOCK-PROGRAM-*`, `INV-TRAFFIC-DSL-*`, `INV-PRESENTATION-*`, `INV-STRUCTURAL-*`, `INV-EXPANSION-*`, `INV-TIER-*` invariants remain as-is. This consolidation does not modify them.

### Existing invariants retired

| ID | Reason |
|---|---|
| INV-TRAFFIC-DSL-INVENTORY-TYPE-001 | `traffic.inventories` concept removed. Asset sets are pools. |
| INV-TRAFFIC-DSL-INVENTORY-PLANNING-ONLY-001 | Inventory concept removed. Pool queries are planning-time by definition. |

---

## 7. Migration / Deprecation Plan

### Files removed

| File | Reason |
|---|---|
| `docs/contracts/core/programming_dsl.md` | Draft v2, entirely superseded. Uses deprecated concepts (`collection`, `episode_selector`, `movie_selector`, `p.`/`col.` prefixes, Traffic Manager v1). |
| `docs/contracts/core/programming_dsl.schema.json` | Output schema for superseded contract. `compiled_segments` schema is now defined in `block_assembly_tiers.md`. |

### Files replaced

| File | Replaced by | Reason |
|---|---|---|
| `docs/contracts/channel_dsl.md` | `docs/contracts/channel_dsl.md` (rewritten) | Current version uses `match`, `intro`/`outro`, informal invariants. New version uses `select.where`, `presentation`, formal invariants. |

### Files rewritten

| File | Changes |
|---|---|
| `docs/contracts/traffic_dsl.md` | Remove `TrafficInventory` section. `allowed_types` → `allowed_pools`. Add `weights`, `rotation.strategy`, `duration_strategy`. Remove inventory-related invariants. Retain break config, profile resolution, profile-to-policy mapping. |
| `docs/channel-yaml-reference.md` | Rewrite examples with `select.where` syntax. Add `presentation` section. Remove `block:`/`movie_marathon:` legacy block types. Add `daypart` field on schedule blocks. Reflect new traffic profile structure. |

### Files created

| File | Purpose |
|---|---|
| `docs/contracts/presentation_dsl.md` | Presentation structure contract: preroll/postroll, program-level and daypart-level, contextual references, T1/T2/T3 semantics. |
| `docs/contracts/query_dsl.md` | Query language contract: `select.where` operators, contextual references, pool query semantics. |

### Operator YAML changes required

| Change | Before | After |
|---|---|---|
| Pool syntax | `match: { type: movie }` | `select: { where: { type: { eq: movie } } }` |
| Traffic inventories | `traffic.inventories.trailers.match: ...` | Move to top-level `pools.traffic_trailers.select: ...` |
| Traffic allowed types | `allowed_types: [trailer, teaser]` | `allowed_pools: [traffic_trailers, traffic_teasers]` |
| Program presentation | `presentation: [{ pool: intros }]` on program | `presentation: movies` on program + `presentation.programs.movies` block |
| Program intro/outro | `intro: hbo_intro` | Move to presentation preroll/postroll |
| Daypart assignment | (did not exist) | `daypart: late_night` on schedule block |

---

## 8. Philosophy

The RetroVue Channel DSL is:

- **Declarative.** Describes editorial intent — what airs, when, wrapped in what — not how the system assembles it.
- **Deterministic.** Same YAML + same catalog + same broadcast day produces identical compiled output. All randomness flows from seeded RNG.
- **Time-first.** The schedule grid is the organizing principle. Everything else — programs, presentation, traffic — exists relative to grid-aligned time slots.
- **Broadcast-aligned.** Models how real television stations operate: dayparts, preroll/postroll, station IDs, break structure, traffic profiles. The DSL vocabulary matches broadcast operations, not software abstractions.

---
