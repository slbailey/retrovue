# INV-ASSET-TAGS-PERSISTED-CORRECTLY-001

**Domain:** ingest

## Plain-language rule

Asset tags are persisted as queryable rows in `asset_tags` (not buried in JSONB). Each tag uses canonical form (`namespace.value`) and records its provenance source (ingest, operator, enricher).

## Why it exists

Tags drive pool resolution in scheduling. If tags are buried in JSONB, pool queries require full-table JSONB parsing instead of indexed lookups, and provenance is lost.

## What it constrains

- **Entity:** `asset` — tags stored in `AssetTag` table with composite PK (asset_uuid, tag).
- **Service:** all tag write paths — must use `canonicalize_tag()` before persistence (per `INV-TAG-CANONICAL-FORM-001`).

## Failure mode if violated

Pool resolution misses assets due to non-queryable or non-canonical tags. Tag provenance is lost, making audit impossible.
