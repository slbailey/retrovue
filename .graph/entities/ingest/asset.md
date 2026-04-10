# Asset

**Domain:** ingest  
**Slug:** `asset`

## What it represents

A **persisted catalog record** for a piece of media (or synthetic stand-in) with metadata, lifecycle state, and eligibility gates scheduling depends on.

## Lifecycle phase

**Persisted**; transitions through a strict state machine: `new` -> `enriching` -> `ready` -> `retired` (per `INV-ASSET-LIFECYCLE-COMPLETION-001`). Only legal transitions are permitted; `retired` is terminal.

## Owning domain

ingest

## Key fields

- `state` — lifecycle state (new, enriching, ready, retired)
- `approved_for_broadcast` — whether the asset can be scheduled (set by auto-approve or manual approval)
- `operator_verified` — human review flag
- `duration_ms`, `video_codec`, `audio_codec`, `container_format` — media metadata
- `tags` — queryable normalized tags via `AssetTag` table (per `INV-ASSET-TAGS-PERSISTED-CORRECTLY-001`)

## Key relationships

- `AssetTag` — many-to-one normalized tag association with provenance tracking
- `AssetEditorial` — JSONB + indexed columns (series_title, season_number, etc.)
- `AssetProbed`, `AssetStationOps`, `AssetRelationships`, `AssetSidecar` — one-to-one JSONB metadata
- `EnricherRun` — per-enricher execution history (per `INV-ENRICHER-OBSERVABILITY-001`)

## What depends on it

Scheduling pools (via `INV-CATALOG-READY-SCHEDULABLE-001`), eligibility, traffic fill, execution plans **after** resolution to concrete paths.

## What produces it

Importer pipeline from discovered items → validation pipeline (4 core validators per `INV-VALIDATOR-OUTPUT-SHAPE-001`) → auto-approve → enrichment.

## What must NOT be assumed

- That `ready` means enrichment is complete — enrichment is orthogonal to readiness (`INV-CATALOG-READY-SCHEDULABLE-001`).
- That enrichers may silently skip; failures must be visible (`INV-ENRICHER-MUST-EXECUTE-OR-FAIL-001`).
- That tags are in JSONB — tags are queryable rows in `asset_tags` (`INV-ASSET-TAGS-PERSISTED-CORRECTLY-001`).
