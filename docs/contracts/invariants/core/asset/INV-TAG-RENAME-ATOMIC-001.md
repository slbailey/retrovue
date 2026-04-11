# INV-TAG-RENAME-ATOMIC-001 — Tag rename and merge operations are atomic

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring tag rename and merge operations complete fully or not at all. A partial rename leaves the catalog in an inconsistent state where some assets have the old tag and some have the new tag, breaking pool DSL resolution.

## Guarantee

Tag rename and tag merge operations MUST execute within a single database transaction. Either all affected `asset_tags` rows are updated and the SQLite palette is updated, or no changes are committed.

## Preconditions

- Both old and new tag values are canonicalized via `canonicalize_tag()` before mutation.
- Deduplication is handled within the same transaction: if an asset already has the target tag, the source tag row is deleted rather than updated.

## Observability

After a rename from tag A to tag B, `SELECT COUNT(*) FROM asset_tags WHERE tag = A` MUST return zero. The count of assets with tag B MUST equal the prior count of assets with tag A plus the prior count of assets with tag B, minus the overlap count.

## Deterministic Testability

1. Insert N assets with tag A, M assets with tag B, K assets with both A and B.
2. Execute rename(A → B).
3. Assert zero rows with tag A.
4. Assert (N + M - K) rows with tag B.
5. Simulate a mid-transaction failure and assert zero rows changed.

## Failure Semantics

**Planning fault.** Partial rename corrupts pool membership, causing scheduling to select wrong assets.

## Required Tests

- `server/tests/contracts/test_tag_management_api.py`
- `server/tests/contracts/test_tag_management_operations.py`

## Enforcement Evidence

TODO
