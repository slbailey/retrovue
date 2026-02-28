# INV-ASSET-MARKER-BOUNDS-001 — Marker timestamps within asset duration

Status: Invariant
Authority Level: Planning
Derived From: —

## Purpose

Markers annotate time ranges within an asset (chapters, availability windows, etc.). A marker with `start_ms < 0` or `end_ms > asset.duration_ms` references a time range outside the media file, producing invalid seek positions during playout and corrupting chapter-based scheduling decisions.

## Guarantee

Marker `start_ms` MUST be `>= 0`. Marker `end_ms` MUST be `<= asset.duration_ms`. A marker with timestamps exceeding the asset duration or negative timestamps MUST be rejected with `ValueError` and tag `INV-ASSET-MARKER-BOUNDS-001-VIOLATED`.

## Preconditions

The asset MUST have a valid `duration_ms > 0` before markers are validated against bounds.

## Observability

Enforced by `validate_marker_bounds(start_ms, end_ms, asset_duration_ms)` called during marker creation in the enrichment pipeline. Violations raise `ValueError` with the invariant tag.

## Deterministic Testability

Construct an asset stub with `duration_ms=1320000`. Create markers with `(start=0, end=30000)` and assert acceptance. Create markers with `(start=-1, end=30000)` and `(start=0, end=2000000)` and assert rejection. No real database or media files required.

## Failure Semantics

**Data integrity fault.** The probe enricher extracted chapter data with timestamps outside the asset duration. The marker MUST be rejected and logged for investigation.

## Required Tests

- `pkg/core/tests/contracts/test_asset_invariants.py::TestInvAssetMarkerBounds001`

## Enforcement Evidence

- `pkg/core/src/retrovue/domain/entities.py` — `validate_marker_bounds()` function
- `pkg/core/src/retrovue/usecases/ingest_orchestrator.py` — calls `validate_marker_bounds()` during chapter marker creation
- Error tag: `INV-ASSET-MARKER-BOUNDS-001-VIOLATED`
