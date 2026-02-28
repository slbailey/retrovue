# INV-ASSET-APPROVAL-OPERATOR-ONLY-001 — Approval is operator-only

Status: Invariant
Authority Level: Planning
Derived From: `LAW-ELIGIBILITY`

## Purpose

Broadcast approval is an editorial decision that requires human judgement. If the enrichment pipeline could auto-approve assets, content would reach air without operator review, violating the separation between automated technical processing and editorial control.

## Guarantee

`approved_for_broadcast` MUST be set to `TRUE` only by explicit operator action (via `asset_update.update_asset_review_status()`). The enrichment pipeline (`ingest_orchestrator.ingest_collection_assets()`) MUST NOT set `approved_for_broadcast = TRUE`.

## Preconditions

None. This invariant holds unconditionally for all enrichment pipeline executions.

## Observability

Verified by inspection: the enrichment pipeline code path MUST NOT contain any assignment of `approved_for_broadcast = True`. After enrichment completes, the asset MUST have `approved_for_broadcast = False`.

## Deterministic Testability

Simulate a full enrichment cycle with valid probe data. Assert that the resulting asset has `approved_for_broadcast = False` regardless of enrichment success. No real database required.

## Failure Semantics

**Authorization fault.** The enrichment pipeline set `approved_for_broadcast = True`, bypassing operator review. This indicates an unauthorized code path in the enrichment pipeline.

## Required Tests

- `pkg/core/tests/contracts/test_asset_invariants.py::TestInvAssetApprovalOperatorOnly001`

## Enforcement Evidence

- `pkg/core/src/retrovue/usecases/ingest_orchestrator.py` — enrichment pipeline never assigns `approved_for_broadcast = True`
- `pkg/core/src/retrovue/usecases/asset_update.py` — `update_asset_review_status()` is the sole approval path
- Error tag: `INV-ASSET-APPROVAL-OPERATOR-ONLY-001-VIOLATED`
