# INV-TAG-SCOPE-ALL-001 — Tag operations apply across all asset types

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring tag management operations (rename, merge, bulk remove) are not scoped to a single container type. Tags apply to movies, episodes, and interstitials uniformly. Operations that silently skip asset types corrupt pool resolution for the skipped types.

## Guarantee

Tag rename, merge, and bulk remove MUST affect all `asset_tags` rows matching the specified tag regardless of the asset's container type. The `scope=all` query parameter on the assets endpoint MUST return assets from all container types (excluding interstitials-only filtering).

## Preconditions

- Assets exist across multiple container types with the same tag.

## Observability

After any tag mutation, `SELECT COUNT(*) FROM asset_tags WHERE tag = <old>` MUST return zero across all container types. No container type is silently excluded from the operation.

## Deterministic Testability

1. Insert assets in distinct containers (movies, episodes, interstitials) all with tag A.
2. Execute rename(A, B).
3. Assert zero rows with tag A across all containers.
4. Assert all assets (regardless of container) now have tag B.

## Failure Semantics

**Planning fault.** Scoped-only operations leave orphaned tags in excluded container types, causing pool resolution to return stale results for those types.

## Required Tests

- `pkg/core/tests/contracts/test_tag_management_operations.py`

## Enforcement Evidence

TODO
