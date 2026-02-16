# Contract: Programming Pools (Asset Selectors for the DSL)

**Status:** Draft v1
**Depends on:** Programming DSL & Schedule Compiler, Asset Resolver Contract

## Problem

The Programming DSL currently references `col.cheers_s6` as if it were a static collection. But "collections" in the source/ingest domain are physical groupings (e.g., a Plex library called "TV Shows"). These are **not** the same concept as a scheduling pool of assets.

Mixing them causes:
- Tight coupling between source structure and schedule authoring
- Static asset lists that don't update when new content is ingested
- No ability to create cross-source or rule-based groupings
- Naming collision between ingest collections and scheduling references

## Solution: Programming Pools

A **pool** is a named, rule-based query against the asset catalog. Pools are defined in the DSL (or in a shared pool library) and evaluated at compile time. They replace hardcoded `col.*` references.

### Key Distinction

| Concept | Domain | Purpose | Example |
|---------|--------|---------|---------|
| **Source Collection** | Ingest | Physical grouping from a source | Plex "TV Shows" library |
| **Programming Pool** | Scheduling | Logical query for asset selection | "All Cheers Season 6 episodes" |

Source collections are never referenced directly in the DSL. The DSL only references pools.

## Pool Definition Schema

### Inline (in DSL file)

```yaml
pools:
  cheers:
    match:
      type: episode
      series_title: Cheers

  cheers_s6:
    match:
      type: episode
      series_title: Cheers
      season: 6

  eighties_sitcoms:
    match:
      type: episode
      series_title:
        - Cheers
        - The Cosby Show
        - Barney Miller
    order: sequential    # default episode ordering within pool

  short_filler_episodes:
    match:
      type: episode
      max_duration_sec: 1500
      series_title:
        - Batman

  classic_horror:
    match:
      type: movie
      genre:
        - horror
      year_range: [1950, 1989]
      rating:
        include: [PG, PG-13, R]
```

### Shared Pool Library (optional, imported by DSL)

```yaml
# pools/retro_sitcoms.yaml
pools:
  cheers: { match: { type: episode, series_title: Cheers } }
  cheers_s1: { match: { type: episode, series_title: Cheers, season: 1 } }
  cheers_s2: { match: { type: episode, series_title: Cheers, season: 2 } }
  # ...
```

```yaml
# In the DSL file:
imports:
  - pools/retro_sitcoms.yaml

schedule:
  weeknights:
    - start: "20:00"
      slots:
        - title: "Cheers"
          episode_selector:
            pool: cheers_s6
            mode: sequential
```

## Match Criteria

All criteria are AND-combined. Array values are OR within that field.

| Field | Type | Description |
|-------|------|-------------|
| `type` | `string` | Asset type: `episode`, `movie` |
| `series_title` | `string \| string[]` | Exact series name(s) |
| `season` | `int \| int[] \| range` | Season number(s). Supports single (`6`), list (`[1, 3, 5]`), range (`2..10`), or mixed (`[1, 3..6, 9]`). Ranges are inclusive. |
| `episode` | `int \| int[] \| range` | Episode number(s). Same syntax as `season`. |
| `genre` | `string[]` | Any of these genres (future — requires genre tagging) |
| `year_range` | `[int, int]` | Inclusive year range (future — requires year metadata) |
| `rating` | `object` | `{ include: [...], exclude: [...] }` — content rating filter |
| `max_duration_sec` | `int` | Maximum episode/movie duration |
| `min_duration_sec` | `int` | Minimum episode/movie duration |
| `source` | `string` | Source name filter (e.g., "Plex") |
| `collection` | `string` | Source collection name filter (e.g., "TV Shows") |
| `tags` | `string[]` | Custom tags (future — requires tag system) |

### Range Syntax

Numeric fields like `season` and `episode` support a range syntax using `..` (inclusive on both ends):

```yaml
# Single value
season: 6

# Explicit list
season: [1, 3, 5]

# Inclusive range
season: 2..10          # expands to [2, 3, 4, 5, 6, 7, 8, 9, 10]

# Mixed list with ranges
season: [1, 3..6, 9]   # expands to [1, 3, 4, 5, 6, 9]

# Also works for episodes
episode: 1..13          # first 13 episodes of a season
```

The `year_range` field (future) uses the same `..` syntax: `year: 1980..1989`.

### Match Implementation

At compile time, the resolver evaluates each pool's `match` block against the loaded asset catalog. The result is a filtered, ordered list of asset IDs — functionally identical to what the compiler already expects from `AssetMetadata.tags`.

## DSL Changes

### Before (current)
```yaml
episode_selector:
  collection: col.cheers_s6
  mode: sequential
```

### After (with pools)
```yaml
episode_selector:
  pool: cheers_s6
  mode: sequential
```

The keyword changes from `collection` to `pool`. The compiler resolves `cheers_s6` by looking it up in the `pools` section and evaluating the match rules.

### Backward Compatibility

During transition, the compiler SHOULD support both `collection` and `pool` keywords. If `collection` is used with a `col.*` prefix, emit a deprecation warning and attempt to resolve it as a pool with inferred match rules (best-effort).

## Pool Evaluation

### At Compile Time
1. Compiler reads `pools` section from DSL (and any imports)
2. For each pool, evaluates `match` criteria against the asset catalog
3. Returns ordered list of matching asset IDs
4. Selector (`sequential`, `random`, `weighted`) picks from that list

### Ordering Within Pools
Default ordering for matched assets:
- **Episodes:** series_title ASC, season ASC, episode ASC
- **Movies:** title ASC

Can be overridden per pool:
```yaml
pools:
  cheers_random:
    match:
      type: episode
      series_title: Cheers
    order: random
```

### Empty Pools
If a pool evaluates to zero matching assets, the compiler MUST emit a fatal error:
```
CompileError: Pool 'cheers_s6' matched 0 assets (match: {type: episode, series_title: Cheers, season: 6})
```

## Resolver Changes

### Current: `AssetResolver.lookup(asset_id) -> AssetMetadata`
- Collections are pre-baked into the resolver as virtual entries with `tags=(asset_ids...)`
- Lookup is by static ID

### Proposed: Add `AssetResolver.query(match: dict) -> list[str]`
- New method evaluates match criteria dynamically
- Returns ordered list of matching asset IDs
- `lookup()` still works for individual asset metadata
- Pool evaluation calls `query()` internally

```python
class AssetResolver(Protocol):
    def lookup(self, asset_id: str) -> AssetMetadata:
        """Look up a single asset by ID."""
        ...

    def query(self, match: dict[str, Any]) -> list[str]:
        """
        Query the catalog with match criteria.
        Returns ordered list of matching asset IDs.
        Raises AssetResolutionError if no matches.
        """
        ...
```

## Interaction With Source Collections

Source collections (`Collection` entity) are **never** referenced in the DSL. They exist solely in the ingest domain.

However, a pool MAY filter by source collection name as a convenience:
```yaml
pools:
  tv_shows_only:
    match:
      collection: "TV Shows"    # filters to assets from this source collection
```

This is a query filter, not a direct reference. If the source collection is renamed or reorganized, the pool definition is updated — the schedule structure doesn't change.

## Examples

### Full DSL With Pools
```yaml
channel: retro_prime
broadcast_day: "1989-10-12"
timezone: America/New_York

pools:
  cosby_s3:
    match:
      type: episode
      series_title: The Cosby Show
      season: 3
  cheers_s6:
    match:
      type: episode
      series_title: Cheers
      season: 6
  barney_s1:
    match:
      type: episode
      series_title: Barney Miller
      season: 1

schedule:
  weeknights:
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
        - title: "Barney Miller"
          episode_selector:
            pool: barney_s1
            mode: sequential
```

### Cross-Series Pool
```yaml
pools:
  retro_sitcom_mix:
    match:
      type: episode
      series_title:
        - Cheers
        - The Cosby Show
        - Barney Miller
        - Batman

schedule:
  weeknights:
    - start: "22:00"
      slots:
        - title: "Late Night Retro"
          episode_selector:
            pool: retro_sitcom_mix
            mode: random
```

## Related: Virtual Assets

Pools select from existing assets. **Virtual assets** compose new schedulable units from existing assets (e.g., pairing two 12-min episodes into one 24-min unit). Pools can contain virtual assets.

See: [Virtual Assets Contract](virtual_assets.md)

## Open Questions

1. **Pool persistence:** Should evaluated pools be cached/persisted, or always computed fresh at compile time? Fresh is simpler and avoids staleness, but could be slow for very large catalogs.

2. **Pool validation CLI:** Should there be a `retrovue pool list` or `retrovue pool evaluate <name>` command for debugging? Probably yes.

3. **Weighted mode:** How are weights defined? Per-asset? Per-series within a pool? This is a selector concern, not a pool concern, but worth noting.

4. **Future metadata:** Fields like `genre`, `year_range`, and `tags` require enrichment data we don't have yet. The schema should reserve them but the compiler should ignore unknown fields with a warning (not error).

5. **Pool naming:** Is `pool` the right term? Alternatives: `selector`, `filter`, `group`, `roster`. "Pool" suggests "a pool of assets to draw from" which feels right for scheduling.

## Implementation Plan

1. Add `query(match)` method to `AssetResolver` protocol
2. Implement `query()` in `CatalogAssetResolver` using editorial metadata
3. Add `pools` section parsing to DSL parser
4. Update `select_episode()` and `select_movie()` to resolve pools
5. Update test fixtures to use pool syntax
6. Deprecation warning for bare `collection:` references
7. CLI command: `retrovue pool evaluate <pool_def>` for debugging

## Next Steps
- [ ] Review with Steve
- [ ] Finalize match criteria fields (which are v1 vs future)
- [ ] Update programming_dsl.md to reference this contract
- [ ] Update programming_dsl.schema.json with pools schema
- [ ] Implement
