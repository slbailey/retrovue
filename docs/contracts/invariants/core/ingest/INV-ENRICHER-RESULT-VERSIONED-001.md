# INV-ENRICHER-RESULT-VERSIONED-001 — Persisted enricher results carry enricher version

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-DERIVATION` by ensuring every persisted enricher result includes the enricher version that produced it. Without version tracking, re-enrichment decisions cannot distinguish stale results from current ones, and enricher upgrades silently invalidate prior results with no detection path.

## Guarantee

Each persisted enricher result MUST include the version of the enricher that produced it. Re-running an enricher at the same version on the same asset MUST be idempotent (per `INV-ENRICHER-IDEMPOTENT-001`). Upgrading an enricher version MUST NOT require reprocessing all assets — stale results are identified by version comparison, not bulk invalidation.

## Preconditions

- The enricher produces an `EnrichmentResult` with a `version` field.
- The result is persisted to the enricher execution record (per `INV-ENRICHER-OBSERVABILITY-001`).

## Observability

- Each enricher execution record includes the enricher version that produced the result.
- Version mismatch between the current enricher version and the persisted result version is detectable by query.

## Deterministic Testability

1. Run enricher v1 against an asset. Assert the persisted record contains version=v1.
2. Run enricher v1 again against the same asset. Assert idempotent — no new record, same result.
3. Upgrade enricher to v2. Assert the persisted record still shows version=v1 (no automatic reprocessing).
4. Query for assets with enricher version < v2. Assert the stale asset is returned.
5. Re-run enricher v2 against the asset. Assert the persisted record now contains version=v2.

## Failure Semantics

**Planning fault.** Missing version on persisted results prevents targeted re-enrichment and forces expensive bulk reprocessing on enricher upgrades.

## Required Tests

- `pkg/core/tests/contracts/ingest/test_inv_enricher_result_versioned.py`

## Enforcement Evidence

- `EnricherRun.enricher_version` column: `pkg/core/src/retrovue/domain/entities.py`
- Runtime wiring: `pkg/core/src/retrovue/catalog/processor_runtime.py` (version stored on every EnricherRun)
- Stale version query: `pkg/core/src/retrovue/catalog/enrichment_progress.py` (get_stale_enricher_assets)
- Migration: `pkg/core/alembic/versions/20260409_create_enricher_runs.py`
