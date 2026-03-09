# INV-INTERSTITIAL-TYPE-STAMP-001

## Statement

Every asset ingested from a filesystem interstitial source MUST have
`editorial.interstitial_type` set to a canonical interstitial type during
ingest. The type is determined by the collection name, not by the asset's
file path or content.

## Canonical Interstitial Types

The following are the only recognized canonical interstitial types:

| Type          | Description                          |
|---------------|--------------------------------------|
| `commercial`  | Paid advertising spot                |
| `promo`       | Network/channel promotional content  |
| `psa`         | Public service announcement          |
| `bumper`      | Short transition element             |
| `station_id`  | Station identification               |
| `trailer`     | Movie or show trailer                |
| `teaser`      | Short teaser/preview                 |
| `shortform`   | Short-form interstitial content      |
| `filler`      | Generic fill material                |

## Collection Name → Canonical Type Mapping

The mapping from filesystem collection directory name to canonical type is:

| Collection name | Canonical type |
|-----------------|---------------|
| `bumpers`       | `bumper`       |
| `commercials`   | `commercial`   |
| `promos`        | `promo`        |
| `psas`          | `psa`          |
| `station_ids`   | `station_id`   |
| `trailers`      | `trailer`      |
| `teasers`       | `teaser`       |
| `shortform`     | `shortform`    |
| `oddities`      | `filler`       |

This mapping is authoritative. It is applied during ingest by the
`InterstitialTypeEnricher`.

## Failure Behavior

If a collection name does not appear in the mapping table and cannot be
resolved to a canonical type, the enricher MUST raise an error. Silent
fallback to `filler` is NOT allowed. The operator must either:

1. Add the collection name to the mapping, or
2. Rename the directory to match a recognized name

This prevents assets from entering the system with incorrect types that
would silently pollute traffic selection.

## Architectural Boundary

- **TrafficManager** and **TrafficPolicy** operate ONLY on canonical
  interstitial types. They MUST NEVER reference collection names, source
  names, filesystem paths, or any storage-layer concept.

- **DatabaseAssetLibrary** queries assets by `interstitial_type` field
  in `AssetEditorial.payload` using JSONB `has_key`:
  ```sql
  WHERE asset_editorial.payload ? 'interstitial_type'
  ```
  It MUST NOT query by collection name or collection UUID. Collection
  topology is invisible to the traffic layer.

- **AssetLibrary** is the single abstraction boundary between
  TrafficManager and storage layout. Everything below (collections,
  sources, paths, inference rules) is invisible to traffic.

- The mapping from collection name to canonical type lives in the ingest
  layer (`InterstitialTypeEnricher`), not in TrafficManager or AssetLibrary.

## Re-enrichment Path

- `apply_enrichers_to_collection()` MUST auto-inject
  `InterstitialTypeEnricher` for collections whose name appears in
  `COLLECTION_TYPE_MAP`, matching the ingest path.

- `apply_enrichers_to_collection()` MUST persist `item.editorial` into
  `AssetEditorial.payload`. Enrichers that stamp editorial fields (like
  `InterstitialTypeEnricher`) would otherwise have their output silently
  dropped.

- To stamp existing assets: `retrovue collection sync <name> --enrich-only`.

## Enricher Behavior

The `InterstitialTypeEnricher`:

1. Is constructed with a `collection_name` parameter
2. Applies the canonical mapping to determine `interstitial_type`
3. Stamps `editorial.interstitial_type` on each `DiscoveredItem`
4. Does NOT overwrite existing editorial fields (merge, not replace)
5. Raises `EnricherError` for unmapped collection names

## Affected Components

- `pkg/core/src/retrovue/adapters/enrichers/interstitial_type_enricher.py`
  — mapping table and enricher implementation
- `pkg/core/src/retrovue/catalog/db_asset_library.py`
  — reads `editorial.interstitial_type` for traffic candidate filtering
- `pkg/core/src/retrovue/runtime/traffic_manager.py`
  — operates on canonical types via TrafficPolicy, never touches collections
- `pkg/core/src/retrovue/adapters/importers/filesystem_importer.py`
  — existing `_infer_tags_from_path` still provides category tags; type
  authority moves to collection-level enricher

## Test Coverage

- `pkg/core/tests/contracts/test_interstitial_type_stamp.py`
  - Each known collection maps to the correct canonical type
  - Unknown collection raises error (no silent fallback)
  - Editorial merge preserves existing fields
  - All canonical types are covered by at least one collection
  - TrafficManager never references collection names
  - DatabaseAssetLibrary.get_filler_assets() does not use collection_uuid filter
  - DatabaseAssetLibrary.get_filler_assets() does not call collection lookup
  - DatabaseAssetLibrary.get_filler_assets() filters by interstitial_type
  - apply_enrichers_to_collection() auto-injects InterstitialTypeEnricher
  - apply_enrichers_to_collection() persists editorial into AssetEditorial

## Origin

Defined to enforce the architectural boundary between storage topology
(collections, directories) and editorial semantics (interstitial types)
used by the traffic system.
