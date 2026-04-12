# Pool (Programming Pool)

**Domain:** scheduling
**Slug:** `pool`

## What it represents

**A named, rule-based query against the asset catalog.** Pools replace hardcoded `col.*` collection references in the DSL with logical, dynamic selectors that evaluate at compile time. A pool is a persistent named definition — not a runtime object — that bridges editorial intent ("I want Cheers Season 6 episodes") to catalog resolution ("which asset IDs match?").

## Key distinction from Source Containers

| Concept | Domain | Purpose |
|---------|--------|---------|
| **Source Container** | Ingest | Physical grouping from a source (e.g., a Plex library) |
| **Programming Pool** | Scheduling | Logical query for asset selection (e.g., "All Cheers Season 6 episodes") |

Source containers are never referenced directly in the DSL. The DSL only references pools.

## Definition syntax

Pools are declared in channel DSL YAML under the `pools:` key. Two syntaxes:

- **Legacy `match:`** — flat criteria dict consumed directly by the asset resolver
- **Canonical `select.where:`** — structured operators (`eq`, `in`, `contains_all`, etc.) normalized to `match` at `register_pools` time via `pool_dsl_normalize.py`

## Lifecycle phase

1. **Declared** in channel DSL YAML (`pools:` section)
2. **Normalized** via `pool_dsl_normalize.normalize_pool_definition()` (bridges `select.where` → `match`)
3. **Registered** with `AssetResolver.register_pools()` at compile time
4. **Resolved** via `AssetResolver.resolve_pool(name)` during schedule compilation to yield matching asset IDs
5. **Consumed** by the schedule compiler (`schedule_compiler.py`) when building schedule blocks — `prog_def.get("pool", chosen_ref)` resolves to a pool name

## Owning domain

scheduling

## What produces it

DSL compilation. Pools originate exclusively from DSL YAML — either inline in the channel DSL or from a shared pool library imported by the DSL.

## What consumes it

- **Schedule compiler** (`schedule_compiler.py`) — resolves pool names to asset IDs during block assembly
- **AssetResolver** (`CatalogAssetResolver`, `StubAssetResolver`) — executes the pool query against the catalog
- **DslScheduleService** — registers pools with the resolver before compilation

## What it depends on

- **Asset catalog** — pool queries execute against catalog rows; pool results are only as current as the catalog
- **DSL** — pools are declared in DSL YAML; no other origin path exists
- **AssetResolver protocol** — defines `register_pools()`, `resolve_pool()`, `query()`, and `query_with_diagnostics()`

## What depends on it

- Block assembly receives the resolved asset list from pool evaluation
- Progression cursors track position within a pool's resolved asset sequence

## Key invariants

- `INV-POOL-RATING-NORMALIZE-001` — rating match normalizes shorthand to canonical form
- `INV-POOL-TAGS-FILTER-001` — tags evaluated as AND-combined filter
- `INV-POOL-RESOLUTION-VISIBILITY-001` — pool resolution produces per-filter exclusion diagnostics (`PoolDiagnostics`)

## Canonical contract

`docs/contracts/core/programming_pools.md`

## Implementation files

- `server/src/retrovue/runtime/pool_dsl_normalize.py` — `select.where` → `match` normalization
- `server/src/retrovue/runtime/asset_resolver.py` — `AssetResolver` protocol + `PoolDiagnostics`
- `server/src/retrovue/runtime/catalog_resolver.py` — `CatalogAssetResolver.register_pools()` + query execution
- `server/src/retrovue/dev/stub_asset_resolver.py` — test/dev resolver with pool support

## What must NOT be assumed

- That pools are runtime objects with mutable state — they are compile-time query definitions.
- That pool names correspond 1:1 to source containers — pools are scheduling-domain concepts.
- That pools bypass `LAW-ELIGIBILITY` — pool resolution filters after eligibility gating.
- That inline `match:` syntax is deprecated — both `match:` and `select.where:` are valid; normalization bridges them.
