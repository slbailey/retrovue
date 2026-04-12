# INV-ENRICHER-OBSERVABILITY-001 — Per-enricher execution progress is queryable

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-DERIVATION` by ensuring every enricher execution produces a discrete, queryable record. Without per-enricher granularity, ProcessorJob is monolithic — operators cannot determine which enricher succeeded, which failed, and which is still pending for a given asset.

## Guarantee

Every enricher execution MUST produce a queryable record containing: enricher name, asset ID, execution status, enricher version, and timestamps (started_at, completed_at). Enricher progress MUST be retrievable per-asset with per-enricher granularity.

## Preconditions

- The enricher is registered in `ENRICHERS` and dispatched by the system.
- The asset exists in the catalog.

## Observability

- Per-enricher execution records are queryable by asset ID and enricher name.
- Each record includes status (pending, running, succeeded, failed), enricher version, and wall-clock timestamps.
- Structured log event emitted on enricher execution start and completion.

## Deterministic Testability

1. Configure a pipeline with multiple enrichers (e.g. FFprobe, Loudness, InterstitialType).
2. Execute the pipeline against a single asset.
3. Assert that one execution record exists per enricher per asset.
4. Assert each record contains enricher name, asset ID, status, version, started_at, and completed_at.
5. Assert that records are independently queryable — retrieving FFprobe status does not require loading the entire ProcessorJob.

## Failure Semantics

**Planning fault.** Without per-enricher records, operators cannot diagnose partial enrichment failures or determine which enricher needs re-execution.

## Required Tests

- `server/tests/contracts/ingest/test_inv_enricher_observability.py`

## Enforcement Evidence

- `EnricherRun` model: `server/src/retrovue/domain/entities.py`
- Runtime wiring: `server/src/retrovue/catalog/processor_runtime.py` (execute_job creates EnricherRun per enricher)
- Progress query: `server/src/retrovue/catalog/enrichment_progress.py`
- Migration: `server/alembic/versions/20260409_create_enricher_runs.py`
