# INV-ASSET-SCHEDULABLE-TRIPLE-GATE-001 — Schedulability requires three conditions

Status: Invariant
Authority Level: Planning
Derived From: `LAW-ELIGIBILITY`

## Purpose

Schedulability is the gate between the asset catalog and the planning pipeline. If any single condition is relaxed, content reaches air that is either technically incomplete (`state != 'ready'`), editorially unapproved (`approved_for_broadcast = false`), or administratively removed (`is_deleted = true`).

## Guarantee

An asset is schedulable IFF ALL three conditions hold simultaneously:

1. `state = 'ready'`
2. `approved_for_broadcast = TRUE`
3. `is_deleted = FALSE`

No subset of these conditions is sufficient. No other condition may make an asset schedulable.

## Preconditions

None. This invariant holds unconditionally for all asset library queries.

## Observability

Enforced by the partial index `ix_assets_schedulable` and by the `get_filler_assets()` query filter in `DatabaseAssetLibrary`. Only assets matching all three conditions appear in query results.

## Deterministic Testability

Construct asset stubs for all eight combinations of the three boolean conditions. Assert that only the combination `(ready, approved, not-deleted)` passes the schedulability predicate. No real database required.

## Failure Semantics

**Eligibility fault.** A query returned an asset that does not meet all three conditions. This indicates a missing filter in the query or a corrupt partial index.

## Required Tests

- `pkg/core/tests/contracts/test_asset_invariants.py::TestInvAssetSchedulableTripleGate001`

## Enforcement Evidence

- `pkg/core/src/retrovue/domain/entities.py` — partial index `ix_assets_schedulable`: `state = 'ready' AND approved_for_broadcast = true AND is_deleted = false`
- `pkg/core/src/retrovue/catalog/db_asset_library.py` — `get_filler_assets()` applies all three filters
- Error tag: `INV-ASSET-SCHEDULABLE-TRIPLE-GATE-001-VIOLATED`
