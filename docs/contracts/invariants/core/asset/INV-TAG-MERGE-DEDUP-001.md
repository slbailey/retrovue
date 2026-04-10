# INV-TAG-MERGE-DEDUP-001 — Tag merge deduplicates and fully removes source tag

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring tag merge operations fully transfer all asset associations from source to target without creating duplicates, and completely remove the source tag from the system. A partial merge leaves orphaned source tags or duplicate asset-tag rows, breaking pool resolution counts.

## Guarantee

Tag merge MUST move all assets from source tag to target tag within a single transaction. Assets that already carry the target tag MUST have their source tag row deleted (not duplicated). After merge, zero rows with the source tag MUST remain in `asset_tags`.

## Preconditions

- Source and target tag values are canonicalized via `canonicalize_tag()`.
- Source and target are distinct tags.

## Observability

After merge(source, target): `SELECT COUNT(*) FROM asset_tags WHERE tag = source` MUST return zero. The count of assets with target MUST equal the prior distinct union of assets that had source or target.

## Deterministic Testability

1. Insert assets: A with source only, B with target only, C with both.
2. Execute merge(source, target).
3. Assert zero rows with source tag.
4. Assert assets A, B, C all have target tag.
5. Assert no duplicate (asset_uuid, tag) rows exist.
6. Assert reported counts: affected = count(had source but not target), already_had_target = count(had both).

## Failure Semantics

**Planning fault.** Incomplete merge corrupts pool membership, causing duplicate or missing asset counts in scheduling.

## Required Tests

- `pkg/core/tests/contracts/test_tag_management_api.py`
- `pkg/core/tests/contracts/test_tag_management_operations.py`

## Enforcement Evidence

TODO
