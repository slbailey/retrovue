# INV-POOL-RESOLUTION-VISIBILITY-001 — Pool resolution produces per-filter exclusion diagnostics

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`

## Purpose

Protects `LAW-DERIVATION` by ensuring operators can determine why a pool resolved to zero (or fewer than expected) assets. Without per-filter diagnostics, silent exclusion forces trial-and-error debugging of tag, type, and editorial mismatches.

## Guarantee

When a pool query evaluates match criteria against the asset catalog, the resolver MUST be able to produce a `PoolDiagnostics` report containing:

- `total_considered`: count of assets entering the filter pipeline
- `excluded_by_type`: count excluded by type mismatch
- `excluded_by_tags`: count excluded by missing required tags
- `excluded_by_rating`: count excluded by rating filter
- `excluded_by_duration`: count excluded by min/max duration bounds
- `excluded_by_editorial`: count excluded by missing editorial fields (interstitial_type, series_title, etc.)
- `matched`: count of assets passing all filters
- `exclusion_reasons`: per-asset detail for excluded assets (asset_id → list of reason strings)

## Preconditions

- At least one asset exists in the catalog.
- The pool has registered match criteria.

## Observability

`query_with_diagnostics(match)` returns both the matched asset IDs and a `PoolDiagnostics` dataclass. Callers choose whether to log, surface via CLI, or discard.

## Deterministic Testability

Construct a catalog with assets carrying known deficiencies (missing tags, wrong type, missing editorial). Evaluate a pool with `query_with_diagnostics`. Assert that each exclusion category count matches the expected deficiency count. Assert that `exclusion_reasons` names the specific filter and missing value for each excluded asset.

## Failure Semantics

**Planning fault.** A resolver that cannot explain empty pool results forces operators to inspect raw catalog data manually.

## Required Tests

- `pkg/core/tests/contracts/test_pool_resolution_visibility.py`
- `pkg/core/tests/contracts/test_pool_diagnostics_integration.py`

## Enforcement Evidence

TODO
