# Contract: Virtual Assets (Composite Scheduling Units)

**Status:** Draft v1
**Depends on:** Programming Pools, Programming DSL & Schedule Compiler, Asset Resolver Contract

## Problem

Some content doesn't fit standard grid slots as-is:
- **The Fairly OddParents** — ~12-min episodes, need to pair two into a 30-min slot
- **Short-form cartoons** — 7-min segments, bundle 3 into a 30-min block
- **Two-part episodes** — aired as one continuous block
- **Marathon blocks** — multiple movies scheduled as a single programming decision

The compiler currently treats every asset as atomic. There's no way to express "combine these into one schedulable unit" without creating actual edited files — which defeats the purpose of a virtual playout system.

## Solution: Virtual Assets

A **virtual asset** is a scheduling-domain composite that combines multiple real assets into a single schedulable unit. The compiler and playout log expander treat it as one asset with:
- Combined duration (sum of parts)
- Chapter markers injected at segment boundaries (natural ad break points)
- A single `asset_id` in the program schedule output
- Ordered segment list for the playout chain

Virtual assets are **not** stored in the asset catalog. They exist only in the DSL/scheduling domain and are resolved at compile time.

## Relationship to Other Concepts

| Concept | Creates assets? | Selects assets? | Domain |
|---------|:-:|:-:|--------|
| Source Collection | ✗ | ✗ | Ingest |
| Programming Pool | ✗ | ✓ | Scheduling |
| **Virtual Asset** | **✓ (composite)** | ✗ | Scheduling |

- Pools MAY contain virtual assets
- Virtual assets MAY draw from pools for their segments
- The compiler resolves virtual assets before pool evaluation

## Composition Modes

### `pair` — Combine N episodes into one unit

The most common case. Takes a pool of short episodes and pairs them sequentially or randomly.

```yaml
virtual_assets:
  fairly_odd_parents:
    compose: pair
    count: 2                    # episodes per virtual asset (default: 2)
    from:
      pool: fairly_odd_raw      # pool of real ~12-min episodes
    mode: sequential            # (1+2), (3+4), (5+6)...
```

**Behavior:**
- At compile time, selects `count` episodes from the pool using `mode`
- Combined duration = sum of episode durations
- Chapter marker inserted at each episode boundary
- Virtual asset ID: `virtual.fairly_odd_parents.{seed}` (deterministic from seed)

### `block` — Assemble segments from different pools

Like how Cartoon Network packaged multiple shows into one programming block.

```yaml
virtual_assets:
  cartoon_block:
    compose: block
    segments:
      - pool: dexter_raw           # ~7 min
      - pool: powerpuff_raw        # ~7 min
      - pool: johnny_bravo_raw     # ~7 min
    # Total: ~21 min, fits a 30-min grid slot
```

**Behavior:**
- Selects one asset from each segment's pool
- Segments play in defined order
- Chapter markers at each segment boundary
- Each segment's pool uses its own selector state (sequential/random/seed)

### `sequence` — Explicit ordered list of specific assets

For curated combinations — marathons, two-parters, themed blocks.

```yaml
virtual_assets:
  bttf_marathon:
    compose: sequence
    assets:
      - asset.bttf_1
      - asset.bttf_2
      - asset.bttf_3
    # Total: ~5.5 hours, spans multiple grid slots
```

**Behavior:**
- Assets are resolved by ID at compile time
- Plays in exact listed order
- Chapter markers at each asset boundary (plus any existing chapter markers within each asset)
- Useful for multi-slot programming decisions

## Virtual Asset Metadata

When the compiler or resolver encounters a virtual asset, it returns an `AssetMetadata` with:

```python
AssetMetadata(
    type="virtual",
    duration_sec=sum_of_segments,
    tags=(),                              # not a collection
    chapter_markers_sec=(                  # markers at segment boundaries
        0.0,                              # start of segment 1
        segment_1_duration,               # start of segment 2
        segment_1 + segment_2_duration,   # start of segment 3
        ...
    ),
    file_uri="",                          # no single file — segments resolved separately
)
```

The **playout log expander** sees chapter markers at segment boundaries and treats them like act breaks — inserting ad blocks between segments. This means:
- Two paired FairlyOddParents episodes get a commercial break between them
- A cartoon block gets breaks between each show
- This matches how real TV networks package short content

## Playout Chain Resolution

When the playout system needs to actually play a virtual asset, it resolves the segment list:

```json
{
  "virtual_asset_id": "virtual.fairly_odd_parents.42",
  "segments": [
    { "asset_id": "uuid-episode-1", "file_uri": "plex://12345", "duration_sec": 720 },
    { "asset_id": "uuid-episode-2", "file_uri": "plex://12346", "duration_sec": 715 }
  ],
  "total_duration_sec": 1435,
  "chapter_markers_sec": [0.0, 720.0]
}
```

The playout chain plays segment 1, hits the chapter marker at 720s, inserts an ad break, then plays segment 2.

## DSL Integration

### Defining Virtual Assets

Virtual assets are defined in the `virtual_assets` section, alongside `pools`:

```yaml
pools:
  fairly_odd_raw:
    match:
      type: episode
      series_title: The Fairly OddParents

virtual_assets:
  fairly_odd_parents:
    compose: pair
    count: 2
    from:
      pool: fairly_odd_raw
    mode: sequential

schedule:
  weekdays:
    - start: "16:00"
      slots:
        - title: "The Fairly OddParents"
          episode_selector:
            pool: fairly_odd_paired   # a pool of the virtual assets
            mode: sequential
```

### Pools of Virtual Assets

A pool can reference virtual assets. When a virtual asset definition has `compose: pair` with a source pool, it implicitly creates a derived pool of all possible pairings:

```yaml
# This pool contains virtual assets, not raw episodes
pools:
  fairly_odd_paired:
    from_virtual: fairly_odd_parents
```

Or the compiler can infer this — if `episode_selector.pool` points to a virtual asset name, it resolves through the virtual asset definition automatically.

### Shared Library

Like pools, virtual assets can live in importable files:

```yaml
# virtual_assets/nickelodeon.yaml
virtual_assets:
  fairly_odd_parents:
    compose: pair
    count: 2
    from:
      pool: fairly_odd_raw
    mode: sequential

  spongebob_paired:
    compose: pair
    count: 2
    from:
      pool: spongebob_raw
    mode: sequential
```

```yaml
# In DSL file:
imports:
  - pools/nickelodeon_pools.yaml
  - virtual_assets/nickelodeon.yaml
```

## Edge Cases

### Odd Episode Counts
If a pool has 7 episodes and `compose: pair, count: 2`, the last episode has no pair.
- **Option A:** Skip it (default) — pool yields 3 virtual assets
- **Option B:** Allow it as a short virtual asset — `allow_short: true`
- **Decision:** TBD — default to skip, flag with a compiler warning

### Duration Overflow
Two 15-min episodes paired = 30 min of content in a 30-min slot = zero ad time.
- Compiler SHOULD warn if virtual asset duration ≥ slot duration
- Not a fatal error — operator may intend ad-free blocks

### Nested Virtual Assets
Can a virtual asset contain another virtual asset? **No.** Virtual assets compose real assets only. Keep it simple.

## Open Questions

1. **Naming convention:** `virtual.{name}.{seed}` for generated IDs? Or something shorter?

2. **Selector state:** When `pair` mode is `sequential`, does the seed advance per-compile or persist across broadcast days? (Same question exists for pool selectors generally — not unique to virtual assets.)

3. **Segment-level ad control:** Should virtual assets allow specifying whether ad breaks go between segments? e.g., `breaks: between_segments | none | custom`. Default `between_segments` seems right.

4. **Pre-roll / post-roll:** Should virtual assets support wrapping segments with bumpers? e.g., "Coming up next on The Fairly OddParents..." — or is that a playout packaging concern?

5. **UI representation:** How does the UI show virtual assets? As a distinct entity type? Or just as a pool with a "composed" badge?

## Implementation Plan

1. Define `VirtualAssetDefinition` dataclass in the DSL parser
2. Add `virtual_assets` section parsing to `parse_dsl()`
3. Add virtual asset resolution to `CatalogAssetResolver` (or a `VirtualAssetResolver` wrapper)
4. Update `select_episode()` to handle virtual asset pools
5. Update playout log expander to resolve segments from virtual assets
6. Test fixtures for each composition mode
7. CLI command: `retrovue virtual-asset evaluate <name>` for debugging

## Next Steps
- [ ] Review with Steve
- [ ] Decide on edge case behavior (odd counts, duration overflow)
- [ ] Determine if this is v1 or v2 scope
- [ ] Implement after pools contract is finalized
