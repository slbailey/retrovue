# INV-ASSET-SOFTDELETE-SYNC-001 — Soft-delete flag and timestamp always in sync

Status: Invariant
Authority Level: Planning
Derived From: —

## Purpose

The soft-delete mechanism uses two columns: a boolean flag (`is_deleted`) for fast query filtering and a timestamp (`deleted_at`) for audit trail. If these diverge, queries may return deleted assets or hide live assets, and audit timestamps become unreliable.

## Guarantee

`is_deleted = TRUE` MUST imply `deleted_at IS NOT NULL`. `is_deleted = FALSE` MUST imply `deleted_at IS NULL`. The two columns MUST always be in sync.

## Preconditions

None. This invariant holds unconditionally.

## Observability

Enforced at the database layer via CHECK constraint `chk_deleted_at_sync`. Any INSERT or UPDATE violating this relationship MUST raise a constraint-violation error with tag `INV-ASSET-SOFTDELETE-SYNC-001-VIOLATED`.

## Deterministic Testability

Construct asset stubs with all four combinations of `(is_deleted, deleted_at)`. Assert that only `(True, timestamp)` and `(False, None)` pass validation. No real database required.

## Failure Semantics

**Data integrity fault.** Code set `is_deleted` without updating `deleted_at` or vice versa. This indicates a missing helper or direct column mutation bypassing the soft-delete method.

## Required Tests

- `pkg/core/tests/contracts/test_asset_invariants.py::TestInvAssetSoftdeleteSync001`

## Enforcement Evidence

- `pkg/core/src/retrovue/domain/entities.py` — CHECK constraint `chk_deleted_at_sync`: `(is_deleted = TRUE AND deleted_at IS NOT NULL) OR (is_deleted = FALSE AND deleted_at IS NULL)`
- Error tag: `INV-ASSET-SOFTDELETE-SYNC-001-VIOLATED`
