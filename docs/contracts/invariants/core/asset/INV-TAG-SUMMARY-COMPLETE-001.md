# INV-TAG-SUMMARY-COMPLETE-001 — Tag summary includes all tags and orphaned palette entries

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring the tag summary endpoint provides a complete view of all tags in the system, including palette entries with zero asset references. Incomplete summaries hide tags from operators, leading to stale or unreferenced tags accumulating silently.

## Guarantee

The tag summary MUST include every distinct tag in `asset_tags` grouped by namespace with accurate per-tag asset counts. Palette tags with zero asset references MUST appear in a separate orphaned list.

## Preconditions

- Tags in `asset_tags` are in canonical `namespace.value` form per `INV-TAG-CANONICAL-FORM-001`.

## Observability

The sum of all `asset_count` values across namespaces MUST equal `SELECT COUNT(*) FROM asset_tags`. Every tag in the palette that is not present in `asset_tags` MUST appear in the orphaned list.

## Deterministic Testability

1. Insert assets with known tags across multiple namespaces.
2. Insert palette entries for tags not assigned to any asset.
3. Call the summary endpoint.
4. Assert namespace grouping matches expected structure.
5. Assert orphaned list contains exactly the unassigned palette tags.

## Failure Semantics

**Planning fault.** Missing tags in summary prevent operators from discovering and managing stale tags.

## Required Tests

- `pkg/core/tests/contracts/test_tag_management_api.py`

## Enforcement Evidence

TODO
