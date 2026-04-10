# INV-TAG-BULK-REMOVE-001 — Bulk tag removal is atomic and palette-independent

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring bulk tag removal deletes a tag from all assets atomically. Partial removal leaves some assets with a tag the operator believed was fully removed, causing silent scheduling drift. The palette is display-only and MUST NOT be affected by bulk removal.

## Guarantee

Bulk tag removal MUST delete all `asset_tags` rows for the specified tag in a single transaction. The tag palette MUST NOT be modified by bulk removal — palette entries are display-only metadata managed separately by operators.

## Preconditions

- Tag value is canonicalized via `canonicalize_tag()`.

## Observability

After bulk_remove(tag): `SELECT COUNT(*) FROM asset_tags WHERE tag = <tag>` MUST return zero. Palette entry for the tag, if it existed before removal, MUST still exist unchanged.

## Deterministic Testability

1. Insert N assets with the target tag and at least one other tag.
2. Insert a palette entry for the target tag.
3. Execute bulk_remove(target tag).
4. Assert zero rows with the target tag in `asset_tags`.
5. Assert other tags on those assets are unaffected.
6. Assert palette entry for the target tag still exists.

## Failure Semantics

**Planning fault.** Partial removal leaves stale tag associations, causing incorrect pool resolution.

## Required Tests

- `pkg/core/tests/contracts/test_tag_management_api.py`
- `pkg/core/tests/contracts/test_tag_management_operations.py`

## Enforcement Evidence

TODO
