# Current Pipeline Inventory — Media Ingestion and Metadata

This document is a technical inventory of the **existing** RetroVue media ingestion and metadata pipeline. It describes the current implementation only; it does not define or propose behavior. It is intended to support a future refactor toward the contract-defined architecture (ContainerDiscoveryContract, CatalogReconciliationContract, ProcessorJobQueueContract, etc.).

---

## Pipeline Stages (Execution Order)

The current pipeline runs **synchronously** when the operator runs `retrovue source ingest <source>` or `retrovue collection ingest <collection>`.

1. **Source / collection resolution** — Resolve CLI selector (UUID, external_id, name) to `Source` or `Collection` and build importer config from `Source.config` and `Collection.config`.
2. **Prerequisite validation** — Ensure collection is `sync_enabled` and `ingestible`; call `importer.validate_ingestible(collection)` before discovery.
3. **Discovery** — Importer returns a list of items (`importer.discover()` or `importer.discover_scoped(title, season, episode)`). Items are dict-like or `DiscoveredItem` with `path_uri`, `provider_key`, `raw_labels`, etc.
4. **Path resolution** — For each item, resolve playable path (e.g. Plex path → local path via `AssetPathResolver` and `PathMapping`); may overwrite `item.path_uri` with local file path for enrichers.
5. **Enricher pipeline** — Build pipeline from `collection.config['enrichers']` (and optional InterstitialTypeEnricher). For each discovered item, run each enricher in priority order: `enriched = enr.enrich(item)`. Enrichers add `raw_labels`, `probed`, etc.; pipeline checksum is attached for later staleness detection.
6. **Metadata merge** — Build ingest payload (editorial, probed, sidecars, etc.) and call `handle_ingest(payload)`, which validates/merges sidecars and returns resolved editorial/probed/station_ops/relationships.
7. **Canonical identity** — Compute `canonical_key = canonical_key_for(item, collection, provider)` and `canonical_key_hash = canonical_hash(canonical_key)`.
8. **Deduplication** — Look up existing asset by `(collection_uuid, canonical_key_hash)`. If found, skip (count as `assets_skipped`); no update in this path.
9. **Catalog mutation (new asset)** — Create `Asset` row, persist tags to `asset_tags`, call `persist_asset_metadata()` for editorial/probed/station_ops/relationships/sidecar. Flush; no commit (caller owns transaction).
10. **Reconciliation (full collection only)** — After processing all items, any asset in the collection with `canonical_key_hash` not in the set of seen hashes is marked `is_deleted=True`, `deleted_at=now`. Counted as `assets_removed`.
11. **Re-enrichment (separate entry points)** — For existing assets: `asset reprobe <uuid>`, `asset enrich --stale`, or `collection enrichers apply` build the same enricher pipeline and call `enrich_asset(db, asset, pipeline)`, which clears probe data, resets approval/state, runs pipeline on a synthetic DiscoveredItem, then persists and promotes to `ready` if duration present.

There is **no separate processor job queue**. All enrichment runs in the same process and transaction as discovery and catalog mutation.

---

## Code Locations

### Container / source scanning and collection discovery

| Responsibility | Module / file | Key classes / functions |
|----------------|--------------|--------------------------|
| List collections from a source | `pkg/core/src/retrovue/usecases/source_discover.py` | `discover_collections(db, source_id)` |
| Importer registry and construction | `pkg/core/src/retrovue/adapters/registry.py` | `get_importer(name, **kwargs)`, `SOURCES` (FilesystemImporter, PlexImporter) |
| Importer interface and discovered item shape | `pkg/core/src/retrovue/adapters/importers/base.py` | `ImporterInterface`, `BaseImporter`, `DiscoveredItem` |
| Filesystem container scanning | `pkg/core/src/retrovue/adapters/importers/filesystem_importer.py` | `FilesystemImporter.list_collections()`, `discover()`, `discover_scoped()` |
| Plex container scanning | `pkg/core/src/retrovue/adapters/importers/plex_importer.py` | `PlexImporter.list_collections()`, `discover()` |
| Build importer for a collection | `pkg/core/src/retrovue/cli/commands/collection.py` | `construct_importer_for_collection(collection, db)` |

### Media discovery

| Responsibility | Module / file | Key classes / functions |
|----------------|--------------|--------------------------|
| Enumerate items in a collection | Same importers as above | `importer.discover()`, `importer.discover_scoped(title, season, episode)` |
| Discovery invoked from ingest | `pkg/core/src/retrovue/cli/commands/_ops/collection_ingest_service.py` | `CollectionIngestService.ingest_collection()` → `importer.discover()` or `discover_scoped()` |

### Catalog / database mutation

| Responsibility | Module / file | Key classes / functions |
|----------------|--------------|--------------------------|
| Source-level ingest orchestration | `pkg/core/src/retrovue/cli/commands/_ops/source_ingest_service.py` | `SourceIngestService`, `ingest_source(source, dry_run, test_db)` |
| Collection-level ingest orchestration | `pkg/core/src/retrovue/cli/commands/_ops/collection_ingest_service.py` | `CollectionIngestService`, `ingest_collection(collection, importer, ...)`, `_AssetRepository` |
| Asset creation and tag persistence | Same file | `_AssetRepository.create(asset)`, `AssetTag` merge, `persist_asset_metadata()` |
| Metadata persistence to child tables | `pkg/core/src/retrovue/infra/metadata/persistence.py` | `persist_asset_metadata(db, asset, editorial=, probed=, ...)` |
| Reconciliation (mark missing as deleted) | `collection_ingest_service.py` | Inline in `ingest_collection`: query assets not in `seen_hashes`, set `is_deleted`, `deleted_at` |

### Asset and media identity

| Responsibility | Module / file | Key classes / functions |
|----------------|--------------|--------------------------|
| Canonical key and hash | `pkg/core/src/retrovue/infra/canonical.py` | `canonical_key_for(item, collection, provider)`, `canonical_hash(canonical_key)` |
| Duplicate detection | `collection_ingest_service.py` | `_AssetRepository.get_by_collection_and_canonical_hash(collection_uuid, canonical_key_hash)` |
| Domain entities | `pkg/core/src/retrovue/domain/entities.py` | `Asset`, `Collection`, `Source` (no separate `Media` entity; Asset is the single catalog entity for playable items) |

### Metadata extraction (enrichers)

| Responsibility | Module / file | Key classes / functions |
|----------------|--------------|--------------------------|
| Enricher interface and registry | `pkg/core/src/retrovue/adapters/enrichers/base.py` | `Enricher` protocol, `BaseEnricher` |
| FFprobe technical metadata | `pkg/core/src/retrovue/adapters/enrichers/ffprobe_enricher.py` | `FFprobeEnricher.enrich(discovered_item)` |
| Interstitial type from collection name | `pkg/core/src/retrovue/adapters/enrichers/interstitial_type_enricher.py` | `InterstitialTypeEnricher.enrich()` |
| Loudness | `pkg/core/src/retrovue/adapters/enrichers/loudness_enricher.py` | `LoudnessEnricher.enrich()` |
| Enricher lookup by type | `pkg/core/src/retrovue/adapters/registry.py` | `ENRICHERS` dict (ffprobe, interstitial-type, loudness) |

### Metadata enrichment and merge

| Responsibility | Module / file | Key classes / functions |
|----------------|--------------|--------------------------|
| Sidecar validation and merge | `pkg/core/src/retrovue/usecases/metadata_handler.py` | `preprocess_sidecars()`, `validate_sidecar()`, `deep_merge_metadata()` |
| Ingest payload resolution | Same file | `handle_ingest(payload)` → returns `resolved_fields` (editorial, probed, station_ops, relationships, sidecar) |
| Pipeline build (collection) | `collection_ingest_service.py` | Build list of `(enricher_id, priority, instance)` from `collection.config['enrichers']` and Enricher rows; sort by priority; optional InterstitialTypeEnricher injection |
| Pipeline execution (per item) | Same file | Loop over pipeline, `item = enr.enrich(item)`; attach `pipeline_checksum` to item |
| Single-asset re-enrichment | `pkg/core/src/retrovue/usecases/asset_enrich.py` | `enrich_asset(db, asset, pipeline, pipeline_checksum)` |
| Bulk re-apply enrichers to collection | `pkg/core/src/retrovue/usecases/collection_enrichers.py` | `apply_enrichers_to_collection()`, `attach_enricher_to_collection()`, `detach_enricher_from_collection()` |
| Reprobe single asset | `pkg/core/src/retrovue/usecases/asset_reprobe.py` | `reprobe_asset(db, asset_uuid)` → builds pipeline from asset’s collection, calls `enrich_asset()` |

### Background job processing

| Responsibility | Module / file | Key classes / functions |
|----------------|--------------|--------------------------|
| Background job queue | **Not present** | No processor job queue; no async workers; no job table. |
| Scheduled / daemon-triggered ingest | **Not present** | Ingest is only triggered by CLI (`source ingest`, `collection ingest`). No daemon runs discovery or reconciliation on a schedule. |

### Processor / analyzer execution

| Responsibility | Module / file | Key classes / functions |
|----------------|--------------|--------------------------|
| Execution of enrichers | Inline in `CollectionIngestService.ingest_collection()` and in `enrich_asset()` | Enrichers run in the same process and transaction as ingest. No separate “processor runtime” or worker. |
| Enricher config storage | `pkg/core/src/retrovue/domain/entities.py` | `Enricher` table (enricher_id, type, scope, name, config); referenced by `collection.config['enrichers']`. |

---

## Data Flow

1. **CLI** — `retrovue source ingest <selector>` or `retrovue collection ingest <selector>` opens a DB session and calls `SourceIngestService.ingest_source(source)` or `CollectionIngestService.ingest_collection(collection, importer, ...)`.
2. **Importer** — Built from `Source` type and config (and optionally `Collection.external_id` for Plex). Returns list of items (dict or `DiscoveredItem`) with `path_uri`, `provider_key`, `raw_labels`, `editorial`, etc.
3. **Path resolution** — `AssetPathResolver.resolve(uri)` uses `PathMapping` (and optionally Plex client) to turn Plex or remote URIs into local file paths; ingest overwrites `item.path_uri` so enrichers (e.g. ffprobe) see a local path.
4. **Enricher pipeline** — Each item is passed through the pipeline; each enricher returns an updated item (e.g. FFprobeEnricher adds `raw_labels` and `probed`). Pipeline checksum is stored on the item and later on `Asset.last_enricher_checksum` for staleness checks.
5. **Payload and merge** — Code builds a payload (importer_name, asset_type, source_uri, editorial, probed, sidecars, etc.) and calls `handle_ingest(payload)`. Handler validates sidecars, merges editorial/probed/station_ops/relationships, returns `resolved_fields`.
6. **Identity and persistence** — `canonical_key_for` / `canonical_hash`; lookup by (collection_uuid, canonical_key_hash). If new: create `Asset`, write tags, `persist_asset_metadata()`. If existing: skip (no update in collection ingest).
7. **Reconciliation** — After the loop, assets in the collection whose `canonical_key_hash` was not seen are soft-deleted.
8. **Commit** — Caller (CLI) commits the session after `ingest_collection` or `ingest_source` returns.

Re-enrichment flows (reprobe, enrich --stale, apply enrichers) load the asset and its collection, build the same pipeline from collection config, call `enrich_asset(db, asset, pipeline)`, which clears probe data and approval, builds a synthetic DiscoveredItem from the asset, runs the pipeline, then maps results back to the asset and child tables and promotes state to `ready` if duration is set.

---

## Data Models Involved

- **Source** — id, external_id, name, type (plex, filesystem), config. One-to-many Collections.
- **Collection** — uuid, source_id, external_id, name, sync_enabled, ingestible, config (includes `enrichers` list and optionally `locations`). One-to-many Assets; many PathMappings.
- **Asset** — uuid, collection_uuid, canonical_key, canonical_key_hash, uri, canonical_uri, size, state, approved_for_broadcast, operator_verified, duration_ms, video_codec, audio_codec, container, discovered_at, is_deleted, deleted_at, last_enricher_checksum, etc. Child tables: AssetEditorial, AssetProbed, AssetStationOps, AssetRelationships, AssetSidecar, AssetTag, Marker, AssetProbed.
- **Enricher** — id, enricher_id, type (e.g. ffprobe), scope (ingest/playout), name, config. Referenced by collection.config['enrichers'] as list of {enricher_id, priority}.
- **PathMapping** — collection_uuid, plex_path, local_path (for resolving Plex paths to local paths).
- **DiscoveredItem** (in-memory) — path_uri, provider_key, raw_labels, last_modified, size, hash_sha256, editorial, probed, sidecar, source_payload.

There is no `Media` table; the single entity for playable content is `Asset`. Identity for “same file” is effectively `(collection_uuid, canonical_key_hash)`.

---

## Assumptions (Implicit in Current Code)

1. **One asset per (collection, canonical_key_hash)** — New discovery with same hash skips; existing asset is never updated in the main ingest loop. Only re-enrich (reprobe, apply enrichers) updates existing assets.
2. **Enrichers run inline** — No queue; enrichers block the ingest process. Slow enrichers (e.g. ffprobe on many files) make ingest slow.
3. **Enricher set is per collection** — Stored in `collection.config['enrichers']` and in `Enricher` rows; pipeline is built at ingest/re-enrich time from that config. No global “processor capability” registry that selects processors by target type.
4. **Canonical key is the only identity** — No separate (source_id, container_id, locator) tuple; canonical_key is derived from provider, collection, and item path/provider_key. Hash is used for deduplication and reconciliation.
5. **Reconciliation only on full collection ingest** — Scoped ingest (title/season/episode) does not run the “mark missing as deleted” step. Only when scope is “collection” and discovery returned at least one item are stale assets soft-deleted.
6. **No “media unavailable” state** — Assets are soft-deleted (is_deleted, deleted_at) when missing from discovery; there is no separate “unavailable” flag. Contracts describe “mark unavailable” as the desired behavior.
7. **Ingest is CLI-triggered only** — No scheduler or daemon invokes discovery or reconciliation. Horizon/playlist daemon does not run ingest.
8. **Single transaction** — Entire source ingest (all collections) or collection ingest runs in one transaction; commit is at the end. No intermediate commits or job handoff.
9. **Path resolution before enrichment** — Local path must be resolved so that enrichers (ffprobe, loudness) can read the file. PathMapping and AssetPathResolver are used for Plex→local; filesystem importer already provides file paths.
10. **Approval and state** — New assets are created with `state='new'`, `approved_for_broadcast=False`. Re-enrichment resets approval and state; promotion to `ready` requires `duration_ms` and state machine transition. No automatic approval by enrichers (INV-ASSET-APPROVAL-OPERATOR-ONLY-001).
