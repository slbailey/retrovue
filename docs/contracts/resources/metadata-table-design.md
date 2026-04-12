# Metadata Table Design Note

**Status:** Accepted
**Reviewed by:** Metadata Engineer (RETA-131)
**Date:** 2026-04-09

## Summary

The 5-table asset metadata design is intentional and requires no consolidation.

## Tables

| Table | Role | Has Production Readers | Has Production Writers |
|---|---|---|---|
| `asset_editorial` | Editorial metadata (series, episode, rating, year). Indexed columns for pool filtering. | Yes (CatalogAssetResolver) | Yes (container_ingest, processor_runtime) |
| `asset_probed` | Technical probe results (codec, duration, loudness). | Yes (CatalogAssetResolver) | Yes (processor_runtime, container_ingest) |
| `asset_station_ops` | Station operations metadata (e.g., cue points, broadcast flags). | No | Write path exists but no enricher populates it yet. |
| `asset_relationships` | Inter-asset relationship metadata (e.g., series groupings, alternate versions). | No | Write path exists but no enricher populates it yet. |
| `asset_sidecar` | Supplementary sidecar metadata from adjacent JSON/YAML files. | No | Written via filesystem importer sidecar loading. |

## Design Rationale

The 5-table structure follows a **separation-by-provenance** model:

1. **Editorial** comes from content metadata sources (Plex, NFO files, operator input).
2. **Probed** comes from technical analysis (ffprobe, loudness measurement).
3. **Station Ops** comes from broadcast automation systems (future).
4. **Relationships** comes from catalog graph analysis (future).
5. **Sidecar** comes from file-adjacent metadata (JSON/YAML files discovered during filesystem import).

Each table has a single `payload` JSONB column keyed by `asset_uuid` (FK with CASCADE delete). This means:

- Each provenance source can be written independently without merge conflicts.
- Tables can be dropped or rebuilt independently during re-ingest.
- CASCADE delete ensures no orphaned metadata when an asset is removed.

## Why AssetSidecar is NOT a "canonical merged view"

Despite the original task description, AssetSidecar does not serve as a merged view of the other tables. It stores raw sidecar file contents from filesystem import. There is no merge or aggregation step that combines the other four tables into AssetSidecar. Each table stands independently.

## Why no consolidation is needed

1. **No redundancy.** Each table has a distinct provenance source. No data is duplicated across tables.
2. **No runtime cost.** StationOps, Relationships, and Sidecar tables are typically empty. They incur no query cost because no production code reads them.
3. **No schema complexity.** All five tables share an identical structure (UUID PK + JSONB payload), except Editorial which adds indexed columns per the metadata_consolidation contract.
4. **Forward compatibility.** The tables exist to receive metadata from enrichers and importers that will be built in the future. Consolidating now would require re-splitting later.

## Reference

- `docs/contracts/metadata_consolidation.md` -- Column extraction contract for AssetEditorial (explicitly scopes out the other four tables).
- `server/src/retrovue/domain/entities.py` lines 436-533 -- Table definitions.
- `server/src/retrovue/infra/metadata/persistence.py` -- Unified write path (`persist_asset_metadata`).
