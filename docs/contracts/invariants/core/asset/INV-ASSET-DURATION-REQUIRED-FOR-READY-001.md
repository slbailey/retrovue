# INV-ASSET-DURATION-REQUIRED-FOR-READY-001 — Duration required for ready state

Status: Invariant
Authority Level: Planning
Derived From: `LAW-ELIGIBILITY`

## Purpose

An asset without a valid duration cannot be scheduled into a time grid. Promoting such an asset to `ready` would create a false eligibility signal: the planning pipeline would select content of unknown length, producing invalid block plans with incorrect boundaries.

## Guarantee

An asset MUST have `duration_ms > 0` to transition to `state = 'ready'`. An asset with `duration_ms = None` or `duration_ms = 0` MUST remain in `state = 'new'`.

## Preconditions

The enrichment pipeline MUST have run and extracted a valid duration from the media file before promotion is attempted.

## Observability

Enforced in `asset_enrich.enrich_asset()` at the promotion gate (canonical enforcement point). `CollectionIngestService.ingest_collection()` creates all assets in `state = 'new'`; promotion to `ready` only occurs through `enrich_asset()`. Also enforced in `ingest_orchestrator.ingest_collection_assets()` (legacy path). Assets failing the duration check are logged at WARNING level and remain in `new` state.

## Deterministic Testability

Simulate enrichment completion with `duration_ms=1320000` and assert promotion to `ready`. Repeat with `duration_ms=None` and `duration_ms=0` and assert the asset remains in `new`. No real database or media files required.

## Failure Semantics

**Enrichment fault.** The probe enricher failed to extract a valid duration from the media file. The asset remains in `new` state for manual investigation or re-probe.

## Required Tests

- `pkg/core/tests/contracts/test_asset_invariants.py::TestInvAssetDurationRequiredForReady001`

## Enforcement Evidence

- `pkg/core/src/retrovue/usecases/asset_enrich.py` — `enrich_asset()` promotion gate (canonical enforcement point)
- `pkg/core/src/retrovue/usecases/ingest_orchestrator.py` — promotion guard (legacy path, unchanged in Phase 1)
- Error tag: `INV-ASSET-DURATION-REQUIRED-FOR-READY-001-VIOLATED`
