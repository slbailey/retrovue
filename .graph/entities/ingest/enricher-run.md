# Enricher Run

**Domain:** ingest  
**Slug:** `enricher-run`

## What it represents

A **per-enricher execution record** for a single enricher against a single asset. Provides queryable, per-enricher granularity that the monolithic ProcessorJob does not expose.

## Lifecycle phase

**Transient → Persisted**; created when an enricher execution starts, updated on completion or failure.

## Owning domain

ingest

## Key fields

- `enricher_name` — which enricher ran (e.g. `ffprobe`, `loudness`, `interstitial_type`)
- `asset_id` — the target asset
- `status` — `pending`, `running`, `succeeded`, `failed`
- `version` — the enricher version that produced the result
- `started_at`, `completed_at` — wall-clock timestamps

## What depends on it

Operator diagnostics, targeted re-enrichment queries, version-based staleness detection.

## What produces it

Enrichment pipeline during enricher dispatch (per `INV-ENRICHER-OBSERVABILITY-001`).

## What must NOT be assumed

- That enricher-run replaces ProcessorJob — it is a per-enricher view, not a replacement for the job-level record.
- That all enricher-runs for an asset complete atomically — each enricher runs independently.
