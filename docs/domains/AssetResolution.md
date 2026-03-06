# Asset Resolution — v1.1

**Status:** Foundational Contract
**Version:** 1.1

**Classification:** Domain (Content Resolution)
**Authority Level:** Planning (Tier 2 Resolution)
**Governs:** Source normalization, media hierarchy, programming hierarchy, resolver architecture, template segment source resolution, asset candidate production, episode strategy contracts
**Out of Scope:** Asset selection strategy (rotation, randomness), schedule slot assignment, runtime execution, frame timing, episode strategy implementation

---

## Purpose

Template segments declare *what kind of content* to draw from. The resolver layer normalizes all source definitions into a flat list of playable assets. This normalization is the single gateway between editorial declarations (collections, pools, programs) and the selection discipline that chooses concrete assets.

Without this boundary, every consumer of source definitions must understand the full media hierarchy — collections contain assets, pools are queries across collections, programs are ordered sequences. The resolver absorbs that complexity and presents a uniform `List[Asset]` to all downstream consumers.

This contract defines:

- The media hierarchy that organizes content.
- The source types the resolver must support.
- The resolver invariant: every resolution produces `List[Asset]`.
- The resolver architecture and its specialization points.
- How template segments invoke the resolver.

---

## Media Hierarchy

RetroVue organizes content in a three-level hierarchy:

```
MediaSource
   |
   v
Collection
   |
   v
Asset
```

### MediaSource

A MediaSource is an external content provider (e.g., a Plex library, a filesystem directory). Sources are the ingest boundary. They are discovered, configured, and synced by the operator. Sources own collections.

### Collection

A Collection is a named grouping of assets within a source. Collections are the organizational unit — they represent a library section, a folder, or a provider category. Collections contain assets. Collections are persistent entities owned by Core.

Example:

```
Plex Library (MediaSource)
   +-- Intros (Collection)
   |      +-- hbo_intro_1.mpg (Asset)
   |      +-- hbo_intro_2.mpg (Asset)
   |      +-- showtime_intro_1.mpg (Asset)
   +-- Movies (Collection)
          +-- blade_runner.mkv (Asset)
          +-- alien.mkv (Asset)
```

### Asset

An Asset is the atomic playable unit. Assets have metadata (duration, type, tags, rating, file URI). Assets are the only entities that can appear in a playout plan. Nothing above Asset in the hierarchy is directly playable.

---

## Pools

Pools are **not** part of the media hierarchy. Pools are named queries that return assets.

A pool definition declares match criteria evaluated against the asset catalog:

```yaml
pools:
  hbo_movies:
    match:
      type: movie
      genre: action
    max_duration_sec: 10800
```

A pool resolves to:

```
List[Asset]
```

Pools may return assets from multiple collections and multiple sources. Pool membership is dynamic — it is determined by query evaluation at resolution time, not by static assignment.

Pools are defined in channel configuration alongside templates. They are registered with the resolver before template compilation begins.

---

## Programming Hierarchy

Separate from the storage hierarchy (MediaSource → Collection → Asset), RetroVue maintains a **programming hierarchy** that models editorial content structure:

```
Program
   |
   v
Episode
   |
   v
Asset
```

### Program

A Program is a logical grouping of episodes representing a television show, miniseries, or any ordered content sequence. Programs are editorial entities — they describe what a show *is*, not where its files are stored.

Programs have:

- A unique name (e.g., `Seinfeld`, `Saturday Night Live`).
- An ordered list of episodes.
- No direct file references. Programs are not playable; their episodes are.

Example:

```
Program: Seinfeld
   +-- S01E01: The Seinfeld Chronicles  →  seinfeld_s01e01.mkv (Asset)
   +-- S01E02: The Stakeout             →  seinfeld_s01e02.mkv (Asset)
   +-- S01E03: The Robbery              →  seinfeld_s01e03.mkv (Asset)
   +-- S02E01: The Ex-Girlfriend        →  seinfeld_s02e01.mkv (Asset)
   ...
```

### Episode

An Episode is a single installment of a program. Each episode maps to exactly one asset. Episodes carry sequence metadata (season number, episode number) that determines their position within the program.

Episodes are not independent entities in the resolver — they exist only as members of a program. The resolver traverses Program → Episode → Asset; it never receives a bare episode reference as a source definition.

### Relationship Between Hierarchies

The storage hierarchy and the programming hierarchy are orthogonal:

- **Storage:** Where files live. `MediaSource → Collection → Asset`.
- **Programming:** What shows are. `Program → Episode → Asset`.

An asset can belong to a collection (storage) AND be referenced by a program episode (programming) simultaneously. The same `seinfeld_s02e03.mkv` asset lives in a collection (e.g., "TV Shows") and is the backing asset for Seinfeld S02E03.

The resolver does not conflate these hierarchies. Collection resolution queries by storage membership. Program resolution queries by editorial sequence.

---

## Source Types

The resolver must support the following source type declarations in template segments:

### `type: asset`

Direct asset reference by ID. Resolution is a single lookup. The result is a list containing exactly one asset.

```yaml
source:
  type: asset
  id: "11111111-1111-1111-1111-111111111111"
```

Resolution: `lookup(id)` -> `[Asset]`

### `type: collection`

Named collection reference. Resolution queries all assets belonging to the named collection.

```yaml
source:
  type: collection
  name: Intros
```

Resolution: `query(collection=name)` -> `List[Asset]`

The resolver MUST NOT attempt to `lookup()` a collection name as if it were an asset or pool identifier. Collections are resolved by querying the catalog for assets whose `collection_name` matches the declared name. This is a query operation, not a lookup operation.

### `type: pool`

Named pool reference. Resolution evaluates the pool's match criteria against the catalog.

```yaml
source:
  type: pool
  name: hbo_movies
```

Resolution: `resolve_pool(name)` -> `List[Asset]`

### `type: program`

Named program reference. Resolution looks up the program, retrieves its episodes in sequence order, and returns the backing assets for those episodes.

```yaml
source:
  type: program
  name: Seinfeld
```

Resolution: `resolve_program(name)` -> `List[Asset]` (ordered by episode sequence)

The returned list is ordered by season and episode number. The ordering is authoritative — downstream selection strategies (see Episode Strategies) use this order to determine which episode airs next. The selection layer MUST NOT shuffle or reorder the list produced by program resolution.

Program resolution respects the serialization boundary defined in [Rotation and Asset Selection](RotationAndAssetSelection.md), "Selection vs serialization boundary". Programs own ordered advancement; rotation owns random selection. These are separate authorities.

---

## Episode Strategies

When a template segment uses `source.type: program`, the segment's `selection.strategy` field determines which episode is chosen from the program's ordered episode list. Episode strategies operate on the `List[Asset]` produced by program resolution.

### Strategy Definitions

#### `next_episode`

Selects the next unwatched episode in sequence order. Tracks per-channel progression state — each channel maintains an independent position cursor for each program. After selection, the cursor advances.

```yaml
segments:
  - source:
      type: program
      name: Seinfeld
    selection:
      strategy: next_episode
```

Behavior: If the last aired episode was S02E03, the next resolution returns S02E04's backing asset. When the sequence is exhausted (all episodes have aired), behavior wraps to the beginning (see `cycle`).

#### `random_episode`

Selects an episode uniformly at random from the program's episode list. Does not track or advance a position cursor. Subject to rotation discipline — the Rotation and Asset Selection domain governs repetition avoidance.

```yaml
segments:
  - source:
      type: program
      name: Seinfeld
    selection:
      strategy: random_episode
```

Behavior: Any episode may be selected on each resolution. Rotation constraints (time-window exclusion, count-based exclusion) prevent excessive repetition.

#### `cycle`

Identical to `next_episode` but with explicit wrap-around semantics. When the last episode in the sequence is reached, the cursor resets to the first episode and the cycle repeats.

```yaml
segments:
  - source:
      type: program
      name: Seinfeld
    selection:
      strategy: cycle
```

Behavior: S01E01 → S01E02 → ... → S09E24 → S01E01 → ... (infinite loop through the program).

### Strategy Invariants

- All strategies receive the same input: the ordered `List[Asset]` from program resolution.
- All strategies produce the same output: a single asset ID (or a filtered candidate set for the mode layer).
- Strategy state (position cursors) is per-channel, per-program. One channel's progression through Seinfeld does not affect another channel's position.
- Strategy state is persistent. Process restarts do not reset episode position.
- Strategies are declared on the template segment, not on the program definition. The same program may use `next_episode` on one channel and `random_episode` on another.

### Strategy Implementation Status

Episode strategies are **defined but not implemented**. The contract specifies their behavioral guarantees. Implementation is deferred until the ProgramResolver is built. Tests may validate the contract interface without exercising real episode progression.

---

## Resolver Invariant

**INV-ASSET-RESOLUTION-NORMALIZE-001**

The resolver MUST always return:

```
List[Asset]
```

The resolver MUST NEVER return:

- A `Collection` — collections are organizational containers, not playable units.
- A `Pool` — pools are query definitions, not content.
- A `Program` — programs are sequence definitions, not content.

These are editorial and organizational constructs. They exist to help operators structure content. The resolver's job is to dereference them into the assets they contain or match.

Every code path through the resolver — regardless of source type — terminates with a list of asset identifiers (or asset metadata objects) that are individually playable. If resolution produces zero assets, it is a hard failure (see Failure Behavior).

**Corollary:** Template segments operate exclusively on assets after resolution. No segment selection rule, mode strategy, or downstream consumer ever receives a collection, pool, or program object. The resolver is the normalization boundary.

---

## Resolver Architecture

### Interface

The resolver exposes a unified resolution interface:

```
resolve(source_definition) -> List[AssetID]
```

Where `source_definition` contains `type` and either `name` or `id`.

Internally, the resolver dispatches to specialized resolution strategies based on source type.

### Specialized Resolvers

```
SourceResolver
   |-- resolve(source) -> List[AssetID]
   |
   +-- AssetSourceResolver     (type: asset)
   +-- CollectionResolver      (type: collection)
   +-- PoolResolver            (type: pool)
   +-- ProgramResolver         (type: program)
```

| Source Type  | Resolution Strategy | Input | Output |
|-------------|-------------------|-------|--------|
| `asset`     | Direct lookup     | Asset ID | `[AssetID]` |
| `collection`| Catalog query by collection name | Collection name | `List[AssetID]` |
| `pool`      | Pool match criteria evaluation | Pool name | `List[AssetID]` |
| `program`   | Program lookup + episode enumeration | Program name | `List[AssetID]` (ordered by season/episode) |

### Resolution Rules

1. **Asset resolution** calls `lookup(asset_id)`. If the asset exists and is in `ready` state, the result is `[asset_id]`. If not found, resolution fails.

2. **Collection resolution** calls `query({"collection": collection_name})`. This queries the catalog for all assets whose collection membership matches the name. The result is the full candidate set from that collection. If the collection is empty or unknown, resolution fails.

3. **Pool resolution** calls `resolve_pool(pool_name)`. The pool's `match` criteria are evaluated against the catalog. The result is all matching assets across all collections and sources. If no assets match, resolution fails.

4. **Program resolution** calls `resolve_program(program_name)`. The program is looked up by name. Its episodes are enumerated in season/episode order. Each episode's backing asset ID is collected into the result list. The ordering is authoritative — it reflects the editorial sequence of the show. The selection layer (via episode strategies) picks from this ordered list but MUST NOT reorder it. If the program is not found or contains zero episodes, resolution fails.

### Relationship to Existing Protocol

The current `AssetResolver` protocol (in `asset_resolver.py`) provides `lookup()` and `query()` as primitive operations. The source resolution layer described here is built on top of these primitives:

- `type: asset` -> `lookup(id)`
- `type: collection` -> `query({"collection": name})`
- `type: pool` -> `resolve_pool(name)` (which internally calls `query(match)`)
- `type: program` -> `resolve_program(name)` (program lookup + episode enumeration + asset mapping)

The specialized resolvers are dispatch logic within the `SourceResolver` that selects the correct resolution path based on `source.type`. The architecture must support extracting them into dedicated resolver implementations without changing the contract.

---

## Template Interaction

Templates declare segments. Each segment declares a source. The resolver normalizes that source into `List[Asset]`. The selection layer then filters and picks from that list.

### Resolution Flow

```
Template Segment
       |
       v
  source definition
  {type, name/id}
       |
       v
  Resolver dispatch
  (asset | collection | pool | program)
       |
       v
  List[AssetID]   <-- resolver invariant boundary
       |
       v
  Selection rules
  (tag filters, metadata filters)
       |
       v
  Filtered List[AssetID]
       |
       v
  Mode strategy
  (random, sequential, serial)
       |
       v
  Single Asset
```

### Example: Collection Source With Tag Filter

```yaml
segments:
  - source:
      type: collection
      name: Intros
    selection:
      - type: tags
        values: [hbo]
    mode: random
```

Resolution:

1. Resolver receives `{type: collection, name: Intros}`.
2. Dispatches to collection resolution: `query({"collection": "Intros"})`.
3. Returns `List[AssetID]` — all assets in the Intros collection.
4. Selection layer applies tag filter: keep only assets with tag `hbo`.
5. Mode `random` selects one asset from the filtered list.
6. Result: one playable asset.

### Example: Pool Source

```yaml
segments:
  - source:
      type: pool
      name: hbo_movies
    mode: random
```

Resolution:

1. Resolver receives `{type: pool, name: hbo_movies}`.
2. Dispatches to pool resolution: `resolve_pool("hbo_movies")`.
3. Pool match criteria `{type: movie, genre: action}` evaluated against catalog.
4. Returns `List[AssetID]` — all matching assets across all collections.
5. Mode `random` selects one asset.
6. Result: one playable asset.

### Example: Program Source With Episode Strategy

```yaml
segments:
  - source:
      type: program
      name: Seinfeld
    selection:
      strategy: next_episode
```

Resolution:

1. Resolver receives `{type: program, name: Seinfeld}`.
2. Dispatches to program resolution: `resolve_program("Seinfeld")`.
3. Program lookup finds the Seinfeld program entity.
4. Episodes are enumerated in season/episode order.
5. Each episode's backing asset ID is collected.
6. Returns `List[AssetID]` — e.g., `[seinfeld_s01e01_uuid, seinfeld_s01e02_uuid, ...]`.
7. Episode strategy `next_episode` consults the per-channel position cursor.
8. If last aired was S02E03, selects S02E04's asset.
9. Result: one playable asset.

The resolver's job ends at step 6 — producing the ordered `List[AssetID]`. Steps 7–9 are the responsibility of the episode strategy layer, which is downstream of resolution.

---

## Failure Behavior

Resolution failures are explicit and hard. The resolver does not silently return empty results, substitute from unrelated sources, or degrade to partial output.

### Failure Conditions

| Condition | Behavior |
|-----------|----------|
| Unknown source type | Hard failure. Compile error. |
| Asset ID not found | Hard failure. `KeyError`. |
| Collection name matches zero assets | Hard failure. `AssetResolutionError`. |
| Pool name not registered | Hard failure. `KeyError`. |
| Pool match criteria match zero assets | Hard failure. `AssetResolutionError`. |
| Program name not found | Hard failure. `KeyError`. |
| Program contains zero episodes | Hard failure. `AssetResolutionError`. |
| Episode references non-existent asset | Hard failure. `AssetResolutionError`. |

### Failure Reporting

All failures MUST surface to the operator. The failure report includes:

- The source type and name/id that failed.
- The template and segment that triggered resolution.
- The channel and time window context.

Silent failure is prohibited. A segment that cannot resolve its source produces no output, and the entire template resolution fails.

---

## Program Resolution Detail

### ProgramResolver Behavior

The ProgramResolver implements the following conceptual flow:

```
resolve(source: {type: program, name: <program_name>})
   |
   v
lookup program by name
   |
   v
enumerate episodes in (season, episode) order
   |
   v
map each episode to its backing asset ID
   |
   v
return List[AssetID]  (ordered)
```

### Program Data Requirements

A program definition must provide:

- **name** — Unique program identifier (e.g., `"Seinfeld"`).
- **episodes** — An ordered sequence where each entry maps to an asset ID.

Episode ordering is determined by `(season_number, episode_number)` sort. The resolver does not infer order from file names, ingest timestamps, or any other heuristic. Season and episode numbers are the authoritative sort key.

### Program Resolution Output

The output is `List[AssetID]` where:

- The list is ordered by `(season_number, episode_number)` ascending.
- Each element is a valid asset ID that exists in the catalog.
- Duplicate asset IDs are permitted (e.g., a clip show may reference previously aired episodes).
- The list contains ALL episodes in the program, not a filtered subset. Filtering is the responsibility of the episode strategy layer.

### Episode Strategy Interaction

The ProgramResolver produces the full ordered episode list. Episode strategies consume this list:

- `next_episode` / `cycle` — Consult a per-channel position cursor, select one asset, advance the cursor.
- `random_episode` — Select uniformly at random from the list, subject to rotation constraints.

The resolver has no knowledge of episode strategies. It produces the complete list; the strategy layer narrows it to a single selection.

### Program Implementation Status

The ProgramResolver contract is **defined and testable at the interface level**. The `SourceResolver` must accept `type: program` as a valid source type and dispatch to program resolution. Full implementation (database-backed program entities, episode enumeration from catalog) is deferred. Tests validate the contract shape with stub program data.

---

## Future Extensibility

### Additional Source Types

New source types may be added by:

1. Defining the source type in this contract.
2. Specifying its resolution strategy (what primitives it calls).
3. Verifying it satisfies the resolver invariant: output is always `List[Asset]`.
4. Adding dispatch logic in the `SourceResolver`.

No new source type may bypass the normalization boundary. All source types resolve to `List[Asset]`.

---

## Invariant Summary

| ID | Statement |
|----|-----------|
| INV-ASSET-RESOLUTION-NORMALIZE-001 | The resolver always returns `List[Asset]`. Never `Collection`, `Pool`, or `Program`. |
| INV-ASSET-RESOLUTION-COLLECTION-QUERY-001 | Collection sources resolve via `query({"collection": name})`, not via `lookup()`. |
| INV-ASSET-RESOLUTION-POOL-QUERY-001 | Pool sources resolve via `resolve_pool(name)`, which evaluates match criteria against the catalog. |
| INV-ASSET-RESOLUTION-PROGRAM-RESOLVE-001 | Program sources resolve via `resolve_program(name)`, returning episodes' backing assets in `(season, episode)` order. |
| INV-ASSET-RESOLUTION-PROGRAM-ORDER-001 | Program resolution output is ordered by `(season_number, episode_number)`. The selection layer MUST NOT reorder it. |
| INV-ASSET-RESOLUTION-EMPTY-FAIL-001 | Zero-asset resolution is a hard failure. No silent empty returns. |
| INV-ASSET-RESOLUTION-DISPATCH-001 | Source type determines the resolution strategy. Unknown source types are compile errors. Supported types: `asset`, `collection`, `pool`, `program`. |

---

## Changelog

| Version | Date       | Summary |
|---------|------------|---------|
| 1.0     | 2026-03-06 | Initial contract: asset, collection, pool source types. |
| 1.1     | 2026-03-06 | Add program source type, programming hierarchy, episode strategies, ProgramResolver contract. |

---

**Document version:** 1.1
**Related:** [Program Template Assembly (v1.0)](ProgramTemplateAssembly.md) · [Rotation and Asset Selection (v1.0)](RotationAndAssetSelection.md) · [ScheduleItem](ScheduleItem.md)
**Governs:** Source normalization, media hierarchy, programming hierarchy, resolver architecture, template segment source resolution, asset candidate production, episode strategy contracts
